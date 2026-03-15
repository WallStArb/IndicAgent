# AI Intelligence Architecture

**Version:** 3.1.0
**Last Updated:** 2026-03-15
**Status:** Operational — I1–I8 pipeline complete (98 plugins + 2 aggregation). LLM stack: OpenRouter (primary) → Ollama local (offline fallback). MLAgent learning machine in design (v1.9+). See `CLAUDE.md` for full current state.

## Executive Summary

Comprehensive technical architecture for AI intelligence systems within IndicAgent. Provides sophisticated, modular foundation for market intelligence extraction that integrates seamlessly with existing infrastructure. The I8 AI Narrative layer uses a **3-tier LLM inference chain** — highest-quality cloud inference first, broad-model cloud fallback second, and always-available local inference as the last resort.

**Core Mission:** Transform raw market data into actionable intelligence through multi-layer AI analysis, pattern recognition, and synthesis. I1-I8 are operational (98 plugins). See `CLAUDE.md` for current state.

## 2-Tier LLM Inference Chain (I8)

The `ai_narrative_service` (I8) uses `LLMChain` from `src/intelligence/llm_providers.py` — providers are tried in order and the first successful response is returned immediately.

```
Tier 1 (Primary)   — OpenRouter
                     Access to 100+ models from major providers (Llama, Mistral, Gemini,
                     Claude, etc.) through a single API. Free-tier models available.
                     Endpoint: https://openrouter.ai/api/v1
                     Env: OPENROUTER_API_KEY, OPENROUTER_TIMEOUT_SEC
                     Per-signal default: meta-llama/llama-3.3-70b-instruct:free
                     Group synthesis default: stepfun/step-3.5-flash:free

Tier 2 (Offline)   — Ollama (local)
                     Runs entirely on-device — always available even with no internet
                     or API access. Adds latency but guarantees narrative generation.
                     Endpoint: http://localhost:11434
                     Env: OLLAMA_BASE_URL, OLLAMA_TIMEOUT_SEC
                     Per-signal: qwen3.5:9b  |  Group synthesis: phi4-mini:3.8b
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
# chain.last_provider_id — which provider succeeded (e.g. "openrouter:llama-3.3-70b")
```

### Adding a New Provider

Implement the `LLMProvider` protocol — one method, one attribute:

```python
class MyProvider:
    provider_id: str  # e.g. "myprovider:model-name"

    async def generate(self, prompt: str, system: str,
                       max_tokens: int, timeout: float) -> str | None:
        ...  # return text or None on failure
```

Add to `Settings` with `*_api_key`, `*_base_url`, `*_model`, `*_timeout_sec` fields, then insert into the chain at the desired priority position.

## Scope and Non-Goals

### Scope
- AI intelligence architecture for I1–I8 tiers (plugin-native, systemd-managed services)
- LLM inference chain and provider failover (I8)
- Redpanda topic distribution and TimescaleDB persistence
- MLAgent learning machine design (v1.9+ — not yet built)

### Non-Goals
- Trading execution systems (orders, broker integration)
- UI implementation details (dashboards, component code)
- Strategy design/backtesting specifics

## Intelligence System Design Principles

- **Intelligence-first**: Plugin protocol (`compute_next` / `compute_full`) separates extraction logic from service orchestration. Each plugin owns one capability; the service owns the loop.
- **Data contracts over APIs**: All inter-service communication is typed Redpanda messages (`IntelligenceEvent` from `src/intelligence/schemas.py`). No direct service-to-service calls.
- **Degrade gracefully**: LLM chain tries providers in order, returns `None` if all fail — the pipeline continues without narrative rather than blocking.
- **Earn the right through proof**: Signal quality gates (`p < 0.05`, `sample_size >= 30`) are encoded in `setup_performance` writes and the CIS `perf_multiplier`. No model touches live selection without evidence.

## Architecture Overview

The intelligence pipeline is a set of systemd services communicating over Redpanda topics. Each service subscribes to upstream topics, runs its plugin tier, and publishes results downstream.

