# Data Pipeline

**Last Updated:** 2026-03-15

## Overview

IndicAgent's data pipeline is organized into three thermal tiers — **hot**, **warm**, and **cold** — reflecting how quickly data must move and how long it must persist.

```
IBKR TWS ──► Hot (Redpanda Streams) ──► Warm (Processing Services) ──► Cold (TimescaleDB)
               sub-millisecond writes        <10ms per bar                   async batch writes
```

The real-time pipeline **never touches the database directly**. All live processing flows through Redpanda topics. TimescaleDB receives data only after it has been processed by the intelligence pipeline.

---

## Hot Tier: Redpanda Streams

**Purpose:** Ingestion and distribution of raw market data
**Technology:** Redpanda (Kafka-compatible, :19092) — replaced DragonflyDB (Phase 30, 2026-03-14)
**Latency:** Sub-millisecond writes

The `IBKRProviderAgent` (`indicagent-ibkr-provider`) connects to IBKR TWS at `192.168.1.157:7497`, collects 5s real-time bars, and publishes them to `market.bars.raw.ibkr`. The `ProviderMergerAgent` (`indicagent-provider-merger`) consumes all provider raw topics and routes to the canonical `market.bars` topic with automatic primary-silence failover. All topic names are constructed via `src/core/stream_keys.py` and are environment-prefixed.

### Topic Convention

```
{env}.market.bars.raw.{provider}   # Per-provider raw bars (e.g. market.bars.raw.ibkr)
{env}.market.bars                  # Canonical 1m bars from ProviderMergerAgent
{env}.market.bars.htf              # Aggregated HTF bars (5m–1d) from BarAggregatorComputeAgent
{env}.intelligence                 # I1–I7 IntelligenceEvent output (keyed SYMBOL:TF)
{env}.intelligence.i7.signals      # All ranked I7 signals per bar (pre-ledger write)
{env}.signals.aggregated           # I7 CISScorer winner signal
{env}.narratives                   # I8 per-signal AI narrative (keyed SYMBOL:TF)
{env}.llm.calls                    # Every LLM call audit record
{env}.llm.outcomes                 # Signal lifecycle exits with pnl_r/mae/mfe
# Producer: indicant-signal-tracker publishes signal lifecycle outcomes (exit events)
```

Environment prefix is `{env}.` (e.g., `development.` in dev, empty string in production). **Always build topics via `src/core/stream_keys.py`** — never hardcode.

### Consumer Groups

Each service reads its input topics via an exclusive Kafka consumer group. The group offset is tracked by Redpanda, enabling independent progress per service and automatic replay on restart. Consumer group names follow the pattern `<concept>_consumer` (idempotent on restart).

---

## Warm Tier: Processing Services

**Purpose:** Intelligence extraction from raw bars
**Technology:** Python async services, systemd-managed
**Latency:** <10ms per bar per symbol/timeframe

The microservices architecture enforces **Separation of Concerns (SoC)** as an operational invariant: each service owns exactly one responsibility and is deployed, restarted, and scaled independently. Data collection, indicator computation, regime classification, signal generation, lifecycle tracking, persistence, AI narrative, and API delivery are fully decoupled processes — the Redpanda stream bus is the only contract between them.

Each service reads from one or more Redpanda topics, computes intelligence, and writes results back to Redpanda topics. Services are stateful — they maintain plugin state in memory across bars.

### Service Pipeline

| Service | Reads From | Writes To |
|---------|-----------|-----------|
| `indicagent-ibkr-provider` | IBKR TWS (5s real-time bars) | `market.bars.raw.ibkr` |
| `indicagent-provider-merger` | `market.bars.raw.*` | `market.bars` (canonical 1m) |
| `indicagent-bar-aggregator-compute` | `market.bars` | `market.bars.htf` (5m–1d) |
| `indicagent-intelligence-pipeline` | `market.bars` + `market.bars.htf` | `intelligence` + `intelligence.i7.signals` + `signals.aggregated` |
| `indicagent-signal-writer` | `intelligence.i7.signals` | `signal_ledger` (new rows) |
| `indicagent-signal-tracker` | `market.bars` | `signal_ledger` (lifecycle updates) |
| `indicagent-ai-narrative` | `signals.aggregated` | `narratives` + `llm.calls` |
| `indicagent-feature-writer` | `intelligence` | `intelligence_features` (TimescaleDB) |
| `indicagent-llm-writer` | `llm.calls` + `llm.outcomes` | `llm_calls` hypertable + `llm_model_scores` |

### Multi-Stream Reading

Services that monitor 60 instruments × 4 timeframes = 240 topic partitions (varies by active instruments) use a **single consumer group poll** with all topic assignments. This avoids worst-case polling latency from sequential blocking reads.

