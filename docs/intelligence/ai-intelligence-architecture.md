<!-- generated-by: gsd-doc-writer -->
# AI Intelligence Architecture

**Version:** 3.4.0
**Last Updated:** 2026-05-27
**Status:** Operational — I1-I8 pipeline complete (132 plugins + 2 aggregation). Unified IntelligencePipelineComputeAgent with parallelized I1/I7 tiers. LLM stack: Ollama local (default gemma4:e4b, configurable via OLLAMA_MODEL env var).

## Executive Summary

IndicAgent's intelligence pipeline transforms raw market data through seven analytical tiers (I1-I7), followed by AI-powered narrative generation (I8). The pipeline uses a **unified in-process architecture** — I1-I7 execute in a single agent with parallelized tiers where Python's GIL permits. I8 provides human-readable market commentary via a local Ollama inference call.

**Core Architecture:**
- **Unified Pipeline:** Single `IntelligencePipelineComputeAgent` runs I1-I7 in-process
- **Parallelized Tiers:** I1 (28 plugins) and I7 (36 plugins) execute concurrently via `asyncio.gather`
- **Sequential Bottleneck:** I2-I6 tiers execute sequentially (current optimization target)
- **Provider Abstraction:** Multi-provider support via `ProviderMergerAgent` failover
- **DB-Ignorant Compute:** All intelligence agents publish to Kafka; WriterAgents handle persistence

**Boundary rule:** the real-time intelligence pipeline is the deterministic market-feature pipeline. AI sits outside that hot path as an adjacent layer:
- **I8 narratives** translate pipeline output into natural language
- **Swarm agents** evaluate signal quality asynchronously
- **ML discovery / training** mine historical data and update models or weights offline

That separation keeps live signal generation deterministic, replayable, and low-latency while still allowing AI to learn from the data the pipeline produces.

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
│  Bar → [I1 parallel] → I2 → I3 → I4 → I5 → SMC → I6 → [I7 parallel] │
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
- **I1 (28 plugins)** — Technical indicators (RSI, MACD, ATR, ADX, BB, OFI, CVD, volume_zscore, etc.)
- **I7 (36 plugins)** — Trading signals with confidence scores

**Sequential (current bottleneck):**
- **I2 (10 plugins)** — Composite events (crossovers, exhaustion, acceleration)
- **I3 (8 plugins)** — Market structure (swing, S/R, market profile, session levels)
- **I4 (12 plugins)** — Context scoring, regime detection (GARCH, Kalman, VIXRegime, etc.)
- **I5 (16 plugins)** — Pattern detection (divergence, squeeze, chart patterns)
- **SMC (16 plugins)** — Smart Money Concepts (BOS/CHoCH, FVG, OB, HMM, liquidity, AMD cycle, etc.)
- **I6 (6 plugins)** — CrossTimeframeConfluence → CIS scoring, isotonic calibration

**Why:** Python's GIL prevents ThreadPoolExecutor from achieving true parallelism. Only one thread executes Python bytecode at a time. CPU-bound work (plugin compute) cannot utilize multiple cores regardless of worker count.

**Latency Breakdown:**
- I1 (parallel): 30ms
- I2-I6 (sequential): 160ms (73% of total)
- I7 (parallel): 20ms

**See:** `docs/architecture/pipeline-optimization.md` for optimization strategy (batch processing).

---

## I8 AI Narrative Layer

### LLM Inference

The `NarrativeComputeAgent` (I8) uses `LLMProviderChain` from `src/core/llm/chain.py`. The narrative service runs as `indicagent-narrative-compute`.

```
Primary   — Ollama (local)
             Runs entirely on-device — always available.
             Endpoint: http://localhost:11434
             Env: OLLAMA_BASE_URL, OLLAMA_MODEL (default: gemma4:e4b)
             Context window: 16384 tokens (OLLAMA_NUM_CTX)
             Timeout: 60s
```

The default model is `gemma4:e4b`. Override by setting `OLLAMA_MODEL` in `.env`. OpenRouter, DeepSeek, and OllamaCloud providers were removed from the narrative service; Ollama is the single provider.

### LLMs Research-Only Principle

Per the Renaissance validation framework, LLMs are **research-only** in our architecture:

- **Beta Pipeline (Offline):** LLMs analyze historical patterns, discover heuristics, generate insights → compiled to deterministic code
- **Alpha Pipeline (Production):** No LLM calls in the hot path. Real-time signal enrichment uses only deterministic Python feature extractors

The I8 AI Narrative layer is the exception (generates human-readable explanations), but its outputs never directly affect position sizing without passing through validation gates first.

The practical rule is:

- **Inside the intelligence pipeline:** deterministic feature extraction, regime classification, pattern detection, and signal generation
- **Outside the intelligence pipeline:** LLM narration, discovery, training, swarm evaluation, and any adaptive learning loop that depends on historical outcomes

AI can consume the pipeline's outputs and write back learned artifacts, but it should not sit on the critical path that turns bars into signals.

**See:** `docs/ideas/renaissance-alpha-pipeline.md` for full validation framework design.

---

## Intelligence Swarm (Async, Out-of-Band)

