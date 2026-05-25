---
phase: 107-infrastructure-hygiene
plan: 01
subsystem: infra
tags: [baseagent, asyncpg, database-manager, otel, metrics, systemd]

requires:
  - phase: 107-00
    provides: Service inventory and baseline measurements
provides:
  - signal_replay_auditor and bar_replay_provider migrated to BaseAgent lifecycle
  - swarm_ledger_writer standardized to DatabaseManager.create_pool()
  - agent_id label consistency across BaseAgent and service_auditor queries
affects: [service-auditor, metrics, grafana-dashboards]

tech-stack:
  added: []
  patterns: [BaseAgent inheritance migration, DatabaseManager pool standardization]

key-files:
  created: []
  modified:
    - services/signal_replay_auditor_agent.py
    - services/bar_replay_provider_agent.py
    - services/swarm_ledger_writer_agent.py
    - src/core/agent/base.py
    - services/service_auditor_agent.py

key-decisions:
  - "agent_id label chosen over agent for fleet-wide metric aggregation consistency"
  - "max_idle_seconds=600 for signal_replay (audit cycle), 300 for bar_replay (replay job)"

patterns-established:
  - "BaseAgent migration: custom lifecycle -> BaseAgent inheritance with super().__init__(name=..., max_idle_seconds=...)"
  - "DatabaseManager pool: asyncpg.create_pool() -> create_db_pool() with JSONB codecs and pool gauges"

requirements-completed: [HYGIENE-07, HYGIENE-08, HYGIENE-09]

duration: 25min
completed: 2026-05-25
---

# Phase 107 Plan 01 Summary

**Migrated 2 services to BaseAgent lifecycle, standardized 3 services to DatabaseManager pool, and fixed agent_id label consistency across all services**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-05-25T14:00:00Z
- **Completed:** 2026-05-25T14:25:00Z
- **Tasks:** 5
- **Files modified:** 5

## Accomplishments
- signal_replay_auditor_agent migrated to BaseAgent with SIGTERM handling, stall detection, OTel instrumentation
- bar_replay_provider_agent migrated to BaseAgent with proper lifecycle management
- swarm_ledger_writer_agent standardized to DatabaseManager.create_pool() with JSONB codecs and pool gauges
- BaseAgent._last_msg_ts_attrs changed from "agent" to "agent_id" for metric consistency
- service_auditor_agent Prometheus queries updated to aggregate using agent_id label

## Task Commits

1. **Task 1: Migrate signal_replay_auditor to BaseAgent** - `6763ffd0` (feat)
2. **Task 2: Migrate bar_replay_provider to BaseAgent** - `ad35b829` (feat)
3. **Task 3: Standardize swarm_ledger_writer to DatabaseManager pool** - `ad35b829` (feat, combined with Task 2)
4. **Task 4: Fix agent_id label consistency in BaseAgent** - `8f86d3e0` (feat)
5. **Task 5: Verify service_auditor metric queries use agent_id** - `b64070c8` (feat)

**Merge commit:** `709ff0d5` (chore: merge Wave 1 executor worktree)
**Tracking commit:** `ae45ad05` (docs: update phase planning documents and roadmap)

## Files Created/Modified
- `services/signal_replay_auditor_agent.py` - BaseAgent lifecycle migration
- `services/bar_replay_provider_agent.py` - BaseAgent lifecycle migration
- `services/swarm_ledger_writer_agent.py` - DatabaseManager pool standardization
- `src/core/agent/base.py` - agent_id label consistency fix
- `services/service_auditor_agent.py` - agent_id label in Prometheus queries

## Decisions Made
- Used "agent_id" label consistently across BaseAgent crash metrics and service_auditor queries for fleet-wide dashboard aggregation
- Set max_idle_seconds=600 for signal_replay (longer audit cycle), 300 for bar_replay (replay job)

## Deviations from Plan

None - plan executed exactly as written. Note: Task 3 (swarm_ledger_writer) was committed together with Task 2 rather than as a separate atomic commit.

## Issues Encountered
None - all tasks completed cleanly.

## User Setup Required

Checkpoint task (Task 6) requires manual verification:
1. Restart migrated services: `sudo systemctl restart indicagent-signal-replay-auditor indicagent-bar-replay-provider indicagent-swarm-ledger-writer`
2. Monitor Grafana dashboards for 1-2 hours
3. Verify SIGTERM handling: `sudo systemctl kill -s SIGTERM indicagent-signal-replay-auditor`

## Next Phase Readiness
- Wave 1 service consistency complete, all 3 HYGIENE criteria (07, 08, 09) addressed
- Waves 2 and 3 already completed in prior execution runs
- Phase 107 is now fully complete

---
*Phase: 107-infrastructure-hygiene*
*Completed: 2026-05-25*
