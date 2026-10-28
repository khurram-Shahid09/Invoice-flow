"""Mirror the ERP's master data into local tables (docs/09-erp-integration.md "Sync").

Incremental by default: each kind remembers the newest ``updated_at`` it has seen and asks
the ERP only for changes after it. ``full=True`` re-reads everything (and is what a first
sync does). Accounts and taxes are small and always read in full.
"""

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from django.db import transaction
from django.utils import timezone

from common import crypto
from common.text import business_domain, normalize_invoice_number, normalize_tax_id

from .adapters.base import ErpAdapter, ErpError, PurchaseOrder, Vendor
from .adapters.fake import FakeErp
from .adapters.odoo import OdooAdapter
from .models import (
    ErpAccount,
    ErpBillRef,
    ErpConnection,
    ErpPurchaseOrder,
    ErpPurchaseOrderLine,
    ErpReceipt,
    ErpTax,
    ErpVendor,
    SyncRun,
)

log = logging.getLogger(__name__)

INCREMENTAL_KINDS = ("vendors", "purchase_orders", "receipts", "bills")


def adapter_for(connection: ErpConnection) -> ErpAdapter:
    if connection.kind == ErpConnection.Kind.ODOO:
        return OdooAdapter(
            connection.url, connection.database, connection.username, connection.get_secret()
        )
    return FakeErp.from_seed()


def sync_connection(
    connection: ErpConnection, *, adapter: ErpAdapter | None = None, full: bool = False
) -> SyncRun:
    """Run one sync and record it. ERP failures are recorded, not raised."""
    run = SyncRun.objects.create(org_id=connection.org_id, full=full)
    adapter = adapter or adapter_for(connection)
    try:
        counts = _sync(connection, adapter, full=full)
    except ErpError as exc:
        log.warning("ERP sync failed for %s: %s", connection.org_id, exc)
        _finish(connection, run, SyncRun.Status.FAILED, error=str(exc))
    else:
        _finish(connection, run, SyncRun.Status.OK, counts=counts)
    return run


def _finish(
    connection: ErpConnection,
    run: SyncRun,
    status: str,
    *,
    counts: dict[str, int] | None = None,
    error: str = "",
) -> None:
    now = timezone.now()
    run.status, run.counts, run.error, run.finished_at = status, counts or {}, error, now
    run.save(update_fields=["status", "counts", "error", "finished_at"])
    ok = status == SyncRun.Status.OK
    connection.last_sync_at = now
    connection.last_sync_status = ErpConnection.Status.OK if ok else ErpConnection.Status.FAILED
    connection.last_error = error
    connection.save(update_fields=["last_sync_at", "last_sync_status", "last_error", "updated_at"])


def _sync(connection: ErpConnection, adapter: ErpAdapter, *, full: bool) -> dict[str, int]:
    state = {} if full else dict(connection.sync_state)

    def since(kind: str) -> datetime | None:
        value = state.get(kind)
        return datetime.fromisoformat(value) if value else None

    # Read everything first, so an ERP error leaves the mirror untouched.
    fetched: dict[str, Any] = {
        "vendors": adapter.list_vendors(since("vendors")),
        "purchase_orders": adapter.list_purchase_orders(since("purchase_orders")),
        "receipts": adapter.list_receipts(since("receipts")),
        "bills": adapter.list_bills(since("bills")),
        "accounts": adapter.list_accounts(),
        "taxes": adapter.list_taxes(),
    }
    org_id = connection.org_id
    writers: dict[str, Callable[[str, list], None]] = {
        "vendors": _save_vendors,
        "purchase_orders": _save_purchase_orders,
        "receipts": _save_receipts,
        "bills": _save_bills,
        "accounts": _save_accounts,
        "taxes": _save_taxes,
    }
    with transaction.atomic():
        for kind, items in fetched.items():  # vendors first: the others link to them
            writers[kind](org_id, items)
        if full:  # a full read is complete: bills gone from the ERP must not count as duplicates
            present = [b.erp_id for b in fetched["bills"]]
            ErpBillRef.objects.filter(org_id=org_id).exclude(erp_id__in=present).delete()
        for kind in INCREMENTAL_KINDS:
            newest = max((i.updated_at for i in fetched[kind]), default=None)
            if newest and (since(kind) is None or newest > since(kind)):
                state[kind] = newest.isoformat()
        connection.sync_state = state
        connection.save(update_fields=["sync_state", "updated_at"])
    return {kind: len(items) for kind, items in fetched.items()}


