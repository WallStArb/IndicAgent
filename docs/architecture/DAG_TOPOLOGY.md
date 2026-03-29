# Architectural Standard: Intelligence DAG Topology

Version: 2.0 (Phase 54 — Provider Abstraction Layer)
Last Updated: 2026-03-29

## Overview

The IndicAgent pipeline is an event-driven, Agentic DAG (Directed Acyclic Graph). Data flows from raw market data sources through a provider abstraction layer, bar aggregation tier, intelligence compute tiers (I1–I7), and finally into persistence. All inter-agent communication is via Redpanda (Kafka-compatible) topics. No agent communicates directly with another agent in process.

## Agent Taxonomy

Each agent has exactly one role, expressed in its class name suffix:

| Role Suffix | Responsibility | DB Access |
|-------------|---------------|-----------|
| `ProviderAgent` | External source → Kafka raw topic. No compute, no DB. | None |
| `MergerAgent` | Multi-source routing + auto-failover. DB-ignorant. | None |
| `ComputeAgent` | Math/stats transform. DB-ignorant. | None |
| `WriterAgent` | DB persistence only. | Write |
| `GeneratorAgent` | Signal/trade fire logic. | Write |
| `TrackerAgent` | Business object lifecycle management. | Read/Write |
| `AuditorAgent` | Data integrity validation + self-healing. | Read |

All agents extend `BaseAgent` (`src/core/agent/base.py`) and implement the `_setup → _run → _teardown` lifecycle with `SIGTERM` graceful drain.

## Full DAG Topology

```mermaid
graph TD
    subgraph Sources["External Data Sources"]
        TWS["IBKR TWS\n192.168.1.157"]
    end

    subgraph ProviderLayer["Provider Layer (Phase 54)"]
        BASE["BaseProviderAgent\nsrc/providers/base_provider_agent.py\nabstract base"]
        IBKR["IBKRProviderAgent\nservices/ibkr_provider_agent.py\n:9129"]
        BASE -->|subclass| IBKR
        TWS --> IBKR
    end

    subgraph MergerLayer["Merger Layer"]
        MERGER["ProviderMergerAgent\nservices/provider_merger_agent.py\n:9130"]
    end

    subgraph BarTier["Bar Processing Tier"]
        BAGG["BarAggregatorComputeAgent\nservices/bar_aggregator_agent.py\n:9120"]
        BWRITE["BarWriterAgent\nservices/bar_writer_agent.py\n:9121"]
        BAUDIT["BarAuditorAgent\nservices/bar_auditor_agent.py\n:9123"]
        ROLL["RollComputeAgent\nservices/roll_compute_agent.py\n:9122"]
    end

    subgraph IntelTier["Intelligence Compute Tier"]
        FEAT["FeatureComputeAgent\nservices/feature_compute_agent.py\n:9125\nI1–I6 unified"]
        SIGGEN["SignalGeneratorAgent\nservices/signal_generator_agent.py\n:9112\nI7"]
        INTEL["IntelligenceComputeAgent\nservices/intelligence_compute_agent.py\n:9114\nstandalone I7/I8"]
        NARR["AINarrativeAgent\n:9113\nI8 / LLM"]
    end

    subgraph PersistTier["Persistence Tier"]
        FWRITE["FeatureWriterAgent\nservices/feature_writer_agent.py\n:9116"]
        LLMWRITE["LLMWriterAgent\n:9117"]
        SIGTRACK["SignalTrackerAgent\nservices/signal_tracker_agent.py\n:9115"]
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
    MERGER -->|"market.bars (canonical)"| BWRITE
    MERGER -->|"market.bars (canonical)"| FEAT
    MERGER -->|"market.data.quality (side-channel)"| SIGGEN

    %% Bar tier
    BAGG -->|"market.bars.htf (5m–1d)"| BWRITE
    BAGG -->|"market.bars.htf"| BAUDIT
    BAGG -->|"market.bars.htf"| FEAT
    BAGG -->|"market.bars.htf"| SIGGEN
    BAUDIT -->|"market.events.gap_requests"| IBKR
    ROLL -->|"market.events.roll"| SIGGEN
    BWRITE --> OHLCV

    %% Intelligence compute
    FEAT -->|"intelligence:{SYMBOL}:{TF}"| SIGGEN
    FEAT -->|"intelligence:{SYMBOL}:{TF}"| FWRITE
    FEAT -->|"intelligence:{SYMBOL}:{TF}"| NARR
    FEAT -->|"intelligence:{SYMBOL}:{TF}"| INTEL

    %% Persistence
    SIGGEN -->|"signals.aggregated"| SIGTRACK
    SIGGEN --> SIGLED
    FWRITE --> INTFEAT
    NARR -->|"narratives:{SYMBOL}:{TF}"| LLMWRITE
    LLMWRITE --> LLMDB
    SIGTRACK --> SIGLED
```

