---
status: pending
priority: P0
filed: 2026-07-29
source: re-running ops_canary_integrity_assert.py while fixing todo 203 (canary RNG seed bug)
---

# `canary_acausal_placebo` (positive control, deliberate look-ahead leak) is NOT
# clearing the POOLED significance gate in live feature_ic_scores -- ic_ci_lower=
# ic_ci_upper=0 exactly, a degenerate-computation signature, not a real small-IC
# measurement -- root cause not yet diagnosed

## Problem

Running `scripts/ops/alpha/ops_canary_integrity_assert.py` against the current
`feature_ic_scores` vintage (`training_window_end = 2025-12-24 05:15:00+00`, the only
vintage in the table) fails:

    FATAL: canary integrity violation -- canary_acausal_placebo (positive control) did
    NOT clear the significance gate in the POOLED stratum -- this pipeline failed to
    detect a deliberate look-ahead leak, meaning it cannot be trusted to detect a real
    one either

Every `canary_acausal_placebo` / POOLED row sampled has `ic_ci_lower = 0` AND
`ic_ci_upper = 0` exactly -- a zero-width CI at exactly zero. This is the signature of
a degenerate/fallback computation path (e.g. a zero-variance guard), not a genuinely
small measured IC (a real Fisher-z or bootstrap CI on thousands of observations is not
exactly [0, 0] to floating-point precision by chance).

This is NOT the same root cause as todo 203's canary RNG seeding bug --
`canary_acausal_placebo` does not use `_canary_sub_seed` at all (it reads
`closes[i+1]`/`closes[i+2]` directly, genuinely per-symbol). Confirmed the raw
`feature_vectors.canary_acausal_placebo` column has real, non-degenerate variance
corpus-wide (stddev 0.003-0.015 depending on tf, 250K-1.4M distinct values per tf) --
so the bug, whatever it is, is in how `ic_engine.py`'s cross-sectional POOLED
measurement processes this specific feature, not in the raw feature data itself.

## Hypotheses (none yet confirmed -- do NOT guess-fix)

1. **Stale vintage**: `feature_ic_scores` has never been recomputed since
   2025-12-24 -- possibly predates a code path that's since been fixed, or the
   corpus's forward_returns/feature_vectors alignment was different then. A full
   `ic_engine` pass against the current corpus (queued behind the Tier -1 regime-repair
   pipeline, `.planning/STATE.md`) would test this -- this todo's finding might simply
   resolve once that pass runs, or might not.
2. **Price-sanity/outlier clipping applied to a feature that looks like a return**:
   `canary_acausal_placebo` is deliberately constructed to have the exact shape of a
   return column (`ln(close[t+2]/close[t+1])`). If `ic_engine.py`'s corrupt-print /
   `max_abs_return` sanity-guard (built for `forward_returns`, todo 148) is also
   touching feature *inputs* that resemble returns, it could be masking/clipping this
   canary's most informative (largest-magnitude) observations specifically.
3. **A genuine bug in `_compute_cross_sectional_tf`'s degenerate-feature masking**
   (`non_degenerate_mask` in `ic_math.py`) incorrectly classifying this feature as
   zero-variance for the POOLED family specifically, even though per-symbol variance
   is real.

## Fix

Not diagnosed yet. Next step: re-run `ops_canary_integrity_assert.py` after the Tier -1
regime-repair pipeline's `ic_engine` step lands a fresh `feature_ic_scores` vintage (cheap,
free confirmation/denial of Hypothesis 1). If it still fails post-rebuild, trace
`_compute_cross_sectional_tf`'s handling of `canary_acausal_placebo` specifically (inspect
this one feature's `X_raw` column and intermediate `non_degenerate_mask`/`ic_vec` values at
a breakpoint) before touching any production code.

## References

- `scripts/ops/alpha/ops_canary_integrity_assert.py` -- the gate that caught this
- `.planning/todos/pending/203-canary-rng-seed-not-per-symbol-cross-sectional-pseudo-replication.md` -- sibling finding, confirmed different root cause
- `.planning/todos/completed/202-per-tf-lookahead-grid-downstream-consumers-stale.md` -- CLOSED 2026-07-30; the corpus-rebuild readiness work that would let Hypothesis 1 be tested once `ic_engine` actually runs
- `services/ic_engine.py` `_compute_cross_sectional_tf` -- where this would need tracing if Hypothesis 1 is ruled out
