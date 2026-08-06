---
status: completed
priority: P3
filed: 2026-08-05
closed: 2026-08-05
source: /simplify reuse-angle review of todo 268's fix (_dist_from_high_series_full/
  _dist_from_low_series_full consolidation onto _is_valid_atr_series)
---

## Closed 2026-08-05

Reused the `atr_valid` mask already hoisted in `_precompute_series` (todo 268) rather than
recomputing `_is_valid_atr_series` again -- sliced to `_gap_z_series_full`'s own index alignment
(`atr_valid[1:1+gap_high]`, since `atr_for_gap[k] == atr_padded[k+1]`).

**Went further than the todo's original Fix section during `/simplify`'s altitude pass**: the
first version threaded `atr_valid` through but left `_gap_z_series_full` still independently
recomputing `atr_core` via its own `_atr_series_full(highs, lows, closes, period)` call -- a
real, literal duplicate of the already-computed `atr_raw` in `_precompute_series` (both use
`config.adx_period`), and a fragile "coincidental equivalence" between the mask and the values
it gated, undocumented-by-structure. Fixed at the right depth: `_gap_z_series_full`'s signature
now takes `atr_raw` directly (dropping `highs`/`lows`/`period`, which existed only to recompute
it), matching the pattern `_dist_from_high_series_full`/`_dist_from_low_series_full` already use
for `atr_padded`. Eliminates the redundant per-symbol/tf ATR computation entirely, not just the
guard-selection bug.

TDD: one test (`TestGapZAtrFloor`) comparing the function's output against a real
`_is_valid_atr_series`-derived mask vs. a literal `atr_padded > 1e-10` reproduction of the old
predicate -- caught a real design flaw during authoring (z-scoring is scale-invariant under a
uniform multiplier, so an initial all-proportional bar design produced identical floored/
unfloored output; redesigned with one position at ordinary ATR and one at BIL-style tiny ATR to
break the degenerate symmetry). Also caught, mid-session, an actual TDD violation: production
code was written before the test in the first pass at this fix -- reverted, test written and
verified RED, then the same fix reapplied as GREEN.

`/simplify`'s 4-angle pass: reuse and efficiency clean (confirmed no other `_series_full`
function still has an ad-hoc ATR epsilon guard -- this closes the sweep started by 266/268);
simplification caught the test using an atypical class-level-fixture pattern and duplicated
call boilerplate (fixed: local variables per this file's convention, merged into one test);
altitude caught the redundant-computation issue above (fixed, not deferred). Independent
correctness review (pr-review-toolkit:code-reviewer) ran a 400-case differential test old-vs-new
(max diff 0.0 on ordinary data, exact match at min_pct=0.0) confirming alignment; zero findings.
Full `tests/unit/` suite green (1287 passed), ruff/black clean.

This closes the ATR-floor sweep: 237 (12 original) -> 266 (2, informed_flow/range_vs_atr) -> 268
(2, dist_from_high/low, plus deleted 2 dead scalar siblings) -> 269 (gap_z, last remaining).

## What

`_gap_z_series_full` (`src/intelligence/feature_factory.py:2283`) computes `gap_z`
(ATR-normalized open gap, rolling z-scored) via `gap_raw = (opens[...] - closes[...]) /
atr_for_gap`, gated by its own absolute-epsilon guard: `np.where(atr_for_gap[:gap_high] >
1e-10, atr_for_gap[:gap_high], 1.0)` (line 2311-2313). Same ATR-ratio shape as the 14+2
features already consolidated onto `_is_valid_atr`/`_is_valid_atr_series` by todos 237, 266,
and 268 -- a legitimately-positive but numerically-tiny ATR relative to the gapping close_
passes uncaught and `gap_z` can explode the same BIL-style way.

## Why not fixed as part of todo 268

Found during `/simplify`'s reuse-angle review of todo 268's diff. Not a drop-in reuse of
`_is_valid_atr_series(atr_padded, closes, min_atr_pct)`: `_gap_z_series_full` computes its own
local ATR series (`atr_core = _atr_series_full(highs, lows, closes, period)`, independent of
the shared `atr_padded` other `_series_full` functions read from `_precompute_series`) with a
shifted/offset alignment (`atr_for_gap = atr_core[:-1]`, indexed against `opens[2:2+gap_high]`/
`closes[1:1+gap_high]` -- gap at position i normalized by ATR at position i-1, not i). Routing
this through `_is_valid_atr_series` needs the *close being gapped from* (`closes[1:1+gap_high]`,
not the padded array's own alignment) as the relative-floor reference, so it's a real, scoped
fix -- not a same-diff bolt-on -- and changes `gap_z`'s live output for every bar, same caution
todo 266/268 gave their own functions.

## Fix

Route `_gap_z_series_full`'s ATR guard through `_is_valid_atr_series(atr_for_gap[:gap_high],
closes[1:1+gap_high], config.atr_normalization_min_pct)` (correct close_ reference is the
pre-gap close, matching what the ratio is normalized against) in place of the inline
`atr_for_gap[:gap_high] > 1e-10`. Thread `config.atr_normalization_min_pct` into the function's
signature (currently takes `period`/`zscore_window` only, no `config`/`min_atr_pct` -- check its
one call site, `feature_factory.py:3490`-ish `gap_z=_gap_z_series_full(...)`, for what's already
in scope there). Same TDD/BIL-regression-test discipline as todos 266/268.

## Constraint

Batch into the next full corpus rebuild (todo 259's backfill -> Phase 151 waves 6-7), same as
todos 266/268 -- a real compute-output change that should land before, not after, the recompute.