## Primary Data Flow (Step by Step)

### 1. Provider Layer
`IBKRProviderAgent` connects to IBKR TWS and emits 1m bars to `market.bars.raw.ibkr`. It never writes to `market.bars` directly — that is the MergerAgent's exclusive responsibility. `BaseProviderAgent` (`src/providers/base_provider_agent.py`) provides lifecycle, metrics, exponential-backoff reconnect, and gap-fill handling. Additional providers would subclass `BaseProviderAgent` and publish to their own `market.bars.raw.<provider>` topic.

### 2. Merger Layer
`ProviderMergerAgent` subscribes to all `market.bars.raw.<provider>` topics and routes the authoritative provider's bars to the canonical `market.bars` topic. It implements auto-failover when the primary provider has been silent for `provider_silence_bars_threshold` bar intervals. A `ProviderQualityEvent` is published to `market.data.quality` on every routed bar, failover event, and recovery event.

`market.bars` is the single source of truth for all downstream consumers — they are completely isolated from provider topology changes.

### 3. Bar Processing Tier

| Agent | Input | Output | Purpose |
|-------|-------|--------|---------|
| `BarAggregatorComputeAgent` | `market.bars` (1m) | `market.bars.htf` | Aggregates 1m bars into 5m, 15m, 1h, 4h, 1d via `BarAccumulator` |
| `BarWriterAgent` | `market.bars` + `market.bars.htf` | `market_data_ohlcv` | Batch-writes all OHLCV bars to TimescaleDB |
| `BarAuditorAgent` | `market.bars.htf` | `market.events.gap_requests` | Detects gaps in bar sequences; emits gap fill requests |
| `RollComputeAgent` | `market.bars` | `market.events.roll` | Detects futures contract roll events |

### 4. Intelligence Compute Tier

`FeatureComputeAgent` subscribes to both `market.bars` (1m) and `market.bars.htf` (all HTF timeframes). Each incoming bar triggers a full I1–I6 compute pipeline run in memory. Output is published as `IntelligenceEvent` to `intelligence:{SYMBOL}:{TF}`.

`SignalGeneratorAgent` subscribes to `intelligence:{SYMBOL}:{TF}` and runs the I7 signal generation logic. It writes all signals (not just the winner) to `signal_ledger` and publishes the winning signal to `signals.aggregated`.

`IntelligenceComputeAgent` is a standalone alternative I7/I8 compute loop with its own `BarHistorySeeder` warmup. It runs independently and does not replace `FeatureComputeAgent` + `SignalGeneratorAgent`.

### 5. Persistence Tier

| Agent | Input | Output | Purpose |
|-------|-------|--------|---------|
| `FeatureWriterAgent` | `intelligence:{SYMBOL}:{TF}` | `intelligence_features` | Batch-writes full feature vectors (I1–I7 JSONB) |
| `SignalTrackerAgent` | `signals.aggregated` | `signal_ledger` | Tracks signal lifecycle: activation, MAE/MFE, 8-class outcome |
| `LLMWriterAgent` | `llm.calls` | `llm_calls` | Writes LLM audit log; back-fills outcomes |

## Topic Registry

