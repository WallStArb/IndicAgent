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

## Done when

E17 v2 is on main with its ledger entry, the step B rule is written, one fresh battery holds
under it, and StepM selection is attested on v2.
