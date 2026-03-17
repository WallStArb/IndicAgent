# Requirements: IndicAgent v1.9

**Defined:** 2026-03-16
**Core Value:** Every intelligence output flows through one canonical typed bus that both internal and external consumers can trust.
**Design anchor:** `docs/ideas/i7-quant-audit-2026-03-16.md`

---

## v1.9 Requirements — I7 Alpha Engine

*"Earn the right through proof. Let the system run. Instrument everything." — Renaissance principles*

46 requirements · 10 new I7 plugins (17 → 27 total) · 5 new I4/I5 plugins · 1 new service

### LEARN — CIS Learning Loop

- [x] **LEARN-01**: CIS scorer loads learned weights from `cis_weights` DB at runtime on startup; refreshes every 30 min; falls back to bootstrap weights when `sample_size < 100` or DB unavailable
- [x] **LEARN-02**: Weight updater trains on binary win/loss labels (`target_1`, `target_1_2`, `target_full` = win; all other outcomes = loss); replaces `signal_quality` proxy target
- [x] **LEARN-03**: `cis_weights` table extended with `asset_cluster` + `timeframe` columns; five clusters: `eq_index` (ES/NQ/RTY/YM), `commodity` (CL/GC/SI/NG/HG/PL/PA), `rates` (ZN/ZB/ZF/ZT), `crypto` (BTC/ETH/SOL), `ag` (ZC/ZS/ZW)
- [x] **LEARN-04**: Weight learner trains separate logistic regression models per `(asset_cluster, timeframe)` when N ≥ 100 resolved signals; falls back to `global` model when cluster is sparse

### FEAT — Signal Feature Snapshots

- [x] **FEAT-01**: `signal_features` TimescaleDB hypertable captures all non-null raw feature values from `IntelligenceEvent` at signal fire time (mid-bar snapshot, not bar-close state from `intelligence_features`)
- [x] **FEAT-02**: `signal_features` write committed atomically with `signal_ledger` row in `signal_generator_service`; no orphaned feature rows

### SHAD — Shadow Infrastructure

- [x] **SHAD-01**: `is_shadow BOOLEAN NOT NULL DEFAULT FALSE` column added to `signal_ledger`; shadow signals co-emitted on same bar as production signals for valid A/B matched-pair comparison
- [x] **SHAD-02**: Statistical promotion gate runnable as CLI script: two-sample proportion z-test, requires p < 0.05 AND N ≥ 200 per variant before any experimental path promoted to production

### SIG — Signal Quality & Stop Architecture

- [x] **SIG-01**: `trade_framer.py` implements structure-first stop placement — tries structural invalidation point first (OB low, demand zone boundary, swing low, FVG low); uses structure level when it exists within 1.5×ATR of raw ATR stop; falls back to ATR when no structure is nearby; `stop_basis` field (`"structure_snap"` | `"garch_adaptive"` | `"atr_static"`) logged in `signal_ledger` for every signal
- [x] **SIG-02**: All 17 existing I7 plugins inherit GARCH-adaptive ATR scaling via centralized `trade_framer.py` — `garch_vol_regime` 0 (low) → 0.8× base multiplier, 1 (normal) → 1.0×, 2 (high) → 1.35×; no per-plugin changes required
- [ ] **SIG-03**: Chandelier Exit trailing stop implemented in `lifecycle_tracker.py` for active signals — `highest_high_since_entry - 3×ATR` (long) / `lowest_low_since_entry + 3×ATR` (short); stop tightens but never widens; logged as `trailing_stop_price` per lifecycle update
- [ ] **SIG-04**: Signal staleness score computed per bar in `signal_lifecycle_service` for all pending signals; regime-flip or vol-drift beyond threshold triggers `condition_expired` outcome; `hmm_regime_at_fire` and `garch_vol_regime_at_fire` stored in `signal_ledger` at generation time
- [x] **SIG-05**: Time stop verified correct per TF — signals not activated within TTL bars automatically expire; TTL values reviewed and documented as named constants per TF

