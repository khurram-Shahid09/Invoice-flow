"""Seed the local Odoo with the demo company, vendors, products, purchase orders and receipts.

Creates the database on first run, installs Purchase, Inventory and Invoicing, then loads
infra/odoo/seed_data.json. Safe to run again: existing records are found by their keys and
left alone. Finally it creates InvoiceFlow's least-privilege API user and stores its secret
in the repo-root .env (ODOO_API_KEY), so the secret is never printed.

    docker compose -f infra/docker-compose.yml --profile erp up -d
    cd services/core && uv run python ../../infra/odoo/seed.py

Settings come from .env: ODOO_URL, ODOO_DB, ODOO_ADMIN_PASSWORD, ODOO_API_USER.
"""

from __future__ import annotations

import json
import secrets
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
DATA = json.loads((Path(__file__).with_name("seed_data.json")).read_text(encoding="utf-8"))
ENV_FILE = ROOT / ".env"
# The local container's database-manager password (Odoo's default). Never expose this Odoo.
MASTER_PASSWORD = "admin"  # noqa: S105


def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.split(" #")[0].strip()
    return values


def save_env(key: str, value: str) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            comment = line[line.index("#") :] if "#" in line else ""
            lines[i] = f"{key}={value}  {comment}".rstrip()
            break
    else:
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def pk_iban(bank_code: str, account: str) -> str:
    """A valid Pakistani IBAN (ISO 13616 checksum) for a fictional bank account."""
    body = f"{bank_code}{account}PK00"
    digits = "".join(str(int(c, 36)) for c in body)
    return f"PK{98 - int(digits) % 97:02d}{bank_code}{account}"


class Odoo:
    def __init__(self, url: str) -> None:
        self.http = httpx.Client(base_url=url, timeout=600)
        self.db = ""
        self.uid = 0
        self.password = ""

    def rpc(self, service: str, method: str, *args: Any) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": list(args)},
            "id": 1,
        }
        body = self.http.post("/jsonrpc", json=payload).json()
        if "error" in body:
            data = body["error"].get("data", {})
            raise RuntimeError(data.get("message") or body["error"].get("message"))
        return body["result"]

    def login(self, db: str, login: str, password: str) -> None:
        self.db, self.password = db, password
        self.uid = self.rpc("common", "authenticate", db, login, password, {})
        if not self.uid:
            sys.exit(f"Odoo rejected the login for {login!r} in database {db!r}.")

    def call(self, model: str, method: str, *args: Any, **kwargs: Any) -> Any:
        return self.rpc(
            "object",
            "execute_kw",
            self.db,
            self.uid,
            self.password,
            model,
            method,
            list(args),
            kwargs,
        )

    def find(self, model: str, domain: list, **kwargs: Any) -> list[int]:
        return self.call(model, "search", domain, **kwargs)

    def ensure(self, model: str, domain: list, values: dict) -> int:
        found = self.find(model, domain, limit=1)
        return found[0] if found else self.call(model, "create", values)

    def xmlid(self, module: str, name: str) -> int:
        rows = self.call(
            "ir.model.data",
            "search_read",
            [("module", "=", module), ("name", "=", name)],
            fields=["res_id"],
        )
        return rows[0]["res_id"]


def wait_for_odoo(odoo: Odoo) -> None:
    for _ in range(90):
        try:
            odoo.rpc("common", "version")
            return
        except (httpx.HTTPError, ValueError):
            time.sleep(2)
    sys.exit(
        "Odoo is not answering. Start it: docker compose -f infra/docker-compose.yml --profile erp up -d"
    )


def create_database(odoo: Odoo, db: str, admin_password: str) -> None:
    if db in odoo.rpc("db", "list"):
        return
    print(f"Creating database {db!r} (Pakistan, PKR)...")
    odoo.rpc(
        "db",
        "create_database",
        MASTER_PASSWORD,
        db,
        False,
        "en_US",
        admin_password,
        "admin",
        "pk",
        "",
    )


