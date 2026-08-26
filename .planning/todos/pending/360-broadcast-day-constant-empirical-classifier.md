---
status: pending
priority: P2
filed: 2026-08-26
source: Todo 354's implementation session -- live DB verification caught a scope bug before
  it shipped, this todo is the proper long-term fix for the narrowed scope that replaced it
---

# Build an empirical "day-constant" classifier for broadcast features, replacing todo 354's
# hardcoded 3-name `_TEMPORAL_BROADCAST_FEATURE_NAMES` allowlist

## What

Todo 354 fixed temporal pseudo-replication (a daily-cadence macro value duplicated across
every intraday bar, inflating N ~78x/26x/6.5x at 5m/15m/1h) for exactly three features:
`vix_z`/`yield_slope_z`/`flight_quality`. The fix's day-decimated measurement path
(`_compute_one_symbol_broadcast_cell`, `services/ic_engine.py`) is gated by a new module
constant, `_TEMPORAL_BROADCAST_FEATURE_NAMES = frozenset({"vix_z", "yield_slope_z",
"flight_quality"})` -- a small, hand-written, explicitly-documented allowlist, not derived
from any live classifier.

**Why not just reuse Phase 173's `broadcast_features` (concept_registry's `broadcast=true`
flag, ~38 features as of 2026-08)?** That was the original plan (and the todo 354 filing's own
"Proposed fix" section explicitly suggested it) -- caught wrong via live DB verification before
shipping. `broadcast=true` means "constant across SYMBOLS at a given bar_ts" (Phase 173's
cross-sectional invariance), a DIFFERENT property from "constant across TIME within one
symbol's own trading day." Spot-checked directly against real `feature_vectors` data
(AAPL/5m, 2024-06-03, 78 bars): `vix_z`/`yield_slope_z`/`flight_quality` each had exactly 1
distinct value across the day (as expected), but `hour_of_day_cos` (also `broadcast=true`) had
78 distinct values -- genuinely intraday-varying, as its name implies. Using the full set would
have either silently dropped real per-bar signal from `_compute_one_regime_cell` or crashed
`_compute_one_symbol_broadcast_cell`'s within-day invariance guard outright on live data.

Several other `broadcast=true` features also happened to be day-constant in that one
spot-check (`dow_sin`, `amd_phase`, `in_ny_session`), but for reasons that don't generalize:
`dow_sin` is a pure calendar-date function (day-constant by construction, no bug to fix);
`amd_phase`/`in_ny_session` were constant only because that specific sample's `feature_vectors`
rows already excluded non-trading-hours bars, not because they're inherently day-constant. A
single spot-check on one symbol/day does not establish day-constancy across the full 231-symbol
corpus, and accidentally widening the allowlist without real evidence risks the exact wrong-scope
bug this todo exists to prevent from recurring.

## Proposed fix

Mirror `scripts/ops/alpha/ops_broadcast_feature_audit.py`'s existing empirical-classifier
pattern (Phase 173 Plan 01), but measure WITHIN-DAY variance instead of CROSS-SYMBOL variance:
for each `broadcast=true` feature, compute `max - min` across all bars of the same calendar day
(same statistic `_compute_one_symbol_broadcast_cell`'s own invariance guard already computes at
compute time), aggregated across a representative sample of (symbol, tf, day) triples. Write the
result as a new `concept_registry.metadata` flag (e.g. `daily_cadence: true`) via the same
migration-seeded, offline-detector-plus-compute-time-assertion pattern Phase 173 already
established (`alpha.ic.broadcast_variance_threshold`, migration 324 -- reuse the SAME shared
epsilon, not a new one, unless the two properties turn out to need different tolerances).
`_compute_symbol_tf`'s broadcast_mask construction then becomes `broadcast_features &
daily_cadence_features` instead of `broadcast_features & _TEMPORAL_BROADCAST_FEATURE_NAMES`,
and the hardcoded constant can be deleted.

## Scope

Not urgent: the 3-name allowlist is correct and safe as far as it's been verified (empirically
checked, not assumed), just narrower than it eventually could be -- `hyg_lqd_ret_z`/
`tip_tlt_ret_z`/`sb_corr_*` (cross-asset return ratios) are plausible candidates for also being
day-constant but were NOT verified either way and must not be added to the allowlist without
the same empirical rigor. Real, scoped classifier-building work, not a quick list edit.
