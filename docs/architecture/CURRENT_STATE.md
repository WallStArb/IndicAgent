# IndicAgent v2.1 — Current Architecture State

**Version:** 2.1
**Last Updated:** 2026-03-30
**Status:** Production — All phases through 57.1 complete

> This is the single source of truth for the current production architecture. For design history and evolution, see `archive/`.

## Executive Summary

IndicAgent v2.1 is a real-time market intelligence platform with a unified I1-I7 pipeline and separate persistence layer. The core philosophy is **agentic decomposition** — each node in the DAG is an autonomous, event-driven agent with clear boundaries.

**Key v2.1 Changes from v2.0:**
- `IntelligencePipelineComputeAgent` — Unified I1-I7 in-process pipeline (no I6→I7 Kafka hop)
- `SignalWriterAgent` — Dedicated persistence agent for `signal_ledger`
- `ProviderMergerAgent` — Multi-provider failover and routing
- `BaseProviderAgent` abstraction — Adding new data sources is now a single subclass

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
| Signal Tracker | `signal_tracker_agent.py` | `indicagent-signal-tracker` | :9115 | Signal lifecycle (activation, MAE/MFE, outcome) |
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
│  │ I1: Technical Indicators (27 plugins)                              │   │
│  │   → ATR, RSI, MACD, ADX, BB, VWAP, Stoch, etc.                    │   │
│  ├────────────────────────────────────────────────────────────────────┤   │
│  │ I2: Volume Analysis                                                │   │
│  │   → OFI, CVD, Volume Profile, Delta                                │   │
│  ├────────────────────────────────────────────────────────────────────┤   │
│  │ I3: Pattern Detection (15 plugins)                                 │   │
│  │   → FVG, Order Blocks, Breaker Blocks                              │   │
│  ├────────────────────────────────────────────────────────────────────┤   │
│  │ I4: Context Scoring                                                │   │
│  │   → CTF (Composite Technical Factor), Regime, TOD                  │   │
│  ├────────────────────────────────────────────────────────────────────┤   │
│  │ I5: Confluence                                                     │   │
│  │   → Multi-TF alignment, structure confluence                       │   │
│  ├────────────────────────────────────────────────────────────────────┤   │
│  │ I6: Scoring & Filtering                                            │   │
│  │   → CIS scoring, isotonic calibration, regime gating               │   │
│  ├────────────────────────────────────────────────────────────────────┤   │
│  │ I7: Signal Generation (36 plugins)                                 │   │
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
| I1 | 27 | Technical indicators |
| I2 | — | Volume analysis (inlined in I1/I4) |
| I3 | 15 | Pattern detection (FVG, OB, BB) |
| I4 | 11 | Context scoring, regime |
| I5 | — | Confluence (inlined in I4) |
| I6 | — | CIS scoring, calibration |
| I7 | 36 | Trading signals |
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
| **Plugin Count** | 121 total | 27 I1, 15 I3, 11 I4, 36 I7 |

### Parallelization Architecture

**Tier Parallelization:**
- **I1 (27 plugins)** — parallelized via `asyncio.gather` + ThreadPoolExecutor
- **I7 (36 plugins)** — parallelized via `asyncio.gather` + ThreadPoolExecutor
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

**See:** `docs/architecture/PIPELINE_OPTIMIZATION.md` for detailed strategy and `docs/ideas/pipeline-throughput-bottleneck-analysis.md` for profiling analysis.

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

- `AGENT_STANDARD.md` — Role taxonomy and naming conventions
- `BASE_AGENT_PATTERNS.md` — BaseAgent lifecycle contract
- `OBSERVABILITY.md` — Metrics and monitoring patterns
