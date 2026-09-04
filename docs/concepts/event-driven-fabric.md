# Event-Driven Fabric

**Version:** 1.1
**Status:** current
**Last Updated:** 2026-09-04
**Tags:** event-driven, messaging, decoupling, kafka

> Agents communicate exclusively through named topics — no agent ever calls another directly.

## The Problem It Solves

Direct inter-agent calls create invisible coupling: agent A's latency affects agent B, a crash in A blocks B, deploying a new version of A requires coordinating with every caller. In a system with 20+ agents, point-to-point coupling produces a dependency web that cannot be reasoned about or restarted safely.

## The Principle

Every agent publishes events to topics and subscribes to topics. No agent holds a reference to another agent. The fabric (Kafka/Redpanda) is the only shared resource between agents. An agent can be restarted, replaced, or scaled independently without affecting any other agent — each resumes from its committed offset with no data loss.

This makes the system topology a first-class artifact: the full data flow is visible by examining topic subscriptions, not by tracing call graphs through code.

## How IndicAgent Applies It

All inter-agent communication flows through Redpanda (Kafka-compatible). Topic names are constructed via `src/core/stream_keys.py` — never hardcoded. The `env_prefix` from `Settings` namespaces all topics, preventing cross-environment contamination.

Key design decisions:
- **Kafka is transport, not state store.** Retention is minimal — topics are not replayed for state reconstruction. Hot state lives in local file checkpoints; historical data lives in TimescaleDB.
- **Topics use dots not colons** (Redpanda convention). `stream_keys.py` enforces this.
- **Consumer groups are service-scoped** — each service has its own group ID, so restarts resume from committed offsets automatically.
- **The `KafkaProducerClient.publish()` kwarg is `msg=`** (not `value=`). Wrong kwarg silently fails at flush.

```
Bar arrives → FeatureVectorPipeline (FeatureFactory.compute()) → topic_feature_vectors

topic_feature_vectors → FeatureVectorWriter (consumer group feature_vector_writer_group)
                       → TimescaleDB (feature_vectors hypertable)

Ensemble alpha score crosses threshold → AlphaPublisher → topic_alpha_events
                                                          → TimescaleDB (alpha_events)
```

`FeatureVectorPipeline` never opens a write connection for its own computed output — it publishes to `topic_feature_vectors` and `FeatureVectorWriter` is the sole consumer that persists. Same pattern for `AlphaPublisher`/`topic_alpha_events` — `alpha_publisher` is the sole writer to `alpha_events`. This is DAG Invariant 3 (see `docs/concepts/dag-execution.md`) expressed as topic flow: a compute daemon publishes, a dedicated writer persists, never the other way around.

## Invariants

- No agent may import or instantiate another agent class directly.
- All topic names must be constructed via `stream_keys.py`. No hardcoded topic strings.
- `INDICAGENT_ENV` must be consistent across all services — mixed env prefixes cause services to subscribe to different topics, producing zero data flow with no error.
- `KafkaProducerClient.publish()` calls must `await` the result — fire-and-forget silently drops messages.

## Recipe

When designing an event-driven agent system:

1. **Define topics before agents** — the topic schema is the API contract between agents.
2. **Name topics after the event, not the producer** — `topic_intelligence_features` not `topic_pipeline_output`.
3. **Namespace by environment** — prevents dev/prod data mixing.
4. **Consumer groups per service** — enables independent restart and scaling.
5. **Treat Kafka as transport** — if you need Kafka for state reconstruction, your agents have no local state management and will be slow on restart.
6. **Audit every `publish()` call** — confirm it is awaited and the kwarg name matches the client's API.

## See Also

- Implementation: `docs/data/data-streaming.md` — full topic catalog, ADRs, stream key conventions
- Related concept: `docs/concepts/hot-path-isolation.md` — why isolation is possible given this fabric
- Code: `src/core/stream_keys.py` — canonical topic construction
