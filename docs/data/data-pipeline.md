<!-- generated-by: gsd-doc-writer -->
# Data Pipeline

**Version:** 2.8
**Status:** current
**Last Updated:** 2026-05-27

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

The `IBKRProvider` (`indicagent-ibkr-provider`) connects to IBKR TWS at `127.0.0.1:7497` (running in Docker `ib-gateway` container), collects 5s real-time bars, and publishes them to `market.bars.raw.ibkr`. The `ProviderMerger` (`indicagent-provider-merger`) consumes all provider raw topics and routes to the canonical `market.bars` topic with automatic primary-silence failover. All topic names are constructed via `src/core/stream_keys.py` and are environment-prefixed.

### Topic Convention

```
{env}.market.bars.raw.{provider}   # Per-provider raw bars (e.g. market.bars.raw.ibkr)
{env}.market.bars                  # Canonical 1m bars from ProviderMerger
{env}.market.bars.htf              # Aggregated HTF bars (5m–1d) from BarAggregator
{env}.intelligence                 # IntelligenceEvent output, indicators through signals (I1-I7)
{env}.intelligence.i7.signals      # Trading signals (I7)
{env}.intelligence.journal         # High-confidence signals → AI narrative (I8)
{env}.intelligence.lifecycle       # LifecycleTransition events
{env}.narratives                   # Per-signal AI narrative (I8)
{env}.llm.calls                    # Every LLM call audit record
{env}.llm.outcomes                 # Signal lifecycle exits with pnl_r/mae/mfe
```

Environment prefix is `{env}.` (e.g., `development.` in dev, empty string in production). **Always build topics via `src/core/stream_keys.py`** — never hardcode.

### Consumer Groups

Each service reads its input topics via an exclusive Kafka consumer group. The group offset is tracked by Redpanda, enabling independent progress per service and automatic replay on restart. Consumer group names follow the pattern `<concept>_consumer` (idempotent on restart).

---

## Warm Tier: Processing Services

**Purpose:** Intelligence extraction from raw bars
**Technology:** Python async services, systemd-managed
**Latency:** <10ms per bar per symbol/timeframe

The microservices architecture enforces **Separation of Concerns (SoC)** as an operational invariant: each service owns exactly one responsibility and is deployed, restarted, and scaled independently. The Redpanda stream bus is the only contract between services.

### Service Pipeline

| Service | Reads From | Writes To |
|---------|-----------|-----------|
| `indicagent-ibkr-provider` | IBKR TWS (5s real-time bars at 127.0.0.1:7497) | `market.bars.raw.ibkr` |
| `indicagent-provider-merger` | `market.bars.raw.*` | `market.bars` (canonical 1m) |
| `indicagent-bar-aggregator` | `market.bars` | `market.bars.htf` (5m–1d) |
| `indicagent-intelligence-pipeline` | `market.bars` + `market.bars.htf` | `intelligence` + `intelligence.i7.signals` |
| `indicagent-signal-writer` | `intelligence.i7.signals` | `signal_ledger` (new rows) |
| `indicagent-signal-tracker-compute` | `market.bars` + `intelligence.i7.signals` | `intelligence.lifecycle` (LifecycleTransition events) |
| `indicagent-lifecycle-writer` | `intelligence.lifecycle` | `signal_ledger` (lifecycle updates) |
| `indicagent-signal-metrics-compute` | `signal_ledger` (DB query) | `intelligence.signal_metrics` |
| `indicagent-signal-metrics-writer` | `intelligence.signal_metrics` | `signal_metrics` table (TimescaleDB) |
| `indicagent-narrative-compute` | `intelligence.journal` | `narratives` + `llm.calls` |
| `indicagent-feature-writer` | `intelligence` | `intelligence_features` (TimescaleDB) |
| `indicagent-llm-writer` | `llm.calls` + `llm.outcomes` | `llm_calls` hypertable + `llm_model_scores` |
| `indicagent-alpha-swarm` | `intelligence.i7.signals` | `intelligence` (adjusted_confidence/swarm_multiplier) |
| `indicagent-bar-replay` | `market_data_ohlcv` (DB read) | `market.bars` + `market.bars.htf` (one-shot, self-terminating) |
| `indicagent-signal-replay` | `signal_ledger` (DB query, expires_at < NOW()) | `intelligence.lifecycle` (periodic, every 5 min) |

### Self-Healing Services

**Bar Auditor** (`indicagent-bar-auditor`) detects gaps in `market_data_ohlcv` and publishes `BarGapRequest` events that trigger gap-filling from the data provider. No manual intervention required.

