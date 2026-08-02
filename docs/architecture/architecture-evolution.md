# IndicAgent v2.8 — Historical Architecture Snapshot (v2.x pipeline, ARCHIVED)

**Version:** 2.8
**Status:** historical — describes the ARCHIVED v2.x I1-I7 pipeline, not current production architecture
**Last Updated:** 2026-05-27 (staleness note added 2026-07-31)
**Tags:** architecture, evolution, versioning, pipeline, swarm, ml-infrastructure

> **This document no longer describes current production architecture.** Per CLAUDE.md, the
> v2.x pipeline this doc documents (`IntelligencePipeline`, `intelligence_features`,
> `signal_ledger`, I1-I7 plugins) is **ARCHIVED with no live consumer as of 2026-07-02**. Live
> production architecture is v3.0's Feature Factory / AlphaEngine pipeline: `IBKR TWS →
> FeatureVectorPipeline → FeatureVectorWriter → feature_vectors → forward_return_writer →
> ic_engine → ensemble_trainer/EnsembleICEngine → alpha_publisher → alpha_events`. See
> `CLAUDE.md`'s Architecture and Pipeline sections and `src/intelligence/CLAUDE.md` for current
> state. This doc is retained as a historical record of the v2.0-v2.7 evolution (the version
> history below is accurate as *history*); do not use it to answer "what does the system do
> today."
>
> **Decision (todo 220, 2026-08-01): stays in place, not moved to `docs/architecture/archive/`.**
> Per user direction, the project intends to eventually revive this v2.x path as a second, more
> conventional intelligence path running alongside v3.0's Renaissance-style AlphaEngine — not to
> retire it permanently. Treating this doc as pure dead history and archiving it away would work
> against that plan; it's the closest thing to a design reference for what gets revived. Re-check
> this decision if the revival is later abandoned outright.

## Executive Summary

IndicAgent v2.8 is a real-time market intelligence platform with a unified I1-I7 pipeline, separate persistence layer, and swarm foundation for multi-agent AI. The core philosophy is **agentic decomposition** — each node in the DAG is an autonomous, event-driven agent with clear boundaries.

## Architecture Evolution

### v2.0 — Data Foundation
Established core data-layer patterns:
- Clock-driven bar emission — guaranteed 1-minute cadence from TWS
- Zero-loss Kafka guarantee — `auto_offset_reset="earliest"` + explicit `commit()`
- Multi-stream reconciliation — 5s real-time bars vs 1m audited comparison
- `BarAccumulator` — stateless windowed HTF aggregation with session-break logic

### v2.1 — Agentic DAG Refactor
Introduced strict agent role separation:
- `BaseAgent` unification — lifecycle, OTel Golden Signals, graceful SIGTERM drain for every service
- Dedicated Writers — DB-ignorant compute principle enforced across the board
- `BaseProvider` + adapter pattern — adding a data source = one subclass, nothing downstream changes
- `ProviderMerger` — multi-provider failover and routing abstraction

### v2.2 — Unified Intelligence Pipeline
Consolidated I1-I7 into a single in-process agent:
- `IntelligencePipeline` — eliminated Kafka hops between tiers (I6→I7 is direct dependency)
- State checkpointing to compacted topic — eliminates warmup on restart
- I1 + I7 tiers parallelized via `asyncio.gather` + ThreadPoolExecutor — ~60% latency reduction
- `SignalWriter` — dedicated persistence agent for `signal_ledger`
- Identified I2-I6 sequential bottleneck (73% of latency) — batch processing is the planned fix

### v2.3 — Swarm Foundation + ML Infrastructure
- `AlphaSwarm` + `LineageWriter` — lineage-first swarm foundation; per-agent predictions persist to `signal_lineage`
- LLM layer extracted into standalone `llm_providers.py` module
- `BarIntelligenceRecord` — atomic per-bar record on `intelligence.journal` (Phase 44.3 / PIPE-06); single INSERT per bar replaces two-phase UPSERT
- Nightly `roll-batch` timer — automated futures roll detection and front-month promotion (replaces 24/7 roll-compute daemon)
- `SignalTracker` + `LifecycleWriter` — signal lifecycle compute/writer split; tracker is now DB-ignorant
- ML timer agents: `MLDataQualityAgent`, `MLDiscoveryAgent`, `MLOrchestratorAgent`

### v2.4 — Observability Hardening
- `ServiceAuditor` — pipeline health monitor and self-healer; publishes to `system.health.events`
- `FeatureSnapshotWriter` + `ParityAuditor` — shadow dual-write with 60-cycle parity certification
- `SignalAuditor` + `SignalMetricsAnalyzer` + `SignalMetricsWriter` — signal coverage + performance metric pipeline
- DLQ topics standardized across all payload-parsing agents (Plan 067-07)
- `bar_id` UUID traceability end-to-end from bar ingestion through signal generation (Phase 68-03)

### v2.5–v2.7 — Mathematical Correctness + Storage Hardening
- Signal schema v1 (`SIGNAL_SCHEMA_VERSION = "v1"` in `src/intelligence/trading/signal_schema.py`) — canonical version constant
- `expires_at` TTL column in `signal_ledger` — bar-time wall-clock evaluation (`bars_elapsed = (current_ts - signal_ts) / tf_seconds`), computed at INSERT time
- `entry_zone_low` / `entry_zone_high` columns in `signal_ledger` — no more LATERAL JOIN to `intelligence_features` for replay
- `tf_to_seconds()` utility in `src/core/service_utils.py`
- OTel SDK fully replaces `prometheus_client` (Phase 83) — all metrics via `src/observability/metrics.py`
- Plugin count: 132 total across I1–I7

**Tooling stack (LGTM + AI):** All telemetry flows through a central OTel Collector (`:4317` gRPC) — services push metrics, traces, and logs via OTLP rather than exposing per-service HTTP scrape endpoints. Collector fans out to Prometheus (metrics → Grafana `:3001`), Tempo (traces), and Loki (logs). Full pipeline: `docs/platform/platform-observability.md`.

## Active Services

| Service | File | Systemd Unit | Metrics Port | Purpose |
|---------|------|--------------|--------------|---------|
| IBKR Provider | `ibkr_provider.py` | `indicagent-ibkr-provider` | :9129 | IBKR dual streams (5s RTB + 1m aggregation) |
| Provider Merger | `provider_merger.py` | `indicagent-provider-merger` | :9130 | Routes `market.bars.raw.*` → `market.bars` |
| Bar Aggregator | `bar_aggregator.py` | `indicagent-bar-aggregator-compute` | :9120 | 1m → HTF (5m-1d) aggregation |
| Bar Writer | `bar_writer.py` | `indicagent-bar-writer` | :9121 | Writes `market_data_ohlcv` (batch) |
| Bar Auditor | `bar_auditor.py` | `indicagent-bar-auditor` | :9123 | Gap detection → `market.events.gap_requests` |
| Roll Batch | `scripts/ops/roll/ops_roll_batch.py` | `indicagent-roll-batch` (timer, 8pm) | — | Calendar-based futures roll detection + front-month promotion |
| Intelligence Pipeline | `intelligence_pipeline_agent.py` | `indicagent-intelligence-pipeline` | :9125 | I1-I7 unified, in-process |
| Signal Writer | `signal_writer_agent.py` | `indicagent-signal-writer` | :9119 | Writes `signal_ledger` (batch) |
| Signal Tracker | `signal_tracker_compute_agent.py` | `indicagent-signal-tracker-compute` | :9115 | Signal lifecycle compute (DB-ignorant); publishes transitions to LifecycleWriter |
| Lifecycle Writer | `lifecycle_writer_agent.py` | `indicagent-lifecycle-writer` | — | Persists signal lifecycle transitions to `signal_outcomes` |
| Signal Metrics Compute | `signal_metrics_compute_agent.py` | `indicagent-signal-metrics-compute` | :9126 | Timer-triggered signal performance metrics |
| Signal Metrics Writer | `signal_metrics_writer_agent.py` | `indicagent-signal-metrics-writer` | :9127 | Persists signal metrics to DB |
| Signal Auditor | `signal_auditor_agent.py` | `indicagent-signal-auditor` | :9128 | Coverage validation + lag monitoring |
| Signal Replay Auditor | `signal_replay_auditor_agent.py` | `indicagent-signal-replay` | — | TTL/expires_at driven signal expiry; reads entry_zone_low/high from signal_ledger directly |
| Feature Writer | `feature_writer_agent.py` | `indicagent-feature-writer` | :9116 | Writes `intelligence_features` (batch) |
| Feature Snapshot Writer | `feature_snapshot_writer_agent.py` | `indicagent-feature-snapshot-writer` | :9132 | Shadow dual-write → `feature_snapshots_shadow` |
| Parity Auditor | `parity_auditor_agent.py` | `indicagent-parity-auditor` | :9133 | 5-min parity comparison; certifies after 60 clean cycles |
| LLM Writer | `llm_writer_service.py` | `indicagent-llm-writer` | :9117 | Writes `llm_calls` + outcome back-fill |
| AI Narrative | `narrative_group_compute_agent.py` | `indicagent-ai-narrative` | :9113 | I8 LLM analysis |
| Cross Asset | `cross_asset_service.py` | `indicagent-cross-asset` | :9118 | Cross-asset spread dynamics |
| Service Auditor | `service_auditor.py` | `indicagent-service-auditor` | :9131 | Pipeline health monitor and self-healer |
| Alpha Swarm | `alpha_swarm_agent.py` | `indicagent-alpha-swarm` | — | Runs alpha agents on I7 signals; emits signal lineage |
| Lineage Writer | `lineage_writer_agent.py` | `indicagent-lineage-writer` | — | Persists signal-affecting lineage to `signal_lineage` |
| ML Data Quality | `ml_data_quality_agent.py` | `indicagent-ml-data-quality` (timer) | — | Audits `intelligence_features` for training data quality |
| ML Discovery | `ml_discovery_agent.py` | `indicagent-ml-discovery` (timer) | — | Discovers ML training signal patterns |
| ML Orchestrator | `ml_orchestrator_agent.py` | `indicagent-ml-orchestrator` (timer) | — | Orchestrates ML training pipeline |
| API | `src/api/main.py` | `indicagent-api` | :8000 | FastAPI + SSE |
| Dashboard | `dashboard/` | `indicagent-dashboard` | :3000 | Next.js dev server |

**ML batch services (timer-triggered, not daemons):** `inactive (dead)` between runs is correct.
- `ml-training` (nightly 11pm), `ml-orchestrator`/`ml-data-quality`/`ml-discovery` (weekly Mon)
- `roll-batch` (nightly 8pm) — calendar-based futures roll detection + contract promotion

## Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              LAYER 1: DATA                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  IBKR TWS → IBKRProvider (market.bars.raw.ibkr)                        │
│                              ↓                                               │
│                    ProviderMerger                                      │
│                    (failover, routing)                                      │
│                              ↓                                               │
│                    market.bars (canonical 1m)                               │
│                              ↓                                               │
│           BarAggregator (market.bars.htf)                       │
│                    (1m → 5m/15m/1h/4h/1d)                                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LAYER 2-3: INTELLIGENCE                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│           IntelligencePipeline                                  │
│           (I1→I7 unified, IN-PROCESS)                                      │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │ I1: Technical Indicators (28 plugins)                              │   │
│  │   → ATR, RSI, MACD, ADX, BB, VWAP, Stoch, OFI, CVD, etc.          │   │
│  ├────────────────────────────────────────────────────────────────────┤   │
│  │ I2: Composite Events (10 plugins)                                  │   │
│  │   → MACDEvents, RSIEvents, ADXEvents, VolumeEvents, etc.           │   │
│  ├────────────────────────────────────────────────────────────────────┤   │
│  │ I3: Market Structure (8 plugins)                                   │   │
│  │   → Swing, S/R, MarketProfile, SessionLevels, FibZones, etc.       │   │
│  ├────────────────────────────────────────────────────────────────────┤   │
│  │ I4: Context / Regime (12 plugins)                                  │   │
│  │   → GARCH, Kalman, HurstExp, VIXRegime, CrossAsset, VWAP, VP       │   │
│  ├────────────────────────────────────────────────────────────────────┤   │
│  │ I5: Pattern Recognition (16 plugins)                               │   │
│  │   → RSIDivergence, BollingerSqueeze, chart patterns, etc.          │   │
│  ├────────────────────────────────────────────────────────────────────┤   │
│  │ SMC: Smart Money Concepts (16 plugins)                             │   │
│  │   → BOS/CHoCH, FVG, OrderBlocks, HMMRegime x4, BOCPD, etc.         │   │
│  ├────────────────────────────────────────────────────────────────────┤   │
│  │ I6: CrossTimeframeConfluence (6 plugins)                           │   │
│  │   → Multi-TF trend/structure/regime/SMC alignment scores           │   │
│  ├────────────────────────────────────────────────────────────────────┤   │
│  │ I7: Signal Generation (36 + 2 agg)                                 │   │
│  │   → Directional signals with confidence                            │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                              ↓                         ↓                   │
│              intelligence.journal           intelligence.i7.signals        │
│                    (tiered JSONB)              (winner signal)             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓                ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LAYER 4: PERSISTENCE                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  FeatureWriter → intelligence_features (DB)                           │
│  SignalWriter → signal_ledger (DB)                                    │
│  SignalTracker → lifecycle updates (DB via LifecycleWriter)      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LAYER 5: CONSUMERS                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  AI Narrative Service (I8) → LLM analysis → narratives topics               │
│  Dashboard → SSE → Real-time UI                                             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Redpanda Topics

| Topic | Purpose | Key Schema |
|-------|---------|------------|
| `market.bars.raw.ibkr` | IBKR raw 5s RTB + 1m bars | `BarEvent` |
| `market.bars` | Canonical 1m bars (routed) | `BarEvent` |
| `market.bars.htf` | HTF bars (5m-1d) | `BarEvent` |
| `intelligence.journal` | Full I1-I7 feature vector | `IntelligenceEvent` |
| `intelligence.i7.signals` | Winner I7 signal | `SignalEvent` |
| `narratives` | I8 LLM analysis | `NarrativeEvent` |
| `market.events.gap_requests` | Gap fill requests | `GapRequestEvent` |
| `cross_asset` | Cross-asset spreads | `CrossAssetEvent` |

## Database Tables

| Table | Purpose | Retention |
|-------|---------|-----------|
| `market_data_ohlcv` | Raw OHLCV ground truth | Forever |
| `intelligence_features` | Full I1-I7 feature vectors (ML training) | Forever |
| `signal_ledger` | ALL I7 signals + fire-time fields (entry_zone_low/high, expires_at) | Forever |
| `signal_outcomes` | Signal lifecycle state (status, activated_at, exit_at, pnl_r, mae, mfe) | Forever |
| `signal_lineage` | Signal-affecting transforms and agent predictions | Forever |
| `llm_calls` | LLM audit log + outcomes | Forever |
| `llm_model_scores` | Per-model win rates | 15min refresh |
| `instruments` | Active contracts | Current |

## Agent Classes

**Base class corrected 2026-07-31:** this table originally said `BaseAgent` throughout; the base
class was renamed `BaseDaemon` during the v3.0 rebuild (`src/core/agent/base.py`; see
`docs/agents/agents-foundation.md`). Several of the files below (`intelligence_pipeline_agent.py`,
`feature_writer_agent.py`, `signal_writer_agent.py`, `signal_tracker_compute_agent.py`,
`parity_auditor_agent.py`) belong to the ARCHIVED v2.x pipeline per this doc's header note and
may no longer exist under these names — this table is left as a historical record of the v2.x
class layout, only the base-class name is corrected.

| Role | Class | Base | File |
|------|-------|------|------|
| Provider | `IBKRProvider` | `BaseProvider` | `services/ibkr_provider.py` |
| Merger | `ProviderMerger` | `BaseDaemon` | `services/provider_merger.py` |
| Compute | `IntelligencePipeline` | `BaseDaemon` | `services/intelligence_pipeline_agent.py` |
| Compute | `BarAggregator` | `BaseDaemon` | `services/bar_aggregator.py` |
| Auditor | `BarAuditor` | `BaseDaemon` | `services/bar_auditor.py` |
| Auditor | `ParityAuditor` | `BaseDaemon` | `services/parity_auditor_agent.py` |
| Writer | `BarWriter` | `BaseWriter` | `services/bar_writer.py` |
| Writer | `FeatureWriter` | `BaseWriter` | `services/feature_writer_agent.py` |
| Writer | `SignalWriter` | `BaseWriter` | `services/signal_writer_agent.py` |
| Tracker | `SignalTracker` | `BaseDaemon` | `services/signal_tracker_compute_agent.py` |

## Intelligence Tiers

| Tier | Plugins | Output |
|------|---------|--------|
| I1 | 28 | Technical indicators + OFI + CVD |
| I2 | 10 | Composite events (MACD, RSI, ADX, volume, etc.) |
| I3 | 8 | Market structure (swing, S/R, profile, session, fib) |
| I4 | 12 | Context/regime (GARCH, Kalman, VIX, CrossAsset, VWAP, VP) |
| I5 | 16 | Pattern detection (divergence, squeeze, chart patterns) |
| SMC | 16 | Smart Money (BOS/CHoCH, FVG, OB, HMM x4, BOCPD, etc.) |
| I6 | 6 | CrossTimeframeConfluence + 5 confluence plugins |
| I7 | 36 + 2 agg | Trading signals + CISScorer + SignalAggregator |
| I8 | — | LLM narratives (separate service) |

**Total:** 132 plugins + 2 aggregation components. Source of truth: `TIER_I*` in `src/intelligence/register_plugins.py`.

## Signal Ledger Schema (post-Phase 107.5)

The `signal_ledger` table now stores all fire-time fields directly — no LATERAL JOIN to `intelligence_features` needed for replay:

| Column | Purpose |
|--------|---------|
| `expires_at` | Bar-time wall-clock TTL. Computed at INSERT: `timestamp + ttl_bars * tf_to_seconds(timeframe)`. Evaluated by `signal_replay_auditor_agent` using `expires_at < NOW()`. |
| `entry_zone_low` | Lower bound of the entry zone. Written at fire time from `TradeFrame.zone_low`. |
| `entry_zone_high` | Upper bound of the entry zone. Written at fire time from `TradeFrame.zone_high`. |

Signal status strings: `"pending"`, `"active"`, `"regime_suppressed"` — raw string literals (also available as `SignalStatus` enum in `signal_ledger_repository.py`).

## Key Principles

1. **Database Ignorance** — Compute agents never touch DB. Persistence is decoupled via Writers.
2. **Typed Event Bus** — All intelligence flows through `IntelligenceEvent` with tiered JSONB.
3. **Graceful Degradation** — DLQ topics, circuit breakers, and shadow modes for new features.
4. **Instrument Everything** — OTel SDK + Grafana for all Golden Signals (`prometheus_client` removed).
5. **Segregated Timeframes** — Separate HTF topics prevent I1 warmup on every 1m bar.

---

## Performance Characteristics

### Current Throughput

| Metric | Value | Context |
|--------|-------|---------|
| **Throughput** | ~4.5 bars/sec | Single symbol, all timeframes |
| **Latency** | ~220ms/bar | End-to-end I1→I7 |
| **Plugin Count** | 132 + 2 agg | 28 I1, 10 I2, 8 I3, 12 I4, 16 I5, 16 SMC, 6 I6, 36 I7 (+2 aggregation) |

### Parallelization Architecture

**Tier Parallelization:**
- **I1 (28 plugins)** — parallelized via `asyncio.gather` + ThreadPoolExecutor
- **I7 (36 plugins)** — parallelized via `asyncio.gather` + ThreadPoolExecutor
- **I2-I6** — sequential execution (current bottleneck)

**Latency Breakdown (Per Bar):**
- I1 (parallel): ~30ms
- I2 (sequential): ~40ms
- I3 (sequential, 8 plugins): ~50ms
- I4 (sequential, 12 plugins): ~40ms
- I5-I6 (sequential): ~30ms
- I7 (parallel): ~20ms

**GIL Bottleneck:** Python's Global Interpreter Lock prevents ThreadPoolExecutor from achieving true parallelism. Only one thread executes Python bytecode at a time, regardless of worker count. CPU-bound work (plugin compute) cannot utilize multiple cores.

### Optimization Strategies

**Individual Plugin Vectorization:**
- **What:** Rewrite plugins in numpy vectorized form
- **Impact:** 46x faster for OBVMomentum (8057ms → 177ms)
- **Throughput gain:** **None** — bottleneck is sequential tier execution, not plugin speed
- **When useful:** If tier itself becomes bottleneck after parallelization

**Batch Processing:**
- **What:** Process 100+ bars in single pass through all tiers
- **Impact:** Expected 10-50x throughput improvement (amortizes sequential tier cost)
- **Trade-off:** Increased latency (accumulate 100 bars OR 5s timeout)
- **Status:** Planned optimization

**Process-Level Parallelism:**
- **What:** Use multiprocessing instead of threading (bypasses GIL)
- **Impact:** Could parallelize I2-I6 tiers across processes
- **Trade-off:** High overhead (process spawn, IPC serialization)
- **Status:** Not pursued unless batch processing insufficient

**See:** `docs/architecture/pipeline-optimization.md` for detailed strategy and `docs/research/pipeline-throughput-bottleneck-analysis.md` for profiling analysis.

---

## What Makes This Architecture Unique

| Aspect | Typical Systems | IndicAgent | Advantage |
|--------|----------------|-------------|-----------|
| **Extensibility** | Hardcoded indicators, core changes required | Plugin-native: empty container, add via registration | Zero risk to existing functionality |
| **Execution Ordering** | Manual config, maintenance burden | Emerges from plugin inputs/outputs (Kahn's algorithm) | Circular deps detected at startup |
| **Database Coupling** | DB in critical path, latency sensitive | Compute agents DB-ignorant, async Writers | DB outage = zero impact on hot path |
| **Provider Switching** | Hardcoded, invasive | Merger pattern isolates all downstream consumers | Add/remove providers without changes |
| **Signal Selection** | Ad-hoc, opaque | CIS requires 3/6 evidence buckets agree | Full transparency, provable quality |
| **Feature Promotion** | Deploy to production, hope for best | Shadow mode with p < 0.05 statistical gates | No production losses from unproven features |
| **Drift Handling** | Manual recalibration | KS/CUSUM auto-correction | System self-adjusts |
| **Computation** | Full recomputation | O(1) incremental updates (141x speedup) | Sub-ms per plugin latency |

### Advanced Patterns

**Convergence Gate (StreamMerger):** All tiered outputs (I1, I3, I4, SMC) join into a single, unified `intelligence.journal` entry before persistence. Guarantees atomicity — no partial writes, no orphaned tiers.

**Provider Isolation:** `ProviderMerger` subscribes to `market.bars.raw.<provider>` topics and routes canonical bars to `market.bars`. Downstream consumers never know provider topology changed. Adding a data source = one subclass.

**Shadow Mode Infrastructure:** Every feature runs in shadow before production. `shadow_promotion_ready` gates require statistical significance (p < 0.05, N ≥ 100) before production eligibility.

**Evidence-Graded Signals:** CIS (Confluence Intelligence Score) fires only when 3 of 6 independent evidence buckets agree. Single dominant bucket cannot override. Full attribution logged per signal.

**Hot/Warm/Cold Separation:** Compute agents (hot) → Redpanda (warm) → Writers (cold). Database latency never affects hot path. Service restart resumes from committed offset — nothing lost.

---

## See Also

- `docs/agents/agents-foundation.md` — BaseDaemon lifecycle contract and role taxonomy
- `docs/agents/agents-operations.md` — Service mesh, DAG topology, and operations
- `observability.md` — Metrics and monitoring patterns
- `CLAUDE.md` — current v3.0 pipeline and architecture (supersedes this doc's "current state" framing)
