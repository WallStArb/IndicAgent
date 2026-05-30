# Platform Tech Stack — Decisions, Reasoning, and Migration Path

**Version:** 1.0
**Status:** draft
**Priority:** medium
**Milestone:** future
**Last Updated:** 2026-03-10
**Tags:** tech-stack, redpanda, timescaledb, fastapi, systemd, docker, python, decisions

> **Living document.** Record every significant tech decision here with the reasoning. Future decisions should reference this doc so we don't re-debate resolved questions.

---

## Philosophy: consolidate before expanding

The guiding rule for every stack decision:

> **Exhaust what you already have before adding anything new. Add a new service only when an extension or existing tool provably cannot do the job. The operational cost of running 6 services is dramatically lower than running 12.**

Open source is a hard requirement for everything. No vendor lock-in. Every component must be self-hostable.

---

## Current stack (IndicAgent v1.8, live)

| Layer | Technology | License | Notes |
|-------|-----------|---------|-------|
| Event bus | Redpanda (Kafka-compatible) | Apache 2.0 | Hot + warm tier — migrated Phase 30, 2026-03-14 |
| Time-series DB | PostgreSQL + TimescaleDB | Apache 2.0 (core) | Feature store, signal ledger |
| Services | Python (asyncio) | — | 8 systemd-managed services |
| API | FastAPI | MIT | SSE + REST on :8000 |
| LLM | Ollama + qwen3.5:9b | MIT / Apache | I8 AI narrative |
| Logging | structlog | MIT | Structured JSON logs |
| Metrics | Prometheus (per-service exporters) | Apache 2.0 | Metrics on :9109–:9117 |

1754 tests passing. 167 ruff errors (E501 line-too-long, 64 fixable with --fix). This stack works.

---

## The event bus question: DragonflyDB vs Redpanda

### What DragonflyDB (Redis Streams) is today

DragonflyDB is a Redis-compatible in-memory store. We use it two ways:

1. **Streams** (XADD / XREADGROUP) — the entire event bus, hot and warm tier. Every service publishes and consumes via Redis Streams. This includes OHLCV bars from the TWS daemon — bars are published to `market:SYMBOL:TF` streams, not stored as key/value. Full stream inventory:

| Stream key | Tier | Publisher → Consumer |
|-----------|------|---------------------|
| `ticks:SYMBOL:live` | Hot | TWS daemon → IndicAgent |
| `market:SYMBOL:TF` | Hot | TWS daemon → indicator_service |
| `indicators:SYMBOL:TF` | Warm | indicator_service → market_analysis_service |
| `intelligence:SYMBOL:TF` | Warm | market_analysis_service → signal_generator, ai_narrative, feature_writer |
| `intelligence_i7:SYMBOL:TF` | Warm | signal_generator → market_analysis_service |
| `intelligence_i8:SYMBOL:TF` | Warm | ai_narrative → market_analysis_service |
| `signals:SYMBOL:TF` | Warm | signal_generator → signal_lifecycle |
| `signals:SYMBOL:TF:aggregated` | Warm | signal_generator → API/SSE |
| `narratives:SYMBOL:TF` | Warm | ai_narrative → API/SSE |

2. **Key/value** (HSET / HGET) — one operation only: `price:SYMBOL:latest` — the current bid/ask snapshot written by the TWS daemon, read by `signal_generator_service` at signal-generation time to get the live spread. This is NOT a stream.

**The bar aggregation pipeline** (important — IBKR only provides 1m bars in real-time):

```
IBKR TWS daemon
  └─→ market:SYMBOL:1m     (1m bars, Redis Stream)
  └─→ ticks:SYMBOL:live    (raw ticks, Redis Stream)
  └─→ price:SYMBOL:latest  (live bid/ask, Redis HASH — not a stream)

timeframes_builder_service  (dedicated aggregation service)
  ← consumes market:SYMBOL:1m
  └─→ market:SYMBOL:5m
  └─→ market:SYMBOL:15m    (aggregates 1m → all higher TFs via OHLCV rolling windows)
  └─→ market:SYMBOL:1h
  └─→ market:SYMBOL:4h
  └─→ market:SYMBOL:1d

indicator_service ← subscribes to the relevant TF streams per configured timeframes
signal_generator  ← reads price:SYMBOL:latest HASH for live bid/ask at signal time
```

