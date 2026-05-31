---
phase: 111-naming-alignment
plan: 03
subsystem: infra
tags: [naming, structlog, observability, loki, prometheus, services]

# Dependency graph
requires:
  - phase: 111-naming-alignment
    plan: 02
    provides: "Service file renames; test file renames; systemd ExecStart updates; BaseDaemon auto-derive"
provides:
  - "~110 structlog event string prefixes updated across 16 service files to match derived agent_id"
  - "src/core/agent/base.py events use daemon. prefix (documented M2 intentional exception)"
  - "src/core/ai/base_agent.py events use ai_worker. prefix (documented M2 intentional exception)"
  - "M2 inline comments in both base files explaining role-prefix convention exception"
  - "test_base_agent.py assertions updated to daemon.run_failed/daemon.setup_failed"
  - "test_signal_auditor.py assertion updated to signal_auditor.lag_threshold_exceeded"
affects:
  - 111-04-PLAN
  - monitoring
  - observability
  - loki-queries

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Event string convention: {derived_agent_id}.{action} for all concrete services"
    - "Base-class role-prefix exception: daemon. for BaseDaemon, ai_worker. for BaseAIWorker — documented inline with M2 comment"

key-files:
  created: []
  modified:
    - services/bar_aggregator.py
    - services/bar_auditor.py
    - services/bar_writer.py
    - services/macro_analyzer.py
    - services/narrative_swarm.py
    - services/signal_auditor.py
    - services/signal_tracker.py
    - services/signal_metrics_analyzer.py
    - services/data_quality_auditor.py
    - services/ml_discovery_analyzer.py
    - services/alert_monitor.py
    - services/provider_merger.py
    - services/service_auditor.py
    - services/config_service.py
    - src/core/agent/base.py
    - src/core/ai/base_agent.py
    - tests/unit/core/test_base_agent.py
    - tests/unit/services/test_signal_auditor.py

key-decisions:
  - "Base-class lifecycle events cannot use a per-service agent_id prefix (base class has no single id); daemon. and ai_worker. role prefixes are documented as M2 intentional exceptions via inline comment"
  - "Several service files had intermediate prefixes (alerting., ml_data_quality., ml_discovery., narrative_group., signal_metrics_compute.) not caught by _agent. grep - these were also updated to the derived agent_id"
  - "provider_merger.py, service_auditor.py, config_service.py found to have stale _agent. event prefixes not listed in plan - auto-fixed inline with Task 1 (Rule 1)"

patterns-established:
  - "Loki queries: use {derived_agent_id}. prefix to filter events for a specific service"
  - "daemon. and ai_worker. prefixes identify BaseDaemon/BaseAIWorker lifecycle events (cross-service)"

requirements-completed:
  - ALIGN-03

# Metrics
duration: 20min
completed: 2026-05-30
---

# Phase 111 Plan 03: Structlog Event Prefix Alignment Summary

**~110 structlog event string prefixes updated to {derived_agent_id}.{action} across 16 service files; BaseDaemon uses daemon. prefix and BaseAIWorker uses ai_worker. prefix — both documented as intentional base-class role-prefix exceptions**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-05-30T21:07:00Z
- **Completed:** 2026-05-30T21:11:00Z
- **Tasks:** 2
- **Files modified:** 18

## Accomplishments

- 14 service files updated: bar_aggregator, bar_auditor, bar_writer, macro_analyzer, narrative_swarm, signal_auditor, signal_tracker, signal_metrics_analyzer, data_quality_auditor, ml_discovery_analyzer, alert_monitor, provider_merger, service_auditor, config_service
- `src/core/agent/base.py`: 13 event strings changed from `agent.` to `daemon.`; M2 comment added above first event
- `src/core/ai/base_agent.py`: 2 event strings changed from `ai_agent.` to `ai_worker.`; M2 comment added
- 3 test assertions updated to match new event strings (auto-fix Rule 1)
- 4049 unit tests green; ruff clean

## Task Commits

