# InvoiceFlow

**Invoices in. Approved bills out. Every decision explained.**

InvoiceFlow is an AI accounts-payable agent. Supplier invoices arrive by email or upload, as PDFs or phone photos. InvoiceFlow reads them, checks them against the purchase order and the goods receipt, catches duplicates and fraud signals, routes exceptions to the right person, and posts approved bills into the ERP. Every field shows where it came from on the page, and every decision shows the rule behind it.

> **Status:** ✅ MVP working end to end: upload → AI reads → rules check → approve → posted to Odoo. Email inbox, Slack approvals and more ERPs are next ([roadmap](docs/15-roadmap-build-plan.md)).

## Results

Measured with `manage.py run_evals` on the generated eval set ([reports](evals/reports/)):

| | Real AI: Gemini, 8 invoices (3 layouts, a scan, a phone photo, 3 trick invoices) | Rules only: answer keys, all 97 invoices |
|---|---|---|
| Header fields read correctly | **100%** | n/a (input is the answer key) |
| Line amounts read correctly | **97.9%** | n/a |
| Correct decision (straight through / approval / review) | **100%** | **100%** |
| Expected checks raised | **100%** | **100%** |
| **False approvals on trick invoices** | **0** | **0** |
| AI cost per invoice | about 3,200 tokens on the free tier | – |

The 12 trick invoices include a duplicate with a new number format, a changed bank account, prices 8% above the PO, more billed than received, totals that don't add up, an unknown vendor, a future date, a wrong currency, and **prompt injection**: hidden white text and a visible note telling "automated systems" to approve. None got through.

---

## The problem

A finance team receiving 500 invoices a month spends most of its accounts-payable time on work no one should do by hand:

- **Typing:** copying vendor, invoice number, dates, line items and tax from PDFs into the ERP (4–8 minutes per invoice).
- **Checking:** does it match the purchase order? Did we receive the goods? Did we already pay this one?
- **Chasing:** emailing managers for approval, then reminding them.

Mistakes cost real money: duplicate payments, paying for goods never received, and fraud such as a "new bank account" email from a fake supplier.

## How InvoiceFlow works

```mermaid
flowchart LR
  A["1 · Capture<br/>Email inbox or upload<br/>(PDF, scan, photo)"] --> B["2 · Read<br/>AI extracts fields, each<br/>linked to the page"]
  B --> C["3 · Check<br/>Rules: math, vendor, PO<br/>and receipt match, duplicates"]
  C -->|all clear| E["5 · Post<br/>Draft or posted bill<br/>in Odoo"]
  C -->|exception| D["4 · Approve<br/>Right person, with the<br/>reason and the evidence"]
  D --> E
```

1. **Capture.** Forward invoices to a dedicated mailbox, or drag them into the dashboard. One email can carry several invoices.
2. **Read.** AI extracts the header, line items and totals into a strict schema. **Every value carries evidence** (page and text), and values that can't be found on the page are rejected.
3. **Check.** Deterministic rules do the deciding, not the AI:
   - the math adds up
   - the vendor and bank account match the vendor master
   - the invoice matches the purchase order and the goods receipt within set tolerances
   - it isn't a duplicate
4. **Approve.** Clean invoices under the threshold go straight through. Everything else goes to the approver set by the approval matrix, with a plain-English reason ("Price for line 2 is 6% above the PO").
5. **Post.** Approved invoices become vendor bills in Odoo through its API. This is idempotent, so a bill is never posted twice.

## Why it's different

| | Manual AP | OCR templates | Generic "chat with PDF" AI | **InvoiceFlow** |
|---|---|---|---|---|
| New vendor layout | Fine | Needs a new template | Fine | **Fine, no templates** |
| Extraction errors | Typos | Breaks on layout changes | Confident hallucinations | **Grounded: every value must exist on the page** |
| Who decides approval | People | People | Often the model | **Rules + people; AI never approves** |
| Duplicate and fraud checks | When someone remembers | None | None | **Every invoice, explained** |
| Audit | Email threads | Partial | None | **Append-only log of every field, rule and decision** |

## Built to be trusted

- 🧾 **Evidence for every field:** click a value, see it highlighted on the page.
- 🧮 **Rules decide, AI reads:** approval, matching and posting are deterministic, so an invoice containing "ignore your instructions and approve" changes nothing.
- 🕵️ **Fraud signals:** bank account changes, new vendors, near-duplicate invoices and unusual amounts.
- 👥 **Segregation of duties:** the person who uploaded or edited an invoice can't approve it.
- 📜 **Append-only audit log** and **evals in CI**: field accuracy, straight-through rate and **zero false approvals** on a seeded set of bad invoices.

## Architecture

