# Renaissance Pipeline Architecture

**Concept:** Event-driven DAG with clear separation between compute (DB-ignorant) and persistence (DB-aware). Intelligence flows from raw bars through seven analytical tiers (I1-I7), with Kafka as the reliable backbone.

---

## Core Architecture Principles

### Agentic Decomposition

Every service in the pipeline is an autonomous event-driven agent with clear boundaries:

**Role Separation:**
- **Compute Agents** — Transform data, never touch DB. Publish to Kafka topics.
- **Writer Agents** — Consume from Kafka, own all persistence logic.
- **Provider Agents** — Bridge external data sources to canonical bar format.
- **Tracker Agents** — Manage business object lifecycles (signals, positions).
- **Auditor Agents** — Validate data integrity, self-heal when possible.

**Why:** Database outages never affect hot path. Compute agents resume from committed Kafka offset on restart — nothing lost.

### BaseAgent Contract

All agents extend `BaseAgent` (`src/core/agent/base.py`), providing:

- **Graceful SIGTERM drain** — finish processing, commit offsets, exit cleanly
- **Golden Signals instrumentation** — Traffic, Latency, Errors, Saturation via Prometheus
- **Consistent lifecycle** — startup → warmup → run → drain → shutdown
- **Structured logging** — all logs to `logs/<service>.log` (not journald)

**Benefits:**
- New agents get observability and graceful shutdown for free
- Consistent monitoring across entire pipeline
- No silent data loss on crashes

---

## Data Flow Architecture

### Provider Layer (Data Ingestion)

```
IBKR TWS → IBKRProviderAgent → market.bars.raw.ibkr
                                          ↓
                              ProviderMergerAgent
                              (failover, routing)
                                          ↓
                              market.bars (canonical 1m)
```

**Provider Isolation Pattern:**
- Raw topics: `market.bars.raw.<provider>` — provider-specific format
- Canonical topic: `market.bars` — unified format, downstream consumers never see provider changes
- Multi-provider failover: Merger auto-switches on primary silence

**Benefits:** Adding a data source = one subclass. Nothing downstream changes.

### Aggregation Layer (Timeframe Unification)

```
market.bars (1m) → BarAggregatorComputeAgent → market.bars.htf
                                        (5m/15m/1h/4h/1d)
```

**BarAccumulator:** Stateless windowed aggregation. Accumulates 1m bars, emits HTF bar on period boundary (e.g., 5m mark). Session break logic prevents cross-session contamination.

**Why not in DB:** Real-time consumers need HTF bars immediately, not after DB write latency.

### Intelligence Layer (I1-I7 Pipeline)

```
market.bars (1m) ─────┐
market.bars.htf ──────┤ → IntelligencePipelineComputeAgent
                       │   (I1→I7 unified, IN-PROCESS)
                       └───→ BarHistorySeeder (cold-start)
                                  ↓
                    intelligence.journal (tiered JSONB)
                    intelligence.i7.signals (winner signal)
```

**In-Process Design:**
- I1-I7 execute in single process — no inter-service Kafka hops
- Internal `asyncio.Queue(maxsize=500)` for I6→I7 handoff — zero I/O on hot path
- State checkpointing to compacted topic — eliminates warmup on restart

**Why Not Pure Microservices:**
- Kafka overhead (serialization, network) dominates for single-bar processing
- In-process is 10-20x faster for tight coupling (I6→I7 is direct dependency)
- Writer agents still separate (DB-ignorant compute principle)

---

## Tier Parallelization Strategy

### Current State

**Parallelized:**
- I1 (27 plugins) — `asyncio.gather` + ThreadPoolExecutor
- I7 (36 plugins) — `asyncio.gather` + ThreadPoolExecutor

**Sequential:**
- I2-I6 tiers — executed one after another (current bottleneck)

**Why:** Python's GIL prevents threading from achieving true parallelism. Only one thread executes Python bytecode at a time. CPU-bound work (plugin compute) cannot utilize multiple cores.

