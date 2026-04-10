# AI Intelligence Architecture

**Version:** 3.2.0
**Last Updated:** 2026-04-07
**Status:** Operational — I1–I8 pipeline complete (121 plugins + 2 aggregation). Unified IntelligencePipelineComputeAgent with parallelized I1/I7 tiers. LLM stack: OpenRouter (primary) → Ollama local (offline fallback).

## Executive Summary

IndicAgent's intelligence pipeline transforms raw market data through seven analytical tiers (I1-I7), followed by AI-powered narrative generation (I8). The pipeline uses a **unified in-process architecture** — I1-I7 execute in a single agent with parallelized tiers where Python's GIL permits. I8 provides human-readable market commentary via a 2-tier LLM inference chain.

**Core Architecture:**
- **Unified Pipeline:** Single `IntelligencePipelineComputeAgent` runs I1-I7 in-process
- **Parallelized Tiers:** I1 (27 plugins) and I7 (36 plugins) execute concurrently via `asyncio.gather`
- **Sequential Bottleneck:** I2-I6 tiers execute sequentially (current optimization target)
- **Provider Abstraction:** Multi-provider support via `ProviderMergerAgent` failover
- **DB-Ignorant Compute:** All intelligence agents publish to Kafka; WriterAgents handle persistence

---

## I1-I7 Unified Intelligence Pipeline

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Provider Layer                          │
│  IBKRProviderAgent → market.bars.raw.ibkr                      │
│                          ↓                                      │
│              ProviderMergerAgent (failover, routing)            │
│                          ↓                                      │
│                market.bars (canonical 1m)                       │
│                          ↓                                      │
│         BarAggregatorComputeAgent (1m → HTF)                    │
│                          ↓                                      │
│                market.bars.htf (5m/15m/1h/4h/1d)                │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│              IntelligencePipelineComputeAgent                  │
│                   (I1→I7 IN-PROCESS)                           │
│                                                                  │
│  Bar → [I1 parallel] → I2 → I3 → I4 → I5 → I6 → [I7 parallel] │
│                                                                  │
│  Internal asyncio.Queue (I6→I7) — zero I/O on hot path         │
│  State checkpointing — no warmup on restart                    │
└─────────────────────────────────────────────────────────────────┘
                          ↓                 ↓
              intelligence.journal    intelligence.i7.signals
              (tiered JSONB)           (winner signal)
                          ↓                 ↓
┌─────────────────────────────────────────────────────────────────┐
│                      Persistence Layer                         │
│  FeatureWriterAgent → intelligence_features (DB)               │
│  SignalWriterAgent → signal_ledger (DB)                        │
└─────────────────────────────────────────────────────────────────┘
```

### Tier Parallelization

**Parallelized (via asyncio.gather + ThreadPoolExecutor):**
- **I1 (27 plugins)** — Technical indicators (RSI, MACD, ATR, ADX, BB, etc.)
- **I7 (36 plugins)** — Trading signals with confidence scores

**Sequential (current bottleneck):**
- **I2** — Volume analysis events
- **I3 (15 plugins)** — Pattern detection (FVG, OB, BB, SMC)
- **I4 (11 plugins)** — Context scoring, regime detection
- **I5-I6** — Confluence, CIS scoring, calibration

**Why:** Python's GIL prevents ThreadPoolExecutor from achieving true parallelism. Only one thread executes Python bytecode at a time. CPU-bound work (plugin compute) cannot utilize multiple cores regardless of worker count.

**Latency Breakdown:**
- I1 (parallel): 30ms
- I2-I6 (sequential): 160ms (73% of total)
- I7 (parallel): 20ms

**See:** `docs/architecture/PIPELINE_OPTIMIZATION.md` for optimization strategy (batch processing).

---

## I8 AI Narrative Layer

### 2-Tier LLM Inference Chain

The `ai_narrative_service` (I8) uses `LLMChain` from `src/intelligence/llm_providers.py` — providers are tried in order and the first successful response is returned immediately.

```
Tier 1 (Primary)   — OpenRouter
                     Access to 100+ models from major providers (Llama, Mistral, Gemini,
                     Claude, etc.) through a single API. Free-tier models available.
                     Endpoint: https://openrouter.ai/api/v1
                     Env: OPENROUTER_API_KEY, OPENROUTER_TIMEOUT_SEC
                     Default: meta-llama/llama-3.3-70b-instruct:free

Tier 2 (Offline)   — Ollama (local)
                     Runs entirely on-device — always available even with no internet
                     or API access. Adds latency but guarantees narrative generation.
                     Endpoint: http://localhost:11434
                     Env: OLLAMA_BASE_URL, OLLAMA_TIMEOUT_SEC
                     Default: qwen3.5:9b
```

### Provider Chain Setup

```python
from src.intelligence.llm_providers import LLMChain, OpenRouterProvider, OllamaProvider

