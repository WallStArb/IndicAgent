---
phase: "080"
plan: "08"
subsystem: swarm-ledger-writer
tags: [swarm, signal-ledger, writer-agent, retry-backoff, prometheus]
dependency_graph:
  requires: [080-02, 080-07]
  provides: [SwarmLedgerWriterAgent, indicagent-swarm-ledger-writer.service]
  affects: [signal_ledger, _DAG_ORDER]
tech_stack:
  added: []
  patterns: [BaseAgent._setup/_run/_teardown, asyncpg exponential backoff, Prometheus labeled counter]
key_files:
  created:
    - services/swarm_ledger_writer_agent.py
    - services/indicagent-swarm-ledger-writer.service
    - tests/unit/service_tests/test_swarm_ledger_writer_agent.py
  modified:
    - services/service_auditor_agent.py
decisions:
  - Used BaseAgent._setup/_run/_teardown lifecycle (not custom start()) to align with standard agent contract and get OTel/lag reporter for free
  - Retry loop iterates over _RETRY_BACKOFF_S tuple: first iteration uses delay as sleep AFTER UPDATE 0 (not before), so the first attempt fires immediately
  - _handle_event validates signal_id presence before dispatching; swarm_multiplier=0 is valid (falsy int check bypassed via explicit `is None`)
metrics:
  duration: ~15 minutes
  completed_date: "2026-05-07"
  tasks_completed: 3
  files_changed: 4
---

# Phase 80 Plan 08: SwarmLedgerWriterAgent Summary

**One-liner:** Writer agent consuming swarm.alpha topic with 5-attempt exponential backoff to project adjusted_confidence/swarm_multiplier/swarm_agent_count into signal_ledger without touching the original confidence column.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Verify topic_swarm_alpha + DAG registration | 9edeb0cb | services/service_auditor_agent.py |
| 2 | Implement SwarmLedgerWriterAgent + systemd unit | 3e5b3bc4 | services/swarm_ledger_writer_agent.py, services/indicagent-swarm-ledger-writer.service |
| 3 | Unit tests | 9ea00c14 | tests/unit/service_tests/test_swarm_ledger_writer_agent.py |

## What Was Built

`SwarmLedgerWriterAgent` (`services/swarm_ledger_writer_agent.py`) is the writer-owned DB persistence layer for swarm aggregate adjustments per D-07:

- Consumes `swarm.alpha` topic via `KafkaConsumerClient` with consumer group `swarm_ledger_writer_consumer`
- On each event: validates `signal_id`, `swarm_multiplier`, `adjusted_confidence` are present
- Calls `_apply_projection(signal_id, swarm_multiplier, adjusted_confidence, swarm_agent_count)` which issues:
  ```sql
  UPDATE signal_ledger
     SET adjusted_confidence = $2, swarm_multiplier = $3, swarm_agent_count = $4
   WHERE signal_id = $1
  ```
- Bounded retry with backoff tuple `(0.1, 0.25, 0.5, 1.0, 2.0)` seconds (5 attempts) — handles race condition where swarm event arrives before signal_writer INSERT
- Emits `SWARM_SIGNAL_LEDGER_UPDATE_TOTAL{status=success|retry|miss}` per outcome
- The original `signal_ledger.confidence` column is never in the UPDATE statement

DAG registration in `service_auditor_agent.py`:
- `_DAG_ORDER["indicagent-swarm-ledger-writer"] = 7` (L7 alongside llm-writer)
- `_LAG_THRESHOLDS["indicagent-swarm-ledger-writer"] = 500`
- `_AGENT_ID_TO_UNIT["swarm_ledger_writer"] = "indicagent-swarm-ledger-writer"`

`topic_swarm_alpha` was NOT modified — pre-existing in `src/core/stream_keys.py` from Phase 73, imported as-is.

## Verification

```
.venv/bin/pytest tests/unit/service_tests/test_swarm_ledger_writer_agent.py -v  → 5 passed
.venv/bin/ruff check services/swarm_ledger_writer_agent.py ...                  → All checks passed
git diff --quiet src/core/stream_keys.py                                         → no changes
```

## Deviations from Plan

### Auto-fixed Issues

None - plan executed as written.

**Design note:** The plan skeleton used a custom `start()` method overriding BaseAgent's lifecycle. I used the standard `_setup()/_run()/_teardown()` pattern instead — this is semantically equivalent but aligns with the agent contract (gets OTel/lag reporting for free) and matches how all other writer agents are implemented. No behavioral deviation.

## Self-Check: PASSED

- services/swarm_ledger_writer_agent.py: FOUND
- services/indicagent-swarm-ledger-writer.service: FOUND
- tests/unit/service_tests/test_swarm_ledger_writer_agent.py: FOUND
- Commit 9edeb0cb: FOUND
- Commit 3e5b3bc4: FOUND
- Commit 9ea00c14: FOUND
