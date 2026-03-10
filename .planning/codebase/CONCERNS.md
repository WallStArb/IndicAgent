# Codebase Concerns

**Analysis Date:** 2026-02-22

## Tech Debt

**Unused Database Tables — Cold Path Incomplete:**
- Issue: `features` table exists in schema (`production/migrations/001_timescale_schema.sql`) but zero INSERT calls in codebase. Completely unused since platform inception.
- Files: `production/migrations/001_timescale_schema.sql`, `production/migrations/003_timescaledb_enable_and_policies.sql`
- Impact: Schema confusion, wasted DBA effort, misleads developers about where feature data lives. The `intelligence` table is written to instead (scalar-only, lossy).
- Fix approach: Define new `intelligence_features` hypertable with tiered JSONB columns (i1, i3, i4, i5, smc, i6). Wire feature writer service to consume `intelligence:` stream and persist to new table. Deprecate old `features` and `intelligence` tables. See design doc: `docs/plans/2026-02-22-unified-intelligence-data-bus-design.md`.

**Dual Pipeline Services — Architecture Violation:**
- Issue: Both `intelligence_processor_service.py` (707 lines) and `market_analysis_service.py` (533 lines) compute I3-I6 plugins. `intelligence_processor_service` reads raw `market:` stream and recomputes I1 internally. This violates separation of concerns: I1 is already computed by `indicator_service.py` and published to `indicators:` stream.
- Files: `services/intelligence_processor_service.py`, `services/market_analysis_service.py`
- Impact: Code duplication, unclear which service is authoritative, confused team routing. If one changes, the other falls out of sync.
- Fix approach: Deprecate `intelligence_processor_service.py`. Audit any consumers relying on it, migrate to `market_analysis_service.py` which correctly consumes pre-computed `indicators:` stream. Do NOT remove yet — check for undocumented consumers first.

**Incomplete Persistence Layer — Ephemeral GARCH/Kalman:**
- Issue: GARCH and Kalman plugins (I4) compute on every bar and publish to `intelligence:` stream. But zero I7 plugins consume them. LLM agents and ML models will need these outputs — currently no wiring exists.
- Files: `src/intelligence/context/garch_volatility.py`, `src/intelligence/context/kalman_trend.py`, `services/market_analysis_service.py`
- Impact: Valuable volatility and trend context completely orphaned. ML scoring model will lack rich features. LLM narrative service operates blind to current market regime.
- Fix approach: (1) Wire GARCH/Kalman outputs to I7 plugins: `trad_MeanReversion` (gate on kalman_price_position), `trad_VWAPDeviation` (use garch_sigma threshold), `trad_SqueezeExpansion` (garch_vol_regime check). (2) Pass full I4 context block to I8 narrative service. (3) Include in intelligence_features persistence (see above).

**Redis Stream Retention — Ephemeral Data:**
- Issue: Streams configured with `maxlen=2000` (count-based trim, not time-based). At 23 contracts × 4 timeframes, this = ~12 bars of history per symbol/timeframe. On restart or lag, data beyond 12 bars is lost forever.
- Files: `production/daemons/high_frequency_tws_daemon.py` (maxlen=2000), `src/core/redis_streams_manager.py` (stream configuration)
- Impact: Backfill/replay cannot access historical streams. Real-time subscriber lag > 12 bars = data loss. No audit trail for debugging.
- Fix approach: Redis Streams are hot path (real-time). Accept ephemeral retention. Cold path (durable) is TimescaleDB via feature writer service (see unified data bus design).

**Lossy Intelligence Table Schema:**
- Issue: `intelligence` table persists only scalars. Arrays (divergence zones, target lists, FVG bounds), nested objects (SMC geometry), and complex structures all dropped at serialization. Only I7 signal snapshots capture partial context.
- Files: `services/market_analysis_service.py` (publishes flat string k/v), `production/migrations/001_timescale_schema.sql` (intelligence table schema)
- Impact: ML training data lacks rich SMC geometry (order block bounds, FVG structure). Backtesting can't replay full feature state. Audit loss for pattern analysis.
- Fix approach: New `intelligence_features` table with tiered JSONB columns: preserve full structure per tier. Validate schema via Pydantic `IntelligenceEvent` model (to be created in `src/intelligence/schemas.py`).

