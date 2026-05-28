<!-- generated-by: gsd-doc-writer -->
# AI Intelligence Resources & Implementation Guide

**Version:** 3.2.0
**Last Updated:** 2026-05-27
**Status:** Operational — I1-I8 pipeline complete (132 plugins + 2 aggregation). LLM stack: Ollama local (default gemma4:e4b, configurable via OLLAMA_MODEL env var).

## Purpose

Reference guide for AI/LLM integration in IndicAgent. Covers LLM provider chain usage, stream key conventions, and current implementation patterns.

---

## LLM Provider Chain

The `NarrativeComputeAgent` (I8) uses `LLMProviderChain` from `src/core/llm/chain.py`. The narrative service (`indicagent-narrative-compute`) runs a single Ollama provider. OpenRouter, DeepSeek, and OllamaCloud providers were removed from the narrative path.

### Usage Example

```python
from src.core.ai.base_agent import BaseAIAgent
from src.config.settings import get_settings

settings = get_settings()

# AI agents use self._llm_generate() — never self._llm.generate() directly.
# _llm_generate() auto-injects audit_context (call_id, symbol, signal_id,
# regime, agent_id, prompt_version) into the llm.calls Kafka stream.

class MyAgent(BaseAIAgent):
    agent_id = "my_agent_v1"
    group = "alpha"
    tiers_needed = frozenset()
    latency_budget_ms = 120_000
    shadow_only = True
    prompt_version = "my_agent_v1"

    async def _compute(self, context):
        result = await self._llm_generate(context, prompt="...", system="...")
        ...
```

### Provider Configuration

**Ollama (primary — local):**
- Endpoint: `http://localhost:11434` (env: `OLLAMA_BASE_URL`)
- Default model: `gemma4:e4b` (env: `OLLAMA_MODEL` overrides)
- Context window: 16384 tokens (env: `OLLAMA_NUM_CTX`)
- Runs in Docker (`ollama/ollama:rocm` container)
- Timeout: 60s (env: `LLM_TIMEOUT_SEC`)
- Runs entirely on-device — always available

**Important:** For swarm agents (alpha_swarm, narrative_compute), Ollama is the sole provider. Hold persistent connections to it — kill those services before swapping models or benchmarking.

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
NarrativeComputeAgent (I8) → narratives:*:* (Kafka)
  ↓
LLMWriterAgent → llm_calls (TimescaleDB)
```

### Service Details

| Service | Unit | Port | Purpose |
|---------|------|------|---------|
| Intelligence Pipeline | `indicagent-intelligence-pipeline` | :9125 | I1-I7 unified pipeline |
| Narrative Compute | `indicagent-narrative-compute` | :9113 | I8 LLM narrative generation |
| LLM Writer | `indicagent-llm-writer` | :9117 | LLM audit log persistence |

---

## I8 AI Narrative Layer

### Functionality

- **Input:** `IntelligenceEvent` from `intelligence.journal` (full I1-I7 feature vector)
- **Processing:** LLM generates human-readable market commentary per symbol/timeframe
- **Output:** narrative published to `narratives:SYMBOL:TF` topics
- **Persistence:** Full LLM audit log to `llm_calls` hypertable (includes prompt, response, latency, model)
- **Timeframes:** `["1m", "5m", "15m", "1h"]`
- **Consumer group:** `"ai_narrative"`, starts at `"$"` (skips backlog)

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
    i2: I2Events          # Composite events (crossovers, exhaustion, etc.)
    i3: I3Structure       # Market structure (swing, S/R, trend, session)
    i4: I4Context         # Context scoring (regime, volatility, etc.)
    i5: I5Patterns        # Pattern confluence
    smc: SMCContext       # Smart money concepts
    i6: I6Confluence      # CIS scoring, calibration
    bar_close_ts: Optional[datetime]
    i1_computed_at: Optional[datetime]
    computed_at: datetime
```

**Persistence:** `intelligence_features` hypertable with tiered JSONB columns (`i1`, `i2`, `i3`, `i4`, `i5`, `smc`, `i6`). Column name is `ts` (not `feature_ts`).

