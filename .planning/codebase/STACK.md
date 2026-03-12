# Technology Stack

**Analysis Date:** 2026-03-11

## Languages

**Primary:**
- **Python 3.13.5** - Backend services, data processing, intelligence plugins
  - Location: `.python-version`
  - Used in: `services/`, `src/`, production scripts, tests

**Secondary:**
- **TypeScript 5** - Frontend UI and dashboard
  - Location: `dashboard/` (Next.js)
  - Node 16+ required

## Runtime

**Environment:**
- **Python 3.13.5** (`~/.pyenv` managed via `.python-version`)
- **Node 16+** for dashboard development and build

**Package Managers:**
- **pip** - Python packages via `requirements.txt`
  - Lockfile: Not present; pinned versions in `requirements.txt`
  - Virtual environment: `.venv/` (created locally)
- **npm** - JavaScript packages (dashboard)
  - Lockfile: `dashboard/package-lock.json` (implied, standard npm)

## Frameworks

**Core Backend:**
- **FastAPI 0.129.0** - REST API, SSE streaming, async request handling
  - Location: `src/api/main.py`, `src/api/routes/`
  - Handles: `/indicators`, `/signals`, `/features`, `/instruments`, SSE stream `/events`
- **Uvicorn 0.40.0** - ASGI server for FastAPI
  - Supports: HTTP/1.1, WebSocket-compatible
  - Port: 8000 (API service)

**Data Processing:**
- **pandas 3.0.0** - DataFrames, time-series alignment, OHLCV manipulation
- **NumPy 2.4.0** - Numerical computing, array operations in indicators
- **scikit-learn 1.5.0** - Regression, clustering for pattern detection
- **PyArrow 23.0.0** - Efficient data serialization, Parquet support

**Intelligence Framework:**
- **LangGraph 1.0.0** - Event-driven DAG workflows, plugin orchestration
  - Used in: `src/intelligence/dag.py`
  - Supports: multi-tier intelligence pipeline, stateful graph execution

**Async Runtime:**
- **asyncio (stdlib)** - Async I/O, coroutine management
- **uvloop 0.22.0** - Drop-in asyncio replacement (non-Windows), faster event loop
  - Conditional: `sys_platform != "win32"`
- **nest_asyncio** - Allow nested `asyncio.run()` (IBKR integration requirement)

**Testing:**
- **pytest 8.4.0** - Unit and integration test runner
  - Command: `.venv/bin/pytest tests/unit/ -v`
- **pytest-asyncio 1.1.0** - Async test support, `@pytest.mark.asyncio` fixtures

**Code Quality & Formatting:**
- **Ruff 0.15.0** - Fast linter, isort, pyupgrade bundled
  - Config: `pyproject.toml` [tool.ruff] section
  - Target: Python 3.13, line-length 100
  - Run: `.venv/bin/ruff check . --fix`
  - Ignores: E402 (module-level imports), B008 (FastAPI Depends()), E741 (single-letter vars in schemas)
- **Black 26.1.0** - Code formatter
  - Config: `pyproject.toml` [tool.black]
  - Run: `.venv/bin/black .`
- **mypy 1.19.0** - Static type checking
  - Config: `pyproject.toml` [tool.mypy]
  - Python 3.13 target, warn_return_any enabled

**Logging & Observability:**
- **structlog 25.5.0** - Structured logging (JSON-serializable context fields)
  - Used in: All services via `structlog.get_logger(__name__)`
  - Fields: `timestamp`, `service`, `symbol`, `timeframe`, `level`
- **Prometheus Client 0.24.0** - Metrics scraping
  - Exposed on per-service ports: :9109 (indicator), :9112 (signal-gen), :9113 (ai-narrative), :9114 (market-analysis), :9115 (signal-lifecycle), :9116 (feature-writer), :9117 (llm-writer)
  - Metrics types: Counter, Histogram, Gauge
  - Sample rate: `PLUGIN_METRICS_SAMPLE_RATE=10` for plugin call tracking
- **OpenTelemetry 1.20.0** - Distributed tracing (SDK + API)
  - Exporter: `opentelemetry-exporter-otlp-proto-http` (HTTP protocol)
  - Not actively used in v1.7 (observability via Prometheus + structlog)

**Serialization & Communication:**
- **msgpack 1.0.0** - Binary message serialization (Redis streams payloads)
- **pydantic 2.12.0** - Data validation, schema enforcement
- **pydantic-settings 2.12.0** - Environment configuration with type hints
  - Location: `src/config/settings.py`

**System Utilities:**
- **aiohttp 3.9.0** - Async HTTP client for external API calls
- **psutil 5.9.0** - System monitoring (CPU, memory, process info)
- **tzdata 2025.1** - Timezone database (UTC + exchange-specific TZ support)

**Database & Caching:**
- **asyncpg 0.31.0** - Async PostgreSQL driver (primary, preferred)
  - Pool size: min=2, max=10
  - Command timeout: 30s
  - JSONB codecs: JSON encoder/decoder registered per connection
