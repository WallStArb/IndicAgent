---
phase: 137-feature-factory
plan: 3
type: tdd
wave: 2
depends_on: [1, 2]
files_modified:
  - src/intelligence/feature_factory.py
  - src/intelligence/feature_cache.py
  - tests/unit/test_feature_factory.py
autonomous: true
requirements: [SC-2, SC-9]

threat_model:
  assets:
    - "FeatureFactory.compute (pure function producing the entire IC research corpus)"
    - "Cross-asset proxy computation (vix_z/flight_quality/yield_slope_z) - no native VIX ETF in universe"
  threats:
    - id: T1
      description: "FeatureFactory calls ConfigService.get(), reads the DB, or touches Kafka at compute time - DAG Invariant 5 / D-08 violation, IO in the hot path"
      severity: high
      mitigation: "FeatureFactoryConfig frozen dataclass passed at construction; compute() takes only (bars, symbol, tf, cache, config); acceptance criterion asserts compute() works with no ConfigService and no DB connection available"
    - id: T2
      description: "HMM uses backward smoother (lookahead bias) instead of forward Viterbi - contaminates regime labels (D-07)"
      severity: high
      mitigation: "Extract only _forward_step() from hmm_regime.py; never reference _smooth(); acceptance criterion asserts no '_smooth' or 'smoothed' token in feature_factory.py regime path"
    - id: T3
      description: "OFI/CVD use the tick path (no tick data in historical bars) producing all-zero or NaN flow features during backfill"
      severity: medium
      mitigation: "compute() always uses the OHLCV proxy path for ofi_z/cvd_slope_z; acceptance criterion asserts no reference to tick_buffer in feature_factory.py"
    - id: T4
      description: "Inline numeric constants (periods, z-windows, thresholds) hardcoded in feature_factory.py - APR architecture violation (SC-9)"
      severity: medium
      mitigation: "All tunable numerics come from FeatureFactoryConfig fields; acceptance criterion greps for bare magic numbers in compute paths"
  block_on: [T1, T2]

must_haves:
  truths:
    - "FeatureFactory.compute(bars, symbol, tf, cache, config) returns a FeatureVector with all 35 fields populated as floats"
    - "compute() performs zero IO - no ConfigService.get, no DB read, no Kafka"
    - "Regime features (hmm_regime_prob, hmm_entropy, hurst, shannon, garch_ratio) use forward-only computation served from FeatureCache with the cache_refresh_bars cadence"
    - "ofi_z and cvd_slope_z are computed via OHLCV proxy, never the tick path"
    - "vix_z, flight_quality, yield_slope_z are read from FeatureCache (populated from cross-asset ETF history), not computed inside compute() from the subject symbol's bars"
  artifacts:
    - path: "src/intelligence/feature_factory.py"
      provides: "FeatureFactory, FeatureFactoryConfig, compute() pure function, 35 primitive cores"
      min_lines: 300
      contains: "class FeatureFactory"
    - path: "src/intelligence/feature_cache.py"
      provides: "FeatureCache mutable state container + cross-asset proxy populators"
      contains: "class FeatureCache"
    - path: "tests/unit/test_feature_factory.py"
      provides: "RED->GREEN tests for all 35 primitives + purity + forward-only HMM"
      contains: "def test_"
  key_links:
    - from: "src/intelligence/feature_factory.py FeatureFactory.compute"
      to: "src/intelligence/feature_cache.py FeatureCache"
      via: "cache argument supplying regime/cross-asset/CTF/session values"
      pattern: "cache\\.(hmm_regime_prob|vix_z|ctf_momentum)"
    - from: "src/intelligence/feature_factory.py FeatureFactoryConfig"
      to: "config_state feature.* keys"
      via: "fields loaded at pipeline init, passed frozen into FeatureFactory"
      pattern: "FeatureFactoryConfig"
---

