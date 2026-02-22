# Architecture

**Analysis Date:** 2026-02-22

## Pattern Overview

**Overall:** Event-driven microservices architecture using Redis Streams as message bus.

**Key Characteristics:**
- Services are independent processes communicating exclusively via Redis Streams (no direct HTTP calls between pipeline services)
- Plugin-based intelligence pipeline with 7 processing tiers (I1 through I8)
- Real-time processing optimized for low latency — no database on hot path
- Stateless service design with optional state persistence in Redis for stateful plugins
- Separate daemon for IBKR tick ingestion with high-frequency optimization (100-500+ ticks/sec)
- Canonical tier plugin registry (TIER_I1 through TIER_I7) as single source of truth

## Layers

**Data Ingestion Layer:**
- Purpose: Capture real-time market data from Interactive Brokers
- Location: `production/daemons/high_frequency_tws_daemon.py`
- Contains: IBKR connection management, tick callback handlers, bar aggregation to 1m
- Depends on: IBKRProvider (`src/providers/ibkr.py`), Redis client, AsyncTickPublisher
- Used by: market_data_daemon publishes to `ticks:SYMBOL:live` and `market:SYMBOL:1m` streams
- Key flow: IBKR ticks → Redis tick stream → 1m bar stream

**Bar Aggregation Layer:**
- Purpose: Convert 1m bars to higher timeframes (5m, 15m, 1h, 4h, 1d)
- Location: Embedded in `services/timeframes_builder_service.py`
- Contains: Time-series bar aggregation logic, multi-timeframe coordination
- Depends on: market_data_daemon's 1m bars from Redis streams
- Used by: indicator_service and downstream intelligence services
- Key mechanics: Consumes `market:SYMBOL:1m`, publishes to `market:SYMBOL:{5m,15m,1h,4h,1d}`

**Technical Indicators Layer (I1):**
- Purpose: Calculate 23 base technical indicators incrementally on each bar
- Location: `services/indicator_service.py` and `src/intelligence/indicators/`
- Contains: 23 indicator plugins (RSI, MA, MACD, ATR, Bollinger, etc.) with incremental compute support
- Depends on: OHLCV bars from multi-timeframe streams, plugin registry
- Used by: market_analysis_service (I3+ pipeline)
- Key output: Combined OHLCV + I1 features to `indicators:SYMBOL:TF` stream

**Intelligence Pipeline Layer (I3-I6):**
- Purpose: Execute plugin tiers for market structure, context, patterns, and smart money
- Location: `services/market_analysis_service.py` consuming from `indicators:SYMBOL:TF`
- Contains: Five sequential plugin execution stages:
  - I3 (Structure): Swing detection, support/resistance, trend structure (3 plugins)
  - I4 (Context): Volatility regime, trend regime, momentum context, GARCH, Kalman (5 plugins)
  - I5 (Patterns): Divergence, squeeze, confluence, chart patterns (8 plugins)
  - SMC (Smart Money): BOS/CHoCH, FVG, order blocks, liquidity sweeps, etc. (8 plugins)
  - I6 (Confluence): Cross-timeframe confluence scoring (1 plugin)
- Depends on: I1 features from indicators stream, plugin registry with tier validation at startup
- Used by: signal_generator_service (I7) and signal_orchestrator_service
- Key output: Combined features to `intelligence:SYMBOL:TF` stream
- Key pattern: Each tier depends on outputs from prior tiers; plugins consume frames from Redis

**Signal Generation Layer (I7):**
- Purpose: Generate trading setups and signal aggregation
- Location: `services/signal_generator_service.py` and `src/intelligence/trading/`
- Contains: 9 I7 setup plugins + aggregation logic, ledger insertion
- Depends on: `intelligence:SYMBOL:TF` stream (enriched with OHLCV), market context snapshot
- Used by: signal_tracker_service (lifecycle management), AI narrative service
- Key output: Individual signals to `signal_ledger` table, winner to `signals:SYMBOL:TF:aggregated` stream
- Key mechanics: Aggregates I7 setup signals by timeframe, selects winner via AggregatedResult

**Signal Tracking Layer:**
- Purpose: Track open signal lifecycle (entry, exit, P&L, status transitions)
- Location: `services/signal_tracker_service.py` and `src/intelligence/trading/lifecycle_tracker.py`
- Contains: Signal state machine (pending→active→exit), P&L calculation, time-based expiration
- Depends on: `signals:SYMBOL:TF:aggregated` (signals), `market:SYMBOL:1m` (price updates for P&L)
- Used by: AI narrative service (for context), dashboard via API
- Key output: Updated signal records in `signal_ledger`, status changes published back to streams
- Key pattern: Lifecycle tracking is separate from generation — enables clean signal state machine