def install_apps(odoo: Odoo) -> None:
    names = ["purchase", "stock", "account"]
    missing = odoo.find("ir.module.module", [("name", "in", names), ("state", "!=", "installed")])
    if missing:
        print("Installing Purchase, Inventory and Invoicing (a few minutes)...")
        odoo.call("ir.module.module", "button_immediate_install", missing)


def setup_company(odoo: Odoo) -> int:
    company = DATA["company"]
    company_id = odoo.find("res.company", [], limit=1, order="id")[0]
    odoo.call(
        "res.company",
        "write",
        [company_id],
        {k: company[k] for k in ("name", "vat", "street", "city", "email")},
    )
    return company_id


def setup_taxes(odoo: Odoo, company_id: int) -> dict[str, int]:
    taxes = {}
    for kind, tax in DATA["taxes"].items():
        taxes[kind] = odoo.ensure(
            "account.tax",
            [("name", "=", tax["name"]), ("company_id", "=", company_id)],
            {
                "name": tax["name"],
                "amount": tax["amount"],
                "amount_type": "percent",
                "type_tax_use": "purchase",
                "company_id": company_id,
            },
        )
    return taxes


def setup_vendors(odoo: Odoo) -> dict[str, int]:
    vendors = {}
    for v in DATA["vendors"]:
        partner = odoo.ensure(
            "res.partner",
            [("ref", "=", v["ref"])],
            {
                "name": v["name"],
                "ref": v["ref"],
                "vat": v["vat"],
                "city": v["city"],
                "email": v["email"],
                "is_company": True,
                "supplier_rank": 1,
            },
        )
        bank = odoo.ensure(
            "res.bank",
            [("name", "=", v["bank"])],
            {"name": v["bank"], "bic": f"{v['bank_code']}PKKA"},
        )
        iban = pk_iban(v["bank_code"], v["account"])
        odoo.ensure(
            "res.partner.bank",
            [("acc_number", "=", iban)],
            {"acc_number": iban, "partner_id": partner, "bank_id": bank},
        )
        vendors[v["ref"]] = partner
    return vendors


def setup_products(odoo: Odoo, taxes: dict[str, int]) -> dict[str, int]:
    products = {}
    for p in DATA["products"]:
        service = p.get("service", False)
        products[p["code"]] = odoo.ensure(
            "product.product",
            [("default_code", "=", p["code"])],
            {
                "name": p["name"],
                "default_code": p["code"],
                "type": "service" if service else "consu",
                "is_storable": not service,
                "standard_price": p["price"],
                "purchase_method": "purchase" if service else "receive",
                "supplier_taxes_id": [(6, 0, [taxes["services" if service else "goods"]])],
            },
        )
    return products


def setup_purchase_orders(odoo: Odoo, vendors: dict[str, int], products: dict[str, int]) -> None:
    for po in DATA["purchase_orders"]:
        if odoo.find("purchase.order", [("partner_ref", "=", po["key"])]):
            continue
        order = odoo.call(
            "purchase.order",
            "create",
            {
                "partner_id": vendors[po["vendor"]],
                "partner_ref": po["key"],
                "order_line": [
                    (0, 0, {"product_id": products[code], "product_qty": qty, "price_unit": price})
                    for code, qty, price in po["lines"]
                ],
            },
        )
        odoo.call("purchase.order", "button_confirm", [order])
        receive(odoo, order, po["receive"])
        print(f"  {po['key']}: confirmed, received {po['receive']}")


