# Intelligence AI — Swarm Agents & LLM Layer

**Version:** 1.0.0
**Last Updated:** 2026-05-28
**Status:** current
**Milestone:** v2.8 — AI Platform + Evolvable Agents

---

## Purpose

HOW to implement I8 AI agents: agent protocol, LLM provider chain, swarm agents, shadow governance, lineage recording, and step-by-step guidance for adding a new agent.

---

## Renaissance Principle for AI

> "LLMs are research-only in production. Deterministic math generates signals; AI evaluates, explains, and learns."

**Why:** LLM outputs are probabilistic and non-deterministic. All alpha must pass statistical validation gates (n >= 100, bootstrap CI lower > 0) before affecting capital.

**What this means:**
- **Hot path (I1-I7)** is deterministic — no LLM calls
- **I8 AI Narrative** generates explanations — never affects position sizing directly
- **Swarm agents** run async, out-of-band — evaluate signals after publication
- **All agents start shadow-only** — must graduate via statistical proof

---

## I8 AI Narrative Layer

### Functionality

- **Input:** `IntelligenceEvent` from `intelligence.journal` (full I1-I7 feature vector)
- **Processing:** LLM generates human-readable market commentary per symbol/timeframe
- **Output:** narrative published to `narratives:SYMBOL:TF` topics
- **Persistence:** Full LLM audit log to `llm_calls` hypertable
- **Timeframes:** `["1m", "5m", "15m", "1h"]`
- **Consumer group:** `"ai_narrative"`, starts at `"$"` (skips backlog)

### LLM Provider (Ollama Local)

**Primary provider:** Ollama (local, self-hosted)

| Setting | Default | Override |
|----------|---------|----------|
| Endpoint | `http://localhost:11434` | `OLLAMA_BASE_URL` |
| Model | `gemma4:e4b` | `OLLAMA_MODEL` |
| Context window | 16384 tokens | `OLLAMA_NUM_CTX` |
| Timeout | 60s | `LLM_TIMEOUT_SEC` |

**Runs in Docker:** `ollama/ollama:rocm` container (AMD ROCm GPU)

**Important:** Live services `alpha_swarm` and `narrative_compute` hold persistent Ollama connections. Kill them before swapping models or benchmarking.

### Narrative Service

- **Service:** `indicagent-narrative-compute`
- **Agent:** `NarrativeSwarm` (`src/intelligence/ai/narrative/narrative_agent.py`)
- **Health:** `:9113` metrics endpoint
- **Latency:** Varies by model and hardware

---

## Swarm Agents (Alpha Group)

### Architecture Overview

The alpha swarm is an async intelligence overlay for I7 signals. It runs after signal publication, never blocks the hot I1-I7 pipeline.

```
intelligence.i7.signals
  -> AlphaSwarm
       -> BaseGroupCoordinator subclasses (parallel dispatch)
       -> LineageRecorder
       -> topic_signal_lineage()
  -> LineageWriter
       -> signal_lineage
  -> writer-owned projection
       -> signal_ledger swarm columns
```

### Active Agents

| Agent | Class | Purpose | Budget | Status |
|-------|-------|---------|--------|--------|
| Skeptic | `SkepticEvaluator` | Estimates holistic failure probability | 120s | Shadow |
| Correlation | `CorrelationEvaluator` | Judges cross-asset coherence | 120s | Shadow |
| Regime Coherence | `RegimeCoherenceEvaluator` | Checks setup vs current regime | 120s | Shadow |
| Counterfactual | `CounterfactualEvaluator` | Tests what must be true for signal to work | 120s | Shadow |
| ML Scorer v1 | `MLScorerV1Agent` | Local ML model signal score | 50ms | Shadow |
| Narrative | `NarrativeSwarm` | Market narrative prose (on-demand HTTP) | — | Live |

**LLM latency:** With gemma4:e4b on AMD ROCm, p50 ~47-52s — within 120s budget.

**ML Scorer:** 50ms budget (local model, no LLM calls).

---

## Agent Protocol

### BaseAIWorker Contract

All AI agents extend `BaseAIWorker` from `src/core/ai/base_agent.py`:

**Five mandatory class attributes:**

| Attribute | Type | Purpose |
|-----------|------|---------|
| `agent_id` | `str` | Stable `<concept>_v<N>` identifier; MUST match `shadow_registry.component_name` |
| `group` | `str` | `"alpha"` or `"narrative"` |
| `tiers_needed` | `frozenset[Tier]` | Pipeline tiers this agent reads; drives `AIContextCache.build()` |
| `latency_budget_ms` | `float` | Hard timeout cap on `_compute` |
| `shadow_only` | `bool` | Starts `True`; refreshed from `shadow_registry` at runtime |
| `prompt_version` | `str` | Set from agent's `ACTIVE_VERSION` constant; auto-injected into `llm_calls` |

