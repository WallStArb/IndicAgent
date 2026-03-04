# Roadmap: IndicAgent

## Milestones

- ✅ **v1.0 MVP** — Phases 0-9 (shipped 2026-02-28)
- ✅ **v1.1 Code Quality Sprint** — Phase 01 complete (ruff 206 → 0, 6/13 tasks done)
- ✅ **v1.2 Intelligence Palette Expansion** — Phases 2-6 + Phase 7 + Phase 8 complete (965 tests, I2/I5/I6 expanded)
- ✅ **v1.3 Signal Intelligence Expansion** — Phases 08-11 + Signal Lifecycle redesign (shipped 2026-03-04)
- 🔲 **v1.4 Quant Foundation** — Phases 12-15 (in progress)

## Phases

<details>
<summary>✅ v1.0 MVP (Phases 0-9) — SHIPPED 2026-02-28</summary>

- [x] Phase 0: GARCH/Kalman Quality Gates (3/3 plans) — completed 2026-02-22
- [x] Phase 1: Typed Event Schema (3/3 plans) — completed 2026-02-23
- [x] Phase 2: Feature Store (3/3 plans) — completed 2026-02-23
- [x] Phase 3: Historical Data (3/3 plans) — completed 2026-02-24
- [x] Phase 4: Query API (3/3 plans) — completed 2026-02-24
- [x] Phase 5: Live Pipeline (3/3 plans) — completed 2026-02-25
- [x] Phase 6: Dashboard Connected (4/4 plans) — completed 2026-02-28
- [x] Phase 7: Composite Intelligence Score (4/4 plans) — completed 2026-02-28
- [x] Phase 8: Integration Fix & Cleanup (3/3 plans) — completed 2026-02-28
- [x] Phase 9: Milestone Verification (3/3 plans) — completed 2026-02-28

Full details: `.planning/milestones/v1.0-ROADMAP.md`

</details>

<details>
<summary>✅ v1.1 Code Quality Sprint — COMPLETE 2026-03-01</summary>

- [x] **Phase 01: Code Quality Sprint** — ruff 206 → 0, 803 tests passing, VX rolled to VXM6

</details>

<details>
<summary>✅ v1.2 Intelligence Palette Expansion — COMPLETE 2026-03-02</summary>

- [x] Phase 02: I2 Composite Events — 5 plugins (2026-02-27)
- [x] Phase 03: I5 Chart Patterns — +6 new plugins (2026-02-27)
- [x] Phase 04: I6 SMC Plugins — +5 new SMC plugins (2026-02-27)
- [x] Phase 05: I6 Confluence Refactor — recency weighting + I2 events (2026-03-02)
- [x] Phase 06: I1-I6 Correctness Audit — 35 tests (2026-03-02)
- [x] Phase 07: Final Verification & Documentation — 965 tests, v5.10.0 (2026-03-02)

</details>

<details>
<summary>✅ v1.3 Signal Intelligence Expansion — COMPLETE 2026-03-04</summary>

- [x] **Phase 08: MomentumAcceleration** — I2 plugin: rsi/macd/roc second-derivative + inflection_flag (complete)
- [x] **Phase 09: GapAnalysisSetup** — I7 opening gap fade/continuation for ES/NQ (GAP-01, GAP-02, GAP-03) (completed 2026-03-03)
- [x] **Phase 10: CandlestickPatternSetup** — I7 confluence-gated candlestick setup consuming I5 output (CNDL-01, CNDL-02, CNDL-03) (completed 2026-03-03)
- [x] **Phase 11: SessionExtremesSetup** — I7 Asian session high/low fade during London/NY (SESS-01, SESS-02, SESS-03) (completed 2026-03-04)

</details>

### v1.4 Quant Foundation

- [ ] **Phase 12: Signal Integrity** — Regime-aware gating on all 12 I7 plugins with shadow signal tracking
- [ ] **Phase 13: Data Completeness** — i7/i8 JSONB columns, concurrent stream polling, days-to-expiry
- [ ] **Phase 14: Feedback Loop** — Setup performance analytics + adaptive aggregator weights + promotion gate
- [ ] **Phase 15: Validated Alpha** — Validation script + 4 new alpha sources (DerivOsc, Candlestick Tier 1, MACD Accel, AC Osc)

## Phase Details

### Phase 01: Code Quality Sprint ✅

**Goal:** Fix all code quality issues identified by ruff, complexity analysis, and manual review

**Status:** Complete — 2026-03-01

**Outcome:** ruff 206 → 0 · 803 tests passing · service startup 9.2s → 1-2s

