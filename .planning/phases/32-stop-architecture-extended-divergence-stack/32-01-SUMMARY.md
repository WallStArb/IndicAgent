---
phase: 32-stop-architecture-extended-divergence-stack
plan: "01"
subsystem: signal-generation
tags: [stop-architecture, trade-framer, garch, fvg, signal-ledger, ml-features]
dependency_graph:
  requires: [31-03]
  provides: [stop_basis-classification, garch-adaptive-stops, fvg-stop-tier]
  affects: [signal_ledger, intelligence_features, all-i7-plugins]
tech_stack:
  added: []
  patterns: [stop-basis-classification, garch-vol-regime-scaling, proximity-gate]
key_files:
  created:
    - production/migrations/035_stop_basis_and_divergence_stack.sql
    - tests/unit/test_trade_framer.py
  modified:
    - src/intelligence/trading/trade_framer.py
    - src/intelligence/trading/signal_ledger.py
    - services/signal_generator_service.py
    - tests/unit/intelligence/test_signal_ledger.py
decisions:
  - "FVG as Priority 0 structural stop (beats demand/supply zone) — provides tighter structural reference for FVG-aligned setups"
  - "GARCH multiplier applied to effective_atr before all stop/target calculations — all 23 I7 plugins inherit vol-regime scaling automatically"
  - "1.5xATR proximity gate: structure_snap vs garch_adaptive — labels structural stops by their proximity to ATR fallback for ML stop quality segmentation"
  - "stop_basis flows to both signal_ledger (for per-signal analysis) and intelligence_features.i7 (for per-bar ML predictor use)"
  - "atr_static when no GARCH regime available — explicit label distinguishes vanilla ATR from regime-scaled ATR in ML training data"
metrics:
  duration: "12m 19s"
  completed_date: "2026-03-17"
  tasks_completed: 3
  files_changed: 6
---

# Phase 32 Plan 01: Stop Architecture + LedgerEntry Extension Summary

GARCH-adaptive ATR scaling and FVG structural stop tier wired into trade_framer.py; all 23 I7 plugins inherit stop_basis classification; LedgerEntry extended with 15 new ML fields; stop_basis flows into intelligence_features.i7 JSONB per bar.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | DB migration 035 + TradeFrame + LedgerEntry extension | 45d507e |
| 2 | GARCH multiplier + FVG tier + stop_basis classification | 617e1cb |
| 3 | Per-TF TTL + fire-time snapshots + i7 payload enrichment | f31d16e |

## What Was Built

### Migration 035 (`production/migrations/035_stop_basis_and_divergence_stack.sql`)
15 new `signal_ledger` columns: `stop_basis`, `stop_structure_type`, `stop_structure_age_bars`, `structural_stop_distance_atr`, `hmm_regime_at_fire`, `garch_sigma_at_fire`, `chandelier_vol_source`, `trailing_stop_price` (JSONB), `trailing_stop_tightening_rate`, `staleness_score`, `staleness_trigger_reason`, `shadow_tracking_start_ts`, `shadow_mae`, `shadow_mfe`, `shadow_outcome`. Partial index on `stop_basis` for ML segmentation queries.

### TradeFrame extension (`src/intelligence/trading/trade_framer.py`)
- `GARCH_MULTIPLIERS = {0: 0.8, 1: 1.0, 2: 1.35}` — vol-regime ATR scaling
- `STRUCTURE_SNAP_PROXIMITY_ATR = 1.5` — proximity gate threshold
- `_classify_stop_basis()` — classifies stop into structure_snap/garch_adaptive/atr_static
- `_stop_type_to_structure_type()` — canonical structure label mapping
- `_get_structure_age_bars()` — age field extraction for swing/SR levels
- FVG Priority 0 in `_resolve_stop_long()` (fvg_low) and `_resolve_stop_short()` (fvg_high)
- `frame_trade()` now applies GARCH multiplier to `effective_atr` and populates 4 new TradeFrame fields

### LedgerEntry extension (`src/intelligence/trading/signal_ledger.py`)
- 15 new fields after `is_shadow`, all nullable
- `to_insert_params()` now returns 54-element tuple (was 39)
- `_INSERT_SQL` extended with $40–$54 placeholders

### Signal Generator wiring (`services/signal_generator_service.py`)
- `TF_TTL_BARS = {"1m": 20, "5m": 12, "15m": 8, "1h": 6}` — per-TF TTL
- TTL applied to raw_signals before aggregation
- `stop_basis`, `stop_structure_type`, `stop_structure_age_bars`, `structural_stop_distance_atr` copied from TradeFrame into selected_signal dict
- `hmm_regime_at_fire`, `garch_sigma_at_fire` captured from features at fire time
- LedgerEntry construction reads all 6 new fields from signal dict
- `_build_i7_payload()` includes all stop_basis fields in per-signal JSONB for intelligence_features.i7

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated test_signal_ledger.py 39-element assertions to 54**
- **Found during:** Task 3 full test suite run
- **Issue:** 5 existing tests asserted `len(params) == 39` — now broken by LedgerEntry expansion
- **Fix:** Changed assertions to `len(params) == 54` with descriptive comments
- **Files modified:** `tests/unit/intelligence/test_signal_ledger.py`
- **Commit:** f31d16e

**2. [Rule 1 - Bug] Ruff linting fixes**
- **Found during:** Post-task linting
- **Issue:** E501 line-too-long, F401 unused imports, F841 unused variables in new code
- **Fix:** Reformatted long lines, removed unused imports/variables
- **Files modified:** All 4 modified Python files + test files
- **Commit:** ab8111e

Pre-existing failures confirmed before/after (not introduced by this plan):
- `tests/unit/api/test_signals_route.py::TestGetSignals::test_get_signals_base_symbol_resolved`
- `tests/unit/config/test_settings.py::TestHelperFunctions::*` (4 tests)
- `tests/unit/service_tests/test_feature_writer_config.py::test_default_config_uses_active_contracts`
- `tests/unit/test_historical_backfill.py::TestInsertFeaturesSync::*` (2 tests)

## Test Results

- `tests/unit/test_trade_framer.py`: 21/21 passed (new TDD tests)
- `tests/unit/intelligence/test_signal_ledger.py`: 41/41 passed (updated + existing)
- Full suite: 1986 passed, 8 pre-existing failures (unchanged)

## Self-Check: PASSED
