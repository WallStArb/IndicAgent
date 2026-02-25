# Roadmap: IndicAgent Unified Data Bus

## Overview

This milestone transforms IndicAgent from a reactive signal pipeline with ephemeral Redis state into a canonical typed intelligence bus with durable feature storage, and a live dashboard showing all intelligence tiers in real time. Phase 0–4 are complete: typed schema, feature store, historical backfill, and query API. The remaining phases focus on getting the full I1→I8 pipeline running live and reliably, then connecting the dashboard to display every data tier end-to-end.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 0: GARCH/Kalman Quality Gates** - Wire GARCH/Kalman outputs into I7 plugins as entry filters (COMPLETE 2026-02-22)
- [x] **Phase 1: Typed Event Schema** - Define IntelligenceEvent Pydantic schema, update publisher, migrate consumers, deprecate old service (COMPLETE 2026-02-23)
- [x] **Phase 2: Feature Store** - intelligence_features hypertable, Feature Writer Service, signal_ledger enhancement (COMPLETE 2026-02-23)
- [x] **Phase 3: Historical Data** - 35-day backfill: 391K feature rows, 248K signals, 0 orphans (COMPLETE 2026-02-24)
- [x] **Phase 4: Query API** - Historical feature and signal query endpoints on existing FastAPI (COMPLETE 2026-02-24)
- [ ] **Phase 5: Live Pipeline** - All 8 services running together, full I1→I8 data flowing live through Redis streams
- [ ] **Phase 6: Dashboard Connected** - Fix SSE multi-TF bug, verify every panel (indicators/structure/context/patterns/SMC/confluence/signals/narrative) shows real data
- [ ] **Phase 7: Dashboard Complete** - Any remaining stubbed panels, signal history view, timeframe matrix wired to live data

## Phase Details

### Phase 1: Typed Event Schema
**Goal**: Every intelligence output flows through one canonical typed bus — IntelligenceEvent replaces flat string k/v stream messages and intelligence_processor_service.py is gone
**Depends on**: Nothing (Phase 0 complete)
**Requirements**: BUS-01, BUS-02, BUS-03, BUS-04
**Status**: COMPLETE 2026-02-23
**Plans**: 3/3 complete

Plans:
- [x] 01-01-PLAN.md — Define IntelligenceEvent schema (src/intelligence/schemas.py) + update market_analysis_service.py publisher (TDD)
- [x] 01-02-PLAN.md — Migrate signal_generator_service.py and dashboard parseIntelligence() to consume IntelligenceEvent
- [x] 01-03-PLAN.md — Delete intelligence_processor_service.py, 3 test files, config, and clean up all codebase references

### Phase 2: Feature Store
**Goal**: Every IntelligenceEvent is persisted to TimescaleDB so features are queryable historically and ML training data accumulates automatically
**Depends on**: Phase 1
**Requirements**: FST-01, FST-02, FST-03, FST-04
**Status**: COMPLETE 2026-02-23
**Plans**: 3/3 complete

Plans:
- [x] 02-01-PLAN.md — DB migrations: intelligence_features hypertable (tiered JSONB, GIN indexes, 7-day compression, no retention) + signal_ledger feature_ts/feature_tf columns
- [x] 02-02-PLAN.md — Build services/feature_writer_service.py (consumer group feature_writer:persist, buffer, batch INSERT to intelligence_features, metrics port 9115, TDD)
- [x] 02-03-PLAN.md — Wire feature_ts/feature_tf: update LedgerEntry+_INSERT_SQL (24 params), signal_generator build_ledger_entries(), backfill _INSERT_SYNC_SQL (NULL passthrough)

### Phase 3: Historical Data
**Goal**: intelligence_features and signal_ledger are populated with history — enough training data for future ML and enough signals for performance analysis
**Depends on**: Phase 2
**Requirements**: HST-01, HST-02, HST-03
**Status**: COMPLETE 2026-02-24 (35 days; HST-01: 248K signals ✅, HST-02: 391K features ✅, HST-03: 0 orphans ✅)
**Plans**: 3/3 complete

Plans:
- [x] 03-01-PLAN.md — Extend historical_backfill.py Stage 2 to write to intelligence_features alongside signal_ledger; set source='backfill' (TDD)
- [x] 03-02-PLAN.md — Run backfill (35 days), diagnose + fix schema field type bug (12 float→bool mismatches), re-run Stage 2
- [x] 03-03-PLAN.md — Post-backfill SQL validation audit: row counts, date coverage, JOIN integrity, JSONB structure check

