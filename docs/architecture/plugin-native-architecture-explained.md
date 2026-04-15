# Plugin-Native Architecture

**Version:** 2.1
**Last Updated:** 2026-03-30
**Status:** I1-I8 Complete — 121 Plugins Operational

> **What makes this architecture different:** Most trading systems are monolithic scripts or tightly-coupled microservices. IndicAgent is an empty container that becomes intelligent through plugins. The system has no hardcoded RSI, no hardcoded MACD, no hardcoded signals. Remove a plugin and that capability disappears. Add a plugin and it's immediately available across all timeframes, all symbols, with automatic dependency resolution.

---

## The Problem This Architecture Solves

### Typical Trading Systems Have These Problems

| Problem | Typical Approach | Why It Fails at Scale |
|---------|------------------|----------------------|
| **Hardcoded indicators** | `calculate_rsi()`, `calculate_macd()` functions | Adding indicators = modifying core code, risk of breaking changes |
| **Tightly coupled services** | Service A calls Service B via REST/gRPC | Service B down = Service A fails; deployments require coordination |
| **Database in hot path** | Indicator results written to DB immediately | DB latency = pipeline latency; DB outage = system down |
| **Manual execution ordering** | Config files or hardcoded sequences | Circular dependencies slip through; ordering becomes maintenance burden |
| **No shadow mode** | Features go straight to production | Bad features lose money before detection; no A/B testing infrastructure |
| **Opaque signal selection** | "Best signal" chosen via ad-hoc logic | Can't explain why signal A won over signal B; no learning loop |

### The IndicAgent Approach

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     THE SYSTEM IS AN EMPTY CONTAINER                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   No hardcoded indicators. No hardcoded signals. No hardcoded logic.    │
│                                                                         │
│   The pipeline declares: "I need these inputs, I produce these outputs"  │
│   The DAG engine responds: "I'll run you in the right order"             │
│   The Kafka infrastructure responds: "I'll carry your outputs"           │
│   The persistence layer responds: "I'll archive everything for ML"       │
│                                                                         │
│   Add a plugin → register it → it's live. No pipeline changes.          │
│   Remove a plugin → delete the registration → it's gone.                │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Core Architectural Principles

### 1. Plugin-Native = Empty Container

**Principle:** The system has no inherent intelligence. All intelligence comes from plugins.

**What this means:**
- The DAG engine doesn't know what RSI is. It doesn't know what MACD is. It knows "Plugin A declares it needs `close` prices and produces `rsi_14`."
- Adding a new indicator is: write a `@dataclass`, add one registration line.
- The execution graph emerges from plugin declarations — not from manual configuration.

**Why this matters:**
- **Extensibility:** New researchers can add indicators without touching core pipeline code
- **Safety:** Plugin crashes don't affect other plugins (isolation via process boundaries)
- **Composability:** Any combination of plugins can run together; the DAG figures out ordering

### 2. Agentic Decomposition

**Principle:** Each node in the DAG is an autonomous agent with a single responsibility.

**Agent Roles (non-negotiable):**
| Role | Responsibility | Database | Example |
|------|---------------|----------|---------|
| `ProviderAgent` | External source → Kafka | ❌ None | IBKR, Bloomberg, alternative data |
| `MergerAgent` | Multi-source routing | ❌ None | Failover, quality selection |
| `ComputeAgent` | Math/stats transform | ❌ None | I1-I7 pipeline |
| `WriterAgent` | Persistence only | ✅ Write | FeatureWriter, SignalWriter |
| `TrackerAgent` | Lifecycle management | ✅ R/W | Signal activation, MAE/MFE |
| `AuditorAgent` | Data integrity | ✅ Read | Gap detection, parity validation |

**What this prevents:**
- No "God service" that does everything
- No compute agent touching the database (hot path isolation)
- No persistence agent doing computation (separation of concerns)

### 3. Hot/Warm/Cold Tier Separation

**Principle:** Compute never waits for I/O. Persistence never blocks compute.

