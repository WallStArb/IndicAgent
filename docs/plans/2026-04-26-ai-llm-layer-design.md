# AI/LLM Layer — B+ Architecture Design

**Date:** 2026-04-26
**Status:** Approved — implementation pending
**Approach:** B+ (Agent Framework Refactor with Mandate Groups + C boundary discipline)

---

## Problem Statement

The current AI/LLM layer has ten structural defects that prevent it from scaling to a stable of many agents:

1. Two competing swarm services running simultaneously (`swarm_orchestrator_agent.py` installed with zero agents; `swarm_dispatch_service.py` uninstalled with real agents)
2. Rate limiters built but `acquire()` never called — dead code, no throttling
3. Guardrails silently pass everything when no schema registered — false confidence
4. LLM audit is caller-driven — callers that forget to publish lose calls from the audit trail
5. Narrative fires on every 1m bar with a winner — no TF gate, no cost control
6. Semantic cache key truncates at 200 chars — different prompts with identical prefixes collide
7. `swarm_orchestrator` unit has `WatchdogSec=60` but service never calls `sd_notify` — CLAUDE.md violation
8. `_find_lead_context` reaches into `_context_cache._cache` (private attr) — broken encapsulation
9. Graduation gate logic exists but has no automated runner — agents never auto-promote
10. `SwarmContext` hardcodes I4/I6 fields — new agent types can't extend context without modifying the shared model

Beyond defects, there is no reusable foundation. Every new agent type requires wiring its own Kafka, DB, LLM chain, and observability. The architecture cannot support a growing agent stable without proportionally growing maintenance burden.

---

## Design Principles

- **One interface for all agents.** Narrative, alpha, risk — same base class, same contract.
- **Groups are the unit of deployment.** Agents are compute classes. The group service owns all infrastructure.
- **The AI layer is a consumer of the intelligence bus.** `src/core/ai/` and `src/intelligence/ai/` import only from `src/intelligence/schemas.py` and `src/core/stream_keys.py`. Never from `src/intelligence/pipeline/` or any tier implementation.
- **Automation over manual.** Graduation, audit, routing — fully automated. No human step in the signal path.
- **Earn the right through proof.** `shadow_only=True` by default. Automated graduation flips it when Spearman gates pass.

---

## Module Structure

```
src/core/ai/                        ← NEW — universal AI infrastructure
  base_agent.py                     ← BaseAIAgent ABC + IAIAgent Protocol
  base_group_service.py             ← BaseGroupService shared dispatcher
  context.py                        ← AIContext, AIContextCache, Tier enum, TierContext models
  output.py                         ← AgentOutput universal envelope
  safe_wrapper.py                   ← SafeAgentWrapper (timeout + exception isolation)

src/core/llm/                       ← EXISTS — 6 fixes applied
  chain.py                          ← + auto-audit, real token counts, rate limiter called
  providers.py                      ← unchanged
  semantic_cache.py                 ← cache key: full prompt hash (remove 200-char truncation)
  token_budget.py                   ← unchanged
  rate_limiter.py                   ← unchanged (now actually called)
  guardrails.py                     ← dead check removed

src/intelligence/ai/                ← NEW — mandate-based agent groups
  alpha/                            ← alpha-contributing agents
    __init__.py
    skeptic_agent.py                ← moved from swarm/agents/
    correlation_agent.py            ← moved from swarm/agents/
    volume_agent.py                 ← moved from swarm/agents/
  narrative/                        ← qualitative/prose agents
    __init__.py
    narrative_agent.py              ← refactored from intelligence/narrative/
    prompts.py                      ← moved
    parsers.py                      ← moved
  risk/                             ← future group (placeholder)
    __init__.py

src/intelligence/swarm/             ← TRIMMED — keep only what's reused
  aggregator.py                     ← kept, used by AlphaSwarmComputeAgent
  graduation.py                     ← kept, called by BaseGroupService graduation_loop

services/
  alpha_swarm_agent.py              ← RENAMED from swarm_dispatch_service.py
  ai_narrative_agent.py             ← REFACTORED to extend BaseGroupService
  llm_writer_agent.py               ← UNCHANGED

DELETED:
  services/swarm_orchestrator_agent.py
  /etc/systemd/system/indicagent-swarm-orchestrator.service
```