### Phase 4: Query API
**Goal**: Historical intelligence data is queryable via REST endpoints — feature context, signal history, and SSE stream all speak IntelligenceEvent
**Depends on**: Phase 3
**Requirements**: API-01, API-02, API-03
**Status**: COMPLETE 2026-02-24
**Plans**: 3/3 complete

Plans:
- [x] 04-01-PLAN.md — TDD: GET /api/features/{symbol}/{timeframe} + GET /api/features/export (Parquet) with pyarrow
- [x] 04-02-PLAN.md — TDD: GET /api/signals/{symbol} with optional intelligence_features LEFT JOIN
- [x] 04-03-PLAN.md — Wire routers into main.py + SSE intelligence_data payload tests (API-03)

### Phase 5: Live Pipeline
**Goal**: All 8 services running together under systemd, full I1→I8 data flowing live — indicators, intelligence, signals, and narratives all present in Redis streams simultaneously
**Depends on**: Phase 4
**Success Criteria** (what must be TRUE):
  1. All 8 systemd services start cleanly and stay running: tws, indicator, market-analysis, signal-generator, signal-tracker, ai-narrative, feature-writer, api
  2. `development:intelligence:ESH6:1m` has live messages within 2 minutes of services starting — market_analysis_service is consuming indicator output and publishing IntelligenceEvent
  3. `development:signals:ESH6:1m:aggregated` has live messages — signal_generator is consuming intelligence stream and producing signals
  4. `development:narratives:ESH6:1m` has live messages — ai-narrative service is producing narratives
  5. feature_writer_service is consuming the intelligence stream and writing rows to intelligence_features (live row count grows over time)
  6. No service crash-loops — all services stable for 30+ minutes under systemd supervision
**Plans**: 3 plans

Plans:
- [ ] 05-01-PLAN.md — Fix TWS daemon false-connected bug + feature_writer symbol config + add indicagent-timeframes.service (TDD)
- [ ] 05-02-PLAN.md — End-to-end RTH smoke test: start all 9 services, verify live data flows through every tier (checkpoint)
- [ ] 05-03-PLAN.md — Stability audit: no crash-loops in 30+ min, metrics endpoints healthy, consumer group health, qualify_instrument investigation

### Phase 6: Dashboard Connected
**Goal**: The dashboard shows real live data in every panel — not simulated data, not empty panels — for all intelligence tiers I1–I8
**Depends on**: Phase 5
**Success Criteria** (what must be TRUE):
  1. SSE connection to `/api/sse/events` works with the dashboard's symbol list — browser DevTools shows `intelligence_data`, `indicator_data`, `signal_data`, `narrative_data` events arriving
  2. Fix SSE multi-TF bug: backend correctly subscribes to per-TF streams when comma-separated timeframes are requested (or frontend sends single TF at a time)
  3. Price hero shows live bid/ask/last price updating in real time
  4. Indicator panel (I1) shows real RSI, MACD, ATR, etc. from the live indicator stream
  5. Structure/Context/Pattern/SMC/Confluence panels (I3–I6) show real values from intelligence_data events
  6. Signal panel (I7) shows real signals with direction, confidence, entry/stop
  7. Narrative panel (I8) shows real AI narrative text from the live narrative stream
  8. Connection status indicator accurately reflects SSE state (connecting/connected/disconnected)
**Plans**: 4 plans

Plans:
- [ ] 06-01-PLAN.md — Backend fixes: implement TimeframeBuilder, fix qualify_instrument currency, add 1m to AI narrative
- [ ] 06-02-PLAN.md — Frontend data layer + Price Hero: fix event.tf bug, session tracking, tickFlash, rebuild price-hero.tsx
- [ ] 06-03-PLAN.md — SMC panel: extend SmartMoneyData with HMM regime + liquidity zones, render in SmartMoneyPanel
- [ ] 06-04-PLAN.md — Human verification checkpoint: confirm all panels show real live data

### Phase 7: Dashboard Complete
**Goal**: Dashboard is fully functional — all panels wired, signal history browsable, timeframe matrix live, no stubs or placeholder data
**Depends on**: Phase 6
**Success Criteria** (what must be TRUE):
  1. Timeframe matrix shows live signal direction across all configured timeframes (1m/5m/15m/1h) for the selected symbol
  2. Signal history is browsable — either via a panel or drill-down view showing recent signals with entry/stop/outcome
  3. No panels show zeroed or placeholder values when the pipeline is live — every panel either shows real data or a clear "no data yet" state
  4. Dashboard works correctly for all configured symbol profiles (equity index, energy, metals, rates groups)
