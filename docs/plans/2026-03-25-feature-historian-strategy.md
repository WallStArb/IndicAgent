# Feature Historian Implementation Strategy: The Renaissance "Shadow" Pattern

## Objective
Decouple I1–I5 feature persistence from the compute hot-path using a robust, verified Kafka-Journaling pattern, ensuring zero data loss and perfect parity with legacy DB writes.

## Phase Strategy: The "Shadow" Rollout
To satisfy the Renaissance mandate for integrity, we will implement this in stages:

1.  **Repository-First (The Data Sink):** 
    - Implement `src/persistence/repository/feature_repository.py`.
    - This creates the contract for writing features, ensuring the Agent has a high-performance DB sink before any Kafka topic is pushed.
2.  **Shadow Mode (Verification):**
    - Deploy `FeatureHistorianAgent` consuming a *new* Kafka topic (`intelligence.feature.journal`).
    - The legacy `FeaturePipelineService` continues writing to the DB directly (Dual-Write).
    - We verify parity between the legacy DB write and the Agent-written DB records.
3.  **Hot-Path Cutover:**
    - Refactor `FeaturePipelineService` to publish to the journal.
    - Remove direct DB writes.
    - Legacy path is now a "standby" if Agent latency or correctness fails.

## Persistence Contract
- **Input Stream:** `intelligence.feature.journal`
- **Schema:** `IntelligenceJournal` (Pydantic, versioned).
- **Sink:** PostgreSQL/TimescaleDB hypertable (`feature_snapshots`).

## Implementation Tasks
- [ ] Create `src/persistence/repository/feature_repository.py`.
- [ ] Implement `FeatureHistorianAgent` batch-write logic.
- [ ] Instrument `FeaturePipelineService` to support Dual-Write.
- [ ] Conduct parity audit (verify Agent-write vs. Service-write).

## Verification
- **Parity Check:** Count rows in `feature_snapshots` (Legacy vs Agent).
- **Latency Check:** `ConsumerLag` of `FeatureHistorianAgent` < 50ms average.
- **Audit Trace:** Verify `ProvenanceChain` is present in all journal entries.