---

## Core Interfaces

### `Tier` enum

```python
class Tier(str, Enum):
    BAR = "bar"
    I1  = "i1"
    I2  = "i2"
    I3  = "i3"
    I4  = "i4"
    I5  = "i5"
    I6  = "i6"
    I7  = "i7"
```

### `IAIAgent` Protocol (type-checking at call sites)

```python
class IAIAgent(Protocol):
    agent_id: str
    group: str
    tiers_needed: frozenset[Tier]
    shadow_only: bool
    latency_budget_ms: float

    async def compute(self, context: AIContext) -> AgentOutput: ...
```

### `BaseAIAgent` ABC (implementation base — agents extend this)

```python
class BaseAIAgent(ABC):
    agent_id: str                           # unique across all groups
    group: str                              # "alpha" | "narrative" | "risk"
    tiers_needed: frozenset[Tier]           # dispatcher populates only declared tiers
    shadow_only: bool = True                # flipped by graduation_loop
    latency_budget_ms: float = 5000.0

    @abstractmethod
    async def _compute(self, context: AIContext) -> AgentOutput:
        """Pure computation. Implement this. Must never raise."""

    async def compute(self, context: AIContext) -> AgentOutput:
        """Concrete wrapper: timing + error capture. Do not override."""
        t0 = time.monotonic()
        try:
            result = await self._compute(context)
            return result.model_copy(update={"latency_ms": (time.monotonic() - t0) * 1000})
        except Exception as exc:
            return self._neutral(error=str(exc), latency_ms=(time.monotonic() - t0) * 1000)

    def _neutral(self, error: str, latency_ms: float) -> AgentOutput:
        return AgentOutput(
            agent_id=self.agent_id, group=self.group,
            signal_id=None, symbol="", timeframe="", ts=datetime.now(UTC),
            output_type="neutral", payload={},
            shadow_only=self.shadow_only, latency_ms=latency_ms, error=error,
        )
```

### `AIContext` — tiered, immutable

```python
class AIContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Universal — always present
    signal_id:  UUID | None
    symbol:     str
    timeframe:  str
    ts:         datetime
    trigger:    str           # "signal" | "bar" | "regime_change" | "schedule"

    # Intelligence tiers — None unless in agent's tiers_needed
    bar: BarContext  | None = None
    i1:  I1Context  | None = None
    i4:  I4Context  | None = None
    i6:  I6Context  | None = None
    i7:  I7Context  | None = None
    # i2, i3, i5 added when first agent declares them

    # Enrichment — set by group service before dispatch
    lead_context:   AIContext        | None = None
    volume_profile: dict[str, float] | None = None
    external:       dict             | None = None  # qualitative stack hook
```

`TierContext` models (e.g. `I4Context`) are frozen Pydantic models — thin typed wrappers over the JSONB fields already present in `IntelligenceEvent`. `AIContextCache` unpacks only the tiers an agent declares.

### `AgentOutput` — universal envelope

```python
class AgentOutput(BaseModel):
    agent_id:    str
    group:       str
    signal_id:   UUID | None
    symbol:      str
    timeframe:   str
    ts:          datetime
    output_type: str          # "multiplier" | "narrative" | "risk_score" | "neutral"
    payload:     dict         # typed by output_type — group aggregator interprets
    shadow_only: bool
    latency_ms:  float
    error:       str | None = None
```

`payload` is untyped dict by design. The alpha aggregator reads `payload["multiplier"]`. The narrative service reads `payload["text"]`. The dispatcher, `SafeAgentWrapper`, graduation task, and `llm_writer_agent` all operate on `AgentOutput` without knowing the payload type. Adding a new output type requires zero changes to infrastructure.

### `BaseGroupService` — shared dispatcher

