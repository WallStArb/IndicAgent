# Requirements: IndicAgent

**Defined:** 2026-02-22
**Core Value:** Every intelligence output flows through one canonical typed bus that both internal and external consumers can trust.

## Validated Requirements

Already built, tested, and working. Locked — changing requires explicit discussion.

### Data Ingestion
- ✓ **ING-01**: System ingests real-time IBKR tick data and aggregates to 1m bars — existing
- ✓ **ING-02**: System aggregates 1m bars to 5m/15m/1h/4h/1d timeframes — existing
- ✓ **ING-03**: System stores OHLCV history in TimescaleDB `market_data_ohlcv` — existing

### Technical Indicators (I1)
- ✓ **IND-01**: System computes 23 technical indicators per bar with incremental support — existing
- ✓ **IND-02**: System publishes OHLCV + I1 features to `indicators:SYMBOL:TF` stream — existing

### Intelligence Pipeline (I3–I6)
- ✓ **INT-01**: System runs market structure analysis (I3: swing/S&R/trend) — existing
- ✓ **INT-02**: System runs context analysis (I4: vol regime, trend, momentum, GARCH, Kalman) — existing
- ✓ **INT-03**: System runs pattern detection (I5: divergence, squeeze, confluence, chart patterns) — existing
- ✓ **INT-04**: System runs smart money concepts (SMC: BOS/CHoCH, FVG, order blocks, liquidity sweeps) — existing
- ✓ **INT-05**: System runs cross-timeframe confluence scoring (I6) — existing
- ✓ **INT-06**: GARCH/Kalman outputs gate I7 signal quality (MeanReversion, VWAPDeviation, SqueezeExpansion) — Phase 0, 2026-02-22

### Signal Generation (I7)
- ✓ **SIG-01**: System generates trading setup signals via 9 I7 plugins with aggregation — existing
- ✓ **SIG-02**: System persists signals to `signal_ledger` with grade, confidence, setup details — existing
- ✓ **SIG-03**: System tracks signal lifecycle (pending → active → exit) with P&L — existing

### AI Narrative (I8)
- ✓ **NAR-01**: System generates human-readable narratives for active signals via Ollama/LangGraph — existing

### Infrastructure
- ✓ **INF-01**: Plugin circuit breaker prevents cascading failures — existing
- ✓ **INF-02**: Plugin state persisted in Redis hash, survives restarts — existing
- ✓ **INF-03**: Plugin tier registry as single source of truth with startup validation — existing
- ✓ **INF-04**: Historical backfill pipeline (IBKR → pipeline → signal_ledger) — existing
- ✓ **INF-05**: FastAPI with SSE streaming and historical query endpoints — existing
- ✓ **INF-06**: Prometheus metrics + structured logging on all services — existing

## v1 Requirements

Building this milestone.

### Bus Schema
- [x] **BUS-01**: System defines `IntelligenceEvent` Pydantic model with tiered JSONB structure (i1/i3/i4/i5/smc/i6), version field, and `platform` dimension
- [x] **BUS-02**: `market_analysis_service.py` publishes `IntelligenceEvent` to `intelligence:SYMBOL:TF` stream replacing flat k/v strings
- [x] **BUS-03**: All downstream consumers (signal_generator, API, ML) deserialize `IntelligenceEvent` instead of raw field dicts
- [x] **BUS-04**: `intelligence_processor_service.py` deprecated and removed; `market_analysis_service.py` is sole canonical pipeline

### Feature Store
- [x] **FST-01**: `intelligence_features` TimescaleDB hypertable created with tiered JSONB columns, GIN indexes, no retention policy
- [x] **FST-02**: Feature Writer Service (`services/feature_writer_service.py`) consumes `intelligence:` stream via consumer group and batch-writes to `intelligence_features`
- [x] **FST-03**: `signal_ledger` gains `feature_ts` + `feature_tf` columns enabling JOIN to full feature context
- [x] **FST-04**: DB compressed after 7 days, indefinite retention for seasonal ML analysis

### Historical Data
- [ ] **HST-01**: Historical backfill runs 365 days producing 2,700+ signals in `signal_ledger`
- [x] **HST-02**: `intelligence_features` populated with corresponding feature history for ML training
- [x] **HST-03**: Backfill writes both `signal_ledger` and `intelligence_features` in Stage 2

### Query API
- [x] **API-01**: `GET /api/features/{symbol}/{timeframe}` returns paginated `intelligence_features` with date range filter
- [x] **API-02**: `GET /api/signals/{symbol}` returns signal history with optional JOIN to feature context
- [x] **API-03**: Existing SSE stream endpoint updated to publish typed `IntelligenceEvent` payloads

### ML Scoring Model
- [ ] **ML-01**: ML model trained on `intelligence_features` to predict signal success probability
- [ ] **ML-02**: ML scoring runs as I7 plugin or post-I7 layer, adding `ml_score` field to signals
- [ ] **ML-03**: ML model versioned and retrainable from `intelligence_features` historical data