**Key changes:**
- All ruff E/F/W/PLR errors resolved across entire codebase
- tf_minutes NameError (real runtime bug) fixed in timeframe_builder.py
- All 6 services migrated to `ensure_consumer_group_with_reset`
- 3 pattern files O(N²) → O(N), warmup parallelized, 27 clamp() replacements

---

### Phase 02: I2 Composite Events ✅

**Goal:** Add 5 composite event plugins that detect crossovers, threshold crosses, and band touches on I1 indicators

**Status:** Complete — 2026-02-27 (planned and implemented pre-v1.0)

**Outcome:**
- MACDEvents: MACD crossover + negative support test signals
- RSIEvents: oversold/overbought crosses + extreme reversal detection
- StochasticEvents: K/D crosses + reversal signals + both oversold/overbought detection
- ADXEvents: trend confirmation + DI crossover signals
- VolumeEvents: volume-based event detection
- All plugins run on I1 output before I3 structure analysis

### Phase 03: I5 Chart Patterns — Add 6 New Plugins ✅

**Goal:** Expand I5 pattern detection with 6 additional chart pattern plugins

**Status:** Complete — 2026-02-27 (part of Intelligence Palette Expansion)

**Outcome:**
- CupHandle: Detect cup-with-handle continuation patterns
- FlagPennant: Detect bullish/bearish flag patterns
- TriangleWedge: Detect triangle and wedge continuation patterns
- HeadShoulders: Detect head-and-shoulders reversal patterns
- DoubleTopBottom: Detect double top/bottom reversal patterns
- CandlestickPatterns: Detect doji, hammer, engulfing, etc.
- I5 now has 14 total pattern detection plugins

### Phase 04: I6 SMC Plugins — Add 5 New SMC Plugins ✅

**Goal:** Expand I6 Smart Money Concepts with 5 additional SMC plugins

**Status:** Complete — 2026-02-27 (part of Intelligence Palette Expansion)

**Outcome:**
- ICTKillzones: Detect Asia, London, NY AM/PM killzones with UTC-aware overlap handling
- AMDCycle: Detect accumulation, manipulation, distribution phases with trend direction
- BreakerBlocks: Identify bullish/bearish breaker block levels with ATR distance
- MitigationBlocks: Track order block mitigation status and percentage
- PremiumDiscount: Calculate premium/discount percentage relative to equilibrium
- I6 SMC now has 13 total plugins (8 original + 5 new)

### Phase 05: I6 Confluence Refactor ✅

**Goal:** Enhance CrossTimeframeConfluence with recency weighting and I2 event integration

**Status:** Complete — 2026-03-02

**Outcome:**
- Added `_get_recency_weight`: stale intel weighted by 1/(bars_since+1)
- Recency weighting applied to trend, structure, and regime scoring
- Added `_score_i2_events`: 8 bullish (+0.1) + 6 bearish (-0.1) + MACD negative support (+0.15)
- Added W_I2=0.1 weight, renormalize composite by dividing by 1.1
- Added 3 SMC cross-TF sub-score outputs: i6_smc_bos_alignment, i6_fvg_tf_alignment (0.0), i6_ob_tf_alignment (0.0)
- CrossTimeframeConfluence now outputs 10 fields
- I6 confluence schema and tests updated (16 tests passing)

### Phase 06: I1-I6 Correctness Audit ✅

**Goal:** Verify mathematical correctness of all I1-I6 intelligence plugins

**Status:** Complete — 2026-03-02

**Outcome:**
- 35 correctness audit tests covering I1 (RSI, ATR, MACD, VWAP, Stochastic), I3 (SwingDetector, GARCH, Bollinger, OBV, SRClustering), I4 (TrendStructure, Kalman, TrendRegime, MomentumContext, BollingerSqueeze), I5 (TrendRegime, MomentumContext), I6 SMC (BOS/CHoCH, FVG, LiquiditySweeps, HMM, LiquidityPools, SupplyDemand)
- All tests verify incremental computation matches full recomputation
- Correctness issues fixed: VWAP std non-negative, Kalman uncertainty positive, etc.

### Phase 07: Final Verification & Documentation ✅

**Goal:** Run full test suite, lint, update CLAUDE.md, and complete milestone

**Status:** Complete — 2026-03-02