```python
class BaseGroupService(BaseAgent):
    group_id:        str           # "alpha" | "narrative" | "risk"
    has_graduation:  bool = True   # False for groups where agents are informational only
    aggregate_topic: str | None    # None if group produces no aggregate (e.g. narrative)

    @property
    @abstractmethod
    def agents(self) -> list[BaseAIAgent]: ...

    @property
    @abstractmethod
    def trigger_topics(self) -> list[str]: ...

    @property
    @abstractmethod
    def output_topic(self) -> str: ...

    # Inherited — subclasses never implement:
    async def _setup(self)                  # Kafka consumers/producer, DB pool, LLM chain, cache seed
    async def _run(self)                    # bar_loop + trigger_loop + graduation_loop tasks
    async def _handle_trigger(self, event)  # build context → gather → publish → aggregate
    async def _graduation_loop(self)        # background: evaluate_all() → auto-flip shadow_only
    async def _teardown(self)               # drain queues, flush, close
```

---

## Group Services

### `AlphaSwarmComputeAgent` (`services/alpha_swarm_agent.py`)

```python
class AlphaSwarmComputeAgent(BaseGroupService):
    group_id        = "alpha"
    has_graduation  = True
    aggregate_topic = topic_swarm_alpha   # publishes AlphaMultiplier

    @property
    def agents(self):
        return [
            SkepticAgentComputeAgent(self._llm_chain),
            CorrelationAgentComputeAgent(self._llm_chain),
            VolumeAgentComputeAgent(self._llm_chain),
        ]

    @property
    def trigger_topics(self):
        return [topic_intelligence_i7_signals(self._env)]

    @property
    def output_topic(self):
        return topic_swarm_results(self._env)
```

Adding a new alpha agent = one line in `agents`. No other change.

### `NarrativeGroupComputeAgent` (`services/ai_narrative_agent.py`)

```python
class NarrativeGroupComputeAgent(BaseGroupService):
    group_id        = "narrative"
    has_graduation  = False   # informational — no Spearman gate
    aggregate_topic = None    # no group aggregate

    @property
    def agents(self):
        return [NarrativeComputeAgent(self._llm_chain)]

    @property
    def trigger_topics(self):
        return [topic_intelligence_journal(self._env)]

    @property
    def output_topic(self):
        return topic_narratives(self._env)
```

### `RiskSwarmComputeAgent` (future)

When built: subclass `BaseGroupService`, declare `group_id = "risk"`, list risk agents, declare trigger topics. Zero infrastructure work.

---

## Data Flow

```
Bar arrives
  → bar_loop → AIContextCache.update(IntelligenceEvent)

Trigger event (i7 signal / journal record)
  → trigger_loop → BaseGroupService._handle_trigger(event)
      → for each agent: AIContextCache.build(symbol, tf, agent.tiers_needed) → AIContext
      → asyncio.gather(*[SafeAgentWrapper(agent).compute(ctx) for agent in self.agents])
      → AgentOutput × N
          → publish to output_topic (per-agent fan-out)
          → if aggregate_topic: SwarmAggregator.aggregate(outputs) → publish aggregate
          → ShadowRecorder.record(output)

LLM call (inside any agent's _compute):
  → LLMProviderChain.generate(prompt, system, max_tokens, timeout, audit_context)
      → rate_limiter.acquire(tokens=max_tokens)          ← NOW CALLED
      → semantic_cache.get(sha256(system+prompt+model))  ← FULL HASH
      → budget.is_exceeded() → route to Ollama if True
      → provider.generate() with circuit breaker
      → guardrails.validate() if schema registered
      → budget.record(actual_tokens from response.usage if available)
      → semantic_cache.put(...)
      → if audit_context: publish to topic_llm_calls     ← AUTO-AUDIT

Background graduation_loop (if has_graduation=True, runs every 15 min):
  → for each agent in self.agents:
      → query signal_transform_log WHERE agent_id = agent.agent_id
      → graduation.evaluate_all(df) → {is_graduated, spearman_rho, ...}
      → if is_graduated and agent.shadow_only:
          agent.shadow_only = False
          publish graduation event to topic_swarm_graduation
          structured log
      → if not is_graduated and not agent.shadow_only and degraded:
          agent.shadow_only = True   ← auto-demotion
```

---

## LLM Chain Fixes (6)

