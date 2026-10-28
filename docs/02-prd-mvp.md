# 02 · PRD: MVP (v0.1)

## Goal

A working, deployed AP agent that takes invoices from an inbox or upload to a posted Odoo vendor bill, with grounded extraction, deterministic checks, approvals and an audit trail, proven by an eval suite and a 2-minute demo.

## Scope

### In scope
- Ingestion: dashboard upload (multi-file), email inbox (Mailpit locally, IMAP in production), API upload.
- File types: PDF (text and scanned), JPG/PNG phone photos, multi-page; several invoices in one email.
- Extraction: header fields, line items, tax, totals, bank details; credit notes recognised as such.
- Validation: math, dates, currency, tax-rate sanity, required fields.
- Vendor matching against the vendor master (synced from Odoo).
- Purchase order matching: 2-way (invoice ↔ PO) and 3-way (invoice ↔ PO ↔ goods receipt) with tolerances.
- Duplicate detection (exact and fuzzy) and fraud signals (bank account change, new vendor, unusual amount).
- Non-PO invoices: expense account suggestion from vendor history.
- Exception queue, approval matrix by amount, approve or reject in app and by email link; Slack optional.
- Posting to Odoo as a vendor bill (draft or posted, configurable), idempotent.
- Organisations, users, roles; segregation of duties; append-only audit log.
- Dashboard: inbox, invoice review screen (document viewer with evidence highlights), exceptions, approvals, rules settings, metrics.
- Eval harness with a synthetic invoice generator and seeded bad invoices; results in CI.

### Out of scope (later)
- Payments and bank files; early-payment discount optimisation.
- ERPs other than Odoo (adapter interface is designed for them).
- Receipts and expense reports, letters of credit, sales invoices.
- Mobile app; SSO/SCIM; multi-currency FX revaluation.

## User stories and acceptance criteria

### Capture
**US-1. As an AP clerk, I forward supplier emails to `ap@<org>` and the invoices appear in my inbox.**
- Each attachment becomes a document; non-invoice attachments (logos, terms PDFs) are classified as "not an invoice" and kept, not processed.
- The source email (sender, subject, received time) is linked to each invoice.
- The same file sent twice is detected by file hash and linked, not processed again.

**US-2. As an AP clerk, I drag 20 PDFs into the dashboard and see each one move through stages live.**
- Progress updates without refresh (SSE). Each card shows: Received → Reading → Checking → Ready / Needs review / Approved / Posted.

### Read
**US-3. As an AP clerk, I open an invoice and see every extracted value next to the document, and clicking a value highlights it on the page.**
- Every field has evidence: page number, the source text and a bounding box when the text layer exists.
- Values with no evidence are shown empty and flagged "Not found on the document", never guessed.

**US-4. As an AP clerk, I can correct a field; the correction is logged and the checks re-run.**
- Edits create an audit entry (old → new, who, when) and re-run validation and matching.
- Corrections are stored per vendor as hints for future extraction ("this vendor's invoice number is the field labelled 'Bill No.'").

### Check
**US-5. As a finance controller, I trust that the numbers were checked.**
- Line totals = qty × unit price (± rounding), subtotal = Σ lines, total = subtotal + tax − discount; tolerance 0.01 per line and 0.05 per document, configurable.
- Invoice date not in the future and not older than the configured limit; due date ≥ invoice date.
- Currency matches the vendor's or PO's currency.

**US-6. As a finance controller, an invoice is matched to its PO and receipt automatically.**
- The PO number is extracted or inferred (vendor + amounts); lines are matched by product code, then description similarity.
- Exceptions: price variance above tolerance (default 2%), quantity invoiced above quantity received, PO already fully invoiced, PO closed or missing.

**US-7. As a finance controller, duplicates never get through.**
- Exact: same vendor + normalised invoice number. Fuzzy: same vendor + same total + date within 7 days, or same file hash. Each shows the matched earlier invoice.

**US-8. As a finance controller, I'm warned about fraud signals.**
- Bank account on the invoice differs from the vendor master → **blocking exception**, regardless of amount.
- New vendor (no master record), amount more than 3× the vendor's median, invoice from a free email domain that the vendor doesn't normally use → warnings.

### Approve
**US-9. As an approver, I get an email with the reason, the key numbers and Approve / Reject buttons, and I can approve without logging in.**
- Signed, single-use, expiring links (72 h); a reject asks for a reason.
- The approver is chosen by the approval matrix (amount bands, department or vendor category).
- The uploader or last editor of an invoice can't approve it (segregation of duties).

**US-10. As a finance controller, clean invoices under my threshold go straight to Odoo with no one touching them.**
- Straight-through only when: all checks pass, vendor known, no fraud signal, matched PO (or vendor is on the non-PO list), amount ≤ threshold.

### Post
**US-11. As a finance controller, approved invoices appear in Odoo as vendor bills with the PDF attached.**
- Lines, taxes, PO link, due date and reference are set; the original file is attached.
- Posting is idempotent: retries never create a second bill (lookup by vendor + reference before create).
- Odoo errors are shown in plain English and the invoice goes to "Posting failed", retryable.

### Oversee
**US-12. As a controller, I see a metrics page:** invoices processed, straight-through rate, exceptions by reason, average time to approve, AI cost.

**US-13. As an auditor, I can see the full history of any invoice:** every extraction, edit, rule result, approval and post, in order, and export it as PDF or CSV.

## Non-functional requirements

| Area | Requirement |
|---|---|
| Performance | p50 < 30 s from upload to "Ready" for a 2-page PDF; 100 invoices queued without errors |
| Cost | ≤ 1 AI call per invoice in the normal path; per-org monthly AI budget enforced |
| Reliability | Every stage is a retryable Celery task; idempotent stage transitions; dead-letter state with a reason |
| Security | Roles, segregation of duties, bank details encrypted at rest, signed approval links, audit log, file type and size limits |
| Privacy | Documents stay in the org's storage; AI provider receives only the document being processed; no training on customer data (provider settings) |
| Accessibility | Keyboard-usable review screen; colour is never the only signal for an exception |

## MVP done means

1. The demo in [16](16-demo-script.md) runs end to end on the deployed version.
2. Evals in [13](13-testing-and-evals.md) meet targets, including **0 false approvals**.
3. Backend and web tests, lint and type checks pass in CI.
4. Docs updated; a case-study page on the portfolio; demo video recorded.