1. **Task 1: Replace structlog event prefixes in services/** - `acfe8111` (refactor)
2. **Task 2: Replace event prefixes in src/core/agent/base.py and src/core/ai/base_agent.py** - `a8f904fb` (refactor)

## Files Created/Modified

- `services/bar_aggregator.py` - bar_aggregator_agent. -> bar_aggregator. (3 events)
- `services/bar_auditor.py` - bar_auditor_agent. -> bar_auditor. (9 events)
- `services/bar_writer.py` - bar_writer_agent. -> bar_writer. (11 events)
- `services/macro_analyzer.py` - macro_compute_agent. -> macro_analyzer. (5 events)
- `services/narrative_swarm.py` - narrative_group. -> narrative_swarm. (7 events)
- `services/signal_auditor.py` - signal_auditor_agent. -> signal_auditor. (5 events)
- `services/signal_tracker.py` - signal_tracker_compute. -> signal_tracker. (1 event)
- `services/signal_metrics_analyzer.py` - signal_metrics_compute. -> signal_metrics_analyzer. (8 events)
- `services/data_quality_auditor.py` - ml_data_quality. -> data_quality_auditor. (6 events)
- `services/ml_discovery_analyzer.py` - ml_discovery. -> ml_discovery_analyzer. (8 events)
- `services/alert_monitor.py` - alerting. -> alert_monitor. (5 events)
- `services/provider_merger.py` - provider_merger_agent. -> provider_merger. (5 events)
- `services/service_auditor.py` - service_auditor_agent. -> service_auditor. (1 event)
- `services/config_service.py` - config_service_agent. -> config_service. (2 events)
- `src/core/agent/base.py` - agent. -> daemon. (13 events); M2 comment added
- `src/core/ai/base_agent.py` - ai_agent. -> ai_worker. (2 events); M2 comment added
- `tests/unit/core/test_base_agent.py` - 3 assertions updated to daemon.run_failed/daemon.setup_failed
- `tests/unit/services/test_signal_auditor.py` - 1 assertion updated to signal_auditor.lag_threshold_exceeded

## Decisions Made

- Base-class lifecycle events cannot carry a per-service `{derived_agent_id}` prefix because `BaseDaemon` and `BaseAIWorker` are subclassed by all services; `daemon.` and `ai_worker.` role prefixes are correct and documented as M2 intentional exceptions via inline comment in each file.
- Several service files already had intermediate stale prefixes (`alerting.`, `ml_data_quality.`, `ml_discovery.`, `narrative_group.`, `signal_metrics_compute.`) not caught by a simple `_agent.` grep pattern; these were also updated to the derived agent_id values as they represent the same naming drift problem.
- Files not in the plan (`provider_merger.py`, `service_auditor.py`, `config_service.py`) had stale `_agent.` event prefixes; fixed inline as Rule 1 auto-fixes.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] 3 unplanned service files had stale _agent. event prefixes**
- **Found during:** Task 1 (initial grep of services/ for _agent. logger calls)
- **Issue:** `provider_merger.py` (provider_merger_agent.), `service_auditor.py` (service_auditor_agent.), `config_service.py` (config_service_agent.) had stale prefixes not listed in the plan
- **Fix:** Replaced with correct derived agent_id prefixes: provider_merger., service_auditor., config_service.
- **Files modified:** services/provider_merger.py, services/service_auditor.py, services/config_service.py
- **Verification:** grep of all services/ logger calls shows zero _agent. prefixed events
- **Committed in:** acfe8111 (Task 1 commit)

**2. [Rule 1 - Bug] Intermediate stale prefixes (alerting., ml_data_quality., ml_discovery., narrative_group., signal_metrics_compute.) not caught by _agent. grep**
- **Found during:** Task 1 (manual grep of each file's logger calls)
- **Issue:** Some services had already dropped the _agent suffix but still used wrong shorthand prefix not matching derived agent_id
- **Fix:** Updated all to derived agent_id prefix: alert_monitor., data_quality_auditor., ml_discovery_analyzer., narrative_swarm., signal_metrics_analyzer.
- **Files modified:** services/alert_monitor.py, services/data_quality_auditor.py, services/ml_discovery_analyzer.py, services/narrative_swarm.py, services/signal_metrics_analyzer.py
- **Verification:** All logger calls now use derived agent_id prefix matching class name
- **Committed in:** acfe8111 (Task 1 commit)

**3. [Rule 1 - Bug] 3 test assertions used stale event string values**
- **Found during:** Task 2 (pytest run after base.py and signal_auditor.py updates)
- **Issue:** test_base_agent.py asserted "agent.run_failed" and "agent.setup_failed"; test_signal_auditor.py asserted "signal_auditor_agent.lag_threshold_exceeded"
- **Fix:** Updated assertions to "daemon.run_failed", "daemon.setup_failed", "signal_auditor.lag_threshold_exceeded"
- **Files modified:** tests/unit/core/test_base_agent.py, tests/unit/services/test_signal_auditor.py
- **Verification:** All 4049 unit tests pass
- **Committed in:** acfe8111/a8f904fb (Task 1 and Task 2 commits)

---

**Total deviations:** 3 auto-fixed (all Rule 1 bugs — stale event strings and test assertions)
**Impact on plan:** All fixes necessary for correctness. Broader than plan scope but all within same naming-alignment objective. No scope creep.

## Issues Encountered

- Pre-commit hook `ruff`/`black` not found on first commit attempt (worktree lacked `.venv` symlink); fixed by symlinking `/home/bg/dev/indicagent/.venv` into worktree directory (same fix as Wave 1).

## Self-Check

Verified:
- `acfe8111` present in git log - FOUND
- `a8f904fb` present in git log - FOUND
- `grep -rn '"agent\.' src/core/agent/base.py` - 0 results (PASS)
- `grep -rn '"ai_agent\.' src/core/ai/base_agent.py` - 0 results (PASS)
- `grep -n '"daemon\.starting"' src/core/agent/base.py` - 1 result (PASS)
- `4049 passed, 31 skipped` in pytest (PASS)

## Self-Check: PASSED

## Next Phase Readiness

- Plan 04 (AUTHORING.md + TEMPLATE.py reference updates / pre-commit hook) can proceed - all event strings now aligned
- Loki queries can filter by `{derived_agent_id}.` prefix to isolate per-service events
- `daemon.` prefix identifies BaseDaemon lifecycle events across all services (start/stop/dlq/stall)
- `ai_worker.` prefix identifies BaseAIWorker compute events across all LLM agents

---
*Phase: 111-naming-alignment*
*Completed: 2026-05-30*
