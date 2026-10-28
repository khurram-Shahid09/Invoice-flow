# 11 · API Spec

Base: `/api/v1`. JSON. Auth: session/JWT for the dashboard, `Authorization: Bearer <token>` for API tokens. Every resource is scoped to the caller's current org (`X-Org` header or the token's org). Errors use `{"error": {"code": "...", "message": "...", "fields": {...}}}`.

## Auth and org

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/login` | email + password → tokens |
| POST | `/auth/refresh` | |
| GET | `/me` | user, memberships, roles |
| GET / PATCH | `/org` | settings (controller/admin) |
| GET / POST / DELETE | `/org/members` | admin |
| GET / POST / DELETE | `/tokens` | personal API tokens |

## Documents and invoices

| Method | Path | Notes |
|---|---|---|
| POST | `/documents` | multipart `files[]` (≤ 20). → `201 {documents: [{id, status, duplicate_of?}]}` |
| GET | `/documents/{id}` | metadata + pages (signed image URLs, 10 min) |
| GET | `/documents/{id}/file` | redirect to a signed URL of the original |
| GET | `/invoices` | filters: `status`, `vendor`, `q`, `has_code`, `date_from/to`, `assigned_to_me`; cursor pagination |
| GET | `/invoices/{id}` | fields with evidence, lines, latest check run, duplicates, approvals, ERP status |
| PATCH | `/invoices/{id}/fields` | `{fields: {name: value}, lines: [...]}` → re-check; clerk only; audited |
| POST | `/invoices/{id}/recheck` | re-run checks (e.g. after ERP sync) |
| POST | `/invoices/{id}/submit` | send for approval (blockers must be resolved or overridden) |
| POST | `/invoices/{id}/override` | `{code, reason}`: override a blocking result (controller) |
| POST | `/invoices/{id}/duplicates/{link_id}/resolve` | `{resolution: "not_duplicate" \| "confirmed", reason}` |
| POST | `/invoices/{id}/reject` | `{reason}` |
| POST | `/invoices/{id}/post` | retry posting (clerk/admin) |
| GET | `/invoices/{id}/history` | audit events for this invoice |
| GET | `/invoices/{id}/history.pdf` | audit report export |
| GET | `/events` | **SSE** stream for the org: `invoice.status`, `invoice.updated`, `approval.requested`, `sync.finished` |

### Invoice object (abridged)

```json
{
  "id": "inv_7Kq2…",
  "status": "awaiting_approval",
  "document": {"id": "doc_…", "filename": "INV-2291.pdf", "pages": 2},
  "vendor": {"id": "ven_…", "name": "Al-Noor Traders", "matched_by": "tax_id"},
  "po": {"number": "P00014", "match": "3-way"},
  "fields": {
    "invoice_number": {"value": "INV-2291", "page": 1, "bbox": [412, 88, 486, 101], "grounding": "exact", "trust": "high"},
    "total": {"value": "184500.00", "page": 2, "bbox": [455, 610, 530, 624], "grounding": "exact", "trust": "high"}
  },
  "lines": [{"description": "A4 paper 80gsm", "quantity": "50", "unit_price": "1450.00", "line_total": "72500.00", "po_line": "pol_…"}],
  "checks": [{"code": "PO_PRICE_VARIANCE", "severity": "info", "message": "Line 2 price is 1.2% above the PO (within 2% tolerance)."}],
  "decision": {"route": "approval", "reason": "Above the 50,000 PKR straight-through limit", "rules_version": "2026.11.1"},
  "approvals": [{"step": 1, "approver": "Sana Ali", "status": "pending", "channel": "email"}]
}
```

## Approvals

| Method | Path | Notes |
|---|---|---|
| GET | `/approvals?mine=1` | pending for me |
| POST | `/approvals/{id}/decide` | `{decision: "approve" \| "reject", reason?}`; enforces segregation of duties and limits |
| POST | `/approvals/bulk` | `{ids: [...], decision: "approve"}`; only items with no warnings |
| GET | `/a/{token}` | **public** signed-link landing page (approve confirms, reject asks reason) |
| POST | `/a/{token}` | performs the decision; single use |
| POST | `/slack/interactions` | Slack interactive callback (signature verified) |

## Rules, vendors, ERP

| Method | Path | Notes |
|---|---|---|
| GET / PUT | `/rules/settings` | tolerances, thresholds, allowed tax rates, toggles |
| GET / PUT | `/rules/approval-matrix` | ordered rules |
| GET | `/vendors` | mirror of ERP vendors + stats |
| PATCH | `/vendors/{id}` | non_po flag, category, known domains |
| POST | `/vendors/{id}/verify-bank` | admin: confirm a changed bank account after a phone check (note required) |
| GET / POST | `/vendors/{id}/hints` | propose / confirm extraction hints |
| GET / PUT | `/erp/connection` | test + save (API key write-only) |
| POST | `/erp/sync` | sync now |
| GET | `/erp/export.csv` | approved bills (csv_export adapter) |

## Metrics

| Method | Path | Notes |
|---|---|---|
| GET | `/metrics/summary?from&to` | processed, straight-through %, exceptions by code, median time to ready / to approve / to post, AI cost |
| GET | `/metrics/timeseries?metric&interval` | daily series for charts |

## Rate limits and quotas

- Uploads: 200 files/hour per org (MVP default).
- AI budget: when the org's monthly AI cost reaches `ai_budget_usd`, extraction pauses (`429 ai_budget_exhausted` on recheck endpoints that would call AI).
