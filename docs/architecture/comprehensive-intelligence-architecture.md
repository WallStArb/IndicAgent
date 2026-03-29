# IndicAgent Intelligence Platform Architecture

**Version:** 2.1
**Last Updated:** 2026-03-29
**Status:** I1-I8 production complete — 121 plugins + 2 aggregation components

## Executive Summary

IndicAgent is a real-time market intelligence platform that transforms raw market data into actionable trading intelligence through a layered plugin-native architecture. The full I1-I8 pipeline is production-complete: 121 plugins across 8 intelligence tiers, 2 aggregation components, and a typed event bus persisted to TimescaleDB.

**Architecture Philosophy:** Plugin pipeline hosted within a unified `feature_compute_agent` for I1-I6, with separate services for signals (I7) and AI (I8). The real-time pipeline never touches the database directly — all cold persistence is decoupled through the `feature_writer_service`.

---

## Architecture Layers

```
Layer 4: AI Intelligence (I8)              → LLM analysis, local Ollama (qwen3.5:9b / phi4-mini:3.8b)
Layer 3: Pattern Intelligence (I5-I7)      → Pattern detection, confluence, trading signals
Layer 2: Mathematical Intelligence (I1-I6) → Technical indicators, second-derivative events, market structure, regime context, SMC
Layer 1: Data Foundation                   → Raw bar collection, multi-TF aggregation, Redpanda topics, TimescaleDB
```

**Full pipeline:**
```
IBKR TWS → IBKRProviderAgent (market.bars.raw.ibkr) →
  ProviderMergerAgent (market.bars) →
  BarAggregatorComputeAgent (market.bars.htf) →
  feature_compute_agent (I1→I6, subscribes to market.bars + market.bars.htf) →
  signal_generator_agent (I7) → signal_ledger + intelligence_features →
  feature_writer_service → TimescaleDB → SSE → Dashboard
```

---

## Layer 1: Data Foundation

### Provider Abstraction

The provider layer uses an abstract base + adapter pattern to keep broker-specific logic isolated:

- `BaseProviderAgent` (`src/providers/base_provider_agent.py`) — abstract base; subclasses get Kafka publish, metrics, and SIGTERM handling for free
- `IBKRAdapter` (`src/providers/ibkr_adapter.py`) — wraps `IBKRProvider` (`src/providers/ibkr.py`); all ib_insync logic isolated here
- `IBKRProviderAgent` (`services/ibkr_provider_agent.py`) — thin subclass of `BaseProviderAgent` for IBKR; publishes raw 1m bars to `market.bars.raw.ibkr`

### ProviderMergerAgent (`services/provider_merger_agent.py`, :9130)
- Subscribes to `market.bars.raw.<provider>` topics
- Routes canonical 1m bars to `market.bars`
- Auto-failover on primary provider silence
- Publishes `ProviderQualityEvent` to `market.data.quality` side-channel

### BarAggregatorComputeAgent (`services/bar_aggregator_agent.py`, :9120)
- Subscribes to `market.bars` (1m canonical stream)
- Aggregates 1m → 5m → 15m → 1h → 4h → 1d via `BarAccumulator`
- Publishes completed HTF bars to `market.bars.htf`

### BarWriterAgent (`services/bar_writer_agent.py`, :9121)
- Subscribes to `market.bars` and `market.bars.htf`
- Batch-writes OHLCV data to `market_data_ohlcv` hypertable

### BarAuditorAgent (`services/bar_auditor_agent.py`, :9123)
- Monitors bar streams for gaps
- Publishes gap fill requests to `market.events.gap_requests`

### Redpanda (Hot Tier)
- Kafka-compatible streaming backbone for real-time pipeline communication
- Sub-millisecond latency for inter-service messaging
- Topic names use dots: `development.market.bars`, `development.intelligence`, etc.
- Topic keys constructed exclusively via `src/core/stream_keys.py`

### TimescaleDB (Cold Tier)
- Populated only by `BarWriterAgent`, `feature_writer_service` (real-time), and `historical_backfill.py` (backfill)
- Real-time pipeline services never write to the database directly
- PostgreSQL/TimescaleDB Docker on :5432, database `indicagent`

---

## Layer 2: Mathematical & Market Intelligence (I1–I6)

Unified in `services/feature_compute_agent.py`.

Subscribes to **both**:
- `market.bars` — 1m canonical bars from ProviderMergerAgent
- `market.bars.htf` — 5m–1d bars from BarAggregatorComputeAgent

