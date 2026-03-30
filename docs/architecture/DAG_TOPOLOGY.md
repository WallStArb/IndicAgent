# DAG Topology & Methodology

**Version:** 2.1
**Last Updated:** 2026-03-30
**Status:** Phase 57 Complete — Unified I1-I7 Pipeline

## Overview

The IndicAgent pipeline is an event-driven, Agentic DAG (Directed Acyclic Graph). Data flows from raw market data through a provider abstraction layer, bar aggregation tier, unified intelligence compute (I1–I7), and finally into persistence via WriterAgents. All inter-agent communication is via Redpanda topics.

---

## Agent Taxonomy

Each agent has exactly one role, expressed in its class name suffix:

| Role Suffix | Responsibility | DB Access | Example |
|-------------|---------------|-----------|---------|
| `ProviderAgent` | External source → Kafka raw topic. No compute. | None | `IBKRProviderAgent` |
| `MergerAgent` | Multi-source routing + auto-failover. DB-ignorant. | None | `ProviderMergerAgent` |
| `ComputeAgent` | Math/stats transform. DB-ignorant. | None | `IntelligencePipelineComputeAgent` |
| `WriterAgent` | DB persistence only. | Write | `FeatureWriterAgent`, `SignalWriterAgent` |
| `TrackerAgent` | Business object lifecycle. | Read/Write | `SignalTrackerAgent` |
| `AuditorAgent` | Data integrity validation + self-healing. | Read | `BarAuditorAgent`, `ParityAuditorAgent` |

All agents extend `BaseAgent` (`src/core/agent/base.py`). See `BASE_AGENT_PATTERNS.md` for lifecycle contract.

---

## Full DAG Topology

```mermaid
graph TD
    subgraph Sources["External Data Sources"]
        TWS["IBKR TWS\n192.168.1.157"]
    end

    subgraph ProviderLayer["Provider Layer (Phase 54)"]
        IBKR["IBKRProviderAgent\n:9129"]
        TWS --> IBKR
    end

    subgraph MergerLayer["Merger Layer"]
        MERGER["ProviderMergerAgent\n:9130"]
    end

    subgraph BarTier["Bar Processing Tier"]
        BAGG["BarAggregatorComputeAgent\n:9120"]
        BWRITE["BarWriterAgent\n:9121"]
        BAUDIT["BarAuditorAgent\n:9123"]
        ROLL["RollComputeAgent\n:9122"]
    end

    subgraph IntelTier["Intelligence Compute Tier (Phase 57)"]
        PIPELINE["IntelligencePipelineComputeAgent\n:9125\nI1→I7 UNIFIED"]
    end

    subgraph PersistTier["Persistence Tier"]
        FWRITE["FeatureWriterAgent\n:9116"]
        SWRITE["SignalWriterAgent\n:9117"]
        STRACK["SignalTrackerAgent\n:9115"]
        LLMWRITE["LLMWriterService\n:9117"]
    end

    subgraph SidePaths["Parallel / Side-Channel"]
        CROSS["CrossAssetService\n:9118"]
        PARITY["ParityAuditorAgent\n:9124"]
        NARR["AINarrativeService\n:9113\nI8"]
    end

    subgraph DB["TimescaleDB"]
        OHLCV[("market_data_ohlcv")]
        INTFEAT[("intelligence_features")]
        SIGLED[("signal_ledger")]
        LLMDB[("llm_calls")]
    end

    %% Provider → Merger
    IBKR -->|"market.bars.raw.ibkr"| MERGER

    %% Merger outputs
    MERGER -->|"market.bars (canonical)"| BAGG
    MERGER -->|"market.bars"| BWRITE
    MERGER -->|"market.bars"| PIPELINE
    MERGER -->|"market.data.quality (side-channel)"| CROSS

    %% Bar tier
    BAGG -->|"market.bars.htf"| BWRITE
    BAGG -->|"market.bars.htf"| BAUDIT
    BAGG -->|"market.bars.htf"| PIPELINE
    BAUDIT -->|"market.events.gap_requests"| IBKR
    ROLL -->|"market.events.roll"| PIPELINE
    BWRITE --> OHLCV

    %% Intelligence compute (v2.1 unified)
    PIPELINE -->|"intelligence.journal"| FWRITE
    PIPELINE -->|"intelligence.i7.signals"| SWRITE
    PIPELINE -->|"intelligence.journal"| NARR
    PIPELINE -->|"intelligence.journal"| PARITY

    %% Persistence
    FWRITE --> INTFEAT
    SWRITE --> SIGLED
    NARR -->|"llm.calls"| LLMWRITE
    LLMWRITE --> LLMDB
    STRACK --> SIGLED

    %% Side-channel
    MERGER --> CROSS
    PIPELINE --> PARITY
```

