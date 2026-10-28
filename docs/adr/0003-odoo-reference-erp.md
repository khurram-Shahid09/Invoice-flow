# ADR-0003: Odoo as the reference ERP, behind an adapter

**Status:** Accepted · 2026-10-28

## Context
A credible AP demo needs a real ERP with vendors, purchase orders, goods receipts and bills, so the 3-way match and posting are real, not mocked. The ERP must be free to run locally and have an API.

## Decision
- Use **Odoo 18 Community** in Docker, with the purchase, inventory and invoicing apps, through its JSON-RPC external API with a least-privilege API user.
- All ERP access goes through an `ErpAdapter` interface; a `fake` adapter backs tests, and a `csv_export` adapter works for any ERP.
- Master data is mirrored locally (sync every 15 min) so checks are fast and don't depend on the ERP being up.

## Consequences
- ✅ Real 3-way match data (`qty_received`, `qty_invoiced`) and real bills with PO links in the demo.
- ✅ Odoo is widely used by SMEs in Pakistan, the Gulf and elsewhere, and Khurram has used it at Enigmatix. It's a credible selling point.
- ✅ The adapter makes QuickBooks, Xero or a WatchOnce-driven ERP a contained piece of work.
- ❌ Odoo uses about 1.5 GB of RAM locally; mitigated by the fake adapter for most development.
