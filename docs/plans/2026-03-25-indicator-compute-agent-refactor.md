# Refactor Plan: IndicatorService to IndicatorComputeAgent

## Objective
Convert `IndicatorService` into a pure `IndicatorComputeAgent` within the Agentic DAG. This agent will focus on I1 technical indicator calculations, emitting events to `intelligence.i1.indicators` and downstream topic streams. I2-I6 remain in `feature_compute_agent`.

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
- **Pipeline Integrity:** Verify that `IndicatorComputeAgent` downstream consumers (e.g., `intelligence_compute_agent`) receive the correct Kafka stream.
- **Observability:** Verify `events_consumed_total` is correctly reporting.

## Architecture Decision: Why Not Tiered Decomposition

A tiered decomposition of I1-I6 into separate agents (IndicatorComputeAgent I1-I2, StructureComputeAgent I3-I4, ConfluenceComputeAgent I5-I6) was evaluated and rejected (see archived plan `tiered-compute-agent-decompostion.md`).

**The correct DAG boundary is `feature_compute_agent` (I1-I6) vs `intelligence_compute_agent` (I7/I8)**, not horizontal tier slicing within I1-I6.

Reasons:
- **State coupling**: GARCH and HMM maintain running estimates across bars as in-process state. These are not snapshots — they cannot be cleanly serialized into a Kafka message at the I4→I5 boundary. A split there requires Redis or repeated recomputation from bar history.
- **The I1→I2 split is the exception**: I2 crossover detection only needs the previous bar's I1 snapshot (a simple dict). That's why `indicator_compute_agent` (I1) publishing to `intelligence_compute_agent` (I2-I6 or I7/I8) works cleanly — it doesn't generalize further down the chain.
- **Goal already achieved**: The compute/persistence separation (DB-ignorant agents + async DataWriterAgents) delivers the observability, scaling, and decoupling benefits without the Kafka hop overhead of 3 additional inter-tier topic boundaries.
- **Wrong bottleneck**: I7/I8 (LLM calls, regime gating, calibration) is the expensive, non-deterministic, rate-limited tier. That is where independent scaling and fault isolation matter, not within the fast deterministic I1-I6 math.
