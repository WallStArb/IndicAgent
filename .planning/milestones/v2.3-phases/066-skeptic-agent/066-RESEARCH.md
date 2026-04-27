# Phase 66: SkepticAgent - Research

**Researched:** 2026-04-24
**Domain:** LLM-powered swarm intelligence / Kafka consumer microservice / Statistical validation
**Confidence:** HIGH

## Summary

Phase 66 implements the first real swarm intelligence agent on the Phase 56 infrastructure. SkepticAgent acts as a "devil's advocate" that consumes I7 winner signals from `intelligence.i7.signals`, asks an LLM "what's wrong with this signal?", and outputs structured failure probability predictions. The agent runs as a standalone Kafka consumer service, writes all predictions to `alpha_multiplier_shadow` (already created in migration 058), and validates statistical significance (Pearson ρ ≥ 0.3, p < 0.05, N ≥ 30) before allowing swarm multiplier adjustments to affect live trading.

**Primary recommendation:** Implement SkepticAgent as a standalone systemd service that consumes `intelligence.i7.signals`, uses `LLMProviderChain` for structured JSON responses, records shadow predictions via `ShadowRecorder`, and includes validation scripts that correlate predictions with actual signal_ledger outcomes.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| LLM inference (structured JSON) | LLM Provider Chain (OpenRouter → Ollama) | SafeSwarmWrapper timeout | LLM calls are external dependencies with latency — wrap with timeout + exception isolation |
| Signal consumption & filtering | Kafka Consumer (intelligence.i7.signals) | SwarmContextCache seeding | Event-driven pattern — subscribe to winner signals, filter 5m+ TF only |
| Swarm context construction | SwarmContextCache (build from DB seed + bar updates) | SwarmContext (immutable model) | Context must be warm — DB seed on startup, kept warm by bar topic consumption |
| Prediction persistence | ShadowRecorder (batch asyncpg writes) | alpha_multiplier_shadow hypertable | Shadow pattern — all predictions recorded for training/validation, never overwrites confidence |
| Statistical validation | PostgreSQL (JOIN alpha_multiplier_shadow ↔ signal_ledger) | Python validation scripts (pearsonr per segment) | Renaissance standard — validate before promotion, segment by regime/TF/setup |
| Service orchestration | SkepticAgentComputeAgent (SwarmBaseAgent) | systemd unit (indicagent-skeptic-agent) | Standard agent lifecycle: _setup → _run → _teardown with graceful shutdown |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `LLMProviderChain` | Built (Phase 16) | Structured LLM calls with caching, rate limiting, budget, guardrails | Project's canonical LLM facade — OpenRouter primary → Ollama fallback |
| `SwarmBaseAgent` | Built (Phase 56) | Abstract base for swarm agents with timeout + shadow recording | All swarm agents extend this — provides compute(), warm_up(), health_check() |
| `ShadowRecorder` | Built (Phase 56) | Batch asyncpg writes to alpha_multiplier_shadow | Zero per-agent boilerplate — call `record()` for each prediction |
| `SwarmContext` / `SwarmContextCache` | Built (Phase 56) | Typed market context for agent computation | Immutable context model + cache with seed_from_db_row() warm-up |
| `SafeSwarmWrapper` | Built (Phase 56) | Timeout + exception isolation + neutral fallback | Defensive shell around any IAlphaContributor |
| `KafkaConsumerClient` | Built | Kafka consumption from intelligence.i7.signals | Project's standard Kafka consumer with manual offset commit |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `scipy.stats.pearsonr` | (via scipy in .venv) | Pearson correlation for validation | Standard statistical validation pattern — used in validate_alpha.py |
| `asyncpg` | (via requirements.txt) | PostgreSQL async writes | Project's DB client — batch inserts via ShadowRecorder |
| `structlog` | (via requirements.txt) | Structured logging | Project-wide logging standard |
| `prometheus_client` | (via requirements.txt) | Metrics (SWARM_AGENT_LATENCY, SWARM_AGENT_ERRORS) | Existing swarm metrics — reuse with agent_id label |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Standalone consumer service | Embed in SwarmOrchestrator | Violates SRP — SkepticAgent is a Path B contributor with independent failure domain |
| Direct LLM calls | Custom HTTP to OpenAI API | Loses provider chain + circuit breaker + caching built into LLMProviderChain |
| Write to signal_ledger directly | Separate shadow columns (planned) | signal_ledger is live production state — shadow predictions must not mix until validated |