**AI Narrative Layer (I8):**
- Purpose: Generate human-readable narratives for active signals using LLM
- Location: `services/ai_narrative_service.py`
- Contains: LangGraph-based agent orchestration, Ollama integration, narrative generation
- Depends on: `signals:SYMBOL:TF:aggregated` stream, active signals from `signal_ledger`, market context
- Used by: Dashboard and external consumers via `narratives:SYMBOL:TF` stream
- Key output: Publishesto `narratives:SYMBOL:TF` stream with signal ID linking

**API Layer:**
- Purpose: Expose real-time data and historical queries to external consumers (dashboard, ML, etc.)
- Location: `src/api/main.py` and `src/api/routes/`
- Contains: FastAPI application, SSE subscriptions, query endpoints, health/metrics
- Routes:
  - `GET /health` — Service health
  - `GET /metrics` — Prometheus metrics
  - `GET /api/sse/stream` — SSE subscriptions to Redis streams (instruments, bars, indicators, intelligence, signals, narratives)
  - `GET /indicators/{symbol}/{timeframe}` — Get latest indicator values
  - `GET /api/market_data/{symbol}/{timeframe}` — Get historical OHLCV
  - `GET /api/instruments` — List all tracked instruments
- Depends on: Redis streams for real-time data, database for historical queries
- Entry point: Lifespan context managers initialize DatabaseManager and RedisStreamsManager

**Core Infrastructure Layer:**
- Purpose: Provide shared utilities and abstractions
- Location: `src/core/`
- Contains:
  - `stream_keys.py` — Centralized stream naming (e.g., `indicators:SYMBOL:TF`) and retention policies
  - `models.py` — Pydantic domain models (Instrument, OHLCVData, TechnicalIndicator, SignalScore, TradingSignal, etc.)
  - `database_manager.py` — AsyncPG pool management and query execution
  - `redis_streams_manager.py` — Redis stream lifecycle (start/stop)
  - `plugin_circuit_breaker.py` — Circuit breaker for plugin execution failures
  - `plugin_state_manager.py` — Persistent plugin state in Redis for stateful plugins
  - `redis_stream_consumer.py` — Consumer group management for stream subscriptions
  - `async_tick_publisher.py` — Async batch publisher for high-frequency tick writing
- Depends on: external libraries (asyncpg, redis-py, pydantic)
- Used by: All services

**Plugin System Layer:**
- Purpose: Provide plugin registration, discovery, and validation
- Location: `src/intelligence/plugins.py` and `src/intelligence/register_plugins.py`
- Contains:
  - Plugin protocol definitions (IndicatorPlugin, PatternPlugin)
  - PluginRegistry class for registration and lookup
  - Tier lists (TIER_I1, TIER_I3, TIER_I4, TIER_I5, TIER_SMC, TIER_I6, TIER_I7) as single source of truth
  - `register_all_plugins()` function to initialize all 57 plugins
- Depends on: Individual plugin implementations in `src/intelligence/{indicators,patterns,context,structure,smart_money,trading,confluence}/`
- Used by: All service layers that execute plugins
- Key pattern: Tier lists are derived from actual plugin objects at registration time, ensuring consistency

**Configuration Layer:**
- Purpose: Centralize environment configuration and provide typed settings
- Location: `src/config/settings.py`
- Contains: Settings class with Pydantic validation, environment variable overrides
- Configuration options: IBKR host/port/client_id, Redis host/port/db, database URL, contracts, env_name for stream prefixing, metrics port
- Used by: All services at initialization
- Key pattern: Supports both individual env vars (e.g., `IB_HOST`) and JSON string contracts (e.g., `HF_CONTRACTS_JSON`)

**Observability Layer:**
- Purpose: Metrics collection and monitoring
- Location: `src/observability/metrics.py`
- Contains: Prometheus metric helpers (counter, gauge, histogram), plugin execution recording
- Metrics exported: bars_processed_total, calculations_total, plugin_execution_* (per-plugin timing and counts)
- Used by: All services for instrumentation

## Data Flow

**Live Market Processing:**

