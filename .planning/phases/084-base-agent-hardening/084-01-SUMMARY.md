---
phase: "084"
plan: "01"
subsystem: base-agent
tags: [infra, observability, circuit-breaker, otel, hardening]
dependency_graph:
  requires: []
  provides:
    - AGENT_DLQ_TOTAL OTel counter in src/observability/metrics.py
    - AGENT_SETUP_RETRIES_TOTAL OTel counter in src/observability/metrics.py
    - AGENT_CIRCUIT_BREAKER_STATE OTel gauge in src/observability/metrics.py
    - AI_AGENT_ERRORS_TOTAL OTel counter in src/observability/metrics.py
    - BaseAgent.SETUP_RETRY_ATTEMPTS / SETUP_RETRY_BACKOFF_S / circuit_breaker class attrs
    - BaseAgent._cb_open open-gate flag
    - BaseAgent._setup_with_retry() using class attrs
    - INFRA-03 and INFRA-05 requirements verified by unit tests
  affects:
    - src/core/agent/base.py
    - src/observability/metrics.py
    - tests/unit/test_base_agent.py
tech_stack:
  added: []
  patterns:
    - OTel counter/gauge instruments via _meter.create_counter / _meter.create_gauge
    - Class attribute configuration for retry/CB (annotated assignments, no ClassVar)
    - Cached OTel attribute dicts in __init__ for hot-path reuse
key_files:
  created: []
  modified:
    - src/observability/metrics.py
    - src/core/agent/base.py
    - tests/unit/test_base_agent.py
decisions:
  - Used module-level _meter in metrics.py (not _base_meter from base.py) for new instruments per plan spec
  - AGENT_SETUP_RETRIES_TOTAL fires in warning branch (pre-final attempt only), count = SETUP_RETRY_ATTEMPTS - 1
  - CB open-gate wrapped inside start() with its own try/except so both _cb_open=True and re-raise happen before outer except sets AGENT_SETUP_FAILURE_TOTAL
metrics:
  duration_minutes: 3
  completed_date: "2026-05-16"
  tasks_completed: 3
  tasks_total: 3
  files_modified: 3
---

# Phase 084 Plan 01: Base Agent Hardening - OTel Instruments + Retry Class Attrs Summary

**One-liner:** Four new OTel instruments (agent_dlq_total, agent_setup_retries_total, agent_circuit_breaker_state, ai_agent_errors_total) plus class-attribute configurable retry/circuit-breaker opt-in on BaseAgent with 5 covering unit tests.

## What Was Built

### Task 1 - Four new OTel instruments in metrics.py (commit 408664bd)

Added a "Base agent hardening metrics (Phase 84)" section after the "Agent liveness" block:

- `AGENT_DLQ_TOTAL` - Counter per agent for every DLQ event (all paths, including log-only discard)
- `AGENT_SETUP_RETRIES_TOTAL` - Counter per setup retry attempt (each loop iteration before final)
- `AGENT_CIRCUIT_BREAKER_STATE` - Gauge for CB state: 0=closed, 1=half-open (reserved), 2=open
- `AI_AGENT_ERRORS_TOTAL` - Counter for AI agent _compute() errors by agent_id and error_type

All use the existing `_meter.create_counter()` / `_meter.create_gauge()` pattern. No prometheus_client imports.

### Task 2 - Class attrs + CB open-gate + DLQ counter in base.py (commit bb5a6e45)

Five surgical changes to `src/core/agent/base.py`:

1. Added three class attributes on BaseAgent: `SETUP_RETRY_ATTEMPTS: int = 3`, `SETUP_RETRY_BACKOFF_S: float = 2.0`, `circuit_breaker: bool = False`

2. Imported `AGENT_DLQ_TOTAL`, `AGENT_SETUP_RETRIES_TOTAL`, `AGENT_CIRCUIT_BREAKER_STATE` at module top (grouped with existing metric imports)

3. Added in `__init__`: `self._dlq_attrs = {"agent_id": self._agent_label}`, `self._cb_attrs = {"agent": self._agent_label}`, `self._cb_open: bool = False`

4. Rewrote `_setup_with_retry()`: replaced local `_attempts = 3` and `_backoff_base = 2.0` with `self.SETUP_RETRY_ATTEMPTS` and `self.SETUP_RETRY_BACKOFF_S`; added `AGENT_SETUP_RETRIES_TOTAL.add(1, self._cb_attrs)` in the warning/sleep branch

5. Modified `start()`: branched on `self.circuit_breaker` - True path calls `_setup_with_retry()`, on total failure sets `self._cb_open = True` and emits `AGENT_CIRCUIT_BREAKER_STATE.set(2, self._cb_attrs)` before re-raising

6. Added `AGENT_DLQ_TOTAL.add(1, self._dlq_attrs)` unconditionally at the top of `_send_to_dlq()` before any routing logic

### Task 3 - Unit tests covering INFRA-03 and INFRA-05 (commit 95c03198)

Five new tests appended to `tests/unit/test_base_agent.py`:

- `test_setup_retry_class_attrs_default` - asserts defaults (3, 2.0, False)
- `test_setup_retry_class_attrs_overridable` - subclass with SETUP_RETRY_ATTEMPTS=1, SETUP_RETRY_BACKOFF_S=0.1 picks up overrides
- `test_circuit_breaker_default_off` - BaseAgent.circuit_breaker is False; _cb_open starts False
- `test_circuit_breaker_opens_after_all_retries_fail` - circuit_breaker=True, SETUP_RETRY_ATTEMPTS=2, _setup always raises; _cb_open is True after start() raises
- `test_setup_retry_counter_increments_on_retry` - SETUP_RETRY_ATTEMPTS=3, counter fires 2 times (N-1 pre-final retries)

All 33 existing tests continue to pass (1 pre-existing skip unchanged).

## Verification

```
pytest tests/unit/test_base_agent.py -v        33 passed, 1 skipped
ruff check metrics.py base.py test_base_agent.py   All checks passed
python -c "from src.observability.metrics import ..."  ok
python -c "from src.core.agent.base import BaseAgent; assert BaseAgent.SETUP_RETRY_ATTEMPTS == 3 ..."  ok
grep "_attempts = 3" src/core/agent/base.py    not found (good)
grep "_backoff_base = 2.0" src/core/agent/base.py  not found (good)
```

## Deviations from Plan

None - plan executed exactly as written.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1    | 408664bd | feat(084-01): register four new OTel instruments in metrics.py |
| 2    | bb5a6e45 | feat(084-01): add class attrs, CB open-gate, DLQ counter to BaseAgent |
| 3    | 95c03198 | test(084-01): add INFRA-03 class attr and INFRA-05 circuit breaker tests |

## Self-Check: PASSED

All created/modified files verified on disk. All three task commits verified in git log.
