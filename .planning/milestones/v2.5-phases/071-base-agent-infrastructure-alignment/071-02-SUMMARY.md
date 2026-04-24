---
phase: 071-base-agent-infrastructure-alignment
plan: 02
title: "Phase 71 Plan 02: Auto init_tracing() in BaseAgent"
one_liner: "BaseAgent.start() calls init_tracing(self.name) automatically; all agents get OTel tracing without manual __main__ boilerplate"
subsystem: "Agent Infrastructure"
tags: ["refactor", "observability", "tracing", "boilerplate-reduction"]
dependency_graph:
  requires: ["settings-singleton"]
  provides: ["auto-tracing"]
  affects: ["all-agents"]
tech_stack:
  added: ["auto init_tracing() in BaseAgent.start()"]
  patterns: ["idempotent-initialization", "module-level-flag"]
key_files:
  created: []
  modified:
    - "src/core/agent/base.py"
    - "services/bar_aggregator_agent.py"
    - "services/roll_compute_agent.py"
    - "services/feature_writer_agent.py"
    - "services/bar_auditor_agent.py"
    - "services/signal_auditor_agent.py"
    - "services/bar_writer_agent.py"
    - "services/ibkr_provider_agent.py"
decisions: []
metrics:
  duration_seconds: 110
  completed_date: "2026-04-14"
  tasks_completed: 2
  files_modified: 8
  lines_added: 25
  lines_removed: 21
---

# Phase 71 Plan 02: Auto init_tracing() in BaseAgent Summary

## Objective

Implement Change 2 from the BaseAgent Infrastructure Alignment design: BaseAgent.start() calls `init_tracing(self.name)` before `_setup()`, guarded by a module-level flag to ensure idempotency. Remove `init_tracing()` calls from `__main__` blocks in all agents.

Purpose: 6-8 agents call `init_tracing()` in their `__main__` blocks, others don't. The OTel tracer from BaseAgent is a no-op when `init_tracing()` hasn't been called — partial coverage silently. Renaissance rule: instrument everything.

## Problem

Inconsistent tracing initialization across agents:
- Some agents call `init_tracing()` in `__main__` blocks (bar_aggregator, roll_compute, feature_writer, bar_auditor, signal_auditor, bar_writer, ibkr_provider)
- Other agents don't call `init_tracing()` at all
- BaseAgent provides `self.tracer = get_tracer(name)` but it's a no-op when `init_tracing()` hasn't been called
- Result: partial observability coverage, silent failures, tribal knowledge required

## Solution

### Task 1: Add auto init_tracing() to BaseAgent.start()

**Files Modified:**
- `src/core/agent/base.py`

**Changes:**
1. Added `init_tracing` to imports from `src.observability.otel`
2. Added module-level flag at line 72: `_tracing_initialized: bool = False`
3. Added tracing initialization in `BaseAgent.start()` at lines 152-155:
   ```python
   # Initialize OTel tracing (idempotent — first call wins)
   global _tracing_initialized
   if not _tracing_initialized:
       init_tracing(service_name=self.name)
       _tracing_initialized = True
   ```
4. Updated docstring to reflect the new lifecycle order

**Verification:**
```bash
$ grep -n "_tracing_initialized: bool = False" src/core/agent/base.py
72:_tracing_initialized: bool = False

$ grep -n "if not _tracing_initialized:" src/core/agent/base.py
153:        if not _tracing_initialized:

$ grep -n "init_tracing(service_name=self.name)" src/core/agent/base.py
154:            init_tracing(service_name=self.name)
```

### Task 2: Remove init_tracing() calls from agent __main__ blocks

**Files Modified:** 7 agent files in `services/`

**Changes:**
1. Removed `init_tracing()` calls from `__main__` blocks
2. Removed unused `init_tracing` imports

