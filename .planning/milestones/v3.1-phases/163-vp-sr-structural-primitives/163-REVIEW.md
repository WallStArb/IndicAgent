---
phase: 163-vp-sr-structural-primitives
reviewed: 2026-07-23T20:43:49Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - production/migrations/255_vp_structural_primitives.sql
  - services/backfill_feature_factory.py
  - services/feature_vector_pipeline.py
  - services/_batch_utils.py
  - src/intelligence/feature_cache.py
  - src/intelligence/feature_factory.py
  - src/intelligence/features/feature_vector_persistence.py
  - src/intelligence/schemas.py
  - tests/unit/intelligence/test_feature_factory_p7.py
  - tests/unit/intelligence/test_support_resistance_primitives.py
  - tests/unit/intelligence/test_volume_profile_primitives.py
  - tests/unit/services/test_backfill_feature_factory.py
  - tests/unit/services/test_feature_vector_writer_column_mapping.py
  - tests/unit/services/test_feature_vector_writer.py
  - tests/unit/test_canary_predictors.py
  - tests/unit/test_feature_factory.py
findings:
  critical: 2
  warning: 3
  info: 3
  total: 8
status: issues_found
---

# Phase 163: Code Review Report

**Reviewed:** 2026-07-23T20:43:49Z
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Phase 163 wires 17 new structural feature_vectors columns (12 ATR-normalized volume-profile
fields + 5 support/resistance strength/age/count fields) through migration 255,
`FeatureCache.update_session_vp()`, `FeatureFactory._compute_sr_dist_atr()`/`_derive_session_vp()`,
and both `compute()` (live) and `compute_batch()` (backfill). The column-mapping mechanics are
excellent: the persistence layer, schema dataclass, and SQL all derive the new column slice by
name from `dataclasses.fields(FeatureVector)` rather than hand-typed lists, and the regression
test suite (column-mapping index pins, live==batch parity to 1e-6, non-constant guards, ATR-unit
pin) is genuinely thorough and all green.

However, two BLOCKER-level correctness gaps were found that are specific to the live pipeline
and are not caught by the existing test suite (which always exercises `compute()`/`compute_batch()`
against an unbounded, synthetic bar list rather than the live pipeline's actual bounded/restart
lifecycle):

1. The new session-VP accumulator (`FeatureCache._sess_bars`) is never warmed from buffered/seeded
   bar history when a `FeatureCache` is created, unlike the sibling `above_wk_vwap` mechanism that
   this exact function already fixes for the same reason (todo 159). Every process restart mid-session
   silently degrades all 12 new VP fields (plus `poc_dist_atr`/`va_position`) until the accumulator
   naturally re-fills.
2. `feature.session_vp.rolling_window` (default 480) exceeds the live pipeline's `BarHistory(maxlen=200)`,
   so `poc_rolling_dist_atr`/`poc_session_rolling_divergence_atr` are computed over a materially
   shorter window live than in backfill — directly contradicting the migration's own documented
   design claim (D-18) that this implementation "genuinely reaches the full 480-bar window."

Both are silent-wrong-answer bugs (no crash, no NaN, no test failure) affecting brand-new alpha
features in exactly the failure mode this codebase's own principles flag as worse than a loud crash.

## Critical Issues

### CR-01: Session-VP accumulator not warmed on FeatureCache creation — silently wrong VP features after any mid-session restart

**File:** `services/feature_vector_pipeline.py:169-191`
**Issue:**
`_get_cache()`'s docstring and warm-up loop explicitly replay `update_wk_vwap()` over buffered/
seeded bar history "so `above_wk_vwap` reflects real week-to-date volume-weighted price instead of
starting cold after every restart" (todo 159). Phase 163 Plan 02 introduced a second, analogous
accumulator — `FeatureCache._sess_bars` / `update_session_vp()` — that backs 14 FeatureVector
fields (`poc_dist_atr`, `va_position`, `nearest_hvn_above_dist_atr`, `nearest_hvn_below_dist_atr`,
`nearest_lvn_above_dist_atr`, `nearest_lvn_below_dist_atr`, `price_in_value_area`, `in_lvn`,
`va_width_atr`, `distance_to_vah_atr`, `distance_to_val_atr`, `nearest_hvn_dist_atr`, plus the two
rolling-track fields), but `_get_cache()` was never updated to also replay `update_session_vp()`
for that history:

