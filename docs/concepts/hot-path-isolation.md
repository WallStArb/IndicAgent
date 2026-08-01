# Hot-Path Isolation

**Version:** 1.0
**Status:** stale (v2.x, see banner)
**Last Updated:** 2026-05-30
**Tags:** latency, real-time, io-isolation, performance

> Real-time compute is strictly isolated from storage and I/O — the hot path never blocks on a database or network call.

> **Staleness note (2026-08-01):** The hot/warm/cold isolation principle still holds in v3.0,
> but this doc's worked example (`IntelligencePipeline`, I1-I7 plugin DAG, `FeatureWriter`/
> `SignalWriter`) names the ARCHIVED v2.x pipeline, with no live consumer as of 2026-07-02 per
> CLAUDE.md — the live equivalent is `FeatureVectorPipeline`/`FeatureVectorWriter`. Not yet
> rewritten for v3.0 -- tracked for a future doc pass, not fixed here.

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
Hot:  IBKR TWS → Redpanda Streams → IntelligencePipeline   (sub-ms)
Warm: Streams → I1-I7 plugin DAG → ranked signals + feature vectors    (<10ms)
Cold: FeatureWriter + SignalWriter → TimescaleDB              (async batch)
```

The intelligence pipeline (I1-I7) is fully DB-ignorant. It reads from in-memory plugin state (loaded at startup, updated per bar) and publishes results to Kafka topics. Dedicated Writers (`FeatureWriter`, `SignalWriter`, `LifecycleWriter`) consume those topics and handle persistence asynchronously.

Performance weights, CIS weights, and regime state are loaded at startup and refreshed on a timer (not per-bar). Plugin state is checkpointed to local disk — not to the database.

## Invariants

- The real-time pipeline (`IntelligencePipeline`) must never import or call `database_manager`.
- Plugin `compute()` and `compute_next()` methods must be pure functions of their input + internal state.
- Writers consume from topics — they never receive direct calls from compute agents.
- A `TimescaleDB` outage must have zero impact on signal generation latency or throughput.

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