**Outcome:**
- Tests: 965 passing (from 803 baseline in v1.0)
- Ruff: 0 errors
- CLAUDE.md updated to v5.10.0
- Plugin counts aligned: 84 total (23 I1, 5 I2, 7 I3, 7 I4, 14 I5, 13 I6 SMC, 1 I6 confluence, 14 I7)
- MILESTONES.md and ROADMAP.md updated with v1.2 entry
- All Intelligence Palette Expansion work committed and pushed

---

### Phase 08: MomentumAcceleration ✅

**Goal:** Users can observe momentum acceleration signals — the rate of change of RSI, MACD, and ROC — and inflection flags in the live intelligence stream

**Status:** Complete — 2026-03-02

**Requirements:** ACCEL-01, ACCEL-02, ACCEL-03

**Success Criteria** (what must be TRUE):
  1. Every bar's IntelligenceEvent contains `rsi_accel`, `macd_accel`, `roc_accel` fields with valid float values (not null)
  2. `inflection_flag` is 1 on any bar where at least one acceleration delta changes sign vs the prior bar, and 0 otherwise
  3. The plugin appears in TIER_I2 and `registry.validate_tier()` passes at service startup with no crash
  4. All MomentumAcceleration tests pass (`tests/unit/intelligence/composites/`)

**Plans:** TBD

---

### Phase 09: GapAnalysisSetup

**Goal:** Traders can see opening gap setups — fade or continuation — generated for ES and NQ at market open (9:30 ET), with confidence scores and defined entry/stop/target levels

**Depends on:** Phase 08

**Requirements:** GAP-01, GAP-02, GAP-03

**Success Criteria** (what must be TRUE):
  1. On a bar where a gap is detected (prior close vs current open), the plugin produces a setup with `direction` (bullish/bearish) and `bias` (fade/continuation) populated
  2. `confidence`, `entry_type` (at_limit or at_pullback), `stop_price`, and `target_price` are all present and non-null on any fired signal
  3. Gap classification correctly distinguishes fade vs continuation based on gap size relative to ATR and volume context
  4. The plugin is registered in TIER_I7 and the full unit test suite passes (`tests/unit/intelligence/`)

**Plans:** 2/2 plans complete

Plans:
- [ ] 09-01-PLAN.md — Write failing test suite for GapAnalysisSetup (TDD RED phase)
- [ ] 09-02-PLAN.md — Implement GapAnalysisSetupPlugin and register in TIER_I7

---

### Phase 10: CandlestickPatternSetup

**Goal:** Traders can see candlestick-confluence setups that consume existing I5 pattern detections and gate on trend, structure, and volume — no re-detection of raw price patterns in I7

**Depends on:** Phase 09

**Requirements:** CNDL-01, CNDL-02, CNDL-03

**Success Criteria** (what must be TRUE):
  1. The plugin reads `candlestick_*` fields from the I5 section of IntelligenceEvent and does not access raw OHLCV directly
  2. A setup signal is only produced when the confluence score meets the configured threshold (trend direction, structure level proximity, and volume confirmation are evaluated)
  3. Signals include a `confluence_score` field that reflects how many confirming factors were present
  4. The plugin is registered in TIER_I7 and all unit tests pass (`tests/unit/intelligence/trading/`)

**Plans:** 2/2 plans complete

Plans:
- [x] 10-01-PLAN.md — Write failing test suite for CandlestickPatternSetup (TDD RED phase)
- [x] 10-02-PLAN.md — Implement CandlestickPatternSetupPlugin and register in TIER_I7 (16th plugin, 87 total)

---

### Phase 11: SessionExtremesSetup

**Goal:** Traders can see fade setups triggered when price approaches Asian session highs or lows during London or NY session windows, confirmed by at least one context factor

**Depends on:** Phase 10

**Requirements:** SESS-01, SESS-02, SESS-03

**Success Criteria** (what must be TRUE):
  1. The plugin reads `session_high` and `session_low` from I3 SessionLevels output rather than computing its own session extremes
  2. A setup signal fires only within a London or NY session window (not during the Asian session itself)
  3. A fade signal is only produced when at least one confirming factor — trend alignment, volume spike, or RSI extreme — is present alongside the session extreme test
  4. The plugin is registered in TIER_I7 and all unit tests pass (`tests/unit/intelligence/trading/`)

**Plans:** TBD

---

### Phase 12: Signal Integrity

**Goal:** All 12 I7 plugins only fire when the market regime supports the setup type — regime-ineligible signals are tracked as shadow signals rather than discarded

**Depends on:** Phase 11

**Requirements:** SIGINT-01, SIGINT-02, SIGINT-03, SIGINT-04, SIGINT-05