```python
key = f"{symbol}:{tf}"
if key not in self._feature_caches:
    cache = FeatureCache()
    for bar in list(self._bar_history.get(symbol, tf))[:-1]:
        cache.update_wk_vwap(bar.ts, bar.high, bar.low, bar.close, float(bar.volume))
    self._feature_caches[key] = cache
return self._feature_caches[key]
```

`self._bar_history` is seeded from DB on every `_setup()` (i.e. on every process start/restart,
see `_seed_bar_history_from_db()`), so at the moment a `FeatureCache` is first created for a given
`(symbol, tf)`, up to 200 bars of real history are already available and are used to warm
`above_wk_vwap` — but never `_sess_bars`. If the restart happens anywhere other than exactly at
a session boundary (deploys, crashes, non-nightly IBKR gateway drops), `_sess_bars` starts empty
and `update_session_vp()` rebuilds the volume-profile histogram from just the handful of bars
processed since restart, producing a degenerate/unrepresentative POC/VAH/VAL/HVN/LVN state (and
therefore wrong values for all 12 dependent fields) until enough bars accumulate later in the
session or the next session boundary reset fires. This is exactly the failure class todo 159
already fixed for `above_wk_vwap`, left unaddressed for the new accumulator this phase adds.
`compute_batch()` has no equivalent gap (it always runs start-to-finish over the full DB history),
so this is a live-only, backfill-invisible defect — the `test_live_batch_parity` tests in
`tests/unit/intelligence/test_volume_profile_primitives.py`/`test_support_resistance_primitives.py`
cannot catch it because they construct `compute()` calls directly against an unbounded synthetic
bar list rather than going through `FeatureVectorPipeline._get_cache()`.

**Fix:**
```python
key = f"{symbol}:{tf}"
if key not in self._feature_caches:
    cache = FeatureCache()
    buffered = list(self._bar_history.get(symbol, tf))[:-1]
    for bar in buffered:
        cache.update_wk_vwap(bar.ts, bar.high, bar.low, bar.close, float(bar.volume))
    for bar in buffered:
        cache.update_session_vp(bar.ts, bar.high, bar.low, bar.close, float(bar.volume), self._feature_factory_config)
    self._feature_caches[key] = cache
return self._feature_caches[key]
```
(Note `self._feature_factory_config` must already be built — it is, by the time bars are flowing,
since `_prewarm_threshold_config()` runs in `_setup()` before Kafka consumption starts.)

### CR-02: `poc_rolling_dist_atr`/`poc_session_rolling_divergence_atr` computed over a materially shorter window live than in backfill

**File:** `src/intelligence/feature_factory.py:3832-3840` (compute), `:4257-4265` (compute_batch); `services/feature_vector_pipeline.py:126`; `production/migrations/255_vp_structural_primitives.sql:190-195`
**Issue:**
`feature.session_vp.rolling_window` defaults to 480 bars (seeded by migration 255, prewarmed
identically in both `backfill_feature_factory.py:_build_feature_factory_config` and
`feature_vector_pipeline.py:_prewarm_threshold_config`). `_rolling_poc_price()` is fed
`highs[-_roll_window:]` (live, `feature_factory.py:3833-3839`) or the causal equivalent
`highs[_roll_start:i+1]` (batch, `:4258-4264`) from the caller-supplied bars array.

In the live pipeline, that bars array is built from `self._bar_history.get(bar.symbol, bar.tf)`,
and `self._bar_history = BarHistory(maxlen=200)` (`feature_vector_pipeline.py:126`) — a hard cap
of 200 bars regardless of timeframe. So live `poc_rolling_dist_atr` /
`poc_session_rolling_divergence_atr` can never see more than 200 bars, while backfill reads the
full unbounded history from `market_data_ohlcv_tradeable` and genuinely reaches all 480. Migration
255's own APR-key description explicitly claims otherwise:

> "unlike the archived plugin (capped at <=390 bars in practice by its own
> InputSpec(lookback=390)), this phase's stateless bars[-N:] slicing genuinely reaches the full
> 480-bar window (D-18)."

That claim is true for backfill and false for the live path — a documented design invariant (D-18)
is silently violated in production, causing a systematic train/serve skew specifically for these
two new fields (IC measured against backfill-computed values will not transfer to what the live
pipeline actually serves). No test in this phase catches it:
`tests/unit/intelligence/test_volume_profile_primitives.py::test_live_batch_parity` deliberately
overrides `session_vp_rolling_window=15` (well below N=90) specifically so both paths see a
"genuine trailing subset," and always calls `FeatureFactory.compute(bars[:i+1], ...)` directly with
an unbounded Python list — it never simulates `BarHistory`'s 200-bar cap.

