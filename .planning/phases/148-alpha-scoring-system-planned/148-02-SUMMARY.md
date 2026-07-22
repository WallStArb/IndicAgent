---
phase: 148-alpha-scoring-system-planned
plan: 02
subsystem: services
tags: [batch-compute, alpha-scoring, bootstrap-reuse, decile-diagnostic, pytest-tdd]

# Dependency graph
requires:
  - phase: 148-01
    provides: alpha_strategy_scores table, gate_evaluations table, alpha.scoring.* APR keys
  - phase: 142B
    provides: alpha_frames hypertable, counterfactual_tracker.evaluate_frame_gate/frame_gate_passes
provides:
  - AlphaScorer(BaseBatch) -- services/alpha_scorer.py
  - services.alpha_scorer.score_cells -- pure aggregation core (unit-testable, no DB)
  - Live alpha_strategy_scores rows (SPY/5m, 6 regimes x 10 deciles = 60 cells per run)
affects: [148-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "per-cohort 2-tuple group_key reuse of a helper that only accepts a 2-tuple destructure (verified against live source before coding)"
    - "deterministic NTILE(10) decile bucketing with explicit tie-break ORDER BY"

key-files:
  created:
    - services/alpha_scorer.py
  modified:
    - tests/unit/test_alpha_scorer.py

key-decisions:
  - "STEP 0 verify-first round-trip re-confirmed live (independent of the plan's own prior verification): evaluate_frame_gate destructures group_key into exactly (dim_a, dim_b) and maps them to output fields tf/regime respectively -- a 4-tuple group_key raises ValueError. AlphaScorer calls it once per (symbol, tf, regime) cohort with group_key=(alpha_score_decile, regime), remapping verdict['tf']->alpha_score_decile and verdict['regime']->regime in Python."
  - "win_rate/sharpe_annualized/max_drawdown adapted (not imported) from phase143_1_08_shadow_validation.py's pure functions, stripped of their gate pass/fail booleans -- alpha_strategy_scores is a diagnostic table with no gate threshold of its own to apply at write time (min_sharpe/max_drawdown_ratio are consumed downstream by SCORE-03, not SCORE-01)."
  - "ic_alpha_score_corr computed via scipy.stats.spearmanr between decile rank and per-decile mean counterfactual_pnl_r, once per (symbol, tf, regime) cohort -- identical across every decile row in that cohort by construction."
  - "No ProcessPoolExecutor: the plan permits parallelization but does not require it; alpha_frames read is a single asyncpg fetch and all downstream computation is pure Python/numpy, so a single serial main-process pass is simpler and still respects the DAG invariant (single serial async batch INSERT in main process)."
  - "bootstrap_max_n=1 used in both unit tests to force evaluate_frame_gate's analytic-CLT branch instead of scipy.stats.bootstrap's BCa resampling -- same call path, deterministic and fast."

patterns-established:
  - "Aggregation core (score_cells) kept as a pure function separate from the BaseBatch class body -- fully unit-testable without a DB connection, mirroring test_ensemble_ic_gate.py's shape."

requirements-completed: [SCORE-01]

# Metrics
duration: ~55min
completed: 2026-07-22
---

# Phase 148 Plan 02: Alpha Scoring System Summary

**AlphaScorer(BaseBatch) buckets closed primary alpha_frames into per-(symbol, tf, regime, alpha_score_decile) cells via deterministic NTILE(10), reuses evaluate_frame_gate unmodified per-cohort with a verified 2-tuple group_key, and writes win_rate/sharpe/drawdown/ic_alpha_score_corr diagnostics to alpha_strategy_scores -- verified end-to-end against SPY/5m real data (60 cells, all sample_n >= 304, all ic_alpha_score_corr non-null).**

## Performance

- **Duration:** ~55 min
- **Completed:** 2026-07-22T20:36:48Z
- **Tasks:** 2/2 completed
- **Files modified:** 1 created (`services/alpha_scorer.py`, 359 lines), 1 modified (`tests/unit/test_alpha_scorer.py`, filled from Wave 0 stub to 138 lines)

## Accomplishments

- Re-verified (STEP 0, independent of the plan's own prior verification and gsd-plan-checker's) `evaluate_frame_gate`'s group-key destructure directly against live source (`services/counterfactual_tracker.py` line ~953: `for (dim_a, dim_b), bucket in groups.items():`) and confirmed via an isolated `python -c` round-trip with 6 synthetic rows that `verdict["tf"]` carries the first group_key element and `verdict["regime"]` the second -- before writing any production code
- Built `services/alpha_scorer.py`: `AlphaScorer(BaseBatch)` (`job_name="alpha-scorer"`, `compute_version="1.0.0"`) plus a pure `score_cells()` aggregation core, reusing `evaluate_frame_gate` UNMODIFIED per-(symbol, tf, regime) cohort with the verified 2-tuple `group_key=(alpha_score_decile, regime)`
- Deterministic decile bucketing: `NTILE(10) OVER (PARTITION BY symbol, tf, regime ORDER BY alpha_score, bar_ts, frame_id)` -- the explicit tie-break avoids unstable decile assignment across runs
- `min_strategy_n`/`bootstrap_max_n`/`bootstrap_batch`/`bootstrap_random_state` all loaded via `load_apr_dict_async` + `cfg()`, no hardcoded thresholds
- Filled both Wave 0 stub tests GREEN, including an explicit group-key round-trip assertion (`by_symbol["SPY"]["alpha_score_decile"] == 1` after remapping from `verdict["tf"]`) and a per-cohort isolation assertion (same decile number in two different symbol cohorts produces two separate output rows, not one merged cell)
- Ran AlphaScorer against the live DB scoped to SPY/5m (317,325 closed primary frames, 6 regimes): wrote 60 cells (6 regimes x 10 deciles), all `sample_n >= 304` (well above the 30 floor), all `ic_alpha_score_corr` non-null, zero unpack/ValueError in the run log -- confirms the 2-tuple group-key call path is correct end-to-end
- Ruff + Black clean on both files; no other test files touched

## Task Commits

Each task was committed atomically:

1. **Task 1: Build AlphaScorer(BaseBatch) and turn test_alpha_scorer.py GREEN** - `2c343830` (feat)
2. **Task 2: Verify AlphaScorer end-to-end on real data** - no commit (DB-only real-data run against already-committed code; no tracked files changed)

## Files Created/Modified

- `services/alpha_scorer.py` - `AlphaScorer(BaseBatch)` + `score_cells()` pure aggregation core + `_max_drawdown`/`_annualized_sharpe`/`_win_rate`/`_ic_alpha_score_corr` helper functions + argparse `main()` entrypoint (manual/on-demand, no systemd unit, no `_DAG_ORDER` registration -- deliberately deferred per RESEARCH.md Open Question 2)
- `tests/unit/test_alpha_scorer.py` - `test_buckets_deciles_and_filters_min_strategy_n` and `test_ic_alpha_score_corr_monotonic` filled from Wave 0 `pytest.fail()` stubs to real pure-function assertions against `score_cells`

## Decisions Made

- Adapted (not imported) `_max_drawdown`/`_annualized_sharpe` from `phase143_1_08_shadow_validation.py`, stripped of the gate pass/fail booleans that script's SCORE-03 use case needs -- `alpha_strategy_scores` has no gate threshold columns of its own to populate at write time; `min_sharpe`/`max_drawdown_ratio` are SCORE-03's concern.
- Skipped `ProcessPoolExecutor` parallelization entirely: the plan permits it conditionally ("if you parallelize...") but does not require it, and a single asyncpg fetch + pure-Python/numpy aggregation + one serial batch INSERT is simpler while still respecting the "never write from a worker" DAG invariant.
- `ic_alpha_score_corr` uses `scipy.stats.spearmanr` (explicitly a "rank correlation" per the plan's own wording) between decile number and per-decile mean `counterfactual_pnl_r`, computed once per cohort (identical value attached to every decile row in that cohort).

## Deviations from Plan

None - plan executed exactly as written. The STEP 0 verify-first round-trip check (already independently verified twice during planning per the plan's `<review_revisions>` note) was re-confirmed a third time as the plan's own instruction requires, with no surprises.

## Issues Encountered

None. The worktree's `.venv` symlink (documented as a known gotcha in 148-01's SUMMARY) was already present; ruff/black/pytest all resolved without additional setup.

## Known Stubs

None. `services/alpha_scorer.py` is fully wired: reads live `alpha_frames`, computes real statistics via `evaluate_frame_gate`, writes real rows to `alpha_strategy_scores`. No placeholder data paths.

## Threat Flags

None. This plan's only trust boundary (operator CLI `--symbols`/`--tf` args) is exactly as scoped in the plan's own `<threat_model>` (T-148-S1, mitigated via `get_active_contracts` validation in `main()`; T-148-S2, accepted). No new surface introduced beyond what the plan already registered.

## User Setup Required

None - no external service configuration required. AlphaScorer is a manual/on-demand oneshot (`.venv/bin/python services/alpha_scorer.py [--symbols ...] [--tf ...]`), not a running service.

## Next Phase Readiness

`alpha_strategy_scores` now has live, real rows (SPY/5m, 60 cells across 6 regimes x 10 deciles, all with valid `ic_alpha_score_corr`) that 148-05 (the promotion decision doc) can cite as evidence that SCORE-01's decile diagnostic pipeline works end-to-end. `score_cells()` is unit-tested and reusable for any future full-corpus sweep without further schema or statistics work. No blockers for 148-03/148-04/148-05.

## Self-Check
