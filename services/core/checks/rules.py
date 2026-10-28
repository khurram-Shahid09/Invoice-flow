"""Deterministic checks and the routing decision (docs/07, ADR-0001: AI reads, rules decide).

``run(invoice)`` links the invoice to its vendor and purchase order from the ERP mirror, runs
every rule, and returns the results plus the route: "review" (something blocks), "approval"
(a person must approve) or "straight_through" (clean and small enough to approve itself).
"""

from dataclasses import asdict, dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Literal

from django.conf import settings
from django.utils import timezone
from rapidfuzz import fuzz

from common import crypto
from common.text import normalize_tax_id
from erp.models import ErpBillRef, ErpPurchaseOrder, ErpPurchaseOrderLine, ErpVendor
from invoices.models import Invoice

RULES_VERSION = "2026.10.1"
MONEY_TOLERANCE = Decimal("0.05")
PRICE_TOLERANCE_PCT = Decimal(2)
PRICE_TOLERANCE_ABS = Decimal(1)
REQUIRED = ("vendor_name", "invoice_number", "invoice_date", "total")

Severity = Literal["info", "warning", "blocking"]


@dataclass
class Check:
    code: str
    severity: Severity
    message: str
    fields: list[str] = field(default_factory=list)


@dataclass
class Outcome:
    checks: list[Check]
    route: Literal["review", "approval", "straight_through"]
    reasons: list[str]
    vendor_matched_by: str = ""

    def as_json(self) -> tuple[list[dict], dict]:
        decision = {
            "route": self.route,
            "reasons": self.reasons,
            "vendor_matched_by": self.vendor_matched_by,
            "rules_version": RULES_VERSION,
        }
        return [asdict(c) for c in self.checks], decision


def _value(invoice: Invoice, name: str) -> str | None:
    return (invoice.fields.get(name) or {}).get("value")


def _dec(value: str | None) -> Decimal | None:
    return Decimal(value) if value not in (None, "") else None


def _money(value: Decimal) -> str:
    return f"{value:,.2f}"


def _line(line: dict, name: str) -> Decimal | None:
    return _dec((line.get(name) or {}).get("value"))


# --- Vendor ---


def _match_vendor(invoice: Invoice) -> tuple[ErpVendor | None, str]:
    vendors = ErpVendor.objects.for_org(invoice.org).filter(active=True)
    tax_id = _value(invoice, "vendor_tax_id")
    if tax_id:
        found = vendors.filter(tax_id_norm=normalize_tax_id(tax_id)).first()
        if found:
            return found, "tax_id"
    account = _value(invoice, "bank_account")
    if account:
        digest = crypto.blind_index(account, org_id=invoice.org_id)
        found = vendors.filter(bank_hashes__contains=[digest]).first()
        if found:
            return found, "bank_account"
    name = _value(invoice, "vendor_name")
    if name:
        scored = sorted(
            ((fuzz.token_set_ratio(name.lower(), v.name.lower()), v) for v in vendors),
            key=lambda pair: -pair[0],
        )
        if scored and scored[0][0] >= 92 and (len(scored) == 1 or scored[1][0] < 92):
            return scored[0][1], "name"
    return None, ""


# --- Purchase order ---


def _find_po(invoice: Invoice, vendor: ErpVendor) -> ErpPurchaseOrder | None:
    orders = ErpPurchaseOrder.objects.for_org(invoice.org).filter(vendor=vendor)
    printed = _value(invoice, "po_number")
    if printed:
        found = orders.filter(number__iexact=printed.strip()).first()
        if found:
            return found
    best, best_score = None, 0.0
    for po in orders.filter(state__in=["purchase", "done"]).prefetch_related("lines"):
        po_lines = list(po.lines.all())
        score = 0.0
        for line in invoice.lines:
            po_line = _match_line(line, po_lines)
            if po_line is None:
                continue
            score += 1
            # Tie-break between POs with the same items: prefer the one whose open quantity fits.
            qty = _line(line, "quantity") or Decimal(0)
            available = (po_line.qty_received or po_line.qty_ordered) - po_line.qty_invoiced
            score += 0.1 if qty == available else (0.01 if qty <= available else 0)
        score /= max(len(invoice.lines), 1)
        if score > best_score:
            best, best_score = po, score
    return best if best_score >= 0.8 else None