**Fix:** Either (a) raise `BarHistory`'s live-pipeline maxlen to cover the largest configured
window across all APR windows that read from it (or make it config-driven, since several
pre-existing windows — `momentum_zscore_window`, `hurst_window`, `vix_zscore_window`, all default
252 — already silently exceed 200 for the same underlying reason), or (b) cap
`session_vp_rolling_window`'s effective value in the live path to `BarHistory`'s maxlen and correct
the D-18 comment to state the window is best-effort/bounded live, not "genuinely reaches the full
window" unconditionally. Add a regression test that constructs `FeatureCache`/`compute()` through
a bar list truncated to 200 (mirroring `BarHistory`) and asserts `poc_rolling_dist_atr` differs
detectably from the unbounded-window value once history exceeds 200 bars, so this gap can't
regress silently again.

## Warnings

### WR-01: Stale docstring in `_compute_symbol_tf()` claims VP/SR are NULL in batch — contradicted by this phase's own change

**File:** `services/backfill_feature_factory.py:1013-1024`
**Issue:** The docstring still reads:
```
3. VP/SR (poc_dist_atr, va_position, sr_support_dist, sr_resist_dist): NULL —
   not computable from OHLCV batch without intraday I3 injection.
```
This is exactly the "stale, never-verified assumption" that `feature_factory.py`'s own
`compute_batch()` docstring (lines 4139-4149) says Phase 163 explicitly disproved and removed
(D-05). `_compute_symbol_tf()` now calls `FeatureFactory.compute_batch()` with a fully-populated
`config` (including `session_vp_*`/`sr_*` fields) and genuinely computes all 21 session-level
fields from OHLCV — the docstring was never updated to match and will mislead the next engineer
who reads this function to understand what backfill can and can't compute.
**Fix:** Update item 3 to describe the real behavior, e.g.: "3. VP/SR (poc_dist_atr, va_position,
+ 17 structural fields): computed from OHLCV via `FeatureCache.update_session_vp()` /
`_compute_sr_dist_atr()`, identical mechanism to the live path (D-05)."

### WR-02: `update_session_vp()`'s session-boundary reset is not DST-aware, and now gates a stateful accumulator

**File:** `src/intelligence/feature_cache.py:216-220`
**Issue:**
```python
ts = bar_ts if bar_ts.tzinfo is not None else bar_ts.replace(tzinfo=UTC)
total_minutes = ts.hour * 60 + ts.minute
start_minutes = config.ny_session_start_utc_hour * 60 + config.ny_session_start_utc_minute
et_date = _et_from_utc(ts).date()
session_day = et_date if total_minutes >= start_minutes else et_date - timedelta(days=1)
```
`ny_session_start_utc_hour`/`minute` is a single fixed UTC-clock APR value (13:30 UTC = 9:30 ET
only during EDT; during EST the correct boundary is 14:30 UTC). `_et_from_utc()` correctly handles
DST for the *date* conversion, but the "has today's session opened yet" comparison against
`total_minutes` does not, so for about an hour twice a year (DST transition weeks) a bar can be
attributed to the wrong session day, causing either a spurious mid-session accumulator reset or
cross-session bar contamination in `_sess_bars`. This exact non-DST-aware pattern already exists
elsewhere (`_in_ny_session()` etc.), but those are read-only calendar flags; this is the first use
of it to gate a *stateful* reset, so a misfire here silently corrupts the volume-profile inputs for
every VP-derived field for the affected bars, not just a single flag's value.
**Fix:** Either accept this as a documented, bounded (twice-yearly, ~1hr) known limitation shared
with the rest of the session-boundary logic, or resolve the session boundary via `_et_from_utc(ts)`
directly (compare ET wall-clock time against `09:30` local, not UTC hour) so it is DST-correct by
construction.

### WR-03: New `feature.sr.*`/`feature.session_vp.*` APR keys inherit a pre-existing "hot-reload doesn't actually reload" gap

