# AI Intelligence Architecture

**Version:** 3.3.0
**Last Updated:** 2026-04-21
**Status:** Operational — I1–I8 pipeline complete (123 plugins + 2 aggregation). Unified IntelligencePipelineComputeAgent with parallelized I1/I7 tiers. LLM stack: OpenRouter (primary) → Ollama local (offline fallback).

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
- **I2 (10 plugins)** — Composite events (crossovers, exhaustion, acceleration)
- **I3 (8 plugins)** — Market structure (swing, S/R, market profile, session levels)
- **I4 (12 plugins)** — Context scoring, regime detection (GARCH, Kalman, VIXRegime, etc.)
- **I5 (16 plugins) + SMC (13 plugins)** — Patterns + Smart Money Concepts
- **I6 (1 plugin)** — CrossTimeframeConfluence → CIS scoring, isotonic calibration

**Why:** Python's GIL prevents ThreadPoolExecutor from achieving true parallelism. Only one thread executes Python bytecode at a time. CPU-bound work (plugin compute) cannot utilize multiple cores regardless of worker count.

**Latency Breakdown:**
- I1 (parallel): 30ms
- I2-I6 (sequential): 160ms (73% of total)
- I7 (parallel): 20ms

**See:** `docs/architecture/pipeline-optimization.md` for optimization strategy (batch processing).

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
                     Default: gemma4:e4b
```

### Provider Chain Setup

```python
from src.intelligence.llm_providers import LLMChain, OpenRouterProvider, OllamaProvider

chain = LLMChain([
    OpenRouterProvider(model="meta-llama/llama-3.3-70b-instruct:free",
                       api_key=settings.openrouter_api_key),
    OllamaProvider(model="gemma4:e4b", base_url=settings.ollama_base_url),
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

## Intelligence Swarm (Path B — Async, Out-of-Band)

The swarm runs alongside the deterministic I1-I7 pipeline without ever blocking it. When an I7 signal fires, `SwarmOrchestratorComputeAgent` fans out to specialist agents that reason about the signal context and produce an `AlphaMultiplier` — applied downstream, after the fact.

```
I7 signal → SwarmOrchestratorComputeAgent
                ├── Path A: deterministic contributors (parallel, <5ms each)
                └── Path B: LLM reasoning agents (async, shadow-only until promoted)
                          ↓
                    SwarmAggregator → AlphaMultiplier [0.7–1.3 clamped]
                          ↓
                    SwarmWriterAgent → alpha_multiplier_shadow (DB)
```

Every agent implements `IAlphaContributor` (`src/core/agents/alpha_contributor.py`). Each receives a `SwarmContext` — a typed, immutable snapshot of I1/I4/I6 features at signal time, built from in-memory cache with no DB access. `SafeSwarmWrapper` enforces a hard timeout and exception isolation around every agent — a failing agent returns `multiplier=1.0, confidence=0.0` and is invisible to the aggregator.

No swarm agent affects production signal confidence until `ρ > 0.4` AND `N ≥ 100` AND `p < 0.05` over a 14-day rolling window. All agents start `shadow_only=True`.

**See:** `docs/intelligence/swarm-architecture.md` — full swarm architecture, data contract, agent registry, and validation gate.

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
| Bar Aggregator | `indicagent-bar-aggregator-compute` | :9120 | 1m → HTF aggregation → `market.bars.htf` |
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

## CIS & Signal Confidence Pipeline

**Pipeline position:** `I5/SMC outputs → I6 CTF sub-scores → CISScorer → I7 setup plugins → SignalAggregator → ranked signal`

CIS (Confluence Intelligence Score) is computed by `CISScorer` after I6 and before I7 setup plugins run. It requires agreement from at least 3 of 6 independent evidence buckets:

| Bucket | Reads from | Weight |
|--------|-----------|--------|
| **Trend** | Kalman slope, trend regime, SMC trend, cross-TF alignment | 0.20 |
| **Momentum** | RSI deviation, MACD histogram, ROC, momentum bias | 0.20 |
| **Structure** | Swing pattern, BOS/CHoCH events | 0.15 |
| **Pattern** | Double top/bottom, H&S, triangle completions | 0.05 |
| **Institutional** | Order blocks, FVG activity, supply/demand zones | 0.25 |
| **Regime** | HMM state probabilities, BOCPD changepoint, vol regime | 0.15 |

**Rule:** `|score| > 0.35` AND at least 3 of 6 buckets agree on direction.

### Six-Layer Self-Correction Stack

Signal confidence flows through six autonomous correction layers before ranking:

```
Raw confidence (I7 plugin output)
    → [1] Isotonic calibration    → calibrated_confidence
    → [2] TOD multiplier          → time-adjusted confidence
    → [3] perf_multiplier         → performance-weighted rank in all_ranked
    → [4] KS drift penalty        → distribution-aware CIS bucket weights
    → [5] CUSUM monitor           → feedback loop back into perf_multiplier
    → [6] Shadow mode gate        → statistical proof before production eligibility
```

| Layer | Mechanism | What it corrects |
|-------|-----------|-----------------|
| **[1] Isotonic calibration** | Isotonic regression on `signal_ledger` outcomes | Systematic over/under-confidence per plugin/regime |
| **[2] TOD multiplier** | Per-cell `(regime_type, tf, hour_et)` — 120 cells | Session-dependent signal quality variation |
| **[3] perf_multiplier** | `setup_performance` table (refreshed 15 min); N<30 gate = no effect | Underperforming setups demoted in `all_ranked` |
| **[4] KS drift** | Kolmogorov-Smirnov vs. historical baseline → CIS bucket weight penalty | Feature distribution shifts before they cause outcome degradation |
| **[5] CUSUM** | Cumulative Sum control charts on win-rate → auto-adjusts `perf_multiplier` | Closes the loop with [3]; no manual intervention |
| **[6] Shadow gate** | `p < 0.05` AND `N ≥ 100` resolved signals required | Prevents unproven features from reaching production |

**Key invariant:** `active` signal is always derived from `all_ranked`, never from the raw `signals` list — otherwise `perf_multiplier` silently has no effect on winner selection.

---

## Plugin System

123 plugins across tiers I1-I7. See `src/intelligence/CLAUDE.md` for tier details, plugin protocol, and LLM provider chain.

**Tier lists:** `TIER_I1`…`TIER_I7` in `src/intelligence/register_plugins.py` — single source of truth.

**Plugin counts:**
- I1: 27 plugins (technical indicators + OFI/CVD microstructure)
- I2: 10 plugins (composite events)
- I3: 8 plugins (market structure)
- I4: 12 plugins (context/regime)
- I5: 16 plugins (patterns)
- SMC: 13 plugins (Smart Money Concepts)
- I6: 1 plugin (CrossTimeframeConfluence)
- I7: 36 plugins (trading signals)

**Key constraint:** Plugins must never know about other plugins directly. Cross-plugin communication goes through tier output schemas only.

---

## Related Documentation

- **Current State:** `docs/architecture/current-state.md` — Active services, data flow, performance
- **Optimization:** `docs/architecture/pipeline-optimization.md` — Batch processing strategy, GIL constraints
- **Principles:** `docs/architecture/principles.md` — Renaissance architecture principles
- **Plugin Protocol:** `docs/architecture/plugin-protocol.md` — How plugins work
- **ML Tech Stack:** `docs/intelligence/ai-tech-stack.md` — ML/AI technology choices
- **ML Resources:** `docs/intelligence/ai-intelligence-resources.md` — Implementation examples

---

*Focus: Architecture and functionality, not implementation phases*
