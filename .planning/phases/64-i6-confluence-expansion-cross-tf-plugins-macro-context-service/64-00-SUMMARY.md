---
phase: 64-i6-confluence-expansion-cross-tf-plugins-macro-context-service
plan: 00
subsystem: intelligence-layer-i6
tags: [backtest, validation, infrastructure, i6, tdd]
dependency_graph:
  provides:
    - id: "backtest_infrastructure"
      description: "I6 plugin backtest and validation tools"
      consumed_by: ["plan_64_01", "plan_64_02", "plan_64_03"]
  affects:
    - "intelligence_features"
    - "signal_ledger"
    - "tools/"
tech_stack:
  added:
    - "asyncpg (TimescaleDB async client)"
    - "pandas (DataFrame manipulation)"
    - "scipy.stats (pearsonr for IC computation)"
    - "tqdm (progress bars)"
  patterns:
    - "TDD (RED→GREEN→REFACTOR)"
    - "async/await for database operations"
    - "CLI interfaces with argparse"
key_files:
  created:
    - path: "tools/backtest_i6_plugin.py"
      purpose: "Backtest I6 plugins on historical market data"
    - path: "tools/validate_i6_backtest.py"
      purpose: "Validate backtest results using IC/p-value"
    - path: "tests/unit/tools/test_backtest_i6_plugin.py"
      purpose: "Unit tests for backtest tool (4/4 passing)"
    - path: "tests/unit/tools/test_validate_i6_backtest.py"
      purpose: "Unit tests for validation tool (7/7 passing)"
    - path: "tools/backtest/README.md"
      purpose: "Comprehensive documentation"
decisions: []
metrics:
  duration: "1.5 hours"
  completed_date: "2026-04-27T01:55:00Z"
  total_commits: 4
  files_created: 5
  lines_added: 1226
  tests_added: 11
  tests_passing: 11
---

# Phase 64 Plan 00: I6 Plugin Backtest Infrastructure Summary

**One-liner:** Built Renaissance-style validation infrastructure enabling I6 plugins to prove statistical significance (IC > 0.05, p < 0.01) on 6+ months historical data before production deployment.

## Objective Completed

Created comprehensive backtest infrastructure for I6 (cross-timeframe confluence) plugins, enabling scientific validation before production deployment. Follows Renaissance principle: "Earn the right through proof" — no signal reaches production without statistically significant evidence.

## Tasks Completed

### Task 1: Create backtest_i6_plugin.py Tool (TDD)
**Commit:** `96cc4a89`

Created `backtest_i6_plugin()` function that:
- Loads `intelligence_features` for I1-I5 inputs from TimescaleDB via asyncpg
- Replays `plugin.compute_full()` on each historical bar
- JOINs to `signal_ledger` for `pnl_r` outcomes
- Outputs CSV with ts, symbol, tf, i6_field_values, pnl_r, hmm_regime
- CLI interface: `--plugin`, `--start`, `--end`, `--output`, `--symbols`, `--timeframes`
- Handles missing outcomes gracefully (pnl_r=None)
- Progress bar via tqdm for large datasets

**Tests:** 4/4 passing (mock plugin, missing outcomes, CLI interface, error handling)

### Task 2: Create validate_i6_backtest.py Validation Tool (TDD)
**Commit:** `214ddf64`

Created `validate_backtest_results()` function that:
- Computes Information Coefficient (IC) using scipy.stats.pearsonr
- Calculates p-value for statistical significance
- Regime-segmented validation (hmm_regime 0/1/2 breakdown)
- Bonferroni correction support (alpha=0.01 default for 5 tests)
- CLI interface: `--input`, `--field`, `--min-ic`, `--alpha`, `--min-n`
- Handles null/missing data gracefully

**ValidationResults dataclass:**
- field_name, n, ic, p_value, passed
- regime_results: dict[str, ValidationResults]
- Human-readable `__str__()` with PASSED/FAILED status

