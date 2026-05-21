# Phase 094: Pydantic AI Agents - Pattern Map

**Mapped:** 2026-05-20
**Files analyzed:** 8
**Analogs found:** 8 / 8

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/intelligence/ai/adapters/pydantic_ai_adapter.py` | adapter | request-response | `src/core/ai/base_agent.py` | role-match |
| `src/intelligence/ai/adapters/agent_deps.py` | utility | config | `src/core/ai/context.py` (dataclass pattern) | role-match |
| `src/intelligence/ai/alpha/skeptic_agent_pydantic.py` | agent | request-response | `src/intelligence/ai/alpha/skeptic_agent.py` | exact |
| `src/intelligence/ai/alpha/skeptic_prompts.py` (modified) | utility | transform | `src/intelligence/ai/alpha/skeptic_prompts.py` | exact |
| `tests/unit/intelligence/ai/test_skeptic_agent_pydantic.py` | test | validation | `tests/unit/test_skeptic_agent.py` | exact |
| `tests/unit/intelligence/ai/test_pydantic_ai_adapter.py` | test | validation | `tests/unit/test_skeptic_agent.py` | role-match |
| `services/alpha_swarm_agent.py` (modified) | service | event-driven | `services/alpha_swarm_agent.py` | exact |
| `requirements.txt` (modified) | config | batch | `requirements.txt` | exact |

## Pattern Assignments

### `src/intelligence/ai/adapters/pydantic_ai_adapter.py` (adapter, request-response)

**Analog:** `src/core/ai/base_agent.py`

**Purpose:** Bridge between Pydantic AI and BaseAIAgent protocol, preserving existing infrastructure while enabling native structured output.

**BaseAIAgent contract pattern** (lines 52-78):
```python
class BaseAIAgent(BaseAgent, ABC):
    """Abstract base for all AI agents.
    
    Subclasses must implement:
    - _compute(context: AIContext) -> AgentOutput
    
    Inherits from BaseAgent for full lifecycle:
    - SIGTERM/SIGINT handling
    - Structured logging (self.logger)
    - OTel tracing (self.tracer)
    """
    agent_id: str = ""  # override in subclass
    group: str = ""  # "alpha", "narrative", "risk"
    tiers_needed: frozenset[Tier] = frozenset()
    shadow_only: bool = True
    latency_budget_ms: float = 5000.0
    prompt_version: str = ""
```

**compute() wrapper pattern** (lines 89-147):
```python
async def compute(self, context: AIContext) -> AgentOutput:
    """Run _compute() with timing capture + exception safety.
    
    Returns AgentOutput with latency_ms populated.
    Returns neutral AgentOutput on timeout or exception.
    """
    with self.tracer.start_as_current_span(
        "agent.compute",
        attributes={
            ATTR_AGENT_ID: self.agent_id,
            "group": self.group,
            ATTR_SYMBOL: context.symbol,
            ATTR_TF: context.timeframe,
        },
    ) as span:
        t0 = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self._compute(context),
                timeout=self._timeout_s,
            )
            latency_ms = (time.monotonic() - t0) * 1000
            self._record_metrics("success", latency_ms)
            return result.model_copy(update={"latency_ms": latency_ms})
        except TimeoutError as exc:
            # ... timeout handling with _neutral()
        except Exception as exc:
            # ... error handling with _neutral()
```

**_llm_generate() audit pattern** (lines 185-253):
```python
async def _llm_generate(
    self,
    context: AIContext,
    prompt: str,
    system: str,
    max_tokens: int,
    timeout: float,
    model: str = "default",
    extra_audit: dict | None = None,
) -> tuple[str | None, str]:
    """Generate LLM response with automatic audit trail.
    
    Wraps self._llm.generate() with auto-injected audit_context so every
    LLM call is captured for model scoring. Agents MUST use this instead of
    calling self._llm.generate() directly.
    
    Returns (response, call_id). call_id is used by agents to publish
    corrective parse_success=False updates via _report_parse_failure().
    """
    call_id = str(uuid4())
    audit_context: dict[str, Any] = {
        "call_id": call_id,
        "called_at": format_iso_ts(datetime.now(UTC)),
        "symbol": context.symbol,
        "signal_id": str(context.signal_id) if context.signal_id else None,
        "group_name": self.group,
        "agent_id": self.agent_id,
        "prompt_version": self.prompt_version,
        "timeframe": context.timeframe,
        "prompt": prompt,
        "succeeded": True,
        "parse_success": True,
    }
    # ... LLM call with audit_context
    return result, call_id
