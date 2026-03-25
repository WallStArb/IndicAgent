# Implementation Plan: Feature-Tier Agentic Refactor

## Objective
Convert `FeaturePipelineService` to a pure ComputeAgent and migrate persistence to the unified `DataWriterAgent`.

## Scope & Impact
- **Services:** `services/feature_pipeline_service.py` (Producer), `src/persistence/writer/data_writer_agent.py` (Consumer).
- **Persistence:** Remove legacy SQL `INSERT` logic; route all data through `intelligence.feature.journal`.

## Implementation Steps
1. **Instrument Producer:** Refactor `FeaturePipelineService` to emit `IntelligenceJournal` records to Kafka topic `intelligence.feature.journal`.
2. **Remove Legacy Sink:** Delete legacy SQL `INSERT` calls from `FeaturePipelineService`.
3. **Configure Writer Agent:** Instantiate `DataWriterAgent` (Feature domain) consuming `intelligence.feature.journal`.
4. **Verification:** Add `tests/integration/test_feature_persistence_parity.py` comparing Agent-written DB rows against expected legacy schema.

## Verification
- **Unit/Int Test:** Ensure `FeaturePipelineService` emits correctly formatted `IntelligenceJournal` packets.
- **Parity Assertion:** Run `test_feature_persistence_parity.py` to confirm identical DB insertion logic.
- **Observability:** Verify `PERSISTENCE_BATCH_LATENCY` is recording in the writer agent.
