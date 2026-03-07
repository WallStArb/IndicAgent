---
phase: 15-validated-alpha
plan: 01
subsystem: validation
tags: [scipy, statsmodels, pandas, psycopg2, argparse, pearson, adf, statistical-validation, promotion-gate]

# Dependency graph
requires:
  - phase: 14-feedback-loop
    provides: setup_performance promotion pattern (N>=30 gate consistency)
  - phase: 13-data-completeness
    provides: intelligence_features with i1/i2/i5 JSONB columns holding plugin outputs
provides:
  - validate_alpha.py CLI with Pearson r > 0 + p < 0.05 + N >= 30 gate
  - Auto-trigger of historical_backfill.py --replay-only when data is sparse
  - docs/validation/ audit trail directory for permanent promotion records
  - --promote flag that patches register_plugins.py at 3 sentinel points
  - Secondary candlestick_pattern_setup.py patch for patt_CandlestickPatterns
affects:
  - 15-02 through 15-05 (each plan terminates with validate_alpha.py --promote)
  - future alpha source additions (all must pass this gate)

# Tech tracking
tech-stack:
  added:
    - statsmodels==0.14.6 (dev dependency via uv; adfuller for ADF stationarity test)
    - patsy==1.0.2 (statsmodels dependency)
  patterns:
    - Statistical gate: Pearson r > 0, p < 0.05, N >= 30 — Renaissance significance floor
    - Forward return alignment: pct_change(N).shift(-N) aligns bar-t signal with FUTURE N-bar return
    - TDD RED/GREEN: test file committed failing, then implementation committed to pass
    - Correlation with full series (include non-signal bars as 0) avoids constant-input NaN
    - Sentinel-based file patching: # END TIER_I1 etc. anchors for safe register_plugins.py promotion

key-files:
  created:
    - production/scripts/validate_alpha.py
    - tests/unit/scripts/test_validate_alpha.py
    - docs/validation/.gitkeep
  modified:
    - pyproject.toml (statsmodels dev dependency added)
    - uv.lock

key-decisions:
  - "Correlation computed over ALL bars (signal=1 and signal=0) not just signal-fired bars — avoids constant-input NaN problem when binary indicator fires consistently"
  - "ADF test runs on forward return series (not signal series) — more meaningful stationarity test; informational only, not a gate"
  - "N gate counts bars where indicator fired (direction != 0), not length of correlation series"
  - "statsmodels not pre-installed in .venv; added as dev dependency via uv add --dev"
  - "Test data mocks _compute_stats directly for gate logic tests (test_gate_logic_pass, test_report_written) to avoid brittle synthetic data correlation issues"

patterns-established:
  - "validate_alpha.py is the load-bearing gate for Phase 15 — Plans 2-5 each terminate with --promote"
  - "register_plugins.py patching: sentinel-comment anchors preferred; fallback to last-pattern regex if sentinels absent"
  - "Validation report JSON always written on every run (pass or fail) — permanent audit trail in docs/validation/"

requirements-completed: [ALPHA-01]

# Metrics
duration: 10min
completed: 2026-03-07
---

# Phase 15 Plan 01: Validated Alpha Gate Summary

**Statistical promotion gate (Pearson r>0, p<0.05, N>=30) with auto-backfill, sentinel-patched register_plugins.py, and JSON audit trail — load-bearing infrastructure for Plans 2-5**

## Performance

- **Duration:** 10 min
- **Started:** 2026-03-07T09:27:58Z
- **Completed:** 2026-03-07T09:38:00Z
- **Tasks:** 2 (TDD: RED then GREEN)
- **Files modified:** 5

## Accomplishments

- `validate_alpha.py` CLI validates any registered plugin against forward close-to-close returns with Pearson correlation gate
- Auto-triggers `historical_backfill.py --replay-only` when fewer than 30 qualifying bars exist in `intelligence_features`
- `--promote` hard-blocked on gate failure; on pass, patches `register_plugins.py` at import + registration + tier-list points using sentinel fallback strategy
- Secondary patch for `patt_CandlestickPatterns` also updates `candlestick_pattern_setup.py` named reads and candidates list
- `docs/validation/.gitkeep` creates git-tracked audit trail directory; every run writes JSON report

