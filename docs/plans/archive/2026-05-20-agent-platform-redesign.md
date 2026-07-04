# Agent Platform Redesign — Pydantic AI + DSPy + Zep + LiteLLM

**Version:** 1.0
**Last Updated:** 2026-05-20
**Date:** 2026-05-20  
**Status:** Approved — pending implementation plan  
**Scope:** Replace BaseAIAgent architecture with institutional-grade open-source stack

---

## Motivation

Current system has ~400 lines of custom boilerplate per agent group (BaseAIAgent,
BaseMultiplierAgent, _parse_multiplier_response, _validate_*_fields, GuardrailsValidator,
OllamaProvider, OpenRouterProvider). Parse failure rate was 17-19% historically. No memory
layer. No systematic prompt optimization. Not extensible to user-created agents.

Goal: platform that scales to many agents, supports user-created agents, uses best-in-class
open-source frameworks, and has systematic evaluation infrastructure — built like Renaissance
would build it (every agent is a measurable hypothesis).

---

## Architecture

Seven layers with clean separation. Each layer has one job.

```
L7  DSPy Optimizer          offline — compiles prompts from outcome data
L6  Agent Registry          agent_id → spec, dynamic instantiation, user agents
L5  Memory (Zep)            episodic — past setups by regime/symbol/setup_type
L4  Guardrails AI           content validation — replaces GuardrailsValidator
L3  Instructor              structured output + retry — replaces parse boilerplate
L2  Pydantic AI             agent execution, typed results, deps injection, tools
L1  LiteLLM + CircuitBreaker provider abstraction — Ollama → OpenRouter fallback
L0  Infrastructure (kept)   Kafka, TimescaleDB, shadow registry, graduation, OTel
```

### What Stays (domain infrastructure — not touched)

- `BaseGroupService` — Kafka consumer/producer/DB pool dispatch
- `signal_ledger`, `llm_calls`, `shadow_registry`, graduation loop
- `CircuitBreaker` — LiteLLM's failure handling is a budget counter, not true half-open
- `SemanticCache`, `TokenBudget`
- OTel tracing, structlog

### What Gets Replaced

- `BaseAIAgent`, `BaseMultiplierAgent` → Pydantic AI `Agent[AgentDeps, ResultType]`
- `_parse_multiplier_response`, `_validate_*_fields` → Instructor structured output
- `GuardrailsValidator` → Guardrails AI
- `OllamaProvider`, `OpenRouterProvider`, `LLMChain` internals → LiteLLM

---

## Layer 1: LLM Infrastructure — LiteLLM + CircuitBreaker

LiteLLM replaces provider-specific classes, normalizing Ollama and OpenRouter into one
interface. `CircuitBreaker` wraps LiteLLM (kept — LiteLLM lacks true half-open state).

```
LiteLLM
  ├── ollama/nemotron-3-nano:4b        primary
  ├── openrouter/nvidia/nemotron...    fallback 1
  └── openrouter/google/gemma-4b      fallback 2

CircuitBreaker (kept)     wraps LiteLLM, half-open recovery
SemanticCache (kept)      in front of LiteLLM
TokenBudget (kept)        observability only
Kafka audit (kept)        via LiteLLM callback hooks
```

`LLMProviderChain.generate()` public interface is unchanged — `BaseGroupService` needs no
changes.

---

## Layer 2: Agent Execution — Pydantic AI + Instructor

Each agent is a `pydantic_ai.Agent[AgentDeps, ResultType]`. Instructor enforces structured
output with automatic retry on parse failure (injects validation error back into prompt).

```python
# Typed result replaces _validate_*_fields
class SkepticResult(BaseModel):
    failure_probability: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    risk_factors: list[str]
    reasoning: str = Field(max_length=400)

# Agent replaces ~100-line BaseAIAgent subclass
skeptic_agent = Agent(
    model=litellm_backend,
    result_type=SkepticResult,
    system_prompt=SYSTEM_PROMPT,
    deps_type=AgentDeps,
)

@skeptic_agent.system_prompt
async def enrich_with_memory(ctx: RunContext[AgentDeps]) -> str:
    episodes = await ctx.deps.memory.recall(ctx.deps.context)
    return format_episodes(episodes)
```

### AgentDeps

```python
@dataclass
class AgentDeps:
    context: AIContext          # existing typed context
    memory: EpisodicMemoryStore
    settings: Settings
```

### Latency budget / timeout

`asyncio.wait_for` wrapper preserved at dispatch layer in `BaseGroupService`.

