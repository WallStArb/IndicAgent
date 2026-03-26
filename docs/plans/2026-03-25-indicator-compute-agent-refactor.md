# Refactor Plan: IndicatorService to IndicatorComputeAgent

## Objective
Convert `IndicatorService` into a pure `IndicatorComputeAgent` within the Agentic DAG. This agent will focus on the compute-intensive I1–I6 technical indicator calculations, emitting events to `intelligence.i1.indicators` and downstream topic streams.

## Scope & Impact
- **Affected File:** `services/indicator_service.py`
- **Impact:** Decouples technical compute from any database/state-management orchestration.
- **Dependency Migration:** Strip legacy DB manager and manual state tracking; enforce `Repository` or external cache for state if needed.

## Implementation Steps
1. **Remove DB Dependencies:** Strip `DatabaseManager`, direct SQL queries, and legacy I/O.
2. **Instrument Producer:** Configure `KafkaProducerClient` to publish `I1Indicators` to `intelligence.i1.indicators`.
3. **Refactor Compute Loop:** Implement the OODA-loop pattern—consume from `market.bars`, compute indicators, publish to `intelligence.i1`.
4. **Standardize Metrics:** Instrument `processing_latency` and `throughput` using our standardized `observability/metrics.py`.

## Verification
- **Functional Check:** Verify I1 indicator outputs match legacy values for a known bar sequence.
- **Pipeline Integrity:** Verify that `IndicatorComputeAgent` downstream consumers (e.g., `ConfluenceComputeAgent`) receive the correct Kafka stream.
- **Observability:** Verify `events_consumed_total` is correctly reporting.
