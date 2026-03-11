# Data Pipeline

**Last Updated:** 2026-03-11

## Overview

IndicAgent's data pipeline is organized into three thermal tiers — **hot**, **warm**, and **cold** — reflecting how quickly data must move and how long it must persist.

```
IBKR TWS ──► Hot (DragonflyDB Streams) ──► Warm (Processing Services) ──► Cold (TimescaleDB)
               sub-millisecond writes        <10ms per bar                   async batch writes
```

The real-time pipeline **never touches the database directly**. All live processing flows through Redis streams. TimescaleDB receives data only after it has been processed by the intelligence pipeline.

---

## Hot Tier: DragonflyDB Streams

**Purpose:** Ingestion and distribution of raw market data
**Technology:** DragonflyDB (Redis-compatible, :6379)
**Latency:** Sub-millisecond writes

The TWS Daemon (`indicagent-tws`) connects to IBKR at `10.0.0.33:7497` and writes completed bars to Redis Streams as they arrive. All stream keys are constructed via `src/core/stream_keys.py` and are environment-prefixed.

### Stream Key Convention

```
{env}:indicators:{SYMBOL}:{TF}          # I1+I2 indicator output
{env}:intelligence:{SYMBOL}:{TF}        # I3–I6 typed IntelligenceEvent
{env}:signals:{SYMBOL}:{TF}:aggregated  # I7 CISScorer aggregated signal
{env}:narratives:{SYMBOL}:{TF}          # I8 per-signal AI narrative
{env}:llm_calls:stream                  # Every LLM call audit record (maxlen=500)
{env}:llm_outcomes:stream               # Signal lifecycle exits with pnl_r/mae/mfe (maxlen=200)
```

Environment prefix is set by `INDICAGENT_ENV` (e.g., `development:` in dev, no prefix in production). **Always build keys via `src/core/stream_keys.py`** — never hardcode.

### Consumer Groups

Each service reads its input streams via an exclusive consumer group. The consumer group tracks what each service has processed, enabling independent progress per service and automatic replay after restart.

**Gotcha:** `xgroup_create(..., "$")` silently fails when the group already exists and leaves the stream position at its current offset. Use `ensure_consumer_group_with_reset()` from `src/core/stream_utils` to safely initialize or reset consumer groups.

---

## Warm Tier: Processing Services

**Purpose:** Intelligence extraction from raw bars
**Technology:** Python async services, systemd-managed
**Latency:** <10ms per bar per symbol/timeframe

Each service reads from one or more Redis streams, computes intelligence, and writes results back to Redis streams. Services are stateful — they maintain plugin state in memory across bars.

### Service Pipeline

| Service | Reads From | Writes To |
|---------|-----------|-----------|
| `indicagent-indicator` | IBKR bar streams | `indicators:SYMBOL:TF` |
| `indicagent-market-analysis` | `indicators:SYMBOL:TF` | `intelligence:SYMBOL:TF` |
| `indicagent-signal-generator` | `intelligence:SYMBOL:TF` | `signals:SYMBOL:TF:aggregated` + `signal_ledger` (new rows) |
| `indicagent-signal-lifecycle` | `market:SYMBOL:1m` | `signal_ledger` (lifecycle updates) + `llm_outcomes:stream` |
| `indicagent-ai-narrative` | `signals:SYMBOL:TF:aggregated` | `narratives:SYMBOL:TF` + `llm_calls:stream` |
| `indicagent-feature-writer` | `intelligence:SYMBOL:TF` | `intelligence_features` (TimescaleDB) |
| `indicagent-llm-writer` | `llm_calls:stream` + `llm_outcomes:stream` | `llm_calls` hypertable + `llm_model_scores` |

### Multi-Stream Reading

Services that monitor 24 contracts × 4 timeframes = 96 streams (varies by active contracts) use a **single `xreadgroup` call** with all stream names in one dict. This avoids worst-case polling latency from sequential blocking reads.

```python
all_streams = {name: ">" for name in self._stream_map}  # built once at init
messages = await self.redis_client.xreadgroup(
    group, consumer, all_streams, count=10, block=1000
)
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
| `signal_ledger` | `signal_generator_service` (new rows) + `signal_lifecycle_service` (lifecycle updates) | I7 signals with lifecycle state, MAE/MFE, 8-class outcome |
| `llm_calls` | `llm_writer_service` | Full LLM call audit — request, response, outcome back-filled on signal close |
| `llm_model_scores` | `llm_writer_service` (refreshed every 15 min) | Per-model win rate, avg pnl_r, p-value — drives model selection |
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
  └─► bar stream (hot, DragonflyDB)
        └─► indicator_service (I1+I2, warm)
              └─► indicators:SYMBOL:TF stream
                    └─► market_analysis_service (I3–I6, warm)
                          └─► intelligence:SYMBOL:TF stream
                                ├─► signal_generator_service (I7, warm)
                                │     ├─► signal_ledger (cold, TimescaleDB — new rows)
                                │     └─► signals:SYMBOL:TF:aggregated (hot)
                                │           └─► ai_narrative_service (I8, warm)
                                │                 ├─► narratives:SYMBOL:TF (hot)
                                │                 └─► llm_calls:stream (hot)
                                │                       └─► llm_writer_service
                                │                             ├─► llm_calls (cold, TimescaleDB)
                                │                             └─► llm_model_scores (cold)
                                └─► feature_writer_service (warm → cold)
                                      └─► intelligence_features (TimescaleDB)

market:SYMBOL:1m
  └─► signal_lifecycle_service
        ├─► signal_ledger (cold — lifecycle updates, MAE/MFE, outcome)
        └─► llm_outcomes:stream → llm_writer_service (outcome back-fill)
```

---

## Related Documentation

- [DAG Execution](dag-execution.md) — how plugin dependencies are ordered
- [Intelligence Tiers](intelligence-tiers.md) — what each processing stage computes
- [Signal Lifecycle](signal-lifecycle.md) — how signals are tracked after I7 fires them
- **Code:** `src/core/stream_keys.py`, `src/core/stream_utils.py`, `src/core/database_manager.py`
