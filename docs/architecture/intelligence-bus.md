# Architecture Reference — IndicAgent Unified Intelligence Bus

Last Updated: 2026-04-21

> Source of truth for architectural decisions. The *why* behind the build sequence.
> Full design doc: `docs/plans/2026-02-22-unified-intelligence-data-bus-design.md`

Status: I1-I8 complete — 128 plugins + 2 aggregation components

---

## Core Architecture

```
IBKR TWS → IBKRProviderAgent (market.bars.raw.ibkr)
                │
                ↓ ProviderMergerAgent
                │   (failover, routing, quality side-channel)
                │   └─ market.data.quality (ProviderQualityEvent)
                │
                market.bars (canonical 1m)
                │
                ├─ BarAggregatorComputeAgent → market.bars.htf (5m-1d)
                ├─ BarWriterAgent → market_data_ohlcv (TimescaleDB)
                ├─ BarAuditorAgent → market.events.gap_requests
                └─ RollComputeAgent → market.events.roll
                        └─ ContractMetadataWriterAgent → contract_metadata (DB)
                │
                ↓ IntelligencePipelineComputeAgent
                │   (I1-I7 unified, subscribes market.bars + market.bars.htf)
                │   ├─ intelligence.journal (BarIntelligenceRecord — atomic per-bar record)
                │   ├─ intelligence.i7.signals (all ranked signals pre-ledger)
                │   └─ lifecycle.transitions (signal state changes)
                │
                ├─ FeatureWriterAgent → intelligence_features (TimescaleDB)
                ├─ FeatureSnapshotWriterAgent → feature_snapshots_shadow (shadow dual-write)
                ├─ ParityAuditorAgent (5-min parity comparison; certifies after 60 clean cycles)
                ├─ SignalWriterAgent → signal_ledger (TimescaleDB)
                ├─ SignalTrackerComputeAgent (lifecycle compute, DB-ignorant)
                │       └─ lifecycle.transitions → LifecycleWriterAgent → signal_ledger
                ├─ SignalAuditorAgent → intelligence.signal.audit
                ├─ SignalMetricsComputeAgent → intelligence.signal_metrics
                │       └─ SignalMetricsWriterAgent → signal_metrics tables (DB)
                ├─ AINarrativeAgent (I8) → narratives → LLMWriterAgent → llm_calls (DB)
                ├─ ServiceAuditorAgent → system.health.events (health monitor + self-healer)
                ├─ SwarmOrchestratorAgent → swarm.alpha.path_a / swarm.alpha.path_b
                │       └─ SwarmWriterAgent → swarm_outputs (DB)
                └─ REST API (:8000) → SSE → Next.js Dashboard (:3000)
```

**Stack choice rationale:** Redpanda (Kafka-compatible) + TimescaleDB — Kafka-native streaming with consumer groups, hot path unchanged, external consumers use REST not Redpanda directly. Right-sized for current scale (60 active instruments × 5 TFs).

---

## Key Architectural Decisions

### 1. Multi-agent bar processing tier before feature computation
`IBKRProviderAgent` publishes raw 1m bars to `market.bars.raw.ibkr`. `ProviderMergerAgent` routes and normalises to `market.bars` (canonical) with an auto-failover on primary silence. `BarAggregatorComputeAgent` aggregates 1m → 5m/15m/1h/4h/1d and publishes to `market.bars.htf`. `IntelligencePipelineComputeAgent` subscribes to both `market.bars` and `market.bars.htf` — each bar triggers an independent I1-I7 in-process pipeline run.

**Why:** Provider-agnostic design — ProviderMergerAgent abstracts the broker. Bar aggregation, persistence, and auditing are separate concerns from intelligence computation. Roll detection and contract promotion run independently without coupling to the hot compute path.

