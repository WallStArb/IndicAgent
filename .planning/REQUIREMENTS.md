# Requirements: IndicAgent v1.4 Quant Foundation

**Defined:** 2026-03-04
**Core Value:** Every intelligence output flows through one canonical typed bus that both internal and external consumers can trust.

---

## Design Philosophy

v1.4 is built to Renaissance Technologies standard. Jim Simons' three foundational principles govern every requirement here:

1. **Data first, not models** — "We don't start with models. We start with data." Every bar accumulating without complete features in `intelligence_features` is a permanently incomplete training sample. We cannot go back.

2. **Signal validation before scale** — "Most signals they find are discarded unless statistically valid." I7 plugins currently fire regardless of market regime. This is not quant-grade. Signals must clear regime, conviction, and stability gates before firing. New indicators must be validated on historical data before live promotion.

3. **Self-improving systems** — "Both managers and algorithms are monitoring current conditions." Static weights that don't update from signal outcomes is not Renaissance-grade. Outcome data must feed back into signal selection without manual intervention.

---

## v1.4 Requirements

### Discipline 1: Signal Integrity (SIGINT)

*Stop generating structurally false signals. Mean-reversion setups firing in trending markets, trend setups firing in ranging markets — these are not edge, they are noise. Renaissance would discard any signal that ignores market state.*

- [x] **SIGINT-01**: Every I7 plugin reads `hmm_regime` from the IntelligenceEvent SMC tier and applies a regime-appropriate gate before firing (trend/momentum setups: regime 1 or 2 only; mean-reversion setups: regime 0 only)
- [x] **SIGINT-02**: Every I7 plugin applies a conviction gate — `hmm_regime_prob < 0.60` suppresses the signal regardless of setup logic
- [x] **SIGINT-03**: Every I7 plugin applies a stability gate — `hmm_regime_duration < 5` suppresses the signal (new regime may be a false start; require 5-bar confirmation)
- [x] **SIGINT-04**: Regime authority for gating uses 5m or 15m timeframe HMM regime, not 1m (1m HMM is noisy; 5m regime is the minimum reliable unit for signal gating)
- [x] **SIGINT-05**: All I7 signals are emitted to the aggregator regardless of regime eligibility, carrying a `regime_eligible` boolean and `suppression_reason` (null / `regime_type` / `regime_prob` / `regime_duration`). Aggregator excludes ineligible signals from selection but records them in `signal_ledger` with `status='regime_suppressed'`. Signal lifecycle tracks their would-be MAE/MFE/outcome — these "shadow signals" are the feedback data for validating and tuning gate thresholds. A gate that cannot be validated by its own shadow data has no place in a quant system.

### Discipline 2: Data Completeness (DATA)

*Never lose a training sample. The ML layer cannot be built on incomplete rows. Every bar written to `intelligence_features` today becomes a permanent training record — missing i7/i8 data cannot be retroactively recovered at scale.*

- [x] **DATA-01**: `intelligence_features` has an `i7 JSONB NOT NULL DEFAULT '{}'` column populated with which setups fired per bar, their confidence scores, and direction — using the enrichment stream pattern (signal_generator publishes to `intelligence_i7:SYMBOL:TF`; feature_writer UPSERTs)
- [x] **DATA-02**: `intelligence_features` has an `i8 JSONB NOT NULL DEFAULT '{}'` column populated with AI narrative metadata per bar (model, confidence, summary) when narrative is available
- [x] **DATA-03**: `feature_writer_service` uses a single concurrent `xreadgroup` call for all streams (not sequential polling) — eliminates worst-case 9.2s lag and ensures feature rows align temporally with the bars they describe
- [x] **DATA-04**: `intelligence_features` has a `days_to_expiry INTEGER` column populated at write time from `get_active_contracts()` — roll proximity is a genuine regime signal for futures (liquidity shifts, basis widening near expiry)

### Discipline 3: Feedback Loop (FEED)

*Self-improving without manual intervention. Renaissance updated model parameters continuously from outcome data. Our signal aggregator uses static weights. Outcome data is now accumulating in `signal_ledger` — the feedback loop must be closed.*

- [x] **FEED-01**: A scheduled job (daily, extends weight-updater cadence) computes win rate, avg pnl_r, sample size, and Sharpe per setup from `signal_ledger` resolved signals (rolling 30-day window) and writes to a `setup_performance` table
- [x] **FEED-02**: Setup performance weights are only applied after a setup meets the promotion gate: minimum 30 resolved signals with non-null pnl_r (prevents overfitting on small samples — Renaissance "minimum bars before deployment" principle applied)
- [x] **FEED-03**: The signal aggregator reads setup performance weights at startup and applies them to setup ranking — outperforming setups get higher rank, underperforming setups get lower rank, with floor weight to prevent full suppression before sufficient evidence

### Discipline 4: Validated Alpha (ALPHA)

*Signal validation before scale. Renaissance discarded most signals unless statistically valid and proven. New indicators and patterns are hypotheses until validated. We build the validation discipline alongside the new alpha sources.*