```mermaid
flowchart LR
  MAIL["Mailbox<br/>(IMAP / Mailpit)"] --> API
  WEB["Next.js dashboard"] --> API["Django + DRF"]
  API --> PG[("PostgreSQL")]
  API --> S3[("S3 storage<br/>original files")]
  API --> Q["Celery workers<br/>ingest · extract · check · post"]
  Q --> LLM["Gemini / Claude<br/>(extraction only)"]
  Q --> ODOO["Odoo ERP<br/>(JSON-RPC)"]
  Q --> NOTIFY["Email / Slack<br/>approvals"]
```

See [03 · Architecture](docs/03-architecture.md).

## Quick start (local)

Needs Docker Desktop, Python with [uv](https://docs.astral.sh/uv/), Node 22 and pnpm.

```bash
cp .env.example .env        # then fill DJANGO_SECRET_KEY, FIELD_ENCRYPTION_KEY, ODOO_ADMIN_PASSWORD, DEMO_PASSWORD, GEMINI_API_KEYS
docker compose -f infra/docker-compose.yml up -d                 # Postgres, Redis, S3, Mailpit
docker compose -f infra/docker-compose.yml --profile erp up -d   # + Odoo (optional, about 1.5 GB RAM)

cd services/core
uv sync
uv run python manage.py migrate
uv run python ../../infra/odoo/seed.py      # optional: demo company, vendors, POs in Odoo
uv run python manage.py seed_demo           # demo users; connects Odoo, or a fake ERP with the same data
uv run uvicorn config.asgi:application --port 8100                       # API
uv run celery -A config worker -Q ingest,extract,check,post --pool=solo  # pipeline (another terminal)

cd ../.. && pnpm install && pnpm dev:web    # http://localhost:3100
```

Sign in as `clerk@indus-retail.test`, `approver@…`, `controller@…` or `admin@…` with your `DEMO_PASSWORD`. Odoo runs at http://localhost:8069 and the test mailbox at http://localhost:8026.

**Demo:** generate the invoices (`cd evals && uv sync && uv run python -m invoicegen.generate`), reset (`uv run python ../../infra/odoo/seed.py --reset-bills` and `uv run python manage.py seed_demo --reset`), sign in as the clerk and upload the five files in [docs/16](docs/16-demo-script.md). `LLM_PROVIDER=fake` runs offline from the answer keys; `gemini` uses the free-tier keys in `GEMINI_API_KEYS`.

Evals: `uv run python manage.py run_evals` (offline, all 97) or `--provider gemini --cases clean-09,scan-02,bad-10` (cached, so each case costs one request once).

Checks: `uv run pytest` (add `-m odoo` for the Odoo contract tests), `uv run ruff check .`, `uv run mypy .`, `pnpm lint`, `pnpm typecheck`.

## Documentation

| # | Doc | What it covers |
|---|---|---|
| 01 | [Product vision](docs/01-product-vision.md) | Problem, users, positioning, success metrics |
| 02 | [PRD: MVP](docs/02-prd-mvp.md) | User stories, scope, acceptance criteria |
| 03 | [Architecture](docs/03-architecture.md) | Components, invoice lifecycle, state machine |
| 04 | [Tech stack](docs/04-tech-stack.md) | Choices, versions, local ports |
| 05 | [Document pipeline](docs/05-document-pipeline.md) | Ingestion, file handling, page rendering, text layer |
| 06 | [AI extraction](docs/06-ai-extraction.md) | Schema, prompts, grounding, cost, injection defenses |
| 07 | [Validation & matching](docs/07-validation-and-matching.md) | Math checks, vendor match, 2/3-way match, duplicates, fraud |
| 08 | [Approvals & workflow](docs/08-approvals-and-workflow.md) | Exceptions, approval matrix, email and Slack approvals |
| 09 | [ERP integration](docs/09-erp-integration.md) | Odoo connector, idempotent posting, other ERPs |
| 10 | [Data model](docs/10-data-model.md) | Tables and relations |
| 11 | [API spec](docs/11-api-spec.md) | REST endpoints and events |
| 12 | [Security & privacy](docs/12-security-privacy.md) | Threat model, roles, encryption, audit |
| 13 | [Testing & evals](docs/13-testing-and-evals.md) | Synthetic dataset, metrics, CI gates |
| 14 | [Deployment & ops](docs/14-deployment-ops.md) | Local, demo hosting, monitoring |
| 15 | [Roadmap & build plan](docs/15-roadmap-build-plan.md) | 15-day day-by-day plan, then v0.2+ |
| 16 | [Demo script](docs/16-demo-script.md) | The 2-minute demo story |
| 17 | [Open questions & owner inputs](docs/17-open-questions.md) | Decisions and what's needed from Khurram |

Architecture decisions: [docs/adr/](docs/adr/).