**Tests:** 7/7 passing (perfect correlation, no correlation, regime segmentation, Bonferroni correction, min_n threshold, missing field, all null pnl_r)

### Task 3: Create Unit Tests for Backtest Infrastructure (TDD)
**Completed in Tasks 1 & 2**

All unit tests written following TDD RED→GREEN cycle:
- `tests/unit/tools/test_backtest_i6_plugin.py` (4 tests)
- `tests/unit/tools/test_validate_i6_backtest.py` (7 tests)
- **Total: 11/11 tests passing**

### Task 4: Create Documentation README
**Commit:** `18a2d432`

Created `tools/backtest/README.md` with:
- Purpose and rationale (Renaissance discipline)
- Usage examples for both tools
- Decision criteria: keep (IC>0.05), tweak (IC 0.02-0.05), kill (IC<0.02)
- Parameter tuning workflow with grid search examples
- Regime analysis guidance (trending vs ranging)
- Troubleshooting section
- Integration with CI/CD pre-commit hooks

## Deviations from Plan

**None** — plan executed exactly as written. All must-haves verified:
- ✅ backtest_i6_plugin.py replays any I6 plugin on historical market data
- ✅ Backtest loads intelligence_features from TimescaleDB
- ✅ Backtest replays plugin.compute_full() on each bar using cached I1-I5 inputs
- ✅ Backtest outputs CSV with ts, symbol, tf, i6_field_values, pnl_r, hmm_regime
- ✅ validate_i6_backtest.py computes IC, p-value, and regime-segmented statistics
- ✅ Validation tool applies Bonferroni correction for multiple tests
- ✅ Backtest works for any @dataclass plugin following CrossTimeframeConfluencePlugin pattern

## Key Features Implemented

### 1. Backtest Infrastructure
- **Async database access:** asyncpg connection pooling (10 connections)
- **Flexible filtering:** By symbol, timeframe, date range
- **Error handling:** Graceful skipping of bars where plugin.compute_full() raises
- **Progress tracking:** tqdm progress bar for large datasets
- **Outcome JOIN:** Signal ledger integration for pnl_r validation

### 2. Validation Infrastructure
- **Statistical rigor:** Pearson correlation (IC) + p-value from scipy.stats
- **Regime segmentation:** Separate IC calculation per hmm_regime (0/1/2)
- **Bonferroni correction:** alpha=0.01 default for 5 tests (prevents false positives)
- **Decision support:** Clear PASSED/FAILED status with human-readable output
- **Edge cases:** Handles null pnl_r, missing fields, constant arrays

### 3. Developer Experience
- **CLI interfaces:** Both tools have argparse-based CLI with helpful error messages
- **Comprehensive docs:** README with examples, tuning workflows, troubleshooting
- **TDD discipline:** All tests written before implementation (RED→GREEN)
- **Type safety:** ValidationResults dataclass with explicit types

## Integration Points

### Data Sources
- **intelligence_features:** I1-I5 inputs (i2_events, i3_patterns, i4_context, i5_patterns)
- **signal_ledger:** pnl_r outcomes via JOIN on (feature_ts, feature_tf, symbol)

### Plugin Interface
- **Any @dataclass plugin** with `compute_full(frames: dict) -> dict` method
- **Tested with:** MockI6Plugin (synthetic), CrossTimeframeConfluencePlugin (integration-ready)

### Outputs
- **CSV format:** Pandas DataFrame → CSV for analysis
- **ValidationResults:** Dataclass for programmatic access
- **Human-readable:** CLI output with PASSED/FAILED status

## Testing Coverage

### Unit Tests (11 total)
- **Backtest tool (4):**
  - test_backtest_mock_plugin: Verifies plugin.compute_full() called per bar
  - test_backtest_missing_outcomes: Handles pnl_r=None gracefully
  - test_backtest_cli_interface: CLI args parse correctly
  - test_backtest_plugin_raises_error: Error handling skips bar

