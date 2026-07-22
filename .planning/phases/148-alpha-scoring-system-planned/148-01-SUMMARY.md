---
phase: 148-alpha-scoring-system-planned
plan: 01
subsystem: database
tags: [postgresql, timescaledb, apr, migration, pytest, tdd-stub]

# Dependency graph
requires:
  - phase: 142B
    provides: alpha_frames hypertable + AlphaFrameWriter + CounterfactualTracker (Gate 1/2 read source)
  - phase: 143.1
    provides: 143.1-08 shadow-mode champion numbers SCORE-03 cites verbatim (D-06)
provides:
  - alpha_strategy_scores table (SCORE-01 write target)
  - gate_evaluations table (SCORE-02/SCORE-03 write target)
  - alpha.scoring.min_sharpe / max_drawdown_ratio / min_ic_alpha_score_corr APR keys
  - Three Wave 0 RED test stub files naming Wave 2's exact SCORE-01/02/03 targets
affects: [148-02, 148-03, 148-04, 148-05]

# Tech tracking
tech-stack:
  added: []
  patterns: [migration APR triple with dual provenance classes, Wave 0 RED stub scaffolding]

key-files:
  created:
    - production/migrations/248_alpha_scoring_gate_tables.sql
    - tests/unit/test_alpha_scorer.py
    - tests/unit/test_oos_gate1_signal_eval.py
    - tests/unit/test_score03_gate2_execution_eval.py
  modified: []

key-decisions:
  - "Migration number 248 confirmed free at execution time (247 was the head, landed same day by an unrelated concurrent workstream); re-verified immediately before applying to guard against a last-second collision"
  - "min_sharpe/max_drawdown_ratio seeded as PRE-REGISTERED gate thresholds (SHADOW-REVIEW.md criteria 3/4); min_ic_alpha_score_corr seeded as DIAGNOSTIC-ONLY, explicitly not a gate threshold, per the plan's provenance-class split"
  - "Renamed both dry-run stub functions to test_gate1_dry_run_writes_nothing / test_gate2_dry_run_writes_nothing (plan specified the same name test_dry_run_writes_nothing in two different files, which the project's duplicate-test-name pre-commit hook rejects) -- -k dry_run substring match preserved for both"

patterns-established:
  - "Wave 0 RED stub: pytest.fail() body naming the concrete Wave 2 target, no module-scope import of the not-yet-built production module, so pytest --collect-only stays clean while pytest execution stays RED"

requirements-completed: [SCORE-01, SCORE-02, SCORE-03]

# Metrics
duration: ~15min
completed: 2026-07-22
---

# Phase 148 Plan 01: Alpha Scoring Foundation Summary

**Migration 248 creates `alpha_strategy_scores` + `gate_evaluations` tables and seeds three never-before-migrated `alpha.scoring.*` APR keys; three Wave 0 test files scaffold SCORE-01/02/03's Wave 2 build targets as collectable-but-RED stubs.**

## Performance

- **Duration:** ~15 min
- **Completed:** 2026-07-22T18:40:01Z
- **Tasks:** 2/2 completed
- **Files modified:** 4 created (1 migration, 3 test files)

## Accomplishments
- Applied migration 248 to the live `indicagent` DB: `alpha_strategy_scores` (SCORE-01's per-decile aggregation write target, PK `(symbol, tf, regime, alpha_score_decile, run_ts)`) and `gate_evaluations` (SCORE-02/SCORE-03's one-row-per-gate-run write target, loose `jsonb` evidence column) both confirmed to exist via `to_regclass`
- Seeded `alpha.scoring.min_sharpe=0.5`, `alpha.scoring.max_drawdown_ratio=0.25` (PRE-REGISTERED gate thresholds, SHADOW-REVIEW.md criteria 3/4) and `alpha.scoring.min_ic_alpha_score_corr=0.3` (DIAGNOSTIC-ONLY monotonicity reference) into `config_schema`/`config_state`/`config_history`, `changed_by='migration_248'` matching the actual applied filename
- Confirmed the four pre-existing `alpha.scoring.*` keys (`min_strategy_n=30`, `bootstrap_max_n=5000`, `bootstrap_batch=1000`, `bootstrap_random_state=42`) unchanged
- Created three Wave 0 test files (10 named stub functions total) that collect cleanly under `pytest --collect-only` and fail RED under execution, naming every concrete target Wave 2's 148-02/148-03/148-04 build plans must fill in
- Verified all six VALIDATION.md `-k` target substrings (`corr`, `oos_start`, `methodology`, `regime_stratified`, `dry_run`, `payload_shape`) each match at least one function name
- Confirmed zero regressions: full `tests/unit/` suite shows exactly 10 failures, all from the three new Wave 0 stub files, no other test affected

## Task Commits

Each task was committed atomically:

1. **Task 1: Migration for alpha_strategy_scores + gate_evaluations tables and missing alpha.scoring.* APR keys** - `0ac4a666` (feat)
2. **Task 2: Wave 0 test scaffolds for SCORE-01/02/03** - `c32df63a` (test)

