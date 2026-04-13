---
phase: 68-pipeline-hardening-institutional-foundation
plan: 03
subsystem: pipeline-traceability
tags: [bar_id, uuid, traceability, migration, signal_ledger, schema]
dependency_graph:
  requires: [68-01, 68-02]
  provides: [bar_id-trace, migration-063, clean-signal-ledger]
  affects: [signal_ledger, intelligence_features, BarMessage, IntelligenceEvent]
tech_stack:
  added: [uuid4-default-factory, bar_id-trace-column]
  patterns: [end-to-end-bar-traceability, idempotent-migration]
key_files:
  created:
    - production/migrations/063_pipeline_hardening.sql
    - tests/unit/test_bar_message.py
  modified:
    - src/core/schemas/bar_message.py
    - src/intelligence/schemas.py
    - services/intelligence_pipeline_agent.py
decisions:
  - bar_id uses UUID default_factory=uuid4 so no provider-level stamping needed
  - IntelligenceEvent.bar_id is UUID | None for backward compat during transition
  - bar_id on signal dicts is str(bar.bar_id) for JSON serialization safety
  - HTF bars get new bar_ids from default_factory (correct - they are distinct bars)
  - Migration TRUNCATE before ADD CONSTRAINT avoids duplicate violation on constraint creation
metrics:
  duration: 664s
  completed: 2026-04-13
  tasks_completed: 2
  files_modified: 4
  files_created: 2
  tests_added: 9
---

# Phase 68 Plan 03: End-to-End bar_id UUID Trace & Migration 063 Summary

End-to-end bar_id UUID trace from BarMessage construction through IntelligenceEvent to signal dicts, plus migration 063 adding 7 columns, unique constraint, 2 indexes, and TRUNCATE signal_ledger for clean slate.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add bar_id to BarMessage, IntelligenceEvent, and carry through pipeline | 23806a63 | src/core/schemas/bar_message.py, src/intelligence/schemas.py, services/intelligence_pipeline_agent.py, tests/unit/test_bar_message.py |
| 2 | Create migration 063_pipeline_hardening.sql | 2bdfa13f | production/migrations/063_pipeline_hardening.sql |

## Key Changes

### Task 1: bar_id UUID Trace

- **BarMessage.bar_id**: `UUID = Field(default_factory=uuid4)` -- auto-generated on construction, no provider changes needed
- **IntelligenceEvent.bar_id**: `UUID | None = None` -- carried from bar.bar_id during pipeline construction
- **Signal dict annotation**: `sig["bar_id"] = str(bar.bar_id)` -- stringified for JSON serialization in Kafka payloads
- **9 TDD tests**: 6 BarMessage tests (auto-gen, type, uniqueness, model_dump, JSON, explicit), 3 IntelligenceEvent tests (accept, default None, explicit None)

### Task 2: Migration 063

- 7 ALTER TABLE statements: bar_id (x2 tables), pre_regime_confidence, pre_tod_confidence, hmm_regime_label, n_agreeing_signals, n_opposing_signals
- TRUNCATE TABLE signal_ledger (clean slate -- all historical signals had broken regime_type)
- Unique constraint uq_signal_ledger_identity on (symbol, feature_ts, feature_tf, setup_plugin)
- 2 indexes for bar_id lookups (signal_ledger, intelligence_features)
- Wrapped in BEGIN/COMMIT; idempotent (IF NOT EXISTS on all ALTER/CREATE)

## Decisions Made

1. **default_factory over explicit stamping**: BarMessage.bar_id auto-generates via uuid4 default_factory. No changes needed in BaseProviderAgent._publish_bar() -- the UUID is created at construction time and serialized automatically by Pydantic's model_dump().
2. **UUID | None on IntelligenceEvent**: Backward compatible during transition -- pre-68-03 events in Kafka will deserialize with bar_id=None.
3. **str(bar.bar_id) on signal dicts**: Signal dicts are serialized to JSON for Kafka. Using str() ensures safe serialization without Pydantic model wrapping.
4. **HTF bars get new bar_ids**: BarAccumulator creates derived HTF BarMessage objects which auto-get new bar_ids from default_factory. This is correct -- HTF bars are distinct bars with distinct IDs.

## Deviations from Plan

None -- plan executed exactly as written.

## Known Stubs

None.

## Threat Flags

None. All threat model items (T-68-08 TRUNCATE, T-68-09 bar_id UUID spoofing, T-68-10 bar_id in Kafka) are accepted per plan threat model with documented rationale.

## Self-Check

| Item | Status |
|------|--------|
| production/migrations/063_pipeline_hardening.sql | EXISTS |
| tests/unit/test_bar_message.py | EXISTS |
| Commit 23806a63 | EXISTS |
| Commit 2bdfa13f | EXISTS |

## Self-Check: PASSED
