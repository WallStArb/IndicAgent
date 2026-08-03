# Data Streaming — Redpanda event bus: topics, contracts, and operations
**Version:** 2.8.0 | **Status:** stale (v2.x, see banner) | **Last Updated:** 2026-05-29

---

> **Staleness note (2026-08-01):** This doc's topic catalog and ADRs describe the ARCHIVED
> v2.x `IntelligencePipeline` (I1-I7 unified compute, `intelligence.journal`,
> `intelligence.i7.signals`, `NarrativeSwarm`/`AlphaSwarm`, `FeatureWriter` →
> `intelligence_features`, `SignalWriter` → `signal_ledger`), with no live consumer as of
> 2026-07-02 per CLAUDE.md. Not yet rewritten for v3.0 -- tracked for a future doc pass, not
> fixed here.

## Purpose

IndicAgent uses Redpanda (Kafka-compatible) as the message bus that carries every real-time event between pipeline stages. This document explains what topics exist, what flows through them, why the bus is designed the way it is, and how to extend or operate it.

A new engineer reading this should be able to answer:
- Why Kafka instead of direct calls or a shared database?
- What topics exist and who owns each one?
- How is consumer lag monitored and what does a DLQ mean?
- How do I add a new topic without breaking the naming contract?

**Scope:** Redpanda topology, stream key conventions, IntelligenceEvent schemas, and operational runbooks. For the indicator-through-signal (I1-I7) compute stages that produce these events see `docs/data/data-pipeline.md`. For the TimescaleDB tables that writer services populate see `docs/data/data-foundation.md`.

**Tier glossary:** I1 = indicators, I2 = composite_events, I3 = structure, I4 = context, I5 = patterns, SMC = smart_money, I6 = confluence, I7 = signals. See `docs/foundation/naming-system.md` for full reference.

---

## Design Principles

These decisions are recorded as ADRs — the *why* is as important as the *what*.

### ADR-01: Multi-stage bar processing before intelligence computation
`IBKRProvider` publishes raw 1m bars to `market.bars.raw.ibkr`. `ProviderMerger` routes and normalises to `market.bars` (canonical) with auto-failover on primary silence. `BarAggregator` aggregates 1m → 5m/15m/1h/4h/1d and publishes to `market.bars.htf`. `IntelligencePipeline` subscribes to both — each bar triggers an independent indicator-through-signal (I1-I7) in-process pipeline run.

**Why:** Provider-agnostic design. ProviderMerger abstracts the broker. Bar aggregation, persistence, and auditing are separate concerns from intelligence computation. Roll detection runs on a nightly timer without coupling to the hot compute path.

### ADR-02: Kafka is transport, not state
Hot state (plugin state dicts, Kalman/GARCH incremental state) lives in memory. Cold state lives in TimescaleDB. Kafka is the pipe between them — sized for transport only, never queried as a database. Retention is intentionally short (1h–7d depending on tier).

**Why:** Prevents the pattern of services reading back their own Kafka output to reconstruct state (a silent dependency that breaks replay semantics). If a service needs history, it reads from TimescaleDB.

### ADR-03: IntelligenceEvent — versioned, tiered JSONB schema
The canonical typed event on the intelligence bus:

```python
class IntelligenceEvent(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    ts: datetime; symbol: str; tf: str
    bar_close_ts: datetime | None = None   # actual bar close (differs from ts for HTF)
    bar_id: UUID | None = None             # end-to-end bar traceability
    platform: str = "futures"
    source: Literal["live", "backfill"] = "live"
    session_type: SessionType = SessionType.RTH
    pipeline_latency_ms: float = 0.0
    bar: OHLCVBar
    i1: I1Indicators          # 28 technical indicator outputs (indicators, I1)
    i2: I2Events              # 10 composite event outputs (composite_events, I2)
    i3: I3Structure           # 8 market structure outputs (structure, I3)
    i4: I4Context             # 12 context/regime outputs (context, I4)
    i5: I5Patterns            # 16 pattern recognition outputs (patterns, I5)
    smc: SMCContext           # 16 smart money outputs (smart_money concepts)
    i6: I6Confluence          # 6 confluence scores (confluence, I6)
```

