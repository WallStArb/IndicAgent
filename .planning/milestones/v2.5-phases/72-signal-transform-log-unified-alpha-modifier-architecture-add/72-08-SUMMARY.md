---
phase: 72-signal-transform-log-unified-alpha-modifier-architecture-add
plan: "08"
subsystem: graduation-writer
tags: [writer-agent, kafka, persistence, transform-graduation, phase-72]
dependency_graph:
  requires: [72-01, 72-03]
  provides: [graduation-writer-agent, transform-graduation-repository]
  affects: [transform_graduation table]
tech_stack:
  added: []
  patterns: [BaseWriterAgent, asyncpg-batch-upsert, ON-CONFLICT-DO-UPDATE]
key_files:
  created:
    - src/persistence/repository/transform_graduation_repository.py
    - services/graduation_writer_agent.py
    - services/indicagent-graduation-writer.service
    - tests/unit/test_graduation_writer_agent.py
  modified: []
decisions:
  - "Mirrored lifecycle_writer_agent.py structure exactly — same teardown, buffer, DLQ, and setup patterns"
  - "BATCH_SIZE=50 (half of lifecycle writer) — graduation events are low-frequency relative to lifecycle transitions"
  - "No watchdog in systemd unit per CLAUDE.md systemd discipline (no sd_notify in agent)"
metrics:
  duration: ~10m
  completed: "2026-04-25T15:16:05Z"
  tasks_completed: 3
  files_created: 4
---

# Phase 72 Plan 08: GraduationWriterAgent Summary

Always-on Kafka-to-DB writer that consumes `intelligence.transform.graduation` and upserts graduation evaluation results into the `transform_graduation` table using `ON CONFLICT (transform_id, transform_version, segment_key) DO UPDATE`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | TransformGraduationRepository | 6b90afbb | src/persistence/repository/transform_graduation_repository.py |
| 2 | GraduationWriterAgent service | 2e500e9d | services/graduation_writer_agent.py |
| 3 | Systemd unit + unit tests | 46a9adb7 | services/indicagent-graduation-writer.service, tests/unit/test_graduation_writer_agent.py |

## What Was Built

**TransformGraduationRepository** (`src/persistence/repository/transform_graduation_repository.py`): Thin UPSERT helper. `batch_upsert(rows)` converts ISO-8601 `evaluated_at`/`expires_at` strings to `datetime` objects (asyncpg timestamptz batch insert requirement per CLAUDE.md), then calls `execute_batch()` — the canonical `DatabaseManager` batch path.

**GraduationWriterAgent** (`services/graduation_writer_agent.py`): `BaseWriterAgent` subclass. Consumes `topic_transform_graduation`, validates 7 required payload keys, buffers rows, flushes in batches of 50 every 5 seconds or on size threshold. Unparseable payloads routed to `topic_transform_graduation_dlq`. Three counters (`events_consumed`, `rows_written`, `write_errors`) + `PERSISTENCE_BATCH_LATENCY` labeled with `agent_id="graduation_writer_agent"`. Metrics port 9136.

**Systemd unit** (`services/indicagent-graduation-writer.service`): `PYTHONUNBUFFERED=1`, no `WatchdogSec`/`NotifyAccess`, `Restart=always`.

**Unit tests** (`tests/unit/test_graduation_writer_agent.py`): 11 tests covering `_parse_payload` (valid, missing key, non-dict, empty, partial), `_flush_batch` (upsert call, row count, error counter, latency observation). All pass without DB or Kafka.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None.

## Threat Flags

None. This is a pure persistence writer with no new network endpoints or auth paths.

## Self-Check: PASSED

- `src/persistence/repository/transform_graduation_repository.py` — exists, imports cleanly
- `services/graduation_writer_agent.py` — exists, imports cleanly, ruff+black clean
- `services/indicagent-graduation-writer.service` — exists, PYTHONUNBUFFERED=1 present, no watchdog
- `tests/unit/test_graduation_writer_agent.py` — 11/11 tests pass
- Commits: 6b90afbb, 2e500e9d, 46a9adb7 — all present in git log
