# IndicAgent Architecture Overview

**Version:** 2.8
**Status:** current
**Last Updated:** 2026-05-28
**Tags:** architecture, overview, intelligence-pipeline, microservices, event-driven, plugin-system

---

## Executive Summary

IndicAgent is a real-time market intelligence platform that processes raw market data through a six-layer intelligence pipeline, producing technical indicators, pattern recognition, regime classification, and AI-powered trading signals. The platform is built on a plugin-native, event-driven microservices architecture with strict separation between compute (hot) and persistence (cold).

**Key architectural principles:**
- **Database ignorance** — Compute agents never touch the database directly
- **Plugin-native extensibility** — Add intelligence via registration, not code changes
- **Hot/warm/cold separation** — Real-time compute → Kafka buffer → async persistence
- **Graceful degradation** — DLQ topics, circuit breakers, shadow mode for new features
- **Instrument everything** — OTel metrics, traces, and logs for all services

---

## Six-Layer Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LAYER 0: DATA INGESTION                           │
├─────────────────────────────────────────────────────────────────────────────┤
│  IBKR TWS → IBKRProvider → market.bars.raw.ibkr                        │
│                              ↓                                               │
│                    ProviderMerger (failover, routing)                   │
│                              ↓                                               │
│                    market.bars (canonical 1m)                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                          LAYER 1: BAR PROCESSING                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  BarAggregator (1m → HTF: 5m, 15m, 1h, 4h, 1d)                  │
│                    ↓                                                         │
│  BarWriter → market_data_ohlcv (DB)                                     │
│  BarAuditor → gap detection → market.events.gap_requests               │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                    LAYER 2: INTELLIGENCE COMPUTATION (I1-I7)                │
├─────────────────────────────────────────────────────────────────────────────┤
│  IntelligencePipeline — unified in-process pipeline            │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │ I1: Technical Indicators (28 plugins)                              │   │
│  │ I2: Composite Events (10 plugins)                                  │   │
│  │ I3: Market Structure (8 plugins)                                   │   │
│  │ I4: Context/Regime (12 plugins)                                    │   │
│  │ I5: Pattern Recognition (16 plugins)                               │   │
│  │ SMC: Smart Money Concepts (16 plugins)                            │   │
│  │ I6: Cross-Timeframe Confluence (6 plugins)                         │   │
│  │ I7: Signal Generation (36 + 2 aggregation)                         │   │
│  └────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Outputs: intelligence.journal, intelligence.i7.signals                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                        LAYER 3: SIGNAL LIFECYCLE                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  SignalTracker → lifecycle.transitions (DB-ignorant)              │
│  SignalReplayAuditor → TTL expiry, reads entry_zone from DB             │
│  SignalAuditor → coverage validation → intelligence.signal.audit       │
│  SignalMetricsAnalyzer → performance metrics (timer-triggered)           │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                          LAYER 4: PERSISTENCE                                │
├─────────────────────────────────────────────────────────────────────────────┤
│  FeatureWriter → intelligence_features                                 │
│  SignalWriter → signal_events + trade_frames (3-table, Phase 128+)    │
│  LifecycleWriter → signal_outcomes                                     │
│  SignalMetricsWriter → signal_metrics tables                           │
│  LLMWriter → llm_calls, llm_model_scores                                │
│  LineageWriter → signal_lineage                                        │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                       LAYER 5: AI INTELLIGENCE (I8)                          │
├─────────────────────────────────────────────────────────────────────────────┤
│  NarrativeSwarm → LLM analysis → narratives + llm.calls        │
│  AlphaSwarm → multi-agent signal refinement                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                       LAYER 6: CONSUMERS & UI                                │
├─────────────────────────────────────────────────────────────────────────────┤
│  indicagent-api (FastAPI) → SSE → Dashboard (Next.js)                       │
│  External consumers via Kafka topics                                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Hot/Warm/Cold Data Flow

**Hot Path (sub-ms latency):**
```
IBKR TWS → IntelligencePipeline → I1-I7 compute → Kafka publish
```
- Zero database touches
- In-memory state (plugin checkpoints)
- Direct Kafka publish

**Warm Path (Kafka buffer, ~10ms):**
```
Kafka topics → Consumer groups → Writers → DB batch commit
```
- Redpanda provides durability and replay
- Consumer groups enable parallel processing
- Async persistence decouples DB latency from hot path

**Cold Path (TimescaleDB, query-time):**
```
DB queries → API → Dashboard UI / External consumers
```
- Hypertable compression for historical data
- Materialized views for common queries
- Retention policies manage growth

---

## Service-Oriented Computing (SOC)

### Agent Role Taxonomy