---

## DAG Methodology

> **Why this matters:** Most systems tightly couple data providers to consumers, hardcode execution order, and mix compute with persistence. The IndicAgent DAG applies Separation of Concerns as an architectural invariant, not a coding guideline.

### 1. Provider Isolation

**Pattern:** `ProviderMergerAgent` is the sole writer to `market.bars`.

- Providers publish to provider-specific topics (`market.bars.raw.<provider>`)
- Merger routes canonical bars to `market.bars`
- Downstream consumers are isolated from provider topology changes
- Adding/removing a provider requires zero downstream changes

**What this prevents:** In typical systems, changing from IBKR to Bloomberg requires modifying every service that consumes market data. In IndicAgent, add a `BloombergProviderAgent` → publish to `market.bars.raw.bbg` → done. The Merger handles routing. Zero downstream changes.

**Why this matters:** Provider diversification becomes a configuration decision, not a development project.

### 2. In-Process Intelligence (Phase 57)

**Pattern:** `IntelligencePipelineComputeAgent` runs I1→I7 entirely in-memory.

```
┌─────────────────────────────────────────────────────────────────────────┐
│              IntelligencePipelineComputeAgent (I1→I7)                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  market.bars → I1 (27 plugins) → tiered outputs                        │
│              → I3 (15 plugins) → tiered outputs                        │
│              → I4 (11 plugins) → tiered outputs                        │
│              → I6 CIS → calibrated scores                              │
│              → I7 (36 plugins) → ranked signals                        │
│                                                                         │
│              ┌─────────────────────────────────────┐                   │
│              │   StreamMerger (Convergence Gate)   │                   │
│              └─────────────────────────────────────┘                   │
│                        ↓                         ↓                     │
│            intelligence.journal      intelligence.i7.signals            │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**Key Points:**
- Kafka is a sink, not an inter-stage pipe
- No I6→I7 Kafka hop (was Phase 56, removed in 57)
- Async output buffering via `asyncio.Queue(maxsize=500)`
- Backpressure from Kafka doesn't block compute

**What this prevents:** In Phase 56, every tier transition required a Kafka round-trip. I6→I7 alone added 5-10ms latency. Running I1→I7 in-process reduces this to <1ms.

**Why this matters:** Sub-10ms end-to-end latency enables real-time response to market movements that slower systems miss.

### 3. Convergence Gate (StreamMerger)

**Pattern:** All tiered outputs join into a single, unified journal entry before persistence.

```
intelligence.i1 (tiered JSONB) ──┐
intelligence.i3 (tiered JSONB) ──┤
intelligence.i4 (tiered JSONB) ──┼──→ StreamMerger → intelligence.journal
intelligence.smc (tiered JSONB) ──┘
```

**Purpose:** Atomic data integrity — no partial writes, no orphaned tiers.

**What this prevents:** In tiered systems that write separately, a crash after I1 but before I7 leaves orphaned partial state. Reconciliation requires complex error-prone logic.

**Why this matters:** Every bar produces exactly one `intelligence.journal` entry containing all tiers. Replay from offset 0 reconstructs complete state. Debugging is trivial — any bar = single entry.

### 4. Compute vs Persistence Separation

**Pattern:** WriterAgents are the ONLY agents with DB write access.

```
Compute (DB-ignorant) → Kafka → WriterAgent (DB access only)
```

| Agent | Reads | Writes | DB Access |
|-------|-------|--------|-----------|
| `IntelligencePipelineComputeAgent` | `market.bars` | Kafka topics | None |
| `FeatureWriterAgent` | `intelligence.journal` | `intelligence_features` | Write |
| `SignalWriterAgent` | `intelligence.i7.signals` | `signal_ledger` | Write |

**What this prevents:** Most systems mix compute and persistence — indicators write directly to DB. When DB slows down, indicators slow down. When DB goes down, indicators stop.

**Why this matters:** Compute agents don't know or care that persistence exists. They publish to Kafka and continue. WriterAgents can batch, retry, or pause without affecting hot path.

### 5. Hot/Warm/Cold Tier Separation

| Tier | Technology | Latency | Purpose |
|------|------------|---------|---------|
| **Hot** | In-memory, asyncio.Queue | <10ms | Plugin execution, no blocking I/O |
| **Warm** | Redpanda topics | Sub-ms | Durable, replayable event bus |
| **Cold** | TimescaleDB batch | Async | Archival, ML training dataset |

---

## Primary Data Flow

### 1. Provider Layer
`IBKRProviderAgent` connects to IBKR TWS and emits 1m bars to `market.bars.raw.ibkr`. It never writes to `market.bars` directly — that is the MergerAgent's exclusive responsibility.

### 2. Merger Layer
`ProviderMergerAgent` subscribes to all `market.bars.raw.<provider>` topics and routes the authoritative provider's bars to `market.bars`. Auto-failover when primary is silent. A `ProviderQualityEvent` side-channel publishes latency, failover, and recovery events.

### 3. Bar Processing Tier

| Agent | Input | Output | Purpose |
|-------|-------|--------|---------|
| `BarAggregatorComputeAgent` | `market.bars` (1m) | `market.bars.htf` | 1m → 5m/15m/1h/4h/1d aggregation |
| `BarWriterAgent` | `market.bars` + `.htf` | `market_data_ohlcv` | Batch-write OHLCV to DB |
| `BarAuditorAgent` | `market.bars.htf` | `market.events.gap_requests` | Gap detection |
| `RollComputeAgent` | `market.bars` | `market.events.roll` | Futures roll events |

### 4. Intelligence Compute (Phase 57)

`IntelligencePipelineComputeAgent` subscribes to both `market.bars` (1m) and `market.bars.htf`. Each bar triggers a full I1–I7 pipeline run in-memory. Output published to `intelligence.journal` (tiered JSONB) and `intelligence.i7.signals` (winner signal).

### 5. Persistence Tier

| Agent | Input | Output | Purpose |
|-------|-------|--------|---------|
| `FeatureWriterAgent` | `intelligence.journal` | `intelligence_features` | Full I1-I7 vectors (ML training) |
| `SignalWriterAgent` | `intelligence.i7.signals` | `signal_ledger` | All ranked I7 signals |
| `SignalTrackerAgent` | `intelligence.i7.signals` | `signal_ledger` | Lifecycle: activation, MAE/MFE, outcome |
| `LLMWriterService` | `llm.calls` | `llm_calls` | LLM audit log + outcome back-fill |

### 6. Parallel / Side-Channel

| Service | Input | Purpose |
|---------|-------|---------|
| `CrossAssetService` | `market.data.quality` + cross-asset streams | Spread dynamics |
| `ParityAuditorAgent` | `intelligence.journal` | Data integrity validation |
| `AINarrativeService` | `intelligence.i7.signals` | I8 LLM narratives |

---

## Topic Registry

| Topic | Producer | Consumers | Content |
|-------|----------|-----------|---------|
| `market.bars.raw.ibkr` | `IBKRProviderAgent` | `ProviderMergerAgent` | Raw 1m bars |
| `market.bars.raw.<provider>` | Any `ProviderAgent` | `ProviderMergerAgent` | Provider-specific bars |
| `market.bars` | `ProviderMergerAgent` | Bar tier, Pipeline | Canonical 1m bars |
| `market.bars.htf` | `BarAggregatorComputeAgent` | Bar tier, Pipeline | HTF bars (5m-1d) |
| `market.data.quality` | `ProviderMergerAgent` | `CrossAssetService` | Provider quality events |
| `market.events.gap_requests` | `BarAuditorAgent` | `IBKRProviderAgent` | Gap fill requests |
| `market.events.roll` | `RollComputeAgent` | Pipeline | Futures roll events |
| `intelligence.journal` | `IntelligencePipelineComputeAgent` | FeatureWriter, Narrative, Parity | Full I1-I7 tiered JSONB |
| `intelligence.i7.signals` | `IntelligencePipelineComputeAgent` | SignalWriter, Tracker | Winner I7 signal |
| `narratives:*:*` | `AINarrativeService` | `LLMWriterService` | I8 LLM analysis |
| `llm.calls` | `AINarrativeService` | `LLMWriterService` | LLM call records |

All topic strings constructed via `src/core/stream_keys.py` — never hardcoded.

---

## Service Inventory

| File | Class | Unit | Port |
|------|-------|------|------|
| `services/ibkr_provider_agent.py` | `IBKRProviderAgent` | `indicagent-ibkr-provider` | :9129 |
| `services/provider_merger_agent.py` | `ProviderMergerAgent` | `indicagent-provider-merger` | :9130 |
| `services/bar_aggregator_agent.py` | `BarAggregatorComputeAgent` | `indicagent-bar-aggregator-compute` | :9120 |
| `services/bar_writer_agent.py` | `BarWriterAgent` | `indicagent-bar-writer` | :9121 |
| `services/bar_auditor_agent.py` | `BarAuditorAgent` | `indicagent-bar-auditor` | :9123 |
| `services/roll_compute_agent.py` | `RollComputeAgent` | `indicagent-roll-compute` | :9122 |
| `services/intelligence_pipeline_agent.py` | `IntelligencePipelineComputeAgent` | `indicagent-intelligence-pipeline` | :9125 |
| `services/feature_writer_agent.py` | `FeatureWriterAgent` | `indicagent-feature-writer` | :9116 |
| `services/signal_writer_agent.py` | `SignalWriterAgent` | `indicagent-signal-writer` | :9117 |
| `services/signal_tracker_agent.py` | `SignalTrackerAgent` | `indicagent-signal-tracker` | :9115 |
| `services/ai_narrative_service.py` | `AINarrativeService` | `indicagent-ai-narrative` | :9113 |
| `services/llm_writer_service.py` | `LLMWriterService` | `indicagent-llm-writer` | :9117 |
| `services/cross_asset_service.py` | `CrossAssetService` | `indicagent-cross-asset` | :9118 |
| `services/parity_auditor_agent.py` | `ParityAuditorAgent` | `indicagent-parity-auditor` | :9124 |

---

## Architectural Invariants

1. **`ProviderMergerAgent` is the sole writer to `market.bars`.** All downstream consumers isolated from provider topology.

2. **I1–I7 runs entirely in-process.** `IntelligencePipelineComputeAgent` computes all tiers in-memory before publishing. Kafka is a sink, not an inter-stage pipe.

3. **No ComputeAgent touches the database.** Only `WriterAgent`, `TrackerAgent`, and `AuditorAgent` perform DB operations.

4. **All topic keys via `stream_keys.py`.** No hardcoded topic strings.

5. **Scaling via systemd + Prometheus lag.** No Kubernetes HPA. Consumer lag monitored via `persistence_consumer_lag` metric.

6. **All timestamps UTC.** Every bar, event, and DB write uses timezone-aware UTC datetimes.

---

## See Also

- `PLUGIN_PROTOCOL.md` — Plugin interface and developer contract
- `AGENT_STANDARD.md` — Role taxonomy and naming conventions
- `BASE_AGENT_PATTERNS.md` — BaseAgent lifecycle contract
- `plugin-native-architecture-explained.md` — Architectural principles
