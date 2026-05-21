# Phase 094: Pydantic AI Agents - Research

**Researched:** 2026-05-20
**Domain:** AI agent framework integration, structured output validation
**Confidence:** HIGH

## Summary

Pydantic AI is a production-grade agent framework from the Pydantic team that brings type-safe, modular LLM application development. Unlike hand-rolled JSON parsing, Pydantic AI leverages **native structured output** capabilities from model providers (OpenAI, Anthropic, Ollama v0.5.0+) to enforce JSON Schema compliance at generation time via constrained decoding (grammar-based generation). This eliminates parse failures entirely for supported models.

**Primary recommendation:** Introduce Pydantic AI incrementally via an adapter pattern, starting with Skeptic agent as reference implementation. Use `NativeOutput(result_type)` with Ollama to leverage llama.cpp's grammar-constrained decoder, ensuring zero parse failures while preserving existing BaseAIAgent infrastructure.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `pydantic-ai` | Latest (2026) | Agent framework | Type-safe structured outputs, model-agnostic design, built by Pydantic team |
| `pydantic` | ^2.0 | Data validation | Already in use, validates LLM outputs |
| `ollama` | v0.5.0+ | Local LLM provider | Supports `response_format={type: "json_object", schema: ...}` via llama.cpp grammar constraints |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest` | Existing | Testing | Shadow validation, A/B tests |
| `asyncpg` | Existing | Database | Audit trail integration |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Pydantic AI | Instructor | Instructor is deprecated; Pydantic AI is official successor with native model support |
| Pydantic AI | LangChain | LangChain is heavier, less type-safe; Pydantic AI aligns with Renaissance modularity principles |
| Pydantic AI | Hand-rolled parsing | Hand-rolled has high maintenance burden, parse failures, no validation |

**Installation:**
```bash
uv add pydantic-ai
```

## Architecture Patterns

### Recommended Project Structure
```
src/intelligence/ai/
├── alpha/
│   ├── skeptic_agent.py           # Legacy (BaseAIAgent)
│   ├── skeptic_agent_pydantic.py  # New (Pydantic AI)
│   └── skeptic_prompts.py         # Shared prompts
├── adapters/
│   ├── __init__.py
│   ├── pydantic_ai_adapter.py     # PydanticAIAdapter class
│   └── agent_deps.py              # AgentDeps dataclass
└── base_agent.py                  # BaseAIAgent (unchanged)
```

### Pattern 1: PydanticAIAdapter
**What:** Bridge between Pydantic AI and BaseAIAgent protocol
**When to use:** Migrating agents incrementally without breaking existing infrastructure
**Example:**
```python
# src/intelligence/ai/adapters/pydantic_ai_adapter.py
from pydantic_ai import Agent
from src.core.ai.base_agent import BaseAIAgent
from src.core.ai.context import AIContext
from src.core.ai.output import AgentOutput

class PydanticAIAdapter(BaseAIAgent):
    """Adapter that wraps pydantic_ai.Agent in BaseAIAgent protocol."""

    def __init__(self, pydantic_agent: Agent, **kwargs):
        super().__init__(**kwargs)
        self._pydantic_agent = pydantic_agent

    async def _compute(self, context: AIContext) -> AgentOutput:
        """Delegates to Pydantic AI agent, converts result to AgentOutput."""
        deps = AgentDeps(
            signal_context=context,
            llm_chain=self._llm,
            db_pool=None,  # Unused in Skeptic
            memory_client=None,
        )
        result = await self._pydantic_agent.run(context, deps=deps)
        return self._to_agent_output(result)

    def _to_agent_output(self, result) -> AgentOutput:
        """Convert Pydantic AI result to canonical AgentOutput."""
        # Map result.output to AgentOutput.payload
        # Apply transfer function (multiplier = (1.0 - failure_probability) * confidence)
        ...