```

**_neutral() fallback pattern** (lines 173-183):
```python
def _neutral(self, error: str, latency_ms: float) -> AgentOutput:
    """Return neutral AgentOutput for error/timeout cases."""
    return AgentOutput(
        agent_id=self.agent_id,
        group=self.group,
        output_type="neutral",
        payload={},
        shadow_only=self.shadow_only,
        latency_ms=latency_ms,
        error=error,
    )
```

**Adapter pattern to implement:**
```python
from pydantic_ai import Agent
from src.core.ai.base_agent import BaseAIAgent
from src.core.ai.context import AIContext
from src.core.ai.output import AgentOutput
from src.intelligence.ai.adapters.agent_deps import AgentDeps

class PydanticAIAdapter(BaseAIAgent):
    """Adapter that wraps pydantic_ai.Agent in BaseAIAgent protocol."""
    
    def __init__(self, pydantic_agent: Agent, **kwargs):
        super().__init__(**kwargs)
        self._pydantic_agent = pydantic_agent
    
    async def _compute(self, context: AIContext) -> AgentOutput:
        """Delegates to Pydantic AI agent, converts result to AgentOutput."""
        deps = self._build_deps(context)
        result = await self._pydantic_agent.run(context, deps=deps)
        return self._to_agent_output(result, context)
    
    def _build_deps(self, context: AIContext) -> AgentDeps:
        """Build dependency container for Pydantic AI run."""
        return AgentDeps(
            signal_context=context,
            llm_chain=self._llm,
            db_pool=None,  # Unused in Skeptic
            memory_client=None,
        )
```

---

### `src/intelligence/ai/adapters/agent_deps.py` (utility, config)

**Analog:** `src/core/ai/context.py` (dataclass pattern)

**Purpose:** Type-safe dependency injection container for Pydantic AI agents.

**TierContext dataclass pattern** (lines 58-59, 64-89):
```python
class TierContext(BaseModel):
    """Base model for tier-specific context (custom types not in schemas.py)."""
    model_config = ConfigDict(frozen=True)

class QuantSignalContext(TierContext):
    """Quantitative signal parameters — the specific trade setup from the aggregator.
    
    Populated from the signal dict produced by the aggregator. Fields here
    are signal-level properties NOT available in pipeline tiers (I1-I6, SMC).
    """
    winner_plugin: str | None = None
    winner_direction: int | None = None
    winner_confidence: float | None = None
    # ... more fields
```

**AgentDeps pattern to implement:**
```python
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
```

---

### `src/intelligence/ai/alpha/skeptic_agent_pydantic.py` (agent, request-response)

**Analog:** `src/intelligence/ai/alpha/skeptic_agent.py`

**Purpose:** Pydantic AI implementation of Skeptic agent, preserves prompt and transfer function, switches transport to NativeOutput.

**SkepticComputeAgent structure pattern** (lines 35-56):
```python
class SkepticComputeAgent(BaseMultiplierAgent):
    """Devil's advocate alpha agent -- predicts signal failure probability.
    
    Per D-03: extends BaseMultiplierAgent, declares output_schema ClassVar.
    Per D-34: returns AgentOutput via _build_multiplier_output.
    Pure compute class -- dispatch layer owns infrastructure.
    """
    output_schema: ClassVar[dict] = {
        "failure_probability": float,
        "confidence": float,
        "risk_factors": list,
        "reasoning": str,
    }
    
    agent_id = "skeptic_v1"
    prompt_version = ACTIVE_VERSION
    group = "alpha"
    tiers_needed = frozenset({Tier.I1, Tier.I4, Tier.I6, Tier.I7, Tier.SMC})
    latency_budget_ms = 120000.0
    shadow_only = False
```

**__init__ pattern** (lines 57-59):
```python
def __init__(self, llm_chain: LLMProviderChain, **kwargs: Any) -> None:
    super().__init__(name="SkepticComputeAgent", **kwargs)
    self._llm = llm_chain