**Installation:**
```bash
# All dependencies already installed
source .venv/bin/activate
pip install -r requirements.txt  # includes asyncpg, scipy, prometheus_client, structlog
```

**Version verification:** All stack components are project-built and verified via code inspection. No external package version checks needed.

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Intelligence Pipeline (I1-I7)                      │
│  IBKR TWS → intelligence_pipeline_agent → signal_ledger + intelligence_features  │
│                              ↓                                              │
│                       SignalWriterAgent                                     │
│                              ↓                                              │
│                  intelligence.i7.signals (Kafka)                             │
│                  [winner signals: symbol, tf, plugin, confidence]            │
└─────────────────────────────────────────────────────────────────────────────┘
                                       ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SkepticAgent Service                                 │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  Bar Loop (background)                                                 │ │
│  │    topic_market_bars + topic_market_bars_htf → SwarmContextCache.update()│ │
│  │    (keeps context warm for each symbol/TF combination)                 │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                   ↓                                         │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  Signal Loop (main)                                                   │ │
│  │    Subscribe: intelligence.i7.signals                                 │ │
│  │    Filter: tf in ['5m', '15m', '1h', '4h', '1d'] (skip 1m)           │ │
│  │    Parse: RankedSignal payload → signal_id, symbol, tf, winner_plugin  │ │
│  │    Build: SwarmContext via cache.build(symbol, tf, signal, signal_id)  │ │
│  │    Compute: LLMProviderChain.generate(prompt, system, max_tokens)      │ │
│  │    Parse JSON: {failure_probability, confidence, risk_factors, reasoning}│ │
│  │    Transfer: multiplier = (1.0 - failure_probability) * llm_confidence │ │
│  │    Record: ShadowRecorder.record(signal_id, agent_id, multiplier, ...) │ │
│  │    Publish: AgentResult → topic_swarm_results (Path B)                │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                   ↓                                         │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  Error Handling                                                        │ │
│  │    - LLM timeout/exception → SafeSwarmWrapper returns neutral (1.0)    │ │
│  │    - JSON parse error → log + DLQ + neutral fallback                   │ │
│  │    - Context cache miss → log warning + skip signal                    │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
                                       ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Shadow Prediction Storage                                 │
│  ShadowRecorder (batch, asyncpg) → alpha_multiplier_shadow                  │
│  Columns: ts, signal_id, agent_id, symbol, tf, hmm_regime, path,            │
│            predicted_multiplier, confidence, features (JSONB)               │
└─────────────────────────────────────────────────────────────────────────────┘
                                       ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Statistical Validation (Post-hoc)                          │
│  scripts/validate_skeptic.py:                                               │
│    JOIN alpha_multiplier_shadow ↔ signal_ledger ON signal_id                │
│    Compute per-segment Pearson(failure_probability, actual_outcome)         │
│    Segment dimensions: (regime_type, tf, setup_plugin)                      │
│    Gate: ρ ≥ 0.3 AND p < 0.05 AND N ≥ 30 → promote segment                │
│    Global gate: overall ρ ≥ 0.2                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure
```
src/intelligence/swarm/agents/
├── skeptic_agent.py              # SkepticAgentComputeAgent (SwarmBaseAgent)
├── skeptic_prompts.py            # Prompt registry with versioning
└── __init__.py

scripts/
├── validate_skeptic.py           # Pearson correlation per segment
└── compute_skeptic_baseline.py   # Naive baseline: historical failure rate

services/
├── skeptic_agent_service.py      # Service entry point
└── indicagent-skeptic-agent.service  # systemd unit

tests/unit/
├── test_skeptic_agent.py         # Unit tests (LLM mock, context build)
└── test_skeptic_validation.py    # Validation script tests
```

### Pattern 1: SwarmBaseAgent Subclass (SkepticAgent)

**What:** Extend `SwarmBaseAgent` to implement `_compute(SwarmContext) -> AgentResult`. The base class handles timeout, exception safety, OTel spans.

**When to use:** All swarm intelligence agents (Path A deterministic or Path B LLM).

