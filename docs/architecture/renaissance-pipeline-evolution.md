# Renaissance Pipeline Evolution Strategy

## Context
This document tracks the evolution of the `indicagent` data layer from a multi-hop Kafka DAG to a high-performance, in-process Intelligence Engine.

## Baseline (Current): Data Layer 2.0
We have successfully implemented:
- **Clock-Driven Data Flow:** `TwsDaemon` now guarantees 1-minute bar emission via internal heartbeat, ensuring temporal alignment for stateful models.
- **Multi-Stream Reconciliation:** Dual-stream comparison (5s real-time vs 1m audited) provides drift detection.
- **Zero-Loss Guarantee:** Kafka consumers migrated to `auto_offset_reset="earliest"` with explicit `commit()` operations, ensuring mathematical continuity after service crashes.

## Architectural Proposal: The In-Process Intelligence Engine
To scale to 5,000+ symbols and reduce cumulative latency (50ms per hop), we propose migrating from a distributed Kafka-DAG to an **In-Process Intelligence Engine**.

### Core Principles
1. **Memory Bus vs. Kafka Bus:** Tier-to-tier communication moves from Kafka topics to an internal `asyncio.Queue` (Memory Bus). 
2. **Selective Egress:** Only critical, consumer-facing data (e.g., `signals.aggregated`) is pushed to Kafka. This preserves modularity and external service observability while eliminating internal serialization overhead.
3. **Tiered Compute:** I1–I3 (Indicator tiers) run for all symbols; I4–I6 (Intelligence/Confluence tiers) run only if triggered by Tier 1.

### Operational Roadmap
1. **Benchmark:** Quantify current Kafka-hop latency and CPU overhead per-symbol.
2. **Sidecar Development:** Implement the `InternalEventBus` and `EgressManager` within `FeaturePipelineService`.
3. **Phase Migration:** Gradually collapse the DAG tiers into the Engine, one tier at a time, using the internal bus.

---
*Analysis Date: 2026-03-22*
