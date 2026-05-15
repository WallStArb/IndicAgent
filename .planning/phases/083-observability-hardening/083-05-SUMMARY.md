---
phase: 083-observability-hardening
plan: "05"
subsystem: observability
tags: [dlq, kafka, timescaledb, dead-code-cleanup, servicedag]
dependency_graph:
  requires: ["083-04"]
  provides: ["dlq_events hypertable", "dlq_drain_agent L9 service", "7-day DLQ retention"]
  affects: ["services/service_auditor_agent.py", "src/core/stream_keys.py", "services/shadow_auditor_agent.py"]
tech_stack:
  added: ["dlq_events TimescaleDB hypertable with 30d retention"]
  patterns: ["asyncpg upsert ON CONFLICT DO NOTHING for idempotent DLQ drain"]
key_files:
  created:
    - production/migrations/088_dlq_events.sql
    - services/dlq_drain_agent.py
    - production/systemd/indicagent-dlq-drain.service
    - production/scripts/ensure_topics.sh
  modified:
    - services/service_auditor_agent.py
    - src/core/stream_keys.py
    - services/shadow_auditor_agent.py
decisions:
  - "DLQ upsert key is (agent, source_topic, routed_at) — not message-id — because DLQPayload.timestamp is the routed_at value and provides natural dedup within an agent+topic pair"
  - "producer removed from shadow_auditor_agent entirely (not just the publish call) since no other Kafka publish calls remain in the file"
  - "ensure_topics.sh uses both rpk topic create + alter-config so new and existing topics both get the retention applied"
metrics:
  duration_minutes: 8
  completed_date: "2026-05-15"
  tasks_completed: 4
  tasks_total: 4
  files_created: 4
  files_modified: 3
---

# Phase 083 Plan 05: DLQ History Substrate Summary

DLQ messages become queryable history via a new `dlq_events` hypertable; dead topics and dead code removed.

## What Was Built

### Task 1 - dlq_events migration (commit 076decdc)
Created `production/migrations/088_dlq_events.sql` and applied to indicagent DB:
- `dlq_events` table with 9 columns: id (BIGSERIAL), routed_at (TIMESTAMPTZ), agent, source_topic, dlq_topic, error_type, error_message, payload (JSONB), retry_count
- Hypertable on `routed_at` with `if_not_exists` guard
- 30-day retention policy
- UNIQUE INDEX `dlq_events_dedup_idx` on (agent, source_topic, routed_at) for ON CONFLICT upsert

### Task 2 - dlq_drain_agent + systemd unit (commit 439a3920)
Created `services/dlq_drain_agent.py` (192 lines):
- `DLQDrainAgent(BaseAgent)` with `agent_id = "dlq_drain_agent"`
- Subscribes to all 15 active DLQ topics via `dlq_drain_consumer` consumer group
- Parses each message as `DLQPayload`, upserts to `dlq_events` via asyncpg
- ON CONFLICT (agent, source_topic, routed_at) DO NOTHING for idempotency
- Handles parse failures gracefully: log warning + continue, no crash
- Emits structured log per event: `dlq_drained` with agent/source_topic/dlq_topic/error_type fields

Created `production/systemd/indicagent-dlq-drain.service` and installed via `systemctl daemon-reload`.

### Task 3 - service_auditor registration (commit 81ef1e8f)
In `services/service_auditor_agent.py`:
- Added `"indicagent-dlq-drain": 9` to `_DAG_ORDER` at L9
- Added `"indicagent-dlq-drain": 500` to `_LAG_THRESHOLDS`
- Added `"dlq_drain_agent": "indicagent-dlq-drain"` to `_AGENT_ID_TO_UNIT`

### Task 4 - ensure_topics.sh + dead topic/code removal (commit aff1f684)
**ensure_topics.sh:** Idempotent script provisions 15 DLQ topics with `retention.ms=604800000` (7 days). Verified: `bar.aggregator.dlq` shows `retention.ms 604800000 DYNAMIC_TOPIC_CONFIG`.

**6 orphaned Redpanda topics deleted** (confirmed empty before deletion):
- `intelligence.shadow.transitions`, `intelligence.signal.audit`, `market.data.quality`
- `ml.data_quality.alerts`, `pipeline.data_quality`, `system.health.events`

**src/core/stream_keys.py dead function removal:**
- Deleted `topic_bar_audit_dlq` (zero callers)
- Deleted `topic_signal_audit_dlq` (zero callers)
- Deleted `topic_cross_asset_dlq` (zero callers)
- Deleted `topic_shadow_transitions` (only caller was shadow_auditor_agent)

**services/shadow_auditor_agent.py cleanup:**
- Removed `topic_shadow_transitions` import and `ShadowTransitionEvent` import
- Removed `KafkaProducerClient` import and `_publish()` function
- Removed `ShadowTransitionEvent` construction + `_publish()` calls from `_check_promotion` and `_check_demotion`
- Removed `producer` parameter from `_run_audit`, `_check_promotion`, `_check_demotion` signatures
- Removed producer lifecycle from `_amain()`
- DB writes (`shadow_transition_log INSERT`) preserved intact - only the Kafka publish is removed

## Verification

- `dlq_events` table: 9 columns confirmed via `\d dlq_events`, hypertable row in `_timescaledb_catalog.hypertable`
- `dlq_events_dedup_idx` unique index confirmed
- `grep -cE "topic_[a-z_]+_dlq" services/dlq_drain_agent.py` = 30 (15 imports + 15 return calls)
- `grep "INSERT INTO dlq_events"` matches; `grep "ON CONFLICT (agent, source_topic, routed_at)"` matches
- Agent imports successfully under Python
- `ruff check` clean on all modified files
- `pytest tests/unit/ -q`: 3248 passed, 1 skipped
- `SELECT COUNT(*) FROM dlq_events` = 0 (table ready, empty)
- `rpk topic list | grep -E "shadow|signal.audit|data.quality|system.health"` = empty
- `rpk topic describe bar.aggregator.dlq | grep retention.ms` = `604800000 DYNAMIC_TOPIC_CONFIG`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing cleanup] producer fully removed from shadow_auditor_agent**
- **Found during:** Task 4
- **Issue:** After removing `_publish()` calls, `KafkaProducerClient`, `json`, `dataclasses` imports, and `producer` parameter became dead code. Ruff would flag as unused imports.
- **Fix:** Removed producer parameter from all three function signatures (`_run_audit`, `_check_promotion`, `_check_demotion`) and from `_amain()` producer lifecycle. DB writes preserved.
- **Files modified:** `services/shadow_auditor_agent.py`
- **Commit:** aff1f684

**2. [Rule 3 - Blocking] .venv symlink for pre-commit hook**
- **Found during:** Task 2 commit
- **Issue:** Pre-commit hook resolves `REPO_ROOT` to the worktree path (not main repo) via `git rev-parse --show-toplevel`. Hook looks for `.venv/bin/ruff` under worktree - not found.
- **Fix:** Created symlink `.claude/worktrees/agent-a9e8ad66d4b861309/.venv -> /home/bg/dev/indicagent/.venv`
- **Files modified:** worktree .venv symlink (not committed - infrastructure only)

## Self-Check

Verifying key artifacts exist and commits are present.
