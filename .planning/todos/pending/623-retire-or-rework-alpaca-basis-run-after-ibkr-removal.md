---
status: pending
priority: P1
filed: 2026-11-17
source: step 7 D4 disposition; lead ruling 2026-11-17 (indicagent-77): the check cannot be satisfied once IBKR raw is gone
---

# Retire or rework alpaca_basis_run now that IBKR is removed

## What

`alpaca_basis_run` (`integrity_checks.alpaca_basis_runs`, required for 1d in `verdict_gate.REQUIRED_CHECKS`)
compares IBKR raw and Alpaca raw 1d closes and explains a run only by a split dated inside the run or on the
first common session after it. IBKR is removed and Part F deletes its raw rows from 2003-09-10, so for 2026
the check has no IBKR input left. It is red for ITA, MTUM and QUAL in the D4 rerun (run 2026-10-07 to
2026-10-30; recorded splits effective 2026-11-03 and 2026-11-04). Those three names are unready on the verdict
gate only through this check until this todo lands. Ruling: no split is dated 2026-11-02 and no
`corporate_action` row changes; the Massive yardstick row (2026-11-04) stands.

## Requirement first (Musk step 1)

Does any vendor-comparison check survive, with Massive the yardstick and Alpaca the continuation? The
comparison that remains meaningful is Massive against Alpaca over the overlap window (nightly capture against
the archive). Decide whether that is needed beyond `split_continuity`, `split_horizon_fresh` and the
unexplained seam check; if those already catch the defect classes `alpaca_basis_run` was written for
(spin-off, split, ticker event since the D-191-Q arbitration), delete the check rather than port it.

## Scope

1. Requirement ruling, written here, with the defect classes each surviving check covers.
2. Change `REQUIRED_CHECKS["1d"]` and `integrity_checks.alpaca_basis_runs` (retire, or rebase on Massive
   against Alpaca), plus the tests, the ready predicate SQL and every doc naming the check.
3. A built worker edits in a detached worktree off `origin/main` after Part F; timers and auditors import
   `integrity_checks`, so the landing waits for a quiet window.

## Gates

D7 rerun with ITA, MTUM and QUAL ready; no other name's verdict changes except through the ruling; the unit
suite exit code; independent review.
