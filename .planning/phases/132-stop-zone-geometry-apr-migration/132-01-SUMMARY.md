---
phase: 132-stop-zone-geometry-apr-migration
plan: "01"
subsystem: signal-lifecycle
tags: [a2-measurement, stop-geometry, zone-engine, lifecycle-replay, measurement]
dependency_graph:
  requires: []
  provides: [132-A2-MEASUREMENT.md, stopped_at_entry rate empirical measurement]
  affects: [132-02, 132-03]
tech_stack:
  added: []
  patterns: [replay-only measurement, lifecycle_replay outcome classification]
key_files:
  created:
    - .planning/phases/132-stop-zone-geometry-apr-migration/132-A2-MEASUREMENT.md
  modified:
    - production/scripts/run_historical_pipeline.py
    - production/scripts/lifecycle_replay.py
decisions:
  - "A2 is GAP (44.7% stopped_at_entry of stop exits vs <5% threshold) on fresh 2-week sample"
  - "zone_engine.py has no TradeFrame construction -- confirmed no bypass"
  - "stopped_at_entry exit_reason is not written to trade_executions; STOPPED_AT_ENTRY is only an outcome enum in lifecycle_replay logs"
  - "ESU6 substituted with ESM6 for ES coverage (ESU6 is metadata front-month but has no bar data)"
metrics:
  duration_minutes: 18
  completed_date: "2026-06-18"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 3
---

# Phase 132 Plan 01: A2 Measurement Summary

Empirically measured stopped_at_entry rate on a fresh 2-week sample replay (4 symbols, 4 asset classes) plus lifecycle_replay. A2 is GAP at 44.7% of stop exits vs the < 5% threshold.

## What Was Done

**Task 1: 2-week sample replay + lifecycle_replay**

Resolved front-month contracts (ESU6/NGN6) via is_front_month=true. ESU6 had no bar data in the 14-day window; substituted ESM6 (documented). Confirmed bar coverage: QQQ (10,140), ESM6 (15,753), NGN6 (15,611), GBPUSD (16,219) bars.

Ran `run_historical_pipeline.py --replay-only --clean --setups ALL --days 14 --symbols QQQ,ESM6,NGN6,GBPUSD --include-rolled`. Produced 14,432 fresh signal_events rows. Then ran `lifecycle_replay.py --reset --reset-after 2026-06-03T00:00:00Z --confirm --symbols QQQ,ESM6,NGN6,GBPUSD --workers 8 --force`, processing 13,049 signals.

**Task 2: zone_engine audit + A2 disposition**

Confirmed zero results for `grep -n "TradeFrame|frame_trade|make_signal_from_frame" zone_engine.py`. zone_engine only returns `ZoneResult` objects; trade_framer's line 1059 gate is the sole rejection point. The `_expand_to_min_width()` at line 398 uses 0.25 ATR (internal minimum) vs trade_framer's 1.5 ATR rejection threshold -- this is by design.

Wrote `132-A2-MEASUREMENT.md` with all 5 required sections (exit_reason distribution, stopped_at_entry percentage, A2 disposition, zone_engine audit conclusion, reproduction commands).

## Key Findings

**A2 rate: 44.7% of stop exits** -- far above the 5% threshold. A2 is GAP.

The Phase 126 gates (zone width rejection, stop distance floor) are working -- they rejected narrow zones and too-close stops. However, the `_classify_stop_outcome()` function in lifecycle_tracker.py classifies any stop with `current_mfe <= 0.05R` as STOPPED_AT_ENTRY, which is a broad catch-all capturing many poor-quality entries, not just geometric bugs.

Per-symbol breakdown:
- GBPUSD: 58.1% (highest -- FX whipsaw behavior)
- QQQ: 38.4%
- ESM6: 37.0%
- NGN6: 31.3%

**Critical insight:** `stopped_at_entry` does NOT appear as exit_reason in trade_executions. lifecycle_replay.py writes all zone-track stops with exit_reason = `"stop_loss"`. The STOPPED_AT_ENTRY classification is an outcome enum used only in replay logs. The DB query in the plan for measuring this metric returns empty results. The correct metric is from lifecycle_replay log output.

**zone_source is not persisted:** `features["zone_source"]` (assigned at trade_framer.py:1050) is not stored in `context_features` JSONB, preventing per-path breakdown of the stopped_at_entry rate.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] run_historical_pipeline.py full-symbol clean FK violation**
- **Found during:** Task 1, Step 3 (first run of replay with --setups ALL)
- **Issue:** The `--setups ALL` clean path deleted `trade_frames` before `trade_executions`, violating FK constraint `fk_trade_executions_frame`. Exit code 0 despite the crash.
- **Fix:** Added `DELETE FROM trade_executions WHERE frame_id IN (...)` before `DELETE FROM trade_frames` in the else branch (full-symbol clean path)
- **Files modified:** `production/scripts/run_historical_pipeline.py`
- **Commit:** c363d6aa

**2. [Rule 1 - Bug] lifecycle_replay.py NoneType.isoformat crash**
- **Found during:** Task 1, Step 4 (first run of lifecycle_replay)
- **Issue:** `_reset_corrupt_data()` log message called `before.isoformat()` when `--reset-before` was not provided (before=None). Traceback: `AttributeError: 'NoneType' object has no attribute 'isoformat'`
- **Fix:** Added None guard: `before.isoformat() if before is not None else "unbounded"`
- **Files modified:** `production/scripts/lifecycle_replay.py`
- **Commit:** c363d6aa

### Measurement Deviation: DB query returns empty stopped_at_entry

The plan's Step 3 query expected `stopped_at_entry` rows in trade_executions. These do not exist -- lifecycle_replay writes `"stop_loss"` as exit_reason for all zone stops; the STOPPED_AT_ENTRY classification is an outcome enum in replay logs only. The measurement was taken from lifecycle_replay log output instead, which is the correct source per the actual code.

## Self-Check: PASSED

File check:
- .planning/phases/132-stop-zone-geometry-apr-migration/132-A2-MEASUREMENT.md: FOUND (240 lines)

Commit check:
- c363d6aa: feat(132-01): measure A2 stopped_at_entry rate on fresh 2-week sample replay: FOUND