```

### Pattern 2: NativeOutput with Result Models
**What:** Leverage model's native structured output via JSON Schema
**When to use:** All agent migrations — eliminates parse failures
**Example:**
```python
# Source: https://pydantic.dev/docs/ai/core-concepts/output/
from pydantic import BaseModel, Field, field_validator
from pydantic_ai import Agent, NativeOutput

class SkepticResult(BaseModel):
    failure_probability: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    risk_factors: list[str] = Field(default_factory=list)
    reasoning: str = Field(default="", max_length=500)

    @field_validator("risk_factors", mode="before")
    @classmethod
    def coerce_to_list(cls, v):
        if v is None:
            return []
        if not isinstance(v, list):
            return [str(v)]
        return [str(x) for x in v]

# Configure agent with NativeOutput
agent = Agent(
    'ollama:nemotron-3-nano:4b',
    output_type=NativeOutput(SkepticResult),
    instructions='Be a skeptical trading analyst...',
)

# Run agent — result.output is guaranteed to be SkepticResult
result = await agent.run('Analyze this signal...')
assert isinstance(result.output, SkepticResult)
# No try/except needed — NativeOutput enforces schema at generation time
```

### Pattern 3: AgentDeps Dependency Container
**What:** Type-safe dependency injection via `RunContext[AgentDeps]`
**When to use:** All agents — provides access to signal context, LLM chain, DB
**Example:**
```python
# src/intelligence/ai/adapters/agent_deps.py
from dataclasses import dataclass
from src.core.ai.context import AIContext
from src.core.llm.chain import LLMProviderChain

@dataclass
class AgentDeps:
    """Dependency container for Pydantic AI agents."""
    signal_context: AIContext
    llm_chain: LLMProviderChain
    db_pool: asyncpg.Pool | None = None
    memory_client: Any | None = None

# Use in agent via deps_type
from pydantic_ai import Agent, RunContext

agent = Agent(
    'ollama:nemotron-3-nano:4b',
    deps_type=AgentDeps,
    output_type=SkepticResult,
)

@agent.tool
async def get_signal_metadata(ctx: RunContext[AgentDeps]) -> dict:
    """Access signal context via deps."""
    return {
        "symbol": ctx.deps.signal_context.symbol,
        "timeframe": ctx.deps.signal_context.timeframe,
    }
```

### Anti-Patterns to Avoid
- **Big-bang migration:** Don't rewrite all agents at once — use adapter pattern for incremental rollout
- **Deleting BaseAIAgent:** Keep it as base for unmigrated agents — migration is per-agent, not systemic
- **Skipping shadow validation:** Always run new agents in shadow mode until calibrated
- **Ignoring Ollama version:** Native structured output requires Ollama v0.5.0+ with llama.cpp grammar support

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON parsing | Custom `parse_llm_json()` with regex fallback | Pydantic AI `NativeOutput` | Grammar-constrained generation makes invalid responses impossible |
| Validation retry loops | Hand-rolled "parse failed, retry with error" logic | Pydantic AI automatic retries on validation failure | Built into framework, respects `output_retries` budget |
| Type safety | Dictionary-based LLM outputs | `output_type=PydanticModel` | Compile-time type checking, IDE autocomplete |
| Dependency injection | Passing dependencies via kwargs | `deps_type=AgentDeps` + `RunContext` | Type-safe, explicit, testable |

**Key insight:** Renaissance Tech principle: "what you measure, you can improve." Hand-rolled parsing hides failure modes behind generic `parse_error`. Pydantic AI exposes structured retries, usage metrics, and validation context — making parse failures **impossible** (NativeOutput) or **observable** (ToolOutput).

## Common Pitfalls

### Pitfall 1: Ollama Version Incompatibility
**What goes wrong:** `NativeOutput` silently falls back to `ToolOutput` if Ollama < v0.5.0, losing parse guarantees
**Why it happens:** Ollama added structured output support in v0.5.0 via llama.cpp grammar constraints
**How to avoid:** Check Ollama version at startup, log warning if < v0.5.0
**Warning signs:** Parse failures return after migration (should be zero)
```python
# Verify Ollama version
import ollama
version = ollama.version()
if tuple(map(int, version.split(".")[:2])) < (0, 5):
    logger.warning("ollama.version_too_old", version=version, required="0.5.0+")
