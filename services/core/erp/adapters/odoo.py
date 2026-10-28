"""Odoo 18 through its external JSON-RPC API (docs/09-erp-integration.md).

Signs in as a dedicated least-privilege user (Purchase user, Inventory user, Billing) with
an API key or password. Reads only, for now; posting bills lands on day 10.
"""

from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx

from .base import (
    Account,
    BillRef,
    ConnectionInfo,
    ErpError,
    PurchaseOrder,
    PurchaseOrderLine,
    Receipt,
    Tax,
    Vendor,
)

ODOO_DATETIME = "%Y-%m-%d %H:%M:%S"  # Odoo stores and returns UTC in this format
BATCH = 500


def _dt(value: Any) -> datetime | None:
    """Odoo sends ``False`` for empty dates."""
    if not isinstance(value, str) or not value:
        return None
    return datetime.strptime(value, ODOO_DATETIME).replace(tzinfo=UTC)


def _date(value: Any) -> date | None:
    return date.fromisoformat(value) if isinstance(value, str) and value else None


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _name(many2one: Any) -> str:
    """Odoo returns relations as ``[id, "display name"]`` or ``False``."""
    return many2one[1] if many2one else ""


def _id(many2one: Any) -> str:
    return str(many2one[0]) if many2one else ""


def _dec(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def _since(since: datetime | None) -> list:
    """Odoo keeps microseconds but returns and compares whole seconds, so records changed in the
    last second are read again next time. That overlap is deliberate: re-reading is harmless,
    missing a change is not."""
    return [("write_date", ">", since.astimezone(UTC).strftime(ODOO_DATETIME))] if since else []


class OdooAdapter:
    def __init__(
        self,
        url: str,
        db: str,
        username: str,
        secret: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30,
    ) -> None:
        self.db = db
        self.username = username
        self.secret = secret
        self.http = httpx.Client(base_url=url.rstrip("/"), timeout=timeout, transport=transport)
        self._uid: int | None = None

    # --- JSON-RPC plumbing ---

    def _rpc(self, service: str, method: str, *args: Any) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": list(args)},
            "id": 1,
        }
        try:
            response = self.http.post("/jsonrpc", json=payload)
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            raise ErpError(f"Can't reach Odoo: {exc.__class__.__name__}") from exc
        except ValueError as exc:
            raise ErpError("Odoo sent a response that isn't JSON.") from exc
        if "error" in body:
            data = body["error"].get("data") or {}
            raise ErpError(data.get("message") or body["error"].get("message") or "Odoo error")
        return body.get("result")

    @property
    def uid(self) -> int:
        if self._uid is None:
            uid = self._rpc("common", "authenticate", self.db, self.username, self.secret, {})
            if not uid:
                raise ErpError("Odoo rejected the API user's credentials.")
            self._uid = int(uid)
        return self._uid

    def _call(self, model: str, method: str, *args: Any, **kwargs: Any) -> Any:
        return self._rpc(
            "object",
            "execute_kw",
            self.db,
            self.uid,
            self.secret,
            model,
            method,
            list(args),
            kwargs,
        )

    def _search_read(
        self, model: str, domain: list, fields: list[str], *, inactive: bool = False
    ) -> list[dict]:
        context = {"active_test": False} if inactive else {}
        rows: list[dict] = []
        while True:
            page = self._call(
                model,
                "search_read",
                domain,
                fields=fields,
                offset=len(rows),
                limit=BATCH,
                order="id",
                context=context,
            )
            rows.extend(page)
            if len(page) < BATCH:
                return rows

    def _read(self, model: str, ids: Iterable[int], fields: list[str]) -> dict[int, dict]:
        ids = sorted(set(ids))
        if not ids:
            return {}
        return {row["id"]: row for row in self._call(model, "read", ids, fields)}

    # --- ErpAdapter ---

    def test_connection(self) -> ConnectionInfo:
        version = self._rpc("common", "version") or {}
        user = self._read("res.users", [self.uid], ["name", "company_id"])[self.uid]
        company_id = user["company_id"][0]
        company = self._read("res.company", [company_id], ["name", "currency_id"])[company_id]
        return ConnectionInfo(
            server_version=str(version.get("server_version", "")),
            company=company["name"],
            currency=_name(company["currency_id"]),
            user=user["name"],
        )

    def _company_currency(self) -> str:
        return self.test_connection().currency

    def list_vendors(self, since: datetime | None = None) -> list[Vendor]:
        rows = self._search_read(
            "res.partner",
            [("supplier_rank", ">", 0), *_since(since)],
            ["name", "ref", "vat", "email", "city", "active", "write_date", "bank_ids"],
            inactive=True,
        )
        banks = self._read(
            "res.partner.bank", (b for r in rows for b in r["bank_ids"]), ["acc_number"]
        )
        currency = self._company_currency() if rows else ""
        return [
            Vendor(
                erp_id=str(r["id"]),
                name=r["name"],
                ref=_text(r["ref"]),
                tax_id=_text(r["vat"]),
                email=_text(r["email"]),
                city=_text(r["city"]),
                currency=currency,
                bank_accounts=tuple(banks[b]["acc_number"] for b in r["bank_ids"] if b in banks),
                active=bool(r["active"]),
                updated_at=_dt(r["write_date"]) or datetime.now(UTC),
            )
            for r in rows
        ]

    def list_purchase_orders(self, since: datetime | None = None) -> list[PurchaseOrder]:
        states = [("state", "in", ["purchase", "done", "cancel"])]
        order_ids = set(self._call("purchase.order", "search", [*states, *_since(since)]))
        if since:
            # Receipts change a line's received quantity without touching its order.
            changed_lines = self._search_read("purchase.order.line", _since(since), ["order_id"])
            order_ids |= {line["order_id"][0] for line in changed_lines}
        if not order_ids:
            return []
        orders = self._read(
            "purchase.order",
            order_ids,
            [
                "name",
                "partner_id",
                "state",
                "currency_id",
                "partner_ref",
                "date_order",
                "user_id",
                "amount_total",
                "write_date",
                "order_line",
            ],
        )
        orders = {k: v for k, v in orders.items() if v["state"] in ("purchase", "done", "cancel")}
        lines = self._read(
            "purchase.order.line",
            (line for o in orders.values() for line in o["order_line"]),
            [
                "product_id",
                "name",
                "product_uom",
                "product_qty",
                "qty_received",
                "qty_invoiced",
                "price_unit",
                "taxes_id",
                "write_date",
            ],
        )
        products = self._read(
            "product.product",
            (line["product_id"][0] for line in lines.values() if line["product_id"]),
            ["default_code"],
        )
        taxes = self._read(
            "account.tax", (t for line in lines.values() for t in line["taxes_id"]), ["amount"]
        )

        def to_line(row: dict) -> PurchaseOrderLine:
            product = products.get(row["product_id"][0]) if row["product_id"] else None
            rates = [_dec(taxes[t]["amount"]) for t in row["taxes_id"] if t in taxes]
            return PurchaseOrderLine(
                erp_id=str(row["id"]),
                product_code=_text(product["default_code"]) if product else "",
                description=row["name"],
                uom=_name(row["product_uom"]),
                qty_ordered=_dec(row["product_qty"]),
                qty_received=_dec(row["qty_received"]),
                qty_invoiced=_dec(row["qty_invoiced"]),
                unit_price=_dec(row["price_unit"]),
                tax_rate=rates[0] if len(rates) == 1 else None,
            )

        result = []
        for order in orders.values():
            order_lines = [lines[i] for i in order["order_line"] if i in lines]
            updated = max(
                [_dt(order["write_date"])] + [_dt(line["write_date"]) for line in order_lines],
                key=lambda d: d or datetime.min.replace(tzinfo=UTC),
            )
            ordered_at = _dt(order["date_order"])
            result.append(
                PurchaseOrder(
                    erp_id=str(order["id"]),
                    number=order["name"],
                    vendor_erp_id=_id(order["partner_id"]),
                    state=order["state"],
                    currency=_name(order["currency_id"]),
                    vendor_ref=_text(order["partner_ref"]),
                    order_date=ordered_at.date() if ordered_at else None,
                    requester=_name(order["user_id"]),
                    amount_total=_dec(order["amount_total"]),
                    updated_at=updated or datetime.now(UTC),
                    lines=tuple(to_line(line) for line in order_lines),
                )
            )
        return sorted(result, key=lambda po: int(po.erp_id))

    def list_receipts(self, since: datetime | None = None) -> list[Receipt]:
        rows = self._search_read(
            "stock.picking",
            [("picking_type_code", "=", "incoming"), *_since(since)],
            ["name", "purchase_id", "state", "date_done", "write_date"],
        )
        return [
            Receipt(
                erp_id=str(r["id"]),
                number=r["name"],
                po_erp_id=_id(r["purchase_id"]),
                state=r["state"],
                done_at=_dt(r["date_done"]),
                updated_at=_dt(r["write_date"]) or datetime.now(UTC),
            )
            for r in rows
        ]

    def list_accounts(self) -> list[Account]:
        rows = self._search_read("account.account", [], ["code", "name", "account_type"])
        return [
            Account(str(r["id"]), _text(r["code"]), r["name"], _text(r["account_type"]))
            for r in rows
        ]

    def list_taxes(self) -> list[Tax]:
        rows = self._search_read(
            "account.tax",
            [("type_tax_use", "=", "purchase"), ("amount_type", "=", "percent")],
            ["name", "amount", "active"],
            inactive=True,
        )
        return [Tax(str(r["id"]), r["name"], _dec(r["amount"]), bool(r["active"])) for r in rows]

    def list_bills(self, since: datetime | None = None) -> list[BillRef]:
        rows = self._search_read(
            "account.move",
            [("move_type", "in", ["in_invoice", "in_refund"]), *_since(since)],
            [
                "partner_id",
                "ref",
                "amount_total",
                "currency_id",
                "invoice_date",
                "state",
                "write_date",
            ],
        )
        return [
            BillRef(
                erp_id=str(r["id"]),
                vendor_erp_id=_id(r["partner_id"]),
                ref=_text(r["ref"]),
                total=_dec(r["amount_total"]),
                currency=_name(r["currency_id"]),
                bill_date=_date(r["invoice_date"]),
                state=r["state"],
                updated_at=_dt(r["write_date"]) or datetime.now(UTC),
            )
            for r in rows
        ]
