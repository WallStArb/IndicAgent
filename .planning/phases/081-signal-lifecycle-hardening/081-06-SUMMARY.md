---
phase: 081-signal-lifecycle-hardening
plan: "06"
subsystem: observability
tags:
  - metrics
  - prometheus
  - alerting
  - signal-lifecycle
dependency_graph:
  requires:
    - 081-02
    - 081-03
    - 081-04
    - 081-05
  provides:
    - signal_ledger_backfill_ratio gauge (11th D-09 metric)
    - four Phase 81 Prometheus alert rules
  affects:
    - services/signal_metrics_compute_agent.py
    - src/observability/metrics.py
    - production/alertmanager-rules.yml
tech_stack:
  added: []
  patterns:
    - prometheus_client.Gauge (no labels) for KPI ratio
    - DatabaseManager.execute_query for periodic backfill ratio update
    - Prometheus alert group with deriv() and increase() expressions
key_files:
  created: []
  modified:
    - src/observability/metrics.py
    - services/signal_metrics_compute_agent.py
    - production/alertmanager-rules.yml
decisions:
  - Reuse existing DatabaseManager._db pool in signal_metrics_compute_agent rather than adding a second asyncpg pool — consistent with the file's existing pattern
  - Place backfill ratio update at end of _run_compute_cycle after all metrics are published, before DQ key pruning — clean separation of concerns
  - Use NULLIF(COUNT(*), 0) guard in SQL to avoid division-by-zero on empty windows
metrics:
  duration_minutes: 8
  completed: "2026-05-08"
  tasks_completed: 3
  files_modified: 3
---

# Phase 081 Plan 06: Metric Coverage Completion and Alert Wiring Summary

Final metric registered, gauge self-updating from DB, and four Prometheus alerts armed for Phase 81 failure modes.

## What Was Built

### Task 1 — signal_ledger_backfill_ratio Gauge (commit 79e5097d)

Added the 11th and final D-09 metric to `src/observability/metrics.py`:

```python
SIGNAL_LEDGER_BACKFILL_RATIO = Gauge(
    "signal_ledger_backfill_ratio",
    "Fraction of signal_ledger rows last 24h with is_backfill=TRUE (training set quality KPI)",
)
```

No labels — this is a single scalar KPI across all symbols and timeframes.

### Task 2 — Gauge Update Wired in SignalMetricsComputeAgent (commit bf0977aa)

At the end of each `_run_compute_cycle` (every 15 minutes), the agent now runs:

```sql
SELECT
  COUNT(*) FILTER (WHERE is_backfill = TRUE)::float
    / NULLIF(COUNT(*), 0)::float AS backfill_ratio
FROM signal_ledger
WHERE timestamp >= NOW() - INTERVAL '24 hours'
```

Result is set on the gauge. Zero-row window returns 0.0 (no crash). Uses existing `DatabaseManager` pool — no new connection management needed.

### Task 3 — Four Phase 81 Alert Rules (commit ab52e4ca)

New Prometheus group `phase81-signal-lifecycle` (interval: 1m) appended to `production/alertmanager-rules.yml`.

## Complete D-09 Metric Inventory (All 11)

| # | Metric | Type | Owner | Labels |
|---|--------|------|-------|--------|
| 1 | `intelligence_pipeline_backfill_signals_total` | Counter | intelligence_pipeline_agent | symbol, timeframe |
| 2 | `signal_tracker_invalid_signal_total` | Counter | signal_tracker_compute_agent | reason |
| 3 | `signal_tracker_backfill_fast_path_total` | Counter | signal_tracker_compute_agent | symbol, timeframe |
| 4 | `bar_replay_provider_bars_published_total` | Counter | bar_replay_provider_agent | symbol, timeframe |
| 5 | `bar_replay_provider_lag_seconds` | Gauge | bar_replay_provider_agent | (none) |
| 6 | `signal_replay_unresolved_gauge` | Gauge | signal_replay_auditor_agent | (none) |
| 7 | `signal_replay_attempted_total` | Counter | signal_replay_auditor_agent | (none) |
| 8 | `signal_replay_resolved_total` | Counter | signal_replay_auditor_agent | outcome |
| 9 | `signal_replay_ohlcv_gap_total` | Counter | signal_replay_auditor_agent | symbol, timeframe |
| 10 | `lifecycle_writer_idempotent_skip_total` | Counter | lifecycle_writer_agent | (none) |
| 11 | `signal_ledger_backfill_ratio` | Gauge | signal_metrics_compute_agent | (none) |

## Phase 81 Alert Rules

| Alert | Expression | For | Severity | Meaning |
|-------|-----------|-----|----------|---------|
| `P81_SignalTrackerInvalidSignals` | `increase(signal_tracker_invalid_signal_total[5m]) > 0` | 5m | page | Publisher contract violation — required fields missing |
| `P81_SignalReplayOhlcvGap` | `increase(signal_replay_ohlcv_gap_total[15m]) > 10` | 5m | page | Replay has zero OHLCV bars in signal window — OHLCV pipeline gap |
| `P81_SignalReplayUnresolvedGrowing` | `deriv(signal_replay_unresolved_gauge[15m]) > 0` | 10m | page | North-star metric trending up — replay auditor stuck |
| `P81_LifecycleWriterIdempotentSkipHigh` | `increase(lifecycle_writer_idempotent_skip_total[1h]) > 100` | 5m | warn | Two-path collision rate elevated — live tracker and replay racing |

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- `src/observability/metrics.py` modified — confirmed, contains `signal_ledger_backfill_ratio`
- `services/signal_metrics_compute_agent.py` modified — confirmed, SIGNAL_LEDGER_BACKFILL_RATIO count=2, is_backfill filter present
- `production/alertmanager-rules.yml` modified — confirmed, phase81-signal-lifecycle group with 4 alerts, YAML parses cleanly
- Commits present: 79e5097d, bf0977aa, ab52e4ca — verified via git log
- docker-compose.yml mounts alertmanager-rules.yml into Prometheus — confirmed