## Task Commits

1. **Task 1: Write failing tests (TDD RED)** - `6c68cc6` (test)
2. **Task 2: Implement validate_alpha.py (TDD GREEN)** - `a6d7fb0` (feat)

## Files Created/Modified

- `production/scripts/validate_alpha.py` — CLI gate: argparse, DB query, Pearson correlation, ADF, FPR, JSON report, --promote patch logic
- `tests/unit/scripts/test_validate_alpha.py` — 8 unit tests covering all gate conditions + auto-backfill + report + forward alignment
- `docs/validation/.gitkeep` — git-tracked audit trail directory
- `pyproject.toml` — statsmodels dev dependency added
- `uv.lock` — updated

## Decisions Made

- **Correlation over all bars:** Binary signals produce a constant series (all 1.0) if only signal-fired bars are included, causing Pearson NaN. Fix: include all bars with valid forward returns, using direction=0 for non-firing bars. N gate counts signal-fired bars separately.
- **ADF on returns not signal series:** Running ADF on the binary signal direction series (mostly zeros + ones) gives a spurious result; forward return series is the meaningful stationarity test.
- **statsmodels as dev dependency:** Research doc said it was pre-installed but it was not. Added via `uv add --dev statsmodels`. No existing tests broken.
- **Test mocking strategy:** Gate logic tests (pass/fail verdicts) mock `_compute_stats` directly to inject known r/p values. Real correlation tests (negative r, forward alignment) use synthetic data with the correct field names.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] statsmodels not installed in .venv**
- **Found during:** Task 2 (implementation attempted to import statsmodels)
- **Issue:** Research doc stated statsmodels was present; actual .venv had no statsmodels module
- **Fix:** `uv add --dev statsmodels` installed statsmodels==0.14.6 + patsy==1.0.2
- **Files modified:** pyproject.toml, uv.lock
- **Verification:** `.venv/bin/python -c "import statsmodels"` succeeds
- **Committed in:** a6d7fb0 (Task 2 commit)

**2. [Rule 1 - Bug] Constant-input NaN in Pearson correlation**
- **Found during:** Task 2 (test_gate_logic_pass failing with r=nan)
- **Issue:** Including only signal-fired bars (direction=1.0) produces a constant series → pearsonr returns NaN
- **Fix:** Changed correlation approach to include ALL bars (direction=0 for non-signal bars); N gate counts signal-fired bars separately; ADF runs on returns series not signal series
- **Files modified:** production/scripts/validate_alpha.py
- **Verification:** test_gate_logic_pass passes, test_forward_return_alignment passes
- **Committed in:** a6d7fb0 (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (1 blocking dependency, 1 correlation logic bug)
**Impact on plan:** Both fixes necessary for correctness. No scope creep. All 8 tests pass.

## Issues Encountered

- `test_gate_logic_pass` and `test_report_written` initially used synthetic row data with wrong field names (generic "test_field" instead of "deriv_osc_cross_bullish") — fixed by parametrizing the test helper with the correct field name from the PLUGIN_REGISTRY
- `test_settings.py::test_get_base_symbols` is a pre-existing failure (VX removed from settings.py in external changes) — out of scope, not caused by this plan

## User Setup Required

None — no external service configuration required. `docs/validation/` directory is git-tracked. Reports are written there automatically on `--promote` runs.

## Next Phase Readiness

- Plan 15-01 complete: `validate_alpha.py` is the load-bearing gate for all remaining Phase 15 plans
- Plans 15-02 through 15-05 can proceed: each implements a new alpha source (DerivOsc I2, Candlestick Tier 1 x10, MACD accel, AC Oscillator I1) and terminates with `validate_alpha.py --plugin X --days 90 --promote`
- Promotion is data-dependent (requires historical data in `intelligence_features`); auto-backfill handles sparse data automatically
- No blockers

---
*Phase: 15-validated-alpha*
*Completed: 2026-03-07*