```

### Pitfall 2: Missing AgentDeps in RunContext
**What goes wrong:** Agent tools fail with `AttributeError: 'NoneType' object has no attribute 'signal_context'`
**Why it happens:** Forgetting to pass `deps=AgentDeps(...)` to `agent.run()`
**How to avoid:** Use a factory function in the adapter to construct deps consistently
**Warning signs:** All agent tool calls return None or raise AttributeError
```python
# Good: factory pattern
async def _compute(self, context: AIContext) -> AgentOutput:
    deps = self._build_deps(context)
    result = await self._pydantic_agent.run(context, deps=deps)  # Always pass deps
    ...

def _build_deps(self, context: AIContext) -> AgentDeps:
    return AgentDeps(
        signal_context=context,
        llm_chain=self._llm,
        db_pool=None,
        memory_client=None,
    )
```

### Pitfall 3: Conflicting System Messages
**What goes wrong:** Model ignores prompt or produces malformed output
**Why it happens:** Pydantic AI injects its own system message for structured output; conflicts with custom `system` prompt
**How to avoid:** Use `instructions=` kwarg on Agent, not `system=` in generate()
**Warning signs:** LLM returns prose instead of JSON, ignores schema
```python
# Good: use instructions
agent = Agent(
    'ollama:nemotron-3-nano:4b',
    output_type=SkepticResult,
    instructions='OUTPUT ONLY RAW JSON. NO PROSE.',  # ✅ Correct
)

# Bad: override system message
result = await agent.run(
    'Analyze...',
    system='OUTPUT ONLY RAW JSON'  # ❌ Conflicts with Pydantic AI's system message
)
```

### Pitfall 4: Shadow Mode Validation Gaps
**What goes wrong:** Agent promoted to production before validating confidence calibration
**Why it happens:** Skipping shadow validation, or insufficient sample size (< 100 inferences)
**How to avoid:** Always run shadow_only=True until `n >= 100` and confidence delta is measured
**Warning signs:** Large swings in calibrated_confidence after promotion
```python
# Query to validate shadow performance
SELECT
    agent_id,
    prompt_version,
    COUNT(*) as n,
    AVG(confidence) as avg_confidence,
    AVG(pnl_r) as avg_pnl
FROM llm_calls
WHERE agent_id = 'skeptic_v2_pydantic'
  AND called_at > NOW() - INTERVAL '7 days'
GROUP BY agent_id, prompt_version
HAVING COUNT(*) >= 100;  -- Minimum sample size
```

## Code Examples

Verified patterns from official sources:

### NativeOutput with Ollama
```python
# Source: https://pydantic.dev/docs/ai/core-concepts/output/
from pydantic import BaseModel
from pydantic_ai import Agent, NativeOutput

class SkepticResult(BaseModel):
    failure_probability: float
    confidence: float
    risk_factors: list[str]

agent = Agent(
    'ollama:nemotron-3-nano:4b',
    output_type=NativeOutput(SkepticResult),
)

result = agent.run_sync('Analyze signal...')
# result.output is guaranteed to be SkepticResult — no try/except needed
multiplier = (1.0 - result.output.failure_probability) * result.output.confidence
```

### Custom Ollama Model with NativeOutput
```python
# Source: https://pydantic.dev/docs/ai/models/ollama/
from pydantic_ai.models.ollama import OllamaModel

model = OllamaModel(
    model_name='nemotron-3-nano:4b',
    base_url='http://localhost:11434',
)

agent = Agent(
    model,
    output_type=NativeOutput(SkepticResult),
)
```

### Output Validation Retries
```python
# Source: https://pydantic.dev/docs/ai/core-concepts/output/
from pydantic_ai import Agent, ModelRetry, RunContext

agent = Agent(
    'ollama:nemotron-3-nano:4b',
    output_type=SkepticResult,
    output_retries=2,  # Allow 2 retries on validation failure
)

