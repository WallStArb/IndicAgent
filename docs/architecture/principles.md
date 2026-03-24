# Foundational Principles of IndicAgent

> This document establishes the "North Star" for all development and architectural decisions. These principles ensure institutional rigor, modularity, and operational resilience.

## 1. Plugin-Native Shell
The platform is an empty shell; intelligence is composed entirely of plugins. If logic isn't a plugin, it's not extensible. The system is designed to be plugin-first, where new capabilities are added by writing a single `@dataclass` without changing pipeline or stream infrastructure.

## 2. Event-Driven Microservices
No service calls another. Redpanda (Kafka-compatible) is the sole, durable communication fabric. This decoupling ensures that restarting one service (e.g., `feature_pipeline_service`) has zero operational impact on others (e.g., `signal_lifecycle_service`).

## 3. Hot Path Isolation
The real-time pipeline never touches the database. Persistence (TimescaleDB) is strictly asynchronous and decoupled via the `feature_writer_service`. This guarantees sub-millisecond hot-path latency.

## 4. Topological Orchestration
Dependency-aware DAG execution replaces hardcoded sequencing. Plugin dependencies are declared (not hardcoded), allowing the system to derive execution order automatically, detect circular dependencies at startup, and enable parallel execution where possible.

## 5. Incremental-First
Every plugin supports incremental `compute_next()` to ensure $O(1)$ updates per bar. This is the cornerstone of our performance (141x speedup over batch recalculation), allowing 123+ plugins to run in <10ms.

## 6. Data Contracts Over APIs
The schema (Pydantic/JSONB) is the API. Service internal logic is opaque; the `IntelligenceEvent` stream is the only contract between producers and consumers.

## 7. Institutional Rigor
Every signal is evidence-graded. No signal fires without cross-tier confluence (CIS score). We prioritize cross-tier agreement from at least 3 of 6 independent evidence buckets.

**See also:** `docs/ideas/renaissance-alpha-pipeline.md` — The Renaissance validation framework that enforces shadow-first statistical testing (ρ > 0.4, p < 0.05) before any alpha source affects position sizing.

## 8. Self-Correcting Pipeline
Drift detection (KS/CUSUM), performance monitoring, and model-weight backfilling are baked into the live loop. The system validates its own integrity and self-adjusts without human intervention.

**See also:** `docs/ideas/ml-ai-palette.md` — Drift detection tools (evidently), automated degradation triggers, and the feedback loop architecture.
