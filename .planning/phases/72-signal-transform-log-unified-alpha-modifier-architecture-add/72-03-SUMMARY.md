---
phase: 72-signal-transform-log-unified-alpha-modifier-architecture-add
plan: "03"
subsystem: streaming
tags: [kafka, stream-keys, topics, graduation-pipeline]
dependency_graph:
  requires: []
  provides: [topic_transform_graduation, topic_transform_graduation_dlq]
  affects: [GraduationComputeAgent, GraduationWriterAgent]
tech_stack:
  added: []
  patterns: [env_prefix topic builder, DLQ per domain]
key_files:
  created: []
  modified:
    - src/core/stream_keys.py
    - production/scripts/kafka_init_topics.py
    - tests/unit/test_stream_keys.py
decisions:
  - "Placed topic_transform_graduation after topic_lifecycle_transitions (lifecycle/graduation proximity)"
  - "Placed topic_transform_graduation_dlq after topic_llm_writer_dlq (DLQ section)"
  - "Used _BUFFER_MS (1-day) retention — results persisted to DB, Kafka is transport only"
metrics:
  duration: "~5 minutes"
  completed: "2026-04-25"
  tasks_completed: 3
  tasks_total: 3
  files_modified: 3
---

# Phase 72 Plan 03: Kafka Topic Registration for Transform Graduation Pipeline Summary

Two Kafka topic builder functions added to stream_keys.py and registered in kafka_init_topics.py with 1-day buffer retention, plus unit tests confirming correct env-prefix behavior.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add topic_transform_graduation + DLQ to stream_keys.py | 6cf24dab | src/core/stream_keys.py |
| 2 | Register topics in kafka_init_topics.py | f38cad8c | production/scripts/kafka_init_topics.py |
| 3 | Add unit tests for new topic functions | 8aa79b09 | tests/unit/test_stream_keys.py |

## What Was Built

- `topic_transform_graduation(env_name)` — returns `{env}.intelligence.transform.graduation`; published by GraduationComputeAgent, consumed by GraduationWriterAgent
- `topic_transform_graduation_dlq(env_name)` — returns `{env}.intelligence.transform.graduation.dlq`; DLQ for GraduationWriterAgent unparseable payloads
- Both topics registered in `kafka_init_topics.py` with `_BUFFER_MS` (1-day) retention and `delete` cleanup policy
- 4 unit tests covering with-env and no-env variants for both functions; all passing

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None.

## Threat Flags

None — topic builder functions introduce no new network endpoints, auth paths, or DB schema changes.

## Self-Check: PASSED

- [x] `def topic_transform_graduation` present in src/core/stream_keys.py (line 288)
- [x] `def topic_transform_graduation_dlq` present in src/core/stream_keys.py (line 441)
- [x] 2 entries matching `intelligence.transform.graduation` in kafka_init_topics.py
- [x] Commit 6cf24dab exists
- [x] Commit f38cad8c exists
- [x] Commit 8aa79b09 exists
- [x] 4 pytest tests passing (`-k transform_graduation`)
