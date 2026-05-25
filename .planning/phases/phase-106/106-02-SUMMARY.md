---
phase: 106-foundation-hardening
plan: 02
subsystem: infra
tags: [service-auditor, dag, systemd, oneshot, kafka-lag, monitoring]

# Dependency graph
requires:
  - phase: 105-architecture-hotfix-sprint
    provides: base correctness fixes that phase 106 builds on
provides:
  - Complete _DAG_ORDER registry with 9 previously-missing services and justified priorities
  - _ONESHOT_UNITS frozenset with guard on all _restart_service_by_unit call sites
  - Correct _LAG_THRESHOLDS for graduation-compute and roll-compute
  - Correct _AGENT_ID_TO_UNIT key for feature_writer_agent
  - systemd unit file dependencies pointing at real units
affects: [service-auditor, restart-ordering, phase-106-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_ONESHOT_UNITS frozenset pattern: guard all restart call sites to prevent auditor from fighting systemd timers"
    - "Inline priority comments on every _DAG_ORDER entry documenting upstream/downstream reasoning"

key-files:
  created: []
  modified:
    - services/service_auditor_agent.py
    - tests/unit/services/test_service_auditor_agent.py
    - production/systemd/indicagent-intelligence-pipeline.service
    - production/systemd/indicagent-alerting-agent.service
    - production/systemd/indicagent-dlq-drain.service

key-decisions:
  - "indicagent-roll-compute stays at priority 8 in _DAG_ORDER (not moved to 3 per audit D-10) because it is a timer-triggered oneshot — audit's priority-3 recommendation assumes daemon restart model"
  - "indicagent-roll-compute added to _ONESHOT_UNITS: inactive between timer runs is correct behavior, not a stall"
  - "_evaluate_service_dynamic guarded with top-level 'if unit in _ONESHOT_UNITS: return' — covers ALL restart paths inside the function including data-stoppage and graduated-restart branches"
  - "indicagent-intelligence-pipeline priority moved from 5 to 6: cross-asset at priority 5 must start first since intelligence-pipeline consumes cross-asset topic output"
  - "Test removed phantom services (parity-auditor, feature-snapshot-writer) not present in live system"

patterns-established:
  - "_ONESHOT_UNITS frozenset: define once, guard at every _restart_service_by_unit call site"
  - "DAG priority comments: every _DAG_ORDER entry documents its upstream dependency and justification"

requirements-completed: []

# Metrics
duration: 5min
completed: 2026-05-24
---

# Phase 106 Plan 02: DAG Correctness and Systemd Hardening Summary

**_ONESHOT_UNITS frozenset guards all 3 restart call sites; 9 missing services added to _DAG_ORDER with priority comments; systemd unit files reference real units only**

## Performance

- **Duration:** 5 min
- **Started:** 2026-05-24T20:49:23Z
- **Completed:** 2026-05-24T20:53:52Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- Added 9 missing services to `_DAG_ORDER` with justified priorities and inline comments documenting upstream/downstream reasoning for every entry
- Created `_ONESHOT_UNITS` frozenset (8 members) and guarded all 3 `_restart_service_by_unit` call sites — the stall-detection loop and the `_evaluate_service_dynamic` top-level gate cover both the graduated-restart branch and the data-stoppage branch
- Added missing `_LAG_THRESHOLDS` entries for `indicagent-graduation-compute` and `indicagent-roll-compute` (500 each)
- Fixed `_AGENT_ID_TO_UNIT` key from `"feature_writer"` to `"feature_writer_agent"` (matches actual `name=` arg in `feature_writer_agent.py:234`)
- Fixed 3 systemd unit file dependencies: intelligence-pipeline `After=` points at real `indicagent-bar-aggregator.service`; alerting-agent and dlq-drain `After=` point at `indicagent-redpanda-ready.service` instead of bare `redpanda.service`

## Task Commits

1. **Tasks 1+2: DAG registry + _ONESHOT_UNITS guard** - `b57ff91c` (feat)
2. **Task 3: systemd unit file dependencies** - `4a5e7e70` (fix)

## Files Created/Modified
- `services/service_auditor_agent.py` - Complete DAG registry, _ONESHOT_UNITS, lag thresholds, agent-id fix
- `tests/unit/services/test_service_auditor_agent.py` - Removed phantom service entries from required set
- `production/systemd/indicagent-intelligence-pipeline.service` - Fixed After=/Wants= to use indicagent-bar-aggregator.service
- `production/systemd/indicagent-alerting-agent.service` - Fixed After= to use indicagent-redpanda-ready.service
- `production/systemd/indicagent-dlq-drain.service` - Fixed After= to use indicagent-redpanda-ready.service

## Decisions Made
- `indicagent-roll-compute` stays at priority 8 (not moved to 3 per audit D-10): the audit recommendation assumes a daemon restart model; roll-compute is timer-triggered and the auditor must not restart it on its own schedule
- `indicagent-intelligence-pipeline` priority moved from 5 to 6: it consumes cross-asset topic output, so cross-asset (priority 5) must be started first during recovery
- `_evaluate_service_dynamic` guarded at top of function rather than at each individual restart site within the function — cleaner and exhaustive; covers all future restart paths added inside the function

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed phantom services from test required set**
- **Found during:** Task 2 verification (pytest run)
- **Issue:** `test_dag_order_covers_required_services` required `indicagent-parity-auditor` and `indicagent-feature-snapshot-writer` — both do not exist in the live system (verified against `/etc/systemd/system/`)
- **Fix:** Removed the two phantom entries from the test's `required` set with a comment explaining why
- **Files modified:** `tests/unit/services/test_service_auditor_agent.py`
- **Verification:** All 17 auditor unit tests pass
- **Committed in:** `b57ff91c` (combined with Tasks 1+2)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug in test)
**Impact on plan:** Required to make auditor tests green; no scope creep.

## Issues Encountered
- Worktree lacked `.venv` symlink — pre-commit hook couldn't find ruff/black at `REPO_ROOT/.venv/bin/`. Fixed by symlinking `/home/bg/dev/indicagent/.venv` into the worktree directory.
- Pre-existing test failures (8 tests): `test_cis_distribution_sets_gauges`, 6x `test_service_contract_resolution`, `test_do_flush_handles_db_error_buffer_preserved` — all confirmed pre-existing before this plan's changes. Out of scope; logged here for tracking.

## Next Phase Readiness
- Service auditor now monitors all deployed units; no blind spots for the 9 previously-missing services
- `_ONESHOT_UNITS` pattern is documented and can be extended when new timer-triggered services are added
- systemd dependencies are clean — no phantom unit references
- Ready for Phase 106 remaining plans (106-03 through 106-06)

---
*Phase: 106-foundation-hardening*
*Completed: 2026-05-24*
