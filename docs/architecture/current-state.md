# IndicAgent v2.4 — Current Architecture State

**Version:** 2.4
**Last Updated:** 2026-04-21
**Status:** v2.4 Observability Hardening — Phase 71 complete; v2.3 ML Foundation deferred pending 30+ days clean signal data

> This is the single source of truth for the current production architecture. For design history and evolution, see `archive/`.

## Executive Summary

IndicAgent v2.2 is a real-time market intelligence platform with a unified I1-I7 pipeline, separate persistence layer, and swarm foundation for multi-agent AI. The core philosophy is **agentic decomposition** — each node in the DAG is an autonomous, event-driven agent with clear boundaries.

## Architecture Evolution

### v2.0 — Data Foundation
Established core data-layer patterns:
- Clock-driven bar emission — guaranteed 1-minute cadence from TWS
- Zero-loss Kafka guarantee — `auto_offset_reset="earliest"` + explicit `commit()`
- Multi-stream reconciliation — 5s real-time bars vs 1m audited comparison
- `BarAccumulator` — stateless windowed HTF aggregation with session-break logic

### v2.1 — Agentic DAG Refactor
Introduced strict agent role separation:
- `BaseAgent` unification — lifecycle, Prometheus Golden Signals, graceful SIGTERM drain for every service
- Dedicated WriterAgents — DB-ignorant compute principle enforced across the board
- `BaseProviderAgent` + adapter pattern — adding a data source = one subclass, nothing downstream changes
- `ProviderMergerAgent` — multi-provider failover and routing abstraction

### v2.2 — Unified Intelligence Pipeline
Consolidated I1-I7 into a single in-process agent:
- `IntelligencePipelineComputeAgent` — eliminated Kafka hops between tiers (I6→I7 is direct dependency)
- State checkpointing to compacted topic — eliminates warmup on restart
- I1 + I7 tiers parallelized via `asyncio.gather` + ThreadPoolExecutor — ~60% latency reduction
- `SignalWriterAgent` — dedicated persistence agent for `signal_ledger`
- Identified I2-I6 sequential bottleneck (73% of latency) — batch processing is the planned fix

### v2.3 — Swarm Foundation + ML Infrastructure
- `SwarmOrchestratorAgent` + `SwarmWriterAgent` — swarm plumbing services live (Phase 56)
- LLM layer extracted into standalone `llm_providers.py` module
- `BarIntelligenceRecord` — atomic per-bar record on `intelligence.journal` (Phase 44.3 / PIPE-06); single INSERT per bar replaces two-phase UPSERT
- `RollComputeAgent` + `ContractMetadataWriterAgent` — automated futures roll detection and front-month promotion
- `SignalTrackerComputeAgent` + `LifecycleWriterAgent` — signal lifecycle compute/writer split; tracker is now DB-ignorant
- ML timer agents: `MLDataQualityAgent`, `MLDiscoveryAgent`, `MLOrchestratorAgent`

### v2.4 — Observability Hardening (current)
- `ServiceAuditorAgent` — pipeline health monitor and self-healer; publishes to `system.health.events`
- `FeatureSnapshotWriterAgent` + `ParityAuditorAgent` — shadow dual-write with 60-cycle parity certification
- `SignalAuditorAgent` + `SignalMetricsComputeAgent` + `SignalMetricsWriterAgent` — signal coverage + performance metric pipeline
- `ContractMetadataWriterAgent` — `ContractUpdateEvent` cache invalidation for downstream agents
- DLQ topics standardized across all payload-parsing agents (Plan 067-07)
- `bar_id` UUID traceability end-to-end from bar ingestion through signal generation (Phase 68-03)

## Active Services

