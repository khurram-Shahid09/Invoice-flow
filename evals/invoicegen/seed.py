"""The Odoo seed (infra/odoo/seed_data.json) as the generator needs it.

Invoices are built from these vendors and purchase orders, so matching can be evaluated end to
end against the same data in Odoo or the fake ERP. PO numbers follow creation order (P00001 for
SEED-PO-01 ...), which is how both the Odoo seed and the fake ERP number them.
"""

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .model import Party

ROOT = Path(__file__).resolve().parents[2]
SEED_FILE = ROOT / "infra" / "odoo" / "seed_data.json"


def pk_iban(bank_code: str, account: str) -> str:
    """ISO 13616 checksum, same as infra/odoo/seed.py and erp/adapters/fake.py."""
    digits = "".join(str(int(c, 36)) for c in f"{bank_code}{account}PK00")
    return f"PK{98 - int(digits) % 97:02d}{bank_code}{account}"


@dataclass(frozen=True)
class Vendor:
    ref: str
    party: Party
    non_po: bool
    category: str


@dataclass(frozen=True)
class Product:
    code: str
    name: str
    price: Decimal
    service: bool


@dataclass(frozen=True)
class PoLine:
    product: Product
    ordered: Decimal
    received: Decimal  # services count as received in full (2-way match)
    price: Decimal


@dataclass(frozen=True)
class PurchaseOrder:
    key: str
    number: str
    vendor: Vendor
    lines: tuple[PoLine, ...]

    @property
    def received_any(self) -> bool:
        return any(line.received > 0 for line in self.lines)


@dataclass(frozen=True)
class Seed:
    buyer: Party
    vendors: dict[str, Vendor]
    products: dict[str, Product]
    purchase_orders: dict[str, PurchaseOrder]
    taxes: dict[str, Decimal]
    erp_bills: list[dict]


def load(path: Path = SEED_FILE) -> Seed:
    data = json.loads(path.read_text(encoding="utf-8"))
    company = data["company"]
    buyer = Party(
        name=company["name"],
        tax_id=company["vat"],
        address=f"{company['street']}, {company['city']}",
        email=company["email"],
        bank_name=None,
        bank_account=None,
    )
    vendors = {
        v["ref"]: Vendor(
            ref=v["ref"],
            party=Party(
                name=v["name"],
                tax_id=v["vat"],
                address=f"{v['city']}, Pakistan",
                email=v["email"],
                bank_name=v["bank"],
                bank_account=pk_iban(v["bank_code"], v["account"]),
            ),
            non_po=bool(v.get("non_po")),
            category=v["category"],
        )
        for v in data["vendors"]
    }
    products = {
        p["code"]: Product(p["code"], p["name"], Decimal(p["price"]), bool(p.get("service")))
        for p in data["products"]
    }
    purchase_orders = {}
    for n, po in enumerate(data["purchase_orders"], start=1):
        plan = po["receive"]
        lines = []
        for code, qty, price in po["lines"]:
            product = products[code]
            if product.service or plan == "full":
                received = qty
            elif plan == "none":
                received = 0
            else:
                received = plan.get(code, 0)
            lines.append(PoLine(product, Decimal(qty), Decimal(received), Decimal(price)))
        purchase_orders[po["key"]] = PurchaseOrder(
            po["key"], f"P{n:05d}", vendors[po["vendor"]], tuple(lines)
        )
    taxes = {kind: Decimal(t["amount"]) for kind, t in data["taxes"].items()}
    return Seed(buyer, vendors, products, purchase_orders, taxes, data["bills"])
