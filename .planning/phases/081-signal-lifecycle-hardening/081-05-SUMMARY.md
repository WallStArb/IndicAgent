---
phase: 081
plan: "05"
subsystem: signal-lifecycle
tags: [replay-auditor, idempotency, two-path-safety, lifecycle-writer, metrics]
dependency_graph:
  requires: ["081-01", "081-03"]
  provides: ["signal_replay_unresolved_gauge=0 guarantee", "two-path EXIT safety"]
  affects: ["services/lifecycle_writer_agent.py", "services/signal_replay_auditor_agent.py"]
tech_stack:
  added: []
  patterns: ["two-path safety (live + replay)", "first-writer-wins idempotency", "bar-by-bar replay evaluation"]
key_files:
  created:
    - services/signal_replay_auditor_agent.py
    - production/systemd/indicagent-signal-replay.service
  modified:
    - src/observability/metrics.py
    - services/lifecycle_writer_agent.py
decisions:
  - "Idempotency guard implemented as per-item execute() in _flush_exit_items rather than executemany, enabling UPDATE 0 detection for counter increment"
  - "evaluate_signal and evaluate_market_entry imported directly from lifecycle_tracker — no logic duplication"
  - "Replay skips signals still within TTL window to avoid racing the live tracker"
  - "Market-entry track published as MARKET_RESOLUTION (informational); only zone EXIT counts toward north-star gauge"
metrics:
  duration_minutes: 4
  completed_date: "2026-05-08"
  tasks_completed: 4
  tasks_total: 4
  files_created: 2
  files_modified: 2
---

# Phase 81 Plan 05: Signal Replay Auditor + Writer Idempotency Summary

Signal outcome recovery with two-path safety: `SignalReplayAuditorAgent` closes labels for v1 signals the live tracker missed, and `LifecycleWriterAgent` guards all EXIT writes with `WHERE exit_at IS NULL` so live and replay paths never corrupt each other.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Register signal_replay + lifecycle_writer_idempotent_skip metrics | f271f303 | src/observability/metrics.py |
| 2 | Add idempotency guard in lifecycle_writer_agent.py | 01a1884c | services/lifecycle_writer_agent.py |
| 3 | Create SignalReplayAuditorAgent | 821c77c0 | services/signal_replay_auditor_agent.py |
| 4 | Create systemd unit | 9cf5d617 | production/systemd/indicagent-signal-replay.service |

## What Was Built

### Task 1 — Five New Metrics (src/observability/metrics.py)

- `SIGNAL_REPLAY_UNRESOLVED_GAUGE` — north-star gauge, target = 0 permanently
- `SIGNAL_REPLAY_ATTEMPTED_TOTAL` — signals queried each cycle
- `SIGNAL_REPLAY_RESOLVED_TOTAL(outcome=...)` — outcomes published by replay
- `SIGNAL_REPLAY_OHLCV_GAP_TOTAL(symbol, timeframe)` — gaps where OHLCV window had no bars
- `LIFECYCLE_WRITER_IDEMPOTENT_SKIP_TOTAL` — EXIT writes skipped by idempotency guard

### Task 2 — Two-Path EXIT Safety (services/lifecycle_writer_agent.py)

Added `_EXIT_IDEMPOTENT_SQL` with `WHERE signal_id = $1::uuid AND exit_at IS NULL` guard. Added `_flush_exit_items()` that calls `execute_command()` per item (vs. `executemany`) so the status string `"UPDATE 0"` is detectable. When 0 rows updated, increments `LIFECYCLE_WRITER_IDEMPOTENT_SKIP_TOTAL` and logs `lifecycle_writer_idempotent_skip`. `_flush_batch()` routes `transition_type == "exit"` through this new method; all other types remain on the batch path.

### Task 3 — SignalReplayAuditorAgent (services/signal_replay_auditor_agent.py)

5-minute periodic auditor (L9). Each cycle:
1. Queries `signal_ledger WHERE exit_at IS NULL AND signal_schema_version = 'v1' AND timestamp < NOW() - INTERVAL '2 minutes'`
2. Skips any signal still within `ttl_bars * tf_seconds` (live tracker still owns it)
3. Fetches `market_data_ohlcv` bars for `[timestamp, timestamp + ttl*tf_secs]`
4. Empty OHLCV window → increments gap metric, skips
5. Replays bar-by-bar using `evaluate_signal()` from `lifecycle_tracker.py` (no logic duplication)
6. On terminal `Transition`, publishes `LifecycleTransition(EXIT)` to `topic_lifecycle_transitions`
7. If `market_entry_price` is set, also replays `evaluate_market_entry()` and publishes `MARKET_RESOLUTION`
8. After batch: runs fresh `COUNT(*)` query and sets `SIGNAL_REPLAY_UNRESOLVED_GAUGE`

### Task 4 — Systemd Unit (production/systemd/indicagent-signal-replay.service)

`Type=simple`, `Restart=on-failure`, `RestartSec=15`, `PYTHONUNBUFFERED=1`, `INDICAGENT_ENV=production`. No `WatchdogSec` (agent does not send sd_notify heartbeats). `ExecStart` uses `python -m services.signal_replay_auditor_agent`.

## Idempotency Contract

```
Live tracker (fast) ──┐
                       ├── lifecycle.transitions ──► LifecycleWriterAgent
Replay auditor (5m) ──┘                              (WHERE exit_at IS NULL)
```

Both paths emit EXIT transitions. The writer's `WHERE exit_at IS NULL` guard ensures the second writer is always a no-op — the first writer to reach DB wins. `LIFECYCLE_WRITER_IDEMPOTENT_SKIP_TOTAL` validates the contract is exercised when both paths fire on the same signal.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Idempotency guard implemented via per-item execute, not executemany**
- **Found during:** Task 2
- **Issue:** `executemany`/`execute_batch` returns no per-row status; cannot detect UPDATE 0 (idempotent skip) to increment the counter
- **Fix:** Added `_flush_exit_items()` that calls `self._db.execute_command()` per item; returns status string like `"UPDATE 1"` or `"UPDATE 0"`; routes exit group through this instead of `self._repo.batch_execute("exit", items)`
- **Files modified:** services/lifecycle_writer_agent.py

**2. [Rule 2 - Missing] Signal dict needs symbol/timeframe for LifecycleTransition**
- **Found during:** Task 3
- **Issue:** `_build_signal_dict()` is used as `signal_dict` in evaluate_signal but also needs `symbol` and `timeframe` to build the LifecycleTransition; the DB row has them
- **Fix:** Added `symbol` and `timeframe` pass-through in `_build_exit_transition()` from the outer `signal_dict` which the caller populates from the row

## Self-Check

### Files Exist
- `services/signal_replay_auditor_agent.py` — FOUND
- `production/systemd/indicagent-signal-replay.service` — FOUND

### Commits Exist
- f271f303 — FOUND
- 01a1884c — FOUND
- 821c77c0 — FOUND
- 9cf5d617 — FOUND

## Self-Check: PASSED
