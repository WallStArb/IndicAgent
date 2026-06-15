---
phase: 125-apr-full-migration-all-three-tiers
reviewed: 2026-06-15T09:00:00Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - production/migrations/132_phase125_param_store.sql
  - src/intelligence/trading/anchored_vwap_reversion.py
  - src/intelligence/trading/cis_scorer.py
  - src/intelligence/trading/confidence_utils.py
  - src/intelligence/trading/gap_analysis_setup.py
  - src/intelligence/trading/mean_reversion.py
  - src/intelligence/trading/momentum_breakout.py
  - src/intelligence/trading/squeeze_expansion.py
  - src/intelligence/trading/vwap_reclaim.py
  - tests/unit/intelligence/test_param_store_migration.py
findings:
  critical: 3
  warning: 5
  info: 3
  total: 11
status: issues_found
---

# Phase 125: Code Review Report

**Reviewed:** 2026-06-15T09:00:00Z
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Phase 125 wires six I7 plugins and CIS scorer to ConfigService and seeds 10 new APR keys
via migration 132. The migration and prewarm list pattern are consistent and the
`_validate_weights_sum` utility is correctly implemented. Three blockers were found: two are
a single root cause (wrong asset-class suffix names propagated from the migration through the
pipeline prewarm list), and one is hardcoded empty strings for symbol/timeframe/timestamp in
SqueezeExpansionPlugin. Five warnings cover volume-baseline bias, a confidence-score formula
that diverges from its live gate threshold, missing `shadow_only` declarations, and zero test
coverage of the new APR paths.

---

## Critical Issues

### CR-01: Zone-width APR keys use wrong asset-class suffixes -- dead configuration

**Files:** `production/migrations/132_phase125_param_store.sql:25-30`,
`services/intelligence_pipeline.py:448-450`

**Issue:** Migration 132 seeds asset-class-specific zone-width keys using suffixes `.equity_etf`
and `.forex`:

```sql
('feature.zone_engine.min_zone_width_atr.equity_etf', 'float', '1.5', ...)
('feature.zone_engine.min_zone_width_atr.forex',      'float', '1.0', ...)
```

The pipeline prewarm list (`_THRESHOLD_KEYS`) preloads those same wrong names. The consuming
code in `trade_framer._min_zone_width_atr()` builds the APR key from
`AssetClass.value` which is defined as `"equity"` and `"fx"` (verified in
`src/core/models.py`):

```python
return _cfg(f"feature.zone_engine.min_zone_width_atr.{asset_class}", default)
# resolves to: feature.zone_engine.min_zone_width_atr.equity
# resolves to: feature.zone_engine.min_zone_width_atr.fx
```

The keys `...equity_etf` and `...forex` will never be found. Both asset classes silently
fall back to the universal default (1.5 ATR). The FX-specific threshold of 1.0 ATR -- the
only value that differs -- is permanently dead until the names are corrected.

The correct keys are seeded by the concurrent `132_phase126_apr_seeds.sql` (which uses
`.equity` and `.fx`) but they are NOT added to `_THRESHOLD_KEYS`, so they are not
prewarmed and will hit the DB on the hot path each call.

**Fix:** In the migration, rename the suffixes and update `_THRESHOLD_KEYS`:

```sql
-- migration fix
('feature.zone_engine.min_zone_width_atr.equity', 'float', '1.5', ...)
('feature.zone_engine.min_zone_width_atr.fx',     'float', '1.0', ...)
```

```python
# intelligence_pipeline.py _THRESHOLD_KEYS fix
("feature.zone_engine.min_zone_width_atr.equity",  1.5),
("feature.zone_engine.min_zone_width_atr.fx",      1.0),
("feature.zone_engine.min_zone_width_atr.futures", 1.5),
```

Note: `132_phase126_apr_seeds.sql` already seeds the correct keys; the Phase125 migration
seeds become redundant dead rows and should be dropped or updated via a follow-on migration
(`DELETE FROM config_state WHERE config_key IN ('...equity_etf', '...forex')`).

---

### CR-02: SqueezeExpansionPlugin passes hardcoded empty strings for symbol, timeframe, timestamp

**File:** `src/intelligence/trading/squeeze_expansion.py:184-187`

**Issue:** The call to `make_signal_from_frame()` passes literal empty strings:

```python
return make_signal_from_frame(
    tf,
    symbol="",        # hardcoded -- should be frames.get("symbol", "")
    timeframe="",     # hardcoded -- should be features.get("timeframe", "")
    timestamp="",     # hardcoded -- should be features.get("timestamp", "")
    ...
)
```

