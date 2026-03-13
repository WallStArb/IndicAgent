---
phase: 29-renaissance-signal-quality
plan: "07"
subsystem: drift-detection
tags: [cusum, drift-monitor, perf-multiplier, api, observability, qual-10]
dependency_graph:
  requires: [29-06]
  provides: [cusum-monitor, drift-api, cusum-perf-response]
  affects: [setup_performance_updater, drift_monitor_service, signal_generator]
tech_stack:
  added: []
  patterns:
    - Page CUSUM algorithm for sequential degradation detection
    - Multiplicative perf_multiplier adjustment with floor guard
    - Concurrent asyncio task per monitor type (KS + CUSUM)
    - Redis cursor scan for wildcard key enumeration in API endpoint
key_files:
  created:
    - src/monitoring/cusum_monitor.py
    - src/api/routes/drift.py
    - production/scripts/reset_cusum.py
    - tests/unit/monitoring/test_cusum_monitor.py
  modified:
    - src/core/stream_keys.py
    - src/intelligence/setup_performance_updater.py
    - services/drift_monitor_service.py
    - src/api/main.py
decisions:
  - "CUSUM adjustment applied after base perf_multiplier, before Redis write — single write point in setup_performance_updater"
  - "CUSUM floor=0.30 prevents complete suppression of any setup"
  - "severity string only stored in Redis; s_neg not persisted (API returns None for s_neg field)"
  - "CUSUMMonitor._fetch_eligible_setups() uses HAVING N>=20 so run_forever only checks setups with sufficient data"
  - "reset_cusum.py inserts into drift_monitor hypertable for audit trail per migration 026 schema"
metrics:
  duration_minutes: 6
  completed_date: "2026-03-13"
  tasks_completed: 3
  files_modified: 8
---

# Phase 29 Plan 07: CUSUM Monitor + API Drift Endpoint Summary

**One-liner:** Page's CUSUM performance monitor with multiplicative perf_multiplier response (floor=0.30) + GET /api/drift observability endpoint closing QUAL-10.

## What Was Built

### CUSUMMonitor (src/monitoring/cusum_monitor.py)
Page's CUSUM algorithm for detecting per-setup pnl_r degradation before losses accumulate. Queries the last 90 days of resolved signal outcomes, uses the first 20 as the baseline window, and runs CUSUM over the remainder. Writes `drift:cusum:{plugin}` to Redis with 2h TTL when severity != "none". `run_forever()` loops every 1h over all eligible setups (N >= 20).

Severity classification:
- `s_neg >= 2*h (8.0)` → "critical" (strong degradation)
- `s_neg >= h (4.0)` → "warning" (degradation signal)
- `s_pos >= h (4.0)` → "info" (winning streak, not penalized)

### drift_cusum() stream key (src/core/stream_keys.py)
Added `drift_cusum(env_prefix, setup_plugin) → "{env_prefix}drift:cusum:{setup_plugin}"` alongside existing `drift_ks()`.

### CUSUM → perf_multiplier integration (src/intelligence/setup_performance_updater.py)
After computing base `perf_weights` from setup_performance table stats, reads all `drift:cusum:{plugin}` Redis keys and applies multiplicative adjustment: warning=0.85, critical=0.70. Floor at 0.30 prevents complete suppression. Single write point — drift_monitor_service never touches perf_weights directly.

### drift_monitor_service.py completion
Added `_cusum_task()` that creates and runs a `CUSUMMonitor.run_forever()` concurrently with the existing `_ks_task()`. Both tasks share the same DB pool and Redis client initialized at service startup.

### GET /api/drift (src/api/routes/drift.py)
Scans Redis for all `drift:ks:*` and `drift:cusum:*` keys via async cursor scan. Returns structured JSON with ks array (symbol, timeframe, severity), cusum array (setup_plugin, severity), and last_updated timestamp. Registered at `/api/drift` in `src/api/main.py`.

### reset_cusum.py (production/scripts/)
CLI tool: `python reset_cusum.py --plugin trad_TrendFollowing`. Deletes Redis CUSUM key and inserts audit record into drift_monitor hypertable (migration 026 schema: check_type='cusum', alert_severity='none').

## Test Results

- 9 new unit tests in `tests/unit/monitoring/test_cusum_monitor.py`
- 16 monitoring tests passing total (KS + CUSUM)
- Full suite: **1659 passing** (up from 1503 baseline)

## Commits

| Hash | Message |
|------|---------|
| `84172c3` | test(29-07): add failing tests for CUSUMMonitor and drift_cusum key |
| `42912a2` | feat(29-07): CUSUMMonitor class + drift_cusum stream key |
| `a14613b` | feat(29-07): CUSUM integration in weight_updater + drift_monitor_service completion |
| `e5388f8` | feat(29-07): GET /api/drift endpoint + router registration |

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- `src/monitoring/cusum_monitor.py` — FOUND
- `src/api/routes/drift.py` — FOUND
- `production/scripts/reset_cusum.py` — FOUND
- `tests/unit/monitoring/test_cusum_monitor.py` — FOUND
- Commits `84172c3`, `42912a2`, `a14613b`, `e5388f8` — all present in git log
- 1659 unit tests passing
