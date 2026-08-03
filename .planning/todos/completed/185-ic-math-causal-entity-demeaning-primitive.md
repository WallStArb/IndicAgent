---
status: closed
priority: P1
filed: 2026-07-26
closed: 2026-07-26
source: /simplify altitude review of scripts/analysis/nonlinear_interaction_combiner_lightgbm_check.py
---

# `ic_math.py` has no causal per-entity (per-symbol) demeaning primitive — every future pooled-panel test will hit the same drift-leak bug nonlinear_interaction_combiner just caught

**CLOSED 2026-07-26.** Added `causal_entity_expanding_mean(entity_ids, values, min_periods)` to
`src/intelligence/statistics/ic_math.py`, immediately after `build_walk_forward_folds`. Pure
numpy (no pandas import — matches this module's existing pure-function/no-new-dependency
convention), operates on pre-sorted `(entity, time)` arrays per the module's established
no-hidden-reordering discipline.

5 unit tests in `tests/unit/test_ic_math_causal_entity_demean.py`, all passing:
- Matches an independently-derived pandas `groupby().shift(1).expanding(min_periods=...)`
  reference implementation exactly (not self-consistency — a real second implementation).
- Causal: truncating the series after row i doesn't change row i's own mean (no look-ahead).
- Never includes its own row's value (outlier-at-row-3 test: row 3's mean is unaffected by
  its own outlier value; row 4's mean correctly reflects it).
- `min_periods` warmup correctly returns NaN, not a spurious zero-filled mean.
- Multi-entity isolation: one entity's values never leak into another's mean regardless of
  array ordering.

No regressions: full existing `ic_math.py` test suite
(`test_ic_math_walk_forward_folds.py`, `test_ensemble_ic_math.py`,
`test_ic_math_guard_fraction.py`) still green.

**Not yet done, deliberately out of scope for this todo:** migrating
`nonlinear_interaction_combiner_lightgbm_check.py`'s own inline demeaning to call this new primitive
instead of its ad hoc `df.groupby(...).shift(1).expanding(...)` — the script's own version is
correct and already tested via the canary-leakage check (todo 184); swapping it to call the
new shared primitive is a trivial follow-up, not blocking, and safe to do opportunistically
next time that script is touched.

## Original finding (unchanged)

Building the nonlinear_interaction_combiner (non-linear combiner) falsification test, a naive pooled-training result showed
IC=0.30 with 80/80 symbols passing — ~3x anything else measured in this corpus. Investigation
found the cause: some ETFs simply have a persistently different long-run average return than
others across the whole 20-year sample (train/test half-correlation of per-symbol mean
`return_fast` = 0.27). A 147-feature LightGBM model can implicitly recognize "this row's
signature looks like ARKK" and predict ARKK's known-good long-run drift — correlating with
actual returns for a reason that has nothing to do with genuine bar-level signal. Exactly the
"factor exposure in disguise" failure mode `docs/research/trade-construction-layer.md`'s
validation gate #2 ("Attribution honesty") already pre-registered.

## References

- `src/intelligence/statistics/ic_math.py` — `causal_entity_expanding_mean`, the new primitive
- `tests/unit/test_ic_math_causal_entity_demean.py` — its test suite
- `scripts/analysis/nonlinear_interaction_combiner_lightgbm_check.py` — the inline fix this generalizes
- `docs/research/trade-construction-layer.md` — validation gate #2 ("Attribution honesty")