### 2. IntelligenceEvent — versioned, tiered JSONB schema
```python
class IntelligenceEvent(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    ts: datetime; symbol: str; tf: str
    bar_close_ts: datetime | None = None   # actual bar close (differs from ts for HTF)
    bar_id: UUID | None = None             # end-to-end bar traceability (Phase 68-03)
    platform: str = "futures"
    source: Literal["live", "backfill"] = "live"
    session_type: SessionType = SessionType.RTH
    pipeline_latency_ms: float = 0.0
    bar: OHLCVBar
    i1: I1Indicators          # 28 technical indicator outputs
    i2: I2Events              # 11 composite event outputs (MACD/RSI/ADX/Volume events)
    i3: I3Structure           # 9 market structure plugins (swing, S/R, profile, fib)
    i4: I4Context             # 13 context/regime outputs (GARCH, Kalman, VIX, VP, CrossAsset)
    i5: I5Patterns            # 16 pattern recognition outputs
    smc: SMCContext           # 13 smart money outputs (BOS/CHoCH, FVG, OB, HMM, BOCPD)
    i6: I6Confluence          # CrossTimeframeConfluence scores
```

**Why tiered sub-dicts vs flat:** Surgical queries (`SELECT i4->>'garch_sigma'`), smaller GIN indexes per tier, cleaner schema evolution per tier, better TimescaleDB compression.

**Why i7 is NOT in this event:** Signal generation is downstream — published separately via `intelligence.i7.signals` and wrapped with the `IntelligenceEvent` in a `BarIntelligenceRecord` on the `intelligence.journal` topic.

### 3. BarIntelligenceRecord — atomic per-bar persistence unit
`BarIntelligenceRecord` (Phase 44.3 / PIPE-06) wraps the `IntelligenceEvent` with all ranked signals and pipeline funnel counts into a single atomic record on `intelligence.journal`. Single topic, single consumer per writer.

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

**Why:** Replaces the old two-phase UPSERT pattern (i7/i8 separate writes). Every row in `intelligence_features` is now complete at insert time — no partial writes, no orphaned tiers. `FeatureWriterAgent` does a single atomic `INSERT` per bar.

### 4. intelligence_features hypertable — no retention policy
```sql
-- Tiered JSONB columns: bar, i1, i2, i3, i4, i5, smc, i6
-- Compression after 7 days (10-20x ratio; ~40GB → ~2-4GB for 3yr)
-- NO retention policy — seasonal analysis requires multi-year data
-- GIN indexes on i4 (GARCH/Kalman) and smc (smart money)
```

**Why no retention:** 400M rows/3yr is fine with compression. Seasonal patterns require years of history.

### 5. FeatureWriterAgent — standalone async service
`services/feature_writer_agent.py` — consumer group `feature_writer_group`, consumes `intelligence.journal`

**Why separate service:** Async decoupling — can lag, batch writes, retry on DB failure without touching the hot path latency. 50 events per batch or 5s flush window. DLQ: `feature.writer.dlq`.

### 6. signal_ledger — feature reference columns + JOIN pattern
```sql
-- Columns: feature_ts TIMESTAMPTZ, feature_tf TEXT
-- ML training JOIN:
SELECT sl.*, f.i4, f.smc, f.i6
FROM signal_ledger sl
JOIN intelligence_features f ON f.symbol = sl.symbol
  AND f.ts = sl.feature_ts AND f.tf = sl.feature_tf
```

### 7. Signal lifecycle — compute/writer split (Phase 56+)
`SignalTrackerComputeAgent` handles lifecycle compute (activation, MAE/MFE, 8-class outcome) without touching the database — publishes typed `lifecycle.transitions` events. `LifecycleWriterAgent` consumes those events and persists to `signal_ledger`. DLQs: `signal.tracker.dlq`, `lifecycle.writer.dlq`.

**8-class outcome taxonomy:** `never_activated`, `stopped_at_entry`, `stopped_in_trade`, `target_1`, `target_1_2`, `target_full`, `ttl_expired_ahead`, `ttl_expired_behind`

**Why split:** Signal tracker previously violated the compute→Kafka→writer DAG by reading and writing signal_ledger in the same process. The split enforces the core principle: compute agents are DB-ignorant.

