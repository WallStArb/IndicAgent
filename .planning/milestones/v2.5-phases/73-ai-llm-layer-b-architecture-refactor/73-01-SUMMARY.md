---
phase: 73-ai-llm-layer-b-architecture-refactor
plan: 01
subsystem: swarm-infrastructure
tags: [kafka-topics, service-deletion, systemd, swarm-alpha, signal-lineage]

dependency_graph:
  requires: [D-08, D-09, D-16, D-49]
  provides: [topic_swarm_alpha, topic_swarm_graduation, topic_signal_lineage, topic_signal_lineage_dlq]
  affects: [alpha-swarm-agent, lineage-recorder, lineage-writer]

tech_stack:
  added: []
  patterns:
    - Unified swarm.alpha topic (replaces path_a/path_b split)
    - Kafka-first signal lineage DAG (transform → agent_prediction → lifecycle)

key_files:
  created: []
  modified:
    - path: src/core/stream_keys.py
      lines_added: 28
      lines_removed: 0
      purpose: Add 4 new Kafka topic functions for unified swarm + lineage infrastructure
    - path: production/scripts/kafka_init_topics.py
      lines_added: 4
      lines_removed: 0
      purpose: Register new topics with _BUFFER_MS (1-day) retention policy
  deleted:
    - path: services/swarm_orchestrator_agent.py
      lines_removed: 240
      reason: Dead orchestrator with zero contributors running with PID 281147 doing nothing
    - path: tests/unit/service_tests/test_swarm_orchestrator_agent.py
      reason: Test file for deleted service
    - path: tests/unit/service_tests/test_swarm_orchestrator_seeding.py
      reason: Test file for deleted service

decisions:
  - description: Delete swarm_orchestrator_agent immediately without waiting for alpha_swarm_agent implementation
    rationale: Service runs with PID 281147 but has zero contributors registered — no code path depends on it. Removing it clears the way for the renamed alpha_swarm_agent in Plan 05 without conflicts.
    impact: systemd unit stopped/disabled/removed, topic functions added, no runtime impact (service was idle)
  - description: Use unified swarm.alpha topic instead of path_a/path_b split
    rationale: Plan 05 AlphaSwarmComputeAgent runs both deterministic and LLM contributors via asyncio.gather() — single topic simplifies consumer contract.
    impact: SwarmWriterAgent subscribes to one topic instead of two; topic_swarm_alpha_path_a/topic_swarm_alpha_path_b retained for backward compatibility during transition
  - description: Add signal lineage topics (intelligence.signal_lineage + DLQ) in infrastructure plan before implementation
    rationale: Topic registration is prerequisite for LineageRecorder/LineageWriterAgent in Plan 04. Adding topics here prevents circular dependency on kafka_init_topics execution order.
    impact: Kafka topics created on next pipeline reset; lineage agents can publish immediately after Plan 04 implementation

metrics:
  duration_seconds: 180
  started_at: "2026-04-28T23:57:49Z"
  completed_at: "2026-04-29T00:00:49Z"
  tasks_completed: 1
  files_modified: 5
  test_results: 2765 passed, 1 failed (pre-existing msgpack→JSON migration in intelligence_pipeline_agent.py — out of scope per deviation boundary rule)
  commits:
    - hash: 8dbdc3cf
      message: feat(73-01): delete dead swarm orchestrator + add 4 Kafka topic functions
      files: [services/swarm_orchestrator_agent.py, tests/unit/service_tests/test_swarm_orchestrator_agent.py, tests/unit/service_tests/test_swarm_orchestrator_seeding.py, src/core/stream_keys.py, production/scripts/kafka_init_topics.py]
---

# Phase 73 Plan 01: Delete Dead Swarm Orchestrator + Add Kafka Topic Infrastructure

**One-liner:** Deleted idle swarm_orchestrator service (PID 281147, zero contributors) and added 4 Kafka topic functions for unified swarm aggregation and signal lineage infrastructure.

## Summary

Plan 73-01 removed the dead `swarm_orchestrator_agent` service that was running in production with PID 281147 but had zero contributors registered, violating CLAUDE.md watchdog discipline (WatchdogSec without sd_notify). The plan also added 4 new Kafka topic functions to `stream_keys.py` required by subsequent plans:
- `topic_swarm_alpha()` — unified aggregate from all alpha agents (replaces path_a/path_b split)
- `topic_swarm_graduation()` — per-agent graduation flip events from BaseGroupService
- `topic_signal_lineage()` — unified signal lineage events (transform, agent_prediction, lifecycle)
- `topic_signal_lineage_dlq()` — DLQ for lineage persistence failures