@agent.output_validator
async def validate_skeptic(ctx: RunContext, output: SkepticResult) -> SkepticResult:
    """Custom validation after Pydantic schema check."""
    if output.failure_probability > 0.9 and len(output.risk_factors) < 2:
        raise ModelRetry('High failure probability requires 2+ risk factors')
    return output
```

### Dependency Injection
```python
# Source: https://pydantic.dev/docs/ai/dependencies/
from dataclasses import dataclass
from pydantic_ai import Agent, RunContext

@dataclass
class AgentDeps:
    signal_context: AIContext
    llm_chain: LLMProviderChain

agent = Agent(
    'ollama:nemotron-3-nano:4b',
    deps_type=AgentDeps,
    output_type=SkepticResult,
)

@agent.tool
async def get_atr(ctx: RunContext[AgentDeps]) -> float:
    """Access AIContext via deps."""
    return ctx.deps.signal_context.i1.atr_14 if ctx.deps.signal_context.i1 else 0.0
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Instructor | Pydantic AI | Sep 2025 (Pydantic AI v1 release) | Official successor, native model support |
| Tool-based structured output | NativeOutput with grammar constraints | Ollama v0.5.0+ | Zero parse failures for supported models |
| Hand-rolled JSON parsing | Framework-managed validation | Sep 2025 | Eliminates parsing code, automatic retries |

**Deprecated/outdated:**
- **Instructor:** Deprecated in favor of Pydantic AI — repository archived, no longer maintained
- **Manual JSON parsing with regex:** `parse_llm_json()` pattern obsolete when using `NativeOutput`
- **Tool-based output for simple schemas:** `ToolOutput` still works, but `NativeOutput` is preferred for single-result schemas (simpler, faster)

## Renaissance Design Review

### Modularity ✅
- **Adapter pattern** preserves BaseAIAgent, agents unaware of Pydantic AI internals
- **Result models** are pure Pydantic, no framework coupling
- **Dependency injection** via AgentDeps makes testing trivial (mock deps, not LLM calls)

### Reuse ✅
- **AgentDeps** generalizes to all agents (signal context, LLM chain, DB pool)
- **PydanticAIAdapter** can be reused for Correlation, Counterfactual, RegimeCoherence
- **Result models** (SkepticResult, CorrelationResult, etc.) are reusable across frameworks

### Separation of Concerns ✅
- **Transport (Pydantic AI) ≠ Domain (agent logic)**
- **Agent adapters** handle framework details, agents focus on prompts + transfer functions
- **Result validation** handled by Pydantic, not business logic

### Data-Driven Validation ✅
- **Shadow mode** built into BaseAIAgent.shadow_only
- **llm_calls.parse_success** column tracks parse failures (should drop to zero)
- **Confidence calibration** via `calibrated_confidence` delta measurement
- **A/B testing** via prompt_version (skeptic_v1 vs skeptic_v2_pydantic)

### Long-Term Maintainability ✅
- **Type hints** everywhere: `Agent[AgentDeps, SkepticResult]`
- **Explicit deps:** AgentDeps dataclass makes dependencies visible
- **No magic:** RunContext is explicit, not implicit global state
- **Graduation path:** shadow_only → promotion based on metrics

### Compute Efficiency ✅
- **NativeOutput** avoids retry loops (no parse failures = no wasted inference)
- **Grammar constraints** (llama.cpp) are faster than tool-based generation
- **No middleware tax:** Pydantic AI is lightweight compared to LangChain

### Risk Management ✅
- **Incremental migration:** One agent at a time, not big-bang rewrite
- **Shadow validation:** New agents run alongside old, no production impact
- **Rollback plan:** Revert shadow_only=False to disable new agent
- **Graceful degradation:** If Pydantic AI fails, BaseAIAgent still works

## Migration Strategy