<objective>
Build the pure-function feature library: `FeatureFactory.compute(bars, symbol, tf, cache, config) -> FeatureVector` producing all 35 primitives, plus the mutable `FeatureCache` state container that holds slow-changing regime, cross-asset, CTF, and session values. This is the core of Phase 137. All 35 primitive algorithms already exist in the codebase - this plan extracts their pure computational cores and assembles them into one stateless function with APR-backed parameters supplied via a frozen `FeatureFactoryConfig`.

TDD is mandatory here: each primitive has a defined input->output contract (e.g. `bar_close_pos = (close - low) / (high - low)`), so tests are written RED before extraction.

Purpose: This function replaces the 138-plugin registry dispatch at cutover (P6). Its outputs are the IC research corpus for Phase 138. Correctness and causal purity (forward-only HMM, OHLCV proxy flow, no IO) are non-negotiable.
Output: `feature_factory.py` (FeatureFactory + FeatureFactoryConfig), `feature_cache.py` (FeatureCache + cross-asset proxy populators), green unit tests.

CRITICAL CROSS-ASSET FINDING (verified at planning time): VXX and VIXY are NOT in the 58 active ETFs. The available proxy instruments are GLD, SLV, TLT, SHY, IEF, LQD, HYG, SPY, and sector ETFs. Therefore:
- `vix_z`: there is no native VIX ETF. Use a realized-volatility proxy - z-score of SPY trailing realized volatility from cross-asset cache (SPY bars). Document this as a proxy in code; Phase 138 IC will judge it.
- `flight_quality`: TLT/SPY relative return divergence (both in universe).
- `yield_slope_z`: TLT/SHY return-ratio z-score as a 2Y-10Y curve proxy (both in universe).
All three are computed in `feature_cache.py` from cross-asset ETF bars and read by compute() from FeatureCache - never computed inside compute() from the subject symbol.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/137-feature-factory/137-CONTEXT.md
@.planning/phases/137-feature-factory/137-RESEARCH.md
@.planning/phases/137-feature-factory/A-PATTERNS.md
@CLAUDE.md
@src/intelligence/context/hurst_exponent.py
@src/intelligence/context/shannon_entropy.py
@src/intelligence/context/garch_volatility.py
@src/intelligence/features/smc_context/hmm_regime.py
</context>

<tasks>