- [x] **ALPHA-01**: A historical validation script exists that, given a new indicator or pattern, runs it against stored `intelligence_features` + `signal_ledger` history and produces: stationarity check (ADF test), correlation with pnl_r outcome, signal frequency, and false-positive rate — this is the promotion gate for all new alpha sources
- [x] **ALPHA-02**: Derivative Oscillator I2 plugin (Constance Brown) — double-smooth RSI (EMA5→EMA3) minus SMA(9) signal line; outputs `deriv_osc`, `deriv_osc_signal`, `deriv_osc_cross_bullish`, `deriv_osc_cross_bearish`; leads MACD by ~1-2 bars; validated via ALPHA-01 before live wiring
- [ ] **ALPHA-03**: Candlestick Tier 1 expansion (10 new patterns) added to `CandlestickPatternsPlugin` (I5) and `CandlestickPatternSetupPlugin` (I7): Three White Soldiers (0.72), Three Black Crows (0.72), Morning Star (0.65), Evening Star (0.65), Three Inside Up/Down (0.65), Harami Cross (0.58), Dark Cloud Cover (0.55), Piercing Line (0.55) — validated via ALPHA-01
- [x] **ALPHA-04**: MACD histogram acceleration added to `MACDEventsPlugin` — `macd_hist_accel` (float) and `macd_hist_contracting` (flag); early trend exhaustion warning 1-2 bars before sign flip — validated via ALPHA-01
- [x] **ALPHA-05**: AC Oscillator I1 plugin (Bill Williams) — `ao` (SMA(midpoint,5) − SMA(midpoint,34)) and `ac` (AO − SMA(AO,5)); new signal family, midpoint SMA-based, AC crosses zero before AO does — validated via ALPHA-01

### Discipline 5: LLM Intelligence Layer (LLM)

*Capture every LLM call. You can always discard data you didn't need. You can never recover data you didn't capture. Renaissance instruments everything — LLM model selection is a decision that should be data-driven, not intuitive.*

- [x] **LLM-01**: Migration `016_llm_intelligence_layer.sql` creates `llm_calls` TimescaleDB hypertable (partitioned by `called_at`) and `llm_model_scores` aggregate table — schema per design doc `docs/plans/2026-03-05-llm-intelligence-layer-design.md`
- [x] **LLM-02**: `ai_narrative_service` emits to `{env}:llm_calls:stream` after every LLM call (success, failure, and counterfactual) — full payload: model, provider, prompt, response, latency_ms, tokens_est, succeeded, regime, session, and all signal context fields
- [x] **LLM-03**: `signal_lifecycle_service` emits to `{env}:llm_outcomes:stream` when any signal exits — payload: signal_id, outcome, pnl_r, mae, mfe, bars_in_trade
- [x] **LLM-04**: New `llm_writer_service` (mirrors feature_writer_service pattern) — batch INSERTs from `llm_calls:stream`, back-fills outcome fields from `llm_outcomes:stream` by `signal_id`, recomputes `llm_model_scores` every 15 min from rows with non-null outcome, writes score cache to Redis `{env}:llm_scores:{call_type}:{regime}`
- [x] **LLM-05**: `ai_narrative_service` reads Redis score cache at startup and every 5 min — if a model is `is_significant=True` (p < 0.05, n_outcomes >= 30), it is moved to position 0 in the provider chain for that call_type + regime combination

---

## v2 Requirements (Future)

### Signal Intelligence
- HMA I1 plugin + HMA 2nd-derivative I2 (prerequisite chain)
- Ehlers Elegant Oscillator I1 (medium-high complexity, inverse Fisher + SuperSmoother)
- Regime-adaptive plugin parameters (I1/I4 parameter values adapt to hmm_regime)

### Data & Infrastructure
- Roll premium/discount feature (front/back month spread — contango/backwardation signal)
- Gap-fill service (detect + backfill market_data_ohlcv gaps from TWS downtime)
- Orderflow integration (tick-by-tick bid/ask; delta divergence, imbalance continuation, absorption setups)

### ML Layer
- ML scoring model (XGBoost/LightGBM on intelligence_features + signal_ledger outcomes) — needs ~90 days data
- Regime-specific ML (separate models per hmm_regime — ranging/trend-up/trend-down)
- Kelly-adjusted position sizing from signal_ledger win rate and payoff

### Commercialization
- Data vendor swap (Databento/Rithmic) — hard blocker for any public distribution
- Auth + subscription gating (Clerk + Stripe + FastAPI tier middleware)
- Webhook delivery for API tier subscribers

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| Order execution / trade management | Intelligence platform only — no execution engine |
| Portfolio management / position sizing | Out of scope for intelligence layer |
| Full ML scoring model | Needs ~90 days of labeled signal outcomes; v1.5+ |
| Commercialization / auth / Cloudflare Tunnel | Hard-blocked on IBKR data license; no external consumers yet |
| Orderflow integration | Requires reqTickByTickData infrastructure; v2+ |
| Cross-asset plugins (ES vs VIX correlation) | Data alignment complexity; v2+ |

---

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SIGINT-01 | Phase 12 | Complete |
| SIGINT-02 | Phase 12 | Complete |
| SIGINT-03 | Phase 12 | Complete |
| SIGINT-04 | Phase 12 | Complete |
| SIGINT-05 | Phase 12 | Complete |
| DATA-01 | Phase 13 | Complete |
| DATA-02 | Phase 13 | Complete |
| DATA-03 | Phase 13 | Complete |
| DATA-04 | Phase 13 | Complete |
| FEED-01 | Phase 14 | Complete |
| FEED-02 | Phase 14 | Complete |
| FEED-03 | Phase 14 | Complete |
| ALPHA-01 | Phase 15 | Complete |
| ALPHA-02 | Phase 15 | Complete |
| ALPHA-03 | Phase 15 | Pending |
| ALPHA-04 | Phase 15 | Complete |
| ALPHA-05 | Phase 15 | Complete |
| LLM-01 | Phase 16 | Complete |
| LLM-02 | Phase 16 | Complete |
| LLM-03 | Phase 16 | Complete |
| LLM-04 | Phase 17 | Complete |
| LLM-05 | Phase 17 | Complete |

**Coverage:**
- v1.4 requirements: 22 total
- Mapped to phases: 22
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-04*
*Last updated: 2026-03-06 — LLM-04/LLM-05 reassigned Phase 16→17 (production wiring breaks); Phase 17 added*
