# External Integrations

**Analysis Date:** 2026-03-11

## APIs & External Services

**Trading & Market Data:**
- **Interactive Brokers (IBKR)** - Live tick data, historical OHLCV, order execution
  - SDK/Client: `ib_insync 0.9.86`
  - Gateway: `10.0.0.33:7497` (Windows LAN, paper trading)
  - Auth: Client ID 35+ (configured in `IBKR_CLIENT_ID`)
  - Integration: `src/providers/ibkr.py` (circuit breaker + circuit breaker recovery)
  - Covered assets: Futures (ES, NQ, RTY, YM, CL, etc.), FX (EURUSD, GBPUSD, USDJPY, USDCHF), Crypto (BTCUSD, ETHUSD, SOLUSD), Volatility (VX), Rates (ZN, ZF, ZB, ZT)
  - Circuit breaker: 3 failures → 180s open, 2 successes → recover

**LLM Providers (Tiered Chain):**
- **Z.ai (Primary)** - GLM-5 foundation model for agentic analysis
  - Provider: `ZAIProvider` in `src/intelligence/llm_providers.py`
  - Model: `glm-5` (configurable via `ZAI_MODEL`)
  - Auth: `ZAI_API_KEY` env var
  - Endpoint: `https://api.z.ai/api/paas/v4/chat/completions` (OpenAI-compatible)
  - Default timeout: 30.0s (configurable via `ZAI_TIMEOUT_SEC`)
  - Circuit breaker: 3 failures → 5 min open, 2 successes → recover
  - Used for: I8 AI narrative generation, per-signal analysis

- **OpenRouter (Secondary Fallback)** - 100+ model selection
  - Provider: `OpenRouterProvider` in `src/intelligence/llm_providers.py`
  - Model: User-configurable (default: empty string → skipped if no key)
  - Auth: `OPENROUTER_API_KEY` env var
  - Endpoint: `https://openrouter.ai/api/v1/chat/completions` (OpenAI-compatible)
  - Timeout: `LLM_TIMEOUT_SEC` (default 60.0s)
  - Circuit breaker: Shared with Z.ai, 3 failures → 5 min open
  - Fallback trigger: When Z.ai unavailable or circuit breaker open

- **Ollama (Tertiary, Offline)** - Local inference fallback
  - Provider: `OllamaProvider` in `src/intelligence/llm_providers.py`
  - Models: `qwen3.5:9b` (per-signal), `phi4-mini:3.8b` (group synthesis)
  - Auth: No API key required
  - Endpoint: `http://localhost:11434` (Docker container, ROCm GPU)
  - Timeout: `LLM_TIMEOUT_SEC` (default 60.0s, configurable)
  - Circuit breaker: Shared with Z.ai/OpenRouter
  - Fallback trigger: When all cloud providers unavailable

**LLM Chain Mechanism:**
- Location: `src/intelligence/llm_providers.py` (`LLMChain` class)
- Behavior: Tries providers in order (Z.ai → OpenRouter → Ollama), returns first successful response
- Attribute: `chain.last_provider_id` indicates which provider succeeded
- Async: All providers support async generation with configurable timeouts
- Error handling: ConnectionError, TimeoutError, BrokenPipeError trigger retry with exponential backoff (1s base, 10s max, 3 attempts)

## Data Storage

**Databases:**
- **PostgreSQL 15+ with TimescaleDB extension**
  - Connection: `DATABASE_URL` env var (default: `postgresql://postgres:postgres@localhost:5432/indicagent`)
  - Client: `asyncpg 0.31.0` (primary, async), `psycopg2-binary 2.9.7` (legacy, sync)
  - Hypertables:
    - `market_data_ohlcv` - Raw OHLCV bars (backfill only, kept forever for ground truth)
    - `intelligence_features` - Full feature vectors per bar incl. I1-I8 JSONB (ML training dataset)
    - `signal_ledger` - I7 signals + lifecycle outcomes, 8-class resolution
    - `llm_calls` - Full LLM audit log per call (timestamp, model, prompt, response, outcome)
  - Views: `ohlcv_15m`, `ohlcv_1h`, `ohlcv_4h`, `ohlcv_1d`, `market_data_5m`, `market_data_15m`
  - Pool: min 2, max 10 connections; 30s command timeout
  - Settings: `max_locks_per_transaction=16384`, `wal_buffers=8192`, `log_min_duration_statement=1000` (slow query logging)
  - VACUUM/ANALYZE: Automated via TimescaleDB job 1020 (Sundays 02:00 UTC)

