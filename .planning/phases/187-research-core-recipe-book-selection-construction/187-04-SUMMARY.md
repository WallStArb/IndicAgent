---
phase: 187-research-core-recipe-book-selection-construction
plan: 04
status: complete
completed: 2026-10-26
commits: [c2d060c52]
requirements: [R-187-06]
---

# 187-04 summary: Romano-Wolf StepM

- `src/intelligence/statistics/stepm.py`: `stepm(series, *, block_mean, max_horizon_sessions,
  reps, fwer, seed) -> StepMResult(t, adjusted_p, selected, ...)`. One joint stationary-
  bootstrap index draw over the common calendar; t_k = mean / HAC se on each attempt's own
  finite sessions; bootstrap t*_k centred on the sample mean and scaled by the sample se (the
  SPA studentization, documented); a draw that lands on none of an attempt's sessions carries
  no evidence about it (-inf); monotone step-down adjusted p-values; refuses a block_mean at
  or below the longest horizon.
- `src/intelligence/statistics/bootstrap.py`: the stationary-bootstrap index generator, moved
  from `research/evaluate.py` with its draw order unchanged.

Verification: `tests/unit/statistics/test_stepm.py` (6): one strong attempt among 30 nulls is
exactly the selection; FWER under a 20-attempt global null over 120 seeds within 0.05 + 2 se;
ten near-copies of a t 2.5 series price at adjusted p 0.01 against 0.05 for the same series
among nine independent tries; seed determinism and monotone p; late-start and early-end spans
are not filled; block refusal. Full unit suite green; repro_frozen bit-identical.

Deviation: the `alpha.selection.stepm.*` APR seeds (planned as migration 516) move to plan 06's
migration, where `select_books.py` is their first reader; seeding them now would leave the keys
reader-less (test_table_and_apr_key_readers).