def _vendor_ids(org_id: str) -> dict[str, str]:
    return dict(ErpVendor.objects.filter(org_id=org_id).values_list("erp_id", "id"))


def _save_vendors(org_id: str, vendors: list[Vendor]) -> None:
    existing = {v.erp_id: v for v in ErpVendor.objects.filter(org_id=org_id)}
    for v in vendors:
        row = existing.get(v.erp_id) or ErpVendor(org_id=org_id, erp_id=v.erp_id)
        hashes = [crypto.blind_index(acc, org_id=org_id) for acc in v.bank_accounts]
        if hashes != row.bank_hashes:  # re-encrypt only when the accounts changed
            row.bank_accounts_enc = [crypto.encrypt(a, org_id=org_id) for a in v.bank_accounts]
            row.bank_hashes = hashes
            row.bank_masks = [crypto.mask(a) for a in v.bank_accounts]
        row.name, row.ref, row.email, row.city = v.name, v.ref, v.email, v.city
        row.tax_id, row.tax_id_norm = v.tax_id, normalize_tax_id(v.tax_id)
        row.currency, row.active, row.erp_updated_at = v.currency, v.active, v.updated_at
        domain = business_domain(v.email)
        if domain and domain not in row.domains:
            row.domains = [*row.domains, domain]
        row.save()


def _save_purchase_orders(org_id: str, orders: list[PurchaseOrder]) -> None:
    vendor_ids = _vendor_ids(org_id)
    for po in orders:
        row, _ = ErpPurchaseOrder.objects.update_or_create(
            org_id=org_id,
            erp_id=po.erp_id,
            defaults={
                "number": po.number,
                "vendor_id": vendor_ids.get(po.vendor_erp_id),
                "vendor_erp_id": po.vendor_erp_id,
                "state": po.state,
                "currency": po.currency,
                "vendor_ref": po.vendor_ref,
                "order_date": po.order_date,
                "requester": po.requester,
                "amount_total": po.amount_total,
                "erp_updated_at": po.updated_at,
            },
        )
        keep = []
        for position, line in enumerate(po.lines):
            ErpPurchaseOrderLine.objects.update_or_create(
                org_id=org_id,
                erp_id=line.erp_id,
                defaults={
                    "po": row,
                    "position": position,
                    "product_code": line.product_code,
                    "description": line.description,
                    "uom": line.uom,
                    "qty_ordered": line.qty_ordered,
                    "qty_received": line.qty_received,
                    "qty_invoiced": line.qty_invoiced,
                    "unit_price": line.unit_price,
                    "tax_rate": line.tax_rate,
                    "is_service": line.is_service,
                },
            )
            keep.append(line.erp_id)
        row.lines.exclude(erp_id__in=keep).delete()  # lines removed in the ERP


def _save_receipts(org_id: str, receipts: list) -> None:
    po_ids = dict(ErpPurchaseOrder.objects.filter(org_id=org_id).values_list("erp_id", "id"))
    for r in receipts:
        ErpReceipt.objects.update_or_create(
            org_id=org_id,
            erp_id=r.erp_id,
            defaults={
                "number": r.number,
                "po_id": po_ids.get(r.po_erp_id),
                "state": r.state,
                "done_at": r.done_at,
            },
        )


def _save_bills(org_id: str, bills: list) -> None:
    vendor_ids = _vendor_ids(org_id)
    for b in bills:
        ErpBillRef.objects.update_or_create(
            org_id=org_id,
            erp_id=b.erp_id,
            defaults={
                "vendor_id": vendor_ids.get(b.vendor_erp_id),
                "vendor_erp_id": b.vendor_erp_id,
                "ref": b.ref,
                "ref_norm": normalize_invoice_number(b.ref) if b.ref else "",
                "total": b.total,
                "currency": b.currency,
                "bill_date": b.bill_date,
                "state": b.state,
            },
        )


def _save_accounts(org_id: str, accounts: list) -> None:
    for a in accounts:
        ErpAccount.objects.update_or_create(
            org_id=org_id,
            erp_id=a.erp_id,
            defaults={"code": a.code, "name": a.name, "kind": a.kind},
        )


def _save_taxes(org_id: str, taxes: list) -> None:
    for t in taxes:
        ErpTax.objects.update_or_create(
            org_id=org_id,
            erp_id=t.erp_id,
            defaults={"name": t.name, "rate": t.rate, "active": t.active},
        )