Each bar triggers an independent I1-I6 pipeline run for its symbol/timeframe.

### I1-I6 Tiers
Covers 121 plugins including technical indicators (RSI, MA, etc.), market structure (Swing, SR), regime context (VolRegime, GARCHVol), and Smart Money Concepts (BOS/CHoCH, FVG).

Output stream: `{env}.intelligence.{symbol}.{tf}` (typed `IntelligenceEvent`).

---

## Layer 3: Signal Intelligence (I7)

Runs in `services/signal_generator_agent.py`.

### I7 — Setup Plugins + 2 Aggregation Components
**Aggregation components:**
- `CISScorer` — Composite Intelligence Score
- `SignalAggregator` — selects winner from `all_ranked`

Output stream: `{env}.signals.{symbol}.{tf}.aggregated`
Cold persistence: `signal_ledger` table (all signals written per bar, not just winner)

### SignalTrackerAgent (`services/signal_tracker_agent.py`, :9115)
- Zone-aware lifecycle: activation, MAE/MFE tracking, 8-class outcome
- 8-class outcome: `never_activated`, `stopped_at_entry`, `stopped_in_trade`, `target_1`, `target_1_2`, `target_full`, `ttl_expired_ahead`, `ttl_expired_behind`

---

## Layer 4: AI Intelligence (I8)

### AI Narrative Service (`services/ai_narrative_service.py`, :9113)
- Consumes `{env}.intelligence.{symbol}.{tf}` events
- Calls local Ollama Docker (:11434)
  - **qwen3.5:9b** — per-signal narrative synthesis
  - **phi4-mini:3.8b** — group synthesis
- Output stream: `{env}.narratives.{symbol}.{tf}`

---

## Services

All services are systemd-managed.

| Service Unit | Purpose | Metrics Port |
|---|---|---|
| `indicagent-ibkr-provider` | IBKR dual streams: 5s RTB → 1m bars; publishes to `market.bars.raw.ibkr` | :9129 |
| `indicagent-provider-merger` | Routes `market.bars.raw.<provider>` → `market.bars`; auto-failover | :9130 |
| `indicagent-bar-aggregator-compute` | 1m → HTF bar aggregation via BarAccumulator; publishes to `market.bars.htf` | :9120 |
| `indicagent-bar-writer` | `market.bars` + `market.bars.htf` → `market_data_ohlcv` batch writer | :9121 |
| `indicagent-bar-auditor` | Gap detection → `market.events.gap_requests` | :9123 |
| `indicagent-feature-compute` | Unified I1+I2+I3+I4+I5+SMC+I6 | :9125 |
| `indicagent-signal-generator` | I7 → `signals:` + `signal_ledger` | :9112 |
| `indicagent-signal-tracker` | Zone-aware lifecycle, MAE/MFE tracking, 8-class outcome | :9115 |
| `indicagent-ai-narrative` | I8 LLM → `narratives:` | :9113 |
| `indicagent-feature-writer` | `intelligence:` → `intelligence_features` | :9116 |
| `indicagent-api` | FastAPI + SSE on :8000 | — |

---

## Stream Architecture

All stream keys are constructed via `src/core/stream_keys.py`.

| Stream | Producer | Consumer(s) |
|---|---|---|
| `{env}.market.bars.raw.{provider}` | IBKRProviderAgent | ProviderMergerAgent |
| `{env}.market.bars` | ProviderMergerAgent | BarAggregatorComputeAgent, BarWriterAgent, BarAuditorAgent, feature_compute_agent |
| `{env}.market.bars.htf` | BarAggregatorComputeAgent | feature_compute_agent, BarWriterAgent |
| `{env}.market.events.gap_requests` | BarAuditorAgent | gap fill handlers |
| `{env}.market.events.roll` | RollComputeAgent | signal_generator_agent |
| `{env}.market.data.quality` | ProviderMergerAgent | observability consumers |
| `{env}.intelligence.{symbol}.{tf}` | feature_compute_agent | signal_generator_agent, ai_narrative_service, feature_writer_service |
| `{env}.signals.{symbol}.{tf}.aggregated` | signal_generator_agent | indicagent-api (SSE) |
| `{env}.narratives.{symbol}.{tf}` | indicagent-ai-narrative | indicagent-api (SSE) |

---

## Related Documentation

- `docs/concepts/intelligence-tiers.md`
- `docs/reference/schemas/stream-schemas.md`
- `src/intelligence/CLAUDE.md` — Plugin protocol and LLM provider chain