def _match_line(line: dict, po_lines: list[ErpPurchaseOrderLine]) -> ErpPurchaseOrderLine | None:
    code = ((line.get("product_code") or {}).get("value") or "").strip().upper()
    if code:
        for po_line in po_lines:
            if po_line.product_code.upper() == code:
                return po_line
    description = ((line.get("description") or {}).get("value") or "").lower()
    if description:
        scored = [(fuzz.token_set_ratio(description, p.description.lower()), p) for p in po_lines]
        scored.sort(key=lambda pair: -pair[0])
        if scored and scored[0][0] >= 85:
            return scored[0][1]
    return None


def _po_checks(invoice: Invoice, po: ErpPurchaseOrder, out: list[Check]) -> None:
    if po.state == "cancel":
        out.append(Check("PO_CLOSED", "blocking", f"Purchase order {po.number} is cancelled."))
        return
    po_lines = list(po.lines.all())
    for n, line in enumerate(invoice.lines, start=1):
        po_line = _match_line(line, po_lines)
        if po_line is None:
            out.append(
                Check(
                    "PO_LINE_UNMATCHED",
                    "blocking",
                    f"Line {n} isn't on purchase order {po.number}.",
                    [f"lines.{n}"],
                )
            )
            continue
        price, qty = _line(line, "unit_price"), _line(line, "quantity") or Decimal(0)
        if price is not None and po_line.unit_price:
            diff = price - po_line.unit_price
            pct = abs(diff) / po_line.unit_price * 100
            if pct > PRICE_TOLERANCE_PCT and abs(diff) > PRICE_TOLERANCE_ABS:
                direction = "above" if diff > 0 else "below"
                out.append(
                    Check(
                        "PO_PRICE_VARIANCE",
                        "blocking",
                        f"Line {n} price {_money(price)} is {pct:.1f}% {direction} the PO price {_money(po_line.unit_price)}.",
                        [f"lines.{n}.unit_price"],
                    )
                )
        billed = qty + po_line.qty_invoiced
        if billed > po_line.qty_ordered:
            out.append(
                Check(
                    "PO_QTY_OVER_ORDERED",
                    "blocking",
                    f"Line {n}: {billed:g} billed in total, {po_line.qty_ordered:g} ordered.",
                    [f"lines.{n}.quantity"],
                )
            )
        elif not po_line.is_service:
            if po_line.qty_received == 0:
                out.append(
                    Check(
                        "GRN_PENDING",
                        "blocking",
                        f"Line {n}: the goods haven't been received yet.",
                        [f"lines.{n}"],
                    )
                )
            elif billed > po_line.qty_received:
                out.append(
                    Check(
                        "GRN_QTY_OVER_RECEIVED",
                        "blocking",
                        f"Line {n}: {billed:g} billed, only {po_line.qty_received:g} received.",
                        [f"lines.{n}.quantity"],
                    )
                )


# --- Rules ---


