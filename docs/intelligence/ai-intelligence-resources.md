# AI Intelligence Resources & Implementation Guide

**Version:** 3.0.0
**Last Updated:** 2026-04-07
**Status:** Operational — I1-I8 pipeline complete (121 plugins + 2 aggregation). LLM chain: OpenRouter (primary) → Ollama (offline fallback).

## Purpose

Reference guide for AI/LLM integration in IndicAgent. Covers LLM provider chain usage, stream key conventions, and current implementation patterns.

---

## LLM Provider Chain

The `ai_narrative_service` (I8) uses `LLMChain` from `src/intelligence/llm_providers.py` — providers are tried in order and the first successful response is returned immediately.

### Usage Example

```python
from src.intelligence.llm_providers import LLMChain, OpenRouterProvider, OllamaProvider
from src.config.settings import get_settings

settings = get_settings()

chain = LLMChain([
    OpenRouterProvider(
        model="meta-llama/llama-3.3-70b-instruct:free",
        api_key=settings.openrouter_api_key
    ),
    OllamaProvider(
        model="gemma4:e4b",
        base_url=settings.ollama_base_url
    ),
])

text = await chain.generate(
    prompt="Analyze this market pattern...",
    system="You are a market intelligence analyst.",
    max_tokens=500,
    timeout=30.0
)
```

### Provider Configuration

**OpenRouter (Tier 1 - Primary):**
- Endpoint: https://openrouter.ai/api/v1
- Env vars: `OPENROUTER_API_KEY`, `OPENROUTER_TIMEOUT_SEC`
- Default model: `meta-llama/llama-3.3-70b-instruct:free`
- Free tier available, access to 100+ models

**Ollama (Tier 2 - Offline):**
- Endpoint: http://localhost:11434
- Env vars: `OLLAMA_BASE_URL`, `OLLAMA_TIMEOUT_SEC`
- Default model: `gemma4:e4b`
- Runs entirely on-device, always available

---

## Stream Key Conventions

All Redpanda topic names are built via `src/core/stream_keys.py` with the `INDICAGENT_ENV` prefix.

```python
from src.core.stream_keys import (
    topic_market_bars,           # market.bars — Canonical 1m bars
    topic_intelligence_journal,  # intelligence.journal — Full I1-I7 features
    topic_intelligence_i7_signals,# intelligence.i7.signals — Winner signal
    topic_narratives,            # narratives:*:* — I8 LLM narratives
    topic_llm_calls,             # llm.calls — LLM audit log
)
from src.config.settings import get_settings

settings = get_settings()

# Usage
journal_topic = topic_intelligence_journal(settings.env_name)
# Returns: "market.bars" if INDICAGENT_ENV unset, "dev.market.bars" if set to "dev"
```

**Topic Naming:** `<env>.<domain>[.<sublayer>]` — dots only, never colons.

---

## Current Intelligence Pipeline

### Architecture

```
IntelligencePipelineComputeAgent (I1-I7 unified in-process)
  ↓
intelligence.journal (Kafka) — Full I1-I7 feature vector
  ↓
FeatureWriterAgent → intelligence_features (TimescaleDB)
  ↓
ai_narrative_service (I8) → narratives:*:* (Kafka)
  ↓
LLMWriterAgent → llm_calls (TimescaleDB)
```

### Service Details

| Service | Unit | Port | Purpose |
|---------|------|------|---------|
| Intelligence Pipeline | `indicagent-intelligence-pipeline` | :9125 | I1-I7 unified pipeline |
| AI Narrative | `indicagent-ai-narrative` | :9113 | I8 LLM narrative generation |
| LLM Writer | `indicagent-llm-writer` | :9117 | LLM audit log persistence |

---

## I8 AI Narrative Layer

### Functionality

- **Input:** `IntelligenceEvent` from `intelligence.journal` (full I1-I7 feature vector)
- **Processing:** LLM generates human-readable market commentary per symbol/timeframe
- **Output:** `NarrativeEvent` published to `narratives:SYMBOL:TF` topics
- **Persistence:** Full LLM audit log to `llm_calls` hypertable (includes prompt, response, latency, model)

### LLM Chain Behavior

Providers tried in sequence:
1. **OpenRouter** — Cloud inference, 100+ models available
2. **Ollama** — Local fallback, always available

First successful response returned immediately. If OpenRouter fails (timeout, API error, rate limit), automatically falls back to Ollama without service interruption.

### Topics

I8 publishes to symbol-specific topics:
```python
narratives:ES:1m   # S&P 500, 1-minute bars
narratives:NQ:15m  # Nasdaq 100, 15-minute bars
narratives:CL:1h   # Crude Oil, 1-hour bars
```

Topic format: `narratives:<symbol>:<timeframe>` where symbol is the base contract code.

