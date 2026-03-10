# Technology Stack

**Analysis Date:** 2026-02-22

## Languages

**Primary:**
- Python 3.13.5 - Core market intelligence platform, backend services, daemons
- TypeScript 5 - Next.js dashboard frontend type definitions
- JavaScript (React 19) - Dashboard UI components and real-time views
- SQL (PostgreSQL/TimescaleDB) - Historical data and time-series storage

**Secondary:**
- JSON - Configuration and serialization formats

## Runtime

**Environment:**
- Python 3.13.5 (specified in `.python-version`)
- Node.js (via Next.js 15.5.12)
- PostgreSQL 15+ with TimescaleDB extension

**Package Manager:**
- pip (with uv.lock for reproducible builds)
- npm/yarn (for dashboard Node dependencies)

## Frameworks

**Core Backend:**
- FastAPI 0.129.0+ - REST API for market data, indicators, instruments, SSE streaming
- Uvicorn 0.40.0+ - ASGI application server

**Data & Intelligence:**
- LangGraph 1.0.0+ - Agentic workflows for signal orchestration and narrative generation
- Pydantic 2.12.0+ - Data validation and type-safe configuration
- Pydantic-Settings 2.12.0+ - Environment-based configuration management

**Frontend:**
- Next.js 15.5.12 - React framework with SSR, API routes, and Turbopack bundling
- React 19.1.0 - UI component library
- React DOM 19.1.0 - DOM rendering
- TailwindCSS 4 - Utility-first CSS framework
- Lucide React 0.536.0 - Icon library for dashboard components
- clsx 2.1.1, tailwind-merge 3.3.1 - Class name utilities

**Testing & Development:**
- pytest 8.4.0 - Python test framework
- pytest-asyncio 1.1.0 - Async test support
- black 26.1.0 - Code formatter (100-char line length)
- ruff 0.15.0 - Linter (E, F, W, I, UP, B rules with B008 ignored for FastAPI)
- mypy 1.19.0 - Static type checker (lenient mode, Python 3.13)

**Observability:**
- structlog 25.5.0 - Structured logging
- prometheus-client 0.24.0 - Metrics collection and exposure
- opentelemetry-api 1.20.0 - Observability API
- opentelemetry-sdk 1.20.0 - SDK implementation
- opentelemetry-exporter-otlp-proto-http 1.20.0 - OTLP HTTP exporter for tracing

## Key Dependencies

**Critical Infrastructure:**
- redis[hiredis] 7.1.0 - Redis client with C parser; DragonflyDB/Redis Streams for real-time data
- asyncpg 0.31.0 - Async PostgreSQL driver (async/await support)
- psycopg2-binary 2.9.7+ - Sync PostgreSQL driver (batch operations, historical backfill)
- aiohttp 3.9.0 - Async HTTP client for external API calls

**Data Processing:**
- pandas 3.0.0 - Data manipulation and time-series handling
- numpy 2.4.0 - Numerical computation for indicators
- msgpack 1.0.0 - Binary serialization for stream messages

**External Integrations:**
- ib_insync 0.9.86 - Interactive Brokers TWS/Gateway async wrapper
- tzdata 2025.1 - Timezone database

**System Utilities:**
- psutil 5.9.0 - System and process monitoring
- uvloop 0.22.0 (non-Windows) - High-performance asyncio event loop replacement

## Configuration

**Environment:**
- `.env` file (not committed; template at `.env.example`)
- Environment variables via Pydantic BaseSettings in `src/config/settings.py`
- Service-specific JSON config files in `config/` directory (e.g., `config/ai_narrative_service.json`)

**Key Configuration Files:**
- `pyproject.toml` - Python tool config (black, ruff, mypy)
- `pytest.ini` - Test runner config (async mode, markers)
- `dashboard/package.json` - Next.js/React dependencies and build config
- `.cursorrules` - Cursor IDE rules for development
- `.mcp.json` - Model Context Protocol configuration

**Environment Variables Required:**
- `INDICAGENT_ENV` - Environment name (development | staging | production)
- `DATABASE_URL` - PostgreSQL connection string
- `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB` - DragonflyDB/Redis connection
- `IBKR_HOST`, `IBKR_PORT`, `IBKR_CLIENT_ID` - Interactive Brokers TWS connection
- `OTEL_EXPORTER_OTLP_ENDPOINT` - (Optional) OpenTelemetry collector endpoint

## Platform Requirements

**Development:**
- Python 3.13+
- PostgreSQL 15+ with TimescaleDB extension
- DragonflyDB (Redis-compatible) running on :6379
- Interactive Brokers TWS/Gateway running on configured host:port
- Node.js 18+ (for dashboard development)

**Production:**
- PostgreSQL with TimescaleDB (hosted or self-managed)
- DragonflyDB or Redis (high-throughput streams required)
- IBKR TWS/Gateway for market data feed (Windows LAN or remote)
- Optional: OpenTelemetry collector (Jaeger/Datadog) for distributed tracing
- Optional: Cloudflare Tunnel for HTTPS frontend proxy

---

*Stack analysis: 2026-02-22*
