---
phase: 105-architecture-hotfix-sprint
plan: 01
subsystem: persistence
tags: [kafka, otel, asyncpg, ctx-writer, llm-writer, base-writer, hotfix]

# Dependency graph
requires: []
provides:
  - CtxWriterAgent flush loop no longer raises AttributeError on .inc() calls; ctx buffers drain correctly
  - CtxWriterAgent._teardown() chains super()._teardown() so generic buffer and lifecycle both flush on shutdown
  - LLMWriterService parse-update back-fills now use db_manager.execute_command (self._pool never existed)
  - LLMWriterService stall watchdog reads correct _last_message_ts attribute set by _record_message_consumed
  - LLMWriterService _process_loop() calls _record_message_consumed() per message so watchdog can fire
  - LLMWriterService dead intelligence.i8 and llm.outcomes subscriptions removed with TODO(HF-10) comment
  - LLMWriterService offset reset changed from latest to earliest; enable_auto_commit=False hands control to base _do_flush
affects: [llm-writer, ctx-writer, signal-writer, persistence-layer]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "OTel counters use .add(n) not .inc(n) — the OTel Python SDK does not expose .inc()"
    - "BaseWriterAgent subclasses with custom buffers must call await super()._teardown() first in _teardown() then flush their own buffers"
    - "self._pool never exists in BaseWriterAgent subclasses — use self.db_manager.execute_command() for one-off DB writes"
    - "BaseAgent._last_message_ts is set by _record_message_consumed(); watchdog must read this, not _last_msg_ts"
    - "enable_auto_commit=False + BaseWriterAgent._do_flush() post-write commit = no llm_calls loss on crash"

key-files:
  created: []
  modified:
    - services/ctx_writer_agent.py
    - services/llm_writer_service.py

key-decisions:
  - "BaseWriterAgent._teardown() drains self._buffer only; ctx-specific _event_buffer/_snapshot_buffer require the custom flush guard in CtxWriterAgent._teardown() — kept intact"
  - "LLMWriterService dead i8/outcomes subscriptions removed (no publishers as of 2026-05-23); _flush_i8() and _i8_buffer kept dead-but-harmless for future re-wire"
  - "auto_offset_reset=earliest safe because llm_calls upsert uses ON CONFLICT (call_id, called_at) DO NOTHING"

patterns-established:
  - "OTel counter pattern: counter().add(n) not .inc(n)"
  - "Teardown chain: super()._teardown() first, then subclass-specific buffer drains"
  - "DB writes in writer services: self.db_manager.execute_command(), never self._pool"

requirements-completed: []

# Metrics
duration: 8min
completed: 2026-05-24
---

# Phase 105 Plan 01: Writer Service Bug Hotfix Summary

**Six silent-failure bugs fixed across CtxWriterAgent and LLMWriterService: AttributeError flush crashes, dead watchdog, self._pool phantom reference, dead topic subscriptions, and pre-write offset commit risk**

## Performance

- **Duration:** 8 min
- **Started:** 2026-05-24T07:41:00Z
- **Completed:** 2026-05-24T07:44:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- CtxWriterAgent flush loop no longer crashes with AttributeError; ctx_events and ctx_snapshots buffers drain correctly on every flush cycle
- CtxWriterAgent teardown now chains super()._teardown() ensuring both the generic buffer and the ctx-specific buffers are drained on shutdown
- LLMWriterService parse-update path now uses self.db_manager.execute_command() — self._pool was undefined, causing every parse_success back-fill to silently drop via swallowed AttributeError
- LLMWriterService stall watchdog now reads self._last_message_ts (BaseAgent attribute) and _process_loop() calls _record_message_consumed() per message so the watchdog can actually fire
- LLMWriterService dead intelligence.i8 and llm.outcomes subscriptions removed with TODO(HF-10) comment; auto_offset_reset changed to earliest; enable_auto_commit=False added so base _do_flush() post-write commit owns offset advancement

## Task Commits

Each task was committed atomically:

1. **Task 1: CtxWriterAgent .inc() AttributeErrors and missing super()._teardown()** - `e1e7fbe9` (fix)
2. **Task 2: LLMWriterService pool ref, .inc(), stall watchdog, dead topics, offset, commit** - `5d6d637c` (fix)

## Files Created/Modified
- `services/ctx_writer_agent.py` - Fixed .inc() to .add() on two OTel counters; added await super()._teardown() as first statement in _teardown()
- `services/llm_writer_service.py` - Six fixes: self._pool -> db_manager.execute_command; .inc() -> .add(); _last_msg_ts -> _last_message_ts; added _record_message_consumed() in _process_loop; removed dead i8/outcomes subscriptions with TODO; auto_offset_reset=earliest; enable_auto_commit=False

## Decisions Made
- BaseWriterAgent._teardown() only drains self._buffer (the generic buffer). The ctx-specific _event_buffer and _snapshot_buffer are NOT drained by the base class. The custom flush guard in CtxWriterAgent._teardown() is the sole drain path for those buffers and was preserved intact.
- Dead _flush_i8() and _i8_buffer in LLMWriterService are kept dead-but-harmless rather than deleted — easy to re-wire when narrative_compute publishes i8 updates in v2.8.
- auto_offset_reset=earliest is safe because the llm_calls upsert uses ON CONFLICT (call_id, called_at) DO NOTHING, making replays idempotent.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Worktree lacked .venv symlink so pre-commit hook could not find ruff/black. Resolved by symlinking /home/bg/dev/indicagent/.venv into the worktree root. Both files were already ruff/black clean before the symlink.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Both writer services now have trustworthy persistence paths; v2.8 AI platform work sits on a correct persistence layer
- ctx_writer and llm_writer can be restarted with confidence that buffers drain and offsets advance only after successful DB writes

---
*Phase: 105-architecture-hotfix-sprint*
*Completed: 2026-05-24*
