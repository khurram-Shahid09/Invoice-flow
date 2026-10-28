"""In-memory ERP for tests, evals and offline demos.

``FakeErp.from_seed()`` builds the same company, vendors, purchase orders and receipts that
infra/odoo/seed.py loads into Odoo, so everything downstream behaves the same without Odoo.
Tests change data by replacing records and bumping ``updated_at`` (see ``touch``).
"""

import json
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from django.conf import settings

from .base import (
    Account,
    BillRef,
    ConnectionInfo,
    PurchaseOrder,
    PurchaseOrderLine,
    Receipt,
    Tax,
    Vendor,
)

SEED_FILE = Path(settings.REPO_ROOT) / "infra" / "odoo" / "seed_data.json"
SEEDED_AT = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def pk_iban(bank_code: str, account: str) -> str:
    """Same IBAN the Odoo seed creates (ISO 13616 checksum)."""
    digits = "".join(str(int(c, 36)) for c in f"{bank_code}{account}PK00")
    return f"PK{98 - int(digits) % 97:02d}{bank_code}{account}"


def _changed[T: (Vendor, PurchaseOrder, Receipt, BillRef)](
    items: list[T], since: datetime | None
) -> list[T]:
    return [i for i in items if since is None or i.updated_at > since]


@dataclass
class FakeErp:
    company: str = "Fake Company"
    currency: str = "PKR"
    vendors: list[Vendor] = field(default_factory=list)
    purchase_orders: list[PurchaseOrder] = field(default_factory=list)
    receipts: list[Receipt] = field(default_factory=list)
    accounts: list[Account] = field(default_factory=list)
    taxes: list[Tax] = field(default_factory=list)
    bills: list[BillRef] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)  # for tests: which lists were requested

    def test_connection(self) -> ConnectionInfo:
        return ConnectionInfo("fake", self.company, self.currency, "fake-bot")

    def list_vendors(self, since: datetime | None = None) -> list[Vendor]:
        self.calls.append("vendors")
        return _changed(self.vendors, since)

    def list_purchase_orders(self, since: datetime | None = None) -> list[PurchaseOrder]:
        self.calls.append("purchase_orders")
        return _changed(self.purchase_orders, since)

    def list_receipts(self, since: datetime | None = None) -> list[Receipt]:
        self.calls.append("receipts")
        return _changed(self.receipts, since)

    def list_accounts(self) -> list[Account]:
        self.calls.append("accounts")
        return list(self.accounts)

    def list_taxes(self) -> list[Tax]:
        self.calls.append("taxes")
        return list(self.taxes)

    def list_bills(self, since: datetime | None = None) -> list[BillRef]:
        self.calls.append("bills")
        return _changed(self.bills, since)

    def touch[T: (Vendor, PurchaseOrder, Receipt, BillRef)](
        self, record: T, at: datetime, **changes
    ) -> T:
        """Replace ``record`` with a changed copy, as if it was edited in the ERP at ``at``."""
        updated = replace(record, updated_at=at, **changes)
        for collection in (self.vendors, self.purchase_orders, self.receipts, self.bills):
            for i, existing in enumerate(collection):
                if existing is record:
                    collection[i] = updated  # type: ignore[call-overload]
                    return updated
        raise ValueError("record is not in this fake ERP")

    @classmethod
    def from_seed(cls, path: Path = SEED_FILE) -> "FakeErp":
        data = json.loads(path.read_text(encoding="utf-8"))
        at = SEEDED_AT
        erp = cls(company=data["company"]["name"])
        vendor_ids: dict[str, str] = {}
        for n, v in enumerate(data["vendors"], start=1):
            vendor_ids[v["ref"]] = str(n)
            erp.vendors.append(
                Vendor(
                    erp_id=str(n),
                    name=v["name"],
                    ref=v["ref"],
                    tax_id=v["vat"],
                    email=v["email"],
                    city=v["city"],
                    currency="PKR",
                    bank_accounts=(pk_iban(v["bank_code"], v["account"]),),
                    active=True,
                    updated_at=at,
                )
            )

        rates = {kind: Decimal(t["amount"]) for kind, t in data["taxes"].items()}
        erp.taxes = [
            Tax(str(n), t["name"], Decimal(t["amount"]), True)
            for n, t in enumerate(data["taxes"].values(), start=1)
        ]
        products = {p["code"]: p for p in data["products"]}
        line_id = 0
        for n, po in enumerate(data["purchase_orders"], start=1):
            lines = []
            subtotal = tax_total = Decimal(0)
            for code, qty, price in po["lines"]:
                line_id += 1
                product = products[code]
                rate = rates["services" if product.get("service") else "goods"]
                plan = po["receive"]
                received = qty if plan == "full" else (0 if plan == "none" else plan.get(code, 0))
                if product.get("service"):
                    received = 0  # services aren't received into stock
                amount = Decimal(qty) * Decimal(price)
                subtotal += amount
                tax_total += amount * rate / 100
                lines.append(
                    PurchaseOrderLine(
                        erp_id=str(line_id),
                        product_code=code,
                        description=f"[{code}] {product['name']}",
                        uom="Units",
                        qty_ordered=Decimal(qty),
                        qty_received=Decimal(received),
                        qty_invoiced=Decimal(0),
                        unit_price=Decimal(price),
                        tax_rate=rate,
                    )
                )
            erp.purchase_orders.append(
                PurchaseOrder(
                    erp_id=str(n),
                    number=f"P{n:05d}",
                    vendor_erp_id=vendor_ids[po["vendor"]],
                    state="purchase",
                    currency="PKR",
                    vendor_ref=po["key"],
                    order_date=date(2026, 9, 15),
                    requester="Administrator",
                    amount_total=subtotal + tax_total,
                    updated_at=at,
                    lines=tuple(lines),
                )
            )
            if po["receive"] != "none":
                erp.receipts.append(Receipt(str(n), f"WH/IN/{n:05d}", str(n), "done", at, at))

        erp.accounts = [
            Account("1", "211000", "Account Payable", "liability_payable"),
            Account("2", "600000", "Expenses", "expense"),
            Account("3", "610100", "Internet & Telephone", "expense"),
            Account("4", "610200", "Electricity", "expense"),
            Account("5", "610300", "Cleaning Services", "expense"),
        ]
        for n, bill in enumerate(data["bills"], start=1):
            total = sum(
                (Decimal(q) * Decimal(p) for _, q, p in bill["lines"]), start=Decimal(0)
            ) * (1 + rates[bill["tax"]] / 100)
            erp.bills.append(
                BillRef(
                    erp_id=str(n),
                    vendor_erp_id=vendor_ids[bill["vendor"]],
                    ref=bill["ref"],
                    total=total,
                    currency="PKR",
                    bill_date=date.fromisoformat(bill["date"]),
                    state="posted",
                    updated_at=at,
                )
            )
        return erp