The stream abstraction is well-contained in two files:
- `src/core/stream_utils.py` — 51 lines: consumer group creation/reset
- `src/core/stream_keys.py` — 136 lines: all stream name construction and MAXLEN policies

### The real limitations of Redis Streams as the platform grows

| Limitation | Impact today | Impact with 6 products |
|-----------|-------------|------------------------|
| **No durable replay** | Low — one product, services rarely restart | High — if QualAgent misses `intelligence:*` events while restarting, it can't catch up |
| **In-memory only** | Low — service restart is fine, just skip backlog | High — cross-product state reconstruction is impossible without replay |
| **No schema enforcement** | Low — internal to one codebase | High — 6 products publishing to the same bus without contracts is chaos |
| **MAXLEN trimming** | Managed via `get_stream_maxlen()` — works | Harder to reason about when 6 publishers are trimming streams |
| **Single node** | Fine for current volume | No built-in replication, no partitioned consumers |

The `ensure_consumer_group_with_reset()` function — which resets to current tail (`$`) on restart — is a workaround for the lack of durability. It deliberately **skips the backlog**. That is fine for IndicAgent (we just resume from the current bar) but is a problem when QualAgent needs to process every `intelligence:*` event to build its regime state.

### Redpanda — why it beats Apache Kafka for us

Kafka is the gold standard for durable event streaming. Redpanda is Kafka-compatible but simpler to operate:

| | Apache Kafka | Redpanda |
|---|---|---|
| **API** | Kafka protocol | Kafka protocol (100% compatible) |
| **Architecture** | JVM, requires ZooKeeper or KRaft | C++ single binary, no ZooKeeper ever |
| **Latency** | ~5–15ms | ~1–5ms |
| **Deployment** | Complex cluster setup | Single binary for dev; simple cluster for prod |
| **License** | Apache 2.0 | Apache 2.0 (BSL for some enterprise features, core is fully open) |
| **Operational overhead** | High | Low — single process, Prometheus metrics built in |
| **Kafka compatibility** | Native | 100% compatible — same client libraries |

For us: **same Kafka client code, dramatically simpler to run**. No ZooKeeper, no JVM GC tuning, no Kafka broker configuration sprawl. Redpanda runs as a single binary locally for development and as a 3-node cluster for production.

### What Redpanda gives us that DragonflyDB doesn't

**Durable, replayable log.** Every event is persisted to disk with configurable retention (days/weeks). A service that restarts can replay from its last committed offset — it misses nothing.

**True consumer group offsets.** In Redis Streams, we reset to `$` (tail) on restart to avoid stale backlog. In Kafka/Redpanda, each consumer group tracks its offset per partition. On restart, it resumes from exactly where it left off. `ensure_consumer_group_with_reset()` disappears as a concept.

**Topic + partition model.** One topic per stream type (`intelligence`, `signals`, `qual.regime`), partitioned by `SYMBOL:TF` as the message key. All events for `ES:5m` land on the same partition — ordering guaranteed per instrument. Wildcard subscriptions via topic prefix patterns.

**Schema registry.** Redpanda ships with a built-in schema registry (compatible with Confluent Schema Registry API). Stream contracts are enforced — a producer can't publish a malformed event.

**Cross-product replay for free.** When DerivAgent subscribes to `intelligence` for the first time, it can start from offset 0 and process every historical event. This enables zero-touch bootstrap of new products.

### Redpanda only — start clean, add DragonflyDB when a real trigger exists

**The decision: Redpanda is the only event bus. DragonflyDB is not in the initial target stack.**

The one remaining non-stream use (the `price:SYMBOL:latest` hash) is replaced with in-process state in signal_generator:

```python
# signal_generator — replace HGETALL with in-process dict
self._live_quotes: dict[str, dict] = {}

async def _on_tick(self, symbol: str, bid: float, ask: float):
    self._live_quotes[symbol] = {"bid": bid, "ask": ask}

def _get_spread(self, symbol: str) -> dict:
    return self._live_quotes.get(symbol, {"bid": None, "ask": None})
```

**Target infrastructure: two components.**

```
Redpanda        → ALL streams
                  hot tier:  market.ticks, market.bars (1m + aggregated TFs)
                  warm tier: indicators, intelligence, signals, narratives
                  future:    qual.*, deriv.*, execution.*, portfolio.*, risk.*

PostgreSQL      → Cold tier
+ TimescaleDB     feature store, signal ledger, historical data, continuous aggregates
+ pgvector        vector search — regime analogs, vol surface matching (extension, no new service)
```

