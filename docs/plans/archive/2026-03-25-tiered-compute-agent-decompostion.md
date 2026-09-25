# Implementation Plan: Decomposing FeaturePipelineService into Tiered Agents

**Last Updated:** 2026-05-02

## Objective
Break down the `FeaturePipelineService` monolith into specialized, tier-specific `ComputeAgents` to achieve granular scaling, pipeline observability, and decoupling.

## Decomposition Strategy (The DAG)
1.  **`IndicatorComputeAgent` (I1-I2):** Consumes `market.bars`, emits `intelligence.i1.indicators` and `intelligence.i2.events`.
2.  **`StructureComputeAgent` (I3-I4):** Consumes `intelligence.i2.events`, emits `intelligence.i3.structure` and `intelligence.i4.context`.
3.  **`ConfluenceComputeAgent` (I5-I6):** Consumes `intelligence.i4.context`, emits `intelligence.i5.patterns` and `intelligence.i6.confluence`.

## Implementation Steps
1. **Extract Logic:** Modularize existing logic in `feature_pipeline_service.py` into tier-specific processing functions.
2. **Define Agent Interfaces:** Create separate `ComputeAgent` classes for each tier (using the `DataWriterAgent` pattern where appropriate).
3. **Kafka Wiring:** Point each Agent to consume its specific input topic and publish to its specific tier topic as defined in `docs/architecture/AGENT_STANDARD.md`.
4. **Metrics Instrumentation:** Add tier-specific Prometheus metrics (`processing_latency`, `events_emitted_total`) to each agent.

## Verification
- **DAG Integrity:** Ensure a single event flows from I1 -> I8 through the defined topics.
- **Independence:** Verify each Agent scales/operates independently on its own consumer group.
- **Latency Audit:** Confirm that the decoupling removes the "monolith jitter" observed in the original service.
