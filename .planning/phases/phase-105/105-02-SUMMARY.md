---
phase: 105-architecture-hotfix-sprint
plan: 02
subsystem: persistence
tags: [kafka, writer-agents, offset-commit, db-connect, stall-detection, liveness]

# Dependency graph
requires: []
provides:
  - FeatureWriterAgent fails loudly on DB connect failure (no more ghost-run)
  - BarWriterAgent stall watchdog fires on dead consumer via _record_message_consumed()
  - SwarmLedgerWriterAgent commits Kafka offsets only after successful or terminal-invalid DB writes
affects: [bar-writer, feature-writer, swarm-ledger-writer, service-auditor, systemd-restart]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fail-fast DB connect: raise on DatabaseManager.initialize() failure, no db_manager=None ghost-run"
    - "Liveness call placement: _record_message_consumed() after contract-update routing, before bar parse try:"
    - "By-outcome Kafka commit: enable_auto_commit=False + await self._consumer.commit() on terminal outcome only"

key-files:
  created: []
  modified:
    - services/feature_writer_agent.py
    - services/bar_writer_agent.py
    - services/swarm_ledger_writer_agent.py

key-decisions:
  - "FeatureWriterAgent._connect_database() raises on failure; systemd Restart=on-failure provides backoff (no retry loop in service)"
  - "BarWriterAgent._record_message_consumed() placed after contract-update continue so contract-update-only traffic does not falsely mark liveness"
  - "_handle_event() returns bool (terminal=True) for both success and invalid payloads; malformed messages committed to avoid infinite replay"
  - "SwarmLedgerWriterAgent transient DB exceptions propagate from _handle_event() to _run() which skips commit, enabling re-delivery"

patterns-established:
  - "Ghost-run prevention: never set db_manager=None and continue; raise so caller (systemd) restarts cleanly"
  - "Custom _run() loops that bypass BaseWriterAgent must call _record_message_consumed() per consumed message"
  - "enable_auto_commit=False pattern for BaseAgent consumers: manual commit after terminal outcome, no commit on transient exception"

requirements-completed: [HF-4, HF-5, HF-7]

# Metrics
duration: 3min
completed: 2026-05-24
---

# Phase 105 Plan 02: Writer Service Bugs & Shadow Governance Summary

**Eliminated three silent-failure bugs in writer services: FeatureWriterAgent DB ghost-run (~160 rows/min data loss), BarWriterAgent stall-watchdog blindness, and SwarmLedgerWriterAgent pre-write Kafka offset commit (message loss on DB failure)**

## Performance

- **Duration:** 3 min
- **Started:** 2026-05-24T11:41:14Z
- **Completed:** 2026-05-24T11:44:00Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- FeatureWriterAgent now raises on DB connect failure instead of silently running with db_manager=None and dropping ~160 rows/min; systemd Restart=on-failure handles backoff
- BarWriterAgent._run() calls _record_message_consumed() after the contract-update routing block, enabling BaseAgent stall watchdog and service_auditor stall detection
- SwarmLedgerWriterAgent uses enable_auto_commit=False with explicit by-outcome commit policy: success or terminal-invalid commits the offset; transient DB exceptions skip commit and allow re-delivery

## Task Commits

Each task was committed atomically:

1. **Task 1: FeatureWriterAgent fail-fast on DB connect failure (HF-4)** - `97a4a854` (fix)
2. **Task 2: BarWriterAgent _record_message_consumed() in custom _run() loop (HF-7)** - `55196e46` (fix)
3. **Task 3: SwarmLedgerWriterAgent disable auto-commit + wire explicit by-outcome manual commit (HF-5)** - `7dc5dcce` (fix)

## Files Created/Modified

- `services/feature_writer_agent.py` - _connect_database() except block: replaced warning+db_manager=None with error log + raise
- `services/bar_writer_agent.py` - _run() loop: added self._record_message_consumed() after contract-update routing, before bar-parse try
- `services/swarm_ledger_writer_agent.py` - enable_auto_commit=True -> False; _handle_event() returns bool; _run() loop commits only on terminal outcome

## Decisions Made

- Raise-and-exit pattern for DB connect failure mirrors ctx_writer_agent.py's existing pattern; no retry loop added (BaseAgent._setup_with_retry is the right place if ever needed, out of scope here)
- _record_message_consumed() placed after contract-update `continue` so contract-update-only traffic does not falsely keep bar_writer "alive" to the stall watchdog
- Terminal-invalid (malformed) swarm payloads return True (commit) because replaying them forever serves no purpose; ON CONFLICT UPSERT makes re-delivery of valid messages safe

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Created .venv symlink in worktree for pre-commit hook**
- **Found during:** Task 1 commit
- **Issue:** Pre-commit hook resolves ruff/black via `${REPO_ROOT}/.venv/bin/ruff` where REPO_ROOT = worktree path; no .venv exists in worktree
- **Fix:** `ln -s /home/bg/dev/indicagent/.venv /home/bg/dev/indicagent/.claude/worktrees/agent-a9f3bbff8a25c6c3f/.venv`
- **Files modified:** worktree filesystem only (symlink)
- **Verification:** Pre-commit hook passed ruff/black checks on subsequent commits
- **Committed in:** Not committed (filesystem symlink, not tracked by git)

---

**Total deviations:** 1 auto-fixed (1 blocking infrastructure)
**Impact on plan:** Symlink fix unblocked commits. No scope creep.

## Issues Encountered

- `test_flush_batch_leaves_buffer_on_error` in `tests/unit/services/test_bar_writer_agent.py` was already failing on the base commit before any changes (pre-existing regression, confirmed via git stash). Not caused by this plan. Per scope boundary rules, logged here but not fixed.

## Next Phase Readiness

- All three writer correctness bugs resolved; services can now be safely restarted knowing failures are loud and recoverable
- service_auditor stall detection is now enabled for bar_writer
- SwarmLedgerWriterAgent re-delivery is safe on transient DB outages
- Pre-existing test failure in test_bar_writer_agent.py::test_flush_batch_leaves_buffer_on_error should be addressed in a follow-up

---
*Phase: 105-architecture-hotfix-sprint*
*Completed: 2026-05-24*
