---
status: completed
priority: P1
filed: 2026-09-13
closed: 2026-09-13
source: council review of the personal-scale edge program's decision gate, verified against primary sources
---

# Single-name-only `range_pct_fast_xs_ls_h5` re-falsification — CLOSED, DEAD

## What was found (superseded by the closure below — kept for the record)

A council review of the fired decision gate (rule 3, 2026-09-12) raised a specific,
falsifiable objection: `range_pct_fast_xs_ls_h5`'s DEAD verdict (beta +1.14, R²=0.75,
pooled across 231 symbols = 128 single-name equities + 103 ETFs) was never checked for
whether the beta contamination is a property of the *signal* or a property of *pooling
baskets with single names in one cross-sectional ranking*.

A diagnostic (`scripts/analysis/range_pct_fast_beta_by_universe_composition.py`) found
the single-name subset showed materially less beta contamination (R² 0.44 vs 0.75
pooled) and a neutralized intercept more than double the pooled result (10.17bp vs
4.87bp, primary-phase-only). This was explicitly recorded as a preliminary, non-
load-bearing signal — no cost drag, bootstrap CI, or stability check had been run.

## Closure: Pre-registration 3 designed, AGY-reviewed, verdict DEAD

Wrote a full pre-registration (`docs/plans/2026-09-02-personal-scale-edge-determination-
plan.md`, "Pre-registration 3") inheriting every fixed quantity from Pre-registration 1
except the universe restriction, locked before running. Got an AGY adversarial review
before running, per this program's standing practice.

AGY raised real structural objections (post-hoc subgroup selection without a meta-FDR
alpha adjustment, unrealistic single-stock cost assumptions, a shuffled null that
breaks sector clustering, survivorship bias, under-diversified k=6 legs in 2007-2008,
an unlocked/unversioned symbol query) and specifically claimed the pre-registered
stability criterion (net > 0 in 3/3 subperiods) fails.

**AGY's specific subperiod numbers (+10.98/-8.26/-2.10bp) were independently verified
against the exact locked formula and found WRONG.** True numbers, computed directly:
subperiod 1 (2007-08-14..2013-09-25) +17.87bp, subperiod 2 (2013-10-02..2019-11-06)
**-1.14bp**, subperiod 3 (2019-11-13..2025-12-23) +4.87bp. But the qualitative
conclusion held: subperiod 2 is negative, and the pre-registered rule requires strict
positivity in all three. **DEAD on criterion (c) alone**, per the pre-registration's own
no-post-hoc-loosening clause — the full bootstrap CI / shuffled-null machinery
(criteria a/b) was not run, since all three criteria are required and (c) already
fails under the locked design. No wasted compute chasing a lead already closed by its
own rule.

The earlier diagnostic's headline 10.17bp (primary-phase-only) masked this: the excess
return is concentrated in the 2007-2013 crisis-era subperiod and does not hold
uniformly. Verdict registered `range_pct_fast_xs_ls_h5_single_name_only`, migration 334.

**This closes the single highest-leverage open lead from the 2026-09-13 council
review.** The "universe expansion is primary" resourcing call from the 2026-09-12 gate
firing now stands on firmer ground — three distinct construction paradigms (pooled
cross-sectional, single-name-only cross-sectional, per-symbol time-series/TSMOM) have
now all failed on this corpus.

AGY's other structural objections (meta-FDR adjustment, single-stock cost realism,
sector-stratified null design, symbol-list versioning) remain valid critiques of this
construction TYPE generally, recorded in migration 334's metadata for any future
attempt, but did not need resolving to reach this verdict.