**Caching & Streams:**
- **DragonflyDB (Redis-compatible)**
  - Connection: `REDIS_HOST:REDIS_PORT` (default: localhost:6379)
  - Client: `redis-py 7.1.0` (with hiredis C parser)
  - Max connections: 100 (configurable via `REDIS_MAX_CONNECTIONS`)
  - Docker: `docker.dragonflydb.io/dragonflydb/dragonfly:latest`
  - Configuration:
    - Snapshot: `--snapshot_cron "*/5 * * * *"` (every 5 min)
    - Keepalive: `--tcp_keepalive 300` (5 min)
    - Data dir: `/data` (volume: `dragonfly-data`)
  - Stream Keys (22+):
    - `{env_prefix}:indicators:SYMBOL:TF` - I1 technical indicators
    - `{env_prefix}:intelligence:SYMBOL:TF` - I3-I6 typed intelligence events
    - `{env_prefix}:signals:SYMBOL:TF:aggregated` - Selected I7 signal per bar
    - `{env_prefix}:narratives:SYMBOL:TF` - I8 AI narratives
    - `{env_prefix}:llm_calls:stream` - Every LLM call (maxlen=500)
    - `{env_prefix}:llm_outcomes:stream` - Signal exit outcomes (maxlen=200)
  - Consumer groups: `indicator`, `market_analysis`, `signal_generator`, `signal_lifecycle`, `ai_narrative`, `feature_writer`, `llm_writer` (auto-created on service startup)
  - Note: No Redis modules (TS.*, RediSearch unavailable) — time-series queries via TimescaleDB

**File Storage:**
- Local filesystem only (no S3/cloud storage)
  - Backups: `.venv/`, `production/migrations/`, `docker-compose.yml`, volumes (docker managed)
  - Output: Dashboard static files in `dashboard/.next/`, logs in service systemd journals

## Authentication & Identity

**Auth Provider:**
- Custom (none for API)
- IBKR: Client ID + Gateway credentials (paper trading)
- LLM providers: API keys (Z.ai, OpenRouter) via env vars; Ollama unauthenticated
- Dashboard: No auth required (localhost-only in development)

## Monitoring & Observability

**Error Tracking:**
- Structured logging via structlog (not sent to external service)
- Circuit breaker metrics via Prometheus (IBKR, LLM providers)
- LLM failures tracked in `llm_calls` hypertable (outcome field back-filled)

**Logs:**
- **Approach:** structlog + systemd journal
  - Structured: JSON-serializable context fields (`service`, `symbol`, `timeframe`, `level`)
  - Output: STDOUT (captured by systemd `journalctl -u indicagent-<name> -f`)
  - Log level: Configurable per service (default: INFO)

**Metrics:**
- **Prometheus 2.47.0** (Docker)
  - Scrape targets: Service `/metrics` ports (9109, 9112–9117 on host)
  - Scrape interval: 15s (default, configurable in `prometheus.yml`)
  - Retention: 15 days (default)
  - TSDB: Time series database at `/prometheus` (volume: `prometheus-data`)
  - Metrics exposed:
    - Plugin call counters (per tier, sampled at rate 10)
    - Circuit breaker state transitions, open duration
    - Redis stream lag per consumer group
    - Database query latencies (when tracked)

**Dashboards:**
- **Grafana 10.2.0** (Docker)
  - Port: 3001 (separate from Next.js dashboard on 3000)
  - Data sources: Prometheus, PostgreSQL (optional)
  - Dashboards: Provisioned from `grafana/dashboards/` directory
  - Auth: admin/admin (default, change in production)