**Example:**
```python
# Source: src/core/swarm/base_agent.py (verified)
from src.core.swarm.base_agent import SwarmBaseAgent
from src.intelligence.schemas import AgentResult
from src.intelligence.swarm.context import SwarmContext
from src.core.llm.chain import LLMProviderChain

class SkepticAgentComputeAgent(SwarmBaseAgent):
    agent_id = "skeptic_v1"
    path = "llm_swarm"
    shadow_only = True
    latency_budget_ms = 5000.0  # 5s LLM timeout

    def __init__(self, settings, llm_chain: LLMProviderChain):
        super().__init__(name="SkepticAgentComputeAgent")
        self.settings = settings
        self._llm = llm_chain

    async def _compute(self, context: SwarmContext) -> AgentResult:
        # 1. Build structured prompt from context
        prompt = _build_skeptic_prompt(context)

        # 2. Call LLM with JSON response requirement
        response = await self._llm.generate(
            prompt=prompt,
            system="You are a financial trading risk analyst. Always respond with valid JSON.",
            max_tokens=500,
            timeout=self.latency_budget_ms / 1000.0,
        )

        # 3. Parse JSON response
        if not response:
            return self._neutral("LLM returned empty response", latency_ms=0.0)

        parsed = _parse_skeptic_response(response)
        if not parsed:
            return self._neutral("JSON parse failed", latency_ms=0.0)

        # 4. Transfer function: failure_probability → multiplier
        multiplier = (1.0 - parsed["failure_probability"]) * parsed["confidence"]

        # 5. Return AgentResult (shadow_only=True by default from SwarmBaseAgent)
        return AgentResult(
            agent_id=self.agent_id,
            path=self.path,
            multiplier=max(0.0, min(2.0, multiplier)),  # clamp to [0, 2]
            confidence=parsed["confidence"],
            shadow_only=True,
            metadata={
                "failure_probability": parsed["failure_probability"],
                "risk_factors": parsed["risk_factors"],
                "reasoning": parsed["reasoning"],
                "prompt_version": "skeptic_v1",
            },
        )
```

### Pattern 2: Prompt Versioning Registry

**What:** Store prompt templates in a module-level registry with version IDs. Version tracked in metadata for A/B testing.

**When to use:** All LLM agents where prompt evolution needs tracking.

**Example:**
```python
# Source: Pattern from ai_narrative_agent.py (verified via codebase inspection)
PROMPT_REGISTRY = {
    "skeptic_v1": """You are a skeptical trading analyst reviewing a signal.

Signal details:
- Symbol: {symbol}
- Timeframe: {timeframe}
- Setup: {winner_plugin} ({direction} {confidence:.0%})
- Regime: hmm_regime={hmm_regime} (0=ranging, 1=trending_up, 2=trending_down)
- ATR: {atr:.2f}
- RSI: {rsi:.1f}
- ADX: {adx:.1f}
- Price: {price:.2f}
- Volume: {volume:.0f}

Cross-timeframe confluence:
- CTF trend alignment: {ctf_trend_alignment}
- CTF regime agreement: {ctf_regime_agreement}
- CTF FVG alignment: {ctf_fvg_alignment}
- CTF OB alignment: {ctf_ob_alignment}

Context classification:
- Trend regime: {trend_regime}
- Vol regime: {vol_regime}
- VWAP: {vwap:.2f}
- POC: {poc_price:.2f}
- POC rolling: {poc_price_rolling:.2f}

TASK: Identify what's WRONG with this signal. Respond with JSON ONLY:
{{
    "failure_probability": <float 0.0-1.0>,
    "confidence": <float 0.0-1.0>,
    "risk_factors": ["<factor1>", "<factor2>", ...],
    "reasoning": "<1-2 sentence explanation>"
}}

Rules:
- failure_probability=0.0 means "nothing wrong, this is a great signal"
- failure_probability=1.0 means "this will definitely fail"
- Be contrarian — look for hidden risks, regime mismatches, weak confluence
- confidence reflects how certain you are in your failure probability
""",
}
```

### Pattern 3: ShadowRecorder Batch Writes

**What:** Use `ShadowRecorder` to batch-write predictions to `alpha_multiplier_shadow`. Zero per-agent boilerplate.

**When to use:** All swarm agents recording shadow predictions.

**Example:**
```python
# Source: src/core/ml/shadow.py (verified)
from src.core.ml.shadow import ShadowRecorder
import asyncpg

# In agent _setup():
pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)
self._recorder = ShadowRecorder(pool, batch_size=100, flush_interval_s=2.0)

# In _compute() after building AgentResult:
await self._recorder.record(
    signal_id=context.signal_id,
    agent_id=self.agent_id,
    multiplier=result.multiplier,
    confidence=result.confidence,
    symbol=context.symbol,
    tf=context.timeframe,
    regime=context.hmm_regime,
    path=self.path,
    features=result.metadata,  # Stores prompt_version, risk_factors, etc.
)

# In _teardown():
await self._recorder.flush()  # Final flush before shutdown
```