### 8. Plugin state — in-memory per-service
Stateful plugins are managed via in-memory dicts (not Redis-backed):
- `_plugin_cache` — plugin singletons built at service init, reused per bar
- `_plugin_states` — `dict[tuple[str,str,str], dict]` keyed by `(plugin_name, symbol, timeframe)`; state is swapped onto `p._state` before `compute_full()` and written back after
- `_plugin_call_counts` — Prometheus metrics sampling (every `PLUGIN_METRICS_SAMPLE_RATE=10` calls)

The `PluginStateManager` (Redis-backed) in `src/core/plugin_state_manager.py` exists but is not used in the hot path. Plugin state resets on service restart (warm-up: ~50 1m bars for I1 incremental state).

### 9. Consumer group naming convention
```
{service_short_name}:{purpose}          # internal
ext:{app_name}:{purpose}               # external

feature_writer_group      → feature_writer_agent
signal_writer:i7          → signal_writer_agent
narrative_agent:i8        → ai_narrative_agent
ext:vercel_dashboard:realtime
ext:ml_trainer:batch
```

### 10. DLQ pattern — every payload-parsing agent has a DLQ
Each agent that deserializes external payloads publishes to a dedicated DLQ topic on parse failure rather than crashing. Pattern: `<domain>.<agent>.dlq`. Full list in stream_keys.py (`topic_*_dlq` functions). Enables post-mortem investigation without data loss.

### 11. Shadow mode infrastructure — parity before promotion
`FeatureSnapshotWriterAgent` dual-writes to `feature_snapshots_shadow` (shadow table). `ParityAuditorAgent` runs 5-min parity comparisons against the canonical `intelligence_features` table and certifies after 60 consecutive clean cycles (`match_rate ≥ 0.95`). Alerts route to `topic_alert_requests` when parity drops below threshold.

### 12. Auth — JWT + API key, single Depends (designed, not yet implemented)
```python
async def verify_auth(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None),
) -> AuthContext:
    if x_api_key: return verify_api_key(x_api_key)    # machine consumers
    if authorization: return verify_jwt(authorization) # human users
    raise HTTPException(401)
```
Storage: `api_keys` table in PostgreSQL (hashed, with metadata).

### 13. ML export — TimescaleDB + Parquet endpoint (designed, not yet built)
```
GET /api/features/export?symbol=ESH6&tf=5m&from=...&tiers=i1,i4,smc&format=parquet
```
Queries `intelligence_features`, flattens JSONB with `jsonb_to_record`, returns Parquet via pyarrow.

### 14. GARCH + Kalman — wired to I7, valuable for ML
Both compute on every bar, output to `IntelligenceEvent.i4`. Use cases:
- **trad_MeanReversion**: gate on `kalman_price_position` (> 1.0 std dev)
- **trad_VWAPDeviation**: `garch_sigma` as dynamic spread threshold
- **trad_SqueezeExpansion**: `garch_vol_regime` check (avoid explosive vol)

### 15. LLM provider chain — adaptive routing
Primary: `OpenRouterProvider` (free models via OpenRouter). Offline fallback: `OllamaProvider` (gemma4:e4b per-signal, phi4-mini:3.8b group synthesis — local Docker on AMD ROCm iGPU). `LLMChain` tries in order, returns first non-None. When a model reaches `is_significant=True` (p<0.05, n≥30), it moves to position 0 in the chain for that `call_type + regime` combination. Key: `openrouter_api_key` (empty → skip to Ollama).

### 16. LLM audit trail — llm_calls hypertable + LLMWriterAgent
Every LLM call is published to `llm.calls` (Kafka) with full request/response context. `LLMWriterAgent` consumes and writes to `llm_calls` hypertable (keep forever). Signal lifecycle exits are published to `llm.outcomes`; `LLMWriterAgent` back-fills realized outcome (pnl_r, mae, mfe) onto historical `llm_calls` records. `llm_model_scores` table tracks per-model performance, refreshed every 15 min.

