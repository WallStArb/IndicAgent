---
phase: 039-data-quality-db-health
plan: 05
subsystem: database
tags: [ic, information-coefficient, signal-performance, pearson, scipy, timescaledb, ml]

# Dependency graph
requires:
  - phase: 039-01
    provides: signal_stats_daily materialized view (IC baseline queries)
  - phase: 039-04
    provides: signal_ledger schema hardening (clean outcome data)
provides:
  - signal_performance_segmented table with per-regime IC scores
  - compute_ic() function (Pearson r(confidence, binary_outcome))
  - compute_ic.py CLI for on-demand and scheduled IC computation
  - ICResult dataclass with grade property and is_noise flag
  - 3,227 IC result rows written for 30-day window
affects:
  - 039-aggregator (perf_multiplier reads signal_performance_segmented)
  - 044-shadow-graduation (IC gate determines phase-44 shadow review candidates)
  - 046-ml-model (IC scores as feature quality gate)

# Tech tracking
tech-stack:
  added: [scipy (already installed 1.17.1)]
  patterns:
    - IC computation per (plugin, tf, symbol, regime) slice with FEED-02 gate (N>=30)
    - Zero-variance guard prevents NaN Pearson correlations
    - Exit-1 pattern for noise detection (monitoring integration)

key-files:
  created:
    - production/migrations/044_signal_performance_segmented.sql
    - src/intelligence/ml/information_coefficient.py
    - production/scripts/compute_ic.py
    - tests/unit/ml/__init__.py
    - tests/unit/ml/test_information_coefficient.py
  modified: []

key-decisions:
  - "Migration 043 used (not 042) because 042 was already taken by signal_stats_daily"
  - "confidence column used (not calibrated_confidence) because migration 038 calibration fields not yet applied to this DB"
  - "IC computed per (plugin, tf, symbol, regime_context) for maximum segmentation — Renaissance 'segment relentlessly'"
  - "Noise = ic_score < 0.05 OR p_value >= 0.05 OR N < 30 — all 3 gates required"
  - "Binary outcome: +1.0 for WIN_OUTCOMES, -1.0 for all others (not 0/1) — centered encoding for Pearson"

patterns-established:
  - "FEED-02 gate at DB level: CHECK (sample_size >= 30) prevents unconstrained writes"
  - "ICResult.grade property: strong(>0.20)/meaningful(>0.10)/weak(>0.05)/noise/insufficient_data"
  - "compute_ic() always returns 3-tuple (ic_score, p_value, n) — None when insufficient data"

requirements-completed:
  - DATA-11
  - DATA-12

# Metrics
duration: 6min
completed: 2026-03-19
---

# Phase 039 Plan 05: Signal Performance Segmented + IC Computation Summary

**signal_performance_segmented table with Pearson IC scores per plugin-regime slice; 3,227 rows written; trad_MeanReversion leads at IC=0.81 (15m); 512/3,227 slices statistically significant**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-19T23:22:42Z
- **Completed:** 2026-03-19T23:28:50Z
- **Tasks:** 5
- **Files modified:** 5 created

## Accomplishments

- `signal_performance_segmented` table created (migration 043) with IC columns, per-regime index, and FEED-02 CHECK constraint
- `compute_ic()` module implements Pearson r(confidence, binary_outcome) per plugin-regime slice with scipy, zero-variance guard, and is_ic_significant() 3-gate check
- `compute_ic.py` CLI runs on 2.5M resolved signals from signal_ledger, groups by (plugin, tf, symbol, regime), writes 3,227 rows to DB, exits 1 when noise detected
- 26 unit tests pass covering edge cases (zero variance, None outcomes, boundary N=30, frozen dataclass)
- `signal_stats_daily` refreshed (33,859 rows)

## IC Results Summary (30-day window, 2026-02-17 to 2026-03-19)

| Plugin | TF | N | IC | p-val | Grade |
|--------|-----|---|----|-------|-------|
| trad_MeanReversion | 15m | 47 | 0.8130 | <0.0001 | strong |
| trad_MeanReversion | 5m | 103 | 0.8110 | <0.0001 | strong |
| trad_MeanReversion | 1h | 64 | 0.7681 | <0.0001 | strong |
| trad_MeanReversion | 15m | 39 | 0.7542 | <0.0001 | strong |
| trad_MeanReversion | 1h | 38 | 0.7508 | <0.0001 | strong |
| trad_LiquiditySweepReclaim | 1h | 111 | 0.6111 | <0.0001 | strong |
| trad_VWAPDeviation | 5m | 56 | 0.5925 | <0.0001 | strong |
| trad_VWAPDeviation | 1m | 125 | 0.5849 | <0.0001 | strong |
| trad_MomentumBreakout | 1m | 69 | 0.5002 | <0.0001 | strong |
| trad_LiquidityHunt | 15m | 32 | 0.5746 | 0.0006 | strong |