chain = LLMChain([
    OpenRouterProvider(model="meta-llama/llama-3.3-70b-instruct:free",
                       api_key=settings.openrouter_api_key),
    OllamaProvider(model="qwen3.5:9b", base_url=settings.ollama_base_url),
])
text = await chain.generate(prompt, system, max_tokens=500, timeout=30.0)
```

### LLMs Research-Only Principle

Per the Renaissance validation framework, LLMs are **research-only** in our architecture:

- **Beta Pipeline (Offline):** LLMs analyze historical patterns, discover heuristics, generate insights → compiled to deterministic code
- **Alpha Pipeline (Production):** No LLM calls in the hot path. Real-time signal enrichment uses only deterministic Python feature extractors

The I8 AI Narrative layer is the exception (generates human-readable explanations), but its outputs never directly affect position sizing without passing through validation gates first.

**See:** `docs/ideas/renaissance-alpha-pipeline.md` for full validation framework design.

---

## Redpanda Topics

All topic names are built via `src/core/stream_keys.py`.

```python
from src.core.stream_keys import (
    topic_market_bars,           # market.bars — Canonical 1m bars
    topic_market_bars_htf,       # market.bars.htf — HTF bars (5m-1d)
    topic_intelligence_journal,  # intelligence.journal — Full I1-I7 feature vector
    topic_intelligence_i7_signals,# intelligence.i7.signals — Winner I7 signal
    topic_narratives,            # narratives:*:* — I8 LLM narrative per symbol/TF
    topic_llm_calls,             # llm.calls — Full LLM audit log
)
```

**Topic Naming Convention:** `<env>.<domain>[.<sublayer>]` — dots only, never colons.

---

## Services Reference

| Service | Unit | Metrics | Purpose |
|---------|------|---------|---------|
| IBKR Provider | `indicagent-ibkr-provider` | :9129 | IBKR dual streams → `market.bars.raw.ibkr` |
| Provider Merger | `indicagent-provider-merger` | :9130 | Routes `market.bars.raw.*` → `market.bars` |
| Bar Aggregator | `indicagent-bar-aggregator` | :9120 | 1m → HTF aggregation → `market.bars.htf` |
| Intelligence Pipeline | `indicagent-intelligence-pipeline` | :9125 | I1-I7 unified in-process pipeline |
| Feature Writer | `indicagent-feature-writer` | :9116 | `intelligence.journal` → `intelligence_features` (DB) |
| Signal Writer | `indicagent-signal-writer` | :9119 | `intelligence.i7.signals` → `signal_ledger` (DB) |
| Signal Tracker | `indicagent-signal-tracker` | :9115 | Signal lifecycle (activation, MAE/MFE, outcome) |
| AI Narrative | `indicagent-ai-narrative` | :9113 | I8 LLM analysis → `narratives:*:*` |
| LLM Writer | `indicagent-llm-writer` | :9117 | `llm.calls` → `llm_calls` (DB) + outcome back-fill |

---

## Database Schema

**Hypertables (TimescaleDB):**
- `market_data_ohlcv` — Raw OHLCV ground truth (keep forever)
- `intelligence_features` — Full I1-I7 feature vectors per bar (ML training dataset, keep forever)
- `signal_ledger` — ALL I7 signals + lifecycle outcomes (keep forever)
- `llm_calls` — LLM audit log + outcomes (keep forever)

**Design Principle:** Never drop data that could contain signal. Storage is cheapest, data is irreplaceable.

---

## Plugin System

121 plugins across tiers I1-I7. See `src/intelligence/CLAUDE.md` for tier details, plugin protocol, and LLM provider chain.

**Tier lists:** `TIER_I1`…`TIER_I7` in `src/intelligence/register_plugins.py` — single source of truth.

**Plugin counts:**
- I1: 27 plugins (technical indicators)
- I3: 15 plugins (pattern detection)
- I4: 11 plugins (context scoring)
- I7: 36 plugins (trading signals)

**Key constraint:** Plugins must never know about other plugins directly. Cross-plugin communication goes through tier output schemas only.

---

## Related Documentation

- **Current State:** `docs/architecture/CURRENT_STATE.md` — Active services, data flow, performance
- **Optimization:** `docs/architecture/PIPELINE_OPTIMIZATION.md` — Batch processing strategy, GIL constraints
- **Evolution:** `docs/architecture/renaissance-pipeline-evolution.md` — Architecture principles and patterns
- **Plugin Protocol:** `docs/architecture/PLUGIN_PROTOCOL.md` — How plugins work
- **ML Tech Stack:** `docs/intelligence/ai-tech-stack.md` — ML/AI technology choices
- **ML Resources:** `docs/intelligence/ai-intelligence-resources.md` — Implementation examples

---

*Focus: Architecture and functionality, not implementation phases*
