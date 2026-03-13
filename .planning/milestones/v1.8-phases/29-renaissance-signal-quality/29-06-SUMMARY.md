---
phase: 29-renaissance-signal-quality
plan: "06"
subsystem: monitoring
tags: [ks-drift, distribution-monitoring, qual-09, redis, timescaledb, prometheus]
dependency_graph:
  requires: [29-05]
  provides: [drift_monitor hypertable, KSDriftMonitor, drift_ks stream key, drift_monitor_service, signal_generator KS penalty]
  affects: [signal_generator_service, aggregator, drift_monitor_service]
tech_stack:
  added: [scipy.stats.ks_2samp, src.monitoring package]
  patterns: [two-sample KS test, Redis severity key with TTL, recovery mechanic via clean-cycle counter, direct prometheus_client metrics with labels]
key_files:
  created:
    - production/migrations/026_drift_monitor.sql
    - src/monitoring/__init__.py
    - src/monitoring/ks_drift_monitor.py
    - services/drift_monitor_service.py
    - tests/unit/monitoring/__init__.py
    - tests/unit/monitoring/test_ks_drift_monitor.py
  modified:
    - src/core/stream_keys.py (drift_ks() key constructor)
    - services/signal_generator_service.py (_read_drift_penalty, drift_penalty kwarg to aggregate)
    - src/intelligence/trading/aggregator.py (drift_penalty applied in _build_all_ranked)
decisions:
  - "drift_monitor hypertable uses 30-day chunks; NO CONCURRENTLY on indexes (hypertable constraint)"
  - "Recovery mechanic: 2 consecutive clean KS cycles → delete Redis key (full restore); severity string not granular enough for partial penalty fade"
  - "drift_penalty read per bar via _read_drift_penalty() — one Redis GET per bar evaluation, negligible overhead"
  - "drift_monitor_service uses src.observability.metrics counter/gauge for service-level metrics; KSDriftMonitor uses direct prometheus_client Counter/Gauge for labeled KS metrics"
metrics:
  duration: "~30 min (plan already 80% complete at session start)"
  completed: "2026-03-13"
  tasks_completed: 3
  files_created: 6
  files_modified: 3
  tests_added: 7
  tests_total: 1640
requirements: [QUAL-09]
---

# Phase 29 Plan 06: KS Distribution Drift Monitor Summary

KS drift detection infrastructure: hypertable + stream key + KSDriftMonitor class + drift_monitor_service + signal_generator automatic confidence penalty when feature distributions shift from baseline.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Migration 026 + stream_keys drift_ks() | ae2a8ca | 026_drift_monitor.sql, stream_keys.py |
| 2 | KSDriftMonitor class + unit tests | 553accd | ks_drift_monitor.py, test_ks_drift_monitor.py |
| 3 | drift_monitor_service + signal_generator KS penalty | da5938f | drift_monitor_service.py, signal_generator_service.py, aggregator.py |

## What Was Built

**Migration 026** (`production/migrations/026_drift_monitor.sql`): `drift_monitor` hypertable with 30-day chunks, indexed by `(symbol, check_type, checked_at DESC)` and `alert_triggered`. Schema covers both KS (QUAL-09) and CUSUM (QUAL-10, wired in plan 29-07).

**Stream key** (`src/core/stream_keys.py`): `drift_ks(env_prefix, symbol, tf)` returns `{env_prefix}drift:ks:{symbol}:{tf}`. Redis string key written by drift_monitor_service, read by signal_generator.

**KSDriftMonitor** (`src/monitoring/ks_drift_monitor.py`):
- Monitors 8 I1/I4 features: `rsi_14`, `macd_histogram_12_26_9`, `rel_volume`, `hurst_exponent`, `entropy_quality`, `garch_sigma`, `trend_regime`, `hmm_regime_0`
- Reference window: 37 days; current window: 7 days; minimum 30 reference rows before running
- Severity: `critical` if p < 0.01, `warning` if p < 0.05, `none` otherwise
- Recovery mechanic: 2 consecutive clean cycles → delete Redis key (full restore to "none")
- Redis key TTL: 8 hours (2× the 4h run interval — survives one missed cycle)
- `run_forever()` loops every 4h, checks all symbol/TF pairs

**drift_monitor_service** (`services/drift_monitor_service.py`):
- Prometheus metrics on :9118
- `DriftMonitorService` with `_ks_task()` wrapping `KSDriftMonitor.run_forever()`
- Health monitor loop tracking uptime gauge
- Graceful SIGINT/SIGTERM shutdown with Redis + DB cleanup
- CUSUM task slot to be added in plan 29-07

**Signal generator integration** (`services/signal_generator_service.py` + `aggregator.py`):
- `_read_drift_penalty(symbol, tf)` reads severity string from Redis, maps via `DRIFT_PENALTIES` dict
- `DRIFT_PENALTIES = {"none": 1.0, "warning": 0.85, "critical": 0.70}`
- `drift_penalty` float passed to `aggregate()` → `_build_all_ranked()` applies `sig["confidence"] *= drift_penalty` for all signals when penalty < 1.0
- Falls back to `1.0` (no penalty) on Redis errors or absent key

## Verification

```
drift_monitor table: exists (0 rows — fresh)
tests/unit/monitoring/: 7/7 passing
tests/unit/ full suite: 1640 passing
```

## Deviations from Plan

None — plan executed exactly as written. All three tasks were already implemented at session start (prior work in same agent context). Task 3 commit was the only action needed.

## Self-Check: PASSED

- `production/migrations/026_drift_monitor.sql` — FOUND
- `src/monitoring/ks_drift_monitor.py` — FOUND
- `services/drift_monitor_service.py` — FOUND
- `tests/unit/monitoring/test_ks_drift_monitor.py` — FOUND
- Commits ae2a8ca, 553accd, da5938f — FOUND
- `drift_monitor` table in TimescaleDB — FOUND (`SELECT count(*) FROM drift_monitor` returns 0)
- 1640 tests passing — CONFIRMED
