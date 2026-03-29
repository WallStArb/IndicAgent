# IndicAgent Layered Architecture

**Version:** 2.1
**Last Updated:** 2026-03-29
**Status:** I1-I8 production complete — 121 plugins + 2 aggregation components

## Overview

IndicAgent implements a 6-layer intelligence platform that progresses from raw data ingestion through AI-powered narrative synthesis. The platform is provider-agnostic: any market data source can be wired in via a `BaseProviderAgent` implementation.

The central architectural principle: **the real-time compute pipeline never touches the database directly.** All persistence is handled asynchronously by dedicated WriterAgents, decoupling hot-path latency from cold storage.

---

## 6-Layer Architecture

### Layer 0: Data Ingestion

**Purpose:** Receive raw market data from external providers, normalize to a canonical bar stream.

**Components:**
- `services/ibkr_provider_agent.py` (`IBKRProviderAgent`) — connects to IBKR TWS, collects 5s real-time bars, publishes to `market.bars.raw.ibkr`
- `services/provider_merger_agent.py` (`ProviderMergerAgent`) — consumes `market.bars.raw.*` from all active providers, applies auto-failover on primary silence, publishes canonical `market.bars` (1m); emits quality side-channel `ProviderQualityEvent`
- `src/providers/base_provider_agent.py` (`BaseProviderAgent`) — abstract base class defining the provider contract and instrument qualification logic
- `src/providers/ibkr_adapter.py` (`IBKRAdapter`) — adapter wrapping `src/providers/ibkr.py` (all ib_insync logic lives exclusively in that module)

**Output streams:** `market.bars.raw.<provider>` (per-provider), `market.bars` (canonical 1m)

**Metrics:** IBKRProviderAgent `:9129`, ProviderMergerAgent `:9130`

---

### Layer 1: Bar Processing

**Purpose:** Aggregate canonical 1m bars into higher timeframes, persist raw OHLCV data, and detect gaps.

**Components:**
- `services/bar_aggregator_agent.py` (`BarAggregatorComputeAgent`) — consumes `market.bars` (1m), produces multi-timeframe bars via `BarAccumulator` (5m → 15m → 1h → 4h → 1d), publishes to `market.bars.htf`
- `services/bar_writer_agent.py` (`BarWriterAgent`) — consumes `market.bars` + `market.bars.htf`, persists to `market_data_ohlcv` hypertable in batch
- `services/bar_auditor_agent.py` (`BarAuditorAgent`) — validates bar completeness against expected cadence, publishes gap requests to `market.events.gap_requests`

**Output streams:** `market.bars.htf` (all HTF timeframes)
**DB writes:** `market_data_ohlcv` (ground truth, keep forever)

**Metrics:** BarAggregatorComputeAgent `:9120`, BarWriterAgent `:9121`, BarAuditorAgent `:9123`

---

### Layer 2: Feature Computation (I1–I6)

**Purpose:** Incremental indicator computation, market context classification, and pattern recognition. DB-ignorant.

**Service:** `services/feature_compute_agent.py` (`FeatureComputeAgent`) — subscribes to both `market.bars` (1m) and `market.bars.htf` (HTF bars). Each bar triggers an independent I1–I6 pipeline run. Outputs `intelligence:{SYMBOL}:{TF}` (typed `IntelligenceEvent` with tiered JSONB: bar/i1/i2/i3/i4/i5/smc/i6).

**I1–I2 (Indicators):** RSI, MA, MACD, ATR, Bollinger, Stochastic, Volume Profile, and more — 27 I1 plugins.
**I3–I4 (Market Structure + Context):** SMC order blocks, FVGs, liquidity, HTF regime classification — 7 I3 + 11 I4 plugins.
**I5 (Pattern Recognition):** Divergence, exhaustion, momentum confluence — 15 I5 plugins.
**I6 (Cross-Timeframe Confluence):** `cross_timeframe.py` — scores trend alignment, FVG/OB alignment, and regime agreement across all active TFs.

All plugins use `compute_next()` for incremental, stateful computation.

**Metrics:** `:9125`

---

### Layer 3: Signal Generation (I7)

**Purpose:** Pattern confluence, setup detection, signal generation. DB-ignorant compute; WriterAgents handle persistence.

**Components:**
- `services/signal_generator_agent.py` (`SignalGeneratorAgent`) — I7: 36 setup plugins + CISScorer + SignalAggregator. Consumes `intelligence:{SYMBOL}:{TF}` stream. Writes every fired signal to `signal_ledger` regardless of regime eligibility; publishes winner to `signals.aggregated`. Bar history fed from IntelligenceEvent stream.
- `services/signal_tracker_agent.py` (`SignalTrackerAgent`) — zone-aware lifecycle tracking: entry activation, MAE/MFE, 8-class outcome classification. Updates `signal_ledger` with lifecycle outcomes.

**8-class signal outcomes:** `never_activated`, `stopped_at_entry`, `stopped_in_trade`, `target_1`, `target_1_2`, `target_full`, `ttl_expired_ahead`, `ttl_expired_behind`

**DB writes:** `signal_ledger` (all signals + lifecycle outcomes, keep forever)

**Metrics:** SignalGeneratorAgent `:9112`, SignalTrackerAgent `:9115`

---

### Layer 4: Persistence

**Purpose:** Asynchronously consume compute-layer streams and write to TimescaleDB. All persistence agents are DB-aware; all compute agents above are DB-ignorant.

