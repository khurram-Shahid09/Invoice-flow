"""An invoice to generate: what is printed, plus the answer key (docs/13-testing-and-evals.md).

``Truth`` mirrors the extraction schema in docs/06-ai-extraction.md: a field is ``None`` when the
document doesn't show it, because that is what a correct extraction returns. ``Expected`` is
what the checks in docs/07 should decide for this invoice when processed on its own.
"""

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

CENT = Decimal("0.01")

Route = Literal["straight_through", "approval", "review"]
Kind = Literal["clean", "scan", "photo", "bad", "demo"]


def money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Line:
    description: str
    quantity: Decimal
    unit_price: Decimal
    product_code: str | None = None
    unit: str | None = None
    discount_pct: Decimal | None = None
    tax_rate_pct: Decimal | None = None  # set when the layout prints tax per line

    @property
    def total(self) -> Decimal:
        gross = self.quantity * self.unit_price
        if self.discount_pct:
            gross = gross * (1 - self.discount_pct / 100)
        return money(gross)


@dataclass(frozen=True)
class Party:
    name: str
    tax_id: str | None
    address: str | None
    email: str | None
    bank_name: str | None
    bank_account: str | None


@dataclass
class Invoice:
    """Everything a layout needs to print one invoice. Amounts are computed, never typed in."""

    case_id: str
    layout: str
    vendor: Party
    buyer: Party
    invoice_number: str
    invoice_date: date
    lines: list[Line]
    tax_rate: Decimal  # document-level rate (layouts that print tax per line use line rates)
    currency: str = "PKR"
    due_date: date | None = None
    payment_terms: str | None = None
    po_number: str | None = None
    shipping: Decimal | None = None
    notes: list[str] = field(default_factory=list)
    hidden_text: str | None = None  # white-on-white text, for the injection case
    total_override: Decimal | None = None  # a printed total that doesn't add up (MATH_TOTAL)
    pages: int = 1  # 2 = a second page with terms and bank details
    title: str = "INVOICE"

    @property
    def subtotal(self) -> Decimal:
        return money(sum((line.total for line in self.lines), start=Decimal(0)))

    @property
    def tax_total(self) -> Decimal:
        if all(line.tax_rate_pct is not None for line in self.lines):
            taxed = sum(
                (line.total * (line.tax_rate_pct or 0) / 100 for line in self.lines),
                start=Decimal(0),
            )
            return money(taxed)
        return money(self.subtotal * self.tax_rate / 100)

    @property
    def computed_total(self) -> Decimal:
        return money(self.subtotal + self.tax_total + (self.shipping or 0))

    @property
    def total(self) -> Decimal:
        """What the invoice prints as the total."""
        return self.total_override if self.total_override is not None else self.computed_total


@dataclass
class Expected:
    route: Route
    codes: list[str]  # the blocking/warning check codes that must appear (docs/07)
    note: str = ""
    after: list[str] = field(default_factory=list)  # cases to process first (duplicates)


@dataclass
class Case:
    invoice: Invoice
    kind: Kind
    expected: Expected
    file_format: Literal["pdf", "scan_pdf", "jpg"] = "pdf"
    filename: str = ""
    shows: dict[str, bool] = field(default_factory=dict)  # layout-dependent: which fields print

    @property
    def case_id(self) -> str:
        return self.invoice.case_id

    def truth(self) -> dict[str, Any]:
        """The correct extraction for this document (docs/06 schema, values normalised)."""
        inv, shows = self.invoice, self.shows

        def shown(name: str, value: Any) -> Any:
            return value if shows.get(name, True) else None

        def num(value: Decimal | None) -> str | None:
            return None if value is None else str(value)

        return {
            "document_type": "invoice",
            "vendor_name": inv.vendor.name,
            "vendor_tax_id": shown("vendor_tax_id", inv.vendor.tax_id),
            "vendor_address": shown("vendor_address", inv.vendor.address),
            "vendor_email": shown("vendor_email", inv.vendor.email),
            "bank_account": shown("bank_account", inv.vendor.bank_account),
            "bank_name": shown("bank_name", inv.vendor.bank_name),
            "invoice_number": inv.invoice_number,
            "invoice_date": inv.invoice_date.isoformat(),
            "due_date": inv.due_date.isoformat() if inv.due_date else None,
            "payment_terms": inv.payment_terms,
            "po_number": inv.po_number,
            "currency": inv.currency,
            "subtotal": num(inv.subtotal),
            "discount_total": None,
            "tax_total": num(inv.tax_total),
            "shipping": num(inv.shipping),
            "total": num(inv.total),
            "lines": [
                {
                    "description": line.description,
                    "product_code": shown("product_code", line.product_code),
                    "quantity": num(line.quantity),
                    "unit": shown("unit", line.unit),
                    "unit_price": num(line.unit_price),
                    "discount_pct": num(line.discount_pct),
                    "tax_rate_pct": num(line.tax_rate_pct),
                    "line_total": num(line.total),
                }
                for line in inv.lines
            ],
        }

    def manifest_entry(self) -> dict[str, Any]:
        return {
            "id": self.case_id,
            "kind": self.kind,
            "file": self.filename,
            "format": self.file_format,
            "layout": self.invoice.layout,
            "vendor": self.invoice.vendor.name,
            "has_text_layer": self.file_format == "pdf",
            "expected": asdict(self.expected),
        }