```

**_compute() pattern** (lines 61-109):
```python
async def _compute(self, context: AIContext) -> AgentOutput:
    """Core computation: build prompt -> call LLM -> parse JSON -> transfer function.
    
    Per D-01: full AIContext dump in prompt.
    Per D-04: multiplier = (1.0 - failure_probability) * llm_confidence.
    Per D-06: raw values stored in payload, never overwrites signal_ledger.
    """
    # Build prompt
    prompt = build_skeptic_prompt(context)
    
    # Call LLM via _llm_generate (auto-audit)
    response, call_id = await self._llm_generate(
        context,
        prompt=prompt,
        system=_SYSTEM_MESSAGE,
        max_tokens=500,
        timeout=self.latency_budget_ms / 1000.0,
    )
    
    if not response:
        return self._neutral(error="LLM returned empty response", latency_ms=0.0)
    
    # Parse JSON response
    parsed = self._parse_multiplier_response(response, _validate_skeptic_fields)
    if parsed is None:
        await self._report_parse_failure(call_id)
        return self._neutral(error="JSON parse failed", latency_ms=0.0)
    
    # Apply transfer function
    failure_probability = parsed["failure_probability"]
    llm_confidence = parsed["confidence"]
    multiplier = (1.0 - failure_probability) * llm_confidence
    
    return self._build_multiplier_output(
        context=context,
        multiplier=multiplier,
        confidence=llm_confidence,
        payload={
            "failure_probability": failure_probability,
            "risk_factors": parsed["risk_factors"],
            "reasoning": parsed["reasoning"],
        },
        prompt_version=ACTIVE_VERSION,
    )
```

**Pydantic AI version to implement:**
```python
from pydantic_ai import Agent, NativeOutput
from src.intelligence.ai.adapters.pydantic_ai_adapter import PydanticAIAdapter
from src.intelligence.ai.alpha.skeptic_prompts import SkepticResult, ACTIVE_VERSION

class SkepticComputeAgentPydantic(PydanticAIAdapter):
    """Pydantic AI implementation of Skeptic agent."""
    
    agent_id = "skeptic_v2_pydantic"
    prompt_version = ACTIVE_VERSION
    group = "alpha"
    tiers_needed = frozenset({Tier.I1, Tier.I4, Tier.I6, Tier.I7, Tier.SMC})
    latency_budget_ms = 120000.0
    shadow_only = True  # Start in shadow mode
    
    def __init__(self, llm_chain: LLMProviderChain, **kwargs):
        # Configure Pydantic AI agent with NativeOutput
        pydantic_agent = Agent(
            'ollama:nemotron-3-nano:4b',
            deps_type=AgentDeps,
            output_type=NativeOutput(SkepticResult),
            instructions='Be a skeptical trading analyst...',
        )
        super().__init__(pydantic_agent=pydantic_agent, **kwargs)
        self._llm = llm_chain
    
    def _to_agent_output(self, result, context: AIContext) -> AgentOutput:
        """Convert Pydantic AI result to canonical AgentOutput."""
        # result.output is guaranteed to be SkepticResult (no try/except needed)
        failure_probability = result.output.failure_probability
        llm_confidence = result.output.confidence
        multiplier = (1.0 - failure_probability) * llm_confidence
        
        return self._build_multiplier_output(
            context=context,
            multiplier=multiplier,
            confidence=llm_confidence,
            payload={
                "failure_probability": failure_probability,
                "risk_factors": result.output.risk_factors,
                "reasoning": result.output.reasoning,
            },
            prompt_version=self.prompt_version,
        )
```

---

### `src/intelligence/ai/alpha/skeptic_prompts.py` (modified, utility)

**Analog:** `src/intelligence/ai/alpha/skeptic_prompts.py`

**Purpose:** Add SkepticResult Pydantic model with validators, preserve existing prompts.

**Existing field validator pattern** (lines 103-136):
```python
def _validate_skeptic_fields(data: dict) -> dict[str, Any] | None:
    """Validate and sanitize the parsed skeptic response fields.
    
    Moved here from skeptic_agent.py per D-03: field validators belong in the
    prompts file alongside the prompt content they validate.
    """
    if not isinstance(data, dict):
        return None
    
    fp = data.get("failure_probability")
    conf = data.get("confidence")
    
    if not isinstance(fp, (int, float)) or not isinstance(conf, (int, float)):
        return None
    
    fp = clamp(float(fp), 0.0, 1.0)
    conf = clamp(float(conf), 0.0, 1.0)
    
    risk_factors = data.get("risk_factors", [])
    if not isinstance(risk_factors, list):
        risk_factors = [str(risk_factors)]
    else:
        risk_factors = [str(rf) for rf in risk_factors]
    
    reasoning = data.get("reasoning", "")
    if not isinstance(reasoning, str):
        reasoning = str(reasoning)
    
    return {
        "failure_probability": fp,
        "confidence": conf,
        "risk_factors": risk_factors,
        "reasoning": reasoning,
    }
