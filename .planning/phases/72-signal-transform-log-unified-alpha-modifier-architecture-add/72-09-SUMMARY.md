---
phase: 72-signal-transform-log-unified-alpha-modifier-architecture-add
plan: "09"
subsystem: graduation-compute
tags: [graduation, compute-agent, kafka, event-driven, renaissance]
dependency_graph:
  requires: ["72-01", "72-02", "72-03"]
  provides: ["GraduationComputeAgent", "graduation_compute_group consumer", "topic_transform_graduation producer"]
  affects: ["72-08-graduation-writer"]
tech_stack:
  added: []
  patterns: ["BaseAgent consumer+producer pattern", "asyncpg.create_pool with acquire ctx", "defaultdict(int) ephemeral counters", "__new__ test bypass"]
key_files:
  created:
    - services/graduation_compute_agent.py
    - services/indicagent-graduation-compute.service
    - tests/unit/test_graduation_compute_agent.py
  modified: []
decisions:
  - "KafkaProducerClient.publish(topic, msg: dict, key=) passes dict not bytes — plan skeleton had json.dumps().encode() which is wrong; corrected to pass dict directly per kafka_utils.py signature"
  - "BaseAgent auto-configures logging from name via PascalCase->snake_case conversion; setup_service_logging() call in _setup() removed (would double-configure)"
  - "structlog import removed — BaseAgent provides self.logger via structlog.get_logger().bind(); skeleton's explicit import was unused"
  - "14 tests written vs plan's 7 — added coverage for MAE_MFE_UPDATE skip, missing signal_id guard, below-threshold non-trigger, empty-rows skip, and DLQ payload content"
metrics:
  duration: "3m"
  completed: "2026-04-25"
  tasks_completed: 2
  tasks_total: 2
  files_created: 3
  files_modified: 0
---

# Phase 72 Plan 09: GraduationComputeAgent Summary

**One-liner:** Event-driven graduation evaluator consuming lifecycle EXIT transitions, incrementing per-segment counters, and triggering Renaissance `evaluate_all()` at threshold=20 with results published to `topic_transform_graduation`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | GraduationComputeAgent service | `070ff484` | `services/graduation_compute_agent.py` |
| 2 | Systemd unit + unit tests | `25376daf` | `services/indicagent-graduation-compute.service`, `tests/unit/test_graduation_compute_agent.py` |

## What Was Built

**`services/graduation_compute_agent.py`** — Always-on ComputeAgent that:
- Consumes `topic_lifecycle_transitions` on consumer group `graduation_compute_group`
- Ignores non-EXIT transitions (ACTIVATION, MAE_MFE_UPDATE) with zero overhead
- On EXIT: fetches all `signal_transform_log` rows for that `signal_id`, increments per-`(transform_id, transform_version, segment_key)` counter
- When any counter reaches `EVAL_RESOLUTION_THRESHOLD` (20): queries rolling 90d JOIN data, calls `evaluate_all()`, publishes `GraduationResult` dict to `topic_transform_graduation`, resets counter
- On startup: seeds counters from `transform_graduation` table by counting new EXIT resolutions since last `evaluated_at`
- Evaluation failures: logs, increments error counter, routes structured error to `topic_transform_graduation_dlq`
- Metrics port 9135; counters for exits_consumed, evaluations_total, evaluation_errors_total

**`services/indicagent-graduation-compute.service`** — Type=simple, PYTHONUNBUFFERED=1, no WatchdogSec/NotifyAccess, User=bg, WorkingDirectory=/home/bg/dev/indicagent.

**`tests/unit/test_graduation_compute_agent.py`** — 14 tests covering locked constants, EXIT routing, counter threshold, Kafka publish payload, empty-rows skip, DLQ on DB error, and DLQ payload structure. All pass.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected KafkaProducerClient.publish call signature**
- **Found during:** Task 1 implementation
- **Issue:** Plan skeleton called `publish(topic, key=..., value=json.dumps(result).encode("utf-8"))` using kwargs `key` and `value`, but the actual signature is `publish(self, topic: str, msg: dict, key: str | None = None)` which serializes internally
- **Fix:** Changed to `publish(topic_transform_graduation(self.env_name), result, key=f"{transform_id}:{segment_key}")` — passes dict as positional 2nd arg
- **Files modified:** `services/graduation_compute_agent.py`
- **Commit:** `070ff484`

**2. [Rule 1 - Bug] Removed duplicate setup_service_logging call**
- **Found during:** Task 1 — reading `src/core/agent/base.py`
- **Issue:** Plan skeleton called `setup_service_logging("logs/graduation_compute_agent.log")` in `_setup()`. BaseAgent `__init__` already calls `setup_service_logging()` by converting the agent name `GraduationComputeAgent` → `graduation_compute_agent.log` via PascalCase→snake_case conversion. Calling it again would double-configure the logger.
- **Fix:** Removed the explicit `setup_service_logging()` call from `_setup()`
- **Files modified:** `services/graduation_compute_agent.py`
- **Commit:** `070ff484`

**3. [Rule 1 - Bug] Removed unused structlog import**
- **Found during:** Task 1 ruff check
- **Issue:** Plan skeleton imported `structlog` explicitly but `self.logger` is already set by BaseAgent via `structlog.get_logger().bind(agent=name)`. Unused import caused ruff F401 failure.
- **Fix:** Removed `import structlog`
- **Files modified:** `services/graduation_compute_agent.py`
- **Commit:** `070ff484`

**4. [Rule 2 - Enhancement] Extended test coverage from 7 to 14 tests**
- **Found during:** Task 2 — identified additional edge cases not in plan's test list
- **Issue:** Plan specified 7 tests. Additional correctness scenarios identified: MAE_MFE_UPDATE skip, missing signal_id guard, counter below-threshold non-trigger, empty-rows skip, DLQ payload content verification
- **Fix:** Added 7 additional tests covering these cases
- **Files modified:** `tests/unit/test_graduation_compute_agent.py`
- **Commit:** `25376daf`

## Known Stubs

None — all behavior is wired end-to-end. The `_seed_counters` method correctly handles empty `transform_graduation` table (counter starts at 0, fires after 20 new resolutions).

## Threat Flags

None — no new network endpoints or auth paths introduced. The agent reads from an internal DB table (`signal_transform_log`, `signal_ledger`, `transform_graduation`) and publishes to internal Kafka topics. DB access uses the existing `settings.database_url` with asyncpg pool.

## Self-Check

Checking created files exist and commits are present...

## Self-Check: PASSED

- `services/graduation_compute_agent.py` — FOUND
- `services/indicagent-graduation-compute.service` — FOUND
- `tests/unit/test_graduation_compute_agent.py` — FOUND
- Commit `070ff484` — FOUND
- Commit `25376daf` — FOUND