| Service | File | Systemd Unit | Metrics Port | Purpose |
|---------|------|--------------|--------------|---------|
| IBKR Provider | `ibkr_provider_agent.py` | `indicagent-ibkr-provider` | :9129 | IBKR dual streams (5s RTB + 1m aggregation) |
| Provider Merger | `provider_merger_agent.py` | `indicagent-provider-merger` | :9130 | Routes `market.bars.raw.*` → `market.bars` |
| Bar Aggregator | `bar_aggregator_agent.py` | `indicagent-bar-aggregator-compute` | :9120 | 1m → HTF (5m-1d) aggregation |
| Bar Writer | `bar_writer_agent.py` | `indicagent-bar-writer` | :9121 | Writes `market_data_ohlcv` (batch) |
| Bar Auditor | `bar_auditor_agent.py` | `indicagent-bar-auditor` | :9123 | Gap detection → `market.events.gap_requests` |
| Roll Compute | `roll_compute_agent.py` | `indicagent-roll-compute` | :9122 | Calendar + volume z-score roll detection |
| Contract Metadata Writer | `contract_metadata_writer_agent.py` | `indicagent-contract-metadata-writer` | :9124 | Consumes roll events → promotes front-month in `contract_metadata` |
| Intelligence Pipeline | `intelligence_pipeline_agent.py` | `indicagent-intelligence-pipeline` | :9125 | I1-I7 unified, in-process |
| Signal Writer | `signal_writer_agent.py` | `indicagent-signal-writer` | :9119 | Writes `signal_ledger` (batch) |
| Signal Tracker | `signal_tracker_compute_agent.py` | `indicagent-signal-tracker-compute` | :9115 | Signal lifecycle compute (DB-ignorant); publishes transitions to LifecycleWriterAgent |
| Lifecycle Writer | `lifecycle_writer_agent.py` | `indicagent-lifecycle-writer` | — | Persists signal lifecycle transitions to `signal_ledger` |
| Signal Metrics Compute | `signal_metrics_compute_agent.py` | `indicagent-signal-metrics-compute` | :9126 | Timer-triggered signal performance metrics |
| Signal Metrics Writer | `signal_metrics_writer_agent.py` | `indicagent-signal-metrics-writer` | :9127 | Persists signal metrics to DB |
| Signal Auditor | `signal_auditor_agent.py` | `indicagent-signal-auditor` | :9128 | Coverage validation + lag monitoring |
| Feature Writer | `feature_writer_agent.py` | `indicagent-feature-writer` | :9116 | Writes `intelligence_features` (batch) |
| Feature Snapshot Writer | `feature_snapshot_writer_agent.py` | `indicagent-feature-snapshot-writer` | :9132 | Shadow dual-write → `feature_snapshots_shadow` |
| Parity Auditor | `parity_auditor_agent.py` | `indicagent-parity-auditor` | :9133 | 5-min parity comparison; certifies after 60 clean cycles |
| LLM Writer | `llm_writer_service.py` | `indicagent-llm-writer` | :9117 | Writes `llm_calls` + outcome back-fill |
| AI Narrative | `ai_narrative_service.py` | `indicagent-ai-narrative` | :9113 | I8 LLM analysis |
| Cross Asset | `cross_asset_service.py` | `indicagent-cross-asset` | :9118 | Cross-asset spread dynamics |
| Service Auditor | `service_auditor_agent.py` | `indicagent-service-auditor` | :9131 | Pipeline health monitor and self-healer |
| Swarm Orchestrator | `swarm_orchestrator_agent.py` | `indicagent-swarm-orchestrator` | — | Routes swarm tasks to specialist agents |
| Swarm Writer | `swarm_writer_agent.py` | `indicagent-swarm-writer` | — | Persists swarm outputs to DB |
| ML Data Quality | `ml_data_quality_agent.py` | `indicagent-ml-data-quality` (timer) | — | Audits `intelligence_features` for training data quality |
| ML Discovery | `ml_discovery_agent.py` | `indicagent-ml-discovery` (timer) | — | Discovers ML training signal patterns |
| ML Orchestrator | `ml_orchestrator_agent.py` | `indicagent-ml-orchestrator` (timer) | — | Orchestrates ML training pipeline |
| API | `src/api/main.py` | `indicagent-api` | :8000 | FastAPI + SSE |
| Dashboard | `dashboard/` | `indicagent-dashboard` | :3000 | Next.js dev server |
| Weight Updater | `src/intelligence/weight_updater.py` | `indicagent-weight-updater` | — (oneshot) | Daily CIS weight refresh |

## Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              LAYER 1: DATA                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  IBKR TWS → IBKRProviderAgent (market.bars.raw.ibkr)                        │
│                              ↓                                               │
│                    ProviderMergerAgent                                      │
│                    (failover, routing)                                      │
│                              ↓                                               │
│                    market.bars (canonical 1m)                               │
│                              ↓                                               │
│           BarAggregatorComputeAgent (market.bars.htf)                       │
│                    (1m → 5m/15m/1h/4h/1d)                                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LAYER 2-3: INTELLIGENCE                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│           IntelligencePipelineComputeAgent                                  │
│           (I1→I7 unified, IN-PROCESS)                                      │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │ I1: Technical Indicators (28 plugins)                              │   │
│  │   → ATR, RSI, MACD, ADX, BB, VWAP, Stoch, OFI, CVD, etc.          │   │
│  ├────────────────────────────────────────────────────────────────────┤   │
│  │ I2: Composite Events (11 plugins)                                  │   │
│  │   → MACDEvents, RSIEvents, ADXEvents, VolumeEvents, etc.           │   │
│  ├────────────────────────────────────────────────────────────────────┤   │
│  │ I3: Market Structure (9 plugins)                                   │   │
│  │   → Swing, S/R, MarketProfile, SessionLevels, FibZones, etc.       │   │
│  ├────────────────────────────────────────────────────────────────────┤   │
│  │ I4: Context / Regime (13 plugins)                                  │   │
│  │   → GARCH, Kalman, HurstExp, VIXRegime, CrossAsset, VWAP, VP       │   │
│  ├────────────────────────────────────────────────────────────────────┤   │
│  │ I5: Pattern Recognition (16 plugins)                               │   │
│  │   → RSIDivergence, BollingerSqueeze, chart patterns, etc.          │   │
│  ├────────────────────────────────────────────────────────────────────┤   │
│  │ SMC: Smart Money Concepts (13 plugins)                             │   │
│  │   → BOS/CHoCH, FVG, OrderBlocks, HMMRegime, BOCPD, etc.            │   │
│  ├────────────────────────────────────────────────────────────────────┤   │
│  │ I6: CrossTimeframeConfluence (1 plugin)                            │   │
│  │   → Multi-TF trend/structure/regime/SMC alignment scores           │   │
│  ├────────────────────────────────────────────────────────────────────┤   │
│  │ I7: Signal Generation (37 plugins)                                 │   │
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
│  FeatureWriterAgent → intelligence_features (DB)                           │
│  SignalWriterAgent → signal_ledger (DB)                                    │
│  SignalTrackerAgent → lifecycle updates (DB)                               │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LAYER 5: CONSUMERS                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  AI Narrative Service (I8) → LLM analysis → narratives:*:* topics          │
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
| `narratives:*:*` | I8 LLM analysis per symbol/TF | `NarrativeEvent` |
| `market.events.gap_requests` | Gap fill requests | `GapRequestEvent` |
| `development.cross_asset` | Cross-asset spreads | `CrossAssetEvent` |

## Database Tables

| Table | Purpose | Retention |
|-------|---------|-----------|
| `market_data_ohlcv` | Raw OHLCV ground truth | Forever |
| `intelligence_features` | Full I1-I7 feature vectors (ML training) | Forever |
| `signal_ledger` | ALL I7 signals + lifecycle outcomes | Forever |
| `llm_calls` | LLM audit log + outcomes | Forever |
| `llm_model_scores` | Per-model win rates | 15min refresh |
| `instruments` | Active contracts | Current |

## Agent Classes

| Role | Class | Base | File |
|------|-------|------|------|
| Provider | `IBKRProviderAgent` | `BaseProviderAgent` | `services/ibkr_provider_agent.py` |
| Merger | `ProviderMergerAgent` | `BaseAgent` | `services/provider_merger_agent.py` |
| Compute | `IntelligencePipelineComputeAgent` | `BaseAgent` | `services/intelligence_pipeline_agent.py` |
| Compute | `BarAggregatorComputeAgent` | `BaseAgent` | `services/bar_aggregator_agent.py` |
| Compute | `RollComputeAgent` | `BaseAgent` | `services/roll_compute_agent.py` |
| Auditor | `BarAuditorAgent` | `BaseAgent` | `services/bar_auditor_agent.py` |
| Auditor | `ParityAuditorAgent` | `BaseAgent` | `services/parity_auditor_agent.py` |
| Writer | `BarWriterAgent` | `BaseAgent` | `services/bar_writer_agent.py` |
| Writer | `FeatureWriterAgent` | `BaseAgent` | `services/feature_writer_agent.py` |
| Writer | `SignalWriterAgent` | `BaseAgent` | `services/signal_writer_agent.py` |
| Tracker | `SignalTrackerAgent` | `BaseAgent` | `services/signal_tracker_agent.py` |

## Intelligence Tiers

| Tier | Plugins | Output |
|------|---------|--------|
| I1 | 28 | Technical indicators + OFI + CVD |
| I2 | 11 | Composite events (MACD, RSI, ADX, volume, etc.) |
| I3 | 9 | Market structure (swing, S/R, profile, session, fib) |
| I4 | 13 | Context/regime (GARCH, Kalman, VIX, CrossAsset, VWAP, VP) |
| I5 | 16 | Pattern detection (divergence, squeeze, chart patterns) |
| SMC | 13 | Smart Money (BOS/CHoCH, FVG, OB, HMM, BOCPD, etc.) |
| I6 | 1 | CrossTimeframeConfluence |
| I7 | 37 | Trading signals |
| I8 | — | LLM narratives (separate service) |