```

**Pydantic model to add (from 094-PRESERVED.md):**
```python
from pydantic import BaseModel, Field, field_validator

class SkepticResult(BaseModel):
    """Result model for Skeptic agent with NativeOutput enforcement."""
    failure_probability: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    risk_factors: list[str] = Field(default_factory=list)
    reasoning: str = Field(default="", max_length=500)
    
    @field_validator("risk_factors", mode="before")
    @classmethod
    def coerce_to_list(cls, v: object) -> list[str]:
        """Handle LLM output variations: None, single value, or list."""
        if v is None:
            return []
        if not isinstance(v, list):
            return [str(v)]
        return [str(x) for x in v]
```

**Preserve existing:**
- `ACTIVE_VERSION` constant
- `PROMPT_REGISTRY` dict
- `build_skeptic_prompt()` function
- `_validate_skeptic_fields()` function (used by skeptic_v1)

---

### `tests/unit/intelligence/ai/test_skeptic_agent_pydantic.py` (test, validation)

**Analog:** `tests/unit/test_skeptic_agent.py`

**Purpose:** Validate NativeOutput guarantees, confidence calibration, shadow mode behavior.

**Existing test pattern** (lines 15-116):
```python
def test_active_version_in_registry():
    assert ACTIVE_VERSION in PROMPT_REGISTRY

def test_build_prompt_fills_fields(monkeypatch):
    """Verify v1 prompt template has all expected placeholders filled (dict path)."""
    # ... prompt building test

def test_parse_valid_json():
    raw = json.dumps({
        "failure_probability": 0.7,
        "confidence": 0.8,
        "risk_factors": ["weak trend"],
        "reasoning": "test",
    })
    result = parse_llm_json(raw, _validate_skeptic_fields)
    assert result is not None
    assert result["failure_probability"] == 0.7

def test_parse_json_with_preamble():
    """Test brace-counting extract handles prose preamble."""
    raw = "Here is my analysis:\n" + json.dumps({...})
    result = parse_llm_json(raw, _validate_skeptic_fields)
    assert result is not None

def test_parse_invalid_returns_none():
    assert parse_llm_json("not json", _validate_skeptic_fields) is None

def test_validate_clamps_values():
    result = _validate_skeptic_fields({
        "failure_probability": 1.5,
        "confidence": -0.5,
        "risk_factors": "not a list",
        "reasoning": 123,
    })
    assert result is not None
    assert result["failure_probability"] == 1.0  # clamped
    assert result["confidence"] == 0.0  # clamped
```

**Pydantic AI test pattern to implement:**
```python
import pytest
from src.intelligence.ai.alpha.skeptic_agent_pydantic import SkepticComputeAgentPydantic
from src.core.ai.context import AIContext
from src.intelligence.ai.alpha.skeptic_prompts import SkepticResult

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

def test_skeptic_result_coerce_to_list():
    """Test field_validator handles LLM output variations."""
    # None -> []
    assert SkepticResult(risk_factors=None).risk_factors == []
    # Single value -> [str(value)]
    assert SkepticResult(risk_factors="weak trend").risk_factors == ["weak trend"]
    # List -> [str(x) for x in v]
    assert SkepticResult(risk_factors=["a", "b"]).risk_factors == ["a", "b"]
```

---

### `tests/unit/intelligence/ai/test_pydantic_ai_adapter.py` (test, validation)

**Analog:** `tests/unit/test_skeptic_agent.py` (agent testing pattern)

**Purpose:** Validate adapter protocol compliance, dependency injection, error handling.

**Adapter test pattern to implement:**
```python
import pytest
from src.intelligence.ai.adapters.pydantic_ai_adapter import PydanticAIAdapter
from src.intelligence.ai.adapters.agent_deps import AgentDeps
from src.core.ai.context import AIContext
from pydantic_ai import Agent, NativeOutput

@pytest.mark.asyncio
async def test_adapter_implements_base_ai_agent():
    """PydanticAIAdapter must satisfy BaseAIAgent protocol."""
    result_model = type("TestResult", (BaseModel,), {"value": float})
    pydantic_agent = Agent(
        'ollama:nemotron-3-nano:4b',
        deps_type=AgentDeps,
        output_type=NativeOutput(result_model),
    )
    adapter = PydanticAIAdapter(pydantic_agent=pydantic_agent)
    
    # Check protocol compliance
    assert hasattr(adapter, 'agent_id')
    assert hasattr(adapter, 'group')
    assert hasattr(adapter, 'compute')
    assert hasattr(adapter, '_compute')