**Why tiered sub-dicts vs flat:** Surgical JSONB queries (`SELECT i4->>'garch_sigma'`), smaller GIN indexes per tier, cleaner schema evolution per tier, better TimescaleDB compression.

**Why signals (I7) is NOT in this event:** Signal generation is downstream — published separately via `intelligence.i7.signals` and wrapped with the `IntelligenceEvent` in a `BarIntelligenceRecord` on `intelligence.journal`.

### ADR-04: BarIntelligenceRecord — atomic per-bar persistence unit
`BarIntelligenceRecord` wraps the `IntelligenceEvent` with all ranked signals and pipeline funnel counts into a single atomic record on `intelligence.journal`. Single topic, single consumer per writer.

```python
class BarIntelligenceRecord(BaseModel):
    intelligence: IntelligenceEvent
    ranked_signals: list[RankedSignal]
    winner_plugin: str | None
    winner_confidence: float | None
    winner_direction: int | None
    signals_evaluated: int
    signals_after_quality: int
    signals_after_regime: int
    signals_after_tod: int
    signals_after_calibration: int
```

**Why:** Replaces the old two-phase UPSERT pattern (i7/i8 separate writes). Every row in `intelligence_features` is now complete at insert time — no partial writes, no orphaned tiers. `FeatureWriter` does a single atomic INSERT per bar.

### ADR-05: intelligence_features hypertable — no retention policy
```sql
-- Tiered JSONB columns: bar, i1, i2, i3, i4, i5, smc, i6
-- Compression after 7 days (10-20x ratio; ~40GB → ~2-4GB for 3yr)
-- NO retention policy — seasonal analysis requires multi-year data
-- GIN indexes on i4 (GARCH/Kalman) and smc (smart money)
```

**Why no retention:** 400M rows/3yr is fine with compression. Seasonal patterns require years of history.

### ADR-06: FeatureWriter — standalone async consumer
`services/feature_writer.py` — consumer group `feature_writer`, consumes `intelligence.journal`. 50 events per batch or 5s flush window. DLQ: `feature.writer.dlq`.

**Why separate service:** Async decoupling — can lag, batch writes, retry on DB failure without touching hot path latency.

### ADR-07: signal_ledger — fire-time fields eliminate LATERAL JOIN
Signal replay reads fire-time fields (`expires_at`, `entry_zone_low`, `entry_zone_high`) directly from `signal_ledger` — no JOIN to `intelligence_features` needed at replay time. ML training JOIN is still available when needed.

**Why:** `SignalReplayAuditor` evaluates expiry via `expires_at < NOW()` directly from `signal_ledger`. `expires_at` is computed at INSERT time using `tf_to_seconds()` from `src/core/service_utils.py`.

### ADR-08: Signal lifecycle — compute/writer split
`SignalTracker` handles lifecycle compute (activation, MAE/MFE, 8-class outcome) without touching the database — publishes typed `lifecycle.transitions` events. `LifecycleWriter` consumes those events and persists to `signal_outcomes`.

**8-class outcome taxonomy:** `never_activated`, `stopped_at_entry`, `stopped_in_trade`, `target_1`, `target_1_2`, `target_full`, `ttl_expired_ahead`, `ttl_expired_behind`

**Why split:** Signal tracker previously violated the compute→Kafka→writer DAG by reading and writing `signal_ledger` in the same process. The split enforces the core principle: compute agents are DB-ignorant.

### ADR-09: Plugin state — in-memory per-service
Stateful plugins are managed via in-memory dicts:
- `_plugin_cache` — plugin singletons built at service init, reused per bar
- `_plugin_states` — `dict[tuple[str,str,str], dict]` keyed by `(plugin_name, symbol, timeframe)`; state is swapped onto `p._state` before `compute_full()` and written back after
- `_plugin_call_counts` — OTel metrics sampling (every `PLUGIN_METRICS_SAMPLE_RATE=10` calls)

Plugin state resets on service restart (warm-up: ~50 1m bars for I1 incremental state).

### ADR-10: Consumer group naming convention
```
{service_short_name}_{purpose}         # internal (snake_case)
ext:{app_name}:{purpose}               # external

feature_writer      → feature_writer
signal_writer       → signal_writer
narrative               → narrative
ext:vercel_dashboard:realtime
ext:ml_trainer:batch
```

