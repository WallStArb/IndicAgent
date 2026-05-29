<!-- generated-by: gsd-doc-writer -->
# IndicAgent Layered Architecture

**Version:** 2.8
**Last Updated:** 2026-05-27
**Status:** v2.8 in progress — 132 plugins + 2 aggregation components

## Overview

IndicAgent implements a 6-layer intelligence platform that progresses from raw data ingestion through AI-powered narrative synthesis. The platform is provider-agnostic: any market data source can be wired in via a `BaseProviderAgent` implementation.

The central architectural principle: **the real-time compute pipeline never touches the database directly.** All persistence is handled asynchronously by dedicated WriterAgents, decoupling hot-path latency from cold storage.

---

## 6-Layer Architecture

### Layer 0: Data Ingestion

**Purpose:** Receive raw market data from external providers, normalize to a canonical bar stream.

**Components:**
- `services/ibkr_provider_agent.py` (`IBKRProviderAgent`) — connects to IBKR TWS, collects 5s real-time bars, publishes to `market.bars.raw.ibkr`
- `services/provider_merger_agent.py` (`ProviderMergerAgent`) — consumes `market.bars.raw.*` from all active providers, applies auto-failover on primary silence, publishes canonical `market.bars` (1m); emits quality side-channel `ProviderQualityEvent` to `market.data.quality`
- `src/providers/base_provider_agent.py` (`BaseProviderAgent`) — abstract base class defining the provider contract and instrument qualification logic
- `src/providers/ibkr_adapter.py` (`IBKRAdapter`) — adapter wrapping `src/providers/ibkr.py` (all ib_insync logic lives exclusively in that module)

**Output streams:** `market.bars.raw.<provider>` (per-provider), `market.bars` (canonical 1m), `market.data.quality`

**Metrics:** IBKRProviderAgent `:9129`, ProviderMergerAgent `:9130`

---

### Layer 1: Bar Processing

**Purpose:** Aggregate canonical 1m bars into higher timeframes, persist raw OHLCV data, detect gaps, and track contract rolls.

**Components:**
- `services/bar_aggregator_agent.py` (`BarAggregatorComputeAgent`) — consumes `market.bars` (1m), produces multi-timeframe bars via `BarAccumulator` (5m → 15m → 1h → 4h → 1d), publishes to `market.bars.htf`
- `services/bar_writer_agent.py` (`BarWriterAgent`) — consumes `market.bars` + `market.bars.htf`, persists to `market_data_ohlcv` hypertable in batch. DLQ: `bar.writer.dlq`
- `services/bar_auditor_agent.py` (`BarAuditorAgent`) — validates bar completeness against expected cadence, publishes gap requests to `market.events.gap_requests`. DLQ: `bar.audit.dlq`, `gap_fill.dlq`
- `production/scripts/roll_batch.py` (nightly timer at 8pm) — calendar-based roll detection, promotes front-month in `contract_metadata` table, broadcasts updates via Kafka. Replaces the previous 24/7 `roll-compute` + `contract-metadata-writer` daemon pair.

**Output streams:** `market.bars.htf`, `market.events.gap_requests`, `market.events.roll`, `market.events.contract_update`
**DB writes:** `market_data_ohlcv` (ground truth, keep forever), `contract_metadata`

**Metrics:** BarAggregatorComputeAgent `:9120`, BarWriterAgent `:9121`, BarAuditorAgent `:9123`

---

### Layer 2: Intelligence Computation (I1–I7)

**Purpose:** Incremental indicator computation, market context classification, pattern recognition, and signal generation. DB-ignorant — all persistence handled by WriterAgents downstream.

**Service:** `services/intelligence_pipeline_agent.py` (`IntelligencePipelineComputeAgent`) — subscribes to both `market.bars` (1m) and `market.bars.htf`. Each bar triggers an independent I1–I7 in-process pipeline run. Outputs:
- `intelligence.journal` — `BarIntelligenceRecord` (atomic per-bar record wrapping `IntelligenceEvent` + all ranked signals + funnel counts)
- `intelligence.i7.signals` — all ranked I7 signals per bar (pre-ledger write)
- `lifecycle.transitions` — signal state changes for LifecycleWriterAgent
- `intelligence.signal.dlq` — null-CIS signals caught before publish

