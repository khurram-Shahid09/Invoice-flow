# ADR-0004: Reuse the WatchOnce stack and patterns

**Status:** Accepted · 2026-10-28

## Context
WatchOnce already has working, tested patterns:
- Django + DRF with org scoping and an audit log
- Celery queues
- Redis pub/sub to SSE
- a Next.js dashboard with BFF routes
- a pluggable LLM provider (Gemini, Claude, fake) with cost tracking and retries
- quotas, evals in CI and a demo video pipeline

The goal is to ship in 15 working days.

## Decision
- Use the same stack and copy (not share) the relevant modules as a starting point: provider wrapper, SSE streaming, audit helper, quotas, video pipeline.
- Keep it a separate repository and product. No runtime dependency on WatchOnce; the `watchonce` ERP adapter (v0.2) calls WatchOnce over its public API.

## Consequences
- ✅ Faster start; consistent engineering story across the portfolio.
- ✅ Interview talking point: the same architecture pattern applied to a second domain.
- ❌ Some duplicated code between the two repos. Acceptable for two products; extract a shared package only if a third appears.