**Why:** Renaissance principle — every LLM call is a labeled training sample. Once gone, the outcome cannot be recovered.

### 17. Historical backfill — replay fidelity tradeoff
Stage 2 replay writes `source='backfill'`. First ~50 bars have degraded quality (Kalman/GARCH warm-up). Accepted — complexity of saving warm-up state not worth it.

### 18. ServiceAuditorAgent — pipeline health and self-healing
`ServiceAuditorAgent` monitors all active services, publishes typed health state transitions to `system.health.events`, and can trigger restarts on breach of lag/error thresholds. Unhealthy services that exhaust the escalation restart threshold are routed to `intelligence.service_auditor.journal.dlq` for human review.

---

## Stream Keys (canonical)

All stream keys are constructed via `src/core/stream_keys.py` — never hardcoded. Topic names use dots, not colons.

```
# Bar pipeline
{env}.market.bars.raw.{provider}        # per-provider raw bars (IBKRProviderAgent)
{env}.market.bars                        # canonical 1m bars (ProviderMergerAgent)
{env}.market.bars.htf                    # HTF bars 5m-1d (BarAggregatorComputeAgent)
{env}.market.data.quality               # ProviderQualityEvent side-channel

# Market events
{env}.market.events.gap_requests        # gap fill requests (BarAuditorAgent)
{env}.market.events.roll                # roll detection events (RollComputeAgent)
{env}.market.events.contract_update    # front-month promotions (ContractMetadataWriterAgent)
{env}.market.events.roll.dlq           # malformed roll event DLQ

# Intelligence pipeline
{env}.intelligence.journal             # BarIntelligenceRecord — atomic per-bar output
{env}.intelligence.i7.signals          # all ranked I7 signals per bar (pre-ledger)
{env}.intelligence.pipeline.state      # compacted state checkpoints (key: version:symbol:tf)
{env}.intelligence.pipeline.dlq        # unparseable bar payloads
{env}.intelligence.signal.dlq          # null-CIS signals caught before publish
{env}.intelligence.signal.audit        # SignalCoverageGapEvent (SignalAuditorAgent)
{env}.intelligence.signal_metrics      # SignalMetricsComputeAgent output
{env}.intelligence.shadow              # shadow validation only (temporary, manual inspection)

# Lifecycle
{env}.lifecycle.transitions            # signal lifecycle transition events
{env}.lifecycle.writer.dlq

# LLM
{env}.llm.calls                        # every LLM call (success + failure + counterfactual)
{env}.llm.outcomes                     # signal exits with pnl_r/mae/mfe for back-fill
{env}.llm.writer.dlq

# Narratives
{env}.narratives                       # I8 AI narratives (AINarrativeAgent)
{env}.narratives.group                 # group synthesis narratives

# Writer DLQs
{env}.bar.writer.dlq
{env}.feature.writer.dlq
{env}.signal.writer.dlq
{env}.bar.audit.dlq
{env}.signal.audit.dlq
{env}.signal.tracker.dlq

# Swarm (Phase 56)
{env}.intelligence.swarm               # per-AgentResult fan-out (SwarmWriterAgent)
{env}.swarm.alpha.path_a               # deterministic contributor output
{env}.swarm.alpha.path_b               # LLM swarm contributor output
{env}.swarm.world_state                # compacted world state (cleanup.policy=compact)
{env}.swarm.orchestrator.dlq
{env}.swarm.writer.dlq

# ML (Phase 56)
{env}.ml.data_quality.alerts
{env}.ml.discovery.results
{env}.ml.orchestrator.dlq

# Cross-asset
{env}.cross_asset                      # cross-asset spread features (CrossAssetService)
{env}.cross.asset.dlq

# System
{env}.system.events
{env}.system.health.events             # service health state transitions (ServiceAuditorAgent)
{env}.intelligence.service_auditor.journal.dlq  # escalation DLQ
{env}.alert.requests                   # AlertingAgent dispatch (Telegram/Discord)
{env}.gap_fill.dlq                     # gap-fill requests that exhausted retries
{env}.audit                            # parity violations + certification events
```