The swarm runs alongside the deterministic I1-I7 pipeline without ever blocking it. When an I7 signal fires, `AlphaSwarmComputeAgent` fans out to specialist agents that reason about the signal context and produce confidence multipliers. Per-agent predictions are recorded to `signal_lineage`; any `signal_ledger` swarm fields are writer-owned projections.

```
I7 signal → AlphaSwarmComputeAgent
                ├── SkepticAgentComputeAgent        (120s budget)
                ├── CorrelationAgentComputeAgent    (120s budget)
                ├── RegimeCoherenceAgentComputeAgent (120s budget)
                └── CounterfactualAgentComputeAgent (120s budget)
                          ↓
                    LineageRecorder → topic_signal_lineage
                          ↓
                    LineageWriterAgent → signal_lineage
                          ↓
                    writer-owned projection → signal_ledger swarm columns
```

Every agent extends `BaseMultiplierAgent` and receives an `AIContext` built from requested tiers. `BaseAIAgent.compute()` enforces timeout and exception isolation; a failing agent returns a neutral `AgentOutput` and does not break dispatch.

No swarm agent affects production signal confidence until it graduates through shadow governance. All agents start `shadow_only=True`, and all agents continue writing lineage whether shadow or live. Shadow/live controls production influence, not data capture.

**Shadow governance:** Components are auto-enrolled at startup via `shadow_registry_ensure()`. Promotion requires `n >= 100` resolved signals AND `bootstrap_ci_lower(pnl_r) > 0.0`. Demotion occurs when EV[R] < -0.05 for 3 consecutive evaluation cycles.

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
    topic_signal_lineage,         # signal_lineage — Agent prediction lineage
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
| Narrative Compute | `indicagent-narrative-compute` | :9113 | I8 LLM analysis → `narratives:*:*` |
| LLM Writer | `indicagent-llm-writer` | :9117 | `llm.calls` → `llm_calls` (DB) + outcome back-fill |
| Alpha Swarm | `indicagent-alpha-swarm` | — | I7 signals → alpha agent lineage |
| Lineage Writer | `indicagent-lineage-writer` | — | `signal_lineage` → `signal_lineage` (DB) |

---

## Database Schema

**Hypertables (TimescaleDB):**
- `market_data_ohlcv` — Raw OHLCV ground truth (keep forever)
- `intelligence_features` — Full I1-I7 feature vectors per bar (ML training dataset, keep forever)
- `signal_ledger` — ALL I7 signals + lifecycle outcomes (keep forever). Key columns: `entry_zone_low`, `entry_zone_high` (zone fields), `expires_at` (TTL column, bar-time wall-clock). Time column: `timestamp`.
- `signal_lineage` — Signal-affecting transforms and agent predictions (keep forever)
- `llm_calls` — LLM audit log + outcomes (keep forever). Composite PK: `(call_id, called_at)`.

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
| **[6] Shadow gate** | `n >= 100` AND `bootstrap_ci_lower(pnl_r) > 0.0` required | Prevents unproven features from reaching production |

**Key invariant:** `active` signal is always derived from `all_ranked`, never from the raw `signals` list — otherwise `perf_multiplier` silently has no effect on winner selection.

---

## Plugin System

132 plugins across tiers I1-I7. See `src/intelligence/CLAUDE.md` for tier details, plugin protocol, and LLM provider chain.

**Tier lists:** `TIER_I1`…`TIER_I7` in `src/intelligence/register_plugins.py` — single source of truth.

**Plugin counts (verified from register_plugins.py):**
- I1: 28 plugins (technical indicators + OFI/CVD microstructure + volume_zscore)
- I2: 10 plugins (composite events)
- I3: 8 plugins (market structure)
- I4: 12 plugins (context/regime)
- I5: 16 plugins (patterns)
- SMC: 16 plugins (Smart Money Concepts, including 4 HMM timeframe instances)
- I6: 6 plugins (CrossTimeframeConfluence variants)
- I7: 36 plugins (trading signals)
- **Total: 132 plugins** + 2 aggregation (CISScorer, SignalAggregator)

**Signal schema version:** Single canonical `SIGNAL_SCHEMA_VERSION = "v1"` in `src/intelligence/trading/signal_schema.py`. All producers and consumers import from there — no hardcoded version strings.

**Key constraint:** Plugins must never know about other plugins directly. Cross-plugin communication goes through tier output schemas only.

---

## Signal Lifecycle

Signal lifecycle is managed by `lifecycle_tracker.py` (pure compute, no DB) with persistence via `SignalLedgerRepository`.

**`signal_ledger` key fields:**
- `entry_zone_low` / `entry_zone_high` — entry zone bounds (from TradeFrame zone fields)
- `expires_at` — TTL deadline as a wall-clock timestamp (bar-time evaluation, Phase 107.5)
- `exit_at` — when signal exited (not `exit_ts`)
- `activated_at` — when signal became active
- `outcome` — 8-class taxonomy (never_activated, stopped_at_entry/in, target_1/1_2/full, ttl_expired_ahead/behind)

**Replay architecture (post-Phase 107.5):** `signal_replay_auditor_agent` evaluates signal outcomes directly from `signal_ledger` using `expires_at` for TTL checks. No LATERAL JOIN to `intelligence_features` required for replay.

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