**I1 (28 plugins — Indicators):** RSI, MA, MACD, ATR, Bollinger, Stochastic, ADX, Volume Profile, OFI, CVD, and more
**I2 (10 plugins — Composite Events):** MACDEvents, RSIEvents, ADXEvents, VolumeEvents, ExhaustionScore, AccelerationRegime, etc.
**I3 (8 plugins — Market Structure):** Swing, S/R, MarketProfile, SessionLevels, FibZones, SwingMomentum, MACDEvents
**I4 (12 plugins — Context / Regime):** GARCH, Kalman, HurstExp, VIXRegime, CrossAsset, VWAP, VolumeProfile, and more
**I5 (16 plugins — Pattern Recognition):** Divergence, exhaustion, squeeze, chart patterns
**SMC (16 plugins — Smart Money Concepts):** BOS/CHoCH, FVG, OrderBlocks, HMMRegime x4 (1m/5m/15m/1h), BOCPD, LiquidityPools, ICT Killzones, AMD Cycle, etc.
**I6 (6 plugins — Cross-Timeframe Confluence):** Cross-timeframe momentum divergence, SR confluence, regime agreement, squeeze/expansion divergence, orderflow alignment
**I7 (36 plugins — Signal Generation):** Setup plugins + CISScorer aggregator. Every fired signal written to `intelligence.i7.signals`

**Parallelization:** I1 and I7 tiers are parallelized via `asyncio.gather` + ThreadPoolExecutor. I2–I6 remain sequential (GIL prevents true thread parallelism for CPU-bound Python; batch processing is the planned fix). See `docs/architecture/pipeline-optimization.md`.

All plugins use `compute_next()` for incremental, stateful, O(1) computation.

**Metrics:** `:9125`

---

### Layer 3: Signal Lifecycle

**Purpose:** Track signal activation, MAE/MFE, and 8-class outcome without touching the database. Publish typed lifecycle events for the writer to persist.

**Components:**
- `services/signal_tracker_compute_agent.py` (`SignalTrackerComputeAgent`) — zone-aware lifecycle tracking: entry activation, MAE/MFE accumulation, 8-class outcome classification. DB-ignorant — publishes transitions to `lifecycle.transitions`. DLQ: `signal.tracker.dlq`
- `services/signal_replay_auditor_agent.py` (`SignalReplayAuditorAgent`) — reads signals where `expires_at < NOW()` directly from `signal_ledger` (no LATERAL JOIN to `intelligence_features`); uses `entry_zone_low`/`entry_zone_high` stored at fire time
- `services/signal_auditor_agent.py` (`SignalAuditorAgent`) — validates signal coverage per (symbol, tf) per session; publishes `SignalCoverageGapEvent` to `intelligence.signal.audit` when coverage drops. DLQ: `signal.audit.dlq`
- `services/signal_metrics_compute_agent.py` (`SignalMetricsComputeAgent`) — timer-triggered performance metrics (win rate, avg pnl_r, IC) per plugin + regime; publishes to `intelligence.signal_metrics`

**8-class signal outcomes:** `never_activated`, `stopped_at_entry`, `stopped_in_trade`, `target_1`, `target_1_2`, `target_full`, `ttl_expired_ahead`, `ttl_expired_behind`

**Signal schema version:** `SIGNAL_SCHEMA_VERSION = "v1"` in `src/intelligence/trading/signal_schema.py` — canonical constant imported by all producers/consumers.

**Metrics:** SignalTrackerComputeAgent `:9115`, SignalAuditorAgent `:9128`, SignalMetricsComputeAgent `:9126`

---

### Layer 4: Persistence

**Purpose:** Asynchronously consume compute-layer streams and write to TimescaleDB. All persistence agents are DB-aware; all compute agents above are DB-ignorant.

**Components:**
- `services/feature_writer_agent.py` (`FeatureWriterAgent`) — batch-consumes `intelligence.journal` (`BarIntelligenceRecord`), writes to `intelligence_features` hypertable; single atomic INSERT per bar (Phase 44.3). Consumer group: `feature_writer_group`. DLQ: `feature.writer.dlq`
- `services/feature_snapshot_writer_agent.py` (`FeatureSnapshotWriterAgent`) — shadow dual-write of feature records to `feature_snapshots_shadow` for parity validation. `:9132`
- `services/parity_auditor_agent.py` (`ParityAuditorAgent`) — 5-min parity comparison between canonical and shadow tables; certifies after 60 consecutive clean cycles (`match_rate ≥ 0.95`); alerts via `alert.requests` on breach. `:9133`
- `services/signal_writer_agent.py` (`SignalWriterAgent`) — batch-consumes `intelligence.i7.signals`, writes new rows to `signal_ledger` (including `expires_at`, `entry_zone_low`, `entry_zone_high`). DLQ: `signal.writer.dlq`
- `services/lifecycle_writer_agent.py` (`LifecycleWriterAgent`) — consumes `lifecycle.transitions`, persists lifecycle updates to `signal_outcomes`. DLQ: `lifecycle.writer.dlq`
- `services/signal_metrics_writer_agent.py` (`SignalMetricsWriterAgent`) — consumes `intelligence.signal_metrics`, upserts `signal_metrics`, `signal_metrics_ic`, `signal_metrics_dq_failures` tables. `:9127`
- `services/bar_writer_agent.py` (`BarWriterAgent`) — also writes `market_data_ohlcv` (see Layer 1)

