---
phase: 57-intelligencepipelinecomputeagent-unified-i1-i7-pipeline
plan: 01
subsystem: infra
tags: [kafka, stream-keys, migration, systemd, intelligence-pipeline]

# Dependency graph
requires:
  - phase: 54
    provides: Provider abstraction layer (DataProviderAgent, ProviderMergerAgent, IBKRProviderAgent)
provides:
  - topic_intelligence_pipeline_state() Kafka topic function for compacted state checkpoints
  - topic_intelligence_shadow() Kafka topic function for shadow rollout validation
  - Migration 052 adding pre_quality_confidence and pre_calibration_confidence to signal_ledger
  - Systemd unit reference template for IntelligencePipelineComputeAgent
affects: [57-02, 57-03, 57-04]

# Tech tracking
tech-stack:
  added: []
  patterns: [compacted-kafka-topic-for-state-checkpoint, shadow-rollout-topic-pattern]

key-files:
  created:
    - tests/unit/test_stream_keys_57.py
    - production/migrations/052_signal_ledger_attribution.sql
    - services/indicagent-intelligence-pipeline.service
  modified:
    - src/core/stream_keys.py

key-decisions:
  - "New topic functions placed after topic_intelligence_journal() following file ordering convention"
  - "Migration 052 uses IF NOT EXISTS guard; not applied until Plan 4 cutover"
  - "Systemd unit lives in services/ as reference template only; not installed until Plan 4"

patterns-established:
  - "Compacted Kafka topic for agent state checkpoint: intelligence.pipeline.state"
  - "Shadow rollout topic pattern: intelligence.shadow (temporary, removed after cutover)"
  - "Per-stage confidence columns for pipeline attribution analysis"

requirements-completed: []

# Metrics
duration: 3min
completed: 2026-03-29
---

# Phase 57 Plan 01: Foundations — Stream Keys, DB Migration, Systemd Unit Summary

**Kafka topic functions, signal_ledger attribution migration, and systemd unit for unified IntelligencePipelineComputeAgent infrastructure scaffolding**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-29T21:15:56Z
- **Completed:** 2026-03-29T21:19:08Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- Added topic_intelligence_pipeline_state() and topic_intelligence_shadow() to stream_keys.py with 4 passing tests
- Created migration 052 for signal_ledger pre-stage confidence attribution columns
- Created systemd unit reference template for the new IntelligencePipelineComputeAgent

## Task Commits

Each task was committed atomically:

1. **Task 1: Add new topic functions to stream_keys.py** - `ce79669` (feat)
2. **Task 2: DB migration — signal_ledger attribution columns** - `f8f048c` (feat)
3. **Task 3: Systemd unit file for new agent** - `10ba6cc` (feat)

## Files Created/Modified
- `src/core/stream_keys.py` - Added topic_intelligence_pipeline_state() and topic_intelligence_shadow() functions
- `tests/unit/test_stream_keys_57.py` - 4 unit tests for new topic functions
- `production/migrations/052_signal_ledger_attribution.sql` - Adds pre_quality_confidence and pre_calibration_confidence FLOAT columns
- `services/indicagent-intelligence-pipeline.service` - Systemd unit reference template

## Decisions Made
- New topic functions placed after topic_intelligence_journal() to maintain file ordering convention
- Migration 052 uses IF NOT EXISTS guard; not applied until Plan 4 cutover to avoid impacting live signal_ledger
- Systemd unit lives in services/ as reference template only; Plan 4 installs via sudo cp + daemon-reload
- Dead pipeline.* topic functions (topic_quality_gated, topic_regime_gated, etc.) left untouched — still imported by live signal_generator_agent.py

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Stream key infrastructure ready for Plan 02 (IntelligencePipelineComputeAgent implementation)
- Migration 052 ready for application during Plan 4 cutover
- Systemd unit ready for installation during Plan 4 cutover
- No live service files modified; zero risk of regression

## Self-Check: PASSED

All files verified on disk. All 3 commit hashes found in git log. 18/18 tests passing.

---
*Phase: 57-intelligencepipelinecomputeagent-unified-i1-i7-pipeline*
*Completed: 2026-03-29*
