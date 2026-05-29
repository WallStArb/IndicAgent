# Concepts Library

Reusable intellectual artifacts — the architectural DNA of IndicAgent. Each doc captures the *why* behind a design decision at a level of abstraction that transfers to new systems.

**How to read this library:**
- New engineer onboarding: read Layer 1 first, then Layer 2
- Designing a new system: use the Recipe section of any relevant doc
- Understanding a domain doc: the concept doc is its intellectual foundation

---

## Layer 1 — System Architecture

Foundations that everything else rests on.

| Doc | Core idea |
|-----|-----------|
| [Hot-Path Isolation](hot-path-isolation.md) | Real-time compute never touches storage — decouples latency from I/O |
| [Event-Driven Fabric](event-driven-fabric.md) | Agents decouple through topics, never direct calls |
| [Incremental Computation](incremental-computation.md) | O(1) per-bar updates via stateful plugins |
| [Temporal Data Architecture](temporal-data-architecture.md) | Time-series native; every event timestamped, nothing dropped |

## Layer 2 — Intelligence Design

How you build a smart system on that foundation.

| Doc | Core idea |
|-----|-----------|
| [Progressive Intelligence Extraction](progressive-intelligence-extraction.md) | Raw data → actionable intelligence through 8 tiers (I1-I8) |
| [Plugin Composability](plugin-composability.md) | Intelligence as independently-testable units with declared dependencies |
| [DAG Execution](dag-execution.md) | Topological ordering derives parallelism from the dependency graph |
| [Regime Awareness](regime-awareness.md) | Signals conditioned on market state, not absolute thresholds |

## Layer 3 — Trust and Quality

How you know the system is right.

| Doc | Core idea |
|-----|-----------|
| [Evidence-Graded Signals](evidence-graded-signals.md) | Multi-dimensional confirmation before any signal fires |
| [Adaptive Intelligence](adaptive-intelligence.md) | The system earns the right to act through statistical proof |
| [Swarm Intelligence](swarm-intelligence.md) | Mixture of expert agents — no single model makes a decision |

## Layer 4 — Operational Excellence

How you run it reliably at scale.

| Doc | Core idea |
|-----|-----------|
| [Observability and Traceability](observability-and-traceability.md) | Every decision auditable end-to-end |
| [Autonomous Resilience](autonomous-resilience.md) | The system detects and corrects its own failures |