**File:** `services/feature_vector_pipeline.py:722-731`, `:809-811`
**Issue:** `_handle_config_update()` invalidates and re-fetches the changed key into
`ConfigService`'s cache, but `self._feature_factory_config` is a `frozen` dataclass built once in
`_prewarm_threshold_config()` at `_setup()` time and never rebuilt. `compute()`/`compute_batch()`
always read from that frozen snapshot, never from `ConfigService` directly on the hot path (by
design — PURITY CONTRACT). So changing `feature.sr.window`, `feature.session_vp.rolling_window`,
etc. via the `/config/parameters` dashboard produces a `feature_vector_pipeline.config_reloaded`
log line that looks like success but has zero effect on computed values until the service is
restarted; the `_on_feature_config_reload()` SIGUSR1 handler is even more clearly a no-op — it only
logs receipt. This is a systemic, pre-existing gap for every `feature.*` key (not introduced by
Phase 163), but this phase adds 8 new operator-tunable dials (`feature.session_vp.value_area_pct`,
`.n_buckets`, `.hvn_threshold`, `.lvn_threshold`, `.rolling_window`, `feature.sr.window`,
`.cluster_atr_mult`, `.lookback_by_tf`) that inherit it silently, without any comment noting a
restart is required.
**Fix:** Either wire `_handle_config_update()` to rebuild `self._feature_factory_config` when a
`feature.*` key changes (a `dataclasses.replace()` call would suffice given the frozen dataclass),
or add an explicit log/comment at the new APR keys' seed sites (migration 255, `_THRESHOLD_KEYS`)
noting these require a service restart to take effect, so operators tuning them via the dashboard
aren't misled by the "reloaded" log line.

## Info

### IN-01: `threshold.backfill.coverage_threshold` key name mismatch — seeded config is dead code

**File:** `services/backfill_feature_factory.py:769`
**Issue:** `run_compute_stage()` reads `cfg.get_sync("threshold.backfill.coverage_threshold", 0.80)`,
but the only APR key ever seeded for this purpose (migration 153) and prewarmed in
`feature_vector_pipeline.py:508` is `threshold.backfill.coverage_gate` — a different key name.
Since the two names never match, this call always falls through to the hardcoded 0.80 default; any
operator/dashboard edit to `threshold.backfill.coverage_gate` is silently ignored by the backfill
coverage gate. Pre-existing (not part of this phase's diff), but directly in a function this
phase's own tests exercise (`test_compute_resume_skips_complete_pairs`).
**Fix:** Rename the read to `threshold.backfill.coverage_gate` (or vice versa) so the seeded value
is actually consulted.

### IN-02: `feature.sr.lookback_by_tf` has no `"4h"` entry despite `4h` being a live pipeline timeframe

**File:** `production/migrations/255_vp_structural_primitives.sql:211-216`, `src/intelligence/feature_factory.py:502-504`
**Issue:** `FeatureVectorPipeline._STANDARD_TFS` includes `"4h"`, but
`feature.sr.lookback_by_tf`'s seeded/default value (`{"1m":60,"5m":60,"15m":80,"1h":120,"1d":60}`)
has no `"4h"` key, so `_compute_sr_dist_atr()`'s `.get(tf, 120)` silently falls back to the generic
120-bar default for 4h S/R. Not incorrect, just an unconfigured tunable — matches the pre-existing
`_CTF_HIGHER_TF` mapping's same 4h gap, so likely intentional, but worth an explicit entry for
clarity and independent tunability.
**Fix:** Add an explicit `"4h": <value>` entry (e.g. 90, interpolating between 1h's 120 and 1d's 60)
to the seeded JSON and dataclass default.

### IN-03: `sr_level_count` fallback unnecessarily coupled to ATR validity

**File:** `src/intelligence/feature_factory.py:3264-3272`, `:3348-3350`
**Issue:** `_compute_sr_dist_atr()` returns the entire `_SR_FALLBACK` dict (including
`sr_level_count=0.0`) whenever `atr_val` is not yet valid, even though counting pivot clusters has
no ATR dependency by definition (only the *distance* fields need ATR normalization). This slightly
overstates "zero clusters found" during ATR cold-start when clusters could genuinely exist. Benign
in practice since the ATR and S/R warm-up windows overlap almost entirely, but conflates two
unrelated cold-start conditions in one fallback path.
**Fix:** Compute `sr_level_count` (and cluster detection generally) independently of `atr_valid`,
falling back only the ATR-normalized distance/strength fields when ATR is unavailable.

---

_Reviewed: 2026-07-23T20:43:49Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
