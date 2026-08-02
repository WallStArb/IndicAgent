# Platform API

**Version:** 2.8
**Last Updated:** 2026-05-29
**Status:** current

---

## Purpose

The IndicAgent API (`src/api/main.py`) is the primary interface for external consumers — the Next.js dashboard, research notebooks, and any tooling that needs to query signals, features, or stream real-time data. It is a read-only FastAPI service; all writes happen inside the pipeline via Kafka and the writer agents.

**Readers:** Engineers adding new API endpoints; dashboard developers; anyone debugging SSE stream issues or API startup failures.

---

## Design Principles

### Why SSE for real-time instead of WebSocket?

Server-Sent Events (SSE) are unidirectional — server pushes, client receives. The dashboard only needs to receive data, never send. SSE advantages:

- **Automatic reconnection:** Browser `EventSource` handles reconnect natively, with backoff. WebSocket requires custom reconnect logic.
- **HTTP/1.1 compatible:** SSE works through standard HTTP infrastructure. WebSocket requires a protocol upgrade.
- **Simpler server code:** No bidirectional state machine; the API just fans Kafka messages to the HTTP response stream.
- **Firewalls/proxies:** SSE flows through standard HTTP proxies without special configuration.

SSE is the right answer when the client never needs to send data back. If bidirectional communication becomes necessary, migrate the relevant endpoint to WebSocket.

### API-first rationale

The dashboard, research tools, and any external integrations access data through the API, not direct DB queries. This provides:
- A stable contract: table schema changes do not break consumers
- Rate limiting and auth (planned) at a single enforcement point
- OTel instrumentation on all access patterns (request rate, latency, errors)

### What's in the API vs. direct DB access

