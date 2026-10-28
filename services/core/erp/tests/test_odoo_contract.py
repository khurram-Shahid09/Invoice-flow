"""The Odoo adapter against the real local Odoo seeded by infra/odoo/seed.py.

Run with Odoo up (docker compose -f infra/docker-compose.yml --profile erp up -d):
    uv run pytest -m odoo
Skipped automatically when Odoo or its API user isn't configured or reachable (e.g. in CI).
"""

from decimal import Decimal

import httpx
import pytest
from django.conf import settings

from erp.adapters.odoo import OdooAdapter

pytestmark = pytest.mark.odoo


@pytest.fixture(scope="module")
def odoo() -> OdooAdapter:
    if not settings.ODOO_API_KEY:
        pytest.skip("ODOO_API_KEY not set: run infra/odoo/seed.py first")
    try:
        httpx.get(f"{settings.ODOO_URL}/web/login", timeout=3)
    except httpx.HTTPError:
        pytest.skip("Odoo is not running")
    return OdooAdapter(
        settings.ODOO_URL, settings.ODOO_DB, settings.ODOO_API_USER, settings.ODOO_API_KEY
    )


def test_connection(odoo: OdooAdapter) -> None:
    info = odoo.test_connection()
    assert info.company == "Indus Retail (Pvt) Ltd"
    assert info.currency == "PKR"
    assert info.server_version.startswith("18.")


def test_vendors_have_tax_ids_and_bank_accounts(odoo: OdooAdapter) -> None:
    vendors = {v.ref: v for v in odoo.list_vendors()}
    alnoor = vendors["V01"]
    assert alnoor.tax_id == "3520117-4"
    assert alnoor.bank_accounts and alnoor.bank_accounts[0].startswith("PK")
    assert {"N01", "N02", "N03"} <= set(vendors)


def test_partial_receipt_is_visible_on_the_po_line(odoo: OdooAdapter) -> None:
    po = next(p for p in odoo.list_purchase_orders() if p.vendor_ref == "SEED-PO-03")
    received = {line.product_code: line.qty_received for line in po.lines}
    assert received == {"P-RACK-5": Decimal("6.0"), "P-SHELF-B": Decimal("40.0")}
    assert {line.tax_rate for line in po.lines} == {Decimal("18.0")}


def test_receipts_taxes_accounts_and_bills(odoo: OdooAdapter) -> None:
    assert any(r.state == "done" and r.po_erp_id for r in odoo.list_receipts())
    assert {Decimal("18.0"), Decimal("16.0")} <= {t.rate for t in odoo.list_taxes()}
    assert any(a.kind == "expense" for a in odoo.list_accounts())
    assert any(b.ref == "NL-2026-09-4471" and b.state == "posted" for b in odoo.list_bills())
