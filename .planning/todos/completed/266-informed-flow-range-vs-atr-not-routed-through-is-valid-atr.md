---
status: completed
priority: P3
filed: 2026-08-05
closed: 2026-08-05
source: altitude review (/simplify) of todo 237's ATR floor consolidation
---

## Closed 2026-08-05

Fixed ahead of Phase 151 waves 6-7's corpus recompute (todo 259's backfill still in flight) so
the correct relative floor is baked into the recompute instead of needing a separate re-run
later. Both functions now take `close_`/`min_atr_pct` and delegate to `_is_valid_atr` internally
(`_range_vs_atr` gained a new required `close_` param it didn't have before); all 4 call sites
thread `config.atr_normalization_min_pct` through, same as todo 237's other 12 sites.
`_is_valid_atr`'s docstring updated to reflect both todo 237 and 266's consolidation. TDD: 6 new
tests in `TestInformedFlowRangeVsAtrFloor` (`tests/unit/test_feature_factory.py`), including the
BIL-style tiny-ATR-below-floor regression case for each function. Full `tests/unit/` suite green
(84/84 in the changed file), ruff/black clean.

`/simplify`'s 4-angle pass (reuse/simplification/efficiency/altitude) came back clean on 3 of 4;
altitude review surfaced a real sibling gap -- `_dist_from_high`/`_dist_from_low` (scalar + their
vectorized `_series_full` batch counterparts) are the same ATR-ratio shape, still on their own
absolute `eps=1e-10` epsilon, never routed through `_is_valid_atr`. Out of scope for this diff
(different call graph, vectorized numpy path, real behavior change) -- filed as
[268](268-dist-from-high-low-not-routed-through-is-valid-atr.md), `_is_valid_atr`'s docstring
updated to name it as the known remaining gap rather than overclaim full consolidation.

Independent correctness review (pr-review-toolkit:code-reviewer) confirmed: guard arguments
correct at all 4 call sites (verified `close_` vs `open_`/`prev_close_` scope, not just diff
context), `else 0.0` fallback preserved on guard failure, `compute()`/`compute_batch()` parity
holds (byte-identical argument tuples, `range_vs_atr` covered by `RENAISSANCE_PRIMITIVE_FIELDS`
parity test), no off-by-one/None/type issues, test arithmetic genuine (not a copy-paste
tautology despite both `0.0001` literals -- one is a fraction-of-close floor, the other an
absolute ATR value 91.7x below it). Zero findings at reportable confidence.

# `_informed_flow`/`_range_vs_atr` still use their own `atr > 1e-10` epsilon, not `_is_valid_atr`

## What

Todo 237 consolidated 12 ATR-normalized distance feature call sites in `feature_factory.py`
(session VP, S/R, swing/trend structure, fibonacci zones, session levels, all 6 SMC compute
functions) onto one shared `_is_valid_atr(atr_val, close_, min_atr_pct)` guard, gated by the new
APR key `feature.atr_normalization.min_atr_pct` (migration 294, seeded 1bp of close_).

Two more ATR-ratio features were NOT included in that consolidation, and remain on the
pre-todo-237 pattern: `_informed_flow` (`open_price`, `close`, `atr` -> `(close - open_price) /
atr`, `feature_factory.py:889`) and `_range_vs_atr` (`high`, `low`, `atr`, `eps=1e-10` ->
`(high - low) / atr`, `feature_factory.py:1067`). Both gate on their own inline `atr > 1e-10`
absolute epsilon, called at 4 sites (`feature_factory.py:6806`, `6904`, `7328`, `7620`) inside
`compute()`/`compute_batch()`.

`1e-10` is an absolute floor, not relative to price -- for a low-priced or ultra-flat instrument
(the same BIL-style scenario todo 237 fixed for the other 15+ columns), an ATR well above 1e-10
but still tiny relative to close_ passes this gate uncaught, and `informed_flow`/`range_vs_atr`
can still explode the same way `weekly_r1_dist_atr` did pre-fix.

## Why not fixed as part of todo 237

Found during `/simplify`'s altitude review of todo 237's diff, not during todo 237's own
investigation -- these two functions were out of that diff's reviewed scope (never touched,
different file region, no shared call graph with the 12 consolidated sites). Routing them
through `_is_valid_atr` would change their live output for every bar (tightening the gate from
an absolute 1e-10 to a relative `min_atr_pct * close_` floor) and touch call sites the reviewed
diff never modified -- a real behavior change, not a same-diff cleanup.

## Fix

Route both functions through `_is_valid_atr(atr, close_ or open_price, config.atr_normalization_min_pct)`
in place of their own inline epsilon, at all 4 call sites. `_informed_flow` and `_range_vs_atr`
don't currently take a `close_` parameter for the relative-floor calculation -- `_informed_flow`
already has `close` in scope; `_range_vs_atr` would need `close_` threaded in alongside `high`/
`low` (the caller has it at all 4 sites already). Update `_is_valid_atr`'s own docstring (currently
says "NOT YET used by every ATR-ratio feature... todo 266 tracks routing them through this same
gate") once this lands.
