# Event-Driven Fabric

**Version:** 1.0
**Status:** stale (v2.x, see banner)
**Last Updated:** 2026-05-30
**Tags:** event-driven, messaging, decoupling, kafka

> Agents communicate exclusively through named topics — no agent ever calls another directly.

> **Staleness note (2026-08-01):** The event-driven-fabric principle itself still holds in
> v3.0, but this doc's worked example (`intelligence_pipeline` → `topic_intelligence_features`
> / `topic_intelligence_i7` → `feature_writer_service`/`signal_writer_service`) names the
> ARCHIVED v2.x topology, with no live consumer as of 2026-07-02 per CLAUDE.md. Not yet
> rewritten for v3.0 -- tracked for a future doc pass, not fixed here.

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
Bar arrives → intelligence_pipeline → topic_intelligence_features
                                    → topic_intelligence_i7
                                    → topic_shadow_transitions

topic_intelligence_features → feature_writer_service → TimescaleDB
topic_intelligence_i7       → signal_writer_service  → TimescaleDB (signal_events + trade_frames)
topic_shadow_transitions    → swarm_ledger_writer    → TimescaleDB
```

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