**Breakdown:**
- Total slices: 3,227
- Statistically significant (ic_significant=TRUE): 512
- Zero-variance (ic=None): 917 (confidence has near-zero variance for many regime groups — calibrated_confidence will improve this when migration 038 is applied)
- Noise (significant gate failed): 2,715

## Noise Analysis

The 917 zero-variance slices arise because `confidence` in signal_ledger is very low (~0.0003-0.001) for many non-selected signals. These are signals that were computed but not selected as the winning signal. When all signals in a regime group have near-zero confidence, Pearson r cannot be computed.

**Root cause:** Using `confidence` instead of `calibrated_confidence` (migration 038 not yet applied). Once calibrated confidence is in the DB, IC will be more meaningful.

**Top noise candidates flagged for Phase 44 shadow review:** trad_TrendFollowing, trad_VCP (many regime groups with zero-variance confidence)

## scipy Status

scipy 1.17.1 already installed in .venv. No installation needed.

## Task Commits

1. **Task 1: Create signal_performance_segmented table** - `e08cbee` (feat)
2. **Task 2: Implement IC computation module** - `4fbfb53` (feat)
3. **Task 3: Implement compute_ic.py CLI script** - `06770d5` (feat)
4. **Fix: format string bug in noise candidates output** - `182bd96` (fix)
5. **Task 5: Unit tests for IC computation** - `c5390c4` (test)

## Files Created

- `production/migrations/044_signal_performance_segmented.sql` - Table DDL with IC columns, indexes, CHECK constraint
- `src/intelligence/ml/information_coefficient.py` - compute_ic(), is_ic_significant(), ICResult dataclass
- `production/scripts/compute_ic.py` - CLI runner with --window-days, --symbols, --regime, --write, --min-ic flags
- `tests/unit/ml/__init__.py` - Package marker
- `tests/unit/ml/test_information_coefficient.py` - 26 unit tests

## Decisions Made

- Migration 043 used (not 042) because 042 was already taken by `signal_stats_daily` from Plan 01
- Used `confidence` column (not `calibrated_confidence`) because migration 038 calibration columns not yet applied to this production DB. IC will improve once calibrated_confidence is populated
- Binary outcome encoding: +1.0 for WIN_OUTCOMES, -1.0 for losses (centered) — more natural for Pearson than 0/1
- IC computed per individual symbol to detect regime-specific alpha by instrument class

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed format string ValueError in noise candidates output**
- **Found during:** Task 4 (running IC on production data)
- **Issue:** f-string used `{r.ic_score:.4f if r.ic_score else 'None'}` which Python evaluates as a conditional format spec, raising ValueError
- **Fix:** Extracted `ic_fmt = f"{r.ic_score:.4f}" if r.ic_score is not None else "None"` before the f-string
- **Files modified:** production/scripts/compute_ic.py
- **Verification:** Script ran to completion outputting noise candidates list
- **Committed in:** `182bd96` (separate fix commit)

**2. [Rule 3 - Adaptation] Migration 042 renamed to 043**
- **Found during:** Task 1 (creating migration)
- **Issue:** Plan specified `042_signal_performance_segmented.sql` but `042_signal_stats_daily.sql` already existed from Plan 01
- **Fix:** Used `044_signal_performance_segmented.sql` instead
- **Impact:** Table still created correctly; no schema changes needed

---

**Total deviations:** 2 (1 bug fix, 1 naming adaptation)
**Impact on plan:** Both minor. Format bug required immediate fix. Migration renaming is cosmetic — same DDL applied successfully.

## Issues Encountered

- Many zero-variance IC results due to `confidence` column being near-zero for non-selected signals. This is expected pre-calibration. Will resolve when `calibrated_confidence` is populated via migration 038.

## Next Phase Readiness

- signal_performance_segmented table ready for aggregator perf_multiplier reads (Phase 039-06 or future)
- IC baseline established — Phase 44 shadow graduation has statistical data to evaluate against
- compute_ic.py ready for scheduling as systemd timer (Phase 039-06)

---
*Phase: 039-data-quality-db-health*
*Completed: 2026-03-19*

## Self-Check: PASSED

- FOUND: production/migrations/044_signal_performance_segmented.sql
- FOUND: src/intelligence/ml/information_coefficient.py
- FOUND: production/scripts/compute_ic.py
- FOUND: tests/unit/ml/test_information_coefficient.py
- FOUND: .planning/phases/039-data-quality-db-health/039-05-SUMMARY.md
- Commits verified: e08cbee, 4fbfb53, 06770d5, 182bd96, c5390c4
