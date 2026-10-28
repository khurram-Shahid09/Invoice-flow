# 14 · Deployment & Ops

## Local development

```
docker compose -f infra/docker-compose.yml up -d                 # Postgres 5435, Redis 6380, S3 9100, Mailpit 8026
docker compose -f infra/docker-compose.yml --profile erp up -d   # + Odoo 8069 (about 1.5 GB RAM)
cd services/core
uv sync
uv run python manage.py migrate
uv run python manage.py seed_demo         # org, users, rules, ERP connection to local Odoo
uv run python ../../infra/odoo/seed.py    # company, vendors, POs, receipts in Odoo
uv run uvicorn config.asgi:application --port 8100
uv run celery -A config worker -Q ingest,extract,check,post --pool=solo -l info
uv run celery -A config beat -l info
cd ../../apps/web && pnpm dev             # http://localhost:3100
```

- Demo users: `clerk@demo`, `approver@demo`, `controller@demo`, `admin@demo` (password from `.env`, never committed).
- Send a test invoice: `uv run python ../../evals/send_test_email.py evals/data/demo/INV-2291.pdf` (SMTP to Mailpit), then watch it arrive in the dashboard.
- Approval emails appear in Mailpit at http://localhost:8026.

## Demo deployment (low cost)

| Part | Where | Cost |
|---|---|---|
| Dashboard | Vercel (free) | $0 |
| API, workers, beat, Postgres, Redis | One VPS (4 GB+ RAM) with Docker Compose + Caddy (HTTPS via `sslip.io` hostname) | about $6–15/mo |
| Odoo demo | Same VPS (needs about 1.5 GB) or Odoo's free online trial for screenshots | included |
| Files | Cloudflare R2 (free tier) | $0 |
| Email | Mailpit on the VPS behind basic auth (demo); Resend free tier for real approval emails | $0 |
| AI | Gemini Flash (synthetic invoices only on the free tier) | $0–5 |

A cheaper alternative for the portfolio: **record the demo locally and don't host Odoo publicly**. Host only the dashboard with the fake ERP adapter and the fake LLM in "demo mode" (read-only sample data). This is decision D6 in [17](17-open-questions.md).

## Configuration (`.env` keys)

`DJANGO_SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`, `S3_ENDPOINT`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, `APPROVAL_LINK_SECRET`, `LLM_PROVIDER`, `LLM_FALLBACK_PROVIDER`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `MAIL_INBOUND` (mailpit/imap), `IMAP_HOST`, `IMAP_USER`, `IMAP_PASSWORD`, `EMAIL_URL`, `SLACK_ENABLED`, `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SENTRY_DSN`, `DEMO_PASSWORD`.

`.env.example` lists them all with safe placeholders; the real `.env` is gitignored.

## Monitoring

- **Sentry** for the API, workers and web.
- **Health endpoints:** `/healthz` (process), `/readyz` (DB, Redis, S3, ERP connection status).
- **Queue health:** a beat task records queue lengths every minute. A warning fires when `extract` has waited > 5 minutes.
- **Business alerts:** posting failures, `BANK_CHANGED`, AI budget 80%.
- **Metrics page** (in-app) covers business KPIs. There's no separate Prometheus in the MVP.

## Backups

- Nightly `pg_dump` to R2, kept 14 days (VPS cron).
- R2 bucket versioning on.
- A restore test is documented and run once before calling the deployment "done".

## Runbook (short)

| Symptom | Check | Fix |
|---|---|---|
| Invoices stuck in `received` | worker logs; AI budget; provider status | restart the worker; raise the budget; switch `LLM_PROVIDER` |
| Many `extraction_failed` | Sentry; provider 429s | wait for quota; fallback model; reprocess with `manage.py reprocess --status extraction_failed` |
| Posting failed | invoice page shows the Odoo error | fix the data (tax/account mapping) or the API user rights; retry |
| ERP sync stale | `/readyz`, `erp_connection.last_sync_at` | test the connection; rotate the API key |