Each service has an exclusive consumer group — no two services share a group. This ensures offset tracking is per-service and rebalancing is predictable.

### ADR-11: DLQ pattern — every payload-parsing agent has a DLQ
Each agent that deserializes external payloads publishes to a dedicated DLQ topic on parse failure rather than crashing. Pattern: `<domain>.<agent>.dlq`. Full list in `stream_keys.py` (`topic_*_dlq` functions). Enables post-mortem investigation without data loss.

**When you see a DLQ message:** It means a payload arrived that could not be parsed. The original bytes are preserved. Check logs for the parse error and the offending payload. Drain the DLQ with `DLQDrainAgent` after the root cause is fixed.

### ADR-12: Shadow mode — parity before promotion
`FeatureSnapshotWriter` dual-writes to `feature_snapshots_shadow` (shadow table). `ParityAuditor` runs 5-min parity comparisons against the canonical `intelligence_features` table and certifies after 60 consecutive clean cycles (`match_rate >= 0.95`). Alerts route to `topic_alert_requests` when parity drops below threshold.

### ADR-13: GARCH + Kalman — wired to I7, valuable for ML
Both compute on every bar, output to `IntelligenceEvent.i4`. Use cases:
- **trad_MeanReversion**: gate on `kalman_price_position` (> 1.0 std dev)
- **trad_VWAPDeviation**: `garch_sigma` as dynamic spread threshold
- **trad_SqueezeExpansion**: `garch_vol_regime` check (avoid explosive vol)

### ADR-14: Single partition per topic (current default)
All topics use `--partitions 1 --replicas 1`. Ordering guarantees within topic are preserved. Sufficient for current throughput (~4.5 bars/sec).

**When to add partitions:** Consumer lag is growing and the single consumer can't keep up. Trade-off: partitioning breaks total ordering (per-partition only) and adds rebalancing overhead.

### ADR-15: Retention tiers match data lifecycle

| Tier | Retention | Rationale |
|------|-----------|-----------|
| Raw RTB | 1h | Debugging only; canonical bars persisted to DB |
| Canonical 1m | 24h | Replay window for feature writers; DB is source of truth |
| HTF | 7d | Longer replay for longer timeframes |
| Intelligence journal | 24h | Feature writers batch; DB is source of truth |
| Signals | 7d | Signal replay and analysis |
| LLM | 7d | Audit trail for AI decisions |
| DLQ | 7d | Quarantine period for investigation |

---

## Architecture

### Data flow diagram

```
IBKR TWS → IBKRProvider (market.bars.raw.ibkr)
                │
                ↓ ProviderMerger
                │   (failover, routing, quality side-channel)
                │   └─ market.data.quality (ProviderQualityEvent)
                │
                market.bars (canonical 1m)
                │
                ├─ BarAggregator → market.bars.htf (5m-1d)
                ├─ BarWriter → market_data_ohlcv (TimescaleDB)
                └─ BarAuditor → market.events.gap_requests
                │
                roll-batch timer (nightly 8pm) → contract_metadata (DB)
                │
                ↓ IntelligencePipeline
                │   (I1-I7 unified, subscribes market.bars + market.bars.htf)
                │   ├─ intelligence.journal (BarIntelligenceRecord — atomic per-bar record)
                │   ├─ intelligence.i7.signals (all ranked signals pre-ledger)
                │   └─ lifecycle.transitions (signal state changes)
                │
                ├─ FeatureWriter → intelligence_features (TimescaleDB)
                ├─ FeatureSnapshotWriter → feature_snapshots_shadow (shadow dual-write)
                ├─ ParityAuditor (5-min parity comparison; certifies after 60 clean cycles)
                ├─ SignalWriter → signal_ledger (TimescaleDB)
                ├─ SignalTracker (lifecycle compute, DB-ignorant)
                │       └─ lifecycle.transitions → LifecycleWriter → signal_outcomes
                ├─ SignalReplayAuditor (expires_at-driven TTL)
                ├─ SignalAuditor → intelligence.signal.audit
                ├─ SignalMetricsAnalyzer → intelligence.signal_metrics
                │       └─ SignalMetricsWriter → signal_metrics tables (DB)
                ├─ NarrativeSwarm (I8) → narratives → LLMWriter → llm_calls (DB)
                ├─ ServiceAuditor → system.health.events (health monitor + self-healer)
                ├─ AlphaSwarm → topic_signal_lineage()
                │       └─ LineageWriter → signal_lineage (DB)
                └─ REST API (:8000) → SSE → Next.js Dashboard (:3000)
```

