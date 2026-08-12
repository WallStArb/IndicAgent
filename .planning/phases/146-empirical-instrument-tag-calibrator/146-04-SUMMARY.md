---
phase: 146-empirical-instrument-tag-calibrator
plan: 04
subsystem: alpha
tags: [tag-calibrator, base-batch, bh-fdr, factor-math, asyncpg, otel]

# Dependency graph
requires:
  - phase: 146-01
    provides: tag taxonomy cleanup (real live tag names, definitional/measurable split seed)
  - phase: 146-02
    provides: measurement-contract schema (migration 238 -- tag_vocabulary/instrument_tags columns + alpha.tag_calibrator.* APR keys)
  - phase: 146-03
    provides: src/intelligence/statistics/factor_math.py (standardized_loading, loading_hac_pvalue, long_short_daily_returns, spy_realized_vol_factor)
provides:
  - services/tag_calibrator.py -- TagCalibrator(BaseBatch) generic 3-pass calibration engine
  - Pure, DB-free decision-logic functions (filter_measurable_tag_rows, measure_matrix, apply_run_level_fdr, decide_outcome) pinned by unit tests
  - tag_calibration_total{tag, outcome} OTel counter (F6.4)
affects: [147, tag-calibrator-live-runs, alpha-scoring-system]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Generic (symbol, factor_series, measurement_type) measurement contract loop -- never branches on tag category (D-12, T7)"
    - "Run-level BH-FDR: exactly one apply_bh_fdr call over the full p-vector, never per-hypothesis (F1)"
    - "consecutive_fails hysteresis before expiry (F2) -- mirrors EnsembleICEngine's own weekly re-run flicker-prevention rationale"
    - "Human-asserted instrument_tags rows are seed priors: never overwritten or auto-expired, only annotated on contradiction"
    - "Evidence JSONB carries discovery_state/first_measured_at -- no new schema column needed for the discovery_oos_days gate"

key-files:
  created:
    - services/tag_calibrator.py
    - tests/unit/test_tag_calibrator.py
  modified: []

key-decisions:
  - "Reused existing APR keys (alpha.ensemble.mv_condition_max, alpha.regime.realized_vol_window, alpha.regime.vix_z_window) instead of adding new alpha.tag_calibrator.* keys for condition_max/vol-proxy windows -- keeps TagCalibratorConfig at exactly the 7 fields the plan specified while still being APR-backed, not hardcoded"
  - "Human-asserted instrument_tags rows (source='human') are never converted to source='empirical' by a keep decision, and never expired by a fail decision -- only annotated on contradiction. Read literally from the plan's 'never write... human-only rows' instruction rather than allowing empirical measurements to silently overwrite curated human tags"
  - "discovery_oos_days enforcement is DB-column-free: tracked via evidence JSONB (first_measured_at + discovery_state), avoiding a new instrument_tags column or a separate pending-state table for a value this plan's must-haves don't require to gate downstream trust yet"
  - "apply_bh_fdr imported directly from ic_math (not re-exported via factor_math, since Plan 03's factor_math.py __all__ doesn't include it) -- sanctioned explicitly by the plan's own interfaces section"

requirements-completed: [TAG-01, TAG-03]

# Metrics
duration: ~35min
completed: 2026-07-17
---

# Phase 146 Plan 04: TagCalibrator Engine Summary

**Generic 3-pass TagCalibrator(BaseBatch) oneshot measures the full instrument x measurable-tag matrix off tag_vocabulary's (symbol, factor_series, measurement_type) contract, applies run-level BH-FDR, and decides keep/expire/discover per pair with consecutive_fails hysteresis -- replacing human-asserted tags with measured, falsifiable OLS loadings.**

## Performance

- **Duration:** ~35 min
- **Completed:** 2026-07-17
- **Tasks:** 2/2
- **Files modified:** 2 (both new)