### _compute() Contract

```python
async def _compute(self, context: AIContext) -> AgentOutput:
    # 1. Build prompt (use ACTIVE_VERSION from prompts module)
    prompt = build_<name>_prompt(context)

    # 2. Call LLM via self._llm_generate() — NEVER self._llm.generate() directly
    response = await self._llm_generate(context, prompt=prompt, system=SYSTEM_MSG)

    # 3. Handle empty response
    if not response:
        return self._neutral(error="LLM returned empty", latency_ms=0.0)

    # 4. Parse JSON
    parsed = _parse_response(response)
    if parsed is None:
        return self._neutral(error="JSON parse failed", latency_ms=0.0)

    # 5. Return AgentOutput — never raise
    return AgentOutput(
        agent_id=self.agent_id,
        group=self.group,
        signal_id=context.signal_id,
        symbol=context.symbol,
        timeframe=context.timeframe,
        ts=context.ts,
        output_type="multiplier",  # or "text" for narrative
        payload={
            ...parsed fields...,
            "prompt_version": ACTIVE_VERSION,  # REQUIRED for LineageRecorder
        },
        shadow_only=self.shadow_only,
    )
```

**Critical:** Always use `self._llm_generate()` — it auto-injects audit context (call_id, symbol, signal_id, regime, agent_id, prompt_version) into the `llm.calls` Kafka stream.

### AgentOutput Shape

**Alpha agents** (`output_type="multiplier"`):
```python
{
    "multiplier": float,      # 0.0-2.0 confidence adjustment
    "confidence": float,      # Agent's confidence in its prediction
    "reasoning": str,         # Human-readable explanation
    "prompt_version": str,     # For lineage attribution
}
```

**Narrative agent** (`output_type="text"`):
```python
{
    "text": str,              # Generated narrative
    "prompt_version": str,
}
```

---

## LLM Provider Chain

### Architecture

**Unified pipeline:** cache → rate limit → budget → provider → guardrails → metrics → cache put → audit

**File:** `src/core/llm/chain.py`

### Components

| Component | Purpose | Status |
|-----------|---------|--------|
| `LLMProviderChain` | High-level facade: cache → rate limit → budget → chain → guardrails | Active |
| `SemanticCache` | LRU + TTL (5 min) cache; key = SHA-256(system + prompt[:200] + model); 500 entries max | Active |
| `RateLimiter` | Per-provider RPM/TPM rate limiting | Active |
| `TokenBudget` | Daily token budget tracking | Active |
| `GuardrailsValidator` | Pydantic-based schema validation of LLM responses (custom) | Active |
| `CircuitBreaker` | Per-provider with configurable thresholds and recovery | Active |

### Audit Pipeline

Every LLM call flows through the audit pipeline:

```
Agent._llm_generate()
  -> llm.calls (Kafka)
  -> indicagent-llm-writer
  -> llm_calls (TimescaleDB)
```

**llm_calls columns:** call_id, prompt, response, provider, latency, tokens, agent_id, prompt_version, symbol, signal_id, regime, called_at.

**Composite PK:** `(call_id, called_at)` — use both for ON CONFLICT.

### gemma4:e4b JSON Enforcement

Outputs prose preamble without explicit system message. Use:

```
System: "OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE."
User: "...Begin your response with { and end with }."
```

`_strip_thinking_tags` only removes `<think` tags — does not catch prose.

---

## Shadow Governance

### Auto-Enrollment

All I7 plugins and swarm agents are auto-enrolled at startup via `shadow_registry_ensure()` / `enroll_all_plugins()`:

```python
await shadow_registry_ensure(
    component_name="<agent_id>",
    component_type="swarm_agent",
    tier="alpha",
    initial_state="shadow",
)
```

**Uses ON CONFLICT DO NOTHING** — custom gate parameters tuned directly in DB are never overwritten by restarts.

### Graduation Criteria

**Promotion:**
- `n >= 100` resolved signals
- `bootstrap_ci_lower(pnl_r) > 0.0` (at 95% confidence)

**Demotion:**
- EV[R] < -0.05 for 3 consecutive evaluation cycles

### Shadow-First Lifecycle

```
1. SHADOW MODE — Observe live data, produce analysis, zero production impact
2. FITNESS EVALUATION — Measure out-of-sample across multiple market regimes
3. STATISTICAL GATE — n >= 100 resolved signals + bootstrap CI lower > 0.0 at 95%
4. PROMOTION — Multiplier feeds into signal scoring
5. PRODUCTION — Continuous monitoring continues
6. DEGRADATION — Auto-disable if EV[R] < -0.05 for 3 consecutive cycles
```