**Stack choice rationale:** Redpanda (Kafka-compatible) + TimescaleDB — Kafka-native streaming with consumer groups, hot path unchanged, external consumers use REST not Redpanda directly. Right-sized for current scale (60 active instruments x 5 TFs). Redpanda specifically over vanilla Kafka: single binary with no Zookeeper dependency, lower operational overhead, and compatible with the `rpk` CLI for topic/group management without the Kafka toolchain.

### Redpanda container

**Container:** `redpanda` (from `production/docker-compose.yml`)

| Port | Role |
|------|------|
| `:9092` | Internal Kafka API (container-to-container) |
| `:19092` | External Kafka API (host access) |
| `:9644` | Admin API |
| `:18843` | Schema Registry (available but not yet used) |

### Producer configuration (`KafkaProducerClient`, `src/core/kafka_utils.py`)

librdkafka (via confluent-kafka) config, set in `KafkaProducerClient.start()`:

```python
Producer({
    "bootstrap.servers": settings.kafka_bootstrap_servers,
    "acks": "all",                  # wait for all replicas (durability)
    "enable.idempotence": True,     # exactly-once-per-partition producer semantics
    "compression.type": "lz4",      # ~60% bytes saved on JSON, negligible CPU
})
```

### Consumer configuration (`KafkaConsumerClient`, `src/core/kafka_utils.py`)

```python
Consumer({
    "bootstrap.servers": settings.kafka_bootstrap_servers,
    "group.id": "feature_writer_group",
    "auto.offset.reset": "earliest",   # no data loss on new group
    "enable.auto.commit": False,       # commit only after successful processing
})
```

### Schema evolution

Topics use JSON schemas without Schema Registry (currently):
- Schemas defined in `src/intelligence/schemas.py`
- Core types: `BarEvent`, `IntelligenceEvent`, `SignalEvent`, `LifecycleEvent`, `LLMCallEvent`, `NarrativeEvent`
- Redpanda Schema Registry (port 18843) is available for future backward/forward compatibility enforcement.

---

## Data Contracts

### Topic naming convention

All topics are constructed via `src/core/stream_keys.py` — never hardcoded. Topic names use dots, not colons.

**Pattern:** `{env}.{category}.{subcategory}.{name}`

**Examples:** `dev.market.bars`, `dev.intelligence.journal`, `dev.intelligence.i7.signals`

The `{env}` prefix comes from `Settings.indicagent_env`. Mixed env prefixes cause services to subscribe to different topics and produce zero data flow — always verify `INDICAGENT_ENV` is consistent across the deployment.

### Full stream key catalog

