"""What InvoiceFlow needs from an ERP (docs/09-erp-integration.md).

Adapters return these plain records; the sync (erp/sync.py) mirrors them into local tables
so checks are fast and work while the ERP is down. Every ``list_*`` takes ``since``: only
records changed after that moment (``None`` = everything), compared with ``updated_at``.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol


class ErpError(Exception):
    """The ERP refused or failed a request. ``message`` is safe to show to admins."""


@dataclass(frozen=True)
class ConnectionInfo:
    server_version: str
    company: str
    currency: str
    user: str


@dataclass(frozen=True)
class Vendor:
    erp_id: str
    name: str
    ref: str
    tax_id: str
    email: str
    city: str
    currency: str
    bank_accounts: tuple[str, ...]
    active: bool
    updated_at: datetime


@dataclass(frozen=True)
class PurchaseOrderLine:
    erp_id: str
    product_code: str
    description: str
    uom: str
    qty_ordered: Decimal
    qty_received: Decimal
    qty_invoiced: Decimal
    unit_price: Decimal
    tax_rate: Decimal | None  # percent, None when the line has no or several taxes
    is_service: bool = False  # services have no goods receipt: matched 2-way (docs/07)


@dataclass(frozen=True)
class PurchaseOrder:
    erp_id: str
    number: str
    vendor_erp_id: str
    state: str  # "purchase" (confirmed), "done" (locked), "cancel"
    currency: str
    vendor_ref: str
    order_date: date | None
    requester: str
    amount_total: Decimal
    updated_at: datetime
    lines: tuple[PurchaseOrderLine, ...] = field(default=())


@dataclass(frozen=True)
class Receipt:
    erp_id: str
    number: str
    po_erp_id: str
    state: str  # "done" once goods are received
    done_at: datetime | None
    updated_at: datetime


@dataclass(frozen=True)
class Account:
    erp_id: str
    code: str
    name: str
    kind: str  # e.g. "expense", "liability_payable"


@dataclass(frozen=True)
class Tax:
    erp_id: str
    name: str
    rate: Decimal
    active: bool


@dataclass(frozen=True)
class BillRef:
    """An existing vendor bill, for duplicate checks."""

    erp_id: str
    vendor_erp_id: str
    ref: str
    total: Decimal
    currency: str
    bill_date: date | None
    state: str  # "draft", "posted", "cancel"
    updated_at: datetime


@dataclass(frozen=True)
class BillLine:
    description: str
    quantity: Decimal
    unit_price: Decimal
    tax_rate: Decimal | None
    po_line_erp_id: str | None  # links the bill to the PO, so the ERP tracks billed quantities


@dataclass(frozen=True)
class BillDraft:
    vendor_erp_id: str
    ref: str  # the vendor's invoice number
    invoice_date: date
    due_date: date | None
    currency: str
    lines: tuple[BillLine, ...]
    attachment_name: str
    attachment: bytes
    attachment_mime: str


@dataclass(frozen=True)
class PostedBill:
    erp_id: str
    url: str
    created: bool  # False when a bill with this vendor and ref already existed


class ErpAdapter(Protocol):
    def test_connection(self) -> ConnectionInfo: ...
    def list_vendors(self, since: datetime | None = None) -> list[Vendor]: ...
    def list_purchase_orders(self, since: datetime | None = None) -> list[PurchaseOrder]: ...
    def list_receipts(self, since: datetime | None = None) -> list[Receipt]: ...
    def list_accounts(self) -> list[Account]: ...
    def list_taxes(self) -> list[Tax]: ...
    def list_bills(self, since: datetime | None = None) -> list[BillRef]: ...
    def create_bill(self, bill: BillDraft) -> PostedBill: ...
