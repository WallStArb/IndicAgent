# Roadmap: IndicAgent

## Milestones

- ✅ **v1.0 MVP** — Phases 0-9 (shipped 2026-02-28)
- ✅ **v1.1 Code Quality Sprint** — Phase 01 complete (ruff 206 → 0, 6/13 tasks done)
- ✅ **v1.2 Intelligence Palette Expansion** — Phases 2-6 + Phase 7 + Phase 8 complete (965 tests, I2/I5/I6 expanded)

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

## Progress

| Phase | Milestone | Plans | Status | Completed |
|-------|-----------|-------|--------|-----------|
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

## Backlog

Items decided but not yet scheduled. Pull into a milestone when ready.

| Item | Notes | Analysis |
|------|-------|---------|
| Dashboard Complete | Timeframe matrix wired to live per-TF signal data; signal history view; final audit across all symbol profiles. | — |
| Add i7/i8 columns to intelligence_features | Add `i7 JSONB` (setups + scores) and `i8 JSONB` (narrative + metadata) to intelligence_features. Enrichment stream pattern. | `analysis/2026-02-24-feature-store-completeness.md` |
| ML Scoring Model | XGBoost/LightGBM on intelligence_features + signal_ledger outcomes. Needs ~90 days signal history. | — |
| Auth and External Access | JWT + API key via single Depends(verify_auth); Cloudflare Tunnel; authenticated SSE. | — |
| Gap-fill service | Detect + backfill gaps in market_data_ohlcv from TWS downtime. | — |
| Days-to-expiry feature | `(expiry_date - bar_ts).days` → intelligence_features. Roll proximity signal. | — |
| Roll premium/discount feature | Front/back month spread at roll = contango/backwardation signal. | — |
| Gap Analysis Setup (I7) | Opening gap fade/continuation. Best for ES/NQ at 9:30 ET. | — |
| Candlestick Pattern Setup (I7) | Doji/hammer/engulfing + confluence. | — |
| Session Extremes Setup (I7) | Asian session high/low fade during London/NY. | — |
| Orderflow Integration | reqTickByTickData; buy/sell delta metrics; delta divergence plugins. | — |
| Portfolio Management | Correlation matrix; sector exposure limits; symbol rotation. | — |
| Robinhood-Style Scaling | Consumer Proxy pattern; Changelog Streams for state recovery. | `analysis/2026-02-12-robinhood-scaling-patterns.md` |
