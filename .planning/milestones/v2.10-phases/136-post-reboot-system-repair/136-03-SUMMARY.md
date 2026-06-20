---
phase: 136-post-reboot-system-repair
plan: "03"
subsystem: intelligence_pipeline
tags: [sigterm, graceful-shutdown, kafka, asyncio, systemd]
dependency_graph:
  requires: []
  provides: [graceful-sigterm-shutdown-for-intelligence-pipeline]
  affects: [services/intelligence_pipeline.py, production/systemd/indicagent-intelligence-pipeline.service]
tech_stack:
  added: []
  patterns: [asyncio-signal-handler-override, consumer-stop-unblocks-async-for]
key_files:
  created: []
  modified:
    - services/intelligence_pipeline.py
    - production/systemd/indicagent-intelligence-pipeline.service
decisions:
  - Override _register_signal_handlers() (not _stop() which does not exist on BaseDaemon) to schedule an async shutdown task via loop.create_task(); the task sets _stop_event AND awaits self._kafka_consumer.stop() to unblock the idle async-for
metrics:
  duration_minutes: 8
  tasks_completed: 3
  files_modified: 2
  completed_date: "2026-06-18"
---

# Phase 136 Plan 03: Intelligence Pipeline Graceful Shutdown Summary

**One-liner:** Added async consumer-stop signal handler override plus inner running-check so SIGTERM unblocks the idle Kafka async-for and the pipeline stops cleanly without SIGKILL.

## What Was Built

Three changes (W3a, W3b, W3c) to eliminate the SIGKILL-on-every-restart problem for `indicagent-intelligence-pipeline`:

**Root cause:** `_process_loop` blocks indefinitely inside `async for ... in self._kafka_consumer.messages()` when Kafka is idle. The base `BaseDaemon._register_signal_handlers()` sets `_stop_event` synchronously, but the loop body never executes so the flag is never checked.

**3a - Inner stop-check (belt-and-suspenders):**
Added `if not self.running: break` immediately after `self._record_message_consumed()` inside `_process_loop`. This ensures that if a stop signal arrives while a message is being delivered, the loop exits after processing the current message rather than starting the next one.

**3b - Signal handler override (the actual fix):**
Overrode `_register_signal_handlers()` in `IntelligencePipeline`. The new handler registers a synchronous callback that schedules `_shutdown_consumer()` via `loop.create_task()`. `_shutdown_consumer()` is an async coroutine that: (1) sets `_stop_event`, (2) calls `await self._kafka_consumer.stop()` guarded by `hasattr`. Stopping the consumer closes the async generator, raising `StopAsyncIteration` in `_process_loop`, which immediately unblocks the idle loop. `_teardown()` already calls `await self._kafka_consumer.stop()` with a `hasattr` guard, so the second call is safe (idempotent).

**3c - systemd backstop:**
Added `TimeoutStopSec=90` to `[Service]` in `indicagent-intelligence-pipeline.service`. Documents the hard budget: output queue drain (10s) + worker_manager stop + checkpoint write + kafka stop + db close.

## Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1+2 | 3a inner stop-check + 3b signal handler override | 26536c11 | services/intelligence_pipeline.py |
| 3 | 3c TimeoutStopSec=90 in systemd unit | a2143190 | production/systemd/indicagent-intelligence-pipeline.service |

## Verification

- `grep -n "if not self.running" services/intelligence_pipeline.py` - line 675 confirmed
- `grep -n "_register_signal_handlers\|_kafka_consumer.stop" services/intelligence_pipeline.py` - both present at lines 642, 657, 635
- `ruff check services/intelligence_pipeline.py` - clean (All checks passed)
- `python3 -c "import ast; ast.parse(open('services/intelligence_pipeline.py').read())"` - exits 0
- `grep -n "TimeoutStopSec=90" production/systemd/indicagent-intelligence-pipeline.service` - line 23 confirmed
- Operational verification (post-deploy): `systemctl stop indicagent-intelligence-pipeline` should complete in <5s with no SIGKILL in journalctl when Kafka is idle

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] BaseDaemon has no `_stop()` method**
- **Found during:** Task 2 - inspecting the base class
- **Issue:** The design doc referenced overriding `BaseDaemon._stop()`, but `BaseDaemon` has no such method. It has `stop()` (called AFTER `_teardown()`, too late) and `_register_signal_handlers()` (synchronous, called at startup).
- **Fix:** Overrode `_register_signal_handlers()` instead. This is the correct hook: it controls what happens when SIGTERM fires, before `_process_loop` is awaited. The override schedules an async task via `loop.create_task()` so the coroutine can call `await self._kafka_consumer.stop()`.
- **Files modified:** services/intelligence_pipeline.py
- **Commit:** 26536c11

## Self-Check

- [x] `services/intelligence_pipeline.py` modified - exists and contains all three changes
- [x] `production/systemd/indicagent-intelligence-pipeline.service` modified - contains `TimeoutStopSec=90`
- [x] Commits 26536c11 and a2143190 exist in git log
- [x] ruff clean, AST parses