```python
# AIOKafkaConsumer subscribed to all topics at init
async for msg in self._consumer:
    topic = msg.topic   # e.g. "development.indicators"
    key = msg.key.decode() if msg.key else None  # e.g. "ES:1m"
    payload = json.loads(msg.value)
```

---

## Cold Tier: TimescaleDB

**Purpose:** Long-term storage, ML training data, signal history
**Technology:** PostgreSQL + TimescaleDB extension, :5432, DB `indicagent`
**Write Pattern:** Async batch by `feature_writer_service`

### Tables

| Table | Written By | Purpose |
|-------|-----------|---------|
| `market_data_ohlcv` | `historical_backfill.py` only | Raw OHLCV cold storage — never written by live pipeline |
| `intelligence_features` | `feature_writer_service` | Full feature vectors per bar (tiered JSONB: bar/i1/i3/i4/i5/smc/i6) — ML training dataset |
| `signal_ledger` | `indicant-signal-writer` (new rows) + `indicant-signal-tracker` (lifecycle updates) | I7 signals with lifecycle state, MAE/MFE, 8-class outcome |
| `llm_calls` | `indicant-llm-writer` | Full LLM call audit — request, response, outcome back-filled on signal close |
| `llm_model_scores` | `indicant-llm-writer` (refreshed every 15 min) | Per-model win rate, avg pnl_r, p-value — drives model selection |
| `setup_performance` | weight-updater (nightly) | Per-setup rolling 30d stats — drives I7 signal ranking; only rows with `sample_size >= 30` |

The live pipeline never writes to `market_data_ohlcv` directly. If TWS disconnects, gaps are filled with `historical_backfill.py --days 2`.

### JSONB Codec Requirement

asyncpg requires explicit codec registration for JSONB columns:

```python
await conn.set_type_codec(
    "jsonb",
    encoder=json.dumps,
    decoder=json.loads,
    schema="pg_catalog",
)
```

Without this, asyncpg returns JSONB as raw strings and comparisons like `float <= str` will crash at runtime.

---

## Typed Intelligence Bus

The canonical event type flowing through warm-tier streams is **`IntelligenceEvent`** (`src/intelligence/schemas.py`). It carries all tier outputs in typed JSONB sub-fields:

```python
IntelligenceEvent:
  symbol: str
  timeframe: str
  timestamp: datetime
  i1: dict   # raw indicator values (RSI, MACD, ATR, ...)
  i3: dict   # market structure (swings, S/R, session levels, ...)
  i4: dict   # regime context (volatility state, HMM, Kalman, ...)
  i5: dict   # patterns (divergence, squeeze, chart patterns, ...)
  smc: dict  # smart money concepts (BOS/CHoCH, FVG, order blocks, ...)
  i6: dict   # cross-timeframe confluence scores
```

Downstream plugins read from this single event rather than subscribing to multiple streams. The feature writer persists the entire event to `intelligence_features` as a single row.

---

## Data Flow Summary

```
IBKR TWS
  └─► IBKRProviderAgent (hot)
        └─► market.bars.raw.ibkr
              └─► ProviderMergerAgent
                    └─► market.bars (canonical 1m, hot)
                          ├─► BarAggregatorComputeAgent
                          │     └─► market.bars.htf (5m–1d, hot)
                          │           └─► BarWriterAgent → market_data_ohlcv (cold)
                          └─► IntelligencePipelineComputeAgent (I1–I7 unified, warm)
                                  (also subscribes to market.bars.htf)
                                ├─► intelligence (IntelligenceEvent, keyed SYMBOL:TF)
                                │     ├─► indicant-feature-writer → intelligence_features (cold)
                                │     └─► indicant-ai-narrative (I8, warm)
                                │           ├─► narratives (keyed SYMBOL:TF, hot)
                                │           └─► llm.calls
                                │                 └─► indicant-llm-writer
                                │                       ├─► llm_calls (cold, TimescaleDB)
                                │                       └─► llm_model_scores (cold)
                                └─► intelligence.i7.signals
                                      ├─► indicant-signal-writer → signal_ledger (cold — new rows)
                                      └─► indicant-signal-tracker
                                            └─► signal_ledger (cold — lifecycle updates)
```

---

## Related Documentation

- [DAG Execution](dag-execution.md) — how plugin dependencies are ordered
- [Intelligence Tiers](intelligence-tiers.md) — what each processing stage computes
- [Signal Lifecycle](signal-lifecycle.md) — how signals are tracked after I7 fires them
- **Code:** `src/core/stream_keys.py`, `src/core/stream_utils.py`, `src/core/database_manager.py`