### Dashboard Connected (Phase 6)
- [x] **DASH-01**: SSE connection to `/api/sse/events` works from the dashboard — browser DevTools shows `intelligence_data`, `indicator_data`, `signal_data`, `narrative_data` events arriving
- [x] **DASH-02**: All 23 contracts qualify successfully — SR1H6, 6EH6, 6JH6, BTCH6, BZJ6, NGJ6 no longer fail `qualify_instrument`
- [x] **DASH-03**: Price hero shows live bid/ask/last price with colour-coded direction, flash animation, dual % change (vs prevClose + vs sessionOpen), dual range bars (bar + session), VWAP
- [x] **DASH-04**: Indicator panel (I1) shows real non-zero RSI, MACD, ATR values from live indicator stream, per timeframe tab
- [x] **DASH-05**: Structure/Context/Pattern panels (I3–I5) show real values from `intelligence_data` SSE events including I3 swing/S&R, I4 vol/trend/momentum regime, I5 divergence/squeeze/confluence
- [x] **DASH-06**: SMC panel (I6) shows BOS/CHoCH/FVG signals, HMM regime (label + probability), and liquidity zones (BSL/SSL levels + premium/discount badge)
- [ ] **DASH-07**: Signal panel (I7) shows direction, confidence %, entry price, and stop loss; narrative panel (I8) shows AI narrative text
- [x] **DASH-08**: Connection status indicator accurately reflects SSE state (connecting/connected/disconnected) — green dot with "Live" label when connected

### Auth & External Access
- [ ] **AUTH-01**: Single `Depends(verify_auth)` FastAPI dependency accepts JWT (human/Vercel) and API key (machine)
- [ ] **AUTH-02**: Cloudflare Tunnel configured for HTTPS external access to FastAPI
- [ ] **AUTH-03**: External consumers (Vercel frontend, external apps) can subscribe to `IntelligenceEvent` stream via authenticated SSE

## v2 Requirements

Deferred — not in this milestone's roadmap.

### Multi-Platform Bus
- **PLAT-01**: Fundamentals intelligence platform (earnings, balance sheets, cash flows)
- **PLAT-02**: Sentiment intelligence platform (options flow, put/call, social)
- **PLAT-03**: News intelligence platform (earnings announcements, macro events)
- **PLAT-04**: Cross-platform AI agents synthesizing signals across all platforms

### Additional Signal Intelligence
- **SINT-01**: Additional I7 plugins consuming new GARCH/Kalman outputs (beyond Phase 0 gates)
- **SINT-02**: Regime-aware signal weighting based on GARCH volatility forecast

## Out of Scope

| Feature | Reason |
|---------|--------|
| Order execution / trade management | Intelligence platform only — no execution engine |
| Portfolio management / position sizing | Out of scope for intelligence layer |
| Real-time latency SLAs / co-location | Not a HFT system; latency target is seconds, not microseconds |
| Full multi-platform build | Future milestone — design accommodates it, build defers it |

## Traceability

| Requirement | Phase | Phase Name | Status |
|-------------|-------|------------|--------|
| BUS-01 | Phase 1 | Typed Event Schema | Complete (01-01) |
| BUS-02 | Phase 1 | Typed Event Schema | Complete (01-01) |
| BUS-03 | Phase 1 | Typed Event Schema | Complete (01-02) |
| BUS-04 | Phase 1 | Typed Event Schema | Pending |
| FST-01 | Phase 2 | Feature Store | Pending |
| FST-02 | Phase 2 | Feature Store | Pending |
| FST-03 | Phase 2 | Feature Store | Pending |
| FST-04 | Phase 2 | Feature Store | Pending |
| HST-01 | Phase 3 | Historical Data | Pending |
| HST-02 | Phase 3 | Historical Data | Pending |
| HST-03 | Phase 3 | Historical Data | Pending |
| API-01 | Phase 4 | Query API | Complete |
| API-02 | Phase 4 | Query API | Pending |
| API-03 | Phase 4 | Query API | Pending |
| ML-01 | Phase 5 | ML Scoring Model | Pending |
| ML-02 | Phase 5 | ML Scoring Model | Pending |
| ML-03 | Phase 5 | ML Scoring Model | Pending |
| DASH-01 | Phase 6 | Dashboard Connected | Pending |
| DASH-02 | Phase 6 | Dashboard Connected | Pending |
| DASH-03 | Phase 6 | Dashboard Connected | Pending |
| DASH-04 | Phase 6 | Dashboard Connected | Pending |
| DASH-05 | Phase 6 | Dashboard Connected | Pending |
| DASH-06 | Phase 6 | Dashboard Connected | Pending |
| DASH-07 | Phase 6 | Dashboard Connected | Pending |
| DASH-08 | Phase 6 | Dashboard Connected | Pending |
| AUTH-01 | Phase 7 | Auth and External Access | Pending |
| AUTH-02 | Phase 7 | Auth and External Access | Pending |
| AUTH-03 | Phase 7 | Auth and External Access | Pending |

**Coverage:**
- v1 requirements: 28 total
- Mapped to phases: 28
- Unmapped: 0 ✓

---
*Requirements defined: 2026-02-22*
*Last updated: 2026-02-23 — BUS-01, BUS-02, BUS-03 complete (Plans 01-01, 01-02)*
