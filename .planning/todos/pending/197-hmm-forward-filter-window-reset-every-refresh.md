---
status: pending
priority: P2
filed: 2026-07-27
source: found via cProfile while investigating feature_vectors compute throughput -- SPY/5m's
  full 20-year history, single symbol/tf, took ~10 min to compute; profiling isolated the cost
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
