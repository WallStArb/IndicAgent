# API-First Design Architecture

**Version:** 2.8
**Last Updated:** 2026-05-28

---

## Overview

IndicAgent follows an API-first design principle where the FastAPI service is the primary interface for external consumers. The API is stateless, DB-query-only, and streams real-time data via Server-Sent Events (SSE).

**Design principles:**
- Stateless (no session state in API)
- DB queries only (no direct Kafka access)
- OTel instrumentation on all routes
- Structured logging via structlog
- Health check endpoints for monitoring

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FastAPI Service                            │
│                        (:8000, uvicorn)                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐    │
│  │  Health Router  │  │   API Router    │  │   SSE Router    │    │
│  │   /health/*     │  │    /api/*       │  │    /stream/*     │    │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘    │
│           │                     │                     │             │
│           ▼                     ▼                     ▼             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐    │
│  │  System Health  │  │   REST Queries  │  │  Kafka Streams  │    │
│  │  DB Connect     │  │   DB Query      │  │  SSE Fanout     │    │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
           │                     │                     │
           ▼                     ▼                     ▼
    ┌──────────┐         ┌──────────┐         ┌──────────┐
    │Prometheus│         │TimescaleDB│      │  Redpanda │
    │  :9090   │         │  :5432   │         │  :19092  │
    └──────────┘         └──────────┘         └──────────┘
```

---

## Service Entry Point

**File:** `src/api/main.py`

```python
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from src.api.routes import health, api, stream
from src.observability.otel import init_otel_providers

# Initialize OTel
init_otel_providers(service_name="indicagent-api")

# Create app
app = FastAPI(
    title="IndicAgent API",
    description="Real-time market intelligence platform",
    version="2.8"
)

# Instrument OTel (Phase 108)
FastAPIInstrumentor.instrument_app(app)

# Include routers
app.include_router(health.router, prefix="/health")
app.include_router(api.router, prefix="/api")
app.include_router(stream.router, prefix="/stream")

# Lifespan tasks
@app.on_event("startup")
async def startup():
    """Initialize connection pools, start background tasks"""
    pass

@app.on_event("shutdown")
async def shutdown():
    """Close connection pools, flush metrics"""
    flush_and_shutdown_metrics()
```

---

## Router Architecture

### Health Router (`/health/*`)

**Purpose:** Service health checks for monitoring

**Endpoints:**
- `GET /health/system` — System health (services, pipeline status)
- `GET /health/database` — DB connectivity
- `GET /health/kafka` — Kafka connectivity

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2026-05-28T12:00:00Z",
  "checks": {
    "database": "ok",
    "kafka": "ok"
  }
}
```

**OTel instrumentation:** Sets `api_health` gauge to 1 (up) or 0 (down).

---

### API Router (`/api/v1/*`)

**Purpose:** REST endpoints for historical queries and lookups

**Design principles:**
- Read-only queries (no mutations via API)
- DB queries only (no Kafka access)
- Pagination support
- Time range filtering

**Planned endpoints:**
```
GET /api/v1/bars              — Historical OHLCV data
GET /api/v1/features          — Intelligence feature vectors
GET /api/v1/signals           — Signal ledger
GET /api/v1/signal/:id        — Signal details
GET /api/v1/metrics           — Performance metrics
GET /api/v1/llm/calls         — LLM audit log
```

**Query parameters:**
- `symbol` — Asset symbol filter
- `timeframe` — Timeframe filter (1m, 5m, 15m, 1h, 4h, 1d)
- `start` — Start time (ISO 8601)
- `end` — End time (ISO 8601)
- `limit` — Pagination limit

---

### SSE Router (`/stream/*`)

**Purpose:** Real-time streaming via Server-Sent Events

**Design principles:**
- Fans out Kafka topics to HTTP clients
- Client filters via query params
- Automatic reconnection handling
- Backpressure via consumer lag monitoring

**Streams:**
```
GET /stream/bars              — Canonical 1m bars
GET /stream/bars/htf          — HTF bars (5m-1d)
GET /stream/intelligence      — I1-I7 features
GET /stream/signals           — I7 signals
GET /stream/lifecycle         — Signal lifecycle updates
GET /stream/llm               — LLM calls
```

**Client example:**
```javascript
const eventSource = new EventSource('http://localhost:8000/stream/signals?symbol=ES&timeframe=5m');

eventSource.onmessage = (event) => {
  const signal = JSON.parse(event.data);
  console.log('Signal received:', signal);
};

eventSource.onerror = (error) => {
  console.error('SSE error:', error);
  // Auto-reconnect handled by browser
};
```

---

## Database Access Pattern

The API uses asyncpg for DB queries:

```python
from src.core.database_manager import get_connection
from src.config import get_settings

async def get_bars(symbol: str, start: datetime, end: datetime):
    settings = get_settings()
    async with get_connection(settings) as conn:
        query = """
            SELECT timestamp, open, high, low, close, volume
            FROM market_data_ohlcv
            WHERE symbol = $1
              AND timestamp >= $2
              AND timestamp <= $3
            ORDER BY timestamp ASC
        """
        rows = await conn.fetch(query, symbol, start, end)
        return [dict(row) for row in rows]
```

**Key principles:**
- Use `get_connection()` context manager
- Always parameterize queries (no SQL injection)
- Return dicts (not asyncpg Record objects)
- Consume results inside context manager

---

## OTel Instrumentation

### Auto-Instrumentation (Phase 108)

`FastAPIInstrumentor` automatically instruments all HTTP endpoints:

```python
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

FastAPIInstrumentor.instrument_app(app)
```

This adds metrics for:
- Request rate (`http_server_requests_total`)
- Latency histograms (`http_server_duration_seconds`)
- Error rate (`http_server_requests_exceptions_total`)

### Custom Metrics

The `api_health` gauge tracks DB connectivity:

```python
# In health router
@router.get("/database")
async def check_database():
    try:
        await db_pool.fetchval("SELECT 1")
        API_HEALTH.set(1, {"service": "indicagent-api"})
        return {"status": "healthy"}
    except Exception:
        API_HEALTH.set(0, {"service": "indicagent-api"})
        raise HTTPException(status_code=503, detail="Database unreachable")
```

---

## SSE Streaming Architecture

### Kafka to SSE Bridge

The SSE router subscribes to Kafka topics and fans out to HTTP clients:

```python
from aiokafka import AIOKafkaConsumer

async def stream_signals(request: Request):
    async with AIOKafkaConsumer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="sse-consumer",
        auto_offset_reset="latest"
    ) as consumer:
        await consumer.subscribe([topic_stream_keys("intelligence.i7.signals")])

        async def event_generator():
            async for msg in consumer:
                data = json.loads(msg.value)
                yield f"data: {json.dumps(data)}\n\n"

        return EventSourceResponse(event_generator())
```

### Client Filtering

Clients filter via query params to reduce bandwidth:

```http
GET /stream/signals?symbol=ES&timeframe=5m&min_confidence=0.7
```

Server-side filtering is applied before sending to client.

---

## Error Handling

### HTTP Exceptions

```python
from fastapi import HTTPException

# 404 Not Found
raise HTTPException(status_code=404, detail="Signal not found")

# 400 Bad Request
raise HTTPException(status_code=400, detail="Invalid time range")

# 500 Internal Server Error
raise HTTPException(status_code=500, detail="Database error")
```

### Structured Logging

```python
import structlog

logger = structlog.get_logger(__name__)

logger.info("api_request",
    method=request.method,
    path=request.url.path,
    status_code=response.status_code,
    duration_ms=duration
)
```

---

## Rate Limiting (Planned)

Future implementation using slowapi:

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.get("/api/v1/bars")
@limiter.limit("100/minute")
async def get_bars(...):
    pass
```

---

## Authentication (Planned)

Future implementation using API keys:

```python
from fastapi import Security, HTTPException
from fastapi.security import APIKeyHeader

API_KEY_HEADER = APIKeyHeader(name="X-API-Key")

async def verify_api_key(api_key: str = Security(API_KEY_HEADER)):
    if api_key != os.getenv("API_KEY"):
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key

@app.get("/api/v1/bars", dependencies=[Depends(verify_api_key)])
async def get_bars(...):
    pass
```

---

## Monitoring

### OTel Metrics

Auto-instrumented metrics:
- `http_server_requests_total` — Request count by route, status
- `http_server_duration_seconds` — Request latency histogram
- `http_server_requests_exceptions_total` — Exception count

Custom metrics:
- `api_health` — DB connectivity (1=up, 0=down)

### Grafana Dashboard

See `docs/operations/grafana-dashboards.md` — API panel in Operations dashboard.

---

## See Also

- **REST endpoints:** `docs/reference/api/rest-endpoints.md`
- **SSE protocol:** `docs/reference/api/sse-protocol.md`
- **Stream schemas:** `docs/reference/schemas/stream-schemas.md`
- **Observability:** `docs/architecture/observability.md`
- **Self-healing:** `docs/architecture/self-healing.md`
