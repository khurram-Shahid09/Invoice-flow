# 17 · Open Questions & Owner Inputs

## Needed from Khurram

| # | Item | Needed by | Notes |
|---|---|---|---|
| N1 | **Confirm the name "InvoiceFlow"** (or pick another) | Day 1 | ✅ Kept (repo `Invoice-flow`). It's a working name. Several products already use similar names, so check before a public launch. Alternatives: *Ledgerly AP*, *PayCheck AI*, *BillPilot*. Code uses `invoiceflow` internally; renaming later is cheap |
| N2 | **AI budget decision** | Day 11 | Gemini free tier is enough to build (fake provider for most tests). For evals and the demo, about **$5** of paid Gemini or Claude credit saves days of waiting on quotas. Free-only also works, just slower |
| N3 | **Docker Desktop running** with ≥ 4 GB memory for containers | Day 1 | ✅ Running. Odoo + Postgres + SeaweedFS + Mailpit. Stop WatchOnce's containers while working on this |
| N4 | **GitHub repo** | Day 1 | ✅ `github.com/khurram-Shahid09/Invoice-flow` (public). Commits use the verified email so they count as contributions. CI won't run until the **GitHub billing lock is fixed** (same issue as WatchOnce) |
| N5 | **Sample real invoices** (optional, 5–20, redacted) | Day 12 | From businesses you know. Black out bank numbers and personal names, or give permission to use them as-is **locally only**. They make the eval far more convincing. Never sent to the Gemini free tier |
| N6 | **Slack workspace** for approval buttons (optional) | Day 13 | A free workspace you control; skip if no time |
| N7 | **Real approval emails** (optional) | Day 15 | A free Resend account + a sender address, only if we host the demo publicly. Locally, Mailpit is enough |
| N8 | **VPS** (optional) | Day 15 | Only if we host the full demo publicly (about $6–15/mo). Otherwise, record locally (see D6) |

N1, N3 and N4 are done; nothing else is needed until day 11 (N2).

## Decisions

| # | Question | Decision / default | Alternatives |
|---|---|---|---|
| D1 | Project | ✅ **AI accounts-payable agent** (option 1 of 5) | Support triage, knowledge agent + MCP, LC checker, sales ops |
| D2 | Stack | ✅ **Same as WatchOnce**: Django + DRF + Celery + Postgres + Redis + Next.js ([ADR-0004](adr/0004-reuse-watchonce-stack.md)) | FastAPI |
| D3 | Reference ERP | ✅ **Odoo 18 Community** via JSON-RPC ([ADR-0003](adr/0003-odoo-reference-erp.md)) | QuickBooks/Xero (v0.2) |
| D4 | AI role | ✅ **Extract only; rules decide** ([ADR-0001](adr/0001-ai-extracts-rules-decide.md)) | – |
| D5 | Default model | **Gemini Flash** for cost; Claude Sonnet in comparisons; final choice after E4 | – |
| D6 | Public demo | **Default: record locally + host a read-only demo mode** (fake ERP + recorded data) on Vercel | Full VPS deployment with Odoo |
| D7 | Repo visibility | ✅ **Public from day 1** (build in public) | – |
| D8 | Currency / locale of the demo company | **PKR, Pakistan sales tax (16% / 18%)**, English UI | USD/AED variant for international clients (generator supports both) |
| D9 | Timeline | 15 working days, demo-able at day 10 | 8-day faster cut (see [15](15-roadmap-build-plan.md)) |

## Open questions (to settle while building)

1. Should a clerk be allowed to approve below a small amount (e.g. ≤ 5,000 PKR) when they didn't upload or edit it? Default: yes if they have the approver role.
2. Credit notes: auto-link to the original invoice by reference, or always send to review? Default: review in the MVP.
3. Should the straight-through limit be per vendor category as well as per org? Default: per org in the MVP.
4. Withholding tax on services (common in Pakistan): model it as a line or leave it to Odoo's tax config? Default: Odoo tax config, with a note in the bill.
