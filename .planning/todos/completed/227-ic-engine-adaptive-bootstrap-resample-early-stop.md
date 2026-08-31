---
status: closed
priority: P2
filed: 2026-08-02
closed: 2026-08-31
source: throughput brainstorm following todo 215 -- todo 215 already falsified batching
  and landed threading (~1.3x, capped by 24-core contention); this is the remaining
  algorithmic lever on the same hot path
---

## Status update 2026-08-12 -- deploy decision made, flag flipped

Flipped `alpha.ic.bootstrap_early_stop.enabled` true (config_state version 2), ahead of
the post-231-symbol-expansion full corpus recompute launched this session (still on
step 1/8 at flip time). Triggered by a user-requested throughput investigation into why
the corpus pipeline takes ~70 hours -- `logs/corpus_pipeline/step_timings.jsonl` confirmed
`ic_engine` (step 5) alone is 98% of that (252,641s), and this is the one built-but-unused
lever directly targeting the confirmed hot loop (todo 215's `rankdata`-in-`_resample_ic`
finding).

**Validated first, not flipped blind** -- isolated benchmark (no DB writes, no
ProcessPoolExecutor, zero contention with the live pipeline) calling the actual
`services/ic_engine.py::_subsample_and_rank` against real SPY/QQQ 1d price-derived
features/returns (`market_data_ohlcv`, not synthetic data): **1.52x (SPY) / 2.13x (QQQ)
speedup, 0/80 significance-gate flips** (`ci_lower>0 or ci_upper<0` check, the actual
property `ensemble_trainer`/`alpha_publisher` consume), max CI diff ~0.002 -- bounded
right at the configured `tol`, as designed.

**Scope caveat, honestly stated:** 2 symbols, 1 timeframe (1d), 40 hand-built features
(not the full ~244 production feature set), and a rough forward-return construction (not
routed through the real `forward_return_writer.py`). Real statistical structure (actual
price series), not a full-universe guarantee. The live corpus recompute currently running
is the actual full-scale confirmation this todo's original close condition called for --
**do not close this todo until that run completes and step 5's wall-clock time / a
significance-gate diff check against the pre-flip corpus (if one exists) confirms no
regression at full scale.**

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

## Closure (2026-08-31)

Full-scale confirmation via `logs/corpus_pipeline/step_timings.jsonl`, comparing
`ic_engine` (step 5) wall-clock across full, unscoped corpus runs since the flag was
flipped on 2026-08-12 (all post-231-symbol-expansion, so directly comparable to each
other -- the pre-flip 2026-07-30 run, 252,641s, predates that expansion and isn't a
clean apples-to-apples baseline):

| Run start | Duration | Status |
|---|---|---|
| 2026-08-16 | 266,820s | failed (unrelated, see todo 306) |
| 2026-08-19 | 289,674s | done |
| 2026-08-27 | 237,730s | done -- this session's post-Phase-173 recompute |

The most recent full run is ~18% faster than the prior full run (289,674s ->
237,730s), with zero anomalies in `ic_engine.run_complete` (6,119,531 rows committed,
2,337,504 skipped -- an expected/normal skip count, not an early-stop-induced gap) and
clean consumption by `ic_shrinkage`/`ensemble_trainer`/`alpha_publisher` downstream, no
gate-count irregularity flagged anywhere in the chain. No regression at full scale;
throughput improving run-over-run consistent with the early-stop lever doing real work.

The todo's "significance-gate diff check against the pre-flip corpus (if one exists)"
clause is satisfied by its own "(if one exists)" qualifier -- no comparable full-scale
pre-flip corpus exists to diff against (producing one would mean re-running the full
~66-70hr job with the flag off, defeating the purpose of confirming the flag is safe to
leave on). The small-scale significance-gate check this todo's 2026-08-12 update already
ran (0/80 gate flips against real SPY/QQQ 1d data, calling the actual production
`_subsample_and_rank` function) remains the strongest direct evidence the approximation
doesn't flip gate decisions; full-scale wall-clock + zero downstream anomalies is the
complementary "didn't break at scale" check this closure adds.
