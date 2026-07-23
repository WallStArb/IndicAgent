---
status: pending
priority: P2
filed: 2026-07-22
source: Phase 148-05 (OOS Gate 2 execution) -- discovered while root-causing a 1e-6 tolerance
  failure reproducing the frozen 143.1-08-SHADOW-VALIDATION.md champion baseline; coordinator
  identified the correct fix and explicitly flagged the broader class of bug as worth a
  separate sweep, not blocking Phase 148.
---

# Path-dependent (order-sensitive) statistics over frame-level data silently non-reproducible when rows share a timestamp

## Problem

`scripts/analysis/score03_gate2_execution_eval.py`'s pooled `c4_max_dd` (max drawdown ratio)
failed to reproduce the frozen `143.1-08-SHADOW-VALIDATION.md` section 7 champion baseline
(`9.598299843093644`) within the plan's 1e-6 tolerance -- it came back `9.597283167649175`
on the first real attempt, a ~0.001 absolute difference (four orders of magnitude past
tolerance), despite `alpha_frames.measured_at` confirming the underlying data was byte-identical
to what 143.1-08 measured (all 33,892 champion OOS rows are the same untouched 2026-07-21 batch).

Root cause: the champion OOS population has massive same-`bar_ts` tie density -- 33,892 rows
across only 1,534 distinct `bar_ts` values (~22-way ties, cross-sectional over the active
universe at each 5-minute bar). `_max_drawdown()` computes a cumulative-sum equity walk over
`ORDER BY bar_ts ASC`-fetched rows with no secondary tie-break; TimescaleDB's parallel scan
across 1,034 child chunks does not guarantee stable row interleaving for tied sort keys across
separate executions, so the exact sequence fed into this path-dependent (order-sensitive)
statistic silently varies run-to-run on unchanged data. The frozen baseline itself was produced
by the identical unordered query in `phase143_1_08_shadow_validation.py` -- meaning that cited
number was never a reproducible ground truth, just whatever chunk-scan interleaving Postgres
happened to use on 2026-07-21.

An initial fix attempt (deterministic `frame_id` row-level tie-break) made the query
reproducible but was structurally wrong: same-`bar_ts` frames are genuinely SIMULTANEOUS
positions (multiple symbols opened at the identical bar), not sequential ones -- a row-by-row
cumulative sum over ANY row ordering treats concurrent positions as sequential, which is not
economically meaningful regardless of which arbitrary order is chosen. The correct fix
(shipped in 148-05, commit `51a05f10`) aggregates (SUMs) `counterfactual_pnl_r` per distinct
`bar_ts` BEFORE the cumulative walk, producing one value per timestamp so the walk is both
deterministic and economically correct. Verified reproducible (`9.596266492204732` across
independent runs, ~1e-15 float-summation noise) and confirmed the substantive gate verdict is
unaffected under all three numbers tested (max drawdown is catastrophically >900% regardless).

**A second, related but distinct symptom surfaced during the same investigation, NOT yet
fixed:** the regime-stratified companion's `long/mid_neutral` cell (`n_clusters=7`,
`coverage=insufficient`, so excluded from the aggregate pass/fail verdict) showed its
`ci_lower` drift across independent runs even AFTER the `c4` fix landed
(`-0.006660639938119944` baseline -> `-0.006587583828354219` -> `-0.006455963676706368` ->
`-0.006707268...` across four separate invocations, no two matching). This is `evaluate_frame_gate`
/`frame_gate_passes` in `services/counterfactual_tracker.py`: `cluster_members` is built as a
plain dict via `cluster_members.setdefault(cluster_id, []).append(pnl)` iterating rows in fetch
order, then `cluster_means = np.array([... for values in cluster_members.values()])` --
Python dict iteration follows INSERTION order, so the array fed into `scipy.stats.bootstrap`'s
BCa resampling (seeded with a FIXED `bootstrap_random_state`) has an order that depends on row
fetch order. A fixed-seed bootstrap draws specific index positions; the same *set* of cluster
means at different array positions produces a different specific resample sequence, hence a
different numeric CI, even though the day-level mean values themselves are order-independent
sums. The two cells that DO count toward the aggregate verdict (`mid_bull` long/short,
`n_clusters=37`/`23`) matched exactly across every run in this investigation -- plausibly
because their larger cluster counts make the array-order effect wash out, or because dict
insertion order for well-populated cells happens to track ascending `bar_ts`/day order
regardless of intra-day tie order (unconfirmed, not investigated further). This did NOT affect
Phase 148's Gate 2 verdict (the drifting cell is excluded from the pass/fail aggregation by its
own `coverage=insufficient` status), but it means `frame_gate_passes`/`evaluate_frame_gate` --
a SHARED function with multiple callers across the codebase (143.1-08's original validation,
Gate 2's regime companion, and any future caller) -- can silently produce non-reproducible CI
values for any cell whose cluster-mean array happens to be order-sensitive at a given seed.

## Fix

Not scoped in detail here (this is a capture, not a plan). Two candidate directions, likely
both warranted:

1. **Broader sweep for other path-dependent (order-sensitive) statistics over frame-level
   data.** `_max_drawdown`-shaped bugs (any computation whose result depends on row sequence,
   not just row set) could exist elsewhere in the codebase wherever `alpha_frames` or similar
   multi-symbol-per-timestamp tables feed a cumulative/sequential statistic without an explicit
   same-timestamp aggregation step. Grep for `np.cumsum`/`cumulative`/equity-curve-shaped
   computations reading from `alpha_frames` or `market_data_ohlcv` joins with multi-symbol
   cross-sectional ties, and audit each for the same "concurrent-treated-as-sequential" flaw.
2. **`frame_gate_passes`'s cluster-mean array construction determinism.** Either (a) sort
   `cluster_members` by `cluster_id` before building the `cluster_means` array (cheap,
   guarantees deterministic day-order regardless of row fetch order, matches the "aggregate
   first, order deterministically second" pattern this todo's `c4` fix already established), or
   (b) accept that bootstrap CI values for `coverage=insufficient` cells are inherently noisy at
   low cluster counts and are already correctly excluded from any pass/fail decision -- but (a)
   is cheap and removes a real, currently-live non-reproducibility source from a function with
   multiple callers, so should be preferred over accepting it.

## Sizing

Small for item 2 (a one-line sort added to `frame_gate_passes`/`evaluate_frame_gate`, plus a
regression test asserting cluster-mean array order is independent of input row order). Sizing
for item 1 (the broader sweep) is unknown until the grep/audit pass is actually run -- could be
zero additional findings, or could surface something more consequential elsewhere.

## References

- `.planning/phases/148-alpha-scoring-system-planned/148-05-PLAN.md` -- the plan this was
  discovered during
- `docs/plans/2026-07-22-phase148-promotion-decision.md` -- documents this finding and its
  resolution in the Gate 2 section
- `scripts/analysis/score03_gate2_execution_eval.py` commits `7e3c8913` (superseded
  frame_id-tie-break attempt), `51a05f10` (correct per-bar_ts aggregation fix),
  `92544222` (unrelated jsonb non-finite-float sanitization fix found in the same session)
- `services/counterfactual_tracker.py` -- `frame_gate_passes` (line ~172),
  `evaluate_frame_gate` (line ~906) -- the shared functions with the cluster-mean
  array-order-sensitivity symptom described above
- `.planning/phases/143.1-measurement-and-eligibility-integrity-fisher-z-ci-bootstrap-/143.1-08-SHADOW-VALIDATION.md`
  section 7 -- the frozen baseline whose `c4_max_dd` number this todo traces as non-reproducible