**Plans**: TBD

Plans:
- [ ] 07-01: Timeframe matrix — wire to live per-TF signal data from SSE tfSignals state
- [ ] 07-02: Signal history view — connect to GET /api/signals/{symbol} for browsable recent signals
- [ ] 07-03: Final audit — all panels, all symbol profiles, all timeframes

## Progress

**Execution Order:**
Phases execute in numeric order: 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 0. GARCH/Kalman Quality Gates | 3/3 | Complete | 2026-02-22 |
| 1. Typed Event Schema | 3/3 | Complete | 2026-02-23 |
| 2. Feature Store | 3/3 | Complete | 2026-02-23 |
| 3. Historical Data | 3/3 | Complete | 2026-02-24 |
| 4. Query API | 3/3 | Complete | 2026-02-24 |
| 5. Live Pipeline | 1/3 | In Progress|  |
| 6. Dashboard Connected | 2/4 | In Progress|  |
| 7. Dashboard Complete | 0/3 | Not started | - |

## Backlog

Items decided but not yet scheduled into a phase. Pull into a milestone when ready.

| Item | Notes | Analysis |
|------|-------|---------|
| Add i7/i8 columns to intelligence_features | Add `i7 JSONB` (which setups fired + scores) and `i8 JSONB` (narrative text + model metadata) to `intelligence_features`. Use enrichment stream pattern: signal_generator → `intelligence_i7:SYMBOL:TF`, ai_narrative → `intelligence_i8:SYMBOL:TF`; feature_writer UPSERTs both. Keeps `signal_ledger` as operational trading log. | `analysis/2026-02-24-feature-store-completeness.md` |
| ML Scoring Model | Train XGBoost/LightGBM on `intelligence_features` joined to `signal_ledger` outcomes; A/B test rules vs scored aggregator; monthly retraining pipeline. Needs ~90 days of signal history. Files: `feature_engineering.py`, `calibrate_model.py`, `scored_aggregator.py`. | — |
| Auth and External Access | JWT + API key auth via single Depends(verify_auth); Cloudflare Tunnel for HTTPS external access; authenticated SSE for Vercel frontend. Revisit when external consumer exists. | — |
| Gap-fill service | Detect + backfill gaps in `market_data_ohlcv` from downtime/TWS disconnects. Fetch only missing windows, replay Stage 2 for those windows only. | — |
| Days-to-expiry feature | Compute `(expiry_date - bar_ts).days` → store in `intelligence_features`. Roll proximity affects behavior. | — |
| Roll premium/discount feature | Front/back month spread at roll = contango/backwardation signal. Valuable for CL and equity index. | — |
| Gap Analysis Setup (I7) | `trad_GapAnalysis`: opening gap >X ticks → fade or continuation. Best for ES/NQ at 9:30 ET session open. File: `src/intelligence/trading/gap_analysis.py`. | — |
| Candlestick Pattern Setup (I7) | `trad_CandlestickPattern`: doji/hammer/engulfing + confluence at key levels. Reversal signals. File: `src/intelligence/trading/candlestick_patterns.py`. | — |
| Session Extremes Setup (I7) | `trad_SessionExtremes`: Asian session high/low holds during London/NY → fade. Time-based reversion. File: `src/intelligence/trading/session_extremes.py`. | — |
| Orderflow Integration | Upgrade `hf_tws_daemon` to `reqTickByTickData`; new stream `orderflow:SYMBOL:live`; per-bar delta metrics (buy_vol, sell_vol, cumulative_delta, delta_pct). Enables: Delta Divergence, Imbalance Continuation, Absorption Detection, Iceberg Order plugins. | — |
| Portfolio Management | Correlation matrix service (rolling cross-instrument correlations, correlated pair flagging); portfolio risk manager (sector exposure limits, dynamic position sizing); symbol rotation (prioritize best-performing setups). | — |
| Robinhood-Style Scaling | Consumer Proxy pattern (health monitoring, auto-recovery, circuit breaker, latency-based auto-scaling); Changelog Streams for state recovery (mirror streams to `:changelog`, recover plugin state after restart). Full design + code: `.planning/analysis/2026-02-12-robinhood-scaling-patterns.md`. Architecture comparison: `.planning/analysis/2026-02-13-robinhood-architecture-comparison.md`. | — |