## Key Principles

1. **Database Ignorance** — Compute agents never touch DB. Persistence is decoupled via WriterAgents.
2. **Typed Event Bus** — All intelligence flows through `IntelligenceEvent` with tiered JSONB.
3. **Graceful Degradation** — DLQ topics, circuit breakers, and shadow modes for new features.
4. **Instrument Everything** — Prometheus + Grafana for all Golden Signals.
5. **Segregated Timeframes** — Separate HTF topics prevent I1 warmup on every 1m bar.

---

## Performance Characteristics

### Current Throughput

| Metric | Value | Context |
|--------|-------|---------|
| **Throughput** | ~4.5 bars/sec | Single symbol, all timeframes |
| **Latency** | ~220ms/bar | End-to-end I1→I7 |
| **Plugin Count** | 128 total | 28 I1, 11 I2, 9 I3, 13 I4, 16 I5, 13 SMC, 1 I6, 37 I7 (+2 aggregation) |

### Parallelization Architecture

**Tier Parallelization:**
- **I1 (28 plugins)** — parallelized via `asyncio.gather` + ThreadPoolExecutor
- **I7 (37 plugins)** — parallelized via `asyncio.gather` + ThreadPoolExecutor
- **I2-I6** — sequential execution (current bottleneck)

**Latency Breakdown (Per Bar):**
- I1 (parallel): ~30ms
- I2 (sequential): ~40ms
- I3 (sequential, 15 plugins): ~50ms
- I4 (sequential, 11 plugins): ~40ms
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

**See:** `docs/architecture/pipeline-optimization.md` for detailed strategy and `docs/ideas/pipeline-throughput-bottleneck-analysis.md` for profiling analysis.

---

## What Makes This Architecture Unique

| Aspect | Typical Systems | IndicAgent | Advantage |
|--------|----------------|-------------|-----------|
| **Extensibility** | Hardcoded indicators, core changes required | Plugin-native: empty container, add via registration | Zero risk to existing functionality |
| **Execution Ordering** | Manual config, maintenance burden | Emerges from plugin inputs/outputs (Kahn's algorithm) | Circular deps detected at startup |
| **Database Coupling** | DB in critical path, latency sensitive | Compute agents DB-ignorant, async WriterAgents | DB outage = zero impact on hot path |
| **Provider Switching** | Hardcoded, invasive | Merger pattern isolates all downstream consumers | Add/remove providers without changes |
| **Signal Selection** | Ad-hoc, opaque | CIS requires 3/6 evidence buckets agree | Full transparency, provable quality |
| **Feature Promotion** | Deploy to production, hope for best | Shadow mode with p < 0.05 statistical gates | No production losses from unproven features |
| **Drift Handling** | Manual recalibration | KS/CUSUM auto-correction | System self-adjusts |
| **Computation** | Full recomputation | O(1) incremental updates (141x speedup) | Sub-ms per plugin latency |

### Advanced Patterns

**Convergence Gate (StreamMerger):** All tiered outputs (I1, I3, I4, SMC) join into a single, unified `intelligence.journal` entry before persistence. Guarantees atomicity — no partial writes, no orphaned tiers.

**Provider Isolation:** `ProviderMergerAgent` subscribes to `market.bars.raw.<provider>` topics and routes canonical bars to `market.bars`. Downstream consumers never know provider topology changed. Adding a data source = one subclass.

**Shadow Mode Infrastructure:** Every feature runs in shadow before production. `shadow_promotion_ready` gates require statistical significance (p < 0.05, N ≥ 100) before production eligibility.

**Evidence-Graded Signals:** CIS (Confluence Intelligence Score) fires only when 3 of 6 independent evidence buckets agree. Single dominant bucket cannot override. Full attribution logged per signal.

**Hot/Warm/Cold Separation:** Compute agents (hot) → Redpanda (warm) → WriterAgents (cold). Database latency never affects hot path. Service restart resumes from committed offset — nothing lost.

---

## See Also

- `agent-standard.md` — Role taxonomy and naming conventions
- `base-agent-patterns.md` — BaseAgent lifecycle contract
- `observability.md` — Metrics and monitoring patterns