<task type="tdd">
  <name>Task 1: FeatureFactoryConfig + FeatureCache + RED tests for bar-level and calendar primitives</name>
  <files>src/intelligence/feature_factory.py, src/intelligence/feature_cache.py, tests/unit/test_feature_factory.py</files>
  <read_first>
    - src/intelligence/schemas.py (FeatureVector / FeatureVectorRecord from P2 - the output contract)
    - .planning/phases/137-feature-factory/A-PATTERNS.md (FeatureFactoryConfig and FeatureCache dataclass definitions, rolling z-score pattern, ATR extraction note)
    - .planning/phases/137-feature-factory/137-RESEARCH.md (Pattern 1/2/3; z-score Code Example; Pitfall 3 OFI/CVD proxy formulas)
    - src/intelligence/features/i1_indicators/atr.py (ATR Wilder smoothing core)
    - src/intelligence/features/i1_indicators/cmf.py (CMF core)
    - src/intelligence/context/momentum_context.py (log-return + z-score core for momentum_z_5/20)
    - src/intelligence/context/session_context.py (NY session / overlap timestamp logic for in_ny_session, in_overlap)
  </read_first>
  <action>
    RED first: write failing tests in tests/unit/test_feature_factory.py for the deterministic bar-level and calendar primitives where input->output is exact:
    - bar_close_pos = (close - low) / (high - low) with epsilon guard (==0.5 when high==low)
    - range_position = (close - min(low_N)) / (max(high_N) - min(low_N)) over momentum_window_long bars
    - rel_volume = volume / mean(volume over volume_zscore_window)
    - gap_z = (open - prev_close) / atr, z-scored over momentum_zscore_window
    - informed_flow = (close - open) / atr
    - ofi_z = OHLCV proxy `(close - low) / (high - low + eps) * volume`, z-scored over ofi_zscore_window (NEVER tick path)
    - cvd_slope_z = OHLCV proxy `(2*close - high - low) / (high - low + eps) * volume`, cumulative per session, slope over cvd_slope_bars, z-scored
    - volume_z = rolling z-score of volume over volume_zscore_window
    - vol_ratio = realized_vol(vol_short_bars) / realized_vol(vol_long_bars)
    - momentum_z_5 / momentum_z_20 = log-return velocity over window_short/window_long, z-scored over momentum_zscore_window
    - atr_z = ATR (Wilder) z-scored over momentum_zscore_window
    - cmf = Chaikin Money Flow over cmf_period
    - in_ny_session / in_overlap = 1.0/0.0 from bar_ts (NY 09:30-16:00 ET; overlap = London-NY 08:00-11:00 ET window per session_context.py)
    - dow_sin = sin(2*pi*weekday/5), dow_cos = cos(2*pi*weekday/5), month_position = day_of_month / days_in_month

    GREEN: implement FeatureFactoryConfig frozen dataclass (16 int fields mapping to feature.* keys per A-PATTERNS.md), FeatureCache mutable dataclass (per A-PATTERNS.md, with cross-asset/regime/CTF/session defaults), and the bar-level + calendar primitive functions in feature_factory.py. All numeric parameters come from FeatureFactoryConfig - zero inline magic numbers (SC-9). Use a module-level `_rolling_zscore(value, history_array, window)` helper. compute() is not yet assembled; expose individual primitive functions for unit testing this task.

    Add a module-level `set_config_service()` + `get_sync()` wrapper ONLY if needed for the pipeline-init injection pattern, but FeatureFactory.compute itself must take config as an argument (D-08). Prefer: FeatureFactory holds a FeatureFactoryConfig built once; compute() reads from self._config, never ConfigService.
  </action>
  <verify>
    .venv/bin/pytest tests/unit/test_feature_factory.py -q -k "bar_level or calendar or close_pos or rel_volume or momentum or proxy"
  </verify>
  <acceptance_criteria>
    - tests written before implementation fail RED, then pass GREEN (commit history shows test commit before impl commit)
    - `bar_close_pos` test: input high=10,low=8,close=9 -> 0.5; high==low -> 0.5 (no ZeroDivisionError)
    - `ofi_z`/`cvd_slope_z` tests assert the OHLCV proxy formula is used; `grep -n "tick_buffer" src/intelligence/feature_factory.py` returns 0 matches
    - `.venv/bin/pytest tests/unit/test_feature_factory.py -q` passes for the bar-level + calendar subset
    - `grep -nE "window=[0-9]|period=[0-9]|/ 252|/ 20[^0-9]" src/intelligence/feature_factory.py` returns 0 matches in primitive bodies (params from config)
  </acceptance_criteria>
</task>

