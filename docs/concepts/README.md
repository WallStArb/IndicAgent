<!-- generated-by: gsd-doc-writer -->
# Concepts — Architectural Deep Dives

**Version:** 2.8
**Status:** current
**Last Updated:** 2026-05-27

Understand the architectural decisions and design patterns.

---

## Core Architecture

**[Intelligence Tiers](intelligence-tiers.md)**
I1-I8 progressive intelligence framework — what each tier computes and why

**[Plugin Architecture](plugin-architecture.md)**
Plugin protocol, registry pattern, incremental compute interface

**[DAG Execution](dag-execution.md)**
Directed acyclic graph — dependency ordering, topological sort, cycle prevention

**[Data Pipeline](data-pipeline.md)**
Hot/warm/cold data flow, Redpanda topics, consumer groups, TimescaleDB persistence

---

## Advanced Topics

**[Incremental Computation](incremental-computation.md)**
State-based calculations — 141x performance boost, Wilder's smoothing, Welford's algorithm

**[CIS Scoring](cis-scoring.md)**
Composite Intelligence Score — 6-bucket weighted signal selection, regime gating, adaptive weight learning

**[Signal Lifecycle](signal-lifecycle.md)**
I7 signal creation → zone activation → MAE/MFE tracking → 8-class outcome classification; expires_at TTL (Phase 107.5)

**[Regime Classification](regime-classification.md)**
Context-aware intelligence: HMM hidden states, GARCH volatility forecast, Kalman trend filter, BOCPD changepoint detection

**[Swarm Intelligence](swarm-intelligence.md)**
5-agent Mixture of Agents (MoA) overlay — skeptic, correlation, regime coherence, counterfactual, ML scorer

**[Evolvable AI](evolvable-ai.md)**
Evolutionary agent framework — genome mutation, fitness function, reproductive operators (v2.8 active)

---

## Next Steps

- **Learn by doing:** [Guides](../guides/) for hands-on tasks
- **Look up specifics:** [Reference](../reference/) for API docs


---

**Back to:** [Documentation Home](../README.md)