**Components:**
- `services/feature_writer_agent.py` (`FeatureWriterAgent`) — batch-consumes `intelligence:{SYMBOL}:{TF}` streams, writes to `intelligence_features` hypertable; decouples hot-path from TimescaleDB
- `services/bar_writer_agent.py` (`BarWriterAgent`) — persists raw and HTF bar data to `market_data_ohlcv` (see Layer 1)
- `services/signal_tracker_agent.py` (`SignalTrackerAgent`) — writes signal lifecycle outcomes to `signal_ledger` (see Layer 3)

**DB writes:** `intelligence_features` (full feature vectors per bar, ML training dataset, keep forever)

**Metrics:** FeatureWriterAgent `:9116`

---

### Layer 5: AI Intelligence (I8)

**Purpose:** LLM-powered market narrative synthesis and model performance tracking.

**Components:**
- `services/intelligence_compute_agent.py` (`IntelligenceComputeAgent`) — standalone I7/I8 compute loop; warmup via `BarHistorySeeder`; publishes to `intelligence:{SYMBOL}:{TF}`
- `services/ai_narrative_agent.py` (`AINarrativeAgent`) — Ollama qwen3.5:9b per-signal analysis → `narratives:{SYMBOL}:{TF}`
- `services/llm_writer_agent.py` (`LLMWriterAgent`) — `llm.calls` → `llm_calls` hypertable; outcome back-fill; `llm_model_scores` refresh every 15 min

**DB writes:** `llm_calls` (full LLM audit log, keep forever), `llm_model_scores` (per-model win rate)

**Metrics:** IntelligenceComputeAgent `:9114`, AINarrativeAgent `:9113`, LLMWriterAgent `:9117`

---

## Cross-Cutting Services

- `services/bar_auditor_agent.py` — gap detection and integrity validation (feeds back into Layer 0/1 recovery)
- `indicagent-api` — FastAPI + SSE on :8000; fans out all streams to dashboard clients
- `src/core/database_manager.py` — PostgreSQL/TimescaleDB connection pooling (used only by WriterAgents and API)
- `src/core/stream_keys.py` — single source of truth for all topic/stream key construction; never hardcode topic strings

---

## Data Flow

```
IBKR TWS
  └─ IBKRProviderAgent
       └─ market.bars.raw.ibkr
            └─ ProviderMergerAgent
                 └─ market.bars  (canonical 1m)
                      ├─ BarAggregatorComputeAgent
                      │    └─ market.bars.htf  (5m-1d)
                      │         └─ BarWriterAgent → market_data_ohlcv (TimescaleDB)
                      ├─ BarAuditorAgent → market.events.gap_requests
                      ├─ FeatureComputeAgent  (also subscribes to market.bars.htf)
                      │    └─ intelligence:{SYMBOL}:{TF}  (IntelligenceEvent JSONB)
                      │         ├─ SignalGeneratorAgent (I7)
                      │         │    ├─ signals.aggregated
                      │         │    └─ signal_ledger (TimescaleDB)
                      │         │         └─ SignalTrackerAgent
                      │         │              └─ signal_ledger lifecycle updates
                      │         ├─ IntelligenceComputeAgent / AINarrativeAgent (I8)
                      │         │    ├─ narratives:{SYMBOL}:{TF}
                      │         │    └─ llm.calls
                      │         │         └─ LLMWriterAgent → llm_calls (TimescaleDB)
                      │         └─ FeatureWriterAgent
                      │              └─ intelligence_features (TimescaleDB)
```

---

## Persistence Architecture

All persistence is handled by dedicated WriterAgents. No compute agent writes to the database.

| WriterAgent | Source Stream | DB Table |
|---|---|---|
| `BarWriterAgent` | `market.bars`, `market.bars.htf` | `market_data_ohlcv` |
| `FeatureWriterAgent` | `intelligence:{SYMBOL}:{TF}` | `intelligence_features` |
| `SignalTrackerAgent` | `signal_ledger` writes + lifecycle events | `signal_ledger` |
| `LLMWriterAgent` | `llm.calls` | `llm_calls`, `llm_model_scores` |

---

## Agent Role Taxonomy

Per `docs/architecture/AGENT_STANDARD.md`:

| Suffix | Role | DB Access |
|---|---|---|
| `ProviderAgent` | External source → Kafka (no compute, no DB) | No |
| `ComputeAgent` | Math/stats transform, DB-ignorant | No |
| `GeneratorAgent` | Signal/trade fire logic | No |
| `WriterAgent` | DB persistence from Kafka stream | Yes |
| `TrackerAgent` | Business object lifecycle management | Yes |
| `AuditorAgent` | Data integrity validation + self-healing | No (publishes events) |

---

## Plugin System

121 plugins + 2 aggregation components across tiers I1–I7. See `src/intelligence/CLAUDE.md` for tier details, plugin protocol, and LLM provider chain.

- Tier lists: `TIER_I1`…`TIER_I7` in `src/intelligence/register_plugins.py` — single source of truth
- `registry.validate_tier()` hard-crashes at startup on any missing plugin name
- All plugins use `compute_next()` for incremental, stateful, allocation-efficient computation
- I7 plugins must consume relevant I6 `ctf_*` sub-scores (Renaissance I6→I7 confluence obligation)

---

## Renaissance Principles Applied

- **Real-time pipeline never touches the database.** WriterAgents are the only DB-aware components.
- **Degrade gracefully.** ProviderMergerAgent auto-fails over on primary silence; BarAuditorAgent publishes gap requests for self-healing recovery.
- **Never drop data that could contain signal.** Every bar, feature vector, signal, and LLM call is persisted as a labeled training sample.
- **Segment relentlessly.** I6 cross-timeframe confluence scores are computed per regime type, not globally.
- **Instrument everything.** All agents expose Prometheus Golden Signals (Traffic, Latency, Errors, Saturation). Each WriterAgent tracks `persistence_batch_latency` and `persistence_consumer_lag`.
