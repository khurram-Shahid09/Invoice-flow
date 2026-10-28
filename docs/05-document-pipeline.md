# 05 · Document Pipeline

How a file becomes pages, text and images ready for extraction.

## Sources

| Source | How | Notes |
|---|---|---|
| Dashboard upload | `POST /api/documents` (multipart, up to 20 files) | Drag and drop; progress via SSE |
| Email | Beat task `poll_mailbox` every 60 s | Dev: Mailpit HTTP API (`GET /api/v1/messages`, then attachments). Prod: IMAP with `imap-tools`, a dedicated mailbox per org, processed messages moved to a folder |
| API | Same upload endpoint with a personal access token | For integrations (n8n, scanners) |

Each email creates an `InboundEmail` row (sender, subject, message id, received at). Its attachments and any PDF links are documents. The message id makes polling idempotent.

## File acceptance

| Rule | Value |
|---|---|
| Allowed types (checked by **magic bytes**, not extension) | PDF, PNG, JPEG, HEIC (converted to JPEG), TIFF |
| Max size | 20 MB per file, 50 pages per PDF |
| Encrypted PDFs | Rejected with "Password-protected PDF: ask the vendor for an unprotected copy" |
| Zip, Office files | Not in MVP (clear rejection message) |
| Inline images in email bodies (logos, signatures) | Ignored below 30 KB or with `Content-Disposition: inline` + small dimensions |

## Storage

- `orgs/<org_id>/files/<sha256>.<ext>`: the original, never modified.
- `orgs/<org_id>/pages/<sha256>/<n>.png`: rendered pages at 150 dpi (max 2000 px long edge).
- Dedup: a unique `(org, sha256)` constraint. A repeat upload links to the existing `Document`.

## Processing steps (extract queue)

1. **Render.** pypdfium2 renders each PDF page to PNG. For photos, the steps are:
   - apply the EXIF orientation
   - convert to RGB
   - resize to a 2000 px long edge
   - optionally auto-crop to the paper (v0.2)
2. **Text layer.** pdfplumber extracts words with boxes (`x0, top, x1, bottom`, page). A page whose text layer has fewer than 20 characters is treated as a scan.
3. **Classify and split** (one cheap step inside the main extraction call, see [06](06-ai-extraction.md)):
   - `document_type`: invoice, credit_note, statement, receipt, other.
   - `invoice_boundaries`: page ranges when one PDF contains several invoices. Each range becomes its own `Invoice` with a link to the same `Document`.
   - `other` → the document is marked **not_invoice** and kept for audit.
4. **Store the raw result.** The model's raw JSON, the provider, the model, the token counts and the cost are saved on an `ExtractionAttempt` row, for evals and audits.

## Page-count limits and cost

- Send at most the first 6 pages to the model (most invoices are 1–2). Longer documents are split by the classifier first, then processed per range.
- Images are sent at the resolution needed (about 1500 px long edge), which keeps tokens low.

## Failure handling

| Failure | Behaviour |
|---|---|
| Corrupt file | `extraction_failed` with "The file could not be opened" |
| AI timeout / 429 / 5xx | Retry with backoff 10 s, 30 s, 90 s; then try the fallback model; then `extraction_failed` (manual entry stays possible) |
| Org AI budget exhausted | Invoice waits in `received` with "Monthly AI budget reached"; admins notified |