**Success Criteria** (what must be TRUE):
  1. A trend/momentum I7 plugin does not produce an eligible signal when `hmm_regime` is 0 (ranging), and a mean-reversion plugin does not produce an eligible signal when `hmm_regime` is 1 or 2 (trending)
  2. Any bar where `hmm_regime_prob < 0.60` results in all I7 signals carrying `regime_eligible=False` and `suppression_reason='regime_prob'`, regardless of setup logic outcome
  3. Any bar where `hmm_regime_duration < 5` results in all I7 signals carrying `regime_eligible=False` and `suppression_reason='regime_duration'`
  4. Regime authority is sourced from 5m or 15m IntelligenceEvent, not 1m — the gating logic reads from the correct timeframe key
  5. Regime-suppressed signals appear in `signal_ledger` with `status='regime_suppressed'` and their MAE/MFE/outcome are tracked by `signal_lifecycle_service`, making gate threshold tuning possible from data

**Plans:** 4 plans

Plans:
- [ ] 12-01-PLAN.md — Write Wave 0 failing tests for all 5 SIGINT requirements (TDD RED phase)
- [ ] 12-02-PLAN.md — Add regime_type class attribute to all 17 I7 plugin dataclasses
- [ ] 12-03-PLAN.md — Refactor aggregator (shadow signal gate) + signal_generator (regime cache + wiring)
- [ ] 12-04-PLAN.md — Extend signal_ledger query + implement shadow signal virtual-activation in lifecycle service

---

### Phase 13: Data Completeness

**Goal:** Every bar written to `intelligence_features` contains complete i7, i8, and temporal context — no permanently incomplete training samples

**Depends on:** Phase 12

**Requirements:** DATA-01, DATA-02, DATA-03, DATA-04

**Success Criteria** (what must be TRUE):
  1. A row in `intelligence_features` contains a non-null `i7` JSONB column populated with which setups fired on that bar, their confidence scores, and direction — verifiable by querying any recent bar
  2. A row in `intelligence_features` contains a non-null `i8` JSONB column for any bar where an AI narrative was generated, with model name, confidence, and summary fields present
  3. `feature_writer_service` reads all streams in a single concurrent `xreadgroup` call — lag between a bar completing and its feature row appearing drops to under 2 seconds, verifiable from service metrics
  4. Every `intelligence_features` row has a `days_to_expiry` integer populated (0 for non-futures, positive integer for futures contracts based on `get_active_contracts()` expiry)

**Plans:** TBD

---

### Phase 14: Feedback Loop

**Goal:** Setup performance data flows from resolved signal outcomes into the aggregator's ranking weights automatically — no manual intervention required

**Depends on:** Phase 13

**Requirements:** FEED-01, FEED-02, FEED-03

**Success Criteria** (what must be TRUE):
  1. A `setup_performance` table exists and is populated daily by a scheduled job with win rate, avg pnl_r, sample size, and Sharpe per setup type from the rolling 30-day window of resolved signals
  2. A setup with fewer than 30 resolved signals in `signal_ledger` has no performance weight applied — the aggregator uses baseline weights for that setup regardless of early win/loss data
  3. The signal aggregator reads setup performance weights at startup and outperforming setups rank higher than underperforming setups in aggregation — verifiable by comparing aggregator selection logs against `setup_performance` table values

**Plans:** TBD

---

### Phase 15: Validated Alpha

**Goal:** Four new alpha sources (Derivative Oscillator, 10 Candlestick Tier 1 patterns, MACD histogram acceleration, AC Oscillator) are live in production after each passes historical validation — no unvalidated signals fire

**Depends on:** Phase 14

**Requirements:** ALPHA-01, ALPHA-02, ALPHA-03, ALPHA-04, ALPHA-05

**Success Criteria** (what must be TRUE):
  1. A validation script exists that accepts an indicator or pattern name and produces: ADF stationarity result, correlation with pnl_r, signal frequency, and false-positive rate — runnable against `intelligence_features` + `signal_ledger` history from the command line
  2. The Derivative Oscillator I2 plugin outputs `deriv_osc`, `deriv_osc_signal`, `deriv_osc_cross_bullish`, and `deriv_osc_cross_bearish` on every bar and has passed the ALPHA-01 validation gate before being wired to the live pipeline
  3. The CandlestickPatternsPlugin (I5) and CandlestickPatternSetupPlugin (I7) include all 10 new Tier 1 patterns (Three White Soldiers, Three Black Crows, Morning Star, Evening Star, Three Inside Up/Down, Harami Cross, Dark Cloud Cover, Piercing Line), each having passed the ALPHA-01 gate
  4. `MACDEventsPlugin` emits `macd_hist_accel` (float) and `macd_hist_contracting` (bool) on every bar, validated via ALPHA-01 before live promotion
  5. The AC Oscillator I1 plugin emits `ao` and `ac` on every bar, registered in TIER_I1, and validated via ALPHA-01 before live wiring