1. IBKR Connection opens via IBKRProvider
2. TWS Daemon receives tick callbacks, publishes to `ticks:SYMBOL:live` stream
3. TWS Daemon aggregates to 1m bars, publishes to `market:SYMBOL:1m`
4. Timeframes Builder consumes 1m bars, aggregates to 5m/15m/1h/4h/1d, publishes to `market:SYMBOL:{TF}`
5. Indicator Service consumes `market:SYMBOL:{TF}`, runs I1 plugins (23 total), publishes OHLCV + I1 features to `indicators:SYMBOL:TF`
6. Market Analysis Service consumes `indicators:SYMBOL:TF`, runs I3→I4→I5→SMC→I6 plugins in sequence, publishes combined features to `intelligence:SYMBOL:TF`
7. Signal Generator Service consumes `intelligence:SYMBOL:TF`, runs I7 setup plugins, aggregates, inserts to `signal_ledger`, publishes to `signals:SYMBOL:TF:aggregated`
8. Signal Tracker Service consumes `signals:SYMBOL:TF:aggregated` for signal events and `market:SYMBOL:1m` for live P&L, updates signal status in `signal_ledger`
9. AI Narrative Service consumes `signals:SYMBOL:TF:aggregated`, generates narratives via Ollama/LangGraph, publishes to `narratives:SYMBOL:TF`
10. API server reads from streams via SSE for live dashboard, or database for historical queries

**State Management:**