**DB writes:** `intelligence_features`, `feature_snapshots_shadow`, `signal_ledger` (new rows + lifecycle updates via `signal_outcomes`), `market_data_ohlcv`, `signal_metrics*` tables

**Metrics:** FeatureWriterAgent `:9116`, FeatureSnapshotWriterAgent `:9132`, ParityAuditorAgent `:9133`, SignalWriterAgent `:9119`

---

### Layer 5: AI Intelligence (I8)

**Purpose:** LLM-powered market narrative synthesis and model performance tracking.

**Components:**
- `services/narrative_group_compute_agent.py` (`NarrativeGroupComputeAgent`) — primary: Ollama gemma4:e4b (default; `.env` may override via `OLLAMA_MODEL`); optional fallback: OpenRouter. Publishes to `narratives` + `narratives.group`. Consumer group: `ai_narrative`
- `services/llm_writer_service.py` (`LLMWriterAgent`) — consumes `llm.calls` → `llm_calls` hypertable; back-fills outcomes from `llm.outcomes`; refreshes `llm_model_scores` every 15 min. Adaptive routing: model with `is_significant=True` (p<0.05, n≥30) moves to chain position 0

**DB writes:** `llm_calls` (full LLM audit log, keep forever), `llm_model_scores` (per-model win rate + p-value)

**Metrics:** NarrativeGroupComputeAgent `:9113`, LLMWriterAgent `:9117`

---

## Cross-Cutting Services

- `services/service_auditor_agent.py` (`ServiceAuditorAgent`) — monitors all pipeline services, publishes health state transitions to `system.health.events`, triggers restarts on lag/error threshold breach; escalation DLQ: `intelligence.service_auditor.journal.dlq`. `:9131`
- `services/alpha_swarm_agent.py` (`AlphaSwarmComputeAgent`) — runs alpha agents on I7 signals, emits signal lineage; DB-ignorant compute service
- `services/lineage_writer_agent.py` (`LineageWriterAgent`) — persists `topic_signal_lineage()` events to `signal_lineage`; writer-owned projections may materialize swarm fields onto `signal_ledger`
- `services/cross_asset_service.py` (`CrossAssetService`) — cross-asset spread dynamics; publishes to `cross_asset`. `:9118`
- `indicagent-api` — FastAPI + SSE on :8000; fans out all streams to dashboard clients
- `src/core/database_manager.py` — PostgreSQL/TimescaleDB connection pooling (used only by WriterAgents and API)
- `src/core/stream_keys.py` — single source of truth for all topic/stream key construction; never hardcode topic strings

---

## Data Flow

```
IBKR TWS
  └─ IBKRProviderAgent
       └─ market.bars.raw.ibkr
            └─ ProviderMergerAgent ──────────────────────── market.data.quality
                 └─ market.bars  (canonical 1m)
                      ├─ BarAggregatorComputeAgent
                      │    └─ market.bars.htf  (5m-1d)
                      │         └─ BarWriterAgent → market_data_ohlcv
                      ├─ BarAuditorAgent → market.events.gap_requests
                      └─ IntelligencePipelineComputeAgent
                           (also subscribes to market.bars.htf)
                           ├─ intelligence.journal (BarIntelligenceRecord)
                           │    ├─ FeatureWriterAgent → intelligence_features
                           │    └─ FeatureSnapshotWriterAgent → feature_snapshots_shadow
                           │         └─ ParityAuditorAgent (certifies after 60 clean cycles)
                           ├─ intelligence.i7.signals
                           │    ├─ SignalWriterAgent → signal_ledger (new rows)
                           │    └─ SignalTrackerComputeAgent (lifecycle, DB-ignorant)
                           │         └─ lifecycle.transitions
                           │              └─ LifecycleWriterAgent → signal_outcomes (updates)
                           └─ NarrativeGroupComputeAgent (I8)
                                ├─ narratives / narratives.group
                                └─ llm.calls
                                     └─ LLMWriterAgent → llm_calls
                           └─ AlphaSwarmComputeAgent
                                └─ topic_signal_lineage()
                                     └─ LineageWriterAgent → signal_lineage

roll-batch (nightly 8pm timer)
  └─ contract_metadata (DB) → Kafka contract update events → downstream caches
```

---

## Persistence Architecture

All persistence is handled by dedicated WriterAgents. No compute agent writes to the database.