DragonflyDB has well-defined roles where it is the right tool — see "When to add DragonflyDB" below. None of those triggers apply to the current platform. Start simple. Add it when a trigger is real and measurable.

### Why Redpanda for BOTH hot AND warm — not just one

This is the right question. The hot/warm distinction is **conceptual** (raw data vs processed intelligence), not an infrastructure distinction. Both tiers benefit equally from durability and replay.

The reasons I initially suggested keeping DragonflyDB for warm:
- "Warm data is current state, not event log" — but current state is just the latest event. A Kafka **compacted topic** gives you the latest value per key, identical semantics.
- "Kafka has more latency than Redis" — Redpanda is ~1–5ms per message. For intelligence signals that take 10–100ms to compute, the bus latency is irrelevant.

**The clean answer: Redpanda handles both hot and warm. DragonflyDB remains as the key/value cache only.**

```
Redpanda topics        → all event streams (hot + warm + execution + portfolio + risk)
DragonflyDB            → key/value cache only: current bid/ask, session state, rate limits
TimescaleDB            → cold tier: feature store, signal ledger, historical data
```

This is a clean separation of concerns:
- **Redpanda** = the event log (append-only, durable, replayable)
- **DragonflyDB** = the materialized state cache (latest value, fast lookup)
- **TimescaleDB** = the institutional memory (queryable history, ML training data)

### Kafka topic design for our stream namespace

Redis uses one stream per symbol/TF: `development:intelligence:ES:5m`  
Kafka uses one topic per stream type, message key = `SYMBOL:TF`:

```
Topic: dev.market.bars         Key: ES:5m      → all bars for ES 5m partition together
Topic: dev.market.ticks        Key: ES         → raw tick stream
Topic: dev.indicators          Key: ES:5m      → indicator payloads
Topic: dev.intelligence        Key: ES:5m      → I1-I8 IntelligenceEvent
Topic: dev.signals             Key: ES:5m      → I7 signals
Topic: dev.signals.aggregated  Key: ES:5m      → aggregated I7 signal
Topic: dev.narratives          Key: ES:5m      → I8 AI narrative

Future products:
Topic: dev.qual.regime         Key: ES         → QualAgent regime state
Topic: dev.qual.score          Key: GLOBAL     → QualScore
Topic: dev.deriv.vol_regime    Key: ES         → DerivAgent vol regime
Topic: dev.execution.fills     Key: ACCOUNT    → TradeAgent/DerivAgent fills
Topic: dev.portfolio.state     Key: ACCOUNT    → PrimeAgent portfolio state
Topic: dev.risk.alerts         Key: ACCOUNT    → AegisAgent risk alerts
```

Per-symbol/TF topics (Option B) would create hundreds of topics as we add instruments and timeframes. Option A (topic per type, key for routing) is the standard Kafka pattern and the right design.

---

## How hard is the DragonflyDB → Redpanda migration? (Now vs Later)

### What migrates vs what stays

| Key | Current type | Migration target |
|-----|-------------|-----------------|
| `ticks:SYMBOL:live` | Redis Stream | → Redpanda topic `dev.market.ticks` |
| `market:SYMBOL:TF` | Redis Stream | → Redpanda topic `dev.market.bars` |
| `indicators:SYMBOL:TF` | Redis Stream | → Redpanda topic `dev.indicators` |
| `intelligence:SYMBOL:TF` | Redis Stream | → Redpanda topic `dev.intelligence` |
| `intelligence_i7:SYMBOL:TF` | Redis Stream | → Redpanda topic `dev.intelligence.i7` |
| `intelligence_i8:SYMBOL:TF` | Redis Stream | → Redpanda topic `dev.intelligence.i8` |
| `signals:SYMBOL:TF` | Redis Stream | → Redpanda topic `dev.signals` |
| `signals:SYMBOL:TF:aggregated` | Redis Stream | → Redpanda topic `dev.signals.aggregated` |
| `narratives:SYMBOL:TF` | Redis Stream | → Redpanda topic `dev.narratives` |
| `price:SYMBOL:latest` | Redis Hash (key/value) | **Stays in DragonflyDB** — only true key/value operation |

All stream keys share message key = `SYMBOL:TF` for partition routing. Every event for `ES:5m` lands on the same partition — ordering guaranteed per instrument.