**Current policy:** Discount-only — agents may reduce confidence but should not boost above 1.0 until sufficient outcome data proves positive edge.

---

## eAI Substrate (v2.8)

The infrastructure for evolvable AI agents is operational. eAI agents (v2.8 roadmap) build on this existing substrate — no new infrastructure needed.

| Component | Status | Purpose |
|-----------|--------|---------|
| `shadow_registry` table | Live | Auto-enrolls all I7 plugins and swarm agents at startup |
| Signal ledger outcome tracking | Live | Fitness evaluation data accumulates per signal |
| `LineageRecorder` | Live | Full ancestry tracking per agent call |
| Skeptic agent | Live | Adversarial coevolution — challenges other swarm agents |
| `BaseAIWorker` framework | Live | Agent parameter variations implement genome mutations |
| `llm_calls` audit trail | Live | Every LLM call persisted with prompt version; outcome back-filled |
| `bootstrap_ci_lower()` | Live | Statistical gate in `src/core/stats_utils.py` |
| `ShadowTransitionEvent` | Live | Promotion/demotion published to `topic_shadow_transitions` |

**Design principle:** eAI agents are `BaseAIWorker` subclasses with an additional `genome` parameter dict. Reproductive operators (mutation, crossover, selection) are applied to the genome dict between evaluation cycles. The shadow governance lifecycle handles statistical gating before any mutant agent affects production scoring.

See `docs/research/ai-03-evolvable-ai-agents.md` for the full research vision and `docs/research/eai-phase-recommendations.md` for the v2.8 implementation roadmap.

---

## Lineage Recording

### Single Audit Path

After Phase 78, every alpha-group agent records ONE event per signal via `LineageRecorder.record()`:

```python
LineageRecorder.record(
    event_type="agent_prediction",
    source=agent_id,
    multiplier=multiplier,
    metadata={
        "segment_key": "2.15m",
        "confidence": confidence,
        "prompt_version": ACTIVE_VERSION,
        "group": "alpha",
        "payload": {...},
    }
)
```

**Publishes to:** `topic_signal_lineage()` → `LineageWriter` → `signal_lineage` hypertable.

**This is the ONLY swarm write path.** Do not write to `alpha_multiplier_shadow` or `signal_transform_log` (deprecated targets).

### signal_lineage Schema

**Key columns:** call_id, called_at, agent_id, signal_id, symbol, timeframe, event_type, source, payload (JSONB).

**Event types:** `agent_prediction`, `lifecycle_transition`, `transform_application`.

---

## Group Services

### AlphaSwarm

- **Service:** `indicagent-alpha-swarm`
- **File:** `services/alpha_swarm_agent.py`
- **Purpose:** Dispatches swarm agents in parallel, aggregates outputs, publishes lineage
- **Topics:** Consumes `intelligence.i7.signals`, publishes `swarm.alpha` and `signal_lineage`

### NarrativeSwarm

- **Service:** `indicagent-narrative-compute`
- **File:** `services/narrative_group_compute_agent.py`
- **Purpose:** Generates on-demand narratives per signal
- **Topics:** Consumes `intelligence.i7.signals`, publishes `narratives:*:*`

### BaseGroupCoordinator

Shared dispatcher for all group services:
- Kafka consumer/producer
- DB pool via `get_connection()`
- `AIContextCache` (5-min TTL, in-memory)
- `LLMProviderChain`
- Agent dispatch
- Graduation loop

**Construction rule:** Agents needing `self._llm_chain` must be constructed in `_setup()` after `super()._setup()` — `_llm_chain` is `None` in `__init__`.

---

## AIContext

### Tiered Context Structure

`AIContext` carries all I1-I7 data needed by agents:

```python
class AIContext:
    symbol: str
    timeframe: str
    ts: datetime
    signal_id: str | None
    regime: str | None

    # Tier outputs
    bar: OHLCVBar
    i1: I1Indicators
    i2: I2Events
    i3: I3Structure
    i4: I4Context
    i5: I5Patterns
    smc: SMCContext
    i6: I6Confluence
```

### AIContextCache

In-memory cache with 5-min TTL, per-bar refresh.

**`build()` method:** Accepts `tiers_needed` frozenset — only requested tiers populate. This enables agents to declare exactly what they need.

**`render_full_context()` method:** LLM-friendly text rendering, null-filtered, formatted for prompts.

---

## Prompt Convention

