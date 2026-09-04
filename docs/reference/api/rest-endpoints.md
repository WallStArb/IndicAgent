<!-- generated-by: gsd-doc-writer -->
# REST API Endpoints

**Version:** 3.0
**Status:** current
**Last Updated:** 2026-09-04

FastAPI backend routes. Server: `uvicorn src.api.main:app` on `:8000`. Verified 2026-09-04 against `src/api/main.py` router registration (`app.include_router(...)`) and `@router.get/post/put/delete` decorators in every file under `src/api/routes/`.

---

## Root & Health

Registered directly on `app` (no router prefix) in `src/api/main.py`, plus the `health` router at prefix `/health`:

| Route | Description |
|-------|-------------|
| `GET /` | API identity/version banner |
| `GET /health` | Standards-compliant basic health check (separate from the `health` router below — defined inline in `main.py`) |
| `GET /metrics` | **Not a metrics endpoint.** Always returns `404` with JSON guidance: metrics are served by the OTel Collector at `:8889/metrics` (Prometheus scrape format), not by the API process itself. Grafana (`:3001`) points at the Collector, not at this route. |
| `GET /health/` | Basic health check (`health.router`'s own root) |
| `GET /health/database` | Database connectivity check |
| `GET /health/full` | Comprehensive health check — 503 if any component unhealthy |
| `GET /health/system` | Machine-readable system health: lag, DLQ depth, replay gauge, agent heartbeats |

> **Confirmed:** the health router prefix is `/health`, not `/api/health` — `app.include_router(health.router, prefix="/health", tags=["health"])` in `src/api/main.py`. All other routers below are mounted under `/api` (or a deeper `/api/...` prefix), health is the one exception.

---

## Market Data — `market_data.router`, prefix `/api`

| Route | Description |
|-------|-------------|
| `GET /api/market-data/{symbol}/{timeframe}` | Historical OHLCV bars. `limit` query param (default 100, max 1000). Timeframe: 1m/5m/15m/1h/4h/1d |
| `GET /api/symbols` | Active symbols with metadata |

## Instruments — `instruments.router`, prefix `/api`

| Route | Description |
|-------|-------------|
| `GET /api/instruments` | All active instruments |
| `GET /api/instruments/{symbol}` | Single instrument by base symbol |
| `POST /api/instruments` | Insert/upsert (idempotent, `ON CONFLICT (symbol) DO UPDATE`); 201 on success. DB trigger fires `pg_notify` automatically |
| `PUT /api/instruments/{symbol}` | Update `contract_details`/`is_active`; only non-None payload fields applied; 404 if symbol missing |
| `DELETE /api/instruments/{symbol}` | Soft-delete (`is_active=false`) — **not** a hard delete, audit history preserved; 404 if symbol missing |

## Features — `features.router`, prefix `/api`

| Route | Description |
|-------|-------------|
| `GET /api/features/export` | Export `intelligence_features` (v2.x, archived) as Parquet, JSONB tiers flattened into `<tier>_<field>` columns. Required: `symbol`, `timeframe`; optional `from`/`to`; capped at 100,000 rows. **Note:** queries the archived, empty v2.x `intelligence_features` table, not the live `feature_vectors` table — this endpoint currently returns no data against live state |
| `GET /api/features/{symbol}/{timeframe}` | Paginated `intelligence_features` rows (v2.x, same archived-table caveat as above). Accepts base symbols (`ES`) or contract codes (`ESH6`). `limit` max 1000 |

## Signals — `signals.router`, prefix `/api`

All query `signal_ledger`/`setup_performance` (v2.x Signal Ledger Architecture — archived, no live consumer since 2026-07-02; `signal_ledger` is currently an empty view over empty tables, see `docs/reference/db-maintenance.md`). These routes are live code but return no data against the current v2.x-archived state.

| Route | Description |
|-------|-------------|
| `GET /api/signals/active` | Pending/active signals from `signal_ledger`; dashboard SSE-connect pre-populate |
| `GET /api/signals/recent` | Recent signals, `symbol`/`timeframe`/`limit`/`tier` (`hero`\|`monitored`\|`all`) filters, annotated with 30d `setup_performance` |
| `GET /api/signals/stats` | Command-strip metrics: throughput, hero rate, avg confidence, latency P50/P95, rolling PnL |
| `GET /api/signals/heatmap` | Setup x regime performance matrix |
| `GET /api/signals/edge-series` | Edge trend series |
| `GET /api/signals/intraday-heatmap` | Intraday heatmap |
| `GET /api/signals/attribution` | Signal attribution breakdown |
| `GET /api/signals/detail/{signal_id}` | Single signal detail |
| `GET /api/signals/{symbol}` | Signals for one symbol |

## Narrative — `narrative.router`, prefix `/api`

| Route | Description |
|-------|-------------|
| `GET /api/signals/{signal_id}/narrative` | Generate-or-retrieve cached LLM narrative for a signal; idempotent (same `signal_id` always returns the same narrative). Depends on the dormant-pending-design I8 AI stack — see root `CLAUDE.md` |

## AI Stats — `ai_stats.router`, prefix `/api`

| Route | Description |
|-------|-------------|
| `GET /api/ai/stats` | Aggregate AI observability (last 24h): per-agent call counts, latency, token burn, parse success, provider breakdown |
| `GET /api/signals/{signal_id}/ai` | Per-signal swarm agent breakdown from `signal_lineage`/`signal_ai_enrichment` |

## Drift — `drift.router`, prefix `/api/drift`

| Route | Description |
|-------|-------------|
| `GET /api/drift` | Current KS and CUSUM drift state from `drift_state` (degrades gracefully — returns `degraded: true` on DB error rather than 500) |

## Validation — `validation.router`, prefix `/api/validation`

| Route | Description |
|-------|-------------|
| `GET /api/validation/results` | Latest `validation_results` rows, `plugin_name`/`limit` (1-500) filters. Read-only router — no mutating routes exist here |

## Vocabulary — `vocabulary.router`, prefix `/api/vocabulary`

| Route | Description |
|-------|-------------|
| `GET /api/vocabulary/{namespace}` | Codes/labels/groups for a Controlled Vocabulary namespace (see `docs/foundation/controlled-vocabulary-registry.md`). 404 for an unregistered namespace, 503 on genuine backend failure — the two are deliberately not collapsed into one status |

## SSE

`GET /api/sse/events` — see [SSE Protocol](sse-protocol.md) for the full streaming contract.

---

**Guide:** [Dashboard Development](../../guides/dashboard-development.md)