Every other plugin in scope (and all reviewed peers: `gap_analysis_setup.py:217`,
`momentum_breakout.py:189-191`, `vwap_reclaim.py:269-271`) extracts these from
`frames`/`features`. The blank values propagate into the signal dict and from there into
`signal_events` DB rows and any Kafka consumer that reads `symbol` or `timeframe` from the
signal. Downstream lifecycle tracking (TTL expiry, performance attribution, backtesting
attribution) will be silently broken for all `trad_SqueezeExpansion` signals.

The plugin is currently `shadow_only=True`, so this does not corrupt live trades, but it
corrupts ML training data and shadow performance statistics.

**Fix:**

```python
return make_signal_from_frame(
    tf,
    symbol=frames.get("symbol", "") or frames.get("__symbol__", ""),
    timeframe=features.get("timeframe", ""),
    timestamp=features.get("timestamp", ""),
    ...
)
```

---

### CR-03: Duplicate migration number 132 creates ambiguous migration state

**Files:** `production/migrations/132_phase125_param_store.sql`,
`production/migrations/132_phase126_apr_seeds.sql`

**Issue:** Two migration files share the prefix `132_`. The migration runner
(`production/scripts/db_setup.sh:27`) applies all files matching `[0-9][0-9][0-9]_*.sql`
in shell glob order. Both files will be applied but their ordering is determined by
alphabetical sorting of the filename suffix (`phase125...` before `phase126...`), not by
intent. This is fragile and violates the migration numbering invariant -- migration numbers
are the sole ordering key and must be unique.

Additionally, `132_phase126_apr_seeds.sql` was meant to be a Phase 126 migration but
carries a 132 prefix, causing it to be applied during Phase 125 setup. When Phase 126 is
executed, operators who check "which migrations to apply" will not find a 133-series file
for the zone-width gate (the correct Phase 126 migration already ran under 132).

**Fix:** Rename `132_phase126_apr_seeds.sql` to `133_phase126_apr_seeds.sql` (or the next
available number after 133, which is already taken by `133_phase126_mean_reversion.sql`).
If 133 is taken, use 134. Then update `_THRESHOLD_KEYS` to prewarm the keys at the correct
version boundary. Add a migration invariant check to CI.

---

## Warnings

### WR-01: geo_score in GapAnalysisSetup hardcodes 0.8 instead of using the live APR gate

**File:** `src/intelligence/trading/gap_analysis_setup.py:168`

**Issue:** The APR gate threshold is correctly read into `min_gap_atr` from ConfigService.
The gate itself is applied at line 132. However, the `geo_score` formula on line 168 still
hardcodes `0.8`:

```python
geo_score = clamp01((gap_size_atr - 0.8) / 1.7)
```

If an operator changes `threshold.gap_analysis.min_gap_atr` to, say, 1.2, the gate filters
correctly but `geo_score` still computes to `(gap_size_atr - 0.8) / 1.7`. A signal that
barely clears the 1.2 gate would score `(1.2 - 0.8) / 1.7 = 0.235` instead of `0.0`. The
confidence score and the emission gate diverge, giving inflated confidence on signals that
just barely pass the more-restrictive gate.

**Fix:**

```python
# Use min_gap_atr (already loaded from APR) as the zero-point
_geo_range = 1.7  # span from gate to max-confidence (keep as local or APR key)
geo_score = clamp01((gap_size_atr - min_gap_atr) / _geo_range)
```

---

### WR-02: vwap_reclaim volume fallback includes current bar in baseline mean

**File:** `src/intelligence/trading/vwap_reclaim.py:175`

**Issue:** When `rel_volume` is absent, the fallback path computes:

```python
avg_vol = float(df["volume"].mean())
```

This includes the current bar's volume in the average. On the cross bar -- which is the bar
where the signal fires and which is likely the high-volume bar driving the cross -- the
inflated average makes `vol_ok` harder to pass, causing false rejections. Compare with
`gap_analysis_setup.py:140` which correctly excludes the current bar: `np.mean(vol[-21:-1])`.

**Fix:**

```python
avg_vol = float(df["volume"].iloc[:-1].mean()) if len(df) > 1 else float(df["volume"].mean())
```

---

### WR-03: momentum_breakout vol_sma includes current bar in 20-bar window

**File:** `src/intelligence/trading/momentum_breakout.py:117`

**Issue:** The volume SMA used to compute `volume_ratio` is:

```python
vol_sma = float(np.mean(volume[-20:])) if len(volume) >= 20 else float(np.mean(volume))
```

`volume[-20:]` includes the current bar. On the breakout bar (high volume), the elevated
current volume inflates `vol_sma`, which reduces `volume_ratio` and makes the gate harder
to pass. Unlike `vwap_reclaim`, this is the only path (no feature fallback), so it affects
all evaluations.

