# Phase 071 Plan 03: Remove Vestigial setup_service_logging() Calls + Duplicate Lag Task Creation

**One-liner:** Removed vestigial `setup_service_logging()` calls from `__main__` blocks and duplicate `lag_task` creation from 11 agents, relying on BaseAgent infrastructure for both.

**Completed:** 2026-04-14  
**Type:** Infrastructure Refactoring  
**Wave:** 2

---

## Objective

Remove vestigial code patterns now handled by `BaseAgent`:
1. Remove manual `setup_service_logging()` calls from `__main__` blocks (BaseAgent handles logging in `__init__`)
2. Remove duplicate `lag_task = asyncio.create_task(self._report_consumer_lag())` from agents (BaseAgent.start() creates lag task at line 155)

---

## Files Modified

### Task 1: Remove vestigial setup_service_logging() from __main__ blocks
- `services/bar_aggregator_agent.py`
- `services/bar_writer_agent.py`
- `services/contract_metadata_writer_agent.py`
- `services/provider_merger_agent.py`
- `services/service_auditor_agent.py`

### Task 2: Remove duplicate lag_task creation from agents
- `services/ai_narrative_agent.py`
- `services/bar_aggregator_agent.py` (also removed from finally block)
- `services/contract_metadata_writer_agent.py`
- `services/cross_asset_service.py`
- `services/parity_auditor_agent.py`
- `services/roll_compute_agent.py` (also removed from finally block)
- `services/service_auditor_agent.py` (removed from task loop)
- `services/signal_auditor_agent.py`
- `services/signal_metrics_compute_agent.py` (also removed setup_service_logging from _amain)
- `services/signal_metrics_writer_agent.py` (also removed setup_service_logging from _amain)
- `services/swarm_orchestrator_agent.py`

---

## Deviations from Plan

**None - plan executed exactly as written.**

---

## Key Technical Decisions

1. **setup_service_logging() removal:** BaseAgent.__init__() calls `setup_service_logging()` at line 98 with auto-derived log path (PascalCase → snake_case conversion). Manual calls in `__main__` blocks were vestigial noise (idempotent "first call wins" per WR-05 fix) but are now removed for clean code.

2. **lag_task creation removal:** BaseAgent.start() creates lag_task at line 155 using `asyncio.create_task(self._report_consumer_lag())`. Several agents created a second lag_task in their `_run()` method, resulting in two concurrent lag reporting loops. These duplicates have been removed.

3. **finally block cleanup:** For agents with try/finally blocks around lag_task, removed both the `lag_task.cancel()` and `await lag_task` code. BaseAgent.start() manages lag_task lifecycle.

4. **service_auditor_agent.py special case:** This agent creates multiple background tasks (prom_task, sysd_task, hb_task, roll_task). The lag_task was removed from the task loop, but the other tasks remain (they are not duplicated by BaseAgent).

5. **swarm_orchestrator_agent.py special case:** This agent uses `asyncio.gather()` to run bar_task, signal_task, and lag_task concurrently. Removed lag_task from the gather call and from cancel/await loops.

---

## Verification

- [x] No `setup_service_logging()` calls in agent `__main__` blocks (excluding archived files and llm_writer_service.py)
- [x] No duplicate `lag_task = asyncio.create_task(self._report_consumer_lag())` in agents
- [x] All agents still have functional `__main__` entry points
- [x] BaseAgent.start() still creates lag task at line 155

```bash
# Verification commands
! grep -r "setup_service_logging(" services/*.py | grep "__main__" | grep -v "_archived" | grep -v "llm_writer_service.py" | wc -l | xargs -I {} test {} -eq 0
! grep -r "lag_task = asyncio.create_task(self._report_consumer_lag())" services/*.py | grep -v "_archived" | wc -l | xargs -I {} test {} -eq 0
```

---

## Threat Surface Scan

**No new security-relevant surface introduced.** This plan only removes vestigial code. No new endpoints, auth paths, file access patterns, or schema changes were created.

---

## Known Stubs

**None.** No stub patterns found in modified files.

---

## Commits

1. `dd1b9465` - refactor(071-03): remove vestigial setup_service_logging() from __main__ blocks
2. `16805d28` - refactor(071-03): remove duplicate lag_task creation from agents

---

## Self-Check: PASSED

- [x] All modified files exist
- [x] All commits exist in git log
- [x] Verification commands pass
- [x] No unintended deletions (verified commits)
- [x] SUMMARY.md created