### Signal Schema

Signal schema version is `SIGNAL_SCHEMA_VERSION = "v1"` — single canonical constant in `src/intelligence/trading/signal_schema.py`. All producers and consumers import from there. Never hardcode version strings.

**Key signal fields:**
- `entry_zone_low` / `entry_zone_high` — entry zone bounds
- `expires_at` — TTL deadline (bar-time wall-clock timestamp, Phase 107.5)
- `signal_type` — values: `at_close`, `at_pullback`, `at_limit`, `at_reclaim`, `zone_proximal`

---

## LLM Audit Trail

Every LLM call flows through the audit pipeline:

| Table | Purpose |
|-------|---------|
| `llm_calls` | Full audit per call: prompt, response, provider, latency, tokens, agent_id, prompt_version. Composite PK: `(call_id, called_at)` |
| `llm_model_scores` | Per-model win rate, calibration, significance; refreshed every 15 min |
| `signal_lineage` | Agent ancestry per signal (swarm predictions) |
| `shadow_registry` | Shadow state for all I7 plugins + swarm agents; statistical promotion/demotion gates |

**Adaptive routing:** When a model reaches `is_significant=True` (p<0.05, n>=30), it moves to position 0 in the provider chain for that `agent_id + regime` combination.

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

**Rationale:** LLM outputs are probabilistic and non-deterministic. All alpha must pass statistical validation gates (n >= 100, bootstrap CI lower > 0) before affecting capital.

---

## Performance Considerations

### Current Latency

- **I1-I7 Pipeline:** ~220ms per bar (single symbol, all timeframes)
  - I1 (parallel): 30ms
  - I2-I6 (sequential): 160ms (73% of total - bottleneck)
  - I7 (parallel): 20ms

- **I8 Narrative:** varies by Ollama model and hardware
  - Local Ollama gemma4:e4b on AMD ROCm: p50 latency approximately 47-52s for swarm agents

### Throughput

- **Current:** ~4.5 bars/sec (limited by sequential I2-I6 execution)
- **Target:** 530 bars/sec (118x gap)
- **Optimization:** Batch processing expected 10-50x improvement (see `docs/architecture/pipeline-optimization.md`)

### GIL Constraint

Python's Global Interpreter Lock prevents threading from achieving true parallelism:
- I1 and I7 are parallelized via `asyncio.gather` + ThreadPoolExecutor
- Only one thread executes Python bytecode at a time
- CPU-bound work (plugin compute) cannot utilize multiple cores
- Individual plugin speedup (vectorization) doesn't improve overall throughput

---

## External References

### LLM Infrastructure
- **Ollama:** https://ollama.com/docs — Local LLM inference engine (primary)

### Research Concepts
- **Mixture of Agents:** https://arxiv.org/abs/2406.04692 — Multi-agent synthesis patterns
- **Renaissance Validation:** `docs/ideas/renaissance-alpha-pipeline.md` — Shadow-first statistical gates
- **ML Agent Architecture:** `docs/ideas/ai-02-ml-agent-architecture.md` — Learning machine design

### Market Intelligence
- **Volume Profile:** Institutional participation and value areas
- **Order Flow Analysis:** Large player positioning and liquidity sweeps
- **Market Microstructure:** Liquidity and market maker behavior patterns
- **Smart Money Concepts:** Fair value gaps, order blocks, liquidity pools

---

## Related Documentation

- **AI Architecture:** `docs/intelligence/ai-intelligence-architecture.md` — Full pipeline architecture
- **Tech Stack:** `docs/intelligence/ai-tech-stack.md` — ML/AI technology choices
- **Optimization:** `docs/architecture/pipeline-optimization.md` — Performance strategy
- **Current State:** `docs/architecture/current-state.md` — Active services and metrics
- **Plugin System:** `src/intelligence/CLAUDE.md` — Plugin protocol and tier details

---

*Focus: Current implementation and usage patterns, not speculative features*
