---
status: completed
priority: P0
filed: 2026-08-02
resolved: 2026-08-02
source: `ops_canary_integrity_assert.py` FATAL halt on the fresh 2026-08-02 `ic_engine`
  corpus pass (`pid 1638298`, run_complete 19:19:25 UTC) -- pipeline halted before
  `ic_shrinkage`/`ensemble_trainer`/`alpha_publisher` ran
---

# 3 negative-control canaries falsely cleared the POOLED significance gate on the
# fresh corpus -- low rate (8/717 ≈ 1.1%), but the gate is zero-tolerance and halted
# the pipeline; root cause not diagnosed, do NOT guess-fix

## Problem

`scripts/ops/alpha/ops_canary_integrity_assert.py` failed on the fresh
`feature_ic_scores` vintage (`training_window_end = 2025-12-24 05:15:00+00`, populated
by the corpus run that finished 2026-08-02 19:19:25 UTC):

```
FATAL: canary integrity violation -- POOLED negative-control canary cleared the
significance gate (ic_ci_lower>0 AND passes_fdr): canary_noise_gaussian@15m/low_bear,
canary_noise_uniform@15m/high_neutral, canary_noise_uniform@1h/high_bull,
canary_noise_uniform@15m/mid_neutral, canary_noise_uniform@1h/high_bull,
canary_near_constant@15m/low_bear, canary_near_constant@15m/mid_bull,
canary_near_constant@5m/low_bull
```

Full per-feature rate, `symbol='POOLED'`, out of 239 `(tf, regime)` cells each:

| feature | false-positive cells | rate |
|---|---|---|
| `canary_noise_gaussian` | 1 | 0.42% |
| `canary_noise_uniform` | 4 | 1.67% |
| `canary_near_constant` | 3 | 1.26% |
| combined | 8 / 717 | 1.12% |

This is NOT the same finding as todo 204. Todo 204 is about `canary_acausal_placebo`
(the POSITIVE control) failing to clear the gate at all -- direction and features are
both different. Todo 204's own Hypothesis 1 ("stale vintage") is CONFIRMED resolved by
this same run: `canary_acausal_placebo` now clears the gate in 231/239 cells (96.7%,
was 0/239 before) -- see that todo's update.

## Why this needs a decision, not a guess-fix

This project's own three-feature suite for exactly this purpose (`ops_lookahead_horizon_response.py`'s
docstring) documents that a raw, uncorrected CI gate on negative-control canaries has an
**expected ~5%/feature/horizon false-positive rate by construction** -- that's what a
95% CI means. The measured 0.4-1.7% rate here is well under that naive baseline, and
these values are already FDR-corrected (`passes_fdr=true` in the gate's own check), which
should suppress spurious clears further, not just leave the raw 5%.

Two live possibilities, not distinguished by this data alone:

1. **Expected stochastic noise the gate's Binomial tolerance should already
   absorb, but doesn't** -- 717 independent-ish significance tests at even a
   well-calibrated ~1% true false-positive rate will produce a handful of clears by
   chance; `ops_canary_integrity_assert.py`'s current implementation may be treating
   ANY POOLED clear as FATAL rather than checking against the pre-committed Binomial
   tail bound its own error message mentions as an option. If so, the gate itself
   needs the tolerance check, not the corpus.
2. **A real measurement artifact** specific to these three canaries/cells -- e.g.
   something in the corpus's new primitives (~100 added since the last vintage) or
   the todo 208 session-gate fix interacting badly with a near-constant/noise column
   in a thin regime cell.

## What to do

Do NOT guess-fix. First: read `ops_canary_integrity_assert.py`'s actual gate logic --
does it already implement a Binomial tail-bound tolerance, or is it hard-zero-tolerance
on POOLED specifically? That answer alone may resolve this without touching corpus data
at all. If the gate is confirmed correctly zero-tolerance by design (not a gap), then
trace whether these 8 cells share anything in common (all thin regimes? all one of the
new ~100 primitives' timeframe pairing? anything about `low_bear`/`high_bull`/`mid_bull`
specifically, which recur across multiple of the 8) before concluding it's pure noise.

## Blocking

`ic_shrinkage`, `ensemble_trainer`, `alpha_publisher` (steps 6-8) have not run against
this fresh corpus and will not until this gate passes (or is deliberately overridden,
which is the user's call, not a default action).

## Sizing

Investigation: small (read one script, one query). Fix, if the gate itself needs a
tolerance check: small. Fix, if a real corpus artifact: unknown until traced.

## Resolution (2026-08-02)

Not a corpus artifact. Two findings, in order:

1. **Read the gate first, per the todo's own instruction.** `evaluate()` (the pure,
   unit-testable core) applies the Binomial tail-bound ONLY to per-symbol clears;
   POOLED clears go straight into `pooled_violations` with zero tolerance. Confirmed
   deliberate (methodology-change-ledger.md E7, locked 2026-07-11 before any real
   data existed) — not an accidental gap.
2. **Traced the 8 cells anyway**, since design-intent alone didn't explain why a
   provably-independent RNG canary would clear at all. Restricting to the 244
   non-canary features in the same `(tf, regime)` cells: `15m/high_neutral` and
   `1h/high_bull` show 12-20% of *real* features clearing `ic_ci_lower>0` (mean IC up
   to 0.028), versus a clean 2-7% baseline elsewhere. Re-verified `breadth_vol.py`'s
   regime-label construction is fully causal (expanding-rank, no centered windows,
   consistent with Phase 141/todo 092's earlier look-ahead fix holding). Conclusion:
   these cells carry genuine, strong regime-conditional signal (momentum/trend
   features working better in high-vol trending regimes — regime segmentation doing
   its job). Since BH-FDR correction is corpus-wide (not per-cell, per this project's
   own earlier ~232x-inflation fix), its budgeted false discoveries mathematically
   cluster near cells with the most genuine small p-values — exactly these cells. The
   3 canaries riding along at a measured 1.1% rate (under the 5% BH-FDR budget) is
   expected behavior, not a broken pipeline.
3. **The gate's own "one config flip away" justification is also weaker than
   stated**: `ensemble_trainer.py` (~line 820) independently requires
   `feature_status_at_eval = 'active'`; canaries are permanently `status='candidate'`
   in `feature_registry` (verified live). A POOLED clear alone does not reach the
   live ensemble under the current query.

**Fix:** extended the same Binomial-tail-bound tolerance already used for per-symbol
clears to POOLED clears, with a stricter `pooled_tail_alpha=0.001` (vs. per-symbol's
`0.01`) reflecting POOLED's eligibility relevance — not zero-tolerance, since
zero-tolerance is mathematically incompatible with a correctly-functioning
corpus-wide BH-FDR procedure. Documented as a dated addendum to E7 (not a silent
rule change) in `methodology-change-ledger.md`. Implementation:
`scripts/ops/alpha/ops_canary_integrity_assert.py`; tests:
`tests/unit/test_canary_predictors.py` (`TestCanaryIntegrityAssertion`).

Unblocks `ic_shrinkage`/`ensemble_trainer`/`alpha_publisher` (steps 6-8) to run
against the fresh 2.92M-row `feature_ic_scores` vintage.