### DIV — Extended Divergence Stack

- [ ] **DIV-01**: New I5 plugin `src/intelligence/patterns/macd_divergence.py` — detects MACD histogram divergence from price direction; outputs `macd_div_bullish`, `macd_div_bearish`; consumes existing `macd_histogram_12_26_9` from I1
- [ ] **DIV-02**: New I5 plugin `src/intelligence/patterns/obv_divergence.py` — detects OBV direction diverging from price direction over N bars; outputs `obv_div_bullish`, `obv_div_bearish`; consumes existing `obv` from I1
- [ ] **DIV-03**: New I5 plugin `src/intelligence/patterns/cmf_divergence.py` — detects Chaikin Money Flow divergence from price direction; outputs `cmf_div_bullish`, `cmf_div_bearish`; consumes existing `cmf_20` from I1
- [ ] **DIV-04**: `divergence_stack.py` upgraded from hard AND-gate to 5-input weighted convergence score (RSI 0.30, MACD 0.25, vol 0.20, OBV 0.15, CMF 0.10); fires when score > 0.40 AND n_agreeing ≥ 3; preserves quality bar while extending recall ~40%

### PLUG — New I7 Signal Plugins

- [x] **PLUG-01**: New I7 plugin `trad_FailedBreakout` — price breaks key level (BOS/CHoCH confirmed) then reverses within N bars; one of the highest-conviction reversal setups; complementary to `trad_MomentumBreakout`; SoC: standalone plugin consuming existing BOS/CHoCH features
- [x] **PLUG-02**: New I7 plugin `trad_OpeningRangeBreakout` — 15-min and 30-min ORB with overnight gap directional bias and volume expansion gate; fires NY session only (09:30–11:30 ET); extension of session infrastructure from `session_extremes_setup`
- [x] **PLUG-03**: New I7 plugin `trad_PrevDayLevelTest` — PDH/PDL/PDC (previous day high/low/close) fade or breakout-continuation setups; institutional magnet levels; PDH/PDL computed from `bar_history` rolling window in `signal_generator_service`; regime-gated
- [x] **PLUG-04**: New I7 plugin `trad_SecondLegContinuation` — detects leg 1 + pullback to Fibonacci retracement (38.2%–61.8%) → leg 2 entry signal; measured move targets at 100%, 127.2%, 161.8% of leg 1 amplitude; requires swing detection from I3
- [x] **PLUG-05**: New I7 plugin `trad_VCP` (Volatility Contraction Pattern) — 3+ successive range contractions with decreasing volume → breakout entry on first expansion bar; directional bias from HMM regime; momentum-regime gated

### VWAP — Anchored VWAP

- [ ] **VWAP-01**: New I4 plugin `src/intelligence/context/anchored_vwap.py` — VWAP anchored to session open and last significant swing point (from I3 swing detection); outputs `avwap_session`, `avwap_swing`, `avwap_deviation_pct`, `avwap_upper_band`, `avwap_lower_band`
- [ ] **VWAP-02**: New I7 plugin `trad_AnchoredVWAPReversion` — price extended > 1.5 std from anchored VWAP with mean-reversion regime context (HMM ranging + Hurst < 0.55); fade setup targeting VWAP as T1 and opposite band as T2

### VOL — Volume Profile

- [ ] **VOL-01**: New I4 plugin `src/intelligence/context/volume_profile.py` — intraday session volume profile computing POC (Point of Control), HVN (High Volume Nodes top 3), LVN (Low Volume Nodes), VAH (Value Area High), VAL (Value Area Low); outputs `poc_price`, `vah`, `val`, `nearest_hvn_above`, `nearest_hvn_below`, `nearest_lvn_above`, `nearest_lvn_below`
- [ ] **VOL-02**: New I7 plugin `trad_VolumeProfileReaction` — three variants: POC rejection (price tests POC and fails with momentum reversal), HVN rejection (stall + reversal at institutional accumulation), LVN breakout (fast expansion through thin area targeting next HVN); variant selected by proximity + momentum context