## CI/CD & Deployment

**Hosting:**
- Linux VMs (systemd-managed services)
- Docker Compose for infrastructure (PostgreSQL, DragonflyDB, Ollama, Prometheus, Grafana)
  - Single source of truth: `production/docker-compose.yml`

**CI Pipeline:**
- None detected (no GitHub Actions, GitLab CI, or Jenkins configs)
- Manual deployment: `git push` + systemd service restart

**Services (systemd):**
```
indicagent-tws                # IBKR tick/bar collection
indicagent-indicator          # I1 technical indicators
indicagent-market-analysis    # I3→I6 intelligence pipeline
indicagent-signal-generator   # I7 setup detection
indicagent-signal-lifecycle   # Zone-aware lifecycle tracking
indicagent-ai-narrative       # I8 LLM narrative generation
indicagent-feature-writer     # Redis → TimescaleDB persistence
indicagent-llm-writer         # LLM audit log + outcome back-fill
indicagent-api                # FastAPI server (uvicorn :8000)
```

All services: `Restart=always` (auto-restart on failure)

## Environment Configuration

**Required env vars (critical):**
```
DATABASE_URL          # PostgreSQL connection (default OK for dev)
REDIS_HOST, REDIS_PORT (defaults OK)
IBKR_HOST, IBKR_PORT  (default 10.0.0.33:7497)
```

**Optional but recommended:**
```
INDICAGENT_ENV        # "development" | "production" (default: "")
ZAI_API_KEY           # Z.ai GLM-5 (required for I8 narrative)
LLM_TIMEOUT_SEC       # Adjust if LLM calls timeout (default 60s)
```

**Secrets location:**
- `.env` file (not checked into git, matches `.env.example` if present)
- Env vars sourced by systemd service files or `~/.bashrc`
- No `.env.*` variations; single `.env` per environment

## Webhooks & Callbacks

**Incoming:**
- SSE (Server-Sent Events): `/events` endpoint on FastAPI
  - Client: Browser WebSocket or JavaScript EventSource
  - Streams: Intelligence updates, signal changes, narrative generation
  - No webhook/callback endpoints for external services

**Outgoing:**
- None detected (no webhooks to external services)
- IBKR integration: Polling-based (no event callbacks from gateway)
- LLM chains: Request/response model (no async webhooks)

## Data Flow Between Systems

**Hot/Warm/Cold Tiers:**
```
Hot:   IBKR TWS → DragonflyDB Streams (sub-ms latency)
Warm:  Streams → indicator/analysis/signal services (<10ms)
Cold:  feature_writer_service → TimescaleDB (batch, async)
```

**Cross-Service Communication:**
- Redis streams: Service-to-service data flow (async, persistent)
- No gRPC, message queues (RabbitMQ, Kafka), or HTTP polling between services
- All services read independently from Redis streams (consumer groups)

**Real-Time Pipeline Never Touches DB:**
- Live analysis uses DragonflyDB streams only
- Database writes deferred to `feature_writer_service` (batched persistence)
- Backfill/repairs use direct database access

## External API Rate Limits & Quotas

**IBKR:**
- No published rate limit (gateway-based)
- Max historical bars: 6d (1m), 30d (5m), 60d (15m), 1yr (1h-1d)
- Circuit breaker: 3 failures → 180s retry delay

**Z.ai (GLM-5):**
- API rate limits: Check Z.ai documentation (not explicitly listed in code)
- Timeout: 30s per request
- Circuit breaker: 3 failures → 300s retry delay (5 min)

**OpenRouter:**
- Model-specific rate limits (depends on selected model)
- Timeout: 60s per request
- Circuit breaker: Shared with Z.ai (3 failures → 300s)

**Ollama:**
- Local only, no rate limits
- Timeout: 60s per request
- GPU memory: Limited by device VRAM (AMD iGPU: 16.3 GiB shared)

---

*Integration audit: 2026-03-11*