**Stateless Plugin Replay — Quality Degradation:**
- Issue: Backfill replay (`production/scripts/historical_backfill.py`) recomputes I1-I7 from OHLCV each time. Stateful plugins (GARCH, Kalman, divergence lookback, order blocks) lose warm-up state — first ~50 bars of replay have degraded quality. No warm-up state persistence exists.
- Files: `production/scripts/historical_backfill.py` (Stage 2 replay), `src/intelligence/context/garch_volatility.py`, `src/intelligence/context/kalman_trend.py`
- Impact: ML training data has poor signal quality in first ~50 bars of each replay. Seasonal backtests (365 days) accumulate this degradation at year boundaries.
- Fix approach: Add plugin state protocol (`get_state()`, `restore_state()` methods to all stateful plugins). Persist state to Redis hash `plugin_state:{symbol}:{tf}:{plugin_name}` (7-day TTL). Load on startup, checkpoint every 60 bars. See design: `docs/plans/2026-02-22-unified-intelligence-data-bus-design.md` (section 3).

**Retention Policy Misalignment:**
- Issue: Compression policies apply 7 days after insertion, but retention deletes after 30/60/365 days depending on table. `intelligence` table has NO retention policy — unbounded growth risk. If backfill ever runs to 365 days, table will grow indefinitely.
- Files: `production/migrations/003_timescaledb_enable_and_policies.sql`, `production/migrations/007_fix_compress_orderby_and_retention.sql`
- Impact: Production database bloats without bound. Queries slow over time. Storage costs climb. Queries for seasonal patterns become prohibitive.
- Fix approach: Set explicit retention: `market_data_ohlcv` 90 days, `technical_indicators` 60 days, `signal_ledger` 365 days, `intelligence_features` indefinite (seasonal analysis). No retention on new `intelligence_features` — apply only compression (7 days, then archive cold storage if needed).

## Security Considerations

**API Authentication — Not Implemented:**
- Risk: Backend FastAPI (`:8000`) has no auth. Any local process or network hop can call endpoints. If Vercel frontend connects, external exposure without JWT/API keys.
- Files: `src/api/routes/` (all endpoints), `services/` (no auth checks)
- Current mitigation: None. Runs on localhost only; no external exposure yet.
- Recommendations: (1) Add JWT middleware for human users (Vercel frontend login flow). (2) Add API key support for machine consumers. (3) FastAPI `Depends(verify_auth)` single injection point. See design: `docs/plans/2026-02-22-unified-intelligence-data-bus-design.md` (section 9).

**IBKR Credentials — Environment Variable:**
- Risk: `IBKR_HOST` in `.env` must be kept secret. If `.env` leaks, attacker can connect to home TWS instance and execute trades.
- Files: `.env` (NEVER committed), `src/config/settings.py` (loads via Settings)
- Current mitigation: `.env` in `.gitignore`. Local machine only.
- Recommendations: (1) Use separate credentials file for production (not checked in). (2) If containerizing, use Docker secrets or HashiCorp Vault. (3) Rotate API keys periodically.

**No Rate Limiting:**
- Risk: Backend has no rate limits. A local script can flood endpoints with requests, consuming all database connections.
- Files: All FastAPI routes in `src/api/routes/`
- Current mitigation: Internal use only (localhost).
- Recommendations: Add FastAPI middleware with redis-based rate limiting (e.g., `slowapi`). Tie to API key tier.

## Performance Bottlenecks

**Plugin Circuit Breaker — Complexity at Scale:**
- Problem: `src/core/plugin_circuit_breaker.py` (596 lines) implements sophisticated failure recovery: state tracking, fallback execution, recovery testing, LangGraph integration. While robust, it adds latency (async overhead, metrics recording) to every plugin call.
- Files: `src/core/plugin_circuit_breaker.py`, all service files that instantiate it
- Cause: Over-engineered for current 57-plugin workload. Per-plugin failure tracking, metrics, and recovery testing adds ~5-10ms latency per bar processing.
- Improvement path: (1) Profile to confirm overhead vs production value. (2) If latency is unacceptable, decouple circuit breaker to async background thread (not on hot path). (3) Consider lazy initialization — only track plugins that actually fail.

