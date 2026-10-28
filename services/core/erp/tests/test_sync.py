from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.core.management import call_command

from accounts.models import Organization
from common import crypto
from erp.adapters.base import ErpError
from erp.adapters.fake import FakeErp
from erp.models import (
    ErpBillRef,
    ErpConnection,
    ErpPurchaseOrder,
    ErpPurchaseOrderLine,
    ErpReceipt,
    ErpVendor,
    SyncRun,
)
from erp.sync import sync_connection
from erp.tasks import sync_all_erp

pytestmark = pytest.mark.django_db
LATER = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


@pytest.fixture
def connection() -> ErpConnection:
    org = Organization.objects.create(name="Indus Retail (Pvt) Ltd")
    return ErpConnection.objects.create(org=org, kind=ErpConnection.Kind.FAKE)


@pytest.fixture
def erp() -> FakeErp:
    return FakeErp.from_seed()


def test_first_sync_mirrors_everything(connection, erp) -> None:
    run = sync_connection(connection, adapter=erp)
    assert run.status == "ok"
    assert run.counts == {
        "vendors": 11,
        "purchase_orders": 12,
        "receipts": 9,
        "bills": 1,
        "accounts": 5,
        "taxes": 2,
    }
    org = connection.org
    po = ErpPurchaseOrder.objects.for_org(org).get(vendor_ref="SEED-PO-03")
    assert po.vendor is not None and po.vendor.name == "Mehran Steel Works"
    assert [(line.product_code, line.qty_received) for line in po.lines.all()] == [
        ("P-RACK-5", Decimal(6)),
        ("P-SHELF-B", Decimal(40)),
    ]
    bill = ErpBillRef.objects.for_org(org).get()
    assert (bill.ref_norm, bill.vendor.ref) == ("NL2026094471", "N01")  # type: ignore[union-attr]
    assert ErpReceipt.objects.for_org(org).filter(po=po).exists()
    connection.refresh_from_db()
    assert connection.last_sync_status == "ok" and set(connection.sync_state) == {
        "vendors",
        "purchase_orders",
        "receipts",
        "bills",
    }


def test_bank_accounts_are_encrypted_indexed_and_masked(connection, erp) -> None:
    sync_connection(connection, adapter=erp)
    vendor = ErpVendor.objects.for_org(connection.org).get(ref="V01")
    iban = erp.vendors[0].bank_accounts[0]
    assert iban not in vendor.bank_accounts_enc[0]
    assert crypto.decrypt(vendor.bank_accounts_enc[0], org_id=connection.org_id) == iban
    assert vendor.bank_hashes == [crypto.blind_index(iban, org_id=connection.org_id)]
    assert vendor.bank_masks == [f"{iban[:4]} **** **** {iban[-4:]}"]
    assert vendor.domains == ["alnoor-traders.test"]
    assert vendor.tax_id_norm == "35201174"


def test_incremental_sync_reads_only_changes(connection, erp) -> None:
    sync_connection(connection, adapter=erp)
    po = next(p for p in erp.purchase_orders if p.vendor_ref == "SEED-PO-05")
    received = tuple(
        line.__class__(**{**line.__dict__, "qty_received": line.qty_ordered}) for line in po.lines
    )
    erp.touch(po, LATER, lines=received)  # the furniture arrived

    run = sync_connection(connection, adapter=erp)
    assert run.counts["purchase_orders"] == 1 and run.counts["vendors"] == 0
    row = ErpPurchaseOrder.objects.for_org(connection.org).get(vendor_ref="SEED-PO-05")
    assert all(line.qty_received == line.qty_ordered for line in row.lines.all())
    connection.refresh_from_db()
    assert connection.sync_state["purchase_orders"] == LATER.isoformat()


def test_local_vendor_settings_survive_sync(connection, erp) -> None:
    sync_connection(connection, adapter=erp)
    vendor = ErpVendor.objects.for_org(connection.org).get(ref="N01")
    vendor.non_po, vendor.category = True, "internet"
    vendor.domains = [*vendor.domains, "netlink-billing.test"]
    vendor.save()

    erp.touch(erp.vendors[8], LATER, name="NetLink Broadband (Pvt) Ltd")
    sync_connection(connection, adapter=erp)
    vendor.refresh_from_db()
    assert vendor.name == "NetLink Broadband (Pvt) Ltd"
    assert (vendor.non_po, vendor.category) == (True, "internet")
    assert vendor.domains == ["netlink.test", "netlink-billing.test"]


def test_removed_po_lines_are_removed(connection, erp) -> None:
    sync_connection(connection, adapter=erp)
    po = erp.purchase_orders[1]
    erp.touch(po, LATER, lines=po.lines[:1])
    sync_connection(connection, adapter=erp)
    lines = ErpPurchaseOrderLine.objects.for_org(connection.org).filter(po__erp_id=po.erp_id)
    assert lines.count() == 1


def test_erp_failure_is_recorded_and_changes_nothing(connection, erp) -> None:
    sync_connection(connection, adapter=erp)

    def broken(since=None):
        raise ErpError("Odoo rejected the API user's credentials.")

    erp.list_bills = broken
    erp.touch(erp.vendors[0], LATER, name="Renamed")
    run = sync_connection(connection, adapter=erp)
    assert (run.status, run.error) == ("failed", "Odoo rejected the API user's credentials.")
    assert ErpVendor.objects.for_org(connection.org).get(ref="V01").name == "Al-Noor Traders"
    connection.refresh_from_db()
    assert connection.last_sync_status == "failed"
    assert "vendors" in connection.sync_state  # the old high-water mark stays


def test_full_sync_ignores_high_water_marks(connection, erp) -> None:
    sync_connection(connection, adapter=erp)
    run = sync_connection(connection, adapter=erp, full=True)
    assert run.full and run.counts["vendors"] == 11


def test_beat_task_and_command_sync_every_connection(connection) -> None:
    assert sync_all_erp() == 1  # eager in tests: the fake connection syncs from seed data
    assert SyncRun.objects.for_org(connection.org).filter(status="ok").count() == 1
    call_command("erp_sync", "--full", stdout=None)
    assert SyncRun.objects.for_org(connection.org).count() == 2


def test_connection_secret_is_encrypted(connection) -> None:
    connection.set_secret("odoo-api-key-123")
    connection.save()
    connection.refresh_from_db()
    assert "odoo-api-key-123" not in connection.secret_enc
    assert connection.get_secret() == "odoo-api-key-123"