| WriterAgent | Source Stream | DB Table |
|---|---|---|
| `BarWriterAgent` | `market.bars`, `market.bars.htf` | `market_data_ohlcv` |
| `FeatureWriterAgent` | `intelligence.journal` | `intelligence_features` |
| `FeatureSnapshotWriterAgent` | `intelligence.journal` | `feature_snapshots_shadow` |
| `SignalWriterAgent` | `intelligence.i7.signals` | `signal_ledger` (new rows) |
| `LifecycleWriterAgent` | `lifecycle.transitions` | `signal_outcomes` (lifecycle updates) |
| `SignalMetricsWriterAgent` | `intelligence.signal_metrics` | `signal_metrics*` tables |
| `LLMWriterAgent` | `llm.calls`, `llm.outcomes` | `llm_calls`, `llm_model_scores` |
| `LineageWriterAgent` | `topic_signal_lineage()` | `signal_lineage` |

---

## Agent Role Taxonomy

Per `docs/agents/agents-foundation.md` (role taxonomy) and `docs/agents/agents-operations.md` (DAG topology):

| Suffix | Role | DB Access |
|---|---|---|
| `ProviderAgent` | External source → Kafka (no compute, no DB) | No |
| `ComputeAgent` | Math/stats transform, DB-ignorant | No |
| `GeneratorAgent` | Signal/trade fire logic | No |
| `WriterAgent` | DB persistence from Kafka stream | Yes |
| `TrackerAgent` | Business object lifecycle management (compute only; paired with a WriterAgent) | No |
| `AuditorAgent` | Data integrity validation + self-healing (publishes events, no DB writes) | No |

---

## Intelligence Tiers

| Tier | Plugins | Output |
|------|---------|--------|
| I1 | 28 | Technical indicators (RSI, MA, MACD, ATR, BB, Stoch, ADX, OFI, CVD, etc.) |
| I2 | 10 | Composite events (MACD, RSI, ADX, volume, momentum events) |
| I3 | 8 | Market structure (swing, S/R, profile, session levels, fib) |
| I4 | 12 | Context/regime (GARCH, Kalman, VIX, CrossAsset, VWAP, VP) |
| I5 | 16 | Pattern detection (divergence, squeeze, chart patterns) |
| SMC | 16 | Smart Money (BOS/CHoCH, FVG, OB, HMM x4, BOCPD, etc.) |
| I6 | 6 | CrossTimeframeConfluence (6 sub-score plugins) |
| I7 | 36 | Trading signals |
| I8 | — | LLM narratives (separate service; not a plugin) |

**Total:** 132 plugins + 2 aggregation components (CISScorer, SignalAggregator). Source of truth: `TIER_I*` in `src/intelligence/register_plugins.py`.

---

## Plugin System

132 plugins + 2 aggregation components across tiers I1–I7. See `src/intelligence/CLAUDE.md` for tier details, plugin protocol, and LLM provider chain.

- Tier lists: `TIER_I1`…`TIER_I7` in `src/intelligence/register_plugins.py` — single source of truth
- `registry.validate_tier()` hard-crashes at startup on any missing plugin name
- All plugins use `compute_next()` for incremental, stateful, O(1) computation
- I7 plugins must consume relevant I6 `ctf_*` sub-scores (Renaissance I6→I7 confluence obligation)
- I7 shared utilities in `src/intelligence/trading/`: `atr_utils`, `confidence_utils`, `signal_schema`, `state_utils`, `exhaustion_utils`, `microstructure_utils`, `volume_profile_utils`, `plugin_utils`

---

## Observability

All metrics pushed via OTel SDK (`src/observability/metrics.py`) — `prometheus_client` fully removed (Phase 83). Call patterns:
- Counters: `.add(1, {"label": val})`
- Histograms: `.record(val, {"label": val})`
- Up-down gauges: `.add(delta, {"label": val})`

Never import `prometheus_client`.

---

## Renaissance Principles Applied

- **Real-time pipeline never touches the database.** WriterAgents are the only DB-aware components.
- **Degrade gracefully.** ProviderMergerAgent auto-fails over on primary silence; BarAuditorAgent publishes gap requests for self-healing recovery; every payload-parsing agent has a DLQ.
- **Never drop data that could contain signal.** Every bar, feature vector, signal, and LLM call is persisted as a labeled training sample.
- **Segment relentlessly.** I6 cross-timeframe confluence scores are computed per regime type, not globally. Signal metrics are tracked per plugin + regime cell.
- **Instrument everything.** All agents expose OTel Golden Signals. Each WriterAgent tracks `persistence_batch_latency` and `persistence_consumer_lag`.
- **Earn the right through proof.** Shadow mode (FeatureSnapshotWriterAgent + ParityAuditorAgent) gates feature promotion behind 60 clean parity cycles (p < 0.05).
