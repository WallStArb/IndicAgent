# Hot-Path Isolation

**Version:** 1.1
**Status:** current
**Last Updated:** 2026-09-04
**Tags:** latency, real-time, io-isolation, performance

> Real-time compute is strictly isolated from storage and I/O — the hot path never blocks on a database or network call.

## The Problem It Solves

A naively built trading system puts database writes on the critical path: a bar arrives, the system queries historical data, writes features, reads signals, and only then generates a decision. Under load, I/O latency compounds — a 5ms DB round-trip repeated 132 times per bar produces 660ms of unavoidable latency, and any DB outage stops signal generation entirely.

## The Principle

Separate the system into three latency tiers with strict rules about what each tier can do:

- **Hot path** (sub-millisecond): Stateless compute only. Reads from in-memory state. Writes to nothing. Cannot block.
- **Warm path** (<10ms): Stream routing, topic fan-out. Reads topic offsets. Cannot touch the database.
- **Cold path** (async, batch): Persistence workers consume from topics and write to storage. Completely decoupled from hot-path timing.

The invariant: **no component on the hot path may call I/O.** Hot-path state is loaded once at startup and updated incrementally per bar. If the database goes down, signal generation continues uninterrupted.

## How IndicAgent Applies It

```
Hot:  IBKR TWS → Redpanda Streams → FeatureVectorPipeline (compute)   (sub-ms)
Warm: Streams → feature computation → Kafka (sink)                    (<10ms)
Cold: FeatureVectorWriter → feature_vectors (TimescaleDB)             (async batch)
```

`FeatureVectorPipeline` computes feature vectors from in-memory state (bar history, loaded at startup and updated incrementally per bar) and publishes results to Kafka — Kafka is a sink here, not an inter-stage pipe (DAG Invariant #2). It is not fully DB-ignorant: it holds its own DB handle for reads (warmup history, `ConfigService`) and one-time schema bootstrap, but it never persists its own computed output — that always goes through the dedicated `FeatureVectorWriter` (a `BaseWriter` subclass), which consumes the Kafka topic and writes to `feature_vectors` asynchronously (DAG Invariant #3). Reads-for-warmup on the hot path and writes-of-output on the cold path are different things; only the latter is forbidden inline.

Performance weights, config thresholds, and regime state are loaded at startup via `ConfigService`/`VocabularyService` and refreshed on a timer (not per-bar). Plugin/pipeline state is checkpointed to local disk via `PluginStateManager` — not to the database.

## Invariants

- A compute daemon (e.g. `FeatureVectorPipeline`) may hold a DB handle for its own reads and startup bootstrap, but must never write its own computed output rows — that persistence goes through a dedicated `BaseWriter`/`BaseBatch` subclass (DAG Invariant #3).
- Compute methods should be pure functions of their input + internal state wherever possible — no blocking I/O inline in the per-bar compute path.
- Writers consume from topics — they never receive direct calls from compute agents.
- A `TimescaleDB` outage must have zero impact on signal generation latency or throughput; only the async writer's flush backs up.

## Recipe

When designing a new real-time intelligence system:

1. **Classify every operation** — is this hot (compute), warm (routing), or cold (persistence)?
2. **Forbid cross-tier calls** — hot path cannot call warm or cold. Enforce at code review.
3. **Load state at startup** — weights, thresholds, reference data. Refresh on a timer, never per-event.
4. **Design for DB outage** — if the DB goes down for 10 minutes, what breaks? That list is your hot-path violations.
5. **Instrument the boundary** — measure hot-path latency separately from cold-path write latency. They should be uncorrelated.

## See Also

- Implementation: `docs/intelligence/intelligence-foundation.md` — Data Flow section
- Related concept: `docs/concepts/event-driven-fabric.md` — why Kafka is the decoupling mechanism
- Related concept: `docs/concepts/incremental-computation.md` — how hot-path state is maintained O(1)
- Operations: `docs/intelligence/intelligence-operations.md` — latency breakdown and tuning