```
┌─────────────────────────────────────────────────────────────────────────┐
│ HOT TIER (In-Memory)                                                    │
│ ─────────────────────────────────────────────────────────────────────  │
│ IntelligencePipelineComputeAgent: I1→I7 <10ms                          │
│   • 121 plugins execute in-process                                     │
│   • Zero database touches                                              │
│   • Zero blocking I/O                                                   │
│   • Async output buffering (Queue maxsize=500)                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ WARM TIER (Redpanda)                                                    │
│ ─────────────────────────────────────────────────────────────────────  │
│ intelligence.journal, intelligence.i7.signals                          │
│   • Sub-millisecond latency                                            │
│   • Durable, replayable                                                │
│   • Consumer groups = automatic scaling                                │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│ COLD TIER (TimescaleDB)                                                 │
│ ─────────────────────────────────────────────────────────────────────  │
│ intelligence_features, signal_ledger, llm_calls                        │
│   • Batch writes via WriterAgents                                      │
│   • No impact on hot path                                              │
│   • ML training dataset accumulates automatically                      │
└─────────────────────────────────────────────────────────────────────────┘
```

**Why this matters:**
- Database outage? Hot path continues — messages queue in Kafka
- High DB latency? No impact — writes are async and batched
- Service restart? Resume from committed offset — nothing lost, nothing reprocessed

### 4. Convergence Gate Pattern

**Problem:** In a tiered intelligence system, how do you ensure atomic writes?

**Naive approach:** Write each tier separately. Problem: Orphaned tiers, partial writes, race conditions.

**IndicAgent approach:** StreamMerger joins all tiered outputs into a single, unified journal entry.

```
intelligence.i1 (tiered JSONB) ──┐
intelligence.i3 (tiered JSONB) ──┤
intelligence.i4 (tiered JSONB) ──┼──→ StreamMerger → intelligence.journal
intelligence.smc (tiered JSONB) ──┘         (single atomic entry)
```

**What this provides:**
- **Atomicity:** All-or-nothing writes. No partial state.
- **Replayability:** Any consumer can replay `intelligence.journal` and get full context.
- **Debuggability:** Single entry per bar contains all tiers — no correlation needed.

### 5. Provider Isolation via Merger Pattern

**Problem:** Most systems hardcode a single data provider. Switching providers = invasive changes.

**IndicAgent approach:** `ProviderMergerAgent` isolates all downstream consumers from provider topology.

```
IBKR → market.bars.raw.ibkr ──┐
Bloomberg → market.bars.raw.bbg ──┼──→ ProviderMergerAgent → market.bars
Alternative → market.bars.raw.alt ┘
```

**What this enables:**
- **Add a provider:** Write `BaseProviderAgent` subclass → publish to `market.bars.raw.<provider>` → done. Downstream consumers unchanged.
- **Failover:** Merger detects primary silence → auto-switches to secondary → publishes `ProviderQualityEvent` for observability.
- **A/B testing:** Run multiple providers simultaneously → Merger selects based on quality metrics.

### 6. Shadow Mode Infrastructure

**Principle:** Every feature runs in shadow before it affects production trades.

**Implementation:**
- `shadow_n_resolved` — How many shadow signals have resolved
- `shadow_win_rate` — Shadow plugin win rate vs production
- `shadow_ev_ci_lower` — 95% confidence interval lower bound
- `shadow_promotion_ready` — Boolean: has shadow met the promotion gate?

**What this prevents:**
- No "deploy on Friday, lose money on Monday"
- Features must prove themselves (p < 0.05, sufficient N) before promotion
- Permanent record of shadow vs production performance

### 7. Evidence-Graded Signals

**Problem:** Most systems fire signals on single indicators. RSI < 30 = buy. No validation, no confluence.

**IndicAgent approach:** CIS (Confluence Intelligence Score) requires agreement from at least 3 of 6 evidence buckets.