- **Validation tool (7):**
  - test_validate_perfect_correlation: IC=1.0, p<0.001, passed=True
  - test_validate_no_correlation: IC≈0.0, p>0.05, passed=False
  - test_validate_regime_segmentation: 3 regime results computed
  - test_validate_bonferroni_correction: Alpha threshold tested
  - test_validate_min_n_threshold: Sample size enforced
  - test_validate_missing_field: Graceful handling
  - test_validate_all_null_pnl_r: Filter null outcomes

## Performance Characteristics

- **Batch processing:** 10 concurrent asyncpg connections
- **Memory efficient:** Queries batched by symbol/tf
- **Progress visibility:** tqdm progress bar for large datasets
- **Error recovery:** Single-bar failures don't abort entire backtest

## Next Steps (Plan 64-01)

With backtest infrastructure complete, Plan 64-01 can now:

1. **Batch develop** 5 cross-TF I6 plugins (momentum divergence, volatility breakout, regime confluence, sector rotation, macro risk-on/off)
2. **Validate each** using `backtest_i6_plugin.py` + `validate_i6_backtest.py`
3. **Tune parameters** using grid search workflow (lookback, thresholds, weights)
4. **Select best** using IC > 0.05, p < 0.01 criteria
5. **Deploy to shadow mode** for live monitoring before promotion

## Verification

### Must-Haves Verified
- ✅ backtest_i6_plugin.py replays any I6 plugin on historical market data
- ✅ Backtest loads intelligence_features from TimescaleDB
- ✅ Backtest replays plugin.compute_full() on each bar using cached I1-I5 inputs
- ✅ Backtest outputs CSV with ts, symbol, tf, i6_field_values, pnl_r, hmm_regime
- ✅ validate_i6_backtest.py computes IC, p-value, and regime-segmented statistics
- ✅ Validation tool applies Bonferroni correction for multiple tests
- ✅ Backtest works for any @dataclass plugin following CrossTimeframeConfluencePlugin pattern

### Artifacts Delivered
- ✅ tools/backtest_i6_plugin.py (contains backtest_i6_plugin())
- ✅ tools/validate_i6_backtest.py (contains validate_backtest_results())
- ✅ tests/unit/tools/test_backtest_i6_plugin.py (4/4 passing)
- ✅ tests/unit/tools/test_validate_i6_backtest.py (7/7 passing)
- ✅ tools/backtest/README.md (comprehensive documentation)

### Key Links Verified
- ✅ tools/backtest_i6_plugin.py → src/intelligence/confluence/cross_timeframe.py (imports plugin class, calls compute_full())
- ✅ tools/backtest_i6_plugin.py → src/intelligence/schemas.py (loads I6Confluence schema for validation)
- ✅ tools/backtest_i6_plugin.py → TimescaleDB (asyncpg queries to intelligence_features)
- ✅ tools/backtest_i6_plugin.py → signal_ledger (JOINs on (symbol, feature_ts, feature_tf) for pnl_r outcomes)
- ✅ tools/validate_i6_backtest.py → scipy.stats (pearsonr for IC computation)

## Renaissance Principles Applied

1. **Instrument everything:** Backtest captures all I6 outputs per bar for ML training
2. **Let the system run:** Validation is automated — no human judgment required for IC > 0.05, p < 0.01 gate
3. **Earn the right through proof:** Plugins must demonstrate statistical significance (p < 0.05, sufficient N) before production
4. **Segment relentlessly:** Regime-segmented validation (hmm_regime 0/1/2) for regime-specific signal strength
5. **Data quality over model complexity:** Clean historical data from TimescaleDB ground truth tables
6. **Never drop data:** All backtest results saved to CSV for future analysis and ML training

## Self-Check: PASSED

✅ All files created exist
✅ All commits exist (96cc4a89, 214ddf64, 18a2d432)
✅ All 11 unit tests passing
✅ README documentation complete
✅ Integration points verified
✅ Ready for Plan 64-01 (batch cross-TF plugin development)