**Indicator Computation — Deques at Scale:**
- Problem: Backfill and replay use Python `deque(maxlen=200)` for bar history. At 23 contracts × 4 timeframes × multiple lookback windows, memory fragmentation and deque copies can accumulate.
- Files: `production/scripts/historical_backfill.py` (bar_histories dict with deques), `src/indicators/incremental_manager.py` (similar pattern)
- Cause: Deques are convenient but inefficient at large scale. Each deque copy on FIFO rotation copies 200 bars.
- Improvement path: (1) Use numpy arrays with rolling index (O(1) rotation instead of O(n)). (2) Benchmark deque vs numpy at current scale — may be acceptable. (3) For backfill specifically, switch to pandas DataFrame with `.iloc[-200:]` slicing (vectorized, faster).

**JSONB Queries — Index Strategy Missing:**
- Problem: New `intelligence_features` table will store full JSONB payload. Without proper GIN indexes on sub-keys (e.g., `i4.garch_sigma`), queries will scan full column.
- Files: `production/migrations/` (index strategy not yet defined)
- Cause: JSONB queries are powerful but require deliberate indexing. Generic GIN on top-level keys won't help nested queries.
- Improvement path: (1) Add GIN indexes on frequently queried keys: `CREATE INDEX ON intelligence_features USING GIN ((i4->>'garch_sigma'))`. (2) Cluster table by (symbol, tf, ts) for time-range queries. (3) Use `jsonb_path_ops` for prefix searches. (4) Test query plans before enabling historical backfill to 365 days.

**TimescaleDB Compression — Warm-up Stalls:**
- Problem: Compression policy runs every 7 days. When chunks are compressed, first query after compression decompresses entire chunk (~1GB) into memory before filtering. Can stall queries for seconds.
- Files: `production/migrations/006_timescale_compression_retention.sql`, `production/migrations/007_fix_compress_orderby_and_retention.sql`
- Cause: TimescaleDB optimization strategy trades insert speed for query latency. Acceptable for cold data, not for active features.
- Improvement path: (1) Compress only data > 30 days old (not 7 days). (2) Stagger compression to background hours. (3) Monitor decompression latency with `timescaledb.compressed_chunk_decompress_count` metric. (4) Archive to cold storage (S3) after 90 days if seasonal analysis is the only consumer.

## Fragile Areas

**Intelligence Processor Dependency Chain:**
- Files: `services/intelligence_processor_service.py` (707 lines), depends on `market:` stream format, raw OHLCV handling, I1 recomputation.
- Why fragile: Single service with multiple responsibilities (stream consumption, I1 computation, I3-I6 execution, Redis publishing). If one part breaks, whole service stops. I1 recomputation duplicates logic from `indicator_service.py` — if either changes, they diverge.
- Safe modification: Before touching, audit consumers. Create feature flag to toggle between `intelligence_processor_service` and `market_analysis_service`. Run parallel for 1 week, then migrate consumers.
- Test coverage: Likely has unit tests but no integration tests with actual `market:` stream. Add E2E test with real IBKR data.

**Plugin Registry — Tier Validation at Startup:**
- Files: `src/intelligence/register_plugins.py` (tier constants), `services/` (import and use tier constants)
- Why fragile: v4.9.1 refactor moved all tier lists to `register_plugins.py` constants. If plugin is added but not added to correct TIER_* list, service crashes on startup (`PluginRegistry.validate_tier()` hard-crashes). Good for safety, but requires exact coordination.
- Safe modification: When adding new plugin: (1) Add to plugin file (e.g., `src/intelligence/patterns/`). (2) Add to `registry.register_plugin()` call in `register_plugins.py`. (3) Add to correct `TIER_*` constant. (4) Add to all 5 service files that use tiers. (5) Run services and verify startup succeeds.
- Test coverage: Unit tests for tier constants exist. No test that verifies service startup validates tiers correctly.

**Multi-Service Stream Synchronization:**
- Files: `services/indicator_service.py`, `services/market_analysis_service.py`, `services/signal_generator_service.py`, all consuming from Redis Streams
- Why fragile: If any service lags or crashes, stream consumer group falls behind. Other services waiting on features from lagging service will get stale data. No backpressure mechanism.
- Safe modification: Monitor consumer group lag (`XINFO GROUPS intelligence:SYMBOL:TF`). Set up alerts for lag > 1000ms. If lag spikes, manually ack previous batch and resume.
- Test coverage: No tests for multi-service lag or coordination. Add integration test: start all services, inject load, verify lag stays < threshold.

