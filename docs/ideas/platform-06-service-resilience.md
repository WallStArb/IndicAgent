# Service Resilience Patterns

**Version:** 1.0
**Status:** draft
**Priority:** low — Pattern 1 (circuit breaker) elevated to Phase 084 scope
**Milestone:** Pattern 1 → Phase 084; Pattern 2-3 → future
**Last Updated:** 2026-05-16
**Tags:** redpanda, kafka, consumer, resilience, circuit-breaker, monitoring, prometheus, state-recovery
**Reviewed:** 2026-05-16 — Pattern 1 (Consumer Circuit Breaker) cross-referenced from `architectural-weakness-assessment.md` #10 as the implementation design for wiring `PluginCircuitBreaker` into the intelligence pipeline. Pattern 3 (observability metrics) cross-referenced from #6.

---

## Context

Originally documented as "Robinhood-inspired" patterns when the platform used Redis Streams. The patterns themselves remain valid now that the backbone is Redpanda (Kafka-compatible). The implementation details change — Redpanda handles durability and replication natively that Redis Streams could not — but the gaps in consumer isolation, state recovery, and monitoring observability still exist.

These are infrastructure hardening ideas, not intelligence features. Build them when service reliability becomes the bottleneck, not before.

---

## Pattern 1: Consumer Proxy / Circuit Breaker

**The gap:** All Redpanda consumption is currently tightly coupled to business logic inside each service. If a consumer stalls, crashes, or starts lagging, there's no isolation layer — the service either recovers or it doesn't.

**The idea:** A lightweight proxy wraps the Kafka consumer loop and provides:

- **Health checks** on configurable interval — detects stalled consumers, offset-lag growth
- **Circuit breaker** — after N consecutive failures, stops calling the message handler for a timeout window, then enters half-open retry
- **Backoff and retry** with exponential backoff on transient failures
- **Optional latency-based scaling** — if consumer lag exceeds target (e.g. 100ms), spawn additional consumer instances; scale down when well below target

**Config surface:**
```
health_check_interval_sec: 30
max_retry_attempts: 3
retry_backoff_base_sec: 1.0
circuit_breaker_threshold: 5  # failures before open
circuit_breaker_timeout_sec: 60
target_lag_ms: 100  # for optional autoscaling
```

**With Redpanda specifically:** Kafka consumer group lag is directly queryable via Redpanda Admin API — the proxy can use this instead of internal counters. Circuit breaker state should be exported to Prometheus for dashboard visibility.

**Integration point:** `src/core/` — wraps existing consumer loops without touching business logic. Each service opts in via flag.

---

## Pattern 2: Changelog Streams for State Recovery

**The gap:** Services lose their in-memory state on restart and must warm up from scratch. The indicator service reseeds from `market_data_ohlcv`; the signal generator waits ~50 minutes for live bars. More resilient recovery would replay from a changelog.

**The idea:** For critical stateful streams, maintain a companion changelog topic (e.g. `development.indicators.changelog`) that records state snapshots. On restart, read the changelog from a timestamp rather than replaying all raw market bars.

- Create changelog topic per source stream; append entries with `(source_message_id, timestamp, state_snapshot)`
- Optional compaction (Redpanda topic compaction — keep latest per key) to bound size
- Recovery: services read changelog from last known good timestamp, apply state in order, then resume live consumption from the corresponding offset

**With Redpanda specifically:** Redpanda supports log compaction natively — this is closer to Kafka Streams changelog topics than the Redis Streams workaround the original doc described. Compacted topics keyed by `SYMBOL:TF` would store the latest state snapshot per instrument.

**Scope:** Start with indicator state (I1 bar history) and signal generator warmup — these have the longest cold-start penalty. I4 GARCH/HMM state is the next candidate.

---

## Pattern 3: Enhanced Consumer Observability

**The gap:** Current Prometheus metrics cover per-plugin call counts and service-level health. There's no per-consumer lag tracking, processing duration histograms, or circuit breaker state visibility.

**Metrics to add** (via `src/observability/metrics.py`):

```
indicagent_consumer_messages_total{service, topic, status}         # counter
indicagent_consumer_processing_duration_seconds{service, topic}    # histogram
indicagent_consumer_lag_messages{service, topic}                   # gauge (from Redpanda API)
indicagent_consumer_circuit_breaker_state{service, consumer}       # gauge (0=closed, 1=open)
indicagent_stream_throughput_messages_per_second{topic}            # gauge
indicagent_consumer_errors_total{service, error_type, topic}       # counter
```

**Integration:** Extend existing metrics ports (each service already exposes a Prometheus endpoint). Redpanda itself exposes consumer group lag via its Admin API and `/metrics` endpoint — can scrape directly into Grafana without adding service-level code for lag metrics.

**Priority:** Consumer lag and processing duration are the highest-value additions — they directly surface the "is the pipeline keeping up?" question that's currently only answerable by reading logs.

---

## Implementation Order

1. **Enhanced observability first** — lowest effort, highest operational value. Add consumer lag + processing duration metrics. Surfaces whether the other patterns are even needed.
2. **Consumer proxy / circuit breaker** — build when a service has recurring consumer stalls that require manual intervention.
3. **Changelog streams** — build when cold-start time (indicator warmup, signal generator ~50 min) becomes operationally unacceptable.
