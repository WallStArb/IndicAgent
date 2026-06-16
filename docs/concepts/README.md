# Concepts Library

This folder contains the foundational concepts behind IndicAgent's architecture. Each document explains one principle: the problem it solves, the theoretical solution, and how IndicAgent applies it.

These are stable reference documents. They explain *why* the system is designed the way it is — not implementation details (see domain folders) or operational procedures (see `docs/operations/`).

---

## Index

| Concept | One-line summary |
|---------|-----------------|
| [Adaptive Intelligence](adaptive-intelligence.md) | Every component earns influence through statistical proof and loses it when evidence degrades |
| [Autonomous Resilience](autonomous-resilience.md) | The system detects failures, routes around them, and recovers without human intervention |
| [DAG Execution](dag-execution.md) | Plugin dependencies are declared, not scheduled — topological sort derives order automatically |
| [Event-Driven Fabric](event-driven-fabric.md) | Agents communicate exclusively through named topics — no agent ever calls another directly |
| [Evidence-Graded Signals](evidence-graded-signals.md) | A signal requires agreement from multiple independent evidence sources |
| [Extrinsic Confidence Layer](extrinsic-confidence-layer.md) | Extrinsic market context is a feature for the ML model, not a gate — annotate, never suppress |
| [Hot-Path Isolation](hot-path-isolation.md) | Real-time compute is strictly isolated from storage — the hot path never blocks on I/O |
| [Incremental Computation](incremental-computation.md) | Plugins maintain bounded state and update O(1) per bar — no history reprocessed after warmup |
| [Observability and Traceability](observability-and-traceability.md) | Every decision is measurable, attributable, and auditable from bar to signal to outcome |
| [Plugin Composability](plugin-composability.md) | Intelligence is entirely composed of plugins — adding capability means writing a plugin, not modifying core |
| [Progressive Intelligence Extraction](progressive-intelligence-extraction.md) | Raw data is transformed through sequential layers of increasing abstraction before patterns emerge |
| [Regime Awareness](regime-awareness.md) | Market behavior is non-stationary — every signal must know what kind of market it is operating in |
| [Signal Ledger Architecture](signal-ledger-architecture.md) | Three tables, three concerns — detection, hypothesis, execution — enabling an unbiased ML training set |
| [Swarm Intelligence](swarm-intelligence.md) | No single agent makes a decision — specialists each assess one dimension and outputs are composed |
| [Temporal Data Architecture](temporal-data-architecture.md) | Every market event is a timestamped immutable record — nothing dropped, everything queryable by time |