```
# Bar pipeline
{env}.market.bars.raw.{provider}        # per-provider raw bars (IBKRProvider)
{env}.market.bars                        # canonical 1m bars (ProviderMerger)
{env}.market.bars.htf                    # HTF bars 5m-1d (BarAggregator)
{env}.market.data.quality               # ProviderQualityEvent side-channel
{env}.bar.aggregator.state              # compacted BarAggregator state checkpoints (key: version:symbol:tf)
{env}.bar.aggregator.dlq               # malformed 1m bar payloads (BarAggregator)

# Market events
{env}.market.events.gap_requests        # gap fill requests (BarAuditor)
{env}.market.events.roll                # roll detection events (roll_batch timer) — raw string, no stream_keys.py function
{env}.market.events.contract_update    # front-month promotions (ContractMetadataWriter)
{env}.roll.batch.dlq                   # malformed roll event DLQ

# Intelligence pipeline
{env}.intelligence.journal             # BarIntelligenceRecord — atomic per-bar output
{env}.intelligence.i7.signals          # all ranked I7 signals per bar (pre-ledger)
{env}.intelligence.i8                  # I8 AI narrative metadata per bar (topic_intelligence_i8)
{env}.intelligence.pipeline.dlq        # unparseable bar payloads
{env}.intelligence.signal.dlq          # null-CIS signals caught before publish
{env}.intelligence.signal.audit        # SignalCoverageGapEvent (SignalAuditor)
{env}.intelligence.signal_metrics      # SignalMetricsAnalyzer output
{env}.intelligence.signal.writer.dlq   # SignalWriter failures
{env}.intelligence.transform.graduation       # GraduationAnalyzer output
{env}.intelligence.transform.graduation.dlq   # GraduationWriter failures
{env}.intelligence.shadow              # shadow validation only (temporary, manual inspection)

# Lifecycle
{env}.lifecycle.transitions            # signal lifecycle transition events
{env}.lifecycle.writer.dlq

# LLM
{env}.llm.calls                        # every LLM call (success + failure + counterfactual)
{env}.llm.outcomes                     # signal exits with pnl_r/mae/mfe for back-fill
{env}.llm.writer.dlq

# Narratives
{env}.narratives                       # I8 AI narratives (NarrativeSwarm)
{env}.narratives.group                 # group synthesis narratives

# Swarm / lineage
{env}.swarm.alpha                      # unified alpha multiplier (AlphaSwarm)
{env}.intelligence.signal_lineage      # signal-affecting transforms + agent predictions
{env}.intelligence.signal_lineage.dlq  # failed lineage persistence

# CTX / macro
{env}.ctx.snapshot                     # qualitative context snapshots (ContextWriter consumer)
{env}.macro_signals                    # macro factor signals (MacroAnalyzer)

# Writer DLQs
{env}.bar.writer.dlq
{env}.feature.writer.dlq
{env}.signal.tracker.dlq

# ML
{env}.ml.data_quality.alerts
{env}.ml.discovery.results
{env}.ml.orchestrator.dlq

# Cross-asset
{env}.cross_asset                      # cross-asset spread features (CrossAssetService)

# System
{env}.system.events
{env}.system.health.events             # service health state transitions (ServiceAuditor)
{env}.intelligence.service_auditor.journal.dlq  # escalation DLQ
{env}.alert.requests                   # AlertingAgent dispatch (Telegram/Discord)
{env}.gap_fill.dlq                     # gap-fill requests that exhausted retries
```

### Topic catalog with metadata

**Market data topics**

| Topic | Purpose | Producers | Consumers | Retention |
|-------|---------|-----------|-----------|-----------|
| `{env}.market.bars.raw.ibkr` | IBKR raw 5s RTB + 1m bars | `IBKRProvider` | `ProviderMerger` | 1h |
| `{env}.market.bars` | Canonical 1m bars | `ProviderMerger` | `BarAggregator`, `IntelligencePipeline`, `BarWriter` | 24h |
| `{env}.market.bars.htf` | HTF bars (5m-1d) | `BarAggregatorAgent` | `BarWriter`, `IntelligencePipeline` | 7d |

**Intelligence topics**

| Topic | Purpose | Producers | Consumers | Retention |
|-------|---------|-----------|-----------|-----------|
| `{env}.intelligence.journal` | Full I1-I7 features (BarIntelligenceRecord) | `IntelligencePipelineAgent` | `FeatureWriter`, `FeatureSnapshotWriter`, `ParityAuditor` | 24h |
| `{env}.intelligence.i7.signals` | All ranked I7 signals | `IntelligencePipelineAgent` | `SignalWriter`, `SignalTracker`, `AlphaSwarm` | 7d |

**Lifecycle topics**

| Topic | Purpose | Producers | Consumers | Retention |
|-------|---------|-----------|-----------|-----------|
| `{env}.lifecycle.transitions` | Signal state changes | `SignalTracker` | `LifecycleWriter` | 7d |

**Quality and events**

| Topic | Purpose | Producers | Consumers | Retention |
|-------|---------|-----------|-----------|-----------|
| `{env}.market.data.quality` | Provider quality side-channel | `ProviderMerger` | (future consumers) | 24h |
| `{env}.market.events.gap_requests` | Gap fill requests | `BarAuditor` | (future gap fill service) | 24h |