### Prompt File Structure

Each agent has a paired `<name>_prompts.py`:

```python
ACTIVE_VERSION: str = "skeptic_v2"
PROMPT_REGISTRY: dict[str, str] = {
    "skeptic_v1": "...",
    "skeptic_v2": "...",
    # All historical versions preserved for rollback
}
```

### build_prompt() Pattern

```python
def build_skeptic_prompt(ctx: AIContext) -> str:
    """v2+ pattern: accepts typed AIContext directly."""
    return f"""Analyze this trading signal for failure probability.

Symbol: {ctx.symbol}
Timeframe: {ctx.timeframe}
Regime: {ctx.regime}

Key metrics:
- RSI: {ctx.i1.rsi_14}
- MACD histogram: {ctx.i2.macd_histogram_12_26_9}
- HMM regime: {ctx.smc.hmm_regime}
- CTF score: {ctx.i6.ctf_score}

OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE.
Begin your response with {{ and end with }}.
"""
```

**Always include `prompt_version` in AgentOutput.payload** so LineageRecorder attribution is correct.

---

## How to Add an AI Agent

### Step 1: Create Agent File

```python
# src/intelligence/ai/alpha/my_agent.py
from src.core.ai.base_agent import BaseAIWorker
from src.intelligence.ai.alpha.my_agent_prompts import ACTIVE_VERSION

class MyEvaluator(BaseAIWorker):
    agent_id = "my_agent_v1"
    group = "alpha"
    tiers_needed = frozenset([Tier.I4, Tier.I6])  # What this agent needs
    latency_budget_ms = 120_000  # 120 seconds
    shadow_only = True  # Start shadow-only
    prompt_version = ACTIVE_VERSION

    async def _compute(self, context: AIContext) -> AgentOutput:
        prompt = build_my_agent_prompt(context)
        response = await self._llm_generate(context, prompt=prompt, system=SYSTEM_MSG)

        if not response:
            return self._neutral(error="LLM returned empty", latency_ms=0.0)

        parsed = _parse_response(response)
        if parsed is None:
            return self._neutral(error="JSON parse failed", latency_ms=0.0)

        return AgentOutput(
            agent_id=self.agent_id,
            group=self.group,
            signal_id=context.signal_id,
            symbol=context.symbol,
            timeframe=context.timeframe,
            ts=context.ts,
            output_type="multiplier",
            payload={
                "multiplier": parsed.get("multiplier", 0.5),
                "confidence": parsed.get("confidence", 0.5),
                "reasoning": parsed.get("reasoning", ""),
                "prompt_version": self.prompt_version,
            },
            shadow_only=self.shadow_only,
        )
```

### Step 2: Create Prompt File

```python
# src/intelligence/ai/alpha/my_agent_prompts.py
ACTIVE_VERSION: str = "my_agent_v1"

PROMPT_REGISTRY: dict[str, str] = {
    "my_agent_v1": """Analyze this signal...

OUTPUT ONLY RAW JSON. NO PROSE. Begin your response with {{ and end with }}.
""",
}
```

### Step 3: Register in Group Service

```python
# services/alpha_swarm_agent.py
from src.intelligence.ai.alpha.my_agent import MyEvaluator

class AlphaSwarm(BaseGroupCoordinator):
    def _setup(self):
        # ...after super()._setup()...
        self._agents = {
            "skeptic_v1": SkepticEvaluator(...),
            "my_agent_v1": MyEvaluator(...),
            # ...
        }
```

### Step 4: Add to Service DAG

```python
# services/service_auditor.py
_DAG_ORDER = {
    ...
    "indicagent-alpha-swarm": 8,
    ...
}
```

### Step 5: Create systemd Unit

```bash
# production/systemd/indicagent-alpha-swarm.service
# Already exists — just restart after adding agent
sudo systemctl restart indicagent-alpha-swarm
```

### Reference Implementation

**Read first:** `src/intelligence/ai/alpha/skeptic_agent.py`

The patterns there (prompt registry, AgentOutput shape, neutral fallback, prompt_version attribution) are canonical.

---

## See Also

- **Foundation:** `intelligence-foundation.md` — I1-I8 definitions, Renaissance principles
- **Plugins:** `intelligence-plugins.md` — I1-I7 plugin protocol
- **Operations:** `intelligence-operations.md` — Services, monitoring, debugging
- **Authoring:** `src/intelligence/ai/AUTHORING.md` — Full agent authoring protocol
- **Template:** `src/core/ai/TEMPLATE_agent.py` — Agent skeleton
- **LLM chain:** `src/core/llm/chain.py` — Provider chain implementation