**Backfill Script — Replay Quality Variance:**
- Files: `production/scripts/historical_backfill.py` (686 lines, 17 unit tests)
- Why fragile: Stage 2 replay (I1-I7 from OHLCV) drops plugin state. First ~50 bars of replay have degraded quality (especially GARCH/Kalman). If backfill is rerun with different date range, state variance is inconsistent.
- Safe modification: Before running backfill, review design doc for state persistence plan (`docs/plans/2026-02-22-unified-intelligence-data-bus-design.md` section 3). Implement plugin state save/restore, then rerun entire backfill for consistency.
- Test coverage: 17 unit tests for script. Tests mock IBKR and DB. No test for full end-to-end replay with real data. Run manually on test DB with 30 days of real IBKR data before production run.

**Dashboard SSE Connection — No Reconnect Logic:**
- Files: `src/api/routes/sse.py`, `dashboard/src/hooks/use-market-stream.ts`
- Why fragile: SSE is stateless HTTP streaming. If backend crashes or network hiccups, frontend loses connection. Frontend has no auto-reconnect, no fallback, no buffer of missed updates.
- Safe modification: (1) Add exponential backoff reconnect in `use-market-stream.ts` (start 1s, max 30s). (2) Add message deduplication (include sequence number). (3) Add last-seen timestamp; query history on reconnect to fill gap.
- Test coverage: No tests for SSE. Add test: start stream, simulate network dropout, verify auto-reconnect succeeds.

## Scaling Limits

**Redis Retention — Per-Symbol Limits:**
- Current capacity: `maxlen=2000` per stream. At 23 contracts × 4 timeframes = 92 streams. Total retention = ~92 × 2000 = 184K messages ≈ 18 seconds of data at 10K msgs/sec market velocity.
- Limit: Subscriber lag > 18s = data loss. If backfill reader is slow, will miss bars.
- Scaling path: (1) Accept ephemeral Redis, rely on TimescaleDB for durable history. (2) For backfill, switch to direct DB read instead of streaming (already done in backfill.py — no longer uses streams). (3) Monitor lag; if frequent lag spikes, increase `maxlen` to 5000 (uses more memory).

**TimescaleDB Connection Pool — Async Overhead:**
- Current capacity: Default psycopg2 pool (5 connections). With 7 services + backfill + dashboard, can exhaust pool if one service crashes and doesn't release connections.
- Limit: Database lock timeout (default 30s). Long-running queries block others.
- Scaling path: (1) Use `asyncpg` with larger pool (20 connections) for async services. (2) Monitor pool exhaustion: `SELECT count(*) FROM pg_stat_activity WHERE state = 'active'`. (3) Set statement timeout to 30s to abort runaway queries.