def receive(odoo: Odoo, order: int, plan: str | dict) -> None:
    """Validate the incoming shipment fully, partly (a backorder keeps the rest) or not at all."""
    if plan == "none":
        return
    pickings = odoo.find(
        "stock.picking", [("purchase_id", "=", order), ("state", "not in", ("done", "cancel"))]
    )
    for picking in pickings:
        moves = odoo.call(
            "stock.move",
            "search_read",
            [("picking_id", "=", picking)],
            fields=["product_id", "product_uom_qty"],
        )
        for move in moves:
            code = odoo.call("product.product", "read", [move["product_id"][0]], ["default_code"])[
                0
            ]["default_code"]
            qty = move["product_uom_qty"] if plan == "full" else plan.get(code, 0)
            odoo.call("stock.move", "write", [move["id"]], {"quantity": qty, "picked": True})
        result = odoo.call("stock.picking", "button_validate", [picking])
        if isinstance(result, dict) and result.get("res_model") == "stock.backorder.confirmation":
            # Partial receipt: confirm creating a backorder for what hasn't arrived.
            ctx = result.get("context", {})
            wizard = odoo.call("stock.backorder.confirmation", "create", {}, context=ctx)
            odoo.call("stock.backorder.confirmation", "process", [wizard], context=ctx)


def setup_bills(odoo: Odoo, vendors: dict[str, int], taxes: dict[str, int]) -> None:
    """Bills already in the ERP, so duplicate checks have something real to find."""
    for bill in DATA["bills"]:
        partner = vendors[bill["vendor"]]
        if odoo.find("account.move", [("partner_id", "=", partner), ("ref", "=", bill["ref"])]):
            continue
        move = odoo.call(
            "account.move",
            "create",
            {
                "move_type": "in_invoice",
                "partner_id": partner,
                "ref": bill["ref"],
                "invoice_date": bill["date"],
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": name,
                            "quantity": qty,
                            "price_unit": price,
                            "tax_ids": [(6, 0, [taxes[bill["tax"]]])],
                        },
                    )
                    for name, qty, price in bill["lines"]
                ],
            },
        )
        odoo.call("account.move", "action_post", [move])


def setup_api_user(odoo: Odoo, login: str, secret: str) -> None:
    """InvoiceFlow's own Odoo user: purchase and stock read access, bills, nothing else."""
    groups = [
        odoo.xmlid("base", "group_user"),
        odoo.xmlid("purchase", "group_purchase_user"),
        odoo.xmlid("stock", "group_stock_user"),
        odoo.xmlid("account", "group_account_invoice"),
    ]
    values = {
        "name": "InvoiceFlow AP bot",
        "login": login,
        "email": login,
        "groups_id": [(6, 0, groups)],
    }
    found = odoo.find("res.users", [("login", "=", login)])
    if found:
        odoo.call("res.users", "write", found, {**values, "password": secret})
    else:
        odoo.call("res.users", "create", {**values, "password": secret})


def main() -> None:
    env = read_env()
    url = env.get("ODOO_URL") or "http://localhost:8069"
    db = env.get("ODOO_DB") or "invoiceflow"
    admin_password = env.get("ODOO_ADMIN_PASSWORD", "")
    api_user = env.get("ODOO_API_USER") or "ap-bot@indus-retail.test"
    if len(admin_password) < 10:
        sys.exit("Set ODOO_ADMIN_PASSWORD (10+ characters) in .env first.")

    odoo = Odoo(url)
    wait_for_odoo(odoo)
    create_database(odoo, db, admin_password)
    odoo.login(db, "admin", admin_password)
    install_apps(odoo)
    company_id = setup_company(odoo)
    taxes = setup_taxes(odoo, company_id)
    vendors = setup_vendors(odoo)
    products = setup_products(odoo, taxes)
    print("Purchase orders:")
    setup_purchase_orders(odoo, vendors, products)
    setup_bills(odoo, vendors, taxes)

    secret = env.get("ODOO_API_KEY") or secrets.token_urlsafe(24)
    setup_api_user(odoo, api_user, secret)
    if not env.get("ODOO_API_KEY"):
        save_env("ODOO_API_KEY", secret)
    print(
        f"Done. Odoo: {url} (database {db}). API user {api_user}; its secret is in .env (ODOO_API_KEY)."
    )


if __name__ == "__main__":
    main()