| Suffix | Role | DB Access | Example |
|--------|------|------------|---------|
| `Provider` | External source → Kafka | No | `IBKRProvider` |
| Hot-path service | Math/stats transform | No | `IntelligencePipeline` |
| Writer | DB persistence from Kafka | Yes | `FeatureWriter` |
| `Tracker` | Business object lifecycle | No | `SignalTracker` |
| `Auditor` | Data integrity validation | No | `BarAuditor`, `ParityAuditor` |

### Service DAG (Canonical Order)

```
L1:  ibkr-provider, bar-replay
L2:  provider-merger
L3:  bar-aggregator, bar-auditor
L4:  bar-writer
L5:  intelligence-pipeline, cross-asset, macro-compute
L6:  feature-writer, signal-writer, signal-tracker-compute, lifecycle-writer,
     lineage-writer, ctx-writer
L7:  alpha-swarm, narrative-compute, llm-writer, swarm-ledger-writer
L8:  signal-metrics-compute, signal-metrics-writer, graduation-compute,
     graduation-writer, feature-snapshot-writer, ml-training
L9:  signal-auditor, signal-replay, parity-auditor, alerting-agent
L10: service-auditor (meta: monitors all above)
```

**Source of truth:** `_DAG_ORDER` in `services/service_auditor.py`

---

## Plugin System

### Plugin Count by Tier

| Tier | Plugins | Description |
|------|---------|-------------|
| I1 | 28 | Technical indicators (RSI, MACD, ATR, BB, VWAP, Stoch, ADX, OFI, CVD, etc.) |
| I2 | 10 | Composite events (MACDEvents, RSIEvents, ADXEvents, VolumeEvents, etc.) |
| I3 | 8 | Market structure (swing, S/R, profile, session levels, fib) |
| I4 | 12 | Context/regime (GARCH, Kalman, HurstExp, VIXRegime, CrossAsset, VWAP, VP) |
| I5 | 16 | Pattern detection (divergence, squeeze, chart patterns) |
| SMC | 16 | Smart Money (BOS/CHoCH, FVG, OB, HMM x4, BOCPD, etc.) |
| I6 | 6 | CrossTimeframeConfluence (6 sub-score plugins) |
| I7 | 36 + 2 | Trading signals + CISScorer + SignalAggregator |

**Total:** 132 plugins + 2 aggregation components

**Source of truth:** `TIER_I*` in `src/intelligence/register_plugins.py`

### Plugin Protocol

Every plugin implements:
```python
def compute_next(self, bar: BarEvent) -> Output:
    """O(1) incremental state update, returns computed value"""
```

- Stateful computation (no full recalculation)
- Kahn's algorithm determines execution order
- Circular dependency detection at startup

---

## DAG Execution

### Topological Sorting

The DAG emerges from plugin inputs/outputs:
```python
# I1 plugins produce: rsi, macd, atr, bollinger
# I2 plugins consume: rsi, macd, atr (I1 outputs)
# I3 plugins consume: rsi, macd, bollinger (I1 outputs)
# ... and so on
```

**Cycle prevention:** Startup hard-crashes if circular dependency detected.

**See:** `docs/concepts/dag-execution.md`

---

## API-First Design

### FastAPI Service (`indicagent-api`)

**Port:** 8000
**Purpose:** Fans out all streams to dashboard consumers via SSE

**Key routes:**
- `/health/*` — Health check endpoints for monitoring
- `/api/stream` — SSE stream for real-time data
- `/api/v1/*` — REST endpoints for queries

**Design principles:**
- Stateless (no session state in API)
- DB queries only (no direct Kafka access)
- OTel instrumentation on all routes
- Structured logging via structlog

**See:** `docs/platform/platform-api.md`, `docs/reference/api/rest-endpoints.md`

---

## Observability Stack

### OTel Collector Pipeline

```
Services (all)
  │
  ├── metrics (OTLP push, every 15s)  ─┐
  ├── traces  (OTLP push, batched)    ─┼─→  OTel Collector :4317
  └── logs    (OTLP push, every 5s)   ─┘         │
                                            ┌─────┼──────┐
                                            ▼     ▼      ▼
                                        Prometheus Tempo  Loki
                                        exporter  traces  logs
                                        :8889
                                            │
                                      Prometheus :9090
                                      (scrapes :8889)
                                            │
                                       Grafana :3001
```

### Golden Signals

| Signal | Metric | Type | Purpose |
|--------|--------|------|---------|
| Traffic | `stream_messages_read_total` | Counter | Messages processed |
| Latency | `persistence_batch_latency_seconds` | Histogram | DB write time |
| Errors | `plugin_fallbacks_total` | Counter | Plugin failures |
| Saturation | `persistence_consumer_lag_records` | Gauge | Consumer backlog |

**See:** `docs/platform/platform-observability.md`

---

## Self-Healing (Phase 108)

