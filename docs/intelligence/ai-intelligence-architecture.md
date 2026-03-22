# AI Intelligence Architecture

**Version:** 3.1.0
**Last Updated:** 2026-03-22
**Status:** Operational — I1–I8 pipeline complete (98 plugins + 2 aggregation). LLM stack: OpenRouter (primary) → Ollama local (offline fallback). MLAgent learning machine in design (v1.9+). 

## Executive Summary

Comprehensive technical architecture for AI intelligence systems within IndicAgent. Provides sophisticated, modular foundation for market intelligence extraction that integrates seamlessly with existing infrastructure. The I8 AI Narrative layer uses a **3-tier LLM inference chain** — highest-quality cloud inference first, broad-model cloud fallback second, and always-available local inference as the last resort.

**Core Mission:** Transform raw market data through multi-layer AI analysis, pattern recognition, and synthesis. I1-I8 are operational (98 plugins).

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
```

## Architecture Overview

The intelligence pipeline is a set of systemd services communicating over Redpanda topics.

```
IBKR TWS → tws_daemon ──► market.bars (Redpanda)
                              │
                    feature_pipeline_service (I1→I6)
                              │
                         intelligence (Redpanda)
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

All topic names are built via `src/core/stream_keys.py`.

```python
from src.core.stream_keys import (
    topic_market_bars,       # market.bars — OHLCV bars from TWS daemon
    topic_intelligence,      # intelligence — I1–I6 IntelligenceEvent per bar
    topic_signals_aggregated,# signals.aggregated — selected signal per bar
    topic_narratives,        # narratives — I8 LLM narrative per bar
    topic_llm_calls,         # llm.calls — full LLM audit log
    topic_llm_outcomes,      # llm.outcomes — signal lifecycle exits
)
```

## Services Reference

| Service | Unit | Metrics |
|---------|------|---------|
| TWS Daemon | `indicagent-tws` | — |
| Feature Pipeline | `indicagent-feature-pipeline` | :9125 |
| Signal Generator | `indicagent-signal-generator` | :9112 |
| Signal Lifecycle | `indicagent-signal-lifecycle` | :9115 |
| AI Narrative | `indicagent-ai-narrative` | :9113 |
| Feature Writer | `indicagent-feature-writer` | :9116 |
| LLM Writer | `indicagent-llm-writer` | :9117 |
| API | `indicagent-api` | :8000 |
