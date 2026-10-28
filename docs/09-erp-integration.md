# 09 · ERP Integration

## Adapter interface

```python
class ErpAdapter(Protocol):
    def test_connection(self) -> ConnectionInfo: ...
    # master data (pulled by the sync task)
    def list_vendors(self, since: datetime | None) -> Iterable[Vendor]: ...
    def list_purchase_orders(self, since: datetime | None) -> Iterable[PurchaseOrder]: ...
    def list_receipts(self, since: datetime | None) -> Iterable[Receipt]: ...
    def list_accounts(self) -> Iterable[Account]: ...
    def list_taxes(self) -> Iterable[Tax]: ...
    def list_bills(self, since: datetime | None) -> Iterable[BillRef]: ...   # for duplicate checks
    # posting
    def find_bill(self, vendor_ref: str, invoice_ref: str) -> BillRef | None: ...
    def create_bill(self, bill: BillDraft, *, post: bool) -> BillRef: ...
    def attach_file(self, bill: BillRef, name: str, content: bytes, mime: str) -> None: ...
```

Adapters in the plan:
- `odoo` (MVP).
- `fake` (in-memory, for tests).
- `csv_export` (download approved bills as CSV for any ERP, MVP fallback).
- `watchonce` (v0.2): posts through a WatchOnce workflow for ERPs that only have a web UI.

## Odoo (reference ERP)

**Version:** Odoo 18 Community in Docker, with the `purchase`, `stock` and `account` apps installed.

**API:** the external JSON-RPC API (`/jsonrpc`, `execute_kw`), authenticating with a dedicated **API user + API key** (Odoo's user API keys), not a password.

**API user permissions** (least privilege):
- Purchase: User
- Inventory: User (read receipts)
- Invoicing: Billing

The user has no admin and no settings access.

### Model mapping

| InvoiceFlow | Odoo model | Notes |
|---|---|---|
| Vendor | `res.partner` (supplier_rank > 0) | `vat` = tax id; bank accounts in `res.partner.bank` |
| Purchase order | `purchase.order` / `purchase.order.line` | `qty_received`, `qty_invoiced` drive the 3-way checks |
| Goods receipt | `stock.picking` (incoming, done) | Line quantities via `stock.move` |
| Account | `account.account` | For non-PO bills |
| Tax | `account.tax` (type_tax_use = purchase) | Map by rate + name |
| Bill | `account.move` with `move_type = 'in_invoice'` (credit note: `in_refund`) | `ref` = vendor invoice number; `invoice_date`, `invoice_date_due`, `partner_id`, `currency_id` |
| Bill line | `account.move.line` via `invoice_line_ids` | `purchase_line_id` links to the PO line, so Odoo updates billed quantities |
| Attachment | `ir.attachment` (`res_model='account.move'`, `res_id`) | The original file |

### Posting algorithm (idempotent)

```
1. ref = invoice.invoice_number (as printed)
2. existing = search account.move where partner_id = vendor and ref = ref and move_type in (in_invoice, in_refund)
3. if existing: link it, mark posted (or "already in ERP" exception if it wasn't created by us), stop
4. create account.move (state draft) with lines + PO links + taxes
5. attach the original file
6. if org setting post_bills = true: call action_post
7. save erp_id, erp_url; transition posted
```

Each step's result is stored, so a retry after a crash continues instead of creating a second bill (an `ErpPostAttempt` row with step markers).

### Sync

- Every 15 min (beat), incremental by `write_date`: vendors, POs, receipts and bills. Accounts and taxes sync hourly.
- Local mirror tables (`erp_vendor`, `erp_po`, `erp_po_line`, `erp_receipt_line`, `erp_bill_ref`) make checks fast and testable without Odoo running.
- A "Sync now" button for admins.

### Seed data for the demo

The `infra/odoo/seed.py` script uses JSON-RPC to create:
- A company "Indus Retail (Pvt) Ltd" in PKR, with 16% and 18% sales tax on purchases.
- 8 vendors with tax ids and bank accounts. One of them will receive a "changed bank account" invoice.
- 12 purchase orders across them, some fully received, some partly received, one not received.
- Utility and service vendors (internet, electricity, cleaning) on the non-PO list.

## Other ERPs (later)

| ERP | Approach |
|---|---|
| QuickBooks Online / Xero | REST APIs with OAuth; bills + attachments; good next adapters for international freelance clients |
| SAP Business One / Dynamics 365 BC | Service Layer / OData; enterprise pilots |
| Anything with a web UI only | `watchonce` adapter |
| Anything else | `csv_export` |