```
IBKR TWS → tws_daemon ──► market.bars (Redpanda)
                              │
                    indicator_service (I1)
                              │
                         indicators (Redpanda)
                              │
               market_analysis_service (I2→I6)
                              │
                         intelligence (Redpanda)
                         intelligence.i7
                              │
              signal_generator_service (I7)
                              │
               ┌──────────────┴───────────────┐
          signals.aggregated            signal_ledger (TimescaleDB)
               │
      feature_writer_service → intelligence_features (TimescaleDB)
               │
      ai_narrative_service (I8) → narratives (Redpanda) → llm_calls (TimescaleDB)
               │
           API (SSE) → Dashboard
```

## Redpanda Topic Reference

All topic names are built via `src/core/stream_keys.py`. Never construct topic strings manually.

```python
from src.core.stream_keys import (
    topic_market_bars,       # market.bars — OHLCV bars from TWS daemon
    topic_indicators,        # indicators — I1 output per bar
    topic_intelligence,      # intelligence — I2–I6 IntelligenceEvent per bar
    topic_intelligence_i7,   # intelligence.i7 — I7 signal scorecard (all_ranked)
    topic_intelligence_i8,   # intelligence.i8 — I8 narrative metadata
    topic_signals,           # signals — individual I7 signals pre-aggregation
    topic_signals_aggregated,# signals.aggregated — selected signal per bar
    topic_narratives,        # narratives — I8 LLM narrative per bar
    topic_llm_calls,         # llm.calls — full LLM audit log
    topic_llm_outcomes,      # llm.outcomes — signal lifecycle exits for back-fill
    message_key,             # partition key: "SYMBOL:TF" or "SYMBOL"
)
```

Topics use dot-separated names (`development.indicators`) — colons are invalid Kafka topic names.

## TimescaleDB Tables (Intelligence Layer)

```
intelligence_features  — full feature vectors per bar incl. I1–I8 JSONB (ML training dataset)
signal_ledger          — I7 signals + lifecycle outcomes; JOIN via (symbol, feature_ts, feature_tf)
llm_calls              — full LLM audit log per call; outcome back-filled by llm_writer_service
llm_model_scores       — per-model win rate / avg pnl_r / p-value; refreshed every 15 min
setup_performance      — per-setup rolling 30d stats (win_rate, avg_pnl_r, sharpe); rows written
                         only when sample_size >= 30 (FEED-02 gate)
drift_state            — per-feature KS/CUSUM drift scores; written by market_analysis_service
```

## Quality Gates (Live System)

| Gate | Mechanism | Where |
|------|-----------|-------|
| **CIS score** | Weighted sum across I1–I6 signals → 0–1 | CIS aggregator plugin (I7) |
| **Performance weight** | `perf_multiplier` from `setup_performance` — only rows with N≥30 | Signal aggregator |
| **Alpha decay** | Freshness-weighted confidence — older signals score lower | I6 confluence plugin |
| **Drift detection** | KS + CUSUM per feature; drift scores in `drift_state` table | Market analysis service |
| **Shadow mode gate** | p < 0.05 with sufficient N required before ML models affect selection | MLAgent (v1.9+) |
```

## Current Status (as of v1.6)

**All I1–I8 phases complete.** 98 plugins + 2 aggregation components operational. MLAgent learning machine in design (v1.9+).

| Layer | Status |
|-------|--------|
| I1 Technical Indicators (25) | ✅ Running — incremental `compute_next()` |
| I2 Composite Events (11) | ✅ Running — MACD/RSI/Stoch/ADX/Volume events + MomentumAcceleration/DerivativeOscillator/ExhaustionScore/AccelerationRegime |
| I3 Market Structure (8) | ✅ Running — swing, S/R, trend, VWAP, Fibonacci, MarketProfile, SessionLevels, SwingMomentum |
| I4 Context / Regime (7) | ✅ Running — GARCH, Kalman, HMM, BOCPD, MTFVolatility |
| I5 Patterns (14) | ✅ Running — chart patterns, divergence, squeeze, VolumeProfile, KeyLevelReaction |
| I6 SMC + Confluence (14) | ✅ Running — BOS/CHoCH, FVG, order blocks, ICT killzones, AMD, breakers, cross-TF confluence |
| I7 Trading Setups (17+2) | ✅ Running — 17 setup plugins + CIS aggregator + TradeFramer |
| I8 AI Narrative (1) | ✅ Running — OpenRouter (primary) → Ollama qwen3.5:9b (offline fallback) |
| **ML Layer (MLAgent)** | 🔬 Design complete — v1.9+ build target |

**See** `.planning/ROADMAP.md` for the next milestone backlog.

## ML Intelligence Layer (MLAgent — v1.9+)

The I1–I8 pipeline produces labeled training data: every signal outcome (8-class taxonomy: never_activated, stopped_at_entry, stopped_in_trade, target_1, target_1_2, target_full, ttl_expired_ahead, ttl_expired_behind) is recorded in `signal_ledger` alongside the full `intelligence_features` vector captured at signal time. MLAgent is the system that closes the loop from that labeled data back to improved signal selection.

### Five-Agent Architecture

A deterministic **LangGraph Supervisor** coordinates domain-specific agents:

```
┌──────────────────────────────────────────────────────────┐
│  ML Orchestrator (LangGraph Supervisor — deterministic)  │
│  Reads: drift scores, model status, shadow mode results  │
│  Routes to: domain agents · Decides: retrain/promote/HITL│
└──────────────────────────────────────────────────────────┘
     │           │           │           │           │
     ▼           ▼           ▼           ▼           ▼