- **psycopg2-binary 2.9.7** - Synchronous PostgreSQL driver (fallback, legacy)
  - Used in: Production scripts (non-async), backfill operations
- **redis-py 7.1.0** (with hiredis) - Redis/DragonflyDB async client
  - Supports: Redis streams, pub/sub, commands
  - Max connections: 100 (configurable)
  - Hiredis C parser: Performance optimization for protocol parsing

**IBKR Integration:**
- **ib_insync 0.9.86** - Interactive Brokers API wrapper
  - Isolated in: `src/providers/ibkr.py` (no ib_insync imports elsewhere)
  - Client ID: 35+ range
  - Connects to: `10.0.0.33:7497` (TWS Gateway, paper trading)
  - Implements: circuit breaker with 3-min recovery timeout

## Key Dependencies

**Critical (Production Breaking):**
- **fastapi** - API unavailable without it
- **asyncpg** + **redis** - Core data flow requires both
- **ib_insync** - IBKR feed halts without it; fallback to historical backfill only
- **pydantic** - Schema validation for all intelligence events
- **structlog** - Logging pipeline (services degrade gracefully without it)

**Infrastructure:**
- **prometheus-client** - Metrics (can be disabled, affects observability)
- **uvloop** - Performance optimization (falls back to stdlib asyncio on Windows)

## Configuration

**Environment Variables:**
```bash
INDICAGENT_ENV              # "development" | "production" | ""
INDICAGENT_METRICS_PORT     # Default: 9108
DATABASE_URL                # PostgreSQL URI (default: postgres://localhost/indicagent)
REDIS_HOST                  # Default: localhost
REDIS_PORT                  # Default: 6379
REDIS_DB                    # Default: 0
IBKR_HOST                   # Default: 172.18.176.1 (LAN); alt: 10.0.0.33
IBKR_PORT                   # Default: 7497
IBKR_TIMEOUT_SEC            # Default: 20.0
ZAI_API_KEY                 # Z.ai (GLM-5 primary provider)
ZAI_MODEL                   # Default: glm-5
ZAI_BASE_URL                # Default: https://api.z.ai/api/paas/v4
OPENROUTER_API_KEY          # OpenRouter fallback (empty string = skip)
LLM_TIMEOUT_SEC             # Default: 60.0
HF_ASYNC_PUBLISH            # Default: True
HF_CONTRACTS_JSON           # Override contract list (JSON string)
OLLAMA_BASE_URL             # Default: http://localhost:11434 (Docker :11434)
OLLAMA_DEFAULT_MODEL        # Default: qwen3.5:9b
```

**Build Configuration:**
- `pyproject.toml` - Central Python project config (metadata, tool settings, dependencies via `requirements.txt`)
- `dashboard/tsconfig.json` - Next.js TypeScript configuration
- `dashboard/next.config.js` - Next.js build/dev settings (Turbopack enabled in `npm run dev`)
- `.eslintrc.js` (implied) - Dashboard linting
- `src/config/settings.py` - Runtime configuration (pydantic-settings)

**Code Quality Config:**
- `.ruff.toml` or `pyproject.toml [tool.ruff]` - Ruff linter rules, isort config
- `.black` / `pyproject.toml [tool.black]` - Black formatter rules
- `pyproject.toml [tool.mypy]` - mypy static type checking

## Platform Requirements

**Development:**
- Python 3.13.5 (enforced via `.python-version`)
- Node 16+ (for `npm` in `dashboard/`)
- PostgreSQL 15+ with TimescaleDB extension (Docker: `timescale/timescaledb:latest-pg15`)
- DragonflyDB (Redis-compatible, Docker: `docker.dragonflydb.io/dragonflydb/dragonfly:latest`)
- Docker & Docker Compose (for infrastructure containers)
- AMD Phoenix1 iGPU with ROCm support (for Ollama GPU acceleration, optional)

**Production:**
- **Deployment target:** Linux (systemd services expected)
  - Services: `indicagent-{tws,indicator,market-analysis,signal-generator,signal-lifecycle,ai-narrative,feature-writer,llm-writer,api}`
  - Restart policy: systemd `Restart=always`
- **Database:** PostgreSQL 15+ with TimescaleDB
  - Connection pooling: asyncpg (2-10 size)
  - Hypertables: `market_data_ohlcv`, `intelligence_features`, `signal_ledger`, `llm_calls`
  - Settings: `max_locks_per_transaction=16384` (raised 2026-03-07 for 10k chunks on OHLCV)
- **Cache/Streams:** DragonflyDB (Redis API compatible)
  - Streams: 22+ keyed by `env_prefix:entity:symbol:timeframe`
  - Snapshot interval: 5 min (`--snapshot_cron "*/5 * * * *"`)
  - Keepalive: 300s
- **LLM Inference:** Ollama Docker (optional fallback)
  - Models: qwen3.5:9b (per-signal), phi4-mini:3.8b (group synthesis)
  - GPU: ROCm AMD (gfx1100/RDNA3) or CPU fallback
- **Monitoring:** Prometheus (port 9090) + Grafana (port 3001)

---

*Stack analysis: 2026-03-11*
