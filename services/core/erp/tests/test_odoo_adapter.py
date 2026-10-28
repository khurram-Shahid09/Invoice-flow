"""The Odoo adapter against a scripted JSON-RPC server (no Odoo needed)."""

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from erp.adapters.base import ErpError
from erp.adapters.odoo import OdooAdapter

RECORDS: dict[str, dict[int, dict]] = {
    "res.users": {2: {"id": 2, "name": "InvoiceFlow AP bot", "company_id": [1, "Indus"]}},
    "res.company": {1: {"id": 1, "name": "Indus Retail (Pvt) Ltd", "currency_id": [160, "PKR"]}},
    "purchase.order": {
        7: {
            "id": 7,
            "name": "P00007",
            "partner_id": [12, "Mehran Steel Works"],
            "state": "purchase",
            "currency_id": [160, "PKR"],
            "partner_ref": "SEED-PO-03",
            "date_order": "2026-10-20 09:30:00",
            "user_id": [2, "Bilal Ahmed"],
            "amount_total": 248980.0,
            "write_date": "2026-10-20 09:31:00",
            "order_line": [70, 71],
        }
    },
    "purchase.order.line": {
        70: {
            "id": 70,
            "product_id": [5, "[P-RACK-5] Steel Rack 5-Shelf"],
            "name": "[P-RACK-5] Steel Rack 5-Shelf",
            "product_uom": [1, "Units"],
            "product_qty": 10.0,
            "qty_received": 6.0,
            "qty_invoiced": 0.0,
            "price_unit": 18500.0,
            "taxes_id": [3],
            "write_date": "2026-10-21 10:00:00",
        },
        71: {
            "id": 71,
            "product_id": False,
            "name": "Delivery charges",
            "product_uom": [1, "Units"],
            "product_qty": 1.0,
            "qty_received": 0.0,
            "qty_invoiced": 0.0,
            "price_unit": 1500.0,
            "taxes_id": [],
            "write_date": "2026-10-20 09:31:00",
        },
    },
    "product.product": {5: {"id": 5, "default_code": "P-RACK-5"}},
    "account.tax": {3: {"id": 3, "amount": 18.0}},
}


class ScriptedOdoo:
    """Answers the JSON-RPC calls the adapter makes; records what it was asked."""

    def __init__(self, *, uid: int | bool = 2) -> None:
        self.uid = uid
        self.calls: list[tuple] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = json.loads(request.content)["params"]
        service, method, args = params["service"], params["method"], params["args"]
        if service == "common" and method == "authenticate":
            return self._ok(self.uid)
        if service == "common" and method == "version":
            return self._ok({"server_version": "18.0"})
        _db, _uid, _secret, model, op, op_args, kwargs = args
        self.calls.append((model, op, op_args, kwargs))
        table = RECORDS.get(model, {})
        if op == "read":
            return self._ok([table[i] for i in op_args[0] if i in table])
        if op == "search":
            return self._ok(list(table))
        if op == "search_read":
            if model == "purchase.order.line":
                return self._ok([{"id": 70, "order_id": [7, "P00007"]}])
            return self._ok([])
        return self._error("unexpected call")

    @staticmethod
    def _ok(result) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    @staticmethod
    def _error(message: str) -> httpx.Response:
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": 1, "error": {"data": {"message": message}}}
        )


def adapter(server: ScriptedOdoo) -> OdooAdapter:
    return OdooAdapter(
        "http://odoo.test", "invoiceflow", "bot", "secret", transport=httpx.MockTransport(server)
    )


def test_maps_purchase_orders_with_lines() -> None:
    [po] = adapter(ScriptedOdoo()).list_purchase_orders()
    assert (po.number, po.vendor_erp_id, po.vendor_ref, po.currency) == (
        "P00007",
        "12",
        "SEED-PO-03",
        "PKR",
    )
    assert po.amount_total == Decimal("248980.0")
    assert po.order_date is not None and po.order_date.isoformat() == "2026-10-20"
    # The newest change among the order and its lines (a receipt updated line 70).
    assert po.updated_at == datetime(2026, 10, 21, 10, 0, tzinfo=UTC)
    rack, delivery = po.lines
    assert (rack.product_code, rack.qty_ordered, rack.qty_received) == (
        "P-RACK-5",
        Decimal("10.0"),
        Decimal("6.0"),
    )
    assert rack.tax_rate == Decimal("18.0")
    assert (delivery.product_code, delivery.tax_rate) == ("", None)


def test_incremental_sync_also_asks_for_changed_lines() -> None:
    server = ScriptedOdoo()
    adapter(server).list_purchase_orders(since=datetime(2026, 10, 21, tzinfo=UTC))
    searched = [(model, op_args) for model, op, op_args, _ in server.calls if op != "read"]
    assert ("purchase.order.line", [[("write_date", ">", "2026-10-21 00:00:00")]]) in [
        (m, [[tuple(c) for c in a[0]]]) for m, a in searched
    ]


def test_connection_info() -> None:
    info = adapter(ScriptedOdoo()).test_connection()
    assert (info.company, info.currency, info.user) == (
        "Indus Retail (Pvt) Ltd",
        "PKR",
        "InvoiceFlow AP bot",
    )


def test_rejected_credentials() -> None:
    with pytest.raises(ErpError, match="rejected"):
        adapter(ScriptedOdoo(uid=False)).list_taxes()


def test_odoo_errors_and_outages_become_erp_errors() -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(ErpError, match="Can't reach Odoo"):
        OdooAdapter(
            "http://odoo.test", "db", "u", "s", transport=httpx.MockTransport(down)
        ).test_connection()

    with pytest.raises(ErpError, match="unexpected call"):
        adapter(ScriptedOdoo())._call("x.model", "unlink", [1])
