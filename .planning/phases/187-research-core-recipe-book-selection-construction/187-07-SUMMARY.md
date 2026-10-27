---
phase: 187-research-core-recipe-book-selection-construction
plan: 07
status: complete-pending-gate
completed: 2026-10-27
commits: [78acea146, a23f78a49, 37181297f]
requirements: [R-187-12]
---

# 187-07 summary: the construction rule protocol

- Harness (78acea146): `tests/unit/research/test_spec_hashes_pinned.py` pins all seven spec
  hashes (equal to the research_run rows on 2026-10-27); `backfill_attempt_series.py
  --compare-all` replays every completed evidence run and requires the decision block and any
  stored D_s series to match bit for bit, never writing.
- Protocol (a23f78a49): `construction.py` with `RankVolNeutral`, `CalibratedArm` (the three
  phase 179 arms) and `FixedSign`, each equal to its portfolio.py function; `resolve_rule(spec,
  bars_per_session)`. `fixed_sign_weights` extracted, returns arithmetic unchanged.
- Routing (37181297f): `book_timing(rule=...)`, `PowerProblem.rule`, run_family, the shift
  diagnostic and S8 resolve the rule; the runner refuses a non-R1 construction before the
  ledger.

Deviations:
- No new spec fields. The calibrated arms need only fields ScoringSpec already carries
  (warmup, refit, coverage, ridge, mv_condition_max, ic_shrinkage_k), so `ConstructionSpec`
  only widens its name Literal and every hash is unchanged by construction. The rule takes
  them in rows (`evaluate.rows_config`), as evaluate() does; a /review finding caught a
  session-unit config.
- `has_position` for the plan-sized rules: a pre-calibration row (all NaN) or a row with no
  finite nonzero forecast holds no position; any other NaN stays NaN.
- The non-R1 rules size from a covariance plan the runner does not build yet; they become
  runnable with the construction attempt at capital readiness.

Verification: full unit suite green; repro_frozen bit-identical after each commit. Gate still
open: the `--compare-all` baseline has not been run (it is the same replay workload as the
stopped backfill and waits on the owner's restart).