---

## Schema Reference

### IntelligenceEvent (I1-I7)

Canonical schema defined in `src/intelligence/schemas.py`:

```python
class IntelligenceEvent(BaseModel):
    ts: datetime
    symbol: str
    tf: str
    bar: OHLCVBar
    i1: I1Indicators      # Technical indicators (RSI, MACD, ATR, etc.)
    i2: I2Events          # Volume events (OFI, CVD, etc.)
    i3: I3Structure      # Market structure (FVG, OB, SMC, etc.)
    i4: I4Context        # Context scoring (regime, volatility, etc.)
    i5: I5Patterns       # Pattern confluence
    smc: SMCContext      # Smart money concepts
    i6: I6Confluence     # CIS scoring, calibration
    bar_close_ts: Optional[datetime]
    i1_computed_at: Optional[datetime]
    computed_at: datetime
```

**Persistence:** `intelligence_features` hypertable with tiered JSONB columns (`i1`, `i2`, `i3`, `i4`, `i5`, `smc`, `i6`).

### NarrativeEvent (I8)

```python
class NarrativeEvent(BaseModel):
    ts: datetime
    symbol: str
    tf: str
    narrative: str              # LLM-generated text
    llm_provider: str           # "openrouter" or "ollama"
    llm_model: str              # Model used
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    source: str = "ai_narrative_service"
```

**Persistence:** `llm_calls` hypertable (full audit log for analysis and cost tracking).

---

## LLM Research-Only Principle

Per the Renaissance validation framework, LLMs are **research-only** in production:

**Beta Pipeline (Offline):**
- LLMs analyze historical patterns
- Discover heuristics and generate insights
- Compile findings to deterministic Python code

**Alpha Pipeline (Production):**
- No LLM calls in the hot path
- Real-time signal enrichment uses only deterministic feature extractors
- I8 AI Narrative is the exception (generates explanations, never affects position sizing directly)

**Rationale:** LLM outputs are probabilistic and non-deterministic. All alpha must pass statistical validation gates (p < 0.05, ρ > 0.4) before affecting capital.

---

## Performance Considerations

### Current Latency

- **I1-I7 Pipeline:** ~220ms per bar (single symbol, all timeframes)
  - I1 (parallel): 30ms
  - I2-I6 (sequential): 160ms (73% of total - bottleneck)
  - I7 (parallel): 20ms

- **I8 Narrative:** ~2-5 seconds per narrative (LLM inference)
  - OpenRouter: 1-3s (network latency + inference)
  - Ollama: 3-5s (local inference on CPU)

### Throughput

- **Current:** ~4.5 bars/sec (limited by sequential I2-I6 execution)
- **Target:** 530 bars/sec (118x gap)
- **Optimization:** Batch processing expected 10-50x improvement (see `docs/architecture/PIPELINE_OPTIMIZATION.md`)

### GIL Constraint

Python's Global Interpreter Lock prevents threading from achieving true parallelism:
- I1 and I7 are parallelized via `asyncio.gather` + ThreadPoolExecutor
- Only one thread executes Python bytecode at a time
- CPU-bound work (plugin compute) cannot utilize multiple cores
- Individual plugin speedup (vectorization) doesn't improve overall throughput

---

## External References

### LLM Infrastructure
- **OpenRouter:** https://openrouter.ai/docs — Multi-model LLM API aggregation
- **Ollama:** https://ollama.com/docs — Local LLM inference engine
- **LangChain:** https://python.langchain.com — LLM orchestration framework (reference for patterns)

### Research Concepts
- **Mixture of Agents:** https://arxiv.org/abs/2406.04692 — Multi-agent synthesis patterns
- **Renaissance Validation:** `docs/ideas/renaissance-alpha-pipeline.md` — Shadow-first statistical gates
- **ML Agent Architecture:** `docs/ideas/ml-agent-architecture.md` — Learning machine design

### Market Intelligence
- **Volume Profile:** Institutional participation and value areas
- **Order Flow Analysis:** Large player positioning and liquidity sweeps
- **Market Microstructure:** Liquidity and market maker behavior patterns
- **Smart Money Concepts:** Fair value gaps, order blocks, liquidity pools

---

## Related Documentation

- **AI Architecture:** `docs/intelligence/ai-intelligence-architecture.md` — Full pipeline architecture
- **Tech Stack:** `docs/intelligence/ai-tech-stack.md` — ML/AI technology choices
- **Optimization:** `docs/architecture/PIPELINE_OPTIMIZATION.md` — Performance strategy
- **Current State:** `docs/architecture/CURRENT_STATE.md` — Active services and metrics
- **Plugin System:** `src/intelligence/CLAUDE.md` — Plugin protocol and tier details

---

*Focus: Current implementation and usage patterns, not speculative features*
