---
status: pending
priority: P2
filed: 2026-09-12
source: rigor pass firing the personal-scale edge program's decision gate (rule 3, kill criterion)
---

# `bars_since_high_fast_xs_ls_h5`'s DEAD verdict has no committed falsification script backing its core numbers

## What's wrong

Every other construction verdict this program has produced traces to a locked-design,
pre-registered, committed script: `range_pct_fast_xs_ls_h5_falsification.py`,
`phase148_personal_hurdle_placement.py`, `alpha_score_residual_single_security_15m.py`,
`alpha_score_residual_bucketed_retest_15m.py`, `cointegrated_pairs_residual_same_sector_screen.py`.
`bars_since_high_fast_xs_ls_h5` (verdicted DEAD 2026-09-11, closing the decision gate's
last open candidate) does not: `git log` shows no script was ever added for it, and the
only trace of the underlying computation is a stray `/tmp/spy_15m_bars_since.csv`.

Two numbers are load-bearing for the verdict and have no reproducible artifact:
- The unconditional full-history cross-sectional spread check (mean -0.0004/rebalance,
  beta 0.19, R^2=0.085).
- The structurally-motivated S/R-pivot successor's sign-consistency check (51-58%, via
  `feature_factory._compute_sr_dist_atr`).

The regime-decomposition half of the same verdict (the 52-day
`down_primary_backwardation` attribution) IS reproducible — it's pure SQL analysis over
already-persisted `feature_ic_scores`/`market_regimes` rows, consistent with 0c's own
"no new measurement" convention. Only the spread-check and successor halves are ad hoc.

## Why this matters

This verdict was cited as corroborating evidence when the personal-scale edge program's
kill criterion (decision gate rule 3) fired 2026-09-12
(`docs/plans/2026-09-02-personal-scale-edge-determination-plan.md`, Results §3). The gate
firing does NOT rest on this verdict alone — it rests primarily on two fully rigorous,
pre-registered, concept_registry-governed failures (`range_pct_fast_xs_ls_h5` DEAD,
`alpha_score_residual_single_security_15m` FAIL) plus the fully-scripted graveyard items
— but citing an ad hoc, unreproducible result with the same confidence as those, in a
program whose entire discipline is "no post-hoc parameter moves, locked design before
running" (the N1 lesson), is itself a process-integrity gap worth closing, independent of
whether the verdict survives.

A `concept_registry` row was backfilled for this construction (migration 333) with the
reproducibility gap recorded honestly in `metadata.reproducibility` rather than silently
upgraded to the same evidentiary standing as the other three rows.

## What to do

Either:
1. Build a proper locked-design, committed falsification script reproducing the
   unconditional spread check and the S/R-pivot successor check (mirroring
   `range_pct_fast_xs_ls_h5_falsification.py`'s shape: shuffled null, bootstrap CI,
   BH-FDR, stability subperiods, cost bands) and confirm the DEAD verdict survives under
   real statistical rigor, not just a point estimate and a sign-consistency percentage; or
2. If (1) isn't worth the effort (the gate has already fired and this construction's
   fate doesn't block anything further), formally downgrade this row's confidence in
   `concept_registry.metadata` and the ledger to make clear it was never independently
   falsified to this program's own standard — don't let a future reader treat it as
   equivalent evidence to the other three rows.

Not urgent — doesn't block or reopen the fired kill criterion, which stands on the fully
rigorous record alone.

## Triage 2026-09-26 (backlog review with the owner)

Closed: serves a mechanism the adopted evidence framework (E15, `docs/plans/2026-09-24-evidence-framework.md`) replaced: per-feature admission, bootstrap variants E16/E17 superseded, the emission / alpha_events / alpha_frames capital path, frozen legacy verdicts, or cleanup inside dead scripts.