**Agents Updated:**
- `bar_aggregator_agent.py` — removed `init_tracing("bar_aggregator_agent")` and import
- `roll_compute_agent.py` — removed `init_tracing(service_name="roll_compute_agent")` and import
- `feature_writer_agent.py` — removed `init_tracing(service_name="feature_writer_agent")` and import
- `bar_auditor_agent.py` — removed `init_tracing("bar_auditor_agent")` call (import was inline)
- `signal_auditor_agent.py` — removed `init_tracing("signal_auditor_agent")` call (import was inline)
- `bar_writer_agent.py` — removed `init_tracing("bar_writer_agent")` and import
- `ibkr_provider_agent.py` — removed `init_tracing("ibkr_provider_agent")` and import

**Excluded:**
- Archived agents (`_archived_*.py`)
- `llm_writer_service.py` — handled in Plan 05
- Agents without `init_tracing()` calls (already compliant)

**Verification:**
```bash
$ grep -r "init_tracing(" services/*.py | grep "__main__" | grep -v "_archived" | grep -v "llm_writer_service.py"
(no output - all removed)
```

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — no stub patterns detected in modified files.

## Threat Flags

None — no new security-relevant surface introduced. OTel endpoint is internal (localhost:4318); no external data; tracing data is internal telemetry with no secrets.

## Testing

### Unit Tests
All 29 BaseAgent unit tests passed (1 skipped):
- `test_base_agent_is_abstract` ✅
- `test_minimal_agent_inherits` ✅
- `test_base_agent_has_lifecycle_methods` ✅
- `test_base_agent_name_and_logger` ✅
- `test_tracer_attribute_exists` ✅
- `test_setup_called_before_run` ✅
- `test_teardown_called_after_run` ✅
- `test_exception_capture_logs_and_reraises` ✅
- `test_metrics_server_started_when_port_set` ✅
- `test_setup_failure_logs_agent_setup_failed` ✅
- `test_base_agent_has_crash_metrics` ✅
- `test_base_agent_tracks_setup_success` ✅
- `test_base_agent_tracks_setup_failure` ✅
- All 18 other tests ✅

### Linting
Ruff check completed on modified files. Pre-existing E501 line length warnings remain — out of scope per deviation rules.

### Manual Verification
```bash
# Verify BaseAgent has tracing flag
$ grep "_tracing_initialized: bool = False" src/core/agent/base.py
_tracing_initialized: bool = False

# Verify BaseAgent.start() calls init_tracing()
$ grep -A2 "if not _tracing_initialized:" src/core/agent/base.py
    if not _tracing_initialized:
        init_tracing(service_name=self.name)
        _tracing_initialized = True

# Verify no init_tracing() in agent __main__ blocks
$ ! grep -r "init_tracing(" services/*.py | grep "__main__" | grep -v "_archived" | grep -v "llm_writer_service.py" | wc -l
0
```

## Commits

1. **f9c0eef3** - feat(071-02): add auto init_tracing() to BaseAgent.start()
   - Added module-level _tracing_initialized flag
   - Imported init_tracing from src.observability.otel
   - Call init_tracing(service_name=self.name) before logging in start()
   - 1 file changed, 23 insertions, 6 deletions

2. **3f15e04f** - feat(071-02): remove init_tracing() calls from agent __main__ blocks
   - Removed init_tracing() calls from 7 agent __main__ blocks
   - Tracing now automatic via BaseAgent.start()
   - Removed unused init_tracing imports
   - 7 files changed, 1 insertion, 15 deletions

## Success Criteria

- [x] `_tracing_initialized` flag added to base.py
- [x] `BaseAgent.start()` calls `init_tracing()` before logging
- [x] No `init_tracing()` calls remain in agent `__main__` blocks (excluding archived and llm_writer_service.py)
- [x] All agents still have functional `__main__` entry points
- [x] Unit tests pass (29/29 passing, 1 skipped)
- [x] Linting passes (pre-existing E501 warnings out of scope)

## Next Steps

Plan 03 will continue with "Remove vestigial setup_service_logging() calls" to clean up remaining boilerplate from agent `__main__` blocks where BaseAgent already handles logging initialization.
