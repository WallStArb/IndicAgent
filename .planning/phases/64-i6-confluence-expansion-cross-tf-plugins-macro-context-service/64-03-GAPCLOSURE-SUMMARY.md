---
plan: 64-03-GAPCLOSURE
phase: 64-i6-confluence-expansion-cross-tf-plugins-macro-context-service
status: complete
completed: 2026-04-27
self_check: PASSED
---

## Summary

Created automated backtest validation infrastructure for all 5 cross-TF I6 confluence plugins. Implements the D-25 Renaissance validation gate (IC > 0.05 AND p < 0.01 Bonferroni-corrected AND N >= 30) with no human checkpoint.

## What Was Built

### tools/backtest_cross_tf_plugins.py (148 lines)
Backtest runner for all 5 cross-TF plugins (CrossTFMomentumDivergence, CrossTFSRConfluence, CrossTFRegimeAgreement, SqueezeExpansionDivergence, CrossTFOrderFlowAlignment). Uses `backtest_i6_plugin()` infrastructure from Plan 64-00. Fixed column naming (multi-TF framing) in underlying `backtest_i6_plugin.py`.

### tools/validate_i6_backtest.py (336 lines — extended)
Extended with full D-25 automated validation gate:
- `ValidationResults` dataclass with `decision` field (VALIDATED / TWEAK / KILL)
- IC > 0.05 AND p < 0.01 (Bonferroni-corrected for 5 tests) AND N >= 30 = VALIDATED
- IC 0.02–0.05 = TWEAK; IC < 0.02 = KILL
- Regime-segmented statistics (D-26: trending vs ranging)
- `validate_all_plugins()` batch validation function
- `print_validation_report()` human-readable output

### tools/feature_selection.py (110 lines)
Renaissance feature selection tool applying KEEP/TWEAK/KILL thresholds to validation results. Automated decision: if ≥1 feature VALIDATED → deploy to shadow mode, proceed to Plan 04 macro factors. If 0 validated → abandon cross-TF direction per Renaissance discipline.

## Fixes Applied
- `backtest_i6_plugin.py`: corrected column names for multi-TF output framing
- `validate_backtest_results()`: fixed insufficient-data paths to return `decision=KILL` (not `UNKNOWN`)

## Backtest Run Status
Scripts created and compile cleanly. Live backtest execution requires active TimescaleDB data from signal_ledger (pnl_r outcomes). The infrastructure is complete — actual IC values will be computed when the service has accumulated 30+ signal outcomes post-shadow-deployment.

## Key Files

| File | Lines | Purpose |
|------|-------|---------|
| `tools/backtest_cross_tf_plugins.py` | 148 | Backtest runner for 5 cross-TF plugins |
| `tools/validate_i6_backtest.py` | 336 | D-25 automated validation gate |
| `tools/feature_selection.py` | 110 | Renaissance KEEP/TWEAK/KILL selection |

## Self-Check

- [x] `backtest_cross_tf_plugins.py` created with `backtest_all_cross_tf_plugins()` — all 5 plugins
- [x] D-25 validation gate implemented: IC > 0.05 AND p < 0.01 AND N >= 30 = VALIDATED
- [x] Bonferroni correction applied (alpha = 0.01 for 5 tests)
- [x] Regime-segmented validation (D-26) implemented
- [x] Automated decision (no human checkpoint) — VALIDATED / TWEAK / KILL
- [x] Feature selection: KEEP/TWEAK/KILL based on IC thresholds
- [x] All 3 files compile cleanly (py_compile verified)
- [x] 5 commits: creation + fixes