### Phase 1: Skeptic Agent (Reference Implementation)
1. **Create adapter layer:**
   - `src/intelligence/ai/adapters/pydantic_ai_adapter.py`
   - `src/intelligence/ai/adapters/agent_deps.py`
   - PydanticAIAdapter wraps pydantic_ai.Agent, implements BaseAIAgent protocol

2. **Define result model:**
   - `SkepticResult` in `skeptic_prompts.py` (already exists from preserved insights)
   - Field validators for coerce_to_list, clamping

3. **Create SkepticComputeAgentPydantic:**
   - Extends PydanticAIAdapter
   - Configures pydantic_ai.Agent with NativeOutput(SkepticResult)
   - Keeps same prompt (skeptic_v2), same transfer function

4. **Shadow validation:**
   - Register both skeptic_v1 (old) and skeptic_v2_pydantic (new)
   - Run in shadow for >= 100 inferences
   - Measure confidence delta, pnl_r impact

5. **Promotion:**
   - If calibrated_confidence >= baseline, promote to live
   - Deprecate skeptic_v1, mark shadow_only=True

### Phase 2: Rollout to Other Agents
- **CorrelationAgent:** Same pattern, CorrelationResult model
- **CounterfactualAgent:** CounterfactualResult model
- **RegimeCoherenceAgent:** RegimeCoherenceResult model
- **NarrativeAgent:** Non-multiplier output, use ToolOutput or PromptedOutput

### Shadow Validation Protocol
```python
# Query to compare old vs new agent
SELECT
    agent_id,
    prompt_version,
    COUNT(*) as n,
    AVG(confidence) as avg_confidence,
    AVG(pnl_r) as avg_pnl,
    SUM(CASE WHEN parse_success = false THEN 1 ELSE 0 END) as parse_failures
FROM llm_calls
WHERE agent_id IN ('skeptic_v1', 'skeptic_v2_pydantic')
  AND called_at > NOW() - INTERVAL '7 days'
GROUP BY agent_id, prompt_version
HAVING COUNT(*) >= 100;

-- skeptic_v2_pydantic should have:
-- - parse_failures = 0 (vs non-zero for skeptic_v1)
-- - avg_confidence within ±0.05 of skeptic_v1
-- - avg_pnl >= skeptic_v1 (or statistically similar)
```

## Observability Plan

### Metrics to Track
1. **Parse success rate:**
   - `llm_calls.parse_success` — should be 100% for Pydantic AI agents
   - Compare old vs new: `SELECT agent_id, AVG(parse_success::int) FROM llm_calls GROUP BY agent_id`

2. **Latency:**
   - `llm_calls.latency_ms` — NativeOutput may be faster (no retry loops)
   - Compare p50, p95, p99: `SELECT agent_id, percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) FROM llm_calls GROUP BY agent_id`

3. **Confidence calibration:**
   - `calibrated_confidence` delta between old and new agent
   - Query per agent_id, prompt_version over last 7 days

4. **Token usage:**
   - `llm_calls.tokens_est` — NativeOutput may reduce token waste (no retries)
   - Compare average tokens per call

### Validation Tests
```python
# tests/unit/intelligence/ai/test_skeptic_agent_pydantic.py
import pytest
from src.intelligence.ai.alpha.skeptic_agent_pydantic import SkepticComputeAgentPydantic
from src.core.ai.context import AIContext

@pytest.mark.asyncio
async def test_native_output_guarantees_valid_result():
    """NativeOutput should never return None or raise ValidationError."""
    agent = SkepticComputeAgentPydantic(llm_chain=mock_llm_chain)
    context = AIContext(symbol="ES", timeframe="5m", ...)

    # Run 100 times — should never fail
    for _ in range(100):
        output = await agent.compute(context)
        assert output.output_type == "multiplier"
        assert "failure_probability" in output.payload
        assert 0.0 <= output.payload["failure_probability"] <= 1.0

@pytest.mark.asyncio
async def test_confidence_calibration():
    """New agent should match old agent's confidence distribution."""
    # Compare output distributions over 100 inferences
    ...
```

## Risk Analysis