<task type="tdd">
  <name>Task 2: Regime, session, structural, and cross-timeframe primitives (forward-only) served from FeatureCache</name>
  <files>src/intelligence/feature_factory.py, src/intelligence/feature_cache.py, tests/unit/test_feature_factory.py</files>
  <read_first>
    - src/intelligence/context/hurst_exponent.py (_hurst_rs R/S core - extract directly)
    - src/intelligence/context/shannon_entropy.py (_shannon_entropy core)
    - src/intelligence/context/garch_volatility.py (_compute_full_core; garch_ratio = garch_sigma / realized_vol)
    - src/intelligence/features/smc_context/hmm_regime.py (ONLY _forward_step - confirm no _smooth call; produces hmm_regime_prob + hmm_entropy)
    - src/intelligence/features/i1_indicators/adx.py (ADX core)
    - src/intelligence/features/i1_indicators/hma.py (HMA core for hma_slope_z)
    - src/intelligence/context/volume_profile.py (session POC/VAH/VAL for poc_dist_atr, va_position)
    - src/intelligence/context/sr_consensus.py (zone distance for sr_support_dist, sr_resist_dist)
    - src/intelligence/context/anchored_vwap.py (session VWAP + std for vwap_dev_sigma)
    - .planning/phases/137-feature-factory/137-RESEARCH.md (Pitfall 2 regime cache cadence; Open Question 3 - 1d TF session-feature defaults)
  </read_first>
  <action>
    RED then GREEN for the regime-level (hmm_regime_prob, hmm_entropy, hurst, shannon, garch_ratio, hma_slope_z, adx), session-level (poc_dist_atr, va_position, sr_support_dist, sr_resist_dist), structural (vwap_dev_sigma), and cross-timeframe (ctf_momentum, ctf_vwap_align, ctf_regime_align) primitives.

    Regime features: extract forward-only cores from hurst_exponent.py / shannon_entropy.py / garch_volatility.py / hmm_regime.py (_forward_step ONLY - never _smooth). These are EXPENSIVE: implement a `FeatureCache.refresh_regime(bars, config)` method that recomputes them and resets `bars_since_regime_refresh`; compute() reads regime values from cache and the cache is refreshed by the caller every `regime_cache_refresh_bars` bars (Pitfall 2). garch_ratio = garch_sigma / realized_vol. hma_slope_z = z-scored slope of HMA over hma_period.

    Session features: poc_dist_atr / va_position from session volume profile; sr_support_dist / sr_resist_dist from SR zones; vwap_dev_sigma = (close - session_vwap) / session_vwap_std. For tf == '1d' set poc_dist_atr=0.0, va_position=0.5, sr_support_dist=0.0, sr_resist_dist=0.0 (Open Question 3 - intraday-only concepts). Session values live in FeatureCache and reset at session open.

    Cross-timeframe: ctf_momentum / ctf_vwap_align / ctf_regime_align read from FeatureCache HTF-cached state (populated when an HTF bar arrives). compute() reads them from cache; it does not compute HTF state itself.

    All forward-only. No backward smoother. No inline magic numbers - params from FeatureFactoryConfig.
  </action>
  <verify>
    .venv/bin/pytest tests/unit/test_feature_factory.py -q -k "regime or hurst or shannon or garch or hmm or adx or session or vwap or ctf or sr"
  </verify>
  <acceptance_criteria>
    - `grep -nE "_smooth|smoothed|backward" src/intelligence/feature_factory.py` returns 0 matches in the regime computation path
    - hurst test: monotonic increasing series returns hurst > 0.5; random-walk-ish series returns ~0.5
    - hmm_regime_prob/hmm_entropy produced from forward step only; test asserts probabilities sum to ~1.0 and entropy >= 0
    - `tf='1d'` test: poc_dist_atr==0.0, va_position==0.5, sr_support_dist==0.0, sr_resist_dist==0.0
    - ctf_* test: compute() reads ctf values from the passed FeatureCache (asserted by passing a cache with known ctf_momentum and checking it appears in output)
    - `.venv/bin/pytest tests/unit/test_feature_factory.py -q -k "regime or session or ctf"` passes
  </acceptance_criteria>
</task>

