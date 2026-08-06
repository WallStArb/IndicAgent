---
status: pending
priority: P2
filed: 2026-08-02
source: throughput brainstorm following todo 215 -- todo 215 already falsified batching
  and landed threading (~1.3x, capped by 24-core contention); this is the remaining
  algorithmic lever on the same hot path
---

## Status update 2026-08-05

**Step 1 (design decision) RESOLVED**: grepped every downstream consumer of
`ic_ci_lower`/`ic_ci_upper` (`ensemble_trainer.py`'s significance clause,
`alpha_publisher.py`'s direction-aware gate, `counterfactual_tracker.py`'s exit
condition, `cross_sectional_spread_tracker.py`'s bootstrap CI gate). Every single
one reads the CI as a threshold/sign gate (`> 0`, `< 0`, `> cost_hurdle`) --
never an exact value compared run-to-run. Bit-identical reproducibility across
different resample counts is NOT load-bearing for this CI. A documented
tolerance is an acceptable replacement invariant.

**Implementation DONE**: `_blocked_bootstrap_ci`/`_subsample_and_rank` now take
5 new `bootstrap_early_stop_*` params (migration 298:
`alpha.ic.bootstrap_early_stop.{enabled,check_interval,tol,min_resamples,
stable_checks}`), **seeded disabled** -- same "off by default, flipping on is a
separate deploy decision" pattern as `alpha.hmm.walk_forward.enabled`, so
landing this code changes zero existing CI values or gate decisions. When
enabled: computes in checkpoint-sized chunks, stops once the running ci_lower/
ci_upper estimate has changed by <= tol for `stable_checks` consecutive
checkpoints, never before `min_resamples`. The RNG invariant (`starts_matrix`
drawn once, full size, before the feature-block loop) is untouched -- early-stop
only changes how many already-drawn rows get the expensive rankdata/IC compute,
not the RNG draw itself.

New fields classified `COMPUTATIONAL` in `ic_engine.py`'s fingerprint
partition (caught by `test_computational_and_operational_fields_partition_
dataclass_exactly` -- correctly, since enabling this changes ci_lower/ci_upper,
unlike the output-invariant thread-count fields). 5 new tests added
(`tests/unit/test_ic_engine_compute_split.py`) verifying: disabled path is
byte-identical to pre-todo-227 behavior; enabled path's early stop exactly
matches a truncated full computation (proving it's the same statistic, just
fewer resamples); stop never fires before `min_resamples`. Full
`tests/unit/` suite green, ruff/black clean.

**Still open, deliberately not done in this pass**: flipping
`alpha.ic.bootstrap_early_stop.enabled` on is a separate deploy decision
requiring its own corpus re-run to confirm no gate flips from the
approximation (same deferral discipline as todo 229's Viterbi verification).
`check_interval`/`tol`/`min_resamples`/`stable_checks` are `[initial_estimate]`
values, not benchmarked against real feature_vectors convergence data --
calibrate once real data exists, same backlog category as todo 226.

# `_blocked_bootstrap_ci`'s fixed 2000-resample count is a bigger lever than more
# threading, but it breaks the function's current bit-identical guarantee -- scope
# the tolerance change explicitly before touching code

## Problem

Todo 215 (`.planning/todos/completed/215-ic-engine-bootstrap-ci-vectorization.md`,
completed 2026-07-30) confirmed
`_blocked_bootstrap_ci`'s cost is dominated by `scipy.stats.rankdata`'s real O(n log n)
sort, not per-call dispatch overhead (batching was measured and falsified). Threading
landed a real ~1.3x win but is now core-contention-capped (8 `ic_engine` workers x 2
threads already near the 24-logical-core ceiling; todo 215 explicitly found threads=4/8
would regress via oversubscription, not improve).

The remaining lever is doing less total work: `alpha.ic.bootstrap_resamples` = 2000 is
fixed regardless of how quickly the CI's Monte Carlo standard error actually stabilizes.
Many cells likely converge well before 2000 resamples; a fixed count either wastes
compute on already-stable cells or (less likely, worth checking) under-resamples noisy
ones.

## Constraint -- this is the hard part, not the algorithm

`_subsample_and_rank`'s existing docstring guarantees the resample index matrix is
**bit-identical**, not approximately equal, across runs (verified: one batched
`rng.integers(..., size=(B, K))` call consumes the RNG stream identically to B
sequential calls -- see todo 215's evidence). An adaptive/early-stopping resample count
inherently breaks this: the number of resamples drawn becomes data-dependent, so two
runs with different early-stop thresholds produce different N, different RNG stream
consumption, and a CI that is close but not bit-identical to the fixed-2000 baseline.

This is not a "just add an early-stop check" change -- it requires:
1. Deciding whether bit-identical reproducibility is actually load-bearing for this
   specific CI (as opposed to the HMM regime labels, which clearly are, per
   [[project_hmm_improvement_decisions]]) -- if IC confidence intervals are consumed
   downstream as a threshold gate (e.g. significance testing) rather than as an exact
   value compared run-to-run, a documented *tolerance* (e.g. CI bounds within 1e-4)
   may be an acceptable replacement invariant.
2. If tolerance is acceptable: design the stopping rule (e.g. stop once the running
   percentile estimate's Monte Carlo SE drops below some threshold, checked every K
   resamples to keep it vectorizable), and re-derive whatever unit tests currently
   assert exact reproducibility (`test_subsample_and_rank_threaded_matches_serial` and
   any sibling test asserting bit-identical resample counts).
3. If bit-identical reproducibility is NOT negotiable: this todo is closed as "not
   viable," and threads=2 (todo 215's landed value) is the ceiling on this path.

## What to do

Start with step 1 above -- a design decision, not code. Check what actually consumes
IC confidence intervals downstream (`ic_shrinkage`? ensemble gating?) and whether any
consumer needs exact run-to-run reproducibility or just a stable-enough estimate.
Bring the answer back before writing any resample-count logic.

## Sizing

Design/decision step: small. Implementation, if approved: medium (new stopping-rule
code + new tolerance-based tests replacing the exact-match tests it obsoletes) +
requires a full corpus re-run to confirm no downstream regression.
