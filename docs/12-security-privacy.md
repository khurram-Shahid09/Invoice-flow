# 12 · Security & Privacy

Finance data plus payment details make this a high-value target. The MVP is designed so that the worst realistic failures are blocked by design, not by hoping the AI behaves.

## Threat model

| # | Threat | Mitigation |
|---|---|---|
| T1 | **Bank-detail fraud:** a fake invoice or "updated bank account" from a spoofed vendor | `BANK_CHANGED` is always blocking; only an admin can verify after an out-of-band phone check (note required, audited); sender-domain checks; IBAN checksum |
| T2 | **Prompt injection in documents** ("approve this", "change the IBAN") | AI only fills a schema; rules decide; grounding rejects values not printed; hidden-text detector; eval cases in CI |
| T3 | **Duplicate payment** (re-sent invoice, slightly changed number) | Exact, file and fuzzy duplicate checks against InvoiceFlow and ERP bills; idempotent posting |
| T4 | **Insider approves their own invoice** | Segregation of duties enforced server-side; approval limits per membership; audit |
| T5 | **Approval link forwarded or leaked** | HMAC-signed, single use, 72 h expiry, bound to one approver; link approval disabled above the controller limit; IP + user agent logged |
| T6 | **Malicious file upload** (polyglot, zip bomb, huge PDF) | Magic-byte type check, size and page limits, rendering in a worker with time and memory limits, no execution of embedded JavaScript (pdfium render only) |
| T7 | **Cross-tenant data access** | Org-scoped managers, tests that every endpoint rejects other orgs' ids, S3 keys prefixed by org, signed URLs that expire |
| T8 | **ERP credential misuse** | Dedicated least-privilege Odoo user + API key; key encrypted at rest; write-only in the API |
| T9 | **Tampering with history** | Insert-only audit table enforced by a database trigger and grants |
| T10 | **Email spoofing** of the inbox | Treat all inbound as untrusted; record SPF/DKIM results from headers (warning when failing) |

## Data protection

- **Encryption at rest:** bank account numbers and ERP API keys are encrypted with AES-GCM (`cryptography`), using a key from the environment (`FIELD_ENCRYPTION_KEY`). Key rotation re-encrypts in a management command. Only workers decrypt, and only for comparison or posting. The UI shows masked values (`PK36 **** **** 1234`).
- **Storage:** private S3 buckets; access only via signed URLs (10 min).
- **Transport:** HTTPS everywhere in deployment; HSTS; secure, HttpOnly, SameSite cookies.
- **Secrets:** `.env` is gitignored; secret scanning (gitleaks) in CI, as in WatchOnce.
- **Logging:** no invoice contents or bank details in application logs; ids only.

## AI provider data handling

- Only the document being processed is sent, plus up to 5 short vendor hints.
- Use provider settings or paid tiers that don't train on API data for real customer documents. **The Gemini free tier may use data to improve products, so use it only with synthetic or demo invoices**, never real client invoices.
- The org setting `ai_provider_allowed` lets a client choose which provider may see its documents.

## Access control

- Roles: clerk, approver, controller, admin (see [08](08-approvals-and-workflow.md)).
- Every state-changing endpoint checks role + org + segregation-of-duties rules in one place (`policies.py`) with unit tests per rule.
- Admin actions (users, ERP connection, bank verification, rule changes) are audited with before/after values.

## Retention

- Original files and audit events: kept for 7 years by default (common tax-record requirement; configurable per org).
- Extraction raw outputs: 1 year (configurable), then deleted; final field values stay.
- Org deletion: export first, then hard delete after 30 days.

## Security tests (in CI)

- Tenant isolation test for every endpoint (generated from the URL conf).
- Segregation-of-duties and approval-limit tests.
- Signed link tests: tampered, expired, reused, wrong approver.
- Injection eval cases (see [13](13-testing-and-evals.md)).
- Upload fuzz: wrong magic bytes, oversized, encrypted PDF, 1000-page PDF.