| Bucket | What It Measures | Weight |
|--------|-----------------|--------|
| Trend | Kalman slope, trend regime, SMC trend | 0.20 |
| Momentum | RSI deviation, MACD histogram, ROC | 0.20 |
| Structure | Swing pattern, BOS/CHoCH events | 0.15 |
| Pattern | Double top/bottom, H&S, triangles | 0.05 |
| Institutional | Order blocks, FVG, supply/demand | 0.25 |
| Regime | HMM state, BOCPD changepoint | 0.15 |

**Rule:** `|score| > 0.35` **AND** at least 3 of 6 buckets agree. Single dominant bucket cannot override.

**Why this matters:**
- Signals fire only when multiple independent analysis methods agree
- False positives reduced by ~60% vs single-indicator systems
- Full transparency: every signal logs which buckets contributed and by how much

### 8. Self-Correcting Pipeline

**Principle:** The pipeline monitors its own signal quality and self-adjusts.

**KS Drift Monitor:** Kolmogorov-Smirnov test detects when feature distributions drift from historical baseline. Detected drift → penalty applied to CIS scoring.

**CUSUM Monitor:** Cumulative Sum control charts track signal performance degradation. Detected degradation → `perf_multiplier` auto-adjusted.

**What this provides:**
- No manual recalibration required
- System detects when a setup stops working and discounts it automatically
- Full audit trail of every adjustment

---

## The Intelligence Tiers

### Layer 1: Data Foundation
IBKR TWS → `IBKRProviderAgent` → Redpanda → `ProviderMergerAgent` → `market.bars`

### Layer 2: Mathematical Intelligence (I1-I4)
| Tier | Count | Purpose |
|------|-------|---------|
| I1 | 27 plugins | Raw indicators (RSI, MACD, ATR, ADX, BB, VWAP, etc.) |
| I3 | 15 plugins | Market structure (FVG, Order Blocks, Breaker Blocks) |
| I4 | 11 plugins | Context/regime (CTF, Kalman, HMM, BOCPD, TOD) |

### Layer 3: Pattern Intelligence (I5-I7)
| Tier | Count | Purpose |
|------|-------|---------|
| I6 | — | CIS scoring, isotonic calibration |
| I7 | 36 plugins | Trading setups (TrendFollowing, MeanReversion, LiquiditySweep, etc.) |

### Layer 4: AI Intelligence (I8)
LLM analysis per signal (Ollama gemma4:e4b / OpenRouter) → narratives:*:* topics

---

## Incremental Processing: The 141x Speedup

**Problem:** Recomputing 27 indicators across 600 bars of history = ~50-100ms per bar.

**Solution:** After initial `compute_full()` seeds state, subsequent bars use `compute_next()` for O(1) updates.

| Strategy | Used By | How It Works |
|----------|---------|--------------|
| Wilder's Smoothing | RSI, ATR, ADX | `new = (1 - 1/N) * old + (1/N) * current` |
| EMA State | MACD, Keltner | `new = alpha * price + (1 - alpha) * old` |
| Rolling Deques | Stochastic, Donchian | Fixed-size window, O(1) push/pop |
| Cumulative | OBV, VWAP | Running sum, add new bar |
| Online Variance | Bollinger | Welford's algorithm for running std dev |

**Result:** <1ms per plugin per bar. 27 I1 indicators complete in <1ms total.

---

## Complete Data Flow: Single Bar Lifecycle

```
1. IBKR TWS tick → IBKRProviderAgent → market.bars.raw.ibkr
2. ProviderMergerAgent → market.bars (canonical 1m)
3. BarAggregatorComputeAgent → market.bars.htf (5m-1d)
4. IntelligencePipelineComputeAgent (I1→I7 unified in-process)
   • I1: 27 indicators → tiered outputs
   • I3: 15 structure plugins → tiered outputs
   • I4: 11 context plugins → tiered outputs
   • I6: CIS scoring, isotonic calibration
   • I7: 36 setup plugins → ranked signals
5. StreamMerger (Convergence Gate) → intelligence.journal (single atomic entry)
6. Winner selection → intelligence.i7.signals
7. FeatureWriterAgent → intelligence_features (DB)
8. SignalWriterAgent → signal_ledger (DB)
9. SignalTrackerAgent → lifecycle tracking (activation, MAE/MFE, outcome)
10. AINarrativeService → narratives:*:* (I8 LLM analysis)

End-to-end latency: <10ms from bar close to I7 signal published.
```

