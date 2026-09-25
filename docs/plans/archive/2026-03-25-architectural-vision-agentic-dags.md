# Architectural Vision: From Monolith-Services to Agentic-DAGs

**Last Updated:** 2026-05-02

## Objective
Transition the IndicAgent from a monolithic, DB-coupled service architecture to a modular, event-driven "Agentic DAG." This shift ensures sub-millisecond hot-path latency, improved data integrity, and clear separation of concerns (OODA loop).

## The Definition of an "Agent"
An Agent is an autonomous, event-driven compute node that adheres to the following:
1. **OODA Loop (Observe-Decide-Act):** Agents are self-instrumenting and self-aware. They monitor their own metrics (lag, latency, health) and use these metrics to optimize their internal processing loop.
2. **Stream Contract (DAG Alignment):** Agents do not have side-effect I/O (e.g., direct DB writes) in their core processing path. They consume from an input topic, transform/validate, and publish to an output topic or a dedicated persistence journal.
3. **Repository Pattern:** Persistence is delegated to a Repository (e.g., `src/persistence/repository/`). Agents are "DB-ignorant" and interact only with domain-agnostic repositories.
4. **Resilience & Fault Tolerance:** Agents route errors and anomalies to standardized Dead Letter Queues (DLQ) rather than logging-and-dying.

## Domain Taxonomy Refactor
We are standardizing all intelligence pipeline nodes into a clear domain-based taxonomy:

| Domain | Role | Agent Suffix | Example |
| :--- | :--- | :--- | :--- |
| **Compute** | Feature Processing | `ComputeAgent` | `IndicatorComputeAgent` |
| **Decision** | Signal Generation | `SignalGeneratorAgent` | `SignalGeneratorAgent` |
| **Persistence** | Data Write/Historian | `WriterAgent` | `SignalLedgerWriterAgent` |
| **Logic** | Narrative/AI Sync | `NarrativeWriterAgent` | `NarrativeWriterAgent` |

## Strategic Benefits
- **Determinism:** The hot-path (Signal Fire) is decoupled from Cold-path (Database I/O).
- **Observability:** Granular monitoring per-agent allows for surgical bottleneck identification.
- **Resource Scaling:** Agents scale based on their specific resource profile (e.g., compute-heavy agents scale by CPU; I/O-heavy agents scale by Consumer Lag).

## Implementation Roadmap
1. **Standardization:** Refactor all `services/` modules to the Agentic pattern.
2. **Persistence Layering:** Move all direct SQL execution into `src/persistence/repository/`.
3. **Journal-Driven Persistence:** Route all persistent writes to specialized `WriterAgents` consuming `intelligence.*.journal` topics.
4. **Audit Layer:** Implement the "Shadow Audit" framework to validate that Agent logic matches reference implementations.