All 4 topics were registered in `production/scripts/kafka_init_topics.py` with `_BUFFER_MS` (1-day) retention policy, appropriate for data that is persisted to TimescaleDB by downstream writer agents.

## Deviations from Plan

### Auto-fixed Issues

**None — plan executed exactly as written.**

All tasks completed as specified:
1. ✓ Stopped/disabled/removed systemd unit `indicagent-swarm-orchestrator.service`
2. ✓ Deleted `services/swarm_orchestrator_agent.py` (240 lines)
3. ✓ Deleted 2 test files (`test_swarm_orchestrator_agent.py`, `test_swarm_orchestrator_seeding.py`)
4. ✓ Added 4 topic functions to `src/core/stream_keys.py`
5. ✓ Registered 4 topics in `production/scripts/kafka_init_topics.py`
6. ✓ Verification passed (service file deleted, test files deleted, topic functions importable and produce correct strings)

### Pre-existing Issues (Out of Scope)

Per deviation Rule 5 (scope boundary), the following pre-existing issues were NOT fixed:

- **Test failure in `test_intelligence_pipeline_agent.py::TestStateRestore::test_state_restore_populates_fields`** — This test fails due to a pre-existing change in `services/intelligence_pipeline_agent.py` that migrated from msgpack to JSON-tagged dict state serialization (lines 7-8, 52-53 in the diff). This change was present in the working directory before plan execution and is unrelated to swarm_orchestrator deletion or topic function additions. The test passes when run against the baseline commit (8ee04d84) without plan changes.

## Threat Surface

| Flag | File | Description |
|------|------|-------------|
| N/A | — | No new security-relevant surface introduced. Plan only deleted dead code and added topic string builders (no network endpoints, auth paths, or schema changes). |

## Verification

**Automated verification (all passed):**
- ✓ `services/swarm_orchestrator_agent.py` deleted from filesystem
- ✓ `tests/unit/service_tests/test_swarm_orchestrator_agent.py` deleted
- ✓ `tests/unit/service_tests/test_swarm_orchestrator_seeding.py` deleted
- ✓ All 4 topic functions importable from `src.core.stream_keys`
- ✓ Topic functions produce correct strings:
  - `topic_swarm_alpha("development")` → `"development.swarm.alpha"`
  - `topic_swarm_graduation("development")` → `"development.swarm.graduation"`
  - `topic_signal_lineage("development")` → `"development.intelligence.signal_lineage"`
  - `topic_signal_lineage_dlq("development")` → `"development.intelligence.signal_lineage.dlq"`
- ✓ `production/scripts/kafka_init_topics.py` contains 4 references to new topics
- ✓ systemd unit verification: `Unit indicagent-swarm-orchestrator.service could not be found`

**Unit tests:** 2765 passed, 1 failed (pre-existing msgpack→JSON migration — out of scope)

## Key Implementation Notes

### systemd Unit Removal
The plan followed the Gemini review recommendation about "Double-Start Risk" by executing `daemon-reload` and `reset-failed` after unit deletion. This ensures the service manager has a clean slate before Plan 05 installs the new `alpha-swarm` unit, preventing any cached state from interfering with the new service.

### Topic Function Placement
The 4 new topic functions were inserted in `src/core/stream_keys.py` after the existing swarm section (after `topic_swarm_writer_dlq` at line 344) and before the ML topics section. This maintains topic grouping by domain (swarm topics together, followed by ML topics).

### Topic Registration Pattern
All 4 new topics use `_BUFFER_MS` (1-day) retention, consistent with other topics that are consumed by writer agents and persisted to TimescaleDB. The data is redundant in Kafka once persisted — retention is sized for restart catch-up only.

### Test File Cleanup
Two test files were deleted alongside the service:
- `test_swarm_orchestrator_agent.py` — unit tests for SwarmOrchestratorComputeAgent
- `test_swarm_orchestrator_seeding.py` — tests for `_seed_context_cache()` DB warmup logic

Both files imported from the deleted service and would cause collection errors if retained.

## Self-Check: PASSED

- [x] All modified files exist in commit
- [x] Commit hash exists: `8dbdc3cf`
- [x] No unintended file deletions (only 3 files deleted as planned)
- [x] No stub patterns in new code
- [x] All verification criteria met
- [x] Pre-existing test failure documented as out of scope