**DLQ topics**

| Topic | Purpose | Producers | Consumers | Retention |
|-------|---------|-----------|-----------|-----------|
| `{env}.feature.writer.dlq` | Feature writer failures | `FeatureWriter` | `DLQDrainAgent` | 7d |
| `{env}.intelligence.signal.writer.dlq` | Signal writer failures | `SignalWriter` | `DLQDrainAgent` | 7d |
| `{env}.bar.writer.dlq` | Bar writer failures | `BarWriter` | `DLQDrainAgent` | 7d |

**AI/LLM topics**

| Topic | Purpose | Producers | Consumers | Retention |
|-------|---------|-----------|-----------|-----------|
| `{env}.llm.calls` | LLM audit log entries | `NarrativeCompute`, `AlphaSwarm` | `LLMWriter` | 7d |
| `{env}.llm.outcomes` | LLM outcome backfill | `LLMWriter` | (internal) | 1d |

**Cross-asset topics**

| Topic | Purpose | Producers | Consumers | Retention |
|-------|---------|-----------|-----------|-----------|
| `{env}.cross_asset` | Cross-asset spread dynamics | `CrossAssetService` | (future consumers) | 24h |

### Active consumer groups

| Group | Topic | Service | Purpose |
|-------|-------|---------|---------|
| `feature_writer_group` | `intelligence.journal` | `FeatureWriter` | Persist features to DB |
| `signal_writer_group` | `intelligence.i7.signals` | `SignalWriter` | Persist signals to DB |
| `narrative` | `narratives` | `NarrativeSwarm` | Process I8 LLM events |
| `sse-consumer` | Various | API SSE router | Fanout to HTTP clients |

---

## How To Extend

### Adding a new topic

1. Add a `topic_<name>()` function to `src/core/stream_keys.py`. Use the `{env}.{category}.{subcategory}` pattern.
2. If the topic can receive malformed payloads, add a corresponding `topic_<name>_dlq()` function.
3. Update this document's stream key catalog.
4. Create the topic in Redpanda:
   ```bash
   docker exec redpanda rpk topic create dev.<category>.<name> --partitions 1 --replicas 1
   # Set retention (example: 24h)
   docker exec redpanda rpk topic alter-config dev.<category>.<name> --set retention.ms=86400000
   ```
5. Assign a dedicated consumer group — never share a group between two different services.

**Retention conversions:** 1h = 3,600,000 ms | 1d = 86,400,000 ms | 7d = 604,800,000 ms

### Adding a new consumer service

1. Inherit from `BaseAgent` (or `BaseWriter` for DB writers).
2. Subscribe to the topic using a new, exclusive consumer group ID following the naming convention.
3. If the service deserializes external payloads, implement DLQ routing via `_maybe_route_to_dlq`.
4. Register the service in `_DAG_ORDER` in `services/service_auditor.py`.
5. Add a systemd unit file to `production/systemd/` and install to `/etc/systemd/system/`.
6. Emit the mandatory OTel signals via the inherited `BaseAgent` (see CLAUDE.md Phase 108 SOP).

### Producer tuning guide

**High throughput:**
```python
batch_size=32768, linger_ms=50, compression_type="lz4"
```

**Low latency:**
```python
batch_size=16384, linger_ms=0, compression_type="none"
```

**Consumer — reduce lag:**
```python
max_poll_records=200, fetch_min_wait_ms=100
```

**Consumer — memory efficiency:**
```python
max_poll_records=50, fetch_max_bytes=1048576  # 1MB
```

---

## Failure Modes & Operations

### Consumer not receiving messages

```bash
# Verify consumer is registered in the group
docker exec redpanda rpk group list

# Check topic has messages and what offset the consumer is at
docker exec redpanda rpk topic describe <topic> --partition 0
docker exec redpanda rpk group describe <group> --topic <topic>

# Check env prefix is correct — topic must match INDICAGENT_ENV
grep INDICAGENT_ENV .env
docker exec redpanda rpk topic list | grep <expected-prefix>
```

### High consumer lag