### CAL — Confidence Calibration

- [ ] **CAL-01**: `confidence_calibration` DB table stores isotonic regression calibration curves per `(plugin_name, timeframe)`; columns: `breakpoints DOUBLE PRECISION[]`, `values DOUBLE PRECISION[]`, `ece DOUBLE PRECISION`, `sample_size INT`, `updated_at TIMESTAMPTZ`
- [ ] **CAL-02**: Calibration batch job `src/intelligence/ml/confidence_calibrator.py` trains isotonic regression when N ≥ 100 completed signals per `(plugin_name, timeframe)`; runs alongside weight updater systemd timer; `calibrated_confidence` stored in `signal_ledger`
- [ ] **CAL-03**: Aggregator `_build_all_ranked()` applies calibrated confidence as final step after all quality multipliers (Hurst, KS drift, GARCH); `calibrated_confidence` used for winner ranking when available; raw confidence fallback when calibration curve absent

### TOD — Time-of-Day Multiplier

- [ ] **TOD-01**: Time-of-day win rate computed per `(setup_plugin, timeframe, hour_et)` from `signal_ledger`; seeded with known session priors (NY open +10% trend, lunch chop −10% all, London close +8% SMC, MOC +10% session extremes) until N ≥ 20
- [ ] **TOD-02**: TOD multiplier ∈ [0.7, 1.3] applied to signal confidence in `signal_generator_service` before aggregation; cached in-memory dict refreshed every 4h

### KAL — CIS Kalman Filter

- [ ] **KAL-01**: Per-`(symbol, timeframe)` 1D Kalman filter smooths CIS score in `signal_generator_service`; implementation reuses `KalmanTrendPlugin` local-level state machine (Q=0.01, R=0.05); filter state persists across bars
- [ ] **KAL-02**: Both `raw_cis_score` and `filtered_cis_score` logged per signal; updated fire condition: `filtered_cis > 0.35 AND raw_cis > 0.28 AND buckets_agreeing ≥ 3`

### OFI — Order Flow Imbalance

- [ ] **OFI-01**: Tick data availability audited across all 60 instruments on IBKR paper account; bar-level OFI proxy (`(close - low) / (high - low + ε) × volume`) implemented as fallback if true tick-by-tick data unavailable; implementation variant documented
- [ ] **OFI-02**: `ofi_ewma_20` and `ofi_divergence` computed as I1 features in `indicator_service`; EWMA spans: 5-bar and 20-bar; divergence = OFI direction vs price direction over same window
- [ ] **OFI-03**: New I7 plugin `trad_OrderFlowImbalance` — three variants: continuation (sustained buy/sell OFI), divergence (price vs OFI disagree → exhaustion), spike (single-bar OFI > 2σ → potential breakout); registered in `TIER_I7`

### CVD — Cumulative Delta Divergence

- [ ] **CVD-01**: Cumulative Volume Delta computed as I1 feature in `indicator_service` — running `Σ(buy_vol − sell_vol)` using tick rule; outputs `cvd`, `cvd_slope_5bar`, `cvd_divergence` (CVD direction vs price direction)
- [ ] **CVD-02**: New I7 plugin `trad_CVDDivergence` — CVD direction diverging from price direction for N bars signals sustained institutional pressure; highest-conviction when CVD and OFI both diverge simultaneously; registered in `TIER_I7`

### XA — Cross-Asset Intelligence