## Accomplishments
- `services/tag_calibrator.py`: `TagCalibratorConfig` (frozen, `.from_apr`, 7 APR fields) + `TagCalibrator(BaseBatch)` with a fully generic 3-pass loop (measure -> correct once -> decide), reading the measurement contract off `tag_vocabulary` without ever branching on tag category
- Self-regression skip (F6.1), definitional-tag exclusion, and the null-factor_series defensive guard (Blocker-2/T-146-11) are all pure, unit-tested functions independent of any DB connection
- Long-short factor series (HYG-IEF, TIP-IEF, IEF-SHY, XLE-SPY) and the SPY_REALIZED_VOL vol-beta sentinel are built via `factor_math`/`breadth_vol` reuse, never re-derived
- Daily-return reads are exclusively against `market_data_ohlcv_tradeable` -- confirmed via `test_market_data_ohlcv_boundary.py` passing with zero new allow-list entries
- 10 unit tests (6 required + 4 supporting variants) pin the decision logic: self-regression skip, run-level FDR call-count (including the empty-input no-op case), expiry hysteresis (increment/expire/keep-resets/human-never-expires), vol-beta proxy reuse (including missing-SPY guard), definitional-tag exclusion, and null-factor_series skip

## Task Commits

Each task was committed atomically:

1. **Task 1: TagCalibrator(BaseBatch) -- config + 3-pass calibration loop + entrypoint** - `cb0ffbb1` (feat)
2. **Task 2: test_tag_calibrator.py -- decision-logic unit tests** - `6138681a` (test)

## Files Created/Modified
- `services/tag_calibrator.py` - TagCalibratorConfig + TagCalibrator(BaseBatch): pass-1 measurement matrix, pass-2 run-level BH-FDR, pass-3 keep/expire/discover decision engine, price-cache fetch (tradeable view only), UPSERT/annotation SQL, `__main__` entrypoint
- `tests/unit/test_tag_calibrator.py` - 10 decision-logic tests, no DB/network, synthetic price series + monkeypatch for the vol-proxy and BH-FDR call-count checks

## Decisions Made
- See `key-decisions` in frontmatter above (APR-key reuse, human-row protection, discovery_oos_days via evidence JSONB, apply_bh_fdr import source).

## Deviations from Plan

None — plan executed exactly as written. The four decisions above are implementation choices made within the plan's own stated flexibility (interfaces section explicitly sanctions the `apply_bh_fdr` import path; the plan's 7-field `TagCalibratorConfig` spec is satisfied by reusing existing APR keys for the two extra numeric inputs `standardized_loading`/`spy_realized_vol_factor` require rather than adding new ones), not corrections to broken plan instructions.

## Issues Encountered
- The worktree has no gitignored `.venv` (known GSD worktree limitation). Ran `ruff`/`pytest`/`black` via the main repo's `/home/bg/dev/indicagent/.venv/bin` on `PATH` against files inside the worktree — this works because a venv's interpreter and installed packages are location-independent of the files being linted/tested. No workaround of the pre-commit hook itself (`--no-verify` was never used); the hook's own `ruff`/`black` invocation succeeded once `PATH` included a real venv, and it auto-fixed/re-staged formatting as designed.
- `logs/` directory did not exist in the worktree, which the pre-commit hook's log redirect needs — created it (`mkdir -p logs`) before the first commit; this is untracked/gitignored infra, not a code change.

## User Setup Required

None - no external service configuration required. Note: this plan does not wire up a systemd timer (RESEARCH.md Open Question 1, resolved: all project timers are confirmed disabled as of 2026-07-02) -- a live dry-run of `python services/tag_calibrator.py` against the database is explicitly out of this plan's scope per its own `<verification>` section ("Live dry-run (manual, before any timer)").

## Next Phase Readiness
- `services/tag_calibrator.py` is code-complete and unit-tested; a live dry-run against a small symbol subset (inspecting written `instrument_tags` rows for `source='empirical'`, `weight` in `[0, 1]`, `loading`/`passes_fdr` populated) remains manual follow-up before any future timer/scheduling work, consistent with this plan's stated scope boundary.
- No blockers for sibling plan 146-05 (parallel wave 2) or subsequent phase work.

---
*Phase: 146-empirical-instrument-tag-calibrator*
*Completed: 2026-07-17*

## Self-Check: PASSED

- FOUND: `services/tag_calibrator.py`
- FOUND: `tests/unit/test_tag_calibrator.py`
- FOUND: `.planning/phases/146-empirical-instrument-tag-calibrator/146-04-SUMMARY.md`
- FOUND commit: `cb0ffbb1` (Task 1: TagCalibrator feat commit)
- FOUND commit: `6138681a` (Task 2: decision-logic tests commit)
- FOUND commit: `72cb4b73` (this summary's docs commit)