### Anti-Patterns to Avoid
- **Don't write to signal_ledger directly:** signal_ledger is live production state. SkepticAgent predictions must flow through shadow validation first (Renaissance principle: "earn the right through proof").
- **Don't skip context cache warm-up:** SwarmContextCache must be seeded on startup via `seed_from_db_row()`. Without warm cache, `cache.build()` returns None for all signals.
- **Don't process 1m timeframe:** At ~500 signals/day across 55 symbols, 1m is too expensive. Filter to 5m+ (CONTEXT decision D-09).
- **Don't use raw LLM responses without JSON parsing:** Unstructured responses can't be validated or stored in features JSONB. Always require structured JSON output.
- **Don't set shadow_only=False:** Promotion to live is a manual process after statistical validation. Never auto-promote from shadow.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| LLM provider chaining + retry + circuit breaker | Custom HTTP calls to OpenAI/Ollama | `LLMProviderChain` (Phase 16) | Already has OpenRouter→Ollama fallback, semantic cache, rate limiter, token budget, guardrails |
| Timeout + exception isolation for agent compute | try/except with asyncio.wait_for | `SafeSwarmWrapper` (Phase 56) | Standard defensive shell for all swarm agents — returns neutral on failure |
| Batch DB writes with buffer management | Custom asyncpg batch inserts | `ShadowRecorder` (Phase 56) | Handles batching, flush interval, connection pooling, ON CONFLICT DO NOTHING |
| Kafka consumer loop + offset commit | Custom consumer implementation | Extend `SwarmBaseAgent._run()` or implement consume loop | BaseAgent provides lifecycle hooks, Prometheus metrics, graceful shutdown |
| Prometheus metrics for swarm agents | prometheus_client direct instantiation | `SwarmMetrics` (Phase 56) — SWARM_AGENT_LATENCY, SWARM_AGENT_ERRORS | Module-level singleton prevents duplicate registration across tests |
| Statistical correlation validation | Custom scipy.stats code | Pattern from `validate_alpha.py` (production/scripts/) | Project's validated Pearson r + p-value pattern for N ≥ 30 |

**Key insight:** Phase 56 built the complete swarm infrastructure (agents, safety, context, aggregator, metrics, shadow recording). SkepticAgent should use these building blocks, not reimplement them.

## Runtime State Inventory

> N/A — This is a greenfield phase (new service), not a rename/refactor/migration. No runtime state to inventory.

## Common Pitfalls

### Pitfall 1: Context Cache Cold Start
**What goes wrong:** SkepticAgent starts consuming signals immediately, but `SwarmContextCache` is empty. All `cache.build(symbol, tf, signal, signal_id)` calls return None → all signals skipped.

**Why it happens:** Cache is seeded from `intelligence_features` on startup, but seeding is async and may not complete before first signal arrives.

**How to avoid:** In `_setup()`, wait for `seed_from_db_row()` to complete before starting signal consumer. Use a simple seed (e.g., most recent bar per symbol/TF) — don't try to load full history.

**Warning signs:** Log messages `"swarm_context.no_cache"` or `"swarm_context.stale"` for every signal.

### Pitfall 2: LLM JSON Parse Failures
**What goes wrong:** LLM returns valid text but not valid JSON (e.g., includes "Here's the analysis:" prefix). `json.loads()` raises → agent crashes.

**Why it happens:** LLM sometimes chatty even with "JSON ONLY" instructions. Models have different adherence rates.

**How to avoid:** Wrap `json.loads()` in try/except, return neutral AgentResult with error on failure. Use guardrails or regex to extract JSON block if present. Log the raw response for debugging.

**Warning signs:** High `SWARM_AGENT_ERRORS` count with error_type="json_parse_error".

### Pitfall 3: Signal ID UUID Mismatch
**What goes wrong:** `alpha_multiplier_shadow.signal_id` (UUID) doesn't match `signal_ledger.signal_id` → JOIN returns empty rows in validation script.

**Why it happens:** `intelligence.i7.signals` topic has `signal_id` as string (from `RankedSignal.signal_id`). `alpha_multiplier_shadow` expects UUID. Must cast during insert.