### Systemd Watchdog Integration

All 25 daemon services run with:
```ini
[Service]
WatchdogSec=60
NotifyAccess=main
```

When a service stalls (no message for 60s), systemd auto-restarts.

### Self-Healing Mechanisms

| Mechanism | Metric | Action |
|-----------|--------|--------|
| Stall detection | `consumer_stall_detected_total` | Systemd restart |
| DLQ quarantine | `dlq_quarantine_total` | Poison pill isolation |
| Oneshot failure | `job_completed_total{status="failure"}` | Alert for manual intervention |
| API health | `api_health` | Alert on DB disconnect |
| Watchdog suppression | `watchdog_notify_suppressed_total` | Alert on config error |

**See:** `docs/architecture/self-healing.md`

---

## Kafka/Redpanda Topology

### Key Topics

| Topic | Purpose | Schema |
|-------|---------|--------|
| `market.bars.raw.ibkr` | IBKR raw bars | `BarEvent` |
| `market.bars` | Canonical 1m bars | `BarEvent` |
| `market.bars.htf` | HTF bars (5m-1d) | `BarEvent` |
| `intelligence.journal` | Full I1-I7 features | `BarIntelligenceRecord` |
| `intelligence.i7.signals` | Winner I7 signals | `SignalEvent` |
| `narratives` | I8 LLM analysis | `NarrativeEvent` |
| `lifecycle.transitions` | Signal state changes | `LifecycleEvent` |

**Consumer Groups:**
- `feature_writer_group` — FeatureWriter
- `signal_writer_group` — SignalWriter
- `ai_narrative` — NarrativeSwarm

**See:** `docs/data/data-streaming.md`

---

## Database Schema (TimescaleDB)

### Key Tables

| Table | Purpose | Retention |
|-------|---------|-----------|
| `market_data_ohlcv` | Raw OHLCV ground truth | Forever |
| `intelligence_features` | Full I1-I7 feature vectors (ML training) | Forever |
| `signal_events` | Detection layer: one row per I7 plugin fire; ECL annotations + factor_scores + context_features (Phase 128+) | Forever |
| `trade_frames` | Hypothesis layer: one row per entry_type per signal; counterfactual_pnl_r ML training target (Phase 128+) | Forever |
| `trade_executions` | Execution layer: one row per live trade; actual_pnl_r (Phase 128+) | Forever |
| `signal_ledger` | JOIN view (signal_events + trade_frames + trade_executions; renamed from signal_ledger_full in Phase 130) | Forever |
| `signal_lineage` | Signal-affecting transforms and agent predictions | Forever |
| `llm_calls` | LLM audit log + outcomes | Forever |
| `llm_model_scores` | Per-model win rates | 15min refresh |
| `instruments` | Active contracts | Current |

**See:** `docs/reference/db-maintenance.md`

---

## Performance Characteristics

### Throughput
- ~4.5 bars/sec (single symbol, all timeframes)
- ~220ms end-to-end latency (bar close → I7 signal)

### Parallelization
- **I1 (28 plugins)** — parallelized via `asyncio.gather` + ThreadPoolExecutor
- **I7 (36 plugins)** — parallelized via `asyncio.gather` + ThreadPoolExecutor
- **I2-I6** — sequential (current bottleneck; batch processing planned)

**See:** `docs/architecture/pipeline-optimization.md`

---

## Deep-Dive Links

| Topic | Document |
|-------|----------|
| Architecture design principles | `docs/architecture/design-principles.md` |
| Current architecture state | `docs/architecture/current-state.md` |
| Plugin protocol & tier lists | `docs/intelligence/intelligence-plugins.md` |
| DAG execution | `docs/concepts/dag-execution.md` |
| Data pipeline | `docs/data/data-pipeline.md` |
| Intelligence tiers & plugin inventory | `docs/intelligence/intelligence-plugins.md` |
| Observability | `docs/platform/platform-observability.md` |
| Self-healing | `docs/architecture/self-healing.md` |
| API design | `docs/platform/platform-api.md` |
| Data streaming (Kafka) | `docs/data/data-streaming.md` |
| Systemd supervision | `docs/operations/operations-infrastructure.md` |
| Grafana dashboards | `docs/operations/operations-observability.md` |
| Deployment | `docs/operations/operations-infrastructure.md` |
| Alerting runbook | `docs/development/alerting.md` |

---

## Next Steps

- **New to the platform?** Start with `docs/README.md` and `CLAUDE.md`
- **Adding a plugin?** See `src/intelligence/ai/AUTHORING.md`
- **Running services?** See `docs/operations/operations-infrastructure.md`
- **Production deployment?** See `docs/operations/operations-infrastructure.md`
- **Monitoring?** See `docs/operations/operations-observability.md`
