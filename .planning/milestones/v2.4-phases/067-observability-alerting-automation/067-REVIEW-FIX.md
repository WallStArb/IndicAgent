---
phase: 067-observability-alerting-automation
fixed_at: 2026-04-14T00:00:00Z
review_path: .planning/phases/067-observability-alerting-automation/067-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 5
skipped: 1
status: partial
---

# Phase 067: Code Review Fix Report

**Fixed at:** 2026-04-14T00:00:00Z
**Source review:** .planning/phases/067-observability-alerting-automation/067-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 6
- Fixed: 5
- Skipped: 1

## Fixed Issues

### WR-01: Runtime TypeError in `_get_consumer_lag` -- frozenset not subscriptable

**Files modified:** `services/bar_aggregator_agent.py`
**Commit:** 55bc536f
**Applied fix:** Replaced `self._kafka_consumer._consumer` direct access with `getattr(self._kafka_consumer, "_consumer", None)` guarded for None. Replaced `partitions[0]` subscript with `next(iter(partitions))` to handle frozenset. Added `await` to `inner.position(tp)` call.

### WR-02: Blocking `subprocess.run` inside async event loop

**Files modified:** `services/service_auditor_agent.py`
**Commit:** 857cb1d2
**Applied fix:** Replaced synchronous `subprocess.run(cmd, check=True, capture_output=True)` with async `asyncio.create_subprocess_exec` + `asyncio.wait_for` with 30s timeout. Preserved error logging for non-zero return codes and general exceptions.

### WR-04: `_run` in `SwarmOrchestratorComputeAgent` cannot propagate stop signal -- shutdown deadlock

**Files modified:** `services/swarm_orchestrator_agent.py`
**Commit:** 8d62eb87
**Applied fix:** Added `if not self.running: break` at the top of both `_bar_loop` and `_signal_loop` async iterators. When BaseAgent sets `_stop_event` on SIGTERM, `self.running` returns False, breaking both loops and allowing `_run` to return so `_teardown` can execute cleanly. **Status: fixed, requires human verification** (logic fix -- confirm that checking `self.running` at the top of each message loop is the correct shutdown signaling pattern).

### WR-05: `setup_service_logging` call in ML agent `__init__` is overwritten by BaseAgent

**Files modified:** `src/core/service_utils.py`
**Commit:** 914c4118
**Applied fix:** Made `setup_service_logging` idempotent using a module-level `_configured_log_file` sentinel. The first call wins -- subsequent calls are no-ops. This prevents BaseAgent's auto-derived log path (`m_l_data_quality_auditor_agent.log`) from overwriting the correct path set by the subclass (`ml_data_quality_agent.log`). Safe because each service runs in its own process with a single agent instance.

### WR-06: RSI outlier threshold unreachable -- `_check_outliers` score is always 1.0

**Files modified:** `services/ml_data_quality_agent.py`
**Commit:** 4b3750cd
**Applied fix:** Replaced mathematically impossible condition `ABS(rsi - 50) > 120` with `ABS(rsi - 50) > 45` (catches RSI outside [5, 95] -- genuine outliers). Replaced `atr > 200` with `atr < 0` (structurally impossible negative ATR). Updated docstring to document the new threshold rationale. **Status: fixed, requires human verification** (logic fix -- confirm that RSI outside [5,95] and negative ATR are the desired outlier definitions).

## Skipped Issues

### WR-03: `asyncpg` not imported at top level but used in type annotation

**File:** `services/swarm_orchestrator_agent.py:210`
**Reason:** code context differs from review -- `from __future__ import annotations` is already present at line 9 of the file, which makes type annotations lazy and prevents the `NameError`. The fix was already applied in the current codebase.
**Original issue:** `_seed_context_cache` has the annotation `pool: asyncpg.Pool` but `asyncpg` was not imported at top level, potentially causing `NameError`.

---

_Fixed: 2026-04-14T00:00:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