| Topic | Producer | Consumers | Content |
|-------|----------|-----------|---------|
| `market.bars.raw.ibkr` | `IBKRProviderAgent` | `ProviderMergerAgent` | Raw 1m bars from IBKR |
| `market.bars.raw.<provider>` | Any `ProviderAgent` subclass | `ProviderMergerAgent` | Raw bars per provider |
| `market.bars` | `ProviderMergerAgent` | `BarAggregatorComputeAgent`, `BarWriterAgent`, `FeatureComputeAgent`, `SignalGeneratorAgent` | Canonical 1m bars |
| `market.bars.htf` | `BarAggregatorComputeAgent` | `BarWriterAgent`, `BarAuditorAgent`, `FeatureComputeAgent`, `SignalGeneratorAgent` | Aggregated HTF bars (5m–1d) |
| `market.data.quality` | `ProviderMergerAgent` | Observability consumers | Provider quality events (latency, failover, recovery) |
| `market.events.gap_requests` | `BarAuditorAgent` | `IBKRProviderAgent` (gap fill) | Gap fill requests |
| `market.events.roll` | `RollComputeAgent` | `SignalGeneratorAgent` | Futures roll events |
| `intelligence:{SYMBOL}:{TF}` | `FeatureComputeAgent` | `SignalGeneratorAgent`, `FeatureWriterAgent`, `AINarrativeAgent`, `IntelligenceComputeAgent` | Full I1–I6 feature vectors per bar |
| `signals.aggregated` | `SignalGeneratorAgent` | `SignalTrackerAgent` | Winning ranked signals |
| `narratives:{SYMBOL}:{TF}` | `AINarrativeAgent` | `LLMWriterAgent` | LLM narrative analysis |
| `llm.calls` | `AINarrativeAgent` | `LLMWriterAgent` | Raw LLM call records |

All topic strings are constructed via `src/core/stream_keys.py` — never hardcoded.

## Service → Systemd Unit Map

| Service File | Systemd Unit | Metrics Port |
|---|---|---|
| `services/ibkr_provider_agent.py` | `indicagent-ibkr-provider` | :9129 |
| `services/provider_merger_agent.py` | `indicagent-provider-merger` | :9130 |
| `services/bar_aggregator_agent.py` | `indicagent-bar-aggregator-compute` | :9120 |
| `services/bar_writer_agent.py` | `indicagent-bar-writer` | :9121 |
| `services/bar_auditor_agent.py` | `indicagent-bar-auditor` | :9123 |
| `services/roll_compute_agent.py` | `indicagent-roll-compute` | :9122 |
| `services/feature_compute_agent.py` | `indicagent-feature-compute` | :9125 |
| `services/signal_generator_agent.py` | `indicagent-signal-generator` | :9112 |
| `services/intelligence_compute_agent.py` | `indicagent-intelligence-compute` | :9114 |
| `services/feature_writer_agent.py` | `indicagent-feature-writer` | :9116 |
| `services/signal_tracker_agent.py` | `indicagent-signal-tracker` | :9115 |
| AI Narrative | `indicagent-ai-narrative` | :9113 |
| LLM Writer | `indicagent-llm-writer` | :9117 |

## Architectural Invariants

- **`ProviderMergerAgent` is the sole writer to `market.bars`.** All downstream consumers are isolated from provider topology changes. Adding or removing a provider requires no downstream changes.
- **I1–I6 runs entirely in-process.** `FeatureComputeAgent` computes all intelligence tiers in memory before publishing a single `IntelligenceEvent`. Kafka is a sink, not an inter-stage pipe.
- **No ComputeAgent touches the database.** Only `WriterAgent`, `GeneratorAgent`, and `TrackerAgent` subclasses perform DB operations.
- **All topic keys via `stream_keys.py`.** No hardcoded topic strings anywhere in service code.
- **Scaling via systemd + Prometheus lag.** No Kubernetes HPA. Consumer lag monitored via `persistence_consumer_lag` metric.
- **All timestamps UTC.** Every bar, event, and DB write uses timezone-aware UTC datetimes.