---

## Key Files

| File | Role |
|------|------|
| `src/intelligence/schemas.py` | `IntelligenceEvent`, `BarIntelligenceRecord`, `RankedSignal` (canonical) |
| `src/core/stream_keys.py` | All stream/topic key construction — never hardcode |
| `src/providers/base_provider_agent.py` | Abstract base — Kafka publish, metrics, SIGTERM for all providers |
| `src/providers/ibkr_adapter.py` | IBKRAdapter wrapping IBKRProvider; all ib_insync logic isolated here |
| `services/ibkr_provider_agent.py` | IBKRProviderAgent — raw 1m bars → market.bars.raw.ibkr |
| `services/provider_merger_agent.py` | ProviderMergerAgent — routes → market.bars, auto-failover, quality side-channel |
| `services/bar_aggregator_agent.py` | BarAggregatorComputeAgent — 1m → HTF via BarAccumulator → market.bars.htf |
| `services/bar_writer_agent.py` | BarWriterAgent — market.bars + market.bars.htf → market_data_ohlcv |
| `services/bar_auditor_agent.py` | BarAuditorAgent — gap detection → market.events.gap_requests |
| `services/roll_compute_agent.py` | RollComputeAgent — calendar + volume z-score roll detection → market.events.roll |
| `services/contract_metadata_writer_agent.py` | ContractMetadataWriterAgent — roll events → front-month promotion in contract_metadata |
| `services/intelligence_pipeline_agent.py` | Unified I1-I7; subscribes market.bars + market.bars.htf |
| `services/feature_writer_agent.py` | FeatureWriterAgent — intelligence.journal → intelligence_features (batch, async) |
| `services/feature_snapshot_writer_agent.py` | FeatureSnapshotWriterAgent — shadow dual-write → feature_snapshots_shadow |
| `services/parity_auditor_agent.py` | ParityAuditorAgent — 5-min parity comparison; certifies after 60 clean cycles |
| `services/signal_writer_agent.py` | SignalWriterAgent — intelligence.i7.signals → signal_ledger (new rows) |
| `services/signal_tracker_compute_agent.py` | SignalTrackerComputeAgent — lifecycle compute (DB-ignorant); publishes lifecycle.transitions |
| `services/lifecycle_writer_agent.py` | LifecycleWriterAgent — lifecycle.transitions → signal_ledger lifecycle updates |
| `services/signal_auditor_agent.py` | SignalAuditorAgent — coverage validation + lag monitoring → intelligence.signal.audit |
| `services/signal_metrics_compute_agent.py` | SignalMetricsComputeAgent — timer-triggered performance metrics |
| `services/signal_metrics_writer_agent.py` | SignalMetricsWriterAgent — intelligence.signal_metrics → signal_metrics tables |
| `services/ai_narrative_agent.py` | AINarrativeAgent — I8 LLM analysis → narratives |
| `services/llm_writer_service.py` | LLMWriterAgent — llm.calls → llm_calls; outcome back-fill; model score refresh |
| `services/cross_asset_service.py` | CrossAssetService — cross-asset spread dynamics → cross_asset |
| `services/service_auditor_agent.py` | ServiceAuditorAgent — pipeline health monitor and self-healer |
| `services/swarm_orchestrator_agent.py` | SwarmOrchestratorAgent — routes swarm tasks to specialist agents |
| `services/swarm_writer_agent.py` | SwarmWriterAgent — persists swarm outputs to DB |
| `src/core/database_manager.py` | PostgreSQL/TimescaleDB connection pooling (WriterAgents + API only) |
| `src/api/routes/sse.py` | SSE endpoint → dashboard |
| `production/scripts/historical_backfill.py` | Historical IBKR fetch + I1-I7 replay |
| `production/migrations/` | All DB migrations |
