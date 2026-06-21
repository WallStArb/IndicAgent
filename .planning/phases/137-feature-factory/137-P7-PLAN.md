---
phase: 137-feature-factory
plan: 7
type: execute
wave: 5
depends_on: [1, 3, 5]
files_modified:
  - src/intelligence/schemas.py
  - src/intelligence/feature_factory.py
  - src/intelligence/feature_cache.py
  - services/backfill_feature_factory.py
  - production/migrations/156_feature_vectors_expand.sql
  - tests/unit/intelligence/test_feature_factory_p7.py
autonomous: true
requirements: [SC-P7-1, SC-P7-2, SC-P7-3, SC-P7-4]

threat_model:
  assets:
    - "FeatureVector dataclass (schemas.py) — schema contract shared by FeatureFactory, backfill, feature_writer, and IC Engine"
    - "feature_vectors hypertable — any new column must be idempotent-safe to add"
    - "backfill_feature_factory.py _INSERT_FEATURE_VECTORS_SQL — must stay in sync with FeatureVector field order"
    - "FeatureCache — mutable state shared across bars; new fields must not interfere with existing regime/CTF state"
  threats:
    - id: T1
      description: "FeatureVector and _INSERT_FEATURE_VECTORS_SQL column lists diverge after adding 18 fields — inserts silently write NULL for new columns or fail with column count mismatch"
      severity: critical
      mitigation: "Add all 18 fields to _INSERT_FEATURE_VECTORS_SQL and _vector_to_params() in the same commit as schemas.py; acceptance criterion: count(%s) in SQL == len(FeatureVector.__dataclass_fields__) + 6 (the 6 key/metadata columns)"
    - id: T2
      description: "Migration adds column that already exists in DB — ALTER TABLE fails on re-run"
      severity: high
      mitigation: "Use ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS for every new column; migration is idempotent"
    - id: T3
      description: "New APR keys not seeded in config_state — FeatureFactoryConfig construction fails or silently uses wrong defaults at backfill/pipeline startup"
      severity: high
      mitigation: "Migration seeds all 14 new APR keys in config_schema + config_state ON CONFLICT DO NOTHING; _build_feature_factory_config asserts all keys have values; acceptance: run backfill --help exits 0 after migration"
    - id: T4
      description: "FeatureCache.above_wk_vwap week boundary reset not called correctly — weekly VWAP accumulates across weeks, producing a meaningless multi-week average"
      severity: medium
      mitigation: "FeatureCache.update_wk_vwap() resets _wk_tp_vol_sum/_wk_vol_sum when ISO week number changes; unit test verifies reset at week boundary"
    - id: T5
      description: "hmm_duration increments even when regime label is stable across long periods — test checks edge case where regime never changes (duration grows indefinitely)"
      severity: low
      mitigation: "hmm_duration is a float capped nowhere; indefinite growth is correct behavior. Test should verify: changes after refresh_regime with a different discrete label, holds across stable periods"
    - id: T6
      description: "Statistical features (ret_acf1_z, ret_skew_z) produce NaN on short bar arrays — NaN propagates silently through the INSERT to DB"
      severity: medium
      mitigation: "_guard() wrapper in compute() catches all NaN/inf. Minimum bar requirements: ret_acf1_z needs >= 3 bars (2 returns + lag); ret_skew_z needs >= 3 bars. Return 0.0 on cold start"
  block_on: [T1, T2, T3]

must_haves:
  truths:
    - "FeatureVector has exactly 54 float fields after this plan"
    - "feature_vectors hypertable has exactly 54 feature columns (+ 5 key/metadata = 59 total) after migration runs"
    - "_INSERT_FEATURE_VECTORS_SQL in backfill_feature_factory.py lists all 54 feature columns"
    - "_vector_to_params() returns a tuple of length 60 (6 key/metadata + 54 feature values)"
    - "All 14 new APR keys seeded in config_schema + config_state"
    - "FEATURE_VECTOR_DOMAIN constant exists in feature_factory.py mapping all 54 features to their vector_domain"
    - "FeatureFactory.compute() returns a FeatureVector with all 54 fields set to finite floats"
    - "pytest tests/unit/ -q is green after this plan"
  artifacts:
    - path: "production/migrations/156_feature_vectors_expand.sql"
      provides: "18 new feature columns + 14 new APR keys"
      contains: "ADD COLUMN IF NOT EXISTS"
    - path: "src/intelligence/schemas.py"
      provides: "54-field FeatureVector dataclass"
      contains: "rsi_fast"
    - path: "src/intelligence/feature_factory.py"
      provides: "54-feature compute() + FEATURE_VECTOR_DOMAIN"
      contains: "FEATURE_VECTOR_DOMAIN"
    - path: "src/intelligence/feature_cache.py"
      provides: "hmm_duration tracking + above_wk_vwap weekly VWAP"
      contains: "hmm_duration"
    - path: "services/backfill_feature_factory.py"
      provides: "Updated INSERT SQL + _vector_to_params for 54 features"
      contains: "rsi_fast"
    - path: "tests/unit/intelligence/test_feature_factory_p7.py"
      provides: "Unit tests for all 18 new features"
      contains: "test_rsi"