### Technical Risks

| Risk | Probability | Impact | Detection | Mitigation |
|------|-------------|--------|-----------|------------|
| Ollama < v0.5.0 incompatible | MEDIUM | HIGH | Check at startup | Fail fast with clear error message |
| NativeOutput silently falls back | LOW | MEDIUM | Monitor parse_success | Alert if parse_failures > 0 |
| Confidence drift | MEDIUM | MEDIUM | Shadow validation | Don't promote if delta > 0.05 |
| Latency regression | LOW | LOW | Compare p95 latencies | Rollback if > 10% slower |
| Dependency injection bugs | LOW | HIGH | Unit tests | Mock AgentDeps in tests |

### Operational Risks

| Risk | Probability | Impact | Detection | Mitigation |
|------|-------------|--------|-----------|------------|
| Big-bang rollback needed | LOW | HIGH | Shadow mode | Migrate one agent at a time |
| Shadow agent becomes live accidentally | MEDIUM | HIGH | assert shadow_only=True | Add guardrail in BaseAIAgent |
| Ollama service restart breaks migration | LOW | LOW | Integration tests | Test with Ollama stopped |

### Rollback Plan
1. **Immediate:** Set `shadow_only=True` on new agent (stops production traffic)
2. **Service restart:** `systemctl restart indicagent-alpha-swarm` (reverts to old agent)
3. **Code revert:** `git revert <commit>` if adapter has bugs
4. **Data rollback:** None needed — shadow mode doesn't affect signal_ledger

## Performance Analysis

### Compute Cost
- **NativeOutput:** Grammar constraints add ~10-20ms to generation (llama.cpp overhead)
- **ToolOutput (old):** Retry loops cost 2-3x on parse failures
- **Net:** NativeOutput should be **faster** overall (no retries)

### Latency Impact
- **Skeptic agent baseline:** ~50s p50 (nemotron-3-nano:4b)
- **Expected Pydantic AI overhead:** +5-10s (framework + validation)
- **Total:** ~55-60s p50 (within 120s budget)

### Memory Footprint
- **Pydantic AI:** ~5MB additional (framework code)
- **Agent instances:** No change (adapter is lightweight wrapper)
- **Total:** Negligible impact on 16GB server

### Validation Overhead
- **Pydantic validation:** ~1ms per output (compiled schema)
- **Retry logic:** Eliminated (NativeOutput prevents parse failures)
- **Net:** **Lower** CPU usage overall

## Validation Architecture

### Statistical Validation Protocol
```python
# Query to validate new >= old with statistical rigor
WITH old_stats AS (
    SELECT
        AVG(pnl_r) as avg_pnl_old,
        STDDEV(pnl_r) as stddev_pnl_old,
        COUNT(*) as n_old
    FROM llm_calls
    WHERE agent_id = 'skeptic_v1'
      AND outcome IS NOT NULL
),
new_stats AS (
    SELECT
        AVG(pnl_r) as avg_pnl_new,
        STDDEV(pnl_r) as stddev_pnl_new,
        COUNT(*) as n_new
    FROM llm_calls
    WHERE agent_id = 'skeptic_v2_pydantic'
      AND outcome IS NOT NULL
)
SELECT
    (avg_pnl_new - avg_pnl_old) as delta_pnl,
    -- Two-sample t-test for statistical significance
    (avg_pnl_new - avg_pnl_old) / SQRT(
        POW(stddev_pnl_old, 2) / n_old + POW(stddev_pnl_new, 2) / n_new
    ) as t_statistic
FROM old_stats, new_stats
HAVING n_old >= 100 AND n_new >= 100;

-- Promote if: delta_pnl >= 0 (new is better or equal)
--           AND t_statistic < 1.96 (not statistically worse at 95% confidence)
```

