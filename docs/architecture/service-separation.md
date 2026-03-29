# Service Separation of Duties

**Last Updated:** 2026-03-29
**Status:** Production — I1-I8 complete (phases 52-54)

---

## Principle

Each service has **one reason to change**. Services communicate exclusively via Redpanda topics — no direct HTTP calls between services in the pipeline. A service can be restarted, redeployed, or scaled independently without affecting others.

---

## Services and Responsibilities

### Data Ingestion Tier

#### `ibkr_provider_agent.py` — `indicagent-ibkr-provider` (`:9129`)

**Responsibility:** Connect to IBKR TWS, ingest live ticks, form 5s real-time bars and 1m OHLCV bars, and publish raw bars to the provider-specific topic.

Owns the IBKR connection. Restarting it disconnects from the broker. All `ib_insync` logic lives in `src/providers/ibkr.py` — no imports outside that file.

**Publishes:** `market.bars.raw.ibkr`

---

#### `provider_merger_agent.py` — `indicagent-provider-merger` (`:9130`)

**Responsibility:** Route provider-specific raw bar topics to the canonical `market.bars` stream. Implements auto-failover on primary provider silence. Publishes a `market.data.quality` side-channel (`ProviderQualityEvent`) for downstream observability.

This agent is the canonical author of `market.bars`. All downstream consumers are shielded from provider implementation details — swapping or adding a provider requires no changes downstream of this agent.

**Consumes:** `market.bars.raw.*` (all provider topics, e.g., `market.bars.raw.ibkr`)
**Publishes:** `market.bars`, `market.data.quality`

---

### Bar Processing Tier

#### `bar_aggregator_agent.py` — `indicagent-bar-aggregator-compute` (`:9120`)

**Responsibility:** Aggregate canonical 1m bars into higher timeframes (5m, 15m, 1h, 4h, 1d) via `BarAccumulator`. Session break logic prevents cross-session contamination. Overnight gaps do not skip bars — period boundary crossing on the next 1m bar triggers emission of the accumulated HTF bar.

**Consumes:** `market.bars`
**Publishes:** `market.bars.htf`

---

#### `bar_writer_agent.py` — `indicagent-bar-writer` (`:9121`)

**Responsibility:** Async decoupled persistence of OHLCV bars to cold storage. Consumes both the canonical 1m stream and the HTF stream; batches writes to `market_data_ohlcv`.

**Consumes:** `market.bars`, `market.bars.htf`
**Writes:** `market_data_ohlcv` hypertable

---

#### `bar_auditor_agent.py` — `indicagent-bar-auditor` (`:9123`)

**Responsibility:** Detect gaps in the HTF bar stream and emit gap fill requests for downstream resolution.

**Consumes:** `market.bars.htf`
**Publishes:** `market.events.gap_requests`

---

#### `roll_compute_agent.py` — `indicagent-roll-compute` (`:9122`)

**Responsibility:** Detect futures contract roll events and publish roll notifications for downstream regime-aware logic.

**Publishes:** `market.events.roll`

---

### Intelligence Tier

#### `feature_compute_agent.py` — `indicagent-feature-compute` (`:9125`)

**Responsibility:** Unified I1–I6 analysis. Executes the mathematical and market intelligence pipeline (technical indicators, market structure, regime context, pattern recognition, SMC) for both 1m and HTF bars. Each bar triggers an independent I1-I6 pipeline run.

Does **not** write to the database — intelligence features are persisted by `feature_writer_service`.

**Consumes:** `market.bars` (1m), `market.bars.htf` (HTF bars from BarAggregatorComputeAgent)
**Publishes:** `intelligence:SYMBOL:TF`

---

#### `signal_generator_agent.py` — `indicagent-signal-generator` (`:9112`)

**Responsibility:** Detect trading setups and produce actionable signals (I7). On each enriched bar: runs all I7 setup plugins + aggregation components (CISScorer, SignalAggregator). Writes every signal to the ledger regardless of regime eligibility — the winner is published to the stream separately.

**Consumes:** `intelligence:SYMBOL:TF`
**Publishes:** `signals.aggregated`
**Writes:** `signal_ledger` (new signal rows)

---

#### `signal_tracker_agent.py` — `indicagent-signal-tracker` (`:9115`)

**Responsibility:** Zone-aware lifecycle tracking for all pending and active signals. Evaluates activation, tracks MAE/MFE, and classifies exits into 8-class outcomes. Renamed from `signal-lifecycle` in phase 52.4; inherits `BaseAgent`.