- [ ] **XA-01**: New `services/cross_asset_service.py` subscribes to `intelligence:SYMBOL:TF` Redpanda topics for equity index group (ES, NQ, RTY, YM); maintains per-symbol rolling bar window; computes spread features; publishes to `cross_asset:EQ_INDEX:TF` topic; metrics on dedicated port
- [ ] **XA-02**: Equity index spread features: `es_nq_spread_z` (z-scored 5-bar return spread), `es_rty_spread_z`, `eq_corr_break` (abs diff between 5-bar and 20-bar rolling correlation)
- [ ] **XA-03**: New I7 plugin `trad_CrossAssetDivergence` — fires when `|spread_z| > 2.0`; regime-biased direction (reversion in ranging, continuation in trending); confidence scales with spread magnitude and regime clarity; registered in `TIER_I7`

---

## v2.0+ Requirements (Deferred)

### Execution Intelligence
- Portfolio-level signal correlation management (prevent simultaneous same-direction signals on correlated instruments)
- Kelly criterion position sizing from calibrated P(win)

### ML Models (need 90+ days labeled outcomes)
- Gradient Boosting meta-model on `signal_features` table
- Neural sequence model on bar-level feature vectors
- RL-based adaptive regime weight tuning

### Data Infrastructure
- Full tick-by-tick collection for all 60 instruments (prerequisite for true OFI/CVD)
- Economic calendar integration (FOMC, NFP, CPI — suppress signals pre-release)
- Options market data (VIX term structure, IV skew for equity index regime context)

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| Order execution / trade management | Intelligence platform only |
| Portfolio management / position sizing | Out of scope for intelligence layer |
| Auth layer | No external consumers yet |
| Multi-timeframe 4h/1d I7 plugins | Day-trading scope; `InputSpec.timeframe='.*'` dead-code intent explicit |
| Neural/RL models on raw tick data | Requires 90+ days labeled outcomes + GPU training infrastructure |

---

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| LEARN-01 | Phase 31 | Complete |
| LEARN-02 | Phase 31 | Complete |
| LEARN-03 | Phase 31 | Complete |
| LEARN-04 | Phase 31 | Complete |
| FEAT-01 | Phase 31 | Complete |
| FEAT-02 | Phase 31 | Complete |
| SHAD-01 | Phase 31 | Complete |
| SHAD-02 | Phase 31 | Complete |
| SIG-01 | Phase 32 | Complete |
| SIG-02 | Phase 32 | Complete |
| SIG-03 | Phase 32 | Pending |
| SIG-04 | Phase 32 | Pending |
| SIG-05 | Phase 32 | Complete |
| DIV-01 | Phase 32 | Pending |
| DIV-02 | Phase 32 | Pending |
| DIV-03 | Phase 32 | Pending |
| DIV-04 | Phase 32 | Pending |
| PLUG-01 | Phase 33 | Complete |
| PLUG-02 | Phase 33 | Complete |
| PLUG-03 | Phase 33 | Complete |
| PLUG-04 | Phase 33 | Complete |
| PLUG-05 | Phase 33 | Complete |
| VWAP-01 | Phase 34 | Pending |
| VWAP-02 | Phase 34 | Pending |
| VOL-01 | Phase 34 | Pending |
| VOL-02 | Phase 34 | Pending |
| CAL-01 | Phase 35 | Pending |
| CAL-02 | Phase 35 | Pending |
| CAL-03 | Phase 35 | Pending |
| TOD-01 | Phase 35 | Pending |
| TOD-02 | Phase 35 | Pending |
| KAL-01 | Phase 35 | Pending |
| KAL-02 | Phase 35 | Pending |
| OFI-01 | Phase 36 | Pending |
| OFI-02 | Phase 36 | Pending |
| OFI-03 | Phase 36 | Pending |
| CVD-01 | Phase 36 | Pending |
| CVD-02 | Phase 36 | Pending |
| XA-01 | Phase 37 | Pending |
| XA-02 | Phase 37 | Pending |
| XA-03 | Phase 37 | Pending |

**Coverage:**
- v1.9 requirements: 41 total
- Mapped to phases: 41
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-16*
*Last updated: 2026-03-16 after roadmap creation (Phases 31-37 mapped)*