**BarReplayProvider** (`indicagent-bar-replay`) replays historical OHLCV data into the live pipeline. Used for bootstrap after fresh install, recovery from extended downtime, or reprocessing after signal schema upgrades. Checkpoint-based; self-terminates when caught up.

**SignalReplayAuditor** (`indicagent-signal-replay`) resolves orphaned signal lifecycles every 5 minutes. Finds signals with `exit_at IS NULL AND expires_at IS NOT NULL AND expires_at < NOW()`, replays bar-by-bar against `market_data_ohlcv`, publishes idempotent `LifecycleTransition` events. Health invariant: `signal_replay_unresolved_gauge = 0`.

---

## Cold Tier: TimescaleDB

**Purpose:** Long-term storage, ML training data, signal history
**Technology:** PostgreSQL + TimescaleDB extension, :5432, DB `indicagent`
**Write Pattern:** Async batch by Writers

### Tables

| Table | Written By | Purpose |
|-------|-----------|---------|
| `market_data_ohlcv` | `BarWriter` | Raw OHLCV cold storage. Primary time column: `timestamp` |
| `intelligence_features` | `indicagent-feature-writer` | Full feature vectors per bar (tiered JSONB: bar/i1/i3/i4/i5/smc/i6). Column: `ts` |
| `signal_ledger` | `indicagent-signal-writer` (new rows) + `indicagent-lifecycle-writer` (lifecycle updates) | Trading signals (I7) with lifecycle state, MAE/MFE, 8-class outcome; includes `expires_at` (TTL column), `entry_zone_low`, `entry_zone_high` |
| `signal_metrics` | `indicagent-signal-metrics-writer` | Per-setup rolling 30d stats (win_rate, avg_pnl_r, sharpe, n) by regime; only rows with `n >= 30` drive signal ranking |
| `llm_calls` | `indicagent-llm-writer` | Full LLM call audit — request, response, outcome back-filled on signal close |
| `llm_model_scores` | `indicagent-llm-writer` (refreshed every 15 min) | Per-model win rate, avg pnl_r, p-value |

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
IBKR TWS (127.0.0.1:7497, Docker)
  └─► IBKRProvider (hot)
        └─► market.bars.raw.ibkr
              └─► ProviderMerger
                    └─► market.bars (canonical 1m, hot)
                          ├─► BarAggregatorAgent
                          │     └─► market.bars.htf (5m–1d, hot)
                          │           └─► BarWriter → market_data_ohlcv (cold)
                          └─► IntelligencePipeline (I1–I7 unified, warm)
                                  (also subscribes to market.bars.htf)
                                ├─► intelligence (IntelligenceEvent, keyed SYMBOL:TF)
                                │     ├─► indicagent-feature-writer → intelligence_features (cold)
                                │     └─► intelligence.journal
                                │           └─► indicagent-narrative-compute (I8, warm)
                                │                 ├─► narratives (keyed SYMBOL:TF, hot)
                                │                 └─► llm.calls
                                │                       └─► indicagent-llm-writer
                                │                             ├─► llm_calls (cold, TimescaleDB)
                                │                             └─► llm_model_scores (cold)
                                └─► intelligence.i7.signals
                                      ├─► indicagent-signal-writer → signal_ledger (cold — new rows)
                                      ├─► indicagent-alpha-swarm → intelligence (swarm_multiplier)
                                      └─► indicagent-signal-tracker-compute
                                            └─► intelligence.lifecycle
                                                  └─► indicagent-lifecycle-writer
                                                        └─► signal_ledger (cold — lifecycle updates)

signal_ledger (cold)
  └─► indicagent-signal-metrics-compute → intelligence.signal_metrics
        └─► indicagent-signal-metrics-writer → signal_metrics (cold)
              └─► IntelligencePipeline (perf_weights, reloaded hourly)
```

---

## Related Documentation

- **Reference data & roll logic:** `data-foundation.md` — instruments, contract_metadata, roll lifecycle
- **Provider layer:** `data-provider.md` — provider isolation, failover, IBKR dual streams, bar normalization
- [DAG Execution](../concepts/dag-execution.md) — how plugin dependencies are ordered
- [Intelligence Tiers](../concepts/intelligence-tiers.md) — what each processing stage computes
- [Signal Lifecycle](../signals/signals-lifecycle.md) — how signals are tracked after signal generation (I7) fires them
- **Code:** `src/core/stream_keys.py`, `src/core/database_manager.py`