**Fix:**

```python
vol_sma = float(np.mean(volume[-21:-1])) if len(volume) >= 21 else float(np.mean(volume[:-1]))
```

---

### WR-04: AnchoredVWAPReversionPlugin and SqueezeExpansionPlugin missing shadow_only

**Files:** `src/intelligence/trading/anchored_vwap_reversion.py`,
`src/intelligence/trading/squeeze_expansion.py`

**Issue:** Every other reviewed Phase 125 plugin (`gap_analysis_setup.py:63`,
`momentum_breakout.py:42`, `vwap_reclaim.py:56`, `mean_reversion.py:52`) declares
`shadow_only: bool = True`. Intelligence CLAUDE.md states this is mandatory for all new I7
plugins. `AnchoredVWAPReversionPlugin` and `SqueezeExpansionPlugin` omit the field
entirely, which means they default to `False` at the dataclass level. `validate_tier()`
does not check for this, so there is no startup-time gate.

If the shadow governance promotion loop reads `shadow_only` from the plugin to decide
whether to forward signals to live execution, these two plugins would be incorrectly
eligible for live promotion before any shadow-mode performance data exists.

**Fix:** Add `shadow_only: bool = True` to both dataclasses.

---

### WR-05: No test coverage for any Phase 125 APR code paths in the new plugins

**File:** `tests/unit/intelligence/test_param_store_migration.py`

**Issue:** The test file covers pre-existing getters (`get_min_regime_weight`,
`get_min_ctf_score`, volume_profile, aggregator, zone_engine) and `_validate_weights_sum`.
None of the following new Phase 125 APR paths have test coverage:

- `cis_scorer.set_config_service()` and gate constant reads
- `anchored_vwap_reversion._config_service` weight injection and `_validate_weights_sum` call
- Any of the six Tier B plugin `compute_full()` paths verifying that APR values are actually
  used (not just that fallbacks work)
- `_validate_weights_sum` called under `cfg is None` (i.e., the config path is exercised,
  not just the module-level function directly)

If the `if cfg else` branch on any plugin inverts or gets removed, no test catches it.

**Fix:** Add at minimum:
1. `test_cis_scorer_reads_gate_from_config()` -- inject mock ConfigService, verify direction=0 when threshold raised above score.
2. `test_anchored_vwap_weights_sum_validation()` -- inject mock returning bad weights, verify ValueError.
3. One smoke-path test per plugin verifying that `_config_service` injection changes a computed threshold.

---

## Info

### IN-01: Duplicate `tol:` parameter doc line in `_validate_weights_sum`

**File:** `src/intelligence/trading/confidence_utils.py:70-71`

**Issue:** The docstring has the `tol:` parameter documented twice with slightly different wording:

```python
        tol:     Floating-point tolerance. Default 1e-6 handles float repr of 0.40+0.35+0.25.
        tol:     Floating-point tolerance (default 1e-6 handles 0.40+0.35+0.25).
```

**Fix:** Remove line 71 (the shorter duplicate).

---

### IN-02: mean_reversion.py references migration 133 in inline comment but is seeded there

**File:** `src/intelligence/trading/mean_reversion.py:100`

**Issue:** The comment `# APR key: threshold.mean_reversion.trend_regime_max (migration 133)`
is technically accurate (migration 133 does seed that key), but the code reads this key
without a `_THRESHOLD_KEYS` entry in the pipeline prewarm list. The key is loaded lazily on
every bar processed rather than prewarmed at startup.

**Fix:** Add `("threshold.mean_reversion.trend_regime_max", 0.2)` to `_THRESHOLD_KEYS` in
`services/intelligence_pipeline.py`.

---

### IN-03: `BOOTSTRAP_WEIGHTS` alias in cis_scorer.py is deprecated but still exported

**File:** `src/intelligence/trading/cis_scorer.py:68`

**Issue:**

```python
BOOTSTRAP_WEIGHTS = _CONFIG_UNAVAILABLE_FALLBACK  # deprecated: use _CONFIG_UNAVAILABLE_FALLBACK
```

The deprecated alias is module-level and therefore exported. Any code that imports
`BOOTSTRAP_WEIGHTS` directly will not get a deprecation warning. Given the migration to APR,
this alias should be removed rather than silently kept.

**Fix:** Remove the `BOOTSTRAP_WEIGHTS` line. Do a grep sweep to confirm no callers remain
(`grep -r "BOOTSTRAP_WEIGHTS" src/ tests/`).

---

_Reviewed: 2026-06-15T09:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
