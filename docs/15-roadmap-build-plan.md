# 15 · Roadmap & Build Plan

## Phases

| Phase | Goal | Duration (est.) | Exit criteria |
|---|---|---|---|
| **MVP (v0.1)** | Capture → extract → check → approve → post, with evals | **15 working days** (~3 weeks) | Demo video, evals at target, portfolio case study |
| **v0.2** | Daily use | 2–3 weeks | Vendor reply emails (reject / ask for corrected invoice), Slack approvals GA, QuickBooks or Xero adapter, `watchonce` adapter, n8n node, receipts and expenses |
| **v0.3** | Document AI platform | 3–4 weeks | Letter of credit checker (reuses extraction + cross-document rules), statements reconciliation, multi-entity |
| **Pilot** | 1–3 real teams | 4–6 weeks | Real invoices processed weekly; measured hours saved, STP rate, caught duplicates |

## Daily rhythm while building

Earning comes first (see `D:\career\7-day-plan.md`). Each day:
- **2–3 h selling:** proposals, messages, follow-ups.
- **5–6 h building:** this plan.
- Every few days, a short clip of progress goes on LinkedIn. Build in public: it attracts clients for offer B ("PDFs and invoices into a spreadsheet").

## MVP day-by-day

A **demo-able cut lands at day 10**. Days 11–15 harden it, run evals and launch.

### Week 1: foundations, documents, extraction
| Day | Deliverable | Done when |
|---|---|---|
| **D1** | Repo scaffold (uv + pnpm), `infra/docker-compose` (Postgres, Redis, SeaweedFS S3, Mailpit, Odoo), Django project with settings split, accounts/orgs/memberships/roles, audit app with the insert-only trigger, Next.js shell with login, CI (ruff, mypy, pytest, eslint, tsc, gitleaks) | `docker compose up` + login works; CI green |
| **D2** | **Odoo seed** script (company, taxes, vendors, POs, receipts, non-PO vendors) + **ERP adapter** (odoo + fake) + **sync** to mirror tables | `manage.py erp_sync` fills the mirror; contract tests pass |
| **D3** | **Synthetic invoice generator**: 10 layouts, linked to the seed data, ground truth JSON, scan/photo degradations, the safety set | `evals/data/` has 60 clean + 20 degraded + 12 bad invoices |
| **D4** | **Document pipeline:** upload API, magic-byte checks, S3 storage, sha256 dedup, page rendering, text layer with boxes, Mailpit inbound poller | Upload and email both create documents with page images and words |
| **D5** | **Extraction:** Pydantic schema, provider interface (fake, Gemini, Claude), prompt v1, retries/fallback, cost recording, budget | An invoice goes `received → extracting → checking` with fields saved |

### Week 2: grounding, checks, review, approvals
| Day | Deliverable | Done when |
|---|---|---|
| **D6** | **Grounding + normalisation** (exact / fuzzy / model-only, bbox), hidden-text detector, state machine + SSE events | Values not on the page are cleared and flagged; unit tests |
| **D7** | **Checks:** validation rules, vendor matching, duplicates, fraud signals, routing decision, rules versioning | All rule unit tests; the safety set routes correctly with the fake provider |
| **D8** | **PO matching:** PO finding, line matching, 2-way and 3-way tolerances, `GRN_PENDING` waiting + auto recheck after sync, non-PO account suggestion | Match tests against the seed POs |
| **D9** | **Dashboard:** inbox with live status, invoice review screen (PDF viewer + evidence highlight + field editing + check list), duplicates panel | Review a flagged invoice end to end in the browser |
| **D10** | **Approvals:** approval matrix, requests, signed email links, approver pages, segregation of duties, "My approvals". **Posting** to Odoo (idempotent, attachment). ✅ **Demo-able cut** | Upload → approve by email link → bill visible in Odoo |

### Week 3: evals, hardening, launch
| Day | Deliverable | Done when |
|---|---|---|
| **D11** | **Eval harness** E1–E3 with caching and reports; E3 (fake) in CI; first real-provider run on a batch of 20 | First report committed |
| **D12** | Tune prompt v2 and vendor hints from the E1 errors; E2 grounding stats; E4 Gemini vs Claude on 20 invoices (small budget) | Targets met or gaps documented |
| **D13** | **Metrics page**, invoice history + PDF export, reminders/escalation (beat), notifications, Slack approvals (if time) | Metrics show real numbers from the eval runs |
| **D14** | **Hardening:** tenant-isolation tests, signed-link tests, upload fuzz, Sentry, `/readyz`, rate limits, backups script, README quick start, `.env.example` | Security test list in [12](12-security-privacy.md) passes |
| **D15** | **Launch:** demo data reset command, record the demo ([16](16-demo-script.md)), portfolio case-study page + CV line, LinkedIn post, optional VPS deploy | Video published; portfolio live |

## Faster cut (if time is short)

To reach a demo in 8 days:
- Skip Slack, email ingest (upload only), the metrics page and the Claude provider.
- Keep the 3-way match and **the safety set**, because they are the story.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Gemini free-tier quota (about 20 requests/day/model) | Evals take days | Fake provider in CI; cache results; run batches daily; small paid budget for D11–D12 (decision N2) |
| Odoo memory use on this machine | Slow dev, crashes | Stop WatchOnce services while working; use the fake ERP for most tests; Odoo only for D2, D10 and the demo |
| Line-item extraction on poor photos | Lower accuracy | Report scans separately; route low-trust to review (safe by design) |
| Scope creep (receipts, more ERPs) | Late MVP | Everything beyond this list goes to v0.2 |