## Files Created/Modified
- `production/migrations/248_alpha_scoring_gate_tables.sql` - `CREATE TABLE IF NOT EXISTS alpha_strategy_scores` + `gate_evaluations`, plus the three-key APR seed triple; applied to the live DB
- `tests/unit/test_alpha_scorer.py` - SCORE-01 Wave 0 stubs: decile bucketing + `min_strategy_n` filter, `ic_alpha_score_corr` monotonicity
- `tests/unit/test_oos_gate1_signal_eval.py` - SCORE-02 Wave 0 stubs: fail-loud `oos_start` guard, Fisher-z-CI methodology, dry-run escape hatch, evidence payload shape
- `tests/unit/test_score03_gate2_execution_eval.py` - SCORE-03 Wave 0 stubs: champion 143.1-08 number citation, regime-stratified companion requirement, dry-run escape hatch, evidence payload shape

## Decisions Made
- Migration number 248 was re-verified live immediately before writing the file and again immediately before applying it (`ls production/migrations/ | sort -V | tail -5`), per the plan's own warning about repeated concurrent-session collisions on this exact mechanism. No collision occurred this run.
- Followed the plan's exact provenance-class split for the three new APR keys rather than treating all three uniformly as gate thresholds — `min_ic_alpha_score_corr`'s `config_schema` description explicitly states "DIAGNOSTIC-ONLY, not a gate threshold" and omits the "not tunable post-hoc" gate-threshold framing the other two use.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Symlinked the worktree's missing `.venv` to the main repo's shared venv**
- **Found during:** Task 2 (running `pytest`/pre-commit hooks)
- **Issue:** This worktree has no `.venv` (gitignored per project convention — a known project gotcha), so `pytest`, `ruff`, and `black` were all unavailable via the worktree's own `${REPO_ROOT}/.venv/bin/*` paths the pre-commit hook and this agent's own commands expect.
- **Fix:** Created a plain symlink `${WORKTREE_ROOT}/.venv -> /home/bg/dev/indicagent/.venv` (the main repo's already-installed, already-correct venv). This is a symlink to shared, already-installed tooling — not a new package install, so it is not subject to the package-manager-install exclusion in Rule 3.
- **Files modified:** none tracked (the symlink itself is gitignored, matching `.venv`'s existing `.gitignore` entry)
- **Verification:** `.venv/bin/ruff --version` and `.venv/bin/black --version` both resolved; pre-commit hook's ruff/black checks passed on the Task 2 commit
- **Committed in:** N/A (untracked, gitignored — no commit needed)

**2. [Rule 3 - Blocking] Renamed duplicate `test_dry_run_writes_nothing` function names**
- **Found during:** Task 2 (first commit attempt)
- **Issue:** The plan's own action text specified the identical function name `test_dry_run_writes_nothing` in both `test_oos_gate1_signal_eval.py` and `test_score03_gate2_execution_eval.py`. The project's `check_duplicate_tests` pre-commit hook rejects any test function name duplicated across files in the same test directory, blocking the commit.
- **Fix:** Renamed to `test_gate1_dry_run_writes_nothing` (SCORE-02 file) and `test_gate2_dry_run_writes_nothing` (SCORE-03 file). The `dry_run` substring VALIDATION.md's `-k dry_run` target requires is preserved in both names.
- **Files modified:** `tests/unit/test_oos_gate1_signal_eval.py`, `tests/unit/test_score03_gate2_execution_eval.py`
- **Verification:** Re-ran `pytest --collect-only` (10 tests, 0 errors) and `-k dry_run --collect-only` (1 match per file); pre-commit's duplicate-test-names check passed on retry
- **Committed in:** `c32df63a` (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 3 - blocking issues preventing task completion)
**Impact on plan:** Both fixes were mechanical (environment tooling access, test-name disambiguation); no scope creep, no change to any table schema, APR key, or test assertion the plan specified.

## Issues Encountered
None beyond the two auto-fixed blocking issues documented above.

## Known Stubs

Per the plan's own design, all three new test files are intentional Wave 0 stubs — every one of the 10 test functions bodies is `pytest.fail("Wave 0 stub - implemented in Wave 2 SCORE build plan")`. This is not a gap; it is this plan's deliverable (RED-by-construction scaffolding for Wave 2's 148-02/148-03/148-04 build plans). No production code (`services/alpha_scorer.py`, `scripts/ops/corpus/ops_oos_gate1_signal_eval.py`, `scripts/analysis/score03_gate2_execution_eval.py`) exists yet — that is explicitly Wave 2 scope, not this plan's.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

`alpha_strategy_scores`, `gate_evaluations`, and all three `alpha.scoring.*` APR keys are live in the production DB — Wave 2 plans (148-02/148-03/148-04) can now write to both tables and read all seven `alpha.scoring.*` keys (four pre-existing + three seeded here) without any further schema work. The three Wave 0 test files give Wave 2 a concrete, named RED-to-GREEN target for each of SCORE-01/02/03 with zero import-order surprises (no module-scope imports of not-yet-built modules). No blockers identified for Wave 2.

---
*Phase: 148-alpha-scoring-system-planned*
*Completed: 2026-07-22*