- Ephemeral state (window/frame caches): Stored in-memory in service processes, rebuilt from stream history on restart
- Plugin incremental state (Wilder's smoothing, etc.): Stored in Redis hash `plugin_state:{symbol}:{tf}:{plugin_name}` with 7-day TTL
- Signal ledger state: Persistent in PostgreSQL/TimescaleDB `signal_ledger` table
- Bar history: Redis streams store last N bars per stream (e.g., 1000 bars in indicators stream)

**Backfill/Historical Processing:**

- Triggered by `production/scripts/historical_backfill.py`
- Stage 1 (`--fetch-only`): Downloads OHLCV from IBKR via ib_insync, stores in `market_data_ohlcv` table
- Stage 2 (`--replay-only`): Replays stored OHLCV through full pipeline (indicator_service logic), inserts results to `signal_ledger` and `technical_indicators` tables
- Backfill writes to database directly (not streams) for efficiency

## Key Abstractions

**IndicatorPlugin / PatternPlugin:**
- Purpose: Define contract for intelligence plugins (compute_full, compute_next, metadata)
- Examples: `src/intelligence/indicators/rsi.py`, `src/intelligence/patterns/bollinger_squeeze.py`
- Pattern: Each plugin is a dataclass with ClassVar metadata (name, outputs, min_lookback, supports_incremental, capability_tags, inputs)
- Key methods:
  - `compute_full(frames: dict[str, DataFrame]) → dict[str, Any]` — Full recompute from scratch
  - `compute_next(windows: dict[str, Any]) → dict[str, Any]` — Incremental update using cached state

**Stream Message Format:**

All Redis stream messages are JSON-serialized field dictionaries. Example from indicator_service output:
```json
{
  "timestamp": "2026-02-22T14:30:00Z",
  "symbol": "ESH6",
  "timeframe": "1m",
  "open": "5200.00",
  "high": "5210.50",
  "low": "5195.25",
  "close": "5208.75",
  "volume": "125000",
  "rsi_14": "62.3",
  "ma_20": "5195.4",
  "macd": "12.5",
  ...
}
```

**SignalScore / TradingSignal:**
- Purpose: Structured representation of generated signals
- Location: `src/core/models.py`
- Fields: ID (UUID), symbol, timeframe, entry_price, setup_name, grade (A-D), confidence, timestamp
- Pattern: Published as nested JSONB to `signals:SYMBOL:TF:aggregated` stream, persisted in `signal_ledger`

**LedgerEntry:**
- Purpose: Represent a single signal record with full context
- Location: `src/intelligence/trading/signal_ledger.py`
- Fields: signal_id (UUID), symbol, timeframe, entry_ts, entry_price, setup_name, setup_details (JSON), market_context (JSON), status (enum), exit_ts, exit_price, pnl, pnl_percent
- Key pattern: Immutable insert-only during generation; status updates via separate lifecycle module

**InputSpec:**
- Purpose: Define plugin input requirements
- Location: `src/intelligence/plugins.py`
- Fields: symbol (regex pattern), timeframe (str or list), lookback (int), required (bool)
- Usage: Each plugin declares its inputs so services know what data to fetch before execution

## Entry Points

**High-Frequency TWS Daemon:**
- Location: `production/daemons/high_frequency_tws_daemon.py`
- Triggers: Manual CLI invocation (not auto-started)
- Responsibilities: Connect to IBKR, subscribe to tick updates, publish to Redis streams
- CLI usage: `python production/daemons/high_frequency_tws_daemon.py --client-id 35`
- Exit conditions: SIGTERM, network disconnect, unrecoverable error

**Indicator Service:**
- Location: `services/indicator_service.py`
- Triggers: Consumes `market:SYMBOL:*` streams
- Responsibilities: Run I1 plugins on each bar, publish combined features
- CLI usage: `python services/indicator_service.py`
- Consumer group: Created per-service instance with dynamic naming

**Market Analysis Service:**
- Location: `services/market_analysis_service.py`
- Triggers: Consumes `indicators:SYMBOL:*` streams
- Responsibilities: Execute I3/I4/I5/SMC/I6 tiers, publish intelligence features
- CLI usage: `python services/market_analysis_service.py`
- Key startup validation: Validates all tier plugins registered at startup

**Signal Generator Service:**
- Location: `services/signal_generator_service.py`
- Triggers: Consumes `intelligence:SYMBOL:*` streams
- Responsibilities: Run I7 setup plugins, aggregate signals, insert to ledger
- CLI usage: `python services/signal_generator_service.py`
- Ledger interaction: Uses DatabaseManager to batch-insert signals

**Signal Tracker Service:**
- Location: `services/signal_tracker_service.py`
- Triggers: Consumes `signals:SYMBOL:*:aggregated` and `market:SYMBOL:1m` streams
- Responsibilities: Track signal lifecycle, calculate P&L, update status
- CLI usage: `python services/signal_tracker_service.py`
- Database updates: Via DatabaseManager, may queue updates per batch interval

**AI Narrative Service:**
- Location: `services/ai_narrative_service.py`
- Triggers: Consumes `signals:SYMBOL:*:aggregated` streams
- Responsibilities: Fetch signal details from ledger, generate narratives via Ollama, publish
- CLI usage: `python services/ai_narrative_service.py`
- External dependency: Ollama server on localhost:11434

**FastAPI Server:**
- Location: `src/api/main.py`
- Triggers: Manual CLI invocation or container/deployment startup
- Responsibilities: Serve queries, SSE subscriptions, health checks
- CLI usage: `uvicorn src.api.main:app --host 0.0.0.0 --port 8000`
- Lifespan: Initialize database and Redis managers on startup, clean up on shutdown

**Historical Backfill Script:**
- Location: `production/scripts/historical_backfill.py`
- Triggers: Manual CLI invocation
- Responsibilities: Fetch OHLCV from IBKR, replay through pipeline, populate database
- CLI usage: `python production/scripts/historical_backfill.py --days 90 --client-id 35`
- Flags: `--fetch-only`, `--replay-only`, `--symbols`, `--timeframes`

## Error Handling

**Strategy:** Fail fast with structured logging; use circuit breakers for plugin execution; retry streams operations.

**Patterns:**

- **Plugin Execution:** Wrapped in try-except with record_plugin_execution() metrics; individual plugin failure does not stop service
- **Stream Operations:** Retry on transient Redis errors; log at ERROR level on persistent failures
- **Database Operations:** Use asyncpg's built-in connection pooling with configurable timeouts; raise on constraint violations (e.g., signal_ledger PK)
- **IBKR Connection:** Implement reconnect logic with exponential backoff in daemon; track reconnect count in metrics
- **Graceful Shutdown:** Services catch SIGTERM, flush pending writes, close connections, exit cleanly

**Circuit Breaker Pattern:**

Location: `src/core/plugin_circuit_breaker.py`

Purpose: Prevent cascading failures if a plugin begins failing repeatedly

Behavior: Track failure count per plugin; after threshold (default 3), skip execution and log warning; reset after success period

Usage: Wrapped around plugin.compute_full() and plugin.compute_next() calls in services

## Cross-Cutting Concerns

**Logging:** Structured JSON logs via structlog; all services log to stdout and rotating file handlers in `logs/`

**Validation:** Pydantic models validate OHLCV, signals, and configuration; Stream parsing uses explicit field extraction from byte dictionaries

**Authorization:** Not yet implemented (authentication layer planned for Phase 2 per design doc)

**Rate Limiting:** No rate limiting on internal streams; API endpoints will enforce per-consumer limits when auth layer added

**Observability:** Prometheus metrics on `INDICAGENT_METRICS_PORT` (default 9108); dashboard accesses via SSE for real-time updates

**Data Consistency:** Streams provide ordering guarantees per SYMBOL:TF key; signal_ledger uses transactions; timestamps use ISO 8601 UTC

---

*Architecture analysis: 2026-02-22*