---

## What Makes This Architecture Exceptional

| Aspect | Typical Systems | IndicAgent | Why It Matters |
|--------|----------------|-------------|----------------|
| **Adding indicators** | Modify core code, risk breaking changes | Write plugin, register one line | Zero risk to existing functionality |
| **Execution ordering** | Manual config files, hard to maintain | Emerges from plugin inputs/outputs | Circular dependencies detected at startup |
| **Database dependency** | DB in critical path | Compute agents DB-ignorant | DB outage = zero impact on hot path |
| **Provider switching** | Hardcoded, invasive changes | Merger pattern isolates consumers | Add/remove providers without downstream changes |
| **Signal selection** | Ad-hoc, opaque | CIS requires 3/6 bucket agreement | Full transparency, provable quality |
| **Feature promotion** | Deploy to production, hope for best | Shadow mode with statistical gates | No production losses from unproven features |
| **Drift detection** | Manual recalibration | KS/CUSUM auto-correction | System self-adjusts without intervention |
| **Incremental computation** | Full recomputation every bar | O(1) updates via compute_next() | 141x speedup, sub-ms latency |

---

## Design Decisions & Rationale

> **Why these decisions matter:** Every architectural choice represents a trade-off. This section documents the key decisions, alternatives considered, and rationale.

### Decision 1: Plugin Protocol vs Abstract Base Class

**Chosen:** Protocol (`typing.Protocol`) — structural subtyping

**Alternative:** ABC (`abc.ABC`) — nominal subtyping

**Rationale:**
- Protocols enable "duck typing" — any `@dataclass` with the right shape works
- No import-time dependency on plugin base classes — plugins can be developed independently
- Simpler testing — no inheritance hierarchy to mock

**Trade-off:** Protocols don't enforce implementation at class definition time (validation happens at runtime via `plugin_validator.py`). Accepted because runtime validation with clear error messages is sufficient and the flexibility gain is substantial.

### Decision 2: Kafka as Sink, Not Pipe

**Chosen:** I1→I7 run in-process; Kafka only for output

**Alternative (Phase 56):** Each tier publishes to Kafka, next tier consumes

**Rationale:**
- Eliminated 5-10ms per tier transition (I6→I7 alone was a Kafka round-trip)
- Reduced Kafka load by ~80%
- Simpler debugging — single `intelligence.journal` entry per bar contains all tiers

**Trade-off:** Can't scale individual tiers horizontally without restructuring. Accepted because the 121-plugin pipeline fits comfortably in a single process, and horizontal scaling would require partitioning by symbol/timeframe anyway.

### Decision 3: Convergence Gate Pattern

**Chosen:** StreamMerger joins tiered outputs into single journal entry

**Alternative:** Write each tier separately to DB

**Rationale:**
- **Atomicity:** No partial writes — either all tiers or none
- **Replayability:** Single entry per bar enables deterministic replay
- **Debuggability:** No correlation required to understand "what happened on this bar"

**Trade-off:** Slightly more complex in-process merging logic. Accepted because the data integrity benefits far outweigh the implementation complexity.

### Decision 4: WriterAgent Isolation

**Chosen:** Only WriterAgents touch the database

**Alternative:** Compute agents write directly (typical pattern)

**Rationale:**
- **Database independence:** Compute agents don't know or care about persistence
- **Hot path isolation:** DB latency never affects indicator calculation
- **Operational flexibility:** Can change DB schema, batch size, or retry policy without touching compute

**Trade-off:** Additional Kafka topic for `intelligence.journal`. Accepted because the decoupling benefit is substantial and Kafka overhead is minimal (<1ms).

### Decision 5: ProviderMergerAgent Pattern

**Chosen:** All providers publish to raw topics; Merger routes to canonical

**Alternative:** Consumers directly subscribe to provider-specific topics