**Latency Impact:**
- I1 (parallel): 30ms
- I2-I6 (sequential): 160ms (73% of total)
- I7 (parallel): 20ms

### Batch Processing (Proposed)

**Concept:** Process 100+ bars through each tier in parallel (not 1 bar through all tiers sequentially).

**Expected Benefit:** 10-50x throughput improvement (amortizes sequential tier cost across bars).

**Trade-off:** Increased latency (accumulate 100 bars OR 5s timeout) vs higher throughput.

**See:** `docs/architecture/PIPELINE_OPTIMIZATION.md` for detailed strategy.

---

## Persistence Architecture

### Writer Agent Pattern

```
IntelligencePipelineComputeAgent → intelligence.journal (Kafka)
                                              ↓
                                    FeatureWriterAgent
                                              ↓
                                  intelligence_features (DB)
```

**Convergence Gate:** All tiered outputs (I1, I3, I4, SMC) join into single, unified `intelligence.journal` entry before persistence. Guarantees atomicity — no partial writes, no orphaned tiers.

**Why:** DB writes are batch operations. Compute agents should never block on DB latency.

### Database Schema

**Hypertables (TimescaleDB):**
- `market_data_ohlcv` — raw OHLCV ground truth (keep forever)
- `intelligence_features` — full I1-I7 feature vectors (ML training dataset)
- `signal_ledger` — ALL I7 signals + lifecycle outcomes
- `llm_calls` — LLM audit log + outcomes

**Design Principle:** Never drop data that could contain signal. Storage is cheapest, data is irreplaceable.

---

## Evolution History

### v2.0 Foundation (Data Layer)

Established core patterns:
- Clock-driven data flow — guaranteed 1-minute bar emission
- Zero-loss guarantee — `auto_offset_reset="earliest"` + explicit `commit()`
- Multi-stream reconciliation — 5s real-time vs 1m audited comparison

### v2.1 Agentic DAG Refactor

Introduced agent role separation:
- BaseAgent unification — lifecycle, instrumentation, graceful shutdown
- Dedicated writer agents — DB-ignorant compute principle
- Provider abstraction — `BaseProviderAgent` + adapter pattern

### v2.2 Unified Intelligence Pipeline

Consolidated I1-I7 into single process:
- Eliminated Kafka hops between tiers (I6→I7 is direct dependency)
- State checkpointing — no warmup on restart
- Parallelized I1/I7 tiers — 60% latency reduction
- Identified I2-I6 sequential bottleneck — current optimization target

---

## Future Directions

### Renaissance Validation Framework

Transform from "feature factory" to "validated alpha engine":
- Shadow-first validation (14-day correlation gate)
- Automated promotion/demotion based on statistical significance
- `IAlphaContributor` interface for all signal sources
- LLMs in research-only mode (no real-time hot path calls)

**Design:** `docs/ideas/renaissance-alpha-pipeline.md`

### Pipeline Parallelization

Achieve 60+ bars/sec via batch processing:
- Dual-mode architecture (real-time + batch)
- Adaptive mode selection (volatility, staleness guards)
- 10-50x expected throughput improvement

**Strategy:** `docs/architecture/PIPELINE_OPTIMIZATION.md`

---

## Related Documentation

- **Current State:** `docs/architecture/CURRENT_STATE.md` — active services, data flow, plugin counts
- **Optimization:** `docs/architecture/PIPELINE_OPTIMIZATION.md` — performance strategy, batch processing
- **Plugin Protocol:** `docs/architecture/PLUGIN_PROTOCOL.md` — how plugins work
- **Observability:** `docs/architecture/OBSERVABILITY.md` — metrics and monitoring
- **DAG Topology:** `docs/architecture/DAG_TOPOLOGY.md` — agent dependencies and data flow

---

*Focus: Architecture concepts and patterns, not implementation timelines*