<task type="tdd">
  <name>Task 3: Assemble compute(), cross-asset proxies in FeatureCache, purity + completeness tests</name>
  <files>src/intelligence/feature_factory.py, src/intelligence/feature_cache.py, tests/unit/test_feature_factory.py</files>
  <read_first>
    - src/intelligence/feature_factory.py (the primitive functions from Tasks 1-2 - assemble them)
    - src/intelligence/feature_cache.py (FeatureCache from Tasks 1-2 - add cross-asset proxy populators)
    - src/intelligence/schemas.py (FeatureVector - the assembly target)
    - src/intelligence/context/vix_context.py (VIX z-score pattern - adapt to SPY realized-vol proxy since VXX/VIXY absent)
    - src/intelligence/context/macro_context.py (flight_quality / yield_curve_slope pattern - adapt to TLT/SPY and TLT/SHY)
    - .planning/phases/137-feature-factory/137-RESEARCH.md (Pitfall 1 cross-asset redesign; Open Question 1 proxy instruments)
  </read_first>
  <action>
    RED then GREEN:

    (1) Cross-asset proxy populators in feature_cache.py: `FeatureCache.update_cross_asset(spy_bars, tlt_bars, shy_bars, config)` computing:
        - vix_z: z-score of SPY trailing realized volatility over vix_zscore_window (proxy - no native VIX ETF in the 58-ETF universe; document inline)
        - flight_quality: TLT/SPY relative-return divergence (positive when TLT outperforms SPY = risk-off)
        - yield_slope_z: z-score of TLT/SHY return ratio over yield_curve_zscore_window (2Y-10Y curve proxy)
        These write into FeatureCache.vix_z / flight_quality / yield_slope_z. compute() only reads them.

    (2) Assemble `FeatureFactory.compute(bars, symbol, tf, cache, config) -> FeatureVector`: call every primitive function, read cache for regime/cross-asset/CTF/session values, construct and return the frozen FeatureVector with all 35 fields. Cold-start (insufficient history) yields 0.0 for continuous features (never NaN, never None).

    (3) Purity + completeness tests:
        - compute() returns a FeatureVector with all 35 fields as finite floats
        - compute() runs with NO ConfigService importable in scope and NO DB connection (purity) - pass a fully-built FeatureFactoryConfig and FeatureCache
        - compute() is deterministic: same inputs -> identical output
        - no NaN in any output field
  </action>
  <verify>
    .venv/bin/pytest tests/unit/test_feature_factory.py -q && .venv/bin/ruff check src/intelligence/feature_factory.py src/intelligence/feature_cache.py
  </verify>
  <acceptance_criteria>
    - `FeatureFactory.compute(...)` returns a `FeatureVector` instance with all 35 fields set to finite floats (test asserts `math.isfinite` on every field)
    - purity test passes: compute() produces output with no DB/Kafka/ConfigService access (asserted by running with a constructed config+cache and no live services)
    - determinism test: two compute() calls with identical inputs return equal FeatureVectors
    - cross-asset test: a FeatureCache populated via update_cross_asset surfaces vix_z/flight_quality/yield_slope_z in compute() output
    - `.venv/bin/pytest tests/unit/test_feature_factory.py -q` exits 0 (full file green)
    - `.venv/bin/ruff check src/intelligence/feature_factory.py src/intelligence/feature_cache.py` exits 0
  </acceptance_criteria>
</task>

</tasks>

<verification>
- Full tests/unit/test_feature_factory.py green (RED->GREEN history per primitive)
- compute() pure: no ConfigService/DB/Kafka at compute time
- Forward-only HMM (no _smooth), OHLCV proxy flow (no tick_buffer)
- All 35 fields finite, deterministic
- Cross-asset proxies (vix_z/flight_quality/yield_slope_z) computed in FeatureCache from available ETFs (VXX/VIXY confirmed absent)
- Zero inline numeric constants in primitive bodies (SC-9)
- ruff clean
</verification>

<success_criteria>
SC-2 (FeatureFactory.compute -> FeatureVector, all 35 primitives) satisfied.
SC-9 (zero inline numeric constants in feature_factory.py) satisfied: all tunables from FeatureFactoryConfig.
</success_criteria>

<output>
After completion, create `.planning/phases/137-feature-factory/137-P3-SUMMARY.md`. Record the cross-asset proxy decisions (vix_z via SPY realized-vol, flight_quality via TLT/SPY, yield_slope_z via TLT/SHY) since VXX/VIXY are not in the universe - Phase 138 IC will judge these proxies.
</output>