**Consumes:** `signals.aggregated`
**Writes:** `signal_ledger` (lifecycle updates)
**Publishes:** `llm_outcomes:stream` (signal exits with outcome/pnl_r/mae/mfe)

---

#### `ai_narrative_service.py` — `indicagent-ai-narrative` (`:9113`)

**Responsibility:** Synthesise AI narratives from aggregated signals using a local LLM (Ollama `qwen3.5:9b`). Uses `LLMChain` with ordered fallback across multiple free OpenRouter models to prevent rate limit failures.

**Consumes:** `signals.aggregated`
**Publishes:** `narratives:SYMBOL:TF`, `llm.calls`

---

### Persistence Tier

#### `feature_writer_service.py` — `indicagent-feature-writer` (`:9116`)

**Responsibility:** Async decoupled persistence of intelligence features from the hot path to cold storage. Consumes `intelligence:SYMBOL:TF` stream and batches writes to `intelligence_features` hypertable.

**Consumes:** `intelligence:SYMBOL:TF`
**Writes:** `intelligence_features` hypertable

---

#### `llm_writer_service.py` — `indicagent-llm-writer` (`:9117`)

**Responsibility:** Persist LLM call audit records and update model performance scores. Consumes `llm.calls` and `llm_outcomes:stream`. Back-fills outcomes after signal resolution.

**Consumes:** `llm.calls`, `llm_outcomes:stream`
**Writes:** `llm_calls` hypertable, `llm_model_scores` table

---

## Stream Flow

```
IBKR TWS
   │
   ▼
IBKRProviderAgent ──► market.bars.raw.ibkr
                                │
                                ▼
                   ProviderMergerAgent  ◄── market.bars.raw.{other}
                                │
                                ▼
                          market.bars  ◄─────────────────────────────────────┐
                          (canonical)                                         │
                                │                                             │
              ┌─────────────────┼──────────────────────┐                     │
              ▼                 ▼                       ▼                     │
   BarAggregatorComputeAgent  BarWriterAgent      BarAuditorAgent             │
              │               (writes             (gap detection)             │
              ▼                market_data_ohlcv)      │                      │
       market.bars.htf                                 ▼                      │
              │                              market.events.gap_requests       │
              ├─────────────────────────────────────────────────────────────  │
              │  (also consumed by BarWriterAgent)                            │
              ▼
   FeatureComputeAgent (I1-I6)  ◄── market.bars (1m) ───────────────────────┘
              │
              ▼
      intelligence:SYMBOL:TF
      (fully enriched bar)
              │
              ├──────────────────────────────┐
              ▼                              ▼
   SignalGeneratorAgent (I7)      FeatureWriterService
              │                   (writes intelligence_features)
              ▼
      signals.aggregated
              │
              ├───────────────────────────────┐
              ▼                               ▼
   SignalTrackerAgent              AINarrativeService (I8)
   (lifecycle: MAE/MFE,                       │
    8-class outcome)                          ├──► narratives:SYMBOL:TF
              │                               └──► llm.calls
              ▼                                        │
      llm_outcomes:stream                              ▼
              │                               LLMWriterService
              └──────────────────────────────► (writes llm_calls,
                                                llm_model_scores)
```

---

## Stream Key Reference

All stream keys are constructed via `src/core/stream_keys.py` — never hardcoded. Kafka topic naming uses dots only (`development.market.bars`, not `market:SYMBOL:TF`).

| Stream | Producer | Consumer(s) |
|--------|----------|-------------|
| `market.bars.raw.{provider}` | `IBKRProviderAgent` (and future providers) | `ProviderMergerAgent` |
| `market.bars` | `ProviderMergerAgent` | `BarAggregatorComputeAgent`, `BarWriterAgent`, `BarAuditorAgent`, `FeatureComputeAgent` |
| `market.bars.htf` | `BarAggregatorComputeAgent` | `BarWriterAgent`, `FeatureComputeAgent` |
| `market.data.quality` | `ProviderMergerAgent` | observability consumers |
| `market.events.gap_requests` | `BarAuditorAgent` | gap fill handlers |
| `market.events.roll` | `RollComputeAgent` | downstream regime-aware consumers |
| `intelligence:SYMBOL:TF` | `FeatureComputeAgent` | `SignalGeneratorAgent`, `FeatureWriterService` |
| `signals.aggregated` | `SignalGeneratorAgent` | `SignalTrackerAgent`, `AINarrativeService` |
| `narratives:SYMBOL:TF` | `AINarrativeService` | `api_service` |
| `llm.calls` | `AINarrativeService` | `LLMWriterService` |
| `llm_outcomes:stream` | `SignalTrackerAgent` | `LLMWriterService` |