┌─────────┐ ┌─────────┐ ┌─────────┐ ┌────────┐ ┌─────────┐
│  Data   │ │Discovery│ │Training │ │Monitor │ │Narrative│
│ Quality │ │  (LLM)  │ │  (det.) │ │  (det.)│ │  (LLM)  │
└─────────┘ └─────────┘ └─────────┘ └────────┘ └─────────┘
```

Only Discovery and Narrative agents use LLMs. All production decisions are deterministic.

### Key Properties

- **Segmented ensemble:** LightGBM sub-models per `HMM regime × setup type × timeframe` — a model that works in the conditions it was designed for beats a global model every time
- **Shadow mode gate:** `p < 0.05` with sufficient N required before any model affects signal selection. Borderline p-values trigger HITL via LangGraph `interrupt()`.
- **IC-driven feature discovery:** tsfresh extracts 700+ features automatically; alphalens computes IC/ICIR per feature per regime — lets data reveal predictors rather than hand-engineering them
- **Drift detection:** Evidently (KS/PSI/Wasserstein) + CUSUM per feature; auto-retrain on drift, circuit breaker on degradation
- **SHAP explainability:** Every scored signal carries top-5 SHAP contributors — why this model scored this signal

### Agent Tech Stack

| Package | Purpose |
|---------|---------|
| `langgraph` | Agent orchestration — Supervisor state machine, HITL `interrupt()`, typed `StateGraph` for all agent handoffs |
| `langchain` | Tool definitions, LLM wrappers, provider abstractions |
| `langfuse` (self-hosted) | Agent observability — all agent steps, LLM calls, tool invocations traced; OTEL → Grafana |
| `guardrails-ai` | LLM output validation — Discovery + Narrative outputs validated against Pydantic schemas |
| `mlflow` (self-hosted) | Model registry, experiment tracking, artifact versioning |
| `alphalens-reloaded` | IC, ICIR, decay, turnover per feature per regime |
| `tsfresh` | 700+ auto-generated time series features |
| `evidently` | Drift detection + ML monitoring reports |
| `polars` | Batch feature matrix construction (10-100× faster than pandas) |
| `lightgbm` | Tabular ensemble model |
| `shap` | TreeSHAP explainability |
| `optuna` | Bayesian hyperparameter search |
| `river` | Online/incremental learning (Phase 3) |

**Full design:** `docs/ideas/ml-learning-machine.md`

---

## Related Documentation

- [Comprehensive Intelligence Architecture](../architecture/comprehensive-intelligence-architecture.md)
- [Layered Architecture](../architecture/layered-architecture.md)
- [Intelligence Tiers](../concepts/intelligence-tiers.md)
- [Plugin Registry & DAG Execution](../architecture/plugin-registry-and-dag-execution.md)
- [Stream Schemas](../architecture/stream-schemas.md)
- [Market Intelligence Strategy](market-intelligence-strategy.md)
- [AI Intelligence Resources](ai-intelligence-resources.md)

This architecture provides the foundation for sophisticated market intelligence extraction while maintaining focus on analysis and insights rather than execution systems.