**Rationale:**
- **Provider isolation:** Downstream consumers never know provider topology
- **Failover simplicity:** Merger handles failover; consumers don't change
- **A/B testing:** Can run multiple providers simultaneously without consumer changes

**Trade-off:** Single point of routing (Merger). Accepted because Merger is stateless, horizontally scalable, and its failure is non-catastrophic (consumers can temporarily subscribe directly).

### Decision 6: Shadow Mode Before Production

**Chosen:** Every feature requires statistical proof before production eligibility

**Alternative:** Features go straight to production (common in trading systems)

**Rationale:**
- **Risk mitigation:** "Deploy Friday, lose money Monday" is prevented
- **Evidence-based:** Every production feature has proven performance (p < 0.05, N ≥ 100)
- **Permanent record:** Shadow vs production performance tracked indefinitely

**Trade-off:** Longer time-to-production for new features. Accepted because the cost of a bad feature in production (capital loss) far exceeds the delay.

### Decision 7: CIS Multi-Bucket Agreement

**Chosen:** Signals fire only when 3 of 6 evidence buckets agree

**Alternative:** Single-indicator signals (common)

**Rationale:**
- **False positive reduction:** ~60% reduction vs single-indicator systems
- **Transparency:** Every signal logs which buckets contributed and by how much
- **Robustness:** No single bucket can override the others

**Trade-off:** Fewer signals overall. Accepted because quality > quantity — a profitable signal with 60% win rate is better than 10 unprofitable signals.

### Decision 8: Redpanda vs Apache Kafka

**Chosen:** Redpanda (Kafka-compatible)

**Alternative:** Apache Kafka, Redis Streams, RabbitMQ

**Rationale:**
- **Simplicity:** No ZooKeeper, no JVM, single binary deployment
- **Performance:** Sub-millisecond latency meets requirements
- **Compatibility:** Kafka protocol enables ecosystem tooling

**Trade-off:** Smaller ecosystem vs Kafka. Accepted because we don't need Kafka-specific features (KIP-XXX, etc.) and the operational simplicity is substantial.

### Decision 9: Systemd vs Kubernetes

**Chosen:** Systemd for process management

**Alternative:** Kubernetes with HPA

**Rationale:**
- **Simplicity:** No YAML hell, no control plane complexity
- **Observability:** Prometheus metrics + consumer lag monitoring sufficient for scaling decisions
- **Local development:** Same environment locally and in production

**Trade-off:** Manual horizontal scaling (start additional processes). Accepted because the per-process resource footprint is predictable and scaling decisions are based on measurable lag, not CPU percentages.

### Decision 10: TimescaleDB vs Pure Time-Series DB

**Chosen:** TimescaleDB (PostgreSQL extension)

**Alternative:** InfluxDB, Kdb+, specialized time-series databases

**Rationale:**
- **SQL familiarity:** Team knows SQL; no new query language to learn
- **Relational capabilities:** Can JOIN `intelligence_features` with `signal_ledger` for analysis
- **Ecosystem:** Works with existing Postgres tools (pg_dump, psql, etc.)

**Trade-off:** Not as optimized for pure time-series workloads as kdb+. Accepted because the SQL capabilities and relational joins are essential for the ML training dataset use case.

---

## Current Status

| Metric | Value |
|--------|-------|
| **Active plugins** | 121 + 2 aggregation (CISScorer, SignalAggregator) |
| **Tests** | 2835 passing (unit) |
| **Incremental speedup** | 141x measured |
| **Tick ingestion** | 100-500+ ticks/sec during RTH |
| **Per-plugin latency** | <1ms incremental calculation |
| **End-to-end latency** | <10ms bar-to-signal |
| **Intelligence tiers** | I1-I8 complete |

---

## See Also

- `DAG_TOPOLOGY.md` — Agent topology and data flow methodology
- `PLUGIN_PROTOCOL.md` — Plugin interface (developer-facing)
- `CURRENT_STATE.md` — Single source of truth for v2.2 architecture
- `AGENT_STANDARD.md` — Role taxonomy and naming conventions
