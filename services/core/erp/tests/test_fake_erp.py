from datetime import UTC, datetime
from decimal import Decimal

from erp.adapters.fake import FakeErp, pk_iban


def test_seed_matches_the_odoo_seed() -> None:
    erp = FakeErp.from_seed()
    assert erp.test_connection().company == "Indus Retail (Pvt) Ltd"
    assert len(erp.list_vendors()) == 11
    assert len(erp.list_purchase_orders()) == 12
    assert {t.rate for t in erp.list_taxes()} == {Decimal(18), Decimal(16)}

    po3 = next(p for p in erp.purchase_orders if p.vendor_ref == "SEED-PO-03")
    received = {line.product_code: line.qty_received for line in po3.lines}
    assert received == {"P-RACK-5": Decimal(6), "P-SHELF-B": Decimal(40)}
    # 10 racks x 18,500 + 40 brackets x 650, plus 18% GST, as Odoo computes it
    assert po3.amount_total == Decimal("248980")

    bill = erp.list_bills()[0]
    assert (bill.ref, bill.total) == ("NL-2026-09-4471", Decimal("9860"))


def test_services_and_unreceived_orders_have_no_receipts() -> None:
    erp = FakeErp.from_seed()
    received_pos = {r.po_erp_id for r in erp.list_receipts()}
    by_key = {p.vendor_ref: p.erp_id for p in erp.purchase_orders}
    assert by_key["SEED-PO-05"] not in received_pos  # goods not delivered yet
    assert by_key["SEED-PO-01"] in received_pos


def test_iban_checksum_is_valid() -> None:
    iban = pk_iban("MEZN", "0102003300441201")
    assert len(iban) == 24
    rearranged = iban[4:] + iban[:4]
    assert int("".join(str(int(c, 36)) for c in rearranged)) % 97 == 1


def test_since_returns_only_changed_records() -> None:
    erp = FakeErp.from_seed()
    later = datetime(2026, 10, 20, tzinfo=UTC)
    assert erp.list_vendors(since=later) == []
    vendor = erp.touch(erp.vendors[0], datetime(2026, 10, 21, tzinfo=UTC), email="new@x.test")
    assert erp.list_vendors(since=later) == [vendor]


def test_create_bill_is_idempotent() -> None:
    from datetime import date

    from erp.adapters.base import BillDraft, BillLine

    erp = FakeErp.from_seed()
    draft = BillDraft(
        vendor_erp_id="1",
        ref="INV-2291",
        invoice_date=date(2026, 10, 26),
        due_date=None,
        currency="PKR",
        lines=(BillLine("A4 Paper", Decimal(50), Decimal(1450), Decimal(18), "1"),),
        attachment_name="INV-2291.pdf",
        attachment=b"%PDF",
        attachment_mime="application/pdf",
    )
    first, again = erp.create_bill(draft), erp.create_bill(draft)
    assert first.created and not again.created and first.erp_id == again.erp_id
    assert erp.list_bills()[-1].total == Decimal("85550")
    assert any(line.is_service for po in erp.purchase_orders for line in po.lines)
