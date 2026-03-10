# External Integrations

**Analysis Date:** 2026-02-22

## APIs & External Services

**Interactive Brokers (IBKR):**
- TWS/Gateway REST API for market data and order management
  - SDK/Client: `ib_insync` 0.9.86
  - Connection: TCP socket to configurable host:port (default: localhost:7497 paper trading)
  - Data: Historical OHLCV bars, real-time ticks, contract details
  - Implementation: `src/providers/ibkr.py` — abstraction layer wrapping ib_insync
  - Usage: `production/daemons/high_frequency_tws_daemon.py` publishes ticks to Redis Streams
  - Backfill: `production/scripts/historical_backfill.py` stages IBKR data into PostgreSQL

**Ollama (Local LLM):**
- In-process or remote LLM inference for AI narrative generation
  - SDK/Client: HTTP REST client via `urllib.request` (no external library dependency)
  - Endpoint: Configurable (default: `http://localhost:11434`)
  - Auth: None (local or trusted network)
  - Models: qwen3:8b (default), configurable per instance
  - Usage: `services/ai_narrative_service.py` → calls `/api/chat` with trading signals
  - Features: `/no_think` directive for fast inference, 500-token max output

**OpenTelemetry (Optional):**
- Distributed tracing and observability
  - SDK: `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`
  - Endpoint: Configurable via `OTEL_EXPORTER_OTLP_ENDPOINT` (default: http://localhost:4318)
  - Implementation: `src/observability/otel.py` — tracer initialization
  - Status: Optional (can run without external collector)

## Data Storage

**Databases:**

*PostgreSQL + TimescaleDB:*
- Database: `indicagent` on localhost:5432 (configurable via `DATABASE_URL`)
- Client: `asyncpg` (async) + `psycopg2-binary` (sync/batch operations)
- Schema: SQL migrations in `production/migrations/` (idempotent, numbered)
- Tables:
  - `market_data_ohlcv` - Hypertable for 1-minute OHLCV bars (compressed after 7 days)
  - `technical_indicators` - Hypertable for indicator values (compressed after 7 days)
  - `signal_ledger` - Hypertable for trading signals with feature context (feature_ts, feature_tf columns)
  - `intelligence_features` - Hypertable for tiered JSONB intelligence data (I1/I3/I4/I5/I6/SMC/I7 tiers)
  - `instruments` - Reference table for contract metadata
- Features:
  - Time-series compression: Data older than 7 days compressed to reduce storage
  - GIN indexes on JSONB columns for fast tiered intelligence queries
  - Continuous aggregates (5m, 15m bars from 1m) via `SELECT * FROM cagg_5m`
  - No retention policy (data kept for seasonal analysis)
- Connection pooling: `asyncpg` pool 2-10 connections, 30-second command timeout

**Redis/DragonflyDB (Real-time Streams):**
- Store: DragonflyDB compatible with Redis protocol
- Host: localhost:6379 (configurable via `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`)
- Client: `redis[hiredis]` 7.1.0 (async via `redis.asyncio`)
- Streams (core pipeline):
  - `ticks:{symbol}` - Live ticks from IBKR
  - `market:{symbol}:{timeframe}` - OHLCV bars (1m, 5m, 15m, 1h, 4h, 1d)
  - `indicators:{symbol}:{timeframe}` - Technical indicator values (RSI, MACD, Bollinger Bands, etc.)
  - `intelligence:{symbol}:{timeframe}` - Tiered intelligence (market structure, context, patterns, SMC, confluence)
  - `signals:{symbol}:{timeframe}` - Setup-specific trading signals
  - `signals:{symbol}:{timeframe}:aggregated` - Aggregated signals with confidence scoring
  - `narratives:{symbol}:{timeframe}` - AI-generated trading narratives
- Consumer groups:
  - Internal: `{service}:{purpose}` (e.g., `indicator_service:process`, `market_analysis:consume`)
  - External: `ext:{app}:{purpose}` (e.g., `ext:dashboard:events`)
- Max stream length: 1,000 entries per stream (circular buffer, FIFO)
- State persistence: Plugin state hashes at `plugin_state:{symbol}:{tf}:{plugin_name}` (7-day TTL, checkpointed every 60 bars)

**File Storage:**
- None (all runtime data in Redis Streams; historical in PostgreSQL)

**Caching:**
- Redis hashes for plugin state snapshots (transient, not long-lived cache)

## Authentication & Identity

**Auth Provider:**
- Custom: JWT tokens (for humans/Vercel frontend) + API keys (for machines/services)
- Implementation: Single `Depends(verify_auth)` FastAPI dependency in `src/api/dependencies.py`
- Scope: IBKR client ID (service-level) + optional JWT/API key for dashboard access
- Status: Under development (Phase 2 milestone)

**Credentials:**
- IBKR: Client ID passed at connection time (no username/password)
- Ollama: None (local/trusted network)
- OTEL: Optional headers via `OTEL_EXPORTER_OTLP_HEADERS` (key=value pairs)

## Monitoring & Observability

**Error Tracking:**
- None (errors logged to structlog, optional OTEL integration)

**Logs:**
- Structured: `structlog` 25.5.0 for all services
- Output: Console and rotating file handlers in `logs/` directory
- Configuration: Per-service JSON config files (e.g., `config/ai_narrative_service.json`)

**Metrics:**
- Prometheus-compatible endpoint (`:9113` default for AI Narrative, `:9112` for Signal Orchestrator)
- Metrics: Counters (signals/narratives generated, errors), Gauges (latency, uptime), Histograms (processing time)
- Scraped by: External Prometheus server (optional)

**Distributed Tracing:**
- OpenTelemetry SDK exportable to Jaeger/Datadog via OTLP HTTP
- Tracer initialization in `src/observability/otel.py`
- Service names: `indicagent-processor`, `indicagent-api`, etc. (configurable)

## CI/CD & Deployment

**Hosting:**
- Not applicable (development/research platform)
- Potential targets: Vercel (frontend), self-managed Linux VM (services)

**CI Pipeline:**
- Not detected (development uses local test runner)

**Deployment Tools:**
- Container-friendly (no Docker in current setup, but services can be containerized)
- Current: Native processes with systemd or supervisor

## Environment Configuration

**Required env vars (production):**
- `DATABASE_URL` - PostgreSQL connection string
- `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB` - DragonflyDB connection
- `IBKR_HOST`, `IBKR_PORT`, `IBKR_CLIENT_ID` - Interactive Brokers
- `INDICAGENT_ENV` - Environment name for stream key prefixing

**Optional env vars:**
- `OTEL_EXPORTER_OTLP_ENDPOINT` - OpenTelemetry collector (default: http://localhost:4318)
- `OTEL_EXPORTER_OTLP_HEADERS` - OTEL auth headers (if remote collector requires auth)

**Secrets location:**
- `.env` file (local development, not committed)
- Environment variables injected at runtime (production)
- API keys: None currently (future OpenRouter/Claude API keys for I8 expansion)

## Webhooks & Callbacks

**Incoming:**
- None (IndicAgent only publishes; it does not consume external webhooks)

**Outgoing:**
- None (IndicAgent publishes to Redis Streams and PostgreSQL)
- Future: Webhook support planned for external app notifications (Phase 3+)

## Data Flow: Tick to Dashboard

1. **IBKR TWS** → High-frequency daemon publishes ticks to `ticks:{symbol}` stream
2. **Timeframes Builder** consumes ticks, aggregates to multi-timeframe bars
3. **Indicator Service** processes bars, publishes indicators to `indicators:{symbol}:{tf}`
4. **Market Analysis Service** (I1-I7) processes market structure, context, patterns, SMC
5. **Signal Orchestrator** aggregates plugin outputs → `signals:{symbol}:{tf}:aggregated`
6. **AI Narrative Service** subscribes to aggregated signals, calls Ollama, publishes narratives
7. **Signal Tracker** writes signals to `signal_ledger` table (PostgreSQL) for history
8. **FastAPI SSE endpoint** (`/api/sse/events`) bridges Redis Streams → browser SSE
9. **Next.js Dashboard** (socket.io-client) subscribes to SSE events for live updates

---

*Integration audit: 2026-02-22*