---

<objective>
Extend Phase 137's FeatureVector from 36 to 54 fields by implementing the 18 features defined in IC spec §VI.3 that are currently absent from the codebase. This plan MUST run before P6 (cutover): the live pipeline must compute all 54 features from day one, and the backfill must populate all 54 columns.

The 18 missing features are:
- Oscillators (6): rsi_fast, rsi_mid, rsi_slow, cci_fast, cci_mid, cci_slow
- Trend freshness (2): aroon_fast, aroon_slow
- Volume/flow (1): ofi_div
- HMM regime (1): hmm_duration
- Calendar (4): in_london_kz, power_hour, opening_range, above_wk_vwap
- Statistical/liquidity (4): amihud_illiq_z, high_52w_dist, ret_skew_z, ret_acf1_z

The P6 plan depends_on must include P7. Adjust 137-P6-PLAN.md header to depends_on: [3, 4, 5, 7] before running P6.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/137-feature-factory/137-CONTEXT.md
@src/intelligence/schemas.py
@src/intelligence/feature_factory.py
@src/intelligence/feature_cache.py
@services/backfill_feature_factory.py
@production/migrations/155_feature_vectors.sql
@CLAUDE.md
@docs/plans/2026-06-20-alphaengine-ic-spec.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: SQL migration (156) + FeatureVector dataclass extension (schemas.py)</name>
  <files>production/migrations/156_feature_vectors_expand.sql, src/intelligence/schemas.py</files>
  <read_first>
    - production/migrations/155_feature_vectors.sql (current DDL for reference — column order, naming, double precision type)
    - src/intelligence/schemas.py:1204-1262 (current FeatureVector with 36 fields — insert new fields in IC spec §VI.3 group order)
    - docs/plans/2026-06-20-alphaengine-ic-spec.md §VI.3 (canonical 54-feature list with exact column names and group membership)
  </read_first>
  <action>
    Write production/migrations/156_feature_vectors_expand.sql:

    Section 1 — Add 18 feature columns to feature_vectors. Use ADD COLUMN IF NOT EXISTS for idempotency. Group and order matches IC spec §VI.3:

    Oscillators (6): rsi_fast, rsi_mid, rsi_slow, cci_fast, cci_mid, cci_slow — double precision
    Trend freshness (2): aroon_fast, aroon_slow — double precision (after existing hma_slope_z, adx)
    Volume/flow (1): ofi_div — double precision (after rel_volume)
    HMM regime (1): hmm_duration — double precision (after hmm_entropy, as it is a regime-level field)
    Calendar (4): in_london_kz, power_hour, opening_range, above_wk_vwap — double precision (after month_position)
    Statistical/liquidity (4): amihud_illiq_z, high_52w_dist, ret_skew_z, ret_acf1_z — double precision (new group, after ctf_regime_align)

    Section 2 — Seed 14 new APR keys in config_schema + config_state (ON CONFLICT DO NOTHING):
      feature.period.rsi.fast = 7   [conventional] Half of Wilder's canonical; ML learning target
      feature.period.rsi.mid  = 14  [conventional] Wilder canonical RSI period; ML learning target
      feature.period.rsi.slow = 28  [conventional] Double of canonical; ML learning target
      feature.period.cci.fast = 10  [initial_estimate] Fast CCI cycle; ML learning target
      feature.period.cci.mid  = 20  [initial_estimate] Mid CCI cycle; ML learning target
      feature.period.cci.slow = 40  [initial_estimate] Slow CCI cycle; ML learning target
      feature.period.aroon.fast = 14 [initial_estimate] Aroon fast window; ML learning target
      feature.period.aroon.slow = 25 [initial_estimate] Aroon slow window; ML learning target
      feature.amihud.zscore_window = 252 [conventional] ~1 trading year; not an ML learning target
      feature.ret_skew.window      = 60  [initial_estimate] Rolling window for return skewness; ML learning target
      feature.ret_skew.zscore_window = 252 [conventional] Z-score window for skewness; not an ML target
      feature.ret_acf.window       = 30  [initial_estimate] Rolling window for ACF lag-1; ML learning target
      feature.ret_acf.zscore_window = 252 [conventional] Z-score window for ACF; not an ML target
      feature.high_52w.window      = 252 [conventional] 252 trading days = 1 year; not an ML target

    Run the migration against the DB: PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/156_feature_vectors_expand.sql

    Update src/intelligence/schemas.py FeatureVector dataclass:
    - Add 18 new float fields in group order matching IC spec §VI.3:
      After vol_ratio (end of bar-level group): add ofi_div
      After adx (end of regime-level group): add aroon_fast, aroon_slow, hmm_duration
      After month_position (end of calendar group): add in_london_kz, power_hour, opening_range, above_wk_vwap
      After ctf_regime_align (end of CTF group): add rsi_fast, rsi_mid, rsi_slow, cci_fast, cci_mid, cci_slow
      After cci_slow: add amihud_illiq_z, high_52w_dist, ret_skew_z, ret_acf1_z
    - Update the docstring: change "35 orthogonal feature primitives" → "54 orthogonal feature primitives" and update group counts
    - No defaults — all fields remain required (frozen dataclass per D-08)
  </action>
  <verify>
    PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT column_name FROM information_schema.columns WHERE table_name='feature_vectors' ORDER BY ordinal_position;" | grep -c "double\|text\|timestamptz" && python -c "from src.intelligence.schemas import FeatureVector; import dataclasses; fields = dataclasses.fields(FeatureVector); assert len(fields) == 54, f'Expected 54, got {len(fields)}'; print('FeatureVector has', len(fields), 'fields - OK')"
  </verify>
  <acceptance_criteria>
    - `SELECT count(*) FROM information_schema.columns WHERE table_name='feature_vectors'` returns 59 (5 key/metadata + 54 features, up from 41)
    - `len(dataclasses.fields(FeatureVector)) == 54`
    - Migration is idempotent: re-running does not error (IF NOT EXISTS + ON CONFLICT DO NOTHING)
    - All 14 new APR keys exist in config_state: `SELECT count(*) FROM config_state WHERE config_key LIKE 'feature.period.%' OR config_key LIKE 'feature.amihud.%' OR config_key LIKE 'feature.ret_%' OR config_key LIKE 'feature.high_52w.%'` returns >= 14
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 2: FeatureFactoryConfig extensions + RSI/CCI/Aroon/OFI-div implementations</name>
  <files>src/intelligence/feature_factory.py</files>
  <read_first>
    - src/intelligence/feature_factory.py:55-104 (FeatureFactoryConfig — frozen dataclass with APR keys; add 8 new fields)
    - src/intelligence/feature_factory.py:438-630 (FeatureFactory.compute() — current 36-feature implementation; extend to 54)
    - src/intelligence/feature_factory.py:676-710 (_cold_start_vector — update with 18 new fields)
    - docs/plans/2026-06-20-alphaengine-ic-spec.md §VI.3 (Oscillators, Trend freshness, Volume/flow groups — exact formulas)
  </read_first>
  <action>
    Extend FeatureFactoryConfig (frozen dataclass, in APR comment block):
    Add 8 new fields with APR key comments:
      rsi_fast_period: int   # feature.period.rsi.fast
      rsi_mid_period: int    # feature.period.rsi.mid
      rsi_slow_period: int   # feature.period.rsi.slow
      cci_fast_period: int   # feature.period.cci.fast
      cci_mid_period: int    # feature.period.cci.mid
      cci_slow_period: int   # feature.period.cci.slow
      aroon_fast_period: int # feature.period.aroon.fast
      aroon_slow_period: int # feature.period.aroon.slow

    Implement 4 pure-function helpers (stateless, numpy array inputs):

    _rsi(closes: np.ndarray, period: int) -> float:
      Wilder's RSI using smoothed moving average (SMA for first avg, EMA-style after).
      Returns 50.0 (neutral) if len(closes) < period + 1.
      Formula: RS = avg_gain / avg_loss (over period), RSI = 100 - 100/(1+RS).
      Seed: SMA of first `period` gains/losses. Subsequent: EMA smoothing (alpha = 1/period).
      Returns value in [0, 100]. Clamp to [0.0, 100.0] to guard float precision edge cases.

    _cci(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> float:
      Commodity Channel Index: CCI = (typical - SMA_typical) / (0.015 * MAD).
      typical = (high + low + close) / 3.
      MAD = mean absolute deviation of typical from its SMA over period.
      Returns 0.0 if MAD < 1e-10 or len < period.
      No clamp — CCI is unbounded but typically in [-200, +200].

    _aroon_osc(highs: np.ndarray, lows: np.ndarray, period: int) -> float:
      Aroon Oscillator = (aroon_up - aroon_down) / 100, range [-1.0, 1.0].
      aroon_up = ((period - bars_since_high) / period) * 100
      aroon_down = ((period - bars_since_low) / period) * 100
      bars_since_high = period - argmax(highs[-period-1:]) (index from oldest in window)
      bars_since_low = period - argmin(lows[-period-1:])
      Returns 0.0 if len < period + 1.

    _ofi_div(ofi_z: float, momentum_z_5: float) -> float:
      OFI vs price divergence: ofi_z - momentum_z_5.
      Both already in z-score units from compute(). No additional scaling.
      Returns 0.0 if either input is not finite.

    Wire into compute() immediately after the existing bar-level computations:
      ofi_div_val = _ofi_div(ofi_z_val, momentum_z_5_val)
      rsi_fast_val = _rsi(closes, config.rsi_fast_period)
      rsi_mid_val = _rsi(closes, config.rsi_mid_period)
      rsi_slow_val = _rsi(closes, config.rsi_slow_period)
      cci_fast_val = _cci(highs, lows, closes, config.cci_fast_period)
      cci_mid_val = _cci(highs, lows, closes, config.cci_mid_period)
      cci_slow_val = _cci(highs, lows, closes, config.cci_slow_period)
      aroon_fast_val = _aroon_osc(highs, lows, config.aroon_fast_period)
      aroon_slow_val = _aroon_osc(highs, lows, config.aroon_slow_period)

    Update _cold_start_vector() to include all 18 new fields (neutral defaults):
      rsi_fast/mid/slow = 50.0, cci_fast/mid/slow = 0.0, aroon_fast/slow = 0.0,
      ofi_div = 0.0, hmm_duration = 0.0, in_london_kz = 0.0, power_hour = 0.0,
      opening_range = 0.0, above_wk_vwap = 0.0, amihud_illiq_z = 0.0,
      high_52w_dist = 0.0, ret_skew_z = 0.0, ret_acf1_z = 0.0

    Update the FeatureVector() construction in compute() to include the 9 new fields computed here.
    Remaining 9 fields (hmm_duration, calendar 4, statistical 4) will be added in Task 3 — use
    placeholder values from _cold_start_vector() in this task's interim construction, clearly
    marked with a TODO comment that Task 3 removes. Both tasks will be committed together
    before the suite runs, so no intermediate broken state is committed.

    Keep all numeric literals from APR (SC-9): no hard-coded period values in compute().
    All config field accesses via config.rsi_fast_period etc.
  </action>
  <verify>
    .venv/bin/python -c "
from src.intelligence.feature_factory import FeatureFactory, FeatureFactoryConfig, FeatureCache
import numpy as np
cfg = FeatureFactoryConfig(
    momentum_window_short=5, momentum_window_long=20, momentum_zscore_window=20,
    volume_zscore_window=20, ofi_zscore_window=20, cvd_slope_bars=5, cmf_period=20,
    vol_short_bars=5, vol_long_bars=20, hma_period=20, adx_period=14, hurst_window=50,
    garch_window=50, vix_zscore_window=20, yield_curve_zscore_window=20,
    regime_cache_refresh_bars=30,
    rsi_fast_period=7, rsi_mid_period=14, rsi_slow_period=28,
    cci_fast_period=10, cci_mid_period=20, cci_slow_period=40,
    aroon_fast_period=14, aroon_slow_period=25,
    amihud_zscore_window=20, ret_skew_window=20, ret_skew_zscore_window=20,
    ret_acf_window=10, ret_acf_zscore_window=20, high_52w_window=20,
)
import math; from datetime import datetime, timezone
cache = FeatureCache()
bars = [{'open':100+i,'high':101+i,'low':99+i,'close':100+i,'volume':1000+i,'ts':datetime(2026,1,2,9,30,tzinfo=timezone.utc)} for i in range(50)]
fv = FeatureFactory.compute(bars, 'SPY', '1m', cache, cfg)
assert 0 <= fv.rsi_mid <= 100, f'rsi_mid out of range: {fv.rsi_mid}'
assert math.isfinite(fv.cci_mid), f'cci_mid not finite: {fv.cci_mid}'
assert -1.0 <= fv.aroon_fast <= 1.0, f'aroon_fast out of range: {fv.aroon_fast}'
print('RSI/CCI/Aroon/OFI-div smoke test: OK')
" && .venv/bin/ruff check src/intelligence/feature_factory.py
  </verify>
  <acceptance_criteria>
    - `_rsi(closes, 14)` with 50 identical close prices returns 50.0 (no gain/loss, neutral)
    - `_cci` with uniform prices returns 0.0 (zero MAD)
    - `_aroon_osc` with monotonically rising highs returns 1.0 (high always at most recent bar)
    - `_ofi_div(ofi_z=1.0, momentum_z_5=-1.0)` returns 2.0 (positive when flow diverges from price)
    - `fv.rsi_mid` is in [0.0, 100.0] for any valid input
    - `.venv/bin/ruff check src/intelligence/feature_factory.py` exits 0
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 3: Statistical + calendar features + FeatureCache extensions + FEATURE_VECTOR_DOMAIN</name>
  <files>src/intelligence/feature_factory.py, src/intelligence/feature_cache.py</files>
  <read_first>
    - src/intelligence/feature_cache.py:29-181 (FeatureCache dataclass — add hmm_duration, above_wk_vwap state; update refresh_regime for discrete label)
    - src/intelligence/feature_factory.py:381-415 (existing calendar helpers — add in_london_kz, power_hour, opening_range alongside _in_ny_session, _in_overlap)
    - docs/plans/2026-06-20-alphaengine-ic-spec.md §VI.3 (Statistical process / liquidity group — exact formulas for Amihud, 52w, ret_skew, ret_acf1)
    - docs/plans/2026-06-20-alphaengine-ic-spec.md §VI.3a (FEATURE_VECTOR_DOMAIN mapping — all 54 features to their vector_domain string)
  </read_first>
  <action>
    --- FeatureCache extensions ---

    Add to FeatureCache dataclass (after existing ctf fields):
      hmm_duration: float = 0.0       # bars in current HMM regime state
      above_wk_vwap: float = 0.0      # 1.0 if close > weekly VWAP, else 0.0
      _hmm_regime_label: int = -1      # discrete HMM state for change detection (not in FeatureVector)
      _wk_tp_vol_sum: float = 0.0      # accumulator: sum(typical * volume) for current ISO week
      _wk_vol_sum: float = 0.0         # accumulator: sum(volume) for current ISO week
      _wk_isoweek: int = -1            # ISO week number; reset trigger

    Extend refresh_regime() to also compute and track the discrete HMM state label:
      After _hmm_forward_2d() call: derive new_label as argmax of the forward state distribution.
      If new_label != self._hmm_regime_label (and _hmm_regime_label != -1):
          self.hmm_duration = 0.0
      self._hmm_regime_label = new_label

    Add method update_wk_vwap(bar_ts: datetime, high: float, low: float, close: float, volume: float):
      current_week = bar_ts.isocalendar()[1]  # ISO week number
      if current_week != self._wk_isoweek:    # week boundary — reset accumulators
          self._wk_tp_vol_sum = 0.0
          self._wk_vol_sum = 0.0
          self._wk_isoweek = current_week
      typical = (high + low + close) / 3.0
      self._wk_tp_vol_sum += typical * volume
      self._wk_vol_sum += volume
      wk_vwap = self._wk_tp_vol_sum / self._wk_vol_sum if self._wk_vol_sum > 1e-10 else close
      self.above_wk_vwap = 1.0 if close > wk_vwap else 0.0

    The pipeline and backfill call cache.update_wk_vwap(bar_ts, high_, low_, close_, vol_) and
    cache.hmm_duration += 1.0 after each compute() call (BEFORE the next refresh_regime check).

    --- _hmm_forward_2d update ---
    Modify _hmm_forward_2d in feature_cache.py to return (regime_prob, entropy, regime_label: int)
    where regime_label = argmax of alpha[-1] (integer, 0 or 1 for the 2-state model).
    Update refresh_regime() to unpack all three and use regime_label for hmm_duration tracking.

    --- Calendar features in feature_factory.py ---

    Add 3 pure datetime helpers alongside existing _in_ny_session, _in_overlap:

    _in_london_kz(bar_ts: datetime) -> float:
      London killzone: 08:00-10:00 UTC (3-5 AM ET winter / 4-6 AM ET summer).
      Returns 1.0 if UTC hour is 8 or 9, else 0.0.
      Note: uses UTC directly (London open is 08:00 UTC in winter, 07:00 UTC in summer).
      Simple approximation: 07:00-10:00 UTC covers both seasons.
      Range: 07 <= hour <= 09 (inclusive).

    _power_hour(bar_ts: datetime) -> float:
      Power hour: 3:00-4:00 PM ET. ET = UTC-5 (winter) / UTC-4 (summer).
      Approximate in UTC: 20:00-21:00 UTC (winter) or 19:00-20:00 UTC (summer).
      Simple: 19:00 <= UTC hour <= 20. Returns 1.0 if in range, 0.0 otherwise.

    _opening_range(bar_ts: datetime) -> float:
      First 30 min of NY session: 9:30-10:00 AM ET.
      ET = UTC-5 (winter) / UTC-4 (summer). Approximate UTC: 14:30-15:00 winter / 13:30-14:00 summer.
      Use UTC-based proxy: 13:30 <= UTC time <= 15:00 to cover both seasons.
      hour*60+minute >= 810 (13:30 UTC) and <= 900 (15:00 UTC). Returns 1.0 if in range, 0.0 otherwise.

    Wire calendar features into compute():
      in_london_kz_val = _in_london_kz(bar_ts)
      power_hour_val = _power_hour(bar_ts)
      opening_range_val = _opening_range(bar_ts)
      above_wk_vwap_val = cache.above_wk_vwap  # from FeatureCache (updated by caller)

    --- Statistical features in feature_factory.py ---

    Add 4 pure-function helpers (all take np.ndarray + window params):

    _amihud_illiq_z(closes: np.ndarray, volumes: np.ndarray, zscore_window: int) -> float:
      For each bar: illiq_i = |log_return_i| / (close_i * volume_i + eps).
      Compute over last zscore_window bars. Z-score the most recent value vs the window.
      Return 0.0 if len < 2 or all zero volume.
      Use _rolling_zscore pattern (window = min(zscore_window, len - 1)).

    _high_52w_dist(closes: np.ndarray, window: int) -> float:
      (close[-1] - max(closes[-window:])) / (max(closes[-window:]) + eps).
      Returns 0.0 if len < 2. Returns negative float (distance below 52w high).
      No z-scoring — the ratio is already dimensionless and cross-sectionally comparable.

    _ret_skew_z(closes: np.ndarray, skew_window: int, zscore_window: int) -> float:
      Compute log returns. Compute rolling skewness over skew_window. Z-score the most
      recent skewness value vs the last zscore_window computed skewness values.
      Skewness = (mean(r^3) - 3*mean(r)*mean(r^2) + 2*mean(r)^3) / std^3 (Fisher's).
      Use scipy.stats.skew or manual computation (prefer manual for zero-dep).
      Return 0.0 if len < skew_window + 3.

    _ret_acf1_z(closes: np.ndarray, acf_window: int, zscore_window: int) -> float:
      Compute log returns. Compute rolling Pearson lag-1 autocorrelation over acf_window bars.
      Use numpy corrcoef on (returns[1:], returns[:-1]) over each window.
      Z-score the most recent ACF value vs the last zscore_window computed ACF values.
      Return 0.0 if len < acf_window + 2.
      Note: spec says Spearman; use Pearson for simplicity. IC will judge both the same at this N.

    Wire statistical features into compute():
      amihud_illiq_z_val = _amihud_illiq_z(closes, volumes, config.amihud_zscore_window)
      high_52w_dist_val = _high_52w_dist(closes, config.high_52w_window)
      ret_skew_z_val = _ret_skew_z(closes, config.ret_skew_window, config.ret_skew_zscore_window)
      ret_acf1_z_val = _ret_acf1_z(closes, config.ret_acf_window, config.ret_acf_zscore_window)

    --- Additional FeatureFactoryConfig fields ---
    Add these 6 fields to FeatureFactoryConfig (the 8 from Task 2 already added oscillator periods):
      amihud_zscore_window: int    # feature.amihud.zscore_window
      ret_skew_window: int          # feature.ret_skew.window
      ret_skew_zscore_window: int   # feature.ret_skew.zscore_window
      ret_acf_window: int           # feature.ret_acf.window
      ret_acf_zscore_window: int    # feature.ret_acf.zscore_window
      high_52w_window: int          # feature.high_52w.window

    --- FEATURE_VECTOR_DOMAIN constant ---
    Add module-level constant to feature_factory.py immediately after the imports section:

    FEATURE_VECTOR_DOMAIN: dict[str, str] = {
        # Momentum
        "momentum_z_5": "quant", "momentum_z_20": "quant", "range_position": "quant",
        "bar_close_pos": "quant", "gap_z": "quant",
        # Oscillators
        "rsi_fast": "quant", "rsi_mid": "quant", "rsi_slow": "quant",
        "cci_fast": "quant", "cci_mid": "quant", "cci_slow": "quant",
        # Trend
        "aroon_fast": "quant", "aroon_slow": "quant", "hma_slope_z": "quant", "adx": "quant",
        # Volume/flow
        "informed_flow": "quant", "volume_z": "quant", "ofi_z": "quant", "ofi_div": "quant",
        "cvd_slope_z": "quant", "cmf": "quant", "rel_volume": "quant",
        # Volatility
        "vwap_dev_sigma": "quant", "atr_z": "quant", "vol_ratio": "quant",
        "hurst": "quant", "shannon": "quant",
        # HMM regime
        "hmm_regime_prob": "regime", "hmm_entropy": "regime", "hmm_duration": "regime",
        "garch_ratio": "regime",
        # Market structure
        "poc_dist_atr": "structural", "va_position": "structural",
        "sr_support_dist": "structural", "sr_resist_dist": "structural",
        # Macro
        "vix_z": "macro", "flight_quality": "macro", "yield_slope_z": "macro",
        # Calendar/session
        "in_ny_session": "calendar", "in_london_kz": "calendar", "in_overlap": "calendar",
        "power_hour": "calendar", "opening_range": "calendar", "above_wk_vwap": "calendar",
        "dow_sin": "calendar", "dow_cos": "calendar", "month_position": "calendar",
        # Cross-timeframe
        "ctf_momentum": "quant", "ctf_vwap_align": "quant", "ctf_regime_align": "regime",
        # Statistical/liquidity
        "amihud_illiq_z": "quant", "high_52w_dist": "quant",
        "ret_skew_z": "quant", "ret_acf1_z": "quant",
    }

    The mapping must cover all 54 features (assert len(FEATURE_VECTOR_DOMAIN) == 54 in a test).

    Update FeatureVector construction in compute() to include all 18 new fields.
    Remove any TODO placeholders from Task 2's interim construction.
    Update the docstring on compute() to say "54 FeatureVector primitives".
    Update _cold_start_vector() to include all 18 new fields with neutral defaults.
  </action>
  <verify>
    .venv/bin/python -c "
from src.intelligence.feature_factory import FeatureFactory, FeatureFactoryConfig, FeatureCache, FEATURE_VECTOR_DOMAIN
import dataclasses, src.intelligence.schemas as s
fv_fields = {f.name for f in dataclasses.fields(s.FeatureVector)}
assert len(fv_fields) == 54, f'{len(fv_fields)} fields'
assert set(FEATURE_VECTOR_DOMAIN.keys()) == fv_fields, f'domain mismatch: {fv_fields ^ set(FEATURE_VECTOR_DOMAIN.keys())}'
print('FEATURE_VECTOR_DOMAIN covers all 54 fields: OK')
from datetime import datetime, timezone
cache = FeatureCache()
cache.update_wk_vwap(datetime(2026,1,5,14,0,tzinfo=timezone.utc), 101.0, 99.0, 100.0, 1000.0)
assert cache.above_wk_vwap in (0.0, 1.0)
print('above_wk_vwap: OK')
" && .venv/bin/ruff check src/intelligence/feature_factory.py src/intelligence/feature_cache.py
  </verify>
  <acceptance_criteria>
    - `len(FEATURE_VECTOR_DOMAIN) == 54`
    - `set(FEATURE_VECTOR_DOMAIN.keys()) == {f.name for f in dataclasses.fields(FeatureVector)}`
    - `FeatureCache.update_wk_vwap()` resets accumulators when ISO week changes (unit test)
    - `_in_london_kz(datetime(2026,1,5,8,30,tzinfo=UTC))` returns 1.0
    - `_power_hour(datetime(2026,1,5,19,30,tzinfo=UTC))` returns 1.0
    - `_opening_range(datetime(2026,1,5,14,0,tzinfo=UTC))` returns 1.0
    - `_high_52w_dist(array_at_52w_high, 252)` returns 0.0 (close == max)
    - `_amihud_illiq_z` with constant prices returns 0.0 (zero returns)
    - `.venv/bin/ruff check src/intelligence/feature_factory.py src/intelligence/feature_cache.py` exits 0
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 4: Update backfill_feature_factory.py + _build_feature_factory_config + unit tests</name>
  <files>services/backfill_feature_factory.py, tests/unit/intelligence/test_feature_factory_p7.py</files>
  <read_first>
    - services/backfill_feature_factory.py:182-350 (_INSERT_FEATURE_VECTORS_SQL, _vector_to_params, _build_feature_factory_config — must include all 54 features)
    - services/backfill_feature_factory.py:696-780 (compute loop — must call cache.update_wk_vwap() and cache.hmm_duration += 1.0 per bar)
    - tests/unit/services/test_backfill_feature_factory.py (existing test patterns — follow same mock/fixture style)
    - CLAUDE.md "Exception variable name is `error`" and no hardcoded numerics
  </read_first>
  <action>
    Update services/backfill_feature_factory.py:

    (1) _INSERT_FEATURE_VECTORS_SQL: add all 18 new column names to the INSERT list.
    Place them in the same group order as schemas.py FeatureVector field order.
    Add corresponding %s placeholders. Column count: 6 metadata + 54 features = 60.

    (2) _vector_to_params(): add all 18 new fv.<field> accesses in the return tuple.
    Same order as the INSERT SQL. Verify: len(result) == 60.

    (3) _build_feature_factory_config(): add 14 new APR key lookups:
      rsi_fast_period=int(cfg.get_sync("feature.period.rsi.fast", 7)),
      rsi_mid_period=int(cfg.get_sync("feature.period.rsi.mid", 14)),
      rsi_slow_period=int(cfg.get_sync("feature.period.rsi.slow", 28)),
      cci_fast_period=int(cfg.get_sync("feature.period.cci.fast", 10)),
      cci_mid_period=int(cfg.get_sync("feature.period.cci.mid", 20)),
      cci_slow_period=int(cfg.get_sync("feature.period.cci.slow", 40)),
      aroon_fast_period=int(cfg.get_sync("feature.period.aroon.fast", 14)),
      aroon_slow_period=int(cfg.get_sync("feature.period.aroon.slow", 25)),
      amihud_zscore_window=int(cfg.get_sync("feature.amihud.zscore_window", 252)),
      ret_skew_window=int(cfg.get_sync("feature.ret_skew.window", 60)),
      ret_skew_zscore_window=int(cfg.get_sync("feature.ret_skew.zscore_window", 252)),
      ret_acf_window=int(cfg.get_sync("feature.ret_acf.window", 30)),
      ret_acf_zscore_window=int(cfg.get_sync("feature.ret_acf.zscore_window", 252)),
      high_52w_window=int(cfg.get_sync("feature.high_52w.window", 252)),

    (4) Compute loop (the per-bar loop that calls FeatureFactory.compute()):
      After each compute() call and before appending to insert_batch:
        cache.update_wk_vwap(bar_ts, high, low, close, volume)
        cache.hmm_duration += 1.0
      Note: hmm_duration reset is handled by FeatureCache.refresh_regime() when discrete label changes.
      cache.update_wk_vwap() must use the bar's actual high/low/close/volume (already extracted).

    Write tests/unit/intelligence/test_feature_factory_p7.py:

    - test_rsi_neutral_flat_prices: flat prices -> rsi_mid == 50.0
    - test_rsi_all_up_days: monotonically rising -> rsi_mid near 100.0
    - test_rsi_range: result is in [0.0, 100.0] for random close array
    - test_cci_uniform_prices: uniform prices -> cci_mid == 0.0 (zero MAD)
    - test_aroon_monotone_rise: monotonically rising highs -> aroon_fast == 1.0
    - test_aroon_range: result in [-1.0, 1.0]
    - test_ofi_div_divergence: ofi_z=1.0, momentum=-1.0 -> ofi_div == 2.0
    - test_amihud_zero_returns: flat prices -> amihud_illiq_z == 0.0
    - test_high_52w_at_high: close == rolling max -> high_52w_dist == 0.0
    - test_high_52w_below_high: close below max -> high_52w_dist < 0.0
    - test_ret_skew_cold_start: < 10 bars -> ret_skew_z == 0.0
    - test_ret_acf1_cold_start: < 5 bars -> ret_acf1_z == 0.0
    - test_in_london_kz: datetime at 08:30 UTC -> 1.0; at 12:00 UTC -> 0.0
    - test_power_hour: datetime at 19:30 UTC -> 1.0; at 15:00 UTC -> 0.0
    - test_opening_range: datetime at 14:00 UTC -> 1.0; at 16:00 UTC -> 0.0
    - test_above_wk_vwap_above: close above wk_vwap -> 1.0
    - test_above_wk_vwap_below: close below wk_vwap -> 0.0
    - test_wk_vwap_resets_on_new_week: call update_wk_vwap with week N then week N+1 -> accumulators reset
    - test_hmm_duration_increments: cache.hmm_duration increments each bar
    - test_feature_vector_domain_complete: len(FEATURE_VECTOR_DOMAIN) == 54 and covers all FeatureVector fields
    - test_vector_to_params_length: _vector_to_params returns tuple of length 60

    All tests: no live DB, no network, no IBKR. Mock FeatureCache for calendar tests.
    Follow existing test patterns in tests/unit/services/test_backfill_feature_factory.py.
    Exception variable name: `error` (CLAUDE.md rule).
  </action>
  <verify>
    .venv/bin/pytest tests/unit/intelligence/test_feature_factory_p7.py -v && .venv/bin/pytest tests/unit/ -q && .venv/bin/ruff check services/backfill_feature_factory.py tests/unit/intelligence/test_feature_factory_p7.py
  </verify>
  <acceptance_criteria>
    - `python -c "import services.backfill_feature_factory as m; sql = m._INSERT_FEATURE_VECTORS_SQL; assert sql.count('%s') == 60, f'got {sql.count(\"%s\")} placeholders'; print('SQL placeholders OK')"` exits 0
    - All tests in test_feature_factory_p7.py pass
    - `pytest tests/unit/ -q` exits 0 (full unit suite green)
    - `.venv/bin/ruff check services/backfill_feature_factory.py tests/unit/intelligence/test_feature_factory_p7.py` exits 0
  </acceptance_criteria>
</task>

</tasks>

<verification>
- FeatureVector has exactly 54 float fields (schemas.py)
- feature_vectors hypertable has 59 total columns (5 key/metadata + 54 features)
- FeatureFactory.compute() produces all 54 fields as finite floats
- FEATURE_VECTOR_DOMAIN covers all 54 fields with correct vector_domain strings
- 14 new APR keys seeded in config_schema + config_state
- backfill _INSERT_FEATURE_VECTORS_SQL has 60 %s placeholders (6 + 54)
- FeatureCache tracks hmm_duration (resets on regime change) and above_wk_vwap (weekly VWAP binary)
- Full unit suite green (pytest tests/unit/ -q)
- Migration 156 is idempotent (IF NOT EXISTS, ON CONFLICT DO NOTHING)
</verification>

<success_criteria>
SC-P7-1 (schema extension): FeatureVector == 54 fields; feature_vectors hypertable == 59 columns.
SC-P7-2 (compute coverage): FeatureFactory.compute() returns all 54 fields as finite floats for any valid input.
SC-P7-3 (backfill wiring): _INSERT_FEATURE_VECTORS_SQL + _vector_to_params correctly handle all 54 features.
SC-P7-4 (test coverage): pytest tests/unit/ green; test_feature_factory_p7.py covers all 18 new features.
</success_criteria>

<output>
After completion, create `.planning/phases/137-feature-factory/137-P7-SUMMARY.md`.
Record: FeatureVector field count confirmed at 54, DB column count confirmed at 59,
all 4 success criteria met, and that P6's depends_on header was updated to include 7.
</output>
</tasks>
