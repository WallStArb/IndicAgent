---
status: completed
priority: P2
filed: 2026-07-27
closed: 2026-07-30
source: found via cProfile while investigating feature_vectors compute throughput -- SPY/5m's
  full 20-year history, single symbol/tf, took ~10 min to compute; profiling isolated the cost
---

## Resolution (2026-07-30) — superseded by deletion, not optimization

Closing todo 207 (`feature_vectors.hmm_regime_prob`/`hmm_entropy`/`hmm_duration` dual-writer
collision) required tracing every consumer of `_hmm_forward_2d`'s output, and found zero live
consumer beyond the now-removed `FeatureVector` echo this todo already correctly identified as
IC-measured (see "Why this isn't a quick fix" below — that reasoning was right, the columns
*were* live-consumed, just not by anything that needed the K=3 *value specifically*).
`regime_writer.py`'s fitted K=5 HMM is the sole real consumer of the `hmm_regime_prob`/
`hmm_entropy`/`hmm_duration` column *names*; the K=3 forward-filter computed here had never
earned authority over them (no BIC validation, ever). So the right fix wasn't "make this
incremental" (option 2/3 below) — it was delete the call entirely, since the output was going
nowhere.

`refresh_regime()` no longer calls `_hmm_forward_2d`/computes `hmm_regime_prob`/`hmm_entropy`/
`hmm_duration` at all; `_hmm_forward_2d` and `_hmm_entropy` (the two symbols solely responsible
for the ~30% cost measured below) were deleted from `feature_cache.py` outright, confirmed zero
remaining callers repo-wide. `_hmm_forward_step`/`_HMM_A`/`_HMM_MEANS_2D`/`_HMM_VARS_2D`/`_HMM_K`
were kept (not deleted) — `services/backfill_feature_factory.py` imports and calls
`_hmm_forward_step` directly for a genuinely different, live computation (`ctf_regime_align`, a
cross-timeframe regime-alignment feature), reusing the same low-level forward-algorithm step on
higher-timeframe bars; this dependency was missed on a first pass (file-scoped grep, not
repo-wide) and caught by the full test suite (4 collection `ImportError`s), not by review.

The reset-every-window design question this todo raised (point 1 in "What needs to happen") is
now moot — there's no more replay happening in this context to redesign. `hurst`/`shannon`/
`garch_ratio`/`hma_slope_z`/`adx` (the *other* things `refresh_regime()` computes, sharing the
same 30-bar cadence and full-window-replay pattern) are untouched by this fix and still replay
from scratch every cycle — if that remaining cost is ever worth investigating, it needs its own
todo; this one's scope was specifically the HMM sub-computation, now gone.

Full detail: `.planning/todos/completed/207-hmm-column-name-collision-k3-k5.md`.

---

# `FeatureCache`'s inline forward-filter HMM resets to uniform prior and replays the full window from scratch every 30 bars -- ~30% of total feature-compute cost, and possibly not even the statistically correct design

## Finding

**Not to be confused with `regime_writer.py`'s separate, real `hmmlearn.GaussianHMM` (K=5, fitted
per symbol/tf, writes `feature_vectors.regime`).** This is a different, simpler mechanism:
`feature_cache.py`'s `_hmm_forward_2d()`/`_hmm_forward_step()`, called from
`FeatureCache.refresh_regime()` every `feature.regime.cache_refresh_bars` bars (default 30) from
inside `FeatureFactory.compute_batch()`'s main loop. It's a hand-rolled, K=3, forward-only filter
with **fixed constant parameters** (`_HMM_A`/`_HMM_MEANS_2D`/`_HMM_VARS_2D`, no fitting/learning)
that feeds three ordinary `FeatureVector` predictor columns: `hmm_regime_prob`, `hmm_entropy`,
`hmm_duration`.

Profiled via cProfile on SPY/5m (394,121 bars, 50,000-bar subset measured): `_hmm_forward_2d`
cumulative time is ~30% of total `compute_batch()` cost (21.4s of 72.3s on the subset) --
overwhelmingly the single largest contributor, ahead of all the other feature computations
combined.

**Root cause:** every refresh call does `alpha = np.full(_HMM_K, 1.0 / _HMM_K)` (reset to
uniform prior) and then replays the **entire bounded window** (up to `hurst_window`, default
252 bars) through `_hmm_forward_step` from scratch -- it never carries `alpha` forward from the
previous refresh. The transition matrix has ~94-95% self-persistence, so the chain only needs
~15-20 steps to "forget" the uniform-prior restart -- meaning the majority of each 252-bar replay
is provably redundant even under the *current* semantics.

## Why this isn't a quick fix (and shouldn't be one)

A naive "make it incremental" fix (persist `alpha` across refreshes, never reset) would produce
**numerically different** `hmm_regime_prob`/`hmm_entropy`/`hmm_duration` values than today's code
-- not an optimization, a behavior change. Those three columns are IC-measured; changing them
without a recompute + explicit validation is the same class of "silent wrong answer" this
project's principles exist to prevent, and the same class of thing `HMM_RANDOM_STATE=42` is
flagged as load-bearing for in CLAUDE.md (different HMM, same category of risk).

Separately, the *current* reset-every-window design may not even be the statistically correct
one on its own merits -- discarding 252 bars of regime memory every 30 bars and restarting from
an uninformative uniform prior is an unusual choice for a forward filter, and worth questioning
on those grounds independent of performance. That's a design question, not a bug.

## What needs to happen

1. Investigate why the reset-every-window design was chosen this way (check `D-07` context --
   "no backward smoother" -- and any other CONTEXT.md discussion of `refresh_regime`'s history)
   before assuming it's simply a bug.
2. If a genuinely incremental (persistent-`alpha`) redesign is the right call: treat it with the
   same rigor as todo 092's regime-label fix -- a real before/after comparison against the
   current output, an explicit decision on which design is statistically correct (not just
   faster), and a full corpus recompute + `feature_ic_scores` re-run once landed. Not a
   drive-by change.
3. Alternative, lower-risk option worth considering first: keep the reset-to-uniform-at-window-start
   semantics exactly as-is (bit-identical output), but shrink the *replay* using the mixing-time
   argument above -- e.g. empirically bound the window needed for `alpha` to converge to within
   float64 precision of its 252-bar value, and only replay that many bars. This preserves output
   type/meaning but changes the *specific numeric values* by less than the current
   reset-vs-never-reset gap would, so it still needs equivalence testing with a numeric
   tolerance, not exact equality -- cheaper to validate than a full redesign, still not a
   "just merge it" change.

## References

- `src/intelligence/feature_cache.py:110` (`refresh_regime`), `:627` (`_hmm_forward_2d`), `:657`
  (`_hmm_forward_step`), `:602-624` (fixed `_HMM_A`/`_HMM_MEANS_2D`/`_HMM_VARS_2D`/`_HMM_K`
  constants)
- `services/feature_vector_pipeline.py` -- `feature.regime.cache_refresh_bars` (default 30 via
  `_THRESHOLD_KEYS`), `feature.hurst.window` (default 252, bounds the replay window)
- Contrast: `services/regime_writer.py` -- the separate, real fitted HMM (K=5,
  `alpha.hmm.random_state`), writes `feature_vectors.regime`, NOT what this todo is about
