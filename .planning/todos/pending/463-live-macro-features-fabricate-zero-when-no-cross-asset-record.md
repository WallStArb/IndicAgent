---
status: pending
priority: P2
filed: 2026-09-29
source: 186 debt pass B5b (cross-asset no_fill)
---

# The live path writes 0.0 for macro features when no cross-asset record exists

## What

`services/feature_vector_pipeline.py::_cross_asset_record_for_date` returns `CrossAssetRecord()`,
all fields 0.0, when a date predates the earliest record or the series never loaded. The live
`FeatureFactory.compute()` then passes the values through `_guard` (`vix_z=_guard(vix_z)`,
`tip_tlt_ret_z=_guard(..., 0.0)` and the other macro fields), which replaces any non-finite
value with 0.0. The batch and rebuild path (`_macro_kernel_inputs`, 186-12 and 186-15) emits NaN
for the same situation and stores NULL. The two paths disagree, and the live one breaks
`no_fill` (a fabricated 0.0 z-score reads as a real reading).

Scope, stated precisely (pass C): the F9/B5a NaN takes effect only on the registry-kernel path
(`compute_kernels`, `_macro_kernel_inputs`). The legacy `_build_feature_vector` build path, used
by both `compute()` and `compute_batch()`, still wraps vix_z, flight_quality, yield_slope_z,
tip_tlt_ret_z, hyg_lqd_ret_z and sb_corr_fast/slow/z in `_guard(..., 0.0)`, and FeatureVector
fields are non-nullable floats, so a `compute_batch` row with no daily record yet persists 0.0,
not NULL. That includes today's batch backfills, not only the dormant live path. Pass C stopped
the products' `_guard_counted` tripwire from firing on the missing input (544 false counts on the
early rows of one test series) but left the substituted value at 0.0, and pinned the behavior with
`tests/unit/intelligence/test_legacy_featurevector_macro_fill.py`, named to fail when 186-25
changes it. 186-25 removes the `_guard(..., 0.0)` on these fields for the rebuild path and must
prove with a test that rebuilt early-history macro columns are NULL, not 0.0, in the feature
vectors table.

It was not fixed in pass B5 because making the record NaN alone changes nothing: `compute()` puts
the zero back, `FeatureVector` types the macro fields as `float`, and
`validate_feature_vector` (`feature_vector_persistence.py`) rejects a NaN field while accepting
None. Fixing it means deciding how a feature column is allowed to be missing.

## Options

1. Nullable macro fields. `FeatureVector` macro fields become `float | None`; `compute()` passes
   None through (no `_guard` fill) for the ten macro columns and the products derived from them
   (`yield_slope_momentum_product`, `vix_reversion_product`, `tip_tlt`-based ones); the record
   fallback returns None fields; the validator already accepts None and persistence writes NULL.
   Matches the rebuild's NULL. Touches every reader of those fields (`src/core/ml/features.py`
   already types some of them `float | None`).
2. Skip the bar. When no record exists the live path does not persist the bar's macro-dependent
   vector and increments a counted metric. Simple, but it drops the non-macro features of that
   bar, which contradicts "never drop data that could contain signal".
3. Keep 0.0 and mark it. A companion boolean column says the macro block was defaulted. Adds a
   column and every consumer must remember to read it; a fill with a flag is still a fill.

## Recommendation

Option 1, done together with the streaming path's revival (the live feed is down, so nothing
fabricated is being written today) and with a live-versus-rebuild parity test on the first rows
of a series. It is the only option that makes live and rebuild identical and keeps every feature
that is available. Until then the live path stays dormant; rows written by the legacy batch path before the 186-25
rebuild carry 0.0 for these columns on their early history, and the rebuild replaces them.

## Steps

1. Trace every reader of the ten macro fields and their products (ML feature list, dashboard,
   `ic_measure` NaN handling).
2. Implement option 1 behind a failing test: `compute()` with no record returns None macro fields.
3. Add the live-versus-rebuild parity test on rows before the first record.