| # | Fix | File | Detail |
|---|-----|------|--------|
| 1 | Cache key | `semantic_cache.py` | `SHA-256(system + full_prompt + model)` — remove `[:200]` truncation |
| 2 | Rate limiter | `chain.py` | Call `await limiter.acquire(tokens=max_tokens)` before provider dispatch |
| 3 | Guardrails | `chain.py` | Remove dead branch; if no schema registered, skip `validate()` entirely |
| 4 | Auto-audit | `chain.py` | Add `audit_context: dict | None = None`; publish to `llm.calls` when provided |
| 5 | Real token counts | `chain.py` | Use `response_meta["usage"]["total_tokens"]` from OpenRouter when present |
| 6 | Watchdog violation | systemd unit | Remove `WatchdogSec=60` + `NotifyAccess=main` from swarm-orchestrator unit |

---

## Narrative TF Gate

`NarrativeComputeAgent._compute()` rejects timeframes not in `{"5m", "15m", "1h", "4h", "1d"}` before any LLM call. At 1m on 55 symbols, an ungated narrative service can generate 55+ LLM calls/minute with zero signal value — the 1m narrative is noise, not intelligence.

---

## Migration Checklist

| Action | Detail |
|--------|--------|
| DELETE | `services/swarm_orchestrator_agent.py` |
| DELETE | `/etc/systemd/system/indicagent-swarm-orchestrator.service` |
| RENAME | `swarm_dispatch_service.py` → `alpha_swarm_agent.py` |
| RENAME | `SwarmDispatchComputeAgent` → `AlphaSwarmComputeAgent` |
| NEW | `src/core/ai/` — 5 files (base_agent, base_group_service, context, output, safe_wrapper) |
| MOVE | `src/intelligence/swarm/agents/` → `src/intelligence/ai/alpha/` |
| MOVE | `src/intelligence/narrative/` → `src/intelligence/ai/narrative/` |
| GENERALIZE | `src/core/swarm/base_agent.py` → absorbed into `src/core/ai/base_agent.py` |
| GENERALIZE | `src/intelligence/swarm/safety.py` → `src/core/ai/safe_wrapper.py` |
| GENERALIZE | `src/intelligence/swarm/context.py` → `src/core/ai/context.py` (AIContext + AIContextCache) |
| KEEP | `src/intelligence/swarm/aggregator.py` (used by AlphaSwarmComputeAgent) |
| KEEP | `src/intelligence/swarm/graduation.py` (called by graduation_loop) |
| FIX | `ai_narrative_agent.py` — 5m+ TF gate |
| UPDATE | All existing agents extend `BaseAIAgent` instead of `SwarmBaseAgent` |
| PLACEHOLDER | `src/intelligence/ai/risk/__init__.py` — empty, marks future group |
| FIX | `_find_lead_context` — replace private `_cache` access with a public `AIContextCache.get_lead(symbol, tf)` method |

---

## Future Evolution: Approach C (Independent AI Package)

When the qualitative intelligence stack arrives and the agent stable exceeds ~10 agents, extract into a self-contained package:

```
src/ai/                     ← extracted from src/core/ai/ + src/intelligence/ai/
  core/                     ← base_agent, base_group_service, context, output
  llm/                      ← LLM infrastructure (moved from src/core/llm/)
  groups/
    alpha/
    narrative/
    risk/
    qualitative/            ← new qualitative intelligence group
  router.py                 ← AILayerRouter: maps Kafka topics → group services
```

The boundary discipline enforced in B+ (no imports from `src/intelligence/` internals) makes this a mechanical rename — no redesign. The `AILayerRouter` is the only net-new component: it replaces the per-service Kafka subscription with a single router that dispatches events to the right group service, enabling the AI layer to run as a single deployable unit or as independent services per group.

---

## Success Criteria

- Adding a new agent to an existing group = implement `_compute()` + one line in `agents` list
- Adding a new group = ~25 lines in a new `BaseGroupService` subclass
- Every LLM call appears in `llm_calls` audit table automatically
- Agents graduate from shadow mode automatically when Spearman gates pass (ρ ≥ 0.15, n ≥ 30, p < 0.05)
- Zero manual steps in the production signal path
- The AI layer imports nothing from `src/intelligence/pipeline/` or any tier plugin
