---
phase: 083-observability-hardening
plan: "04"
subsystem: observability/dlq
tags: [dlq, base-agent, refactor, consolidation]
dependency_graph:
  requires: ["083-03"]
  provides: ["BaseAgent._get_producer()", "consolidated-dlq-routing"]
  affects: ["bar_aggregator_agent", "graduation_compute_agent", "llm_writer_service"]
tech_stack:
  added: []
  patterns: ["_get_producer() producer selector", "_dlq_topic() override pattern", "inherited _send_to_dlq()"]
key_files:
  modified:
    - src/core/agent/base.py
    - services/bar_aggregator_agent.py
    - services/graduation_compute_agent.py
    - services/llm_writer_service.py
    - tests/unit/service_tests/test_bar_aggregator_agent.py
    - tests/unit/test_graduation_compute_agent.py
decisions:
  - "Used RuntimeError wrapping for llm_writer_service string error_type args at call sites"
  - "Added topics_consumed property to LLMWriterAgent for correct source_topic in DLQ payloads"
  - "Created .venv symlink in worktree to satisfy pre-commit hook path resolution"
metrics:
  duration_minutes: 10
  tasks_completed: 3
  files_modified: 6
  completed_date: "2026-05-15"
---

# Phase 083 Plan 04: DLQ Consolidation Summary

**One-liner:** BaseAgent owns producer selection via `_get_producer()`; three inline DLQ implementations consolidated to single inherited path via `_dlq_topic()` override pattern.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Add `BaseAgent._get_producer()` and refactor `_send_to_dlq` | dd3ef625 |
| 2 | Consolidate `bar_aggregator_agent` DLQ | 3af9446d |
| 3 | Consolidate `graduation_compute_agent` and `llm_writer_service` DLQ | f0010b3b |

## What Was Built

### Task 1: BaseAgent._get_producer()

Added `_get_producer()` method to `BaseAgent` that checks `_kafka_producer` then `_producer`, returning `None` if neither is set. Refactored `_send_to_dlq` to use a single `self._get_producer()` call instead of dual `hasattr` branches (was duplicating the log/metric emit logic). Also removed the `hasattr(self, "_dlq_topic")` guard since `_dlq_topic()` is always defined on `BaseAgent`.

`DLQ_DEPTH` was already removed from `base.py` by plan 02 - no changes needed to imports.

### Task 2: bar_aggregator_agent

- Deleted `self._dlq_producer` field (lines 123), start (lines 219-223), stop (`_teardown`), and retry cleanup references
- Deleted `self._dlq_topic: str = ""` instance attribute that was shadowing the `_dlq_topic()` method
- Replaced inline `self._dlq_producer.produce(self._dlq_topic, payload)` with `await self._send_to_dlq(payload, ValueError(...))`
- Added `_dlq_topic()` method override returning `topic_bar_aggregator_dlq(self.env_name)`
- Updated unit tests: removed `_dlq_producer`/`_dlq_topic` fixture attributes, fixed `start()` call count from 4 to 3

### Task 3: graduation_compute_agent + llm_writer_service

`graduation_compute_agent`:
- Replaced 14-line inline DLQ block (dict construction + raw publish + error handling) with single `await self._send_to_dlq(dlq_payload, exc)`
- Added `_dlq_topic()` method override returning `topic_transform_graduation_dlq(self.env_name)`
- Updated tests: DLQ assertions adapted for `DLQPayload` schema (`error_message` not `error`; original data nested under `payload` key)

`llm_writer_service`:
- Deleted `_send_to_dlq` override (35 lines) - inherited `BaseAgent` path takes over
- Deleted `_dlq_producer` field, start in `_setup_kafka_clients`, stop in `_teardown`
- Kept existing `_dlq_topic()` method override (already correct pattern)
- Updated 4 call sites from 3-arg `(payload, source_topic, error_type)` to 2-arg `(payload, exc)` - string error types wrapped as `RuntimeError(str)`
- Removed `DLQ_MESSAGES_TOTAL` and `KafkaProducerClient` unused imports
- Added `topics_consumed` property listing all three subscribed topics for correct `source_topic` in DLQ payloads

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] bar_aggregator_agent test expected 4 producer starts (including removed DLQ producer)**
- Found during: Task 2
- Issue: `test_setup_retries_on_kafka_connection_error` asserted `mock_producer.start.call_count == 4` (2 failed + 1 main + 1 DLQ). After removing DLQ producer, count is 3.
- Fix: Updated test side_effects to 3 entries, assertion to `call_count == 3`
- Files modified: `tests/unit/service_tests/test_bar_aggregator_agent.py`
- Commit: 3af9446d

**2. [Rule 1 - Bug] graduation_compute_agent tests not setting `agent.name` attribute**
- Found during: Task 3
- Issue: `_make_agent()` fixture used `__new__` bypass but didn't set `name`. `_send_to_dlq` in BaseAgent accesses `self.name`, causing `AttributeError` through `__getattr__`.
- Fix: Added `a.name = "GraduationComputeAgent"` to fixture
- Files modified: `tests/unit/test_graduation_compute_agent.py`
- Commit: f0010b3b

**3. [Rule 1 - Bug] graduation_compute_agent DLQ payload assertion used old dict schema**
- Found during: Task 3
- Issue: Tests checked `dlq_payload["error"]` and `dlq_payload["transform_id"]` but `BaseAgent._send_to_dlq` wraps payload in `DLQPayload` schema which uses `error_message` field and nests original payload under `payload` key.
- Fix: Updated assertions to `dlq_payload["error_message"]` and `dlq_payload["payload"]["transform_id"]`
- Files modified: `tests/unit/test_graduation_compute_agent.py`
- Commit: f0010b3b

**4. [Rule 3 - Blocking] Pre-commit hooks couldn't find ruff/black in worktree**
- Found during: Task 1 commit
- Issue: Pre-commit hook uses `git rev-parse --show-toplevel` which returns the worktree path. Hook then looks for `${REPO_ROOT}/.venv/bin/ruff` which doesn't exist in the worktree.
- Fix: Created symlink `.venv -> /home/bg/dev/indicagent/.venv` in worktree root
- Files modified: `.venv` symlink in worktree

## Verification

```
grep -n "def _get_producer" src/core/agent/base.py         # matches
grep -n "DLQ_DEPTH" src/core/agent/base.py                  # empty
grep -n "DLQ_MESSAGES_TOTAL" src/core/agent/base.py        # matches
grep -n "_dlq_producer" services/bar_aggregator_agent.py   # empty
grep -n "def _dlq_topic" services/bar_aggregator_agent.py  # matches
grep -n "_dlq_producer" services/graduation_compute_agent.py services/llm_writer_service.py  # empty
grep -n "def _send_to_dlq" services/llm_writer_service.py  # empty
grep -n "def _dlq_topic" services/graduation_compute_agent.py services/llm_writer_service.py  # both match
grep -n "DLQ_DEPTH" services/llm_writer_service.py         # empty
pytest tests/unit/ -q                                       # 3248 passed
ruff check src/ services/                                   # all passed
```

## Self-Check: PASSED

All files found, all commits verified, all key methods and absence-of-dead-code confirmed.