| Access method | Use case |
|---------------|---------|
| API (`/api/v1/*`) | Historical queries from the dashboard, external tools |
| API (`/stream/*`) | Real-time data for the dashboard |
| Direct DB | Ad-hoc ops queries (`PGPASSWORD=postgres psql ...`), migration scripts, backfill tools |
| Direct Kafka | Service-to-service (never cross the API for internal pipeline traffic) |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FastAPI Service                             │
│                        (:8000, uvicorn)                             │
├─────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐     │
│  │  Health Router  │  │   API Router    │  │   SSE Router    │     │
│  │   /health/*     │  │    /api/v1/*    │  │    /stream/*    │     │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘     │
│           │                     │                     │              │
│           ▼                     ▼                     ▼              │
│  System Health            REST Queries           Kafka→SSE fanout   │
│  DB connectivity          TimescaleDB            Redpanda topics    │
└─────────────────────────────────────────────────────────────────────┘
```

**Entry point:** `src/api/main.py`
**Run:** `uvicorn src.api.main:app` (port `:8000`)

### Router registration

```python
app.include_router(health.router, prefix="/health")
app.include_router(api.router,    prefix="/api")
app.include_router(stream.router, prefix="/stream")
```

### Health router prefix gotcha

The health router prefix is `/health`, NOT `/api/health`. This is set at `src/api/main.py:196` (verified 2026-08-01, was cited at `:131`). Routes are:
- `GET /health/system`
- `GET /health/database`
- `GET /health/kafka`

**If you write code expecting `/api/health/...` it will 404.** The `api_health` OTel gauge tracks database connectivity and is updated by the background health check task.

---

## Data Contracts

### Health endpoints

`GET /health/system` — Fleet-wide service status
`GET /health/database` — TimescaleDB connectivity
`GET /health/kafka` — Redpanda connectivity

Response shape:
```json
{
  "status": "healthy",
  "timestamp": "2026-05-29T12:00:00Z",
  "checks": {
    "database": "ok",
    "kafka": "ok"
  }
}
```

The `api_health` gauge is set to `1` (healthy) or `0` (unreachable) by the background `_refresh_api_health` task. Grafana fires a page-severity alert when `api_health < 1`.

### API router (`/api/v1/*`)

Read-only REST queries against TimescaleDB. All endpoints support time range filtering (`start`, `end` as ISO 8601) and `symbol`/`timeframe` filters. DB access uses asyncpg via `get_connection()` from `src/core/database_manager.py`.

Endpoint groups:
- `GET /api/v1/bars` — Historical OHLCV from `market_data_ohlcv` (primary time: `timestamp`)
- `GET /api/v1/features` — Intelligence feature vectors from `intelligence_features` (primary time: `ts`)
- `GET /api/v1/signals` — Signal ledger from `signal_ledger` (primary time: `timestamp`)
- `GET /api/v1/signal/:id` — Single signal detail
- `GET /api/v1/metrics` — Performance metrics from `setup_performance`
- `GET /api/v1/llm/calls` — LLM audit log from `llm_calls`

Common query parameters:
| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | string | Asset symbol filter |
| `timeframe` | string | `1m`, `5m`, `15m`, `1h`, `4h`, `1d` |
| `start` | ISO 8601 | Start time (UTC) |
| `end` | ISO 8601 | End time (UTC) |
| `limit` | int | Pagination limit |

DB access pattern:
```python
from src.core.database_manager import get_connection

async def get_bars(symbol: str, start: datetime, end: datetime):
    async with get_connection(settings) as conn:
        rows = await conn.fetch(
            "SELECT timestamp, open, high, low, close, volume "
            "FROM market_data_ohlcv WHERE symbol = $1 "
            "AND timestamp >= $2 AND timestamp <= $3",
            symbol, start, end
        )
        return [dict(row) for row in rows]
```

Consume results **inside** the `async with get_connection()` block. Assigning `rows` outside the block risks `NameError` if `fetch()` raises.

### SSE router (`/stream/*`)

Real-time streams — server fans out Kafka topics to HTTP clients. Clients connect with `EventSource` and optionally filter via query parameters.

Streams:
- `GET /stream/bars` — Canonical 1m bars
- `GET /stream/bars/htf` — HTF bars (5m-1d)
- `GET /stream/intelligence` — I1-I7 feature vectors
- `GET /stream/signals` — I7 signals
- `GET /stream/lifecycle` — Signal lifecycle updates
- `GET /stream/llm` — LLM calls

Client-side filtering via query params reduces bandwidth:
```
GET /stream/signals?symbol=ES&timeframe=5m&min_confidence=0.7
```

Dashboard usage:
```javascript
const es = new EventSource('http://localhost:8000/stream/signals?symbol=ES&timeframe=5m');
es.onmessage = (e) => console.log(JSON.parse(e.data));
// Reconnect on error is handled automatically by EventSource
```

---

## How To Extend

### Adding a new endpoint

1. Identify the router: health check → `health.py`, DB query → `api.py`, real-time stream → `stream.py`.
2. Add the route function with asyncpg DB access or Kafka consumer as appropriate.
3. Add OTel instrumentation — `FastAPIInstrumentor` auto-instruments HTTP metrics, but add custom spans for expensive operations:
   ```python
   from src.observability.spans import observed_span, ATTR_SYMBOL

   @router.get("/api/v1/expensive")
   async def expensive_query(symbol: str):
       with observed_span("expensive_query", attributes={ATTR_SYMBOL: symbol}):
           async with get_connection(settings) as conn:
               return await conn.fetch(...)
   ```
4. Add to `docs/reference/api/rest-endpoints.md` if it is a public endpoint.

---

## Failure Modes & Operations

### uvicorn watchdog integration

The API emits `sd_notify` watchdog pings from a background `_refresh_api_health` task. This task:
1. Probes TimescaleDB connectivity
2. Updates the `api_health` gauge (1 = up, 0 = down)
3. Sends `sd_notify WATCHDOG=1` to satisfy the systemd watchdog

If TimescaleDB becomes unreachable, `api_health` drops to 0 and the Grafana alert fires, but the API continues serving cached/historical data. The watchdog ping is suppressed only if the task itself crashes.

Symptoms of a missing `NotifyAccess=main` in `indicagent-api.service`:
- `watchdog_notify_suppressed_total{agent_id="indicagent-api"}` increments
- Service auto-restarts every 60s

### Common API startup failures

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Address already in use` on `:8000` | Old uvicorn process still running | `kill $(lsof -ti:8000)` |
| `asyncpg.exceptions.ConnectionDoesNotExistError` | TimescaleDB not ready | Wait for `indicagent-timescaledb-ready.service` |
| `Could not connect to Kafka` | Redpanda not ready | Wait for `indicagent-redpanda-ready.service` |
| SSE stream disconnects immediately | Kafka consumer group conflict | Check `group_id` in SSE consumer — use `sse-consumer-<stream>` pattern |
| 404 on `/api/health/*` | Wrong prefix — should be `/health/*` | Update client to use `/health/system`, `/health/database` |
| OTel not emitting | Collector unreachable | API continues running; check `docker ps | grep otel-collector` |

### Checking API health

```bash
# Service status
systemctl status indicagent-api

# Health endpoints
curl http://localhost:8000/health/system
curl http://localhost:8000/health/database

# Metrics (OTel push — no /metrics endpoint)
# Use Prometheus: http://localhost:9090
# Query: http_server_requests_total

# Logs
tail -20 logs/api_agent.log
```

---

## See Also

- **[platform-foundation.md](platform-foundation.md)** — Infrastructure model, Docker, systemd
- **[platform-observability.md](platform-observability.md)** — OTel metrics, SLO alerts, span usage
- **[reference/api/rest-endpoints.md](../reference/api/rest-endpoints.md)** — Full endpoint reference
- **[reference/api/sse-protocol.md](../reference/api/sse-protocol.md)** — SSE protocol details