**Plans:** TBD

---

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 0. GARCH/Kalman Quality Gates | v1.0 | 3/3 | Complete | 2026-02-22 |
| 1. Typed Event Schema | v1.0 | 3/3 | Complete | 2026-02-23 |
| 2. Feature Store | v1.0 | 3/3 | Complete | 2026-02-23 |
| 3. Historical Data | v1.0 | 3/3 | Complete | 2026-02-24 |
| 4. Query API | v1.0 | 3/3 | Complete | 2026-02-24 |
| 5. Live Pipeline | v1.0 | 3/3 | Complete | 2026-02-25 |
| 6. Dashboard Connected | v1.0 | 4/4 | Complete | 2026-02-28 |
| 7. Composite Intelligence Score (CIS) | v1.0 | 4/4 | Complete | 2026-02-28 |
| 8. Integration Fix & Cleanup | v1.0 | 3/3 | Complete | 2026-02-28 |
| 9. Milestone Verification | v1.0 | 3/3 | Complete | 2026-02-28 |
| 01. Code Quality Sprint | v1.1 | 1/1 | Complete | 2026-03-01 |
| 02. I2 Composite Events | v1.2 | — | Complete | 2026-02-27 |
| 03. I5 Chart Patterns | v1.2 | — | Complete | 2026-02-27 |
| 04. I6 SMC Plugins | v1.2 | — | Complete | 2026-02-27 |
| 05. I6 Confluence Refactor | v1.2 | — | Complete | 2026-03-02 |
| 06. I1-I6 Correctness Audit | v1.2 | — | Complete | 2026-03-02 |
| 07. Final Verification | v1.2 | — | Complete | 2026-03-02 |
| 08. MomentumAcceleration | v1.3 | — | Complete | 2026-03-02 |
| 09. GapAnalysisSetup | v1.3 | 2/2 | Complete | 2026-03-03 |
| 10. CandlestickPatternSetup | v1.3 | 2/2 | Complete | 2026-03-03 |
| 11. SessionExtremesSetup | v1.3 | — | Complete | 2026-03-04 |
| 12. Signal Integrity | v1.4 | 0/4 | Not started | — |
| 13. Data Completeness | v1.4 | 0/0 | Not started | — |
| 14. Feedback Loop | v1.4 | 0/0 | Not started | — |
| 15. Validated Alpha | v1.4 | 0/0 | Not started | — |

## Backlog

Items decided but not yet scheduled. Pull into a milestone when ready.

| Item | Notes | Analysis |
|------|-------|---------|
| Dashboard Complete | Timeframe matrix wired to live per-TF signal data; signal history view; final audit across all symbol profiles. | — |
| ML Scoring Model | XGBoost/LightGBM on intelligence_features + signal_ledger outcomes. Needs ~90 days signal history. | — |
| Auth and External Access | JWT + API key via single Depends(verify_auth); Cloudflare Tunnel; authenticated SSE. | — |
| Gap-fill service | Detect + backfill gaps in market_data_ohlcv from TWS downtime. | — |
| Roll premium/discount feature | Front/back month spread at roll = contango/backwardation signal. | — |
| Orderflow Integration | reqTickByTickData; buy/sell delta metrics; delta divergence plugins. | — |
| Portfolio Management | Correlation matrix; sector exposure limits; symbol rotation. | — |
| Robinhood-Style Scaling | Consumer Proxy pattern; Changelog Streams for state recovery. | `analysis/2026-02-12-robinhood-scaling-patterns.md` |
| HMA I1 indicator | Hull Moving Average (WMA of 2×WMA(n/2) − WMA(n), sqrt(n)). ~20 lines. Once added, HMA 2nd derivative is trivial via MomentumAcceleration pattern. | `ideas/2nd-derivative-indicator-research.md` |
| Ehlers Elegant Oscillator I1 | 2-bar price diff → RMS normalize → inverse Fisher transform → SuperSmoother IIR. Near-zero-lag cycle oscillator. Medium-high complexity. | `ideas/2nd-derivative-indicator-research.md` |
| Regime-adaptive plugin parameters | I1/I4 parameter values adapt to hmm_regime (e.g. shorter RSI period in trending regime). | — |