@pytest.mark.asyncio
async def test_build_deps_constructs_valid_container():
    """AgentDeps factory should inject all required dependencies."""
    adapter = PydanticAIAdapter(pydantic_agent=mock_agent)
    context = AIContext(symbol="ES", timeframe="5m", ...)
    
    deps = adapter._build_deps(context)
    
    assert isinstance(deps, AgentDeps)
    assert deps.signal_context is context
    assert deps.llm_chain is adapter._llm
```

---

### `services/alpha_swarm_agent.py` (modified, service)

**Analog:** `services/alpha_swarm_agent.py`

**Purpose:** Register skeptic_v2_pydantic alongside skeptic_v1 for shadow validation.

**Agent registration pattern** (lines 162-171):
```python
async def _setup(self) -> None:
    """Wire infrastructure beyond BaseGroupService defaults.
    
    Plan 80-07: construct all four BaseMultiplierAgent instances + semaphore.
    """
    await super()._setup()
    
    # Agents require _llm_chain which is wired by super()._setup() — construct here.
    self._agents = [
        SkepticComputeAgent(llm_chain=self._llm_chain),
        CorrelationComputeAgent(llm_chain=self._llm_chain),
        RegimeCoherenceComputeAgent(llm_chain=self._llm_chain),
        CounterfactualComputeAgent(llm_chain=self._llm_chain),
    ]
    # MLScorerMultiplierAgent: no LLM chain; uses pool for ModelRegistry.
    self._agents.append(MLScorerMultiplierAgent(pool=self._pool))
    await self._agents[-1]._setup_models()
    
    self._semaphore = asyncio.Semaphore(self.settings.SWARM_MAX_CONCURRENT_CALLS)
    
    # Shadow enrollment
    if self._pool is not None:
        await self._shadow_registry_ensure_agents(self._agents)
```

**Modification pattern:**
```python
from src.intelligence.ai.alpha.skeptic_agent_pydantic import SkepticComputeAgentPydantic

async def _setup(self) -> None:
    await super()._setup()
    
    # Register both v1 (legacy) and v2_pydantic (shadow) for A/B testing
    self._agents = [
        SkepticComputeAgent(llm_chain=self._llm_chain),  # Existing live agent
        SkepticComputeAgentPydantic(llm_chain=self._llm_chain),  # New shadow agent
        CorrelationComputeAgent(llm_chain=self._llm_chain),
        RegimeCoherenceComputeAgent(llm_chain=self._llm_chain),
        CounterfactualComputeAgent(llm_chain=self._llm_chain),
    ]
    self._agents.append(MLScorerMultiplierAgent(pool=self._pool))
    await self._agents[-1]._setup_models()
    
    self._semaphore = asyncio.Semaphore(self.settings.SWARM_MAX_CONCURRENT_CALLS)
    
    # Shadow enrollment — skeptic_v2_pydantic will be enrolled with is_shadow=True
    if self._pool is not None:
        await self._shadow_registry_ensure_agents(self._agents)
```

**_SWARM_AGENT_TO_TRANSFORM mapping update** (lines 74-80):
```python
_SWARM_AGENT_TO_TRANSFORM: dict[str, tuple[str, int]] = {
    "skeptic_v1": ("swarm_skeptic", 6),
    "skeptic_v2_pydantic": ("swarm_skeptic", 6),  # Add this line
    "correlation_v1": ("swarm_correlation", 6),
    "regime_coherence_v1": ("swarm_regime_coherence", 6),
    "counterfactual_v1": ("swarm_counterfactual", 6),
    "ml_scorer_v1": ("swarm_ml_scorer", 6),
}
```

---

### `requirements.txt` (modified, config)

**Analog:** `requirements.txt`

**Purpose:** Add pydantic-ai dependency.

**Current Pydantic versions:**
```
pydantic-settings>=2.12.0
pydantic>=2.12.0
```

**Addition to implement:**
```
pydantic-ai>=0.0.1  # 2026 latest, use actual version when available
```

---

## Shared Patterns

### Agent Class Attributes (All Agents)
**Source:** `src/core/ai/base_agent.py` + `src/intelligence/ai/alpha/skeptic_agent.py`
**Apply to:** All new agent classes

Every agent must declare these class attributes:
```python
agent_id: str = "name_version"  # e.g., "skeptic_v2_pydantic"
prompt_version: str = ACTIVE_VERSION
group: str = "alpha"  # or "narrative", "risk"
tiers_needed: frozenset[Tier] = frozenset({Tier.I1, Tier.I4, ...})
latency_budget_ms: float = 120000.0
shadow_only: bool = True  # Start in shadow mode
```

### LLM Audit Trail (All LLM Calls)
**Source:** `src/core/ai/base_agent.py` lines 185-253
**Apply to:** All agents using LLM

Always use `self._llm_generate()` instead of `self._llm.generate()`:
```python
response, call_id = await self._llm_generate(
    context,
    prompt=prompt,
    system=_SYSTEM_MESSAGE,
    max_tokens=500,
    timeout=self.latency_budget_ms / 1000.0,
)
# Auto-injects: call_id, called_at, symbol, signal_id, agent_id, prompt_version
```

### Neutral Output on Error (All Agents)
**Source:** `src/core/ai/base_agent.py` lines 173-183
**Apply to:** All agent error handling

Return neutral output instead of raising exceptions:
```python
if not response:
    return self._neutral(error="LLM returned empty response", latency_ms=0.0)