```bash
# Identify how far behind the consumer is
docker exec redpanda rpk group describe <group> --topic <topic>

# Check the consumer service is running
systemctl status indicagent-<consumer-service>

# Check for slow DB writes
tail -f logs/<writer>.log | grep "batch written"
```

**Grafana query:**
```promql
persistence_consumer_lag_records{agent_id=~".*-writer"}
```

### DLQ has messages

Messages in a DLQ topic mean a consumer failed to parse a payload. The original bytes are preserved.

```bash
# Inspect DLQ contents
docker exec redpanda rpk topic consume dev.<domain>.<agent>.dlq --from-beginning

# After root cause is fixed, drain the DLQ
# (DLQDrainAgent replays messages back to the source topic)
```

**Grafana query:**
```promql
rate(agent_dlq_total{agent_id="feature_writer"}[5m])
```

### Topic not found

```bash
# List all topics and check for the env prefix
docker exec redpanda rpk topic list | grep <partial-name>

# Recreate if missing (topics are not auto-created in production)
docker exec redpanda rpk topic create <full-topic-name> --partitions 1 --replicas 1
```

### Monitoring — consumer lag (Prometheus/Grafana)

```promql
# Consumer lag by agent
persistence_consumer_lag_records{agent_id=~".*-writer"}

# Messages per second by topic
rate(stream_messages_read_total[5m])
```

### Consumer group management

```bash
# List all consumer groups
docker exec redpanda rpk group list

# Describe a group (shows lag per partition)
docker exec redpanda rpk group describe feature_writer_group --topic dev.intelligence.journal

# Reset offset to reprocess from beginning
docker exec redpanda rpk group reset-offset feature_writer_group --topic dev.intelligence.journal --to-earliest

# Check feature_pipeline lag (from CLAUDE.md cheatsheet)
docker exec redpanda rpk group describe feature_pipeline -t
```

### Topic throughput stats

```bash
docker exec redpanda rpk topic stats <topic-name>
```

---

## See Also

- **Data pipeline (I1-I7 compute):** `docs/data/data-pipeline.md`
- **Data foundation (TimescaleDB tables):** `docs/data/data-foundation.md`
- **Data provider (IBKR integration):** `docs/data/data-provider.md`
- **Stream key source of truth:** `src/core/stream_keys.py`
- **Typed event schemas:** `src/intelligence/schemas.py`
- **Stream schemas reference:** `docs/reference/schemas/stream-schemas.md`
- **Infrastructure operations:** `docs/operations/operations-infrastructure.md`
- **Self-healing and service auditor:** `docs/architecture/self-healing.md`
- **Auth design and ML export API (planned):** `docs/platform-api.md` (planned)
- **Redpanda docs:** https://docs.redpanda.com/

**ADRs 16-19 — cross-domain topics** (these decisions involve other subsystems; their authoritative docs are linked below):

- **ADR-16: LLM audit trail** — every LLM call is a labeled training sample; full design at `docs/intelligence/` (LLM chain, llm_calls hypertable, per-model scoring, outcome back-fill). Design principle: once gone, the outcome cannot be recovered.
- **ADR-17: Historical backfill — replay fidelity tradeoff** — Stage 2 replay writes `source='backfill'`. First ~50 bars have degraded quality (Kalman/GARCH warm-up). Accepted tradeoff. See `docs/data/data-pipeline.md`.
- **ADR-18: ServiceAuditor — pipeline health and self-healing** — monitors all active services, publishes typed health state transitions to `system.health.events`, can trigger restarts on breach of lag/error thresholds. Escalation DLQ: `intelligence.service_auditor.journal.dlq`. See `docs/architecture/self-healing.md`.
- **ADR-19: Roll batch — nightly timer replaces 24/7 daemons** — `production/scripts/roll_batch.py` runs as a nightly systemd timer at 8pm. Detects calendar-based rolls, promotes front-month contracts in `contract_metadata`, broadcasts updates via Kafka. `inactive (dead)` between runs is correct. See `docs/ideas/futures-roll-simplification.md`.

**API-layer ADRs (not streaming concerns — moved to See Also):**

- **Auth design (JWT + API key):** See `platform-api.md` (planned).
- **ML export Parquet endpoint:** See `platform-api.md` (planned).
