---
status: pending
priority: P0
filed: 2026-10-27
source: 187-05-BATTERY.md step A (857cdff9f); owner decision 2026-10-27
---

# E17 v2: fixed-b critical values for the Newey-West timing statistic

## What

E17's HAC timing test over-rejects. Pooled over every gating arm of the 187-08 battery, size at
0.05 is 5.40% at 4,000 sessions, 99% Clopper-Pearson [5.07, 5.75], and 5.47% at 1,500 sessions:
the excess is outside Monte Carlo error and does not shrink with the panel. Mean t is about 0
and its sd 1.006 to 1.016, so the statistic is unbiased with a slightly too wide t: the known
finite-sample understatement of the Bartlett long-run variance. StepM studentizes with the same
HAC and inherits it. A liberal test overstates evidence, so StepM selection, the kappa 0.5 book
and the StepM attestation stay blocked until it is corrected.

## Owner decisions (2026-10-27)

1. Apply fixed-b critical values (Kiefer and Vogelsang 2005) for the Bartlett kernel at E17's
   lag, as E17 v2: a new versioned statistic with its own code key and a methodology-change
   ledger entry under E17.
2. Recorded results are records: every v1 evidence row stays as written under its code key.
   Family 1 is re-scored as new rows (its HAC t of 13.5 to 18.6 does not flip). repro_frozen
   gets a deliberate new baseline, recorded with the reason.
3. Then the battery pass rule (step B), written down before one fresh run and judged on that
   run only: each cell at a Bonferroni bound (1 - 0.01 / 20 = 99.95%) and the pooled size
   within a declared tolerance (for example at most 6%).

## Plan

1. Fixed-b p-values for the Bartlett kernel at b = lag / n, versioned so v1 stays reproducible.
2. Interaction with todo 547 (a horizon-tied lag for overlapping daily targets): decide the
   order and certify both on the same battery, so the daily battery is not run twice.
3. One fresh 4,000-session StepM battery and the fitted-book certificate (voided by 187-09 Task
   1) under v2, judged by step B; 184-05's persistent battery cells go into the v2 certificate.
4. Family 1 re-scored under v2 as new rows.

## Finding before build (indicagent-5b, 2026-10-28): fixed-b may be solving a problem that is not there

Measured with `scripts/research/e17_size_diagnostic.py` (synthetic H0 panels, seeds from
9,000,000, so not the battery's; not a counted look). Raw results:
`/tmp/claude-1000/-home-bg-dev-indicagent/1734d8bc-89a4-4e71-834b-de1559dfe27d/scratchpad/e17acf/`
(scratch; rerun the script to reproduce).

1. **Step A's interval is too narrow.** It pooled 30 arms x 1,000 simulations as 30,000
   independent trials, but an H0 simulation's arms (mean1, 5, 20, 40 and the book) share one
   panel: their rejection indicators correlate about 0.2 and the design effect of pooling them
   is 1.5 to 2.1. Widened by sqrt(1.8), step A's 4,000-session 99% interval [5.07, 5.75]
   becomes about [4.95, 5.85], which contains 5%.
2. **Fresh seeds at 4,000 sessions show no excess.** Pooled size at 0.05: gaussian 4.86%
   (1,000 sims), kappa_0.5 4.60%, kappa_0.5_static 4.63%, kappa_0.2 4.87%, static cell means
   4.67% (600 each), ridge and ridge_static 4.27% (300 each). At 1,500 sessions: gaussian
   5.50%, static 5.32%, hostile 4.93% (2,000 each), so any excess is a short-panel effect.
3. **D_s has no serial dependence for a HAC to miss.** Mean ACF at lags 1-5 is within
   +-0.004 in every cell, and the summed ACF over lags 10-80 equals the -1/n demeaning bias.
   Longer Bartlett lags make size worse (1,500 sessions pooled: x1 5.25%, x2 5.37%, x4 5.56%,
   x8 5.98%), the opposite of under-covered dependence.
4. **Fixed-b barely moves size at E17's bandwidth.** b = lag / n is about 0.004 at 1,500
   sessions and 0.002 at 4,000; the 5% value moves from 1.645 to about 1.65, cutting pooled
   size by 0.14pp at 1,500 (5.25 to 5.11) and nothing measurable at 4,000.

Recommendation for the owner: do not build fixed-b as E17 v2 on step A's evidence. Rerun
step A with a cluster-robust interval (one cluster per simulation) over all gating cells at
4,000 sessions on fresh seeds, and decide from that. If no excess holds, E17 v1 stands, step
B's family-wise rule (Bonferroni per cell plus pooled tolerance) is the only change, and StepM
selection unblocks without a new statistic, a new code key or a repro_frozen rebaseline. The
cells not rerun here (t4, vol_clustering, factor, slot_effects, late_listings,
real_grid_hostile, s1_hostile) are the ones to check first.

## Owner decision 2026-10-28

Rerun step A with a cluster-robust interval before building anything. Unit `e17-step-a-rerun`
(`scripts/research/e17_size_diagnostic.py`, seeds from 9,100,000, 16 gating cells x 600
simulations at 4,000 sessions, output `e17acf/stepA_rerun.json` in the session scratchpad) starts
when the 187-03 apply ends. If the pooled 99% cluster-robust interval contains 5%, E17 v1
stands and only step B's pass rule changes; if it excludes 5%, fixed-b is built as planned.
Record the result here.

## Done when

E17 v2 is on main with its ledger entry, the step B rule is written, one fresh battery holds
under it, and StepM selection is attested on v2.