### Audit trail

Pydantic AI result validators + LiteLLM callback hooks write to `llm_calls` via existing
Kafka audit path. `call_id`, `prompt_version`, `agent_id` injected as before.

---

## Layer 3: Guardrails AI

Replaces custom `GuardrailsValidator`. Validates content (not just structure) of agent
outputs — e.g. confidence values in plausible range, reasoning not hallucinated ticker symbols.

Runs as a Pydantic AI result validator after Instructor has enforced structure.

```python
@skeptic_agent.result_validator
async def validate_skeptic_result(ctx: RunContext[AgentDeps], result: SkepticResult):
    guard = Guard().use(ValidRange, min=0, max=1, on="failure_probability")
    guard.validate(result.model_dump())
    return result
```

---

## Layer 4: Memory — Zep

Zep chosen over Mem0 for temporal knowledge graph model — past trading setups have
timestamps and invalidation events (stale when regime changes). Best fit for episodic
trading memory.

```python
class EpisodicMemoryStore:
    async def recall(self, context: AIContext, k: int = 5) -> list[Episode]
    async def record(self, context: AIContext, outcome: SignalOutcome) -> None
```

`recall()` queries Zep for k most similar past setups by (symbol, regime, setup_type,
indicator fingerprint). Episodes injected into agent system prompt enrichment.

`record()` called by `llm_writer_service` when `signal_ledger` outcome is written —
closes the feedback loop.

---

## Layer 5: Agent Registry

Central registry enabling dynamic agent instantiation and user-created agents without
subclassing.

```python
@dataclass
class AgentSpec:
    agent_id: str
    group: str
    tiers_needed: frozenset[Tier]
    latency_budget_ms: float
    shadow_only: bool
    result_type: type[BaseModel]
    system_prompt: str
    tools: list[Callable]
    memory_schema: MemorySchema | None
    dspy_program: str | None          # path to compiled DSPy artifact
```

User-created agents defined via YAML spec, loaded and instantiated by registry at startup.
No Python subclassing required.

```yaml
# agents/custom_momentum_agent.yaml
agent_id: momentum_v1
group: alpha
tiers_needed: [i1, i4, i6, i7]
latency_budget_ms: 30000
shadow_only: true
result_type: MomentumResult
system_prompt: "..."
```

---

## Layer 6: DSPy Optimization Pipeline

Offline only — never runs in the production hot path.

```
scripts/optimize_agents.py
  1. Load llm_calls (last 30d) + signal_ledger outcomes
  2. Build (input, output) training pairs — pnl_r > 0 = positive label
  3. Define metric: parse_success AND outcome prediction accuracy
  4. Run MIPROv2 optimizer per agent
  5. Save compiled program → agents/<agent_id>_compiled.json
  6. At startup: agents load compiled program, overrides hand-written prompt
```

Compiled programs are versioned artifacts in git. Reverting is `git revert`.
A/B testing is loading two compiled programs and splitting signals between them.

---

## Migration Phases

Each phase ships independently with no regression risk.

| Phase | What | Replaces | Value |
|---|---|---|---|
| 1 | LiteLLM + adapter | OllamaProvider, OpenRouterProvider | Provider abstraction |
| 2 | Instructor | _parse_multiplier_response, _validate_* | Parse failures → ~0% |
| 3 | Pydantic AI agents | BaseAIAgent, BaseMultiplierAgent | Typed results, tool use |
| 4 | Agent Registry | Hard-coded agent lists | User-created agents |
| 5 | Zep memory | Nothing (new capability) | Episodic context enrichment |
| 6 | DSPy optimizer | Hand-written prompt builders | Systematic prompt improvement |
| 7 | Guardrails AI | GuardrailsValidator | Content validation, injection hardening |

---

## Tech Stack

| Component | Library | Version | Notes |
|---|---|---|---|
| Agent execution | pydantic-ai | latest | |
| Structured output | instructor | latest | Works with Pydantic AI natively |
| LLM routing | litellm | latest | Wrap with existing CircuitBreaker |
| Memory | zep-python | latest | Self-hosted, temporal knowledge graph |
| Prompt optimization | dspy-ai | latest | Offline only |
| Content guardrails | guardrails-ai | latest | Phase 7 |

---

## Non-Goals

- Replacing Kafka, TimescaleDB, or the service DAG
- Replacing OTel tracing or structlog
- Adding Claude/Anthropic API (system uses local Ollama + OpenRouter free tier)
- Kubernetes or container orchestration changes
- Real-time DSPy optimization (offline only)