if parsed is None:
    await self._report_parse_failure(call_id)
    return self._neutral(error="JSON parse failed", latency_ms=0.0)
```

### Multiplier Output Construction (Multiplier Agents)
**Source:** `src/core/ai/multiplier_agent.py` lines 44-68
**Apply to:** All multiplier-output agents (Skeptic, Correlation, etc.)

Use canonical `_build_multiplier_output()` method:
```python
return self._build_multiplier_output(
    context=context,
    multiplier=multiplier,  # Clamped to [0.0, 2.0] automatically
    confidence=confidence,  # Clamped to [0.0, 1.0] automatically
    payload={
        "field1": value1,
        "field2": value2,
    },
    prompt_version=ACTIVE_VERSION,
)
```

### Field Validator Pattern (Pydantic Models)
**Source:** `src/intelligence/ai/alpha/skeptic_prompts.py` lines 103-136
**Apply to:** All result models for Pydantic AI agents

Use `@field_validator(mode="before")` for robust list coercion:
```python
from pydantic import BaseModel, Field, field_validator

class MyResult(BaseModel):
    items: list[str] = Field(default_factory=list)
    
    @field_validator("items", mode="before")
    @classmethod
    def coerce_to_list(cls, v: object) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            return [str(v)]
        return [str(x) for x in v]
```

### System Message Convention (All Agents)
**Source:** `src/intelligence/ai/alpha/skeptic_agent.py` lines 25-32
**Apply to:** All agents using LLM

Consistent system message for JSON output:
```python
_SYSTEM_MESSAGE = (
    "OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE. "
    "Your entire response must be a single JSON object starting with { and ending with }. "
    "Begin your response with { and end with }. No prose before or after the JSON."
)
```

### Service Registration (All Swarm Agents)
**Source:** `services/alpha_swarm_agent.py` lines 162-177
**Apply to:** All agents added to AlphaSwarmComputeAgent

1. Import agent class
2. Add to `self._agents` list in `_setup()`
3. Add to `_SWARM_AGENT_TO_TRANSFORM` mapping
4. Shadow enrollment is automatic via `_shadow_registry_ensure_agents()`

---

## No Analog Found

None — all files have clear analogs in the existing codebase.

---

## Metadata

**Analog search scope:**
- `/home/bg/dev/indicagent/src/core/ai/*.py` — base agent and infrastructure
- `/home/bg/dev/indicagent/src/intelligence/ai/alpha/*.py` — existing multiplier agents
- `/home/bg/dev/indicagent/services/alpha_swarm_agent.py` — service registration
- `/home/bg/dev/indicagent/tests/unit/test_skeptic*.py` — test patterns
- `/home/bg/dev/indicagent/src/core/ai/context.py` — dataclass patterns
- `/home/bg/dev/indicagent/src/core/ai/multiplier_agent.py` — multiplier agent base

**Files scanned:** 12
**Pattern extraction date:** 2026-05-20

**Key insights:**
1. **Adapter pattern preserves infrastructure** — PydanticAIAdapter wraps pydantic_ai.Agent, implements BaseAIAgent protocol
2. **Shadow validation built-in** — Register both v1 and v2_pydantic, compare via `llm_calls` query
3. **Result models are data contracts** — SkepticResult, CorrelationResult, etc. work across frameworks
4. **Zero parse failure guarantee** — NativeOutput enforces schema at generation time via llama.cpp grammar constraints
5. **Incremental migration** — One agent at a time, no big-bang rewrite