### What actually needs to change in code

The stream abstraction is centralized. Only these files need rewriting:

| File | Lines | Change required |
|------|-------|----------------|
| `src/core/stream_utils.py` | 51 | Replace `XGROUP_CREATE`/`XGROUP_SETID` with Kafka consumer group management via `aiokafka`. Consumer group creation is implicit in Kafka — just subscribe and commit offsets. |
| `src/core/stream_keys.py` | 136 | Replace Redis key builders with Kafka topic + message key helpers. `get_stream_maxlen()` becomes Kafka topic retention config. |
| `requirements.txt` | — | Add `aiokafka`. Remove Redis stream dependency (keep `redis.asyncio` for key/value operations). |
| 8 service files | ~20–50 lines each | Update stream publish/consume calls to use new Kafka-based stream utilities. The business logic doesn't change — only the transport layer. |
| Test fixtures | — | Replace Redis stream fixtures with Kafka/Redpanda test fixtures. |

### Estimated effort

**1–2 weeks** for a careful migration with full test coverage. This is bounded and predictable.

The business logic — the I1–I8 pipeline, the plugins, the intelligence schemas, the signal ledger — **does not change at all**. Only the transport layer changes.

### Why now is actually the best time to migrate

| Factor | Now (IndicAgent only) | After QualAgent is built |
|--------|----------------------|--------------------------|
| **Products to migrate** | 1 | 2+ |
| **Services to update** | 8 | 16+ |
| **Cross-product stream contracts** | None yet | Already established on DragonflyDB — breaking change |
| **Test coverage** | 1083 tests to verify | More tests, more surface area |
| **Risk of split architecture** | N/A | QualAgent built on Kafka while IndicAgent on Redis — messy |

The window to migrate cleanly is **now**. The moment QualAgent starts consuming `intelligence:*` streams from DragonflyDB, you have two products to migrate simultaneously. Build QualAgent on Redpanda from day one.

### Migration is NOT urgent today

IndicAgent is live and working. Don't migrate mid-feature work. The right trigger is: **before building QualAgent**, not before the next IndicAgent release.

---

## Database strategy: PostgreSQL is the Swiss Army knife

### TimescaleDB — keep, no changes

TimescaleDB is the right tool for the feature store. Hypertables, continuous aggregates, compression, and time-based partitioning are exactly what the cold tier needs. It is working well (1083 tests, feature store active). This is not a problem to solve.

### pgvector — add to existing PostgreSQL, zero new infra

pgvector is a PostgreSQL extension (MIT license). It adds a `vector` column type and approximate nearest-neighbor search operators. Supabase ships it by default. Wires into existing PostgreSQL — no new service, no new database.

**Concrete use cases in our platform:**

```sql
-- QualAgent: store embedded regime state per bar
CREATE TABLE regime_embeddings (
    ts         TIMESTAMPTZ NOT NULL,
    symbol     TEXT NOT NULL,
    embedding  vector(384),      -- small embedding model output
    state      JSONB             -- full regime state for context
);
SELECT * FROM regime_embeddings
ORDER BY embedding <=> $current_embedding   -- cosine distance
LIMIT 5;
-- → "here are the 5 historical moments most similar to right now"
```

Use cases:
- **QualAgent regime analog matching** — "what did the market do the last 5 times macro + sentiment + positioning looked like this?"
- **DerivAgent vol surface pattern matching** — "when has the vol surface shape been similar to today's? What happened to the underlying?"
- **TradeAgent lead agent context** — feed the LLM the 3 most historically similar regime states + outcomes as few-shot context

pgvector handles up to ~1M vectors efficiently. Only consider Qdrant if queries become measurably slow at large scale.

### TimescaleDB continuous aggregates vs ClickHouse

The "add ClickHouse for analytics" recommendation was over-engineering. TimescaleDB continuous aggregates are pre-computed materialized views that update automatically. For learning loop queries ("win rate by regime state over 18 months"), they are fast enough and require zero new infrastructure.

Add ClickHouse only if:
1. Learning loop queries are provably slow on TimescaleDB, AND
2. Continuous aggregates don't solve the specific query pattern

That moment probably arrives at 3+ years of data across 6 products — not a near-term concern.

### DuckDB — for research notebooks, not infrastructure

