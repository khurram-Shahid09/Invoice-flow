# 04 · Tech Stack

Same core as WatchOnce, so patterns and code can be reused ([ADR-0004](adr/0004-reuse-watchonce-stack.md)).

## Backend

| Concern | Choice | Notes |
|---|---|---|
| Language / runtime | Python 3.13, managed with **uv** | |
| Web framework | **Django 6 + DRF** | Admin for back-office fixes; SSE via async views |
| Background jobs | **Celery 5** with Redis broker, queues `ingest`, `extract`, `check`, `post`; **celery beat** | `--pool=solo` on Windows for dev |
| Database | **PostgreSQL 16** | `pg_trgm` for fuzzy vendor and duplicate matching |
| File storage | **S3 API**: SeaweedFS locally (MinIO no longer publishes images), Cloudflare R2 in the demo deployment | Content-addressed by sha256 |
| PDF handling | **pypdfium2** (render pages), **pdfplumber** (text layer with word boxes), **pypdf** (split, metadata) | All pure-Python wheels, no system installs |
| Images | **Pillow** (+ EXIF orientation fix, resize) | |
| LLM | Pluggable provider: **Gemini 3.5 Flash** (default, cheap), **Claude** (`claude-sonnet-5-5`) for comparison, **fake** for tests | Structured JSON output with a schema; see [06](06-ai-extraction.md) |
| Validation | **Pydantic v2** models for the extraction schema and check results | Same models generate JSON Schema for the LLM |
| Fuzzy matching | `rapidfuzz` + `pg_trgm` | Vendor names, line descriptions |
| Money | `Decimal` everywhere, `django-money`-style (amount, currency) pairs | No floats |
| Email in | `imap-tools` (prod); **Mailpit** HTTP API (dev) | |
| Email out | Django email → Mailpit (dev), Resend or SMTP (prod) | |
| Slack (optional) | Slack Bolt for Python, interactive buttons | |
| ERP | Odoo **JSON-RPC external API** via `httpx` | No Odoo Python dependency |
| Encryption | `cryptography` (Fernet / AES-GCM) for bank details | Key from env, rotatable |
| Lint / types / tests | ruff, mypy, pytest + pytest-django, factory_boy, freezegun | |

## Frontend

| Concern | Choice |
|---|---|
| Framework | **Next.js 16** (App Router), TypeScript, React 19 |
| Styling | Tailwind CSS 4, shadcn/ui-style components |
| Document viewer | `react-pdf` (pdf.js) for PDFs; `<img>` for photos; SVG overlay for evidence boxes |
| Data | Server components + BFF route handlers (same pattern as WatchOnce); SSE for live status |
| Charts | Recharts for the metrics page |
| Tests | Vitest + Playwright for end-to-end |

## Infrastructure (local)

`docker compose -f infra/docker-compose.yml up -d` starts these (Odoo only with `--profile erp`):

| Service | Port | Notes |
|---|---|---|
| PostgreSQL 16 (InvoiceFlow) | **5435** | WatchOnce uses 5433, so both can run |
| Redis 7 | **6380** | |
| SeaweedFS (S3) | **9100** | Same image as WatchOnce |
| Mailpit | **1026** SMTP / **8026** web + API | Inbound test mailbox and outbound approvals |
| Odoo 18 Community + its own Postgres | **8069** | Seeded with demo company, vendors, POs, receipts |

App processes (outside Docker, for fast reload):

| Process | Port |
|---|---|
| Django API (uvicorn) | **8100** |
| Next.js dashboard | **3100** |
| Celery worker(s) + beat | – |

**Memory:** Odoo + its Postgres need about 1.5 GB of RAM. When building the portfolio, this machine ran low on memory, so stop WatchOnce's services while working on InvoiceFlow.

## Why not…

| Option | Reason not chosen |
|---|---|
| Tesseract / cloud OCR first | Multimodal LLMs read scans and photos directly; one call instead of OCR + parsing. Text layer is still used for grounding when present. |
| LangChain / agent frameworks | The pipeline is fixed and deterministic; a framework adds weight without value. Plain provider clients + Pydantic. |
| n8n | Great for glue, but the product's value (grounding, matching, audit) needs real code and tests. An n8n node calling the InvoiceFlow API is a nice v0.2 extra. |
| Vector DB | Not needed: vendor hints and history are small, structured and per vendor. |