def _math(invoice: Invoice, out: list[Check]) -> None:
    lines_total = Decimal(0)
    for n, line in enumerate(invoice.lines, start=1):
        qty, price, amount = (
            _line(line, "quantity"),
            _line(line, "unit_price"),
            _line(line, "line_total"),
        )
        if None in (qty, price, amount):
            continue
        assert qty is not None and price is not None and amount is not None
        rate = _line(line, "tax_rate_pct") or Decimal(0)
        net = qty * price
        if (
            abs(net - amount) > MONEY_TOLERANCE
            and abs(net * (1 + rate / 100) - amount) > MONEY_TOLERANCE
        ):
            out.append(
                Check(
                    "MATH_LINE",
                    "blocking",
                    f"Line {n}: {qty:g} × {_money(price)} isn't {_money(amount)}.",
                    [f"lines.{n}.line_total"],
                )
            )
        lines_total += net
    subtotal, tax = _dec(_value(invoice, "subtotal")), _dec(_value(invoice, "tax_total"))
    shipping, total = (
        _dec(_value(invoice, "shipping")) or Decimal(0),
        _dec(_value(invoice, "total")),
    )
    if subtotal is not None and invoice.lines and abs(lines_total - subtotal) > MONEY_TOLERANCE:
        out.append(
            Check(
                "MATH_SUBTOTAL",
                "blocking",
                f"Lines add up to {_money(lines_total)}, the subtotal says {_money(subtotal)}.",
                ["subtotal"],
            )
        )
    if subtotal is not None and tax is not None and total is not None:
        expected = subtotal + tax + shipping
        if abs(expected - total) > MONEY_TOLERANCE:
            out.append(
                Check(
                    "MATH_TOTAL",
                    "blocking",
                    f"Subtotal + tax{' + shipping' if shipping else ''} = {_money(expected)}, but the total says {_money(total)}.",
                    ["total"],
                )
            )


def _duplicates(invoice: Invoice, vendor: ErpVendor, out: list[Check]) -> None:
    number = invoice.invoice_number_norm
    others = (
        Invoice.objects.for_org(invoice.org)
        .filter(vendor=vendor)
        .exclude(pk=invoice.pk)
        .exclude(status=Invoice.Status.REJECTED)
    )
    bills = ErpBillRef.objects.for_org(invoice.org).filter(vendor=vendor).exclude(state="cancel")
    if number:
        twin = others.filter(invoice_number_norm=number).first()
        if twin:
            out.append(
                Check(
                    "DUP_EXACT",
                    "blocking",
                    f"Already received as {twin.invoice_number} ({twin.get_status_display().lower()}).",
                    ["invoice_number"],
                )
            )
            return
        bill = bills.filter(ref_norm=number).first()
        if bill:
            out.append(
                Check(
                    "DUP_EXACT",
                    "blocking",
                    f"Already in the ERP as bill {bill.ref} ({bill.state}).",
                    ["invoice_number"],
                )
            )
            return
    if invoice.total is None or invoice.invoice_date is None:
        return
    low, high = invoice.total * Decimal("0.995"), invoice.total * Decimal("1.005")
    near = (invoice.invoice_date - timedelta(days=7), invoice.invoice_date + timedelta(days=7))
    twin = others.filter(total__range=(low, high), invoice_date__range=near).first()
    bill = bills.filter(total__range=(low, high), bill_date__range=near).first()
    if twin or bill:
        ref = twin.invoice_number if twin else bill.ref  # type: ignore[union-attr]
        out.append(
            Check(
                "DUP_FUZZY",
                "blocking",
                f"Same amount within a week of {ref}: possibly the same invoice renumbered.",
                ["total", "invoice_date"],
            )
        )


def _iban_valid(value: str) -> bool:
    iban = crypto.normalize_account(value)
    if not (len(iban) > 15 and iban[:2].isalpha() and iban[2:4].isdigit()):
        return True  # not an IBAN: nothing to verify
    digits = "".join(str(int(c, 36)) for c in iban[4:] + iban[:4])
    return int(digits) % 97 == 1