DuckDB (MIT, embedded) is excellent for ad-hoc backtesting and research. It runs in-process, queries Parquet exports natively, and has excellent Python integration. Install it as a development dependency for data exploration and backtesting notebooks. Do not run it as infrastructure.

---

## Workflow orchestration: LangGraph + APScheduler

### LangGraph (already in stack)

LangGraph handles stateful multi-step agent workflows — the strategy bot lifecycle (check regime → size → enter → monitor → exit → record) is a LangGraph graph with persistent state. This is already the design intent of the codebase. No new service needed.

### APScheduler (Python library, zero infra)

For scheduled triggers (run at 9:45 ET every weekday), APScheduler is a Python library that runs inside the service process. Zero infrastructure, minimal setup, battle-tested.

### When to consider Temporal

**Important:** Temporal is NOT a library. It is a server (separate process, requires PostgreSQL or Cassandra) plus an SDK. It carries real operational overhead — another service to run, monitor, and recover.

| | LangGraph + APScheduler | Temporal |
|---|---|---|
| **Infrastructure** | Zero — libraries in your process | Temporal server + DB required |
| **Workflow durability** | State lives in memory | Server persists state — survives crashes |
| **Long-running workflows** | You manage restarts manually | Server resumes from exact failed step |
| **Retry logic** | You write it | Built-in, declarative |
| **Visibility** | Your logs | Full workflow history UI, execution timeline |
| **Concurrency** | Bounded by your process | Designed for millions of concurrent workflows |

Temporal is the right tool when:
- Hundreds of concurrent strategy workflows are running simultaneously across many accounts
- Workflow state must survive service restarts across **multi-day or multi-week** sequences (e.g., a 21-day theta decay strategy)
- A workflow failure mid-execution requires guaranteed resumption from the exact failed step
- A full audit trail of every workflow decision is required (regulatory or risk management)

For bar-based strategy bots that complete in minutes to hours on a single machine, LangGraph is sufficient. The moment a real production crash shows that a strategy workflow died mid-execution and lost state — that's the trigger to evaluate Temporal.

That moment arrives at institutional scale. Not in the near term.

---

## Observability: Prometheus + Grafana

Prometheus is already deployed per-service (metrics ports :9109–:9116). Adding Grafana is one Docker container and a Prometheus data source connection. Grafana is Apache 2.0, single binary, and directly reads Prometheus metrics.

