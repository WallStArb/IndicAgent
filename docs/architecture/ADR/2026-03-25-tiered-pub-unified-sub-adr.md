# Architectural Decision Record (ADR): Tiered Pub, Unified Sub Persistence DAG

## Context
We need to balance real-time signal latency (requires granular, decoupled streams) with ML-training/audit requirements (requires unified, snapshot-in-time state).

## The Decision: "Tiered Pub, Unified Sub"
We are implementing a hybrid topology:
1. **Tiered Pub (The Hot Path):** Each intelligence tier (I1–I8) publishes to its own domain-specific Kafka topic (e.g., `intelligence.i1.indicators`). 
   - **Benefit:** Downstream agents only subscribe to the tiers they require, minimizing deserialization overhead and memory footprint.
2. **Unified Sub (The Cold Path):** A dedicated `IntelligenceHistorianAgent` subscribes to *all* tiered topics (I1–I8), performs the "Fan-In" (merging disparate streams into a single, unified `IntelligenceRecord`), and persists the final snapshot to the `intelligence.journal`.
   - **Benefit:** The ML/Training layer sees a unified, consistent state vector without needing to manually synchronize 8 different streams.

## The Convergence Gate (The Partial State Solution)
To address the "Join Dependency" in the Cold Path, the `IntelligenceHistorianAgent` MUST implement a stateful convergence gate:
1. **Watermarking:** Every `IntelligenceEvent` (I1–I8) is keyed by a `BarSequenceID` (e.g., `SYMBOL:TF:TIMESTAMP`).
2. **Convergence Buffer:** The Agent maintains a local TTL-based cache of tiered messages. It only performs the "Fan-In" once the expected set of tiers (or a configurable timeout) is met.
3. **Partial State Audit:** If a tier misses the window (e.g., I3 is missing after 60s), the Agent persists a record flagged `is_complete=False` to the `intelligence.journal`, ensuring we do not synthesize "ghost intelligence" from incomplete data.
4. **Separation of Concerns:** The `Historian` is the SOLE authority for convergence. No other service in the DAG performs multi-stream joining.

## Implementation Standard
- **Compute Agents:** Responsible only for the specific domain calculation and publishing to their respective `intelligence.i{N}` topic.
- **Historian Agent:** The *sole* agent responsible for joining the tiered topics into a canonical persistence record.
- **Data Integrity:** The `IntelligenceRecord` schema is the definitive schema for persistence.

---
**Status:** Architecture Locked.
**Last Updated:** 2026-03-25