**How to avoid:** In `ShadowRecorder.record()`, cast signal_id to `str(UUID)` or ensure payload has UUID type. Check migration 058 schema — signal_id is UUID NOT NULL.

**Warning signs:** Validation script returns N=0 for all segments despite predictions existing.

### Pitfall 4: 1m Timeframe CPU Exhaustion
**What goes wrong:** SkepticAgent processes 1m signals (~500/day × 55 symbols = 27,500 LLM calls/day). CPU/LLM costs explode.

**Why it happens:** Forgot to implement TF filter in consumer loop.

**How to avoid:** Filter early in `_handle_signal()`: `if tf not in ['5m', '15m', '1h', '4h', '1d']: return`. Log skipped signals for observability.

**Warning signs:** Ollama/OpenRouter rate limit errors, high `AGENT_INFERENCE_LATENCY`, wallet drain.

### Pitfall 5: Neutral Fallback Not Returning AgentResult
**What goes wrong:** Exception path returns `None` instead of `AgentResult`. SwarmAggregator crashes when trying to aggregate.

**Why it happens:** `_neutral()` helper not called, or returned bare dict instead of AgentResult.

**How to avoid:** Always use `self._neutral(error, latency_ms)` from `SwarmBaseAgent`. Returns valid AgentResult with multiplier=1.0, confidence=0.0, shadow_only=True.

**Warning signs:** SwarmOrchestrator logs "TypeError: 'NoneType' object is not iterable" during aggregation.

## Code Examples

Verified patterns from official sources:

### LLM Call with Structured JSON Response
```python
# Source: src/core/llm/chain.py (Context7/verified)
from src.core.llm.chain import LLMProviderChain
from src.config.settings import Settings

settings = Settings()
llm = LLMProviderChain(
    call_type="skeptic",
    settings=settings,
    cache_ttl=300.0,  # 5 minutes
)

response = await llm.generate(
    prompt="What's wrong with this signal? Respond with JSON: {failure_probability, confidence, ...}",
    system="You are a risk analyst. Always respond with valid JSON.",
    max_tokens=500,
    timeout=5.0,
)
# response is str or None
if response:
    import json
    data = json.loads(response)
    failure_prob = data["failure_probability"]
```

### SwarmContext Construction from Cache
```python
# Source: src/intelligence/swarm/context.py (verified)
from src.intelligence.swarm.context import SwarmContextCache

cache = SwarmContextCache()

# On startup, seed from DB (in _setup)
import asyncpg
pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)
async with pool.acquire() as conn:
    rows = await conn.fetch("""
        SELECT symbol, tf, ts, bar, i1, i4, i6
        FROM intelligence_features
        WHERE (symbol, tf) IN (
            SELECT symbol, tf FROM recent_signals
        )
        ORDER BY ts DESC
        LIMIT 1000
    """)
    for row in rows:
        cache.seed_from_db_row(dict(row))

# In signal handler
ctx = cache.build(
    symbol=symbol,
    tf=tf,
    signal=signal,  # RankedSignal
    signal_id=signal_id,  # UUID
)
if ctx is None:
    logger.warning("context_cache_miss", symbol=symbol, tf=tf)
    return  # skip signal
```