Consider adding **Loki** (Grafana's log aggregation system, Apache 2.0) alongside Grafana for structured log aggregation from all services. Loki + Grafana means one dashboard for both metrics and logs.

---

## What we are NOT adding (and why)

| Technology | Why we're not adding it |
|-----------|------------------------|
| **Apache Kafka** | Redpanda is 100% Kafka-compatible with dramatically lower operational overhead. If we go Kafka-compatible, we go Redpanda. |
| **Elasticsearch / OpenSearch** | pgvector + pg_trgm cover search within PostgreSQL. No separate search cluster. |
| **Qdrant / Weaviate / Milvus** | pgvector first. Only if pgvector is measurably insufficient. |
| **ClickHouse** | TimescaleDB continuous aggregates cover the analytics use case. Add ClickHouse only when proven necessary. |
| **Temporal** | LangGraph + APScheduler cover the near-term workflow use case. Temporal is the institutional-scale upgrade. |
| **MinIO** | Add only when object storage is actually needed (model artifacts, bulk exports). Not a current requirement. |
| **MongoDB / Cassandra** | PostgreSQL with TimescaleDB handles the data model. No need for a document or wide-column store. |
| **RabbitMQ / ActiveMQ / SQS** | No traditional message queue needed. Redpanda consumer groups handle work distribution. The one request/reply use case (AegisAgent pre-trade check) is better served by a direct HTTP call — not a queue. See below. |

---

## Redpanda is not a message queue — and that's fine

Redpanda (Kafka model) and traditional MQs (RabbitMQ, SQS) are different tools:

| | Redpanda / Kafka | Traditional MQ |
|---|---|---|
| **Message lifecycle** | Retained in log until retention period expires | Deleted after consumer acknowledges |
| **Multiple consumers** | Each consumer group reads all messages independently | One consumer per message (point-to-point) |
| **Replay** | Any consumer group can seek to any offset and replay | No replay — once consumed, gone |
| **Best for** | Event streaming, pub/sub, data pipelines | Task queues, work distribution, RPC |

**Consumer groups give queue-like distribution.** Within a single consumer group, messages are distributed across consumers — each message processed by exactly one consumer in the group. This handles multi-instance service scaling without a separate MQ.

**The one genuinely queue-like pattern in our platform: pre-trade check.**

AegisAgent's pre-trade check is a **request/reply** pattern — TradeAgent needs a synchronous answer before proceeding. Kafka/Redpanda wasn't designed for this. Options:

1. **Correlation ID pattern on Redpanda** — works but adds complexity (publish request, filter response by correlation ID)
2. **Direct HTTP call to AegisAgent API** ✅ — synchronous, simple, correct tool for a blocking request

**Decision: pre-trade check is HTTP, not bus.**

> The bus is for **events** (things that happened, many consumers, async).  
> HTTP is for **requests** (I need an answer right now, one caller, one responder).

This principle applies platform-wide: intelligence signals, regime states, fills, portfolio updates → bus. Pre-trade checks, configuration reads, health checks → HTTP.

---

## Recommended full stack

| Layer | Technology | Status | Notes |
|-------|-----------|--------|-------|
| **Event bus** | **Redpanda** | **Live** (Phase 30, 2026-03-14) | Replaced all DragonflyDB streams |
| **Key/value cache** | ~~DragonflyDB~~ → in-process | **Done** (Phase 30) | `price:SYMBOL:latest` replaced by signal_generator `_live_quotes` dict |
| **Time-series DB** | **TimescaleDB** | Live, keep | Feature store, signal ledger |
| **Vector search** | **pgvector** | Add with QualAgent | PostgreSQL extension, zero new infra |
| **Workflows** | **LangGraph + APScheduler** | Add with strategy bots | LangGraph already in stack; APScheduler is a library |
| **Observability** | **Prometheus + Grafana** | Near-term | Grafana is one Docker container |
| **OLAP analytics** | TimescaleDB continuous aggregates | Use now | Available today; only consider ClickHouse when provably needed |
| **Service APIs** | **FastAPI** (existing) | Live, keep | Pre-trade checks and config calls go here, not through the bus |
| **DragonflyDB** | *(conditional, see triggers)* | Add when triggered | Tick SaaS fan-out, options chain state (DerivAgent), or scale fan-out |

**Target infrastructure: Redpanda + PostgreSQL (TimescaleDB + pgvector).** Two components. DragonflyDB added only when a specific trigger is real. Everything is open source and self-hostable.

---

## When to add DragonflyDB — three specific triggers

DragonflyDB is the right tool for certain problems. None of those problems exist yet. When one of the three triggers below is real and measurable, add DragonflyDB for that specific role. It does not replace Redpanda — it complements it for the use cases where RAM-primary, sub-ms access is the correct model.

### The performance difference (evaluated and documented)

| | DragonflyDB | Redpanda |
|---|---|---|
| **Typical latency** | < 1ms (~0.3–0.5ms) | 5–15ms |
| **P99 tail latency** | ~1–2ms under heavy load | 10–25ms |
| **Architecture** | Multi-threaded, shared-nothing | Thread-per-core, C++ |
| **Storage** | RAM-primary (snapshots to disk) | NVMe/SSD append-only log |
| **Max throughput** | 4M–15M+ ops/sec (single node) | GB/s+ (disk-bound) |
| **Fan-out model** | Push (pub/sub) — all subscribers receive immediately | Pull (consumer poll) — each consumer polls independently |

### Trigger 1 — Tick streaming SaaS tier

**When:** A paid subscription tier offers live tick/quote streaming to external subscribers and < 5ms delivery matters commercially.

**Why DragonflyDB:** Redpanda's pull model requires each external subscriber to poll independently. DragonflyDB's pub/sub is a push model — one publish event delivers to all N subscribers simultaneously with < 1ms fan-out. At 1000+ concurrent subscribers all wanting tick data, this is the correct architecture.

**Important context:** The current tick publisher (`async_tick_publisher.py`) already introduces up to 30ms batching delay by design. True sub-5ms tick streaming requires a dedicated DragonflyDB pub/sub path bypassing the adaptive batcher — it is a distinct product feature, not just an infrastructure change.

```
IBKR tick → DragonflyDB pub/sub channel
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼          < 2ms total
   SSE client  SSE client  SSE client
        │
  (fan-out service subscribes to channel,
   broadcasts to N connected SSE clients)

Bar/intelligence pipeline → Redpanda (unchanged)
```

**Trigger:** Tick streaming tier is defined as a product feature and user count makes Redpanda fan-out latency a real user complaint.

---

### Trigger 2 — DerivAgent options chain state store

**When:** DerivAgent is built and requires a high-speed, randomly-accessible store for full options chain state.

**Why DragonflyDB:** An SPX options chain alone is 20,000+ contracts (100 expiries × 200+ strikes), each with bid/ask/IV/Greeks/OI. Vol surface construction and GEX computation require random access by strike and expiry — "give me all contracts expiring March 21" — not sequential log reads. This is a key/value lookup workload, not a streaming workload.

```
External feed (Polygon / CBOE / IBKR)
    │
    └→ DragonflyDB (options chain state store)
         key: chain:{SYMBOL}:{strike}:{expiry}
         value: {bid, ask, iv, delta, gamma, theta, vega, oi}
         → sub-ms random access for vol surface fitting
         → sub-ms access for GEX computation across all strikes

         Chain data is ephemeral — no replay of 3-month-old option quotes needed.

DerivAgent outputs → Redpanda (derived signals only):
    deriv.vol_regime, deriv.gex, deriv.vrp, deriv.skew
```

Nobody else needs the raw chain data. Only DerivAgent's analytics read it. Derived signals go to Redpanda.

**Trigger:** DerivAgent is being built and options chain access patterns are confirmed.

---

### Trigger 3 — High-scale Redpanda consumer fan-out bottleneck

**When:** SaaS user count reaches a level where thousands of concurrent Redpanda consumers create measurable CPU/memory overhead on the Redpanda cluster.

**Why DragonflyDB:** Redpanda was designed for high throughput with moderate consumer counts. Thousands of persistent consumer connections each polling independently creates overhead that grows linearly. DragonflyDB pub/sub is designed for exactly this fan-out pattern.

**Architecture when triggered:**
```
Redpanda → ONE internal fan-out service (single consumer)
                │
                └→ DragonflyDB pub/sub channel
                            │
                  N external subscribers (push delivery)
```

**Trigger:** Monitoring shows Redpanda consumer connection overhead is measurable at current scale. Not a concern before thousands of concurrent subscribers.

---

### Summary: Redpanda and DragonflyDB are complementary, not competing

| Role | Tool | Why |
|------|------|-----|
| Inter-product event bus (durable, replayable) | **Redpanda** | Log model, consumer groups, replay |
| Hot tick buffer for streaming SaaS tier | **DragonflyDB** (Trigger 1) | Sub-ms push fan-out |
| Options chain state store (DerivAgent) | **DragonflyDB** (Trigger 2) | RAM-primary key/value, random access |
| External subscriber fan-out at scale | **DragonflyDB** (Trigger 3) | Pub/sub push model, millions of connections |

Start with Redpanda only. Add DragonflyDB when a trigger is real.

---

## ML Agent Stack (MLAgent — v1.8+)

See full design: `docs/ideas/ml-learning-machine.md`

### Agent Infrastructure

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Orchestration | LangGraph (already in stack) | Supervisor + domain agent state machines |
| Agent observability | **LangFuse** (self-hosted Docker) | Traces every agent step, LLM call, tool invocation. OpenTelemetry bridge → existing Grafana. |
| LLM output validation | **guardrails-ai** | Validates Discovery Agent + Narrative Agent outputs against Pydantic schemas before persistence |
| Model registry | **MLflow** (self-hosted Docker) | Experiment tracking, model versioning, artifact storage. Replaces hand-rolled filesystem approach. |
| HITL | LangGraph `interrupt()` + dashboard UI | Pauses graph at decision points, waits for human approval with 4h timeout |

### ML / Statistics

| Package | Purpose | Phase |
|---------|---------|-------|
| `scipy` | IC analysis, KS drift test, significance | 1 |
| `alphalens-reloaded` | Quant-standard IC/factor analysis (IC, ICIR, decay, turnover) | 1 |
| `evidently` | Drift detection + ML monitoring reports. Self-hosted. | 1 |
| `tsfresh` | Auto time series feature extraction — 700+ features from any series | 1 |
| `polars` | Rust dataframes, 10-100× faster than pandas for batch feature matrix jobs | 1 |
| `lightgbm` | The model — tabular data champion, fast, handles categoricals | 2 |
| `shap` | TreeSHAP explainability — why did the model score this signal? | 2 |
| `optuna` | Hyperparameter optimisation — Bayesian search | 2 |
| `statsmodels` | CUSUM changepoint detection, time series stats | 2 |
| `river` | Online/incremental learning — model adapts continuously without full retrain | 3 |

### What NOT to add
- **PyTorch/TensorFlow** — overkill for tabular signal scoring; tree ensembles dominate tabular benchmarks
- **Ray/Dask** — overkill for our data volume; polars + pandas is sufficient
- **Feast** — TimescaleDB IS our feature store; no additional feature store needed
- **Weights & Biases** — paid cloud; MLflow is the open source standard
- **Temporal** — institutional-scale workflow orchestration; LangGraph is sufficient until multi-product scale

### Inter-Agent Communication (ML topics)
Over Redpanda topics (migration complete as of Phase 30, 2026-03-14):
```
ml.discovery.completed    → Orchestrator routes to Training Agent
ml.drift.detected         → Orchestrator evaluates retrain
ml.model.shadow_ready     → Orchestrator begins shadow evaluation
ml.model.promoted         → signal_generator reloads CIS weights
ml.hitl.response          → Orchestrator resumes paused graph
```

---

## Decision log

| Date | Decision | Reasoning |
|------|---------|-----------|
| 2026-03-10 | LangFuse over LangSmith for agent observability | Self-hosted, open source, full data ownership. LangSmith is cloud/paid. Renaissance demands no vendor lock-in on intelligence data. |
| 2026-03-10 | LightGBM over XGBoost | Faster training, better on smaller datasets, handles categoricals natively. Both are good; LightGBM wins on our scale. |
| 2026-03-10 | guardrails-ai for LLM output validation | Pydantic schemas already in stack; guardrails-ai adds runtime enforcement on LLM agent outputs. Prevents hallucinated feature names, invalid decisions reaching the DB. |
| 2026-03-10 | tsfresh for feature discovery | Automatically extracts 700+ statistical features from time series. Feeds IC analysis — lets the data tell us what matters rather than hand-engineering features. Very Renaissance. |
| 2026-03-10 | alphalens-reloaded for IC analysis | Quant-standard tool for factor evaluation. IC, ICIR, decay, turnover. Purpose-built for our use case. Replaces hand-rolling scipy.pearsonr loops. |
| 2026-03-10 | Deterministic Orchestrator, LLM only in Discovery + Narrative agents | Production decisions (retrain Y/N, promote Y/N) cannot be non-deterministic. LLM creativity belongs in research/interpretation, not in rules that govern live capital. |
| 2026-03-10 | HITL via LangGraph interrupt() + dashboard | Pause-and-wait for borderline decisions. Default-safe action on timeout (reject promotion, maintain status quo). Full audit trail. |
| 2026-03-04 | Redpanda replaces all DragonflyDB streams (migrate before QualAgent) | Durable replay, consumer offsets, schema registry, cross-product stream contracts. Now is the lowest-friction migration window — one product, 8 services, no established cross-product contracts yet. |
| 2026-03-04 | DragonflyDB dropped from initial target stack | Remaining use (`price:SYMBOL:latest` hash) replaced with in-process state in signal_generator. Start simple: Redpanda + PostgreSQL. Add DragonflyDB when a specific trigger is real (tick SaaS fan-out, DerivAgent options chain, or scale fan-out bottleneck). |
| 2026-03-04 | Redpanda for BOTH hot and warm tiers | The hot/warm distinction is conceptual, not infrastructural. Both benefit from durability and replay. Single streaming system is simpler to operate. |
| 2026-03-04 | pgvector over Qdrant | Zero new infra, already in PostgreSQL, sufficient for near-term scale. |
| 2026-03-04 | No ClickHouse yet | TimescaleDB continuous aggregates are sufficient. Add ClickHouse only when provably needed. |
| 2026-03-04 | LangGraph + APScheduler over Temporal | LangGraph already in stack. APScheduler is a library. Temporal is the institutional-scale upgrade path. |
| 2026-03-04 | No message queue (RabbitMQ etc.) | Redpanda consumer groups handle work distribution. No traditional MQ patterns in our use cases. |
| 2026-03-04 | Pre-trade check via HTTP not bus | Request/reply patterns (need an answer now, one caller, one responder) belong on HTTP. The bus is for events (async, many consumers). AegisAgent exposes a FastAPI endpoint for pre-trade checks. |