**Dashboard Concurrency — WebSocket vs SSE:**
- Current capacity: SSE (Server-Sent Events) can handle ~100 concurrent clients with 1-2 message/sec throughput on a single FastAPI worker.
- Limit: If dashboard goes viral (100+ concurrent users), backend will hit CPU/memory limits. Single worker will saturate.
- Scaling path: (1) Run FastAPI with multiple workers (e.g., gunicorn -w 4). (2) Switch from SSE to WebSocket for true bidirectional (allows Vercel frontend to send queries, not just consume broadcast). (3) Add Redis pub/sub for multi-worker coordination (broadcast to all workers' SSE clients).

**IBKR Rate Limits — Contract Limits:**
- Current capacity: 23 contracts, 6 timeframes = 138 active subscriptions. IBKR allows ~40-50 simultaneous subscriptions per account.
- Limit: >50 subscriptions = connection errors, auto-disconnect.
- Scaling path: (1) If expanding to 50+ contracts, need separate IBKR account or reduce timeframes. (2) Use market data snapshot mode (poll instead of subscribe) for low-velocity timeframes (4h, 1d). (3) Rotate subscriptions dynamically — subscribe to active contracts only during trading hours.

## Test Coverage Gaps

**Multi-Service Integration — No E2E Tests:**
- What's not tested: Full pipeline from IBKR tick → `market:` stream → `indicator_service` → `indicators:` stream → `market_analysis_service` → `intelligence:` stream → dashboard SSE. If any service is down, integration breaks silently.
- Files: Tests exist for individual services (`test_indicator_service.py`, etc.). No `test_e2e_pipeline.py`.
- Risk: Deployment failures go unnoticed until production. A service refactor that breaks the stream format will only be caught when dashboard breaks.
- Priority: High. Add E2E test: mock IBKR, start all services, inject bars, verify dashboard receives updates.

**Plugin State Persistence — Protocol Not Tested:**
- What's not tested: `get_state()` / `restore_state()` methods on stateful plugins. No test verifies that state saved at shutdown can be loaded at startup.
- Files: No test file for plugin state protocol. `src/intelligence/context/garch_volatility.py` and `kalman_trend.py` don't have test coverage for state methods.
- Risk: When state persistence is implemented (see Tech Debt section), it will break silently because there are no tests.
- Priority: Medium (blocking). Before implementing state persistence, write tests for each stateful plugin's state protocol.

**Backfill Replay Quality Validation — No Assertions:**
- What's not tested: First 50 bars of replay have degraded indicator quality due to warm-up loss. No test verifies that replay quality is acceptable.
- Files: `production/scripts/historical_backfill.py` (Stage 2 replay), 17 unit tests (all mock DB).
- Risk: Backfill runs to completion but signals have poor quality. ML model trains on degraded data. No one notices until model performance is poor in production.
- Priority: Medium. Add test: run backfill, compare first-50-bars RSI/MACD values vs live computation on same data. Assert that degradation is < 5%.

**SSE Streaming — Load Tests Missing:**
- What's not tested: Dashboard SSE under concurrent load. How many clients before connection drops? What message throughput before backend saturates?
- Files: `src/api/routes/sse.py` (no load tests), `dashboard/` (no load tests).
- Risk: 50 concurrent dashboard users → backend crashes. Unknown until production.
- Priority: Low (nice-to-have, acceptable failure mode for 1.0). Before external Vercel frontend launch, add locust test: 50 concurrent clients, verify <5% message drop rate.

**Retention Policy Cleanup — No Verification:**
- What's not tested: Retention policies actually delete expired data. No test verifies that `signal_ledger` rows > 365 days old are deleted.
- Files: Retention policies defined in `production/migrations/007_fix_compress_orderby_and_retention.sql`. No test.
- Risk: Retention policy is misconfigured or never applied. Database grows unbounded. No one notices until disk is full.
- Priority: High (critical). Add test: insert a row with timestamp 400 days ago, wait 1 day, verify it's deleted.

## Known Bugs

**Dashboard Component Missing — No Longer Generated:**
- Symptoms: Dashboard signals/narrative panels wired (v4.4.0). But if a new component is added to `signal_orchestrator_service.py` output, dashboard doesn't auto-generate new panels.
- Files: `dashboard/src/components/` (manual component library), `services/signal_orchestrator_service.py` (hardcoded output schema)
- Trigger: Add new signal component to orchestrator → dashboard doesn't show it → admin confusion.
- Workaround: Manually add React component to dashboard, wire to SSE payload. No auto-generation.
- Status: Accepted limitation — no plans to auto-generate (too risky). Documented in STATUS.md.

## Missing Critical Features

**Alert System — No Alerts Defined:**
- Problem: No alerts for critical failures: service crashes, lag spikes, DB errors, IBKR disconnects.
- Blocks: Production monitoring. If service crashes at 3am, no one knows until market opens and trades don't execute.
- Recommended implementation: Integrate with health endpoints (`:9109/health` for indicator service, etc.). Poll every 30s. Alert on 2 consecutive failures. Send to Slack/email.

**HTTPS Reverse Proxy — Required for External Frontend:**
- Problem: Backend FastAPI runs on `:8000` HTTP. Vercel frontend will refuse to call HTTP endpoint (CORS/security).
- Blocks: External frontend access. Currently blocked.
- Recommended implementation: Cloudflare Tunnel (free, no port forwarding). See design doc: `docs/plans/2026-02-22-unified-intelligence-data-bus-design.md` (section 11).

**Feature Writer Service — Not Yet Implemented:**
- Problem: `intelligence_features` hypertable defined in design but Feature Writer Service (`services/feature_writer_service.py`) does not exist. Intelligence data flows to Redis, not persisted to cold storage.
- Blocks: Historical feature access, ML training data collection, backtest replay with full context.
- Recommended implementation: See design doc Phase 2: `docs/plans/2026-02-22-unified-intelligence-data-bus-design.md` (section 7).

---

*Concerns audit: 2026-02-22*