### Statistical Validation (Pearson Correlation)
```python
# Source: production/scripts/validate_alpha.py (verified via codebase)
import pandas as pd
from scipy.stats import pearsonr

# JOIN predictions with outcomes
query = """
SELECT
    s.predicted_multiplier,
    s.confidence,
    s.features->>'failure_probability' as failure_prob,
    l.outcome,
    l.pnl_r
FROM alpha_multiplier_shadow s
JOIN signal_ledger l ON s.signal_id = l.signal_id
WHERE s.agent_id = 'skeptic_v1'
  AND l.exit_at IS NOT NULL
  AND s.symbol = $1
  AND s.tf = $2
  AND s.hmm_regime = $3
"""
df = pd.read_sql(query, conn, params=[symbol, tf, regime])

# Binary outcome: win = 1, loss/stop = 0
df['win'] = (df['pnl_r'] > 0).astype(int)

# Pearson correlation: failure_probability vs win
if len(df) >= 30:
    rho, pvalue = pearsonr(df['failure_prob'], df['win'])
    print(f"ρ={rho:.3f}, p={pvalue:.4f}, N={len(df)}")
    # Gate: ρ ≥ 0.3 AND p < 0.05 AND N ≥ 30
    if rho >= 0.3 and pvalue < 0.05:
        print("SEGMENT PROMOTED")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual LLM calls with urllib | LLMProviderChain with provider fallback + circuit breaker | Phase 16 (2026-03-06) | Automatic failover to Ollama if OpenRouter rate limits, semantic cache reduces costs |
| Single agent per script | SwarmBaseAgent with ShadowRecorder automatic shadow writes | Phase 56 (2026-04-11) | Zero boilerplate for new agents, all predictions tracked for training |
| Ad-hoc validation scripts | Renaissance-standard Pearson correlation with N ≥ 30 gates | Phase 16+ | No promotion without statistical proof, segment-aware validation |

**Deprecated/outdated:**
- Direct OpenAI API calls: Replaced by LLMProviderChain (use the chain, not raw HTTP)
- Manual Kafka consumer loops without BaseAgent: Use SwarmBaseAgent or BaseWriterAgent for consistent lifecycle
- Writing predictions directly to production tables: Use alpha_multiplier_shadow table (Renaissance shadow-first pattern)

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | OpenRouter API key is configured in .env (may be empty string) | LLM Provider Chain | If key missing, chain falls back to Ollama. If Ollama also unavailable, agent returns neutral for all signals — no predictions recorded. Verify: check `.env` for `OPENROUTER_API_KEY`. |
| A2 | Ollama model gemma4:e4b is available at localhost:11434 | LLM Provider Chain | Environment check showed Ollama not available. Agent will skip to next provider. If both fail, no predictions. Risk: LLM dependency is single point of failure. Mitigation: SafeSwarmWrapper returns neutral on timeout. |
| A3 | intelligence.i7.signals topic exists and carries RankedSignal payloads | Kafka Infrastructure | Topic created in Phase 49. Verify: `docker exec redpanda rpk topic list | grep intelligence.i7.signals`. If missing, SignalWriterAgent not publishing. |
| A4 | SwarmOrchestratorComputeAgent bar loop is running and updating SwarmContextCache | Orchestration | SkepticAgent depends on context cache being warm. If bar loop not running, all signals skipped. Verify: check `systemctl status indicagent-swarm-orchestrator`. |
| A5 | signal_ledger has sufficient resolved signals (N ≥ 30) for validation | Validation Framework | If phase is brand-new, validation script will return N=0. Risk: can't validate until signals resolve. Mitigation: validation script runs periodically, not as gate. |
| A6 | Transfer function `multiplier = (1.0 - failure_probability) * llm_confidence` is appropriate | Transfer Function | This is a linear mapping. Actual relationship may be non-linear. Risk: suboptimal multiplier mapping. Mitigation: versioned prompts enable A/B testing of different functions. |

## Open Questions

1. **Prompt wording and system message**
   - What we know: Context decision D-01 says "send all available features", D-02 specifies JSON schema. Claude's discretion on exact wording.
   - What's unclear: Optimal prompt engineering for failure probability prediction. Should we use few-shot examples? Chain-of-thought?
   - Recommendation: Start with simple prompt (see Pattern 2), iterate based on LLM response quality. Log raw responses to `features.reasoning` for analysis.

2. **Exact systemd unit configuration**
   - What we know: Template from `indicagent-ai-narrative.service`, needs `PYTHONUNBUFFERED=1`, `After=network-online.target`.
   - What's unclear: Whether to add `After=indicagent-swarm-orchestrator.service` dependency (context cache warm-up).
   - Recommendation: Add dependency — SkepticAgent depends on warm context. Start ordering: SwarmOrchestrator → SkepticAgent.

3. **Naive baseline computation details**
   - What we know: Context decision D-12 says "per-segment historical failure rate from signal_ledger".
   - What's unclear: Exact SQL query, whether to weight by confidence, how to handle regime transitions.
   - Recommendation: Simple baseline first: `COUNT(win=1) / COUNT(*)` per (regime, tf, setup) segment. Write `scripts/compute_skeptic_baseline.py` to pre-compute table.

4. **LLM cost per signal**
   - What we know: 5m+ TF filter gives ~50-100 signals/day. OpenRouter free models → Ollama fallback.
   - What's unclear: Actual token count per prompt (SwarmContext dump is large).
   - Recommendation: Monitor `llm_calls` hypertable for `call_type='skeptic'` in first week. Budget: `TokenBudget(daily_limit=1_000_000, cost_per_1k=0.001)` in LLMProviderChain.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL (TimescaleDB) | alpha_multiplier_shadow table | ✓ | Up 25 hours | — |
| Redpanda (Kafka) | intelligence.i7.signals topic | ✓ | Up 25 hours | — |
| Ollama (LLM) | Primary LLM provider (local) | ✗ | Not running | OpenRouter (if API key configured) |
| OpenRouter API | Secondary LLM provider | ? | Key in .env (may be empty) | If both fail → neutral predictions only |
| scipy.stats | Pearson correlation in validation | ✓ | (in .venv) | — |
| asyncpg | DB writes via ShadowRecorder | ✓ | (in .venv) | — |

**Missing dependencies with no fallback:**
- None — TimescaleDB and Redpanda are running. If Ollama is down, OpenRouter may be available. If both LLM providers fail, agent returns neutral (multiplier=1.0) for all signals — production-safe but no predictions.

**Missing dependencies with fallback:**
- Ollama: Falls back to OpenRouter if `OPENROUTER_API_KEY` is non-empty string. Verify: `grep OPENROUTER_API_KEY /home/bg/dev/indicagent/.env`.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (project standard) |
| Config file | pytest.ini (root) |
| Quick run command | `.venv/bin/pytest tests/unit/test_skeptic_agent.py -v -x` |
| Full suite command | `.venv/bin/pytest tests/unit/ -v -k "skeptic or swarm" -x` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| D-01 | SwarmContext dump includes all features | unit | `pytest tests/unit/test_skeptic_agent.py::test_context_includes_all_features -x` | ❌ Wave 0 |
| D-02 | LLM returns structured JSON (failure_probability, confidence, risk_factors, reasoning) | unit | `pytest tests/unit/test_skeptic_agent.py::test_llm_json_parse -x` | ❌ Wave 0 |
| D-03 | Prompt version tracked in AgentResult.metadata | unit | `pytest tests/unit/test_skeptic_agent.py::test_prompt_version_in_metadata -x` | ❌ Wave 0 |
| D-04 | Transfer function: (1.0 - failure_prob) * llm_confidence | unit | `pytest tests/unit/test_skeptic_agent.py::test_transfer_function -x` | ❌ Wave 0 |
| D-07 | Consumes from intelligence.i7.signals, filters 5m+ TF only | integration | `pytest tests/unit/test_skeptic_agent.py::test_consume_filter_timeframe -x` | ❌ Wave 0 |
| D-10 | Production impact from day one (shadow_only=True, predictions tracked) | integration | `pytest tests/unit/test_skeptic_agent.py::test_shadow_only_predictions -x` | ❌ Wave 0 |
| D-11 | SafeSwarmWrapper timeout + exception isolation | unit | `pytest tests/unit/test_swarm_safety.py -v -k "test_wrapper_returns_neutral_on_timeout" -x` | ✅ exists |
| D-12 | Naive baseline: per-segment historical failure rate | unit | `pytest tests/unit/test_skeptic_validation.py::test_naive_baseline_computation -x` | ❌ Wave 0 |
| D-13 | Pearson correlation per segment (ρ, p, N) | unit | `pytest tests/unit/test_skeptic_validation.py::test_pearson_per_segment -x` | ❌ Wave 0 |
| D-14 | Graduation gate: ρ ≥ 0.3 AND p < 0.05 AND N ≥ 30 | unit | `pytest tests/unit/test_skeptic_validation.py::test_graduation_gate -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/unit/test_skeptic_agent.py -v -x`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -v -k "skeptic or swarm" -x`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/test_skeptic_agent.py` — SkepticAgent unit tests (LLM mock, context build, transfer function)
- [ ] `tests/unit/test_skeptic_validation.py` — Validation script tests (Pearson, baseline, graduation gate)
- [ ] `scripts/validate_skeptic.py` — Statistical validation script (JOIN alpha_multiplier_shadow ↔ signal_ledger)
- [ ] `scripts/compute_skeptic_baseline.py` — Naive baseline computation script
- [ ] `src/intelligence/swarm/agents/skeptic_agent.py` — SkepticAgentComputeAgent implementation
- [ ] `src/intelligence/swarm/agents/skeptic_prompts.py` — Prompt registry with versioning
- [ ] `services/skeptic_agent_service.py` — Service entry point
- [ ] `services/indicagent-skeptic-agent.service` — systemd unit file

## Security Domain

> Security enforcement is enabled (absent from config = default true). ASVS verification required.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | N/A — service-to-service communication, no user auth |
| V3 Session Management | no | N/A — stateless consumer service |
| V4 Access Control | no | N/A — no user resources |
| V5 Input Validation | yes | **Pydantic schemas** — `AgentResult`, `SwarmContext`, `IntelligenceEvent` validate all inputs |
| V6 Cryptography | no | N/A — no encryption at rest (DB handled by TimescaleDB) |
| V7 Error Handling | yes | **SafeSwarmWrapper** — exceptions return neutral, no crash, DLQ for malformed payloads |
| V8 Data Protection | yes | **Shadow predictions separate** — never overwrite signal_ledger confidence directly |

### Known Threat Patterns for {LLM + Kafka + PostgreSQL}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| LLM prompt injection | Tampering | System message enforces JSON-only response, guardrails validate schema before parsing |
| Kafka message flood (DoS) | Denial of Service | Consumer group manual offset commit, bounded buffer (BaseWriterAgent MAX_BUFFER_SIZE=10k) |
| Malformed Kafka payload (JSON parse error) | Tampering | DLQ routing via `_maybe_route_to_dlq()`, parse failures counted in `SWARM_AGENT_ERRORS` |
| SQL injection in validation script | Tampering | Use parameterized queries (asyncpg `%s` placeholders, no f-string interpolation) |
| LLM provider API key leakage | Information Disclosure | Store in `.env` (not in code), never log API keys, use `OPENROUTER_API_KEY` via Settings |

**Security-specific checklist for this phase:**
- [ ] Verify `.env` is not committed to git (check `.gitignore`)
- [ ] Ensure systemd unit file does not embed secrets (use `EnvironmentFile` or pass via `Environment=` with values from Settings)
- [ ] Validate all LLM responses via Pydantic before using (e.g., `SkepticResponse.parse_obj(json_data)`)
- [ ] Use parameterized queries in validation scripts (no string concatenation for SQL)

## Sources

### Primary (HIGH confidence)
- `src/core/agents/alpha_contributor.py` - IAlphaContributor protocol definition (code verified)
- `src/intelligence/swarm/context.py` - SwarmContext + SwarmContextCache (code verified)
- `src/intelligence/swarm/safety.py` - SafeSwarmWrapper timeout + exception isolation (code verified)
- `src/intelligence/swarm/aggregator.py` - SwarmAggregator Path A/B combination (code verified)
- `src/intelligence/swarm/metrics.py` - Prometheus metrics for swarm operations (code verified)
- `src/core/ml/shadow.py` - ShadowRecorder batch writer (code verified)
- `src/core/llm/chain.py` - LLMProviderChain implementation (code verified)
- `src/core/llm/providers.py` - OpenRouterProvider + OllamaProvider (code verified)
- `src/core/swarm/base_agent.py` - SwarmBaseAgent abstract class (code verified)
- `src/core/agent/base_writer.py` - BaseWriterAgent consume loop pattern (code verified)
- `src/intelligence/schemas.py` - AgentResult, AlphaMultiplier, RankedSignal schemas (code verified)
- `production/migrations/058_alpha_multiplier_shadow.sql` - alpha_multiplier_shadow table schema (code verified)
- `services/swarm_orchestrator_agent.py` - SwarmOrchestratorComputeAgent reference pattern (code verified)
- `services/indicagent-ai-narrative.service` - systemd unit template (code verified)

### Secondary (MEDIUM confidence)
- `production/scripts/validate_alpha.py` - Pearson correlation + p-value validation pattern (code verified)
- `tests/unit/test_swarm_protocol.py` - SwarmContext and AgentResult test patterns (code verified)
- `tests/unit/test_swarm_safety.py` - SafeSwarmWrapper test patterns (code verified)
- `.planning/phases/066-skeptic-agent/066-CONTEXT.md` - User decisions and locked choices (context document)
- `CLAUDE.md` - Project naming conventions, service patterns, Renaissance principles (project documentation)

### Tertiary (LOW confidence)
- None — all claims verified via code inspection or official project documentation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All components are project-built and verified via code inspection (Phase 56 infrastructure, Phase 16 LLM chain)
- Architecture: HIGH - SwarmOrchestratorComputeAgent pattern verified, BaseWriterAgent consume loop pattern verified
- Pitfalls: HIGH - Based on verified code patterns (SwarmContext cache cold start verified in Phase 67 fix, LLM JSON parsing verified in ai_narrative_agent)

**Research date:** 2026-04-24
**Valid until:** 2026-05-24 (30 days — stable infrastructure, low risk of breaking changes)
