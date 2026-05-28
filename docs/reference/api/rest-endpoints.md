<!-- generated-by: gsd-doc-writer -->
# REST API Endpoints

**Version:** 2.8
**Status:** current
**Last Updated:** 2026-05-27

FastAPI backend routes. Server: `uvicorn src.api.main:app` on `:8000`.

---

## Health & Metrics

`GET /health/system` — System health check (services, pipeline status)
`GET /health/database` — Database connectivity check
`GET /metrics` — OTel/Prometheus metrics endpoint (scrape target for Grafana at :3001)

> **Note:** The health router prefix is `/health` (not `/api/health`). Routes are `/health/system`, `/health/database`, etc. Registered at `src/api/main.py` as `app.include_router(health.router, prefix="/health", ...)`.

---

## Market Data

[TODO: Document market data endpoints]

---

## Indicators

[TODO: Document indicator endpoints]

---

**Guide:** [Dashboard Development](../../guides/dashboard-development.md)