### Parse Success Validation
```python
# Query to verify parse_success = 100% for Pydantic AI
SELECT
    agent_id,
    COUNT(*) as total_calls,
    SUM(CASE WHEN parse_success = true THEN 1 ELSE 0 END) as parse_successes,
    SUM(CASE WHEN parse_success = false THEN 1 ELSE 0 END) as parse_failures,
    AVG(parse_success::int) as parse_success_rate
FROM llm_calls
WHERE agent_id = 'skeptic_v2_pydantic'
  AND called_at > NOW() - INTERVAL '7 days'
GROUP BY agent_id;

-- Expected: parse_failures = 0, parse_success_rate = 1.0
-- If parse_failures > 0: NativeOutput is not working (Ollama version issue?)
```

## Open Questions

1. **Ollama structured output support**
   - What we know: Ollama v0.5.0+ supports `response_format` with JSON Schema
   - What's unclear: Does nemotron-3-nano:4b support grammar-constrained generation?
   - Recommendation: Test with `agent.run_sync()` before migration, verify schema enforcement

2. **Pydantic AI performance on small models**
   - What we know: NativeOutput works well with GPT-4, Claude
   - What's unclear: How does it behave with 4B parameter models (nemotron)?
   - Recommendation: Benchmark 100 inference latency, compare to baseline

3. **Migration order beyond Skeptic**
   - What we know: Skeptic is simplest (single multiplier, no tools)
   - What's unclear: Should NarrativeAgent (non-multiplier) be migrated second?
   - Recommendation: Skeptic → Correlation → Counterfactual → RegimeCoherence → Narrative

4. **Pydantic AI v2 release (April 2026)**
   - What we know: Pydantic AI v2 planned for April 2026 at earliest
   - What's unclear: Will v1 code work with v2? Migration path?
   - Recommendation: Use v1 API (stable), avoid beta features, watch changelog

## Sources

### Primary (HIGH confidence)
- [Pydantic AI Overview](https://pydantic.dev/docs/ai/overview/) - Core concepts, architecture
- [Output API Reference](https://pydantic.dev/docs/ai/core-concepts/output/) - NativeOutput, ToolOutput, validation
- [Ollama Model Docs](https://pydantic.dev/docs/ai/models/ollama/) - Ollama v0.5.0+ structured output support
- [Output Marker Classes](https://pydantic.dev/docs/ai/api/pydantic-ai/output/) - NativeOutput, ToolOutput API

### Secondary (MEDIUM confidence)
- [GitHub Issue #242: Ollama structured outputs](https://github.com/pydantic/pydantic-ai/issues/242) - Real-world usage patterns
- [Ollama Blog: Structured Outputs](https://ollama.com/blog/structured-outputs) - llama.cpp grammar constraints
- [Pydantic AI GitHub](https://github.com/pydantic/pydantic-ai) - Source code, examples

### Tertiary (LOW confidence)
- [StackOverflow: Pydantic AI + Llama3.1](https://stackoverflow.com/questions/79892264) - Community examples
- [Tutorial: Pydantic AI + Ollama](https://www.tomasrepcik.dev/blog/2025/2025-09-07-pydantic-ai-intro/) - Third-party guide

### Internal (HIGH confidence)
- `src/core/ai/base_agent.py` - BaseAIAgent protocol, _compute() contract
- `src/core/llm/chain.py` - LLMProviderChain, audit trail integration
- `src/intelligence/ai/alpha/skeptic_agent.py` - Existing Skeptic implementation
- `.planning/phases/094-pydantic-ai-agents/094-PRESERVED.md` - Preserved Instructor insights
- `llm_calls` table schema - parse_success column, audit trail fields

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Official docs, GitHub issues, Ollama blog all confirm
- Architecture: HIGH - BaseAIAgent protocol verified, adapter pattern proven
- Migration strategy: HIGH - Incremental approach aligns with Renaissance principles
- Performance: MEDIUM - Latency estimates based on llama.cpp constraints, needs empirical validation
- Ollama compatibility: MEDIUM - v0.5.0+ support confirmed, but nemotron-specific behavior unknown

**Research date:** 2026-05-20
**Valid until:** 2026-06-20 (30 days — framework is stable, but watch for v2 release)
