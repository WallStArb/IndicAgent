# Latency & Persistence Audit: Signal Generator Refactor (Phase 1)

## Objective
Decouple `SignalGeneratorService` from database I/O to meet sub-millisecond signal latency requirements, adhering to Renaissance "Hot Path" purity principles. 

## Scope & Impact
- **Affected File:** `services/signal_generator_service.py`
- **Impact:** Removes blocking `await db.insert()` from the signal generation hot path.
- **New Dependency:** `IntelligenceJournal` Pydantic model for Kafka-journaled persistence.

## Proposed Solution
1. **Producer Refactor:** Transform existing `LedgerEntry` and `FeatureSnapshot` into an `IntelligenceJournal` record.
2. **Kafka Journaling:** Asynchronously publish journal entries to `topic_intelligence_journal()` (Kafka) instead of direct database writing.
3. **Data Integrity:** Ensure no loss of feature attribution/provenance by embedding `ProvenanceChain`.

## Implementation Steps
1. **Instrument Schema:** Add metadata/provenance field wrappers to support zero-copy instrumentation.
2. **Refactor Service:** Update `signal_generator_service.py` to route entries to a journal-publisher.
3. **Verification:** Add a unit test to verify that the journaled output matches the pre-refactor DB-insert structure.

## Alternatives Considered
- **Direct Kafka write (No Journaling):** Discarded. Violates "Unified Intelligence Journaling" and makes reconciliation harder.
- **Background Task:** Discarded. `asyncio.create_task` introduces risks of event loop saturation. Explicit Kafka producer is preferred.

## Verification
- Run existing signal generator integration tests (e.g., `tests/integration/test_signal_generator_e2e.py`).
- Validate that Kafka journal topic (`dev.intelligence.journal`) receives records with correct provenance schema.