def run(invoice: Invoice) -> Outcome:
    out: list[Check] = []
    org = invoice.org
    for name in REQUIRED:
        if _value(invoice, name) is None:
            out.append(
                Check(
                    "REQ_FIELDS",
                    "blocking",
                    f"{name.replace('_', ' ').capitalize()} is missing or couldn't be verified on the page.",
                    [name],
                )
            )
    _math(invoice, out)

    today = timezone.localdate()
    if invoice.invoice_date and invoice.invoice_date > today + timedelta(days=1):
        out.append(
            Check(
                "DATE_FUTURE",
                "blocking",
                f"Invoice date {invoice.invoice_date:%d %b %Y} is in the future.",
                ["invoice_date"],
            )
        )
    elif invoice.invoice_date and invoice.invoice_date < today - timedelta(days=365):
        out.append(
            Check("DATE_OLD", "warning", "Invoice is more than a year old.", ["invoice_date"])
        )

    if invoice.document.hidden_text:
        out.append(
            Check(
                "HIDDEN_TEXT",
                "warning",
                "The PDF contains invisible text; it was ignored. Check the document.",
                [],
            )
        )
    rejected = [
        n for n, f in invoice.fields.items() if f.get("grounding") in ("none", "unparseable")
    ]
    if rejected:
        out.append(
            Check(
                "NOT_GROUNDED",
                "info",
                f"Not found on the page, so not used: {', '.join(rejected)}.",
                rejected,
            )
        )

    vendor, matched_by = _match_vendor(invoice)
    invoice.vendor, invoice.po = vendor, None
    po = None
    if vendor is None:
        out.append(
            Check(
                "VENDOR_UNKNOWN",
                "blocking",
                f"{_value(invoice, 'vendor_name') or 'The vendor'} isn't in the vendor master.",
                ["vendor_name"],
            )
        )
    else:
        account = _value(invoice, "bank_account")
        if account and not _iban_valid(account):
            out.append(
                Check(
                    "BANK_INVALID",
                    "blocking",
                    "The IBAN's check digits are wrong.",
                    ["bank_account"],
                )
            )
        elif (
            account
            and vendor.bank_hashes
            and crypto.blind_index(account, org_id=org.id) not in vendor.bank_hashes
        ):
            masks = ", ".join(vendor.bank_masks)
            out.append(
                Check(
                    "BANK_CHANGED",
                    "blocking",
                    f"Bank account {crypto.mask(account)} isn't the vendor's account on file ({masks}). Verify by phone before paying.",
                    ["bank_account"],
                )
            )
        if invoice.currency and vendor.currency and invoice.currency != vendor.currency:
            out.append(
                Check(
                    "CURRENCY_MISMATCH",
                    "blocking",
                    f"Billed in {invoice.currency}; {vendor.name} bills in {vendor.currency}.",
                    ["currency"],
                )
            )
        _duplicates(invoice, vendor, out)
        if vendor.non_po:
            if not ErpBillRef.objects.for_org(org).filter(vendor=vendor).exists():
                out.append(
                    Check(
                        "ACCOUNT_SUGGESTED",
                        "warning",
                        "First bill from this vendor: confirm the expense account.",
                        [],
                    )
                )
        else:
            po = _find_po(invoice, vendor)
            invoice.po = po
            if po is None:
                out.append(
                    Check(
                        "PO_NOT_FOUND",
                        "blocking",
                        "No matching purchase order found for this vendor.",
                        ["po_number"],
                    )
                )
            else:
                _po_checks(invoice, po, out)

    blocking = [c for c in out if c.severity == "blocking"]
    warnings = [c for c in out if c.severity == "warning"]
    limit = Decimal(
        str(org.settings.get("straight_through_limit", settings.STRAIGHT_THROUGH_LIMIT))
    )
    if blocking:
        return Outcome(out, "review", [c.message for c in blocking], matched_by)
    reasons = [c.message for c in warnings]
    if matched_by == "name":
        reasons.append("Vendor matched by name only.")
    if invoice.total is not None and invoice.total > limit:
        reasons.append(f"Above the {_money(limit)} {org.base_currency} straight-through limit.")
    if reasons:
        return Outcome(out, "approval", reasons, matched_by)
    return Outcome(out, "straight_through", ["All checks passed and under the limit."], matched_by)
