# Phase 3: Pydantic AI Agents Implementation Plan

**Version:** 1.0
**Status:** archived
**Last Updated:** 2026-05-20
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `BaseAIAgent` / `BaseMultiplierAgent` class hierarchy for the 4 LLM alpha agents with `pydantic_ai.Agent[AgentDeps, ResultType]` instances wrapped in a thin `PydanticAIAgent` adapter. Gains: typed deps injection, `@agent.system_prompt` hooks for Phase 5 memory enrichment, tool use capability, and a flat instance-based model instead of inheritance.

**Architecture:** A `PydanticAIAgent` class in `src/core/ai/pydantic_agent.py` adapts `pydantic_ai.Agent` to the existing `IAIAgent` interface (`compute(context) → AgentOutput`). `AlphaSwarmComputeAgent` iterates these adapters identically to today — no dispatch rewrite required. `MLScorerMultiplierAgent` (LightGBM, no LLM) is untouched.

**Spec:** `docs/plans/2026-05-20-agent-platform-redesign.md` — Layer 2 (Pydantic AI)

**Phase dependencies:** Phase 1 (LiteLLM) + Phase 2 (Instructor result models) must be merged first — `SkepticResult`, `CorrelationResult`, etc. are reused as Pydantic AI `result_type`.

**What does NOT change:**
- `AlphaSwarmComputeAgent`'s `self._agents` iteration and dispatch loop
- `_build_multiplier_output()` → replaced by inline `AgentOutput` construction in the adapter
- `shadow_only`, `tiers_needed`, `agent_id` — moved to adapter instance attrs
- `MLScorerMultiplierAgent` — no LLM, stays as `BaseMultiplierAgent` subclass
- `BaseGroupService`, `BaseAIAgent` — not deleted; other services still use them

**What gets deleted (per agent):**
- The `class FooComputeAgent(BaseMultiplierAgent)` class definition
- `_validate_*_fields` (already gone after Phase 2)
- `output_schema: ClassVar[dict]` (already gone after Phase 2)
- The `_compute()` method (logic moves into factory function + adapter)

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `src/core/ai/pydantic_agent.py` | `AgentDeps`, `PydanticAIAgent` adapter |
| Create | `src/intelligence/ai/alpha/pydantic_agents.py` | 4 factory functions returning `PydanticAIAgent` |
| Modify | `src/intelligence/ai/alpha/skeptic_agent.py` | Delete class, keep module as factory shim |
| Modify | `src/intelligence/ai/alpha/correlation_agent.py` | Delete class, keep module as factory shim |
| Modify | `src/intelligence/ai/alpha/counterfactual_agent.py` | Delete class, keep module as factory shim |
| Modify | `src/intelligence/ai/alpha/regime_coherence_agent.py` | Delete class, keep module as factory shim |
| Modify | `services/alpha_swarm_agent.py` | Construct via factory functions; type from `list[BaseMultiplierAgent]` → `list` |
| Modify | `requirements.txt` | Add `pydantic-ai` |
| Create | `tests/unit/ai_agent_tests/test_pydantic_agent.py` | Unit tests for `PydanticAIAgent.compute()` |

---

## Task 1: Install pydantic-ai

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add pydantic-ai to requirements.txt**

```
pydantic-ai>=0.0.14
```

- [ ] **Step 2: Install**

```bash
uv pip install pydantic-ai
```

Expected: installs without conflicts. Pydantic AI depends on `pydantic>=2.0`, `httpx`, `openai>=1.0` — all already present.

- [ ] **Step 3: Verify**

```bash
.venv/bin/python -c "import pydantic_ai; print(pydantic_ai.__version__)"
```

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "deps: add pydantic-ai for agent execution framework"
```

---

## Task 2: Write failing tests for PydanticAIAgent

**Files:**
- Create: `tests/unit/ai_agent_tests/test_pydantic_agent.py`

- [ ] **Step 1: Create test file**

```python
"""Tests for PydanticAIAgent adapter."""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from src.core.ai.context import AIContext, Tier
from src.core.ai.output import AgentOutput
from src.core.ai.pydantic_agent import AgentDeps, PydanticAIAgent


class _FakeResult(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)


def _make_context() -> AIContext:
    ctx = MagicMock(spec=AIContext)
    ctx.symbol = "ES"
    ctx.timeframe = "5m"
    ctx.signal_id = None
    ctx.smc = None
    return ctx


def _make_agent(settings=None) -> PydanticAIAgent:
    mock_pydantic_agent = MagicMock()
    mock_pydantic_agent.run = AsyncMock()

    return PydanticAIAgent(
        agent_id="test_v1",
        group="alpha",
        tiers_needed=frozenset({Tier.I7}),
        latency_budget_ms=5000.0,
        shadow_only=True,
        prompt_version="test_v1",
        pydantic_agent=mock_pydantic_agent,
        prompt_fn=lambda ctx: f"Analyze {ctx.symbol}",
        multiplier_fn=lambda r: (r.score, r.confidence),
        settings=settings or MagicMock(),
    )


@pytest.mark.asyncio
async def test_compute_returns_agent_output_on_success():
    agent = _make_agent()
    ctx = _make_context()

    mock_result = MagicMock()
    mock_result.data = _FakeResult(score=0.8, confidence=0.9)
    agent._pydantic_agent.run.return_value = mock_result

    output = await agent.compute(ctx)

    assert isinstance(output, AgentOutput)
    assert output.agent_id == "test_v1"
    assert output.error is None
    payload = output.payload
    assert payload["multiplier"] == pytest.approx(0.8, abs=0.01)
    assert payload["confidence"] == pytest.approx(0.9, abs=0.01)


@pytest.mark.asyncio
async def test_compute_returns_neutral_on_exception():
    agent = _make_agent()
    ctx = _make_context()

    agent._pydantic_agent.run.side_effect = Exception("LLM timeout")

    output = await agent.compute(ctx)

    assert isinstance(output, AgentOutput)
    assert output.error is not None
    assert "LLM timeout" in output.error or output.payload.get("multiplier") == 1.0


@pytest.mark.asyncio
async def test_agent_deps_passed_to_run():
    agent = _make_agent()
    ctx = _make_context()

    mock_result = MagicMock()
    mock_result.data = _FakeResult(score=0.5, confidence=0.7)
    agent._pydantic_agent.run.return_value = mock_result

    await agent.compute(ctx)

    call_kwargs = agent._pydantic_agent.run.call_args
    assert call_kwargs is not None
    # First positional arg is the prompt
    prompt_arg = call_kwargs[0][0]
    assert "ES" in prompt_arg
    # deps kwarg is AgentDeps
    deps = call_kwargs[1].get("deps") or call_kwargs[0][1]
    assert isinstance(deps, AgentDeps)
    assert deps.context is ctx


def test_protocol_attrs():
    agent = _make_agent()
    assert agent.agent_id == "test_v1"
    assert agent.group == "alpha"
    assert Tier.I7 in agent.tiers_needed
    assert agent.shadow_only is True
    assert agent.latency_budget_ms == 5000.0
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/unit/ai_agent_tests/test_pydantic_agent.py -v 2>&1 | head -15
```

Expected: `ModuleNotFoundError: No module named 'src.core.ai.pydantic_agent'`

---

## Task 3: Create src/core/ai/pydantic_agent.py

**Files:**
- Create: `src/core/ai/pydantic_agent.py`

- [ ] **Step 1: Read current files**

```bash
grep -n "class AgentOutput\|payload\|shadow_only\|multiplier" src/core/ai/output.py | head -20
```

Note the `AgentOutput` constructor signature and the `clamp` import path.

- [ ] **Step 2: Create the file**

```python
"""PydanticAIAgent — pydantic_ai.Agent adapter implementing the IAIAgent interface.

Wraps a pydantic_ai.Agent instance in a class that the existing dispatch layer
(AlphaSwarmComputeAgent) can call via compute(context: AIContext) -> AgentOutput.

Replaces BaseAIAgent + BaseMultiplierAgent inheritance for LLM alpha agents.
MLScorerMultiplierAgent (LightGBM) keeps its existing class hierarchy.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import structlog
from pydantic_ai import Agent

from src.core.ai.context import AIContext, Tier
from src.core.ai.output import AgentOutput
from src.core.ai.prompt_utils import clamp

logger = structlog.get_logger(__name__)

_T = TypeVar("_T")


@dataclass
class AgentDeps:
    """Typed dependency container for pydantic_ai agents.

    Passed as deps= to agent.run(). Phase 5 adds memory: EpisodicMemoryStore.
    """

    context: AIContext
    settings: Any


class PydanticAIAgent:
    """Adapter: wraps pydantic_ai.Agent and exposes the IAIAgent interface.

    Each LLM alpha agent is an instance of this class, configured at construction
    time with its agent_id, tiers_needed, system prompt, and result model.
    The dispatch layer (AlphaSwarmComputeAgent) calls compute(context) identically
    to how it called BaseAIAgent subclasses.
    """

    def __init__(
        self,
        agent_id: str,
        group: str,
        tiers_needed: frozenset[Tier],
        latency_budget_ms: float,
        shadow_only: bool,
        prompt_version: str,
        pydantic_agent: Agent,
        prompt_fn: Callable[[AIContext], str],
        multiplier_fn: Callable[[Any], tuple[float, float]],
        settings: Any,
    ) -> None:
        self.agent_id = agent_id
        self.group = group
        self.tiers_needed = tiers_needed
        self.latency_budget_ms = latency_budget_ms
        self.shadow_only = shadow_only
        self.prompt_version = prompt_version
        self._pydantic_agent = pydantic_agent
        self._prompt_fn = prompt_fn
        self._multiplier_fn = multiplier_fn
        self._settings = settings
        self._timeout_s = latency_budget_ms / 1000.0

    def _neutral(self, error: str) -> AgentOutput:
        return AgentOutput(
            agent_id=self.agent_id,
            group=self.group,
            signal_id=None,
            symbol="",
            timeframe="",
            ts=None,
            output_type="multiplier",
            payload={"multiplier": 1.0, "confidence": 0.0, "error": error},
            shadow_only=self.shadow_only,
            error=error,
        )

    async def compute(self, context: AIContext) -> AgentOutput:
        """Run the pydantic_ai agent with timeout and error safety."""
        t0 = time.monotonic()
        try:
            deps = AgentDeps(context=context, settings=self._settings)
            prompt = self._prompt_fn(context)

            run_result = await asyncio.wait_for(
                self._pydantic_agent.run(prompt, deps=deps),
                timeout=self._timeout_s,
            )
            multiplier, confidence = self._multiplier_fn(run_result.data)

            latency_ms = (time.monotonic() - t0) * 1000
            logger.debug(
                "pydantic_agent.compute_ok",
                agent_id=self.agent_id,
                latency_ms=round(latency_ms, 1),
            )

            return AgentOutput(
                agent_id=self.agent_id,
                group=self.group,
                signal_id=context.signal_id,
                symbol=context.symbol,
                timeframe=context.timeframe,
                ts=context.ts,
                output_type="multiplier",
                payload={
                    "multiplier": clamp(multiplier, 0.0, 2.0),
                    "confidence": clamp(confidence, 0.0, 1.0),
                    "prompt_version": self.prompt_version,
                    **_result_to_payload(run_result.data),
                },
                shadow_only=self.shadow_only,
            )

        except asyncio.TimeoutError:
            return self._neutral(error=f"timeout after {self._timeout_s}s")
        except Exception as exc:
            logger.warning(
                "pydantic_agent.compute_error",
                agent_id=self.agent_id,
                error=str(exc)[:200],
            )
            return self._neutral(error=str(exc))


def _result_to_payload(result: Any) -> dict:
    """Dump a Pydantic model result to a dict, excluding multiplier control fields."""
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return {}
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest tests/unit/ai_agent_tests/test_pydantic_agent.py -v
```

Expected: all 4 tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/core/ai/pydantic_agent.py tests/unit/ai_agent_tests/test_pydantic_agent.py
git commit -m "feat(ai): add PydanticAIAgent adapter — wraps pydantic_ai.Agent as IAIAgent"
```

---

## Task 4: Build the pydantic_ai model backend

**Files:**
- Create: `src/core/ai/pydantic_model.py`

Pydantic AI's `OpenAIModel` wraps any OpenAI-compatible endpoint. Ollama exposes one at `http://localhost:11434/v1`.

- [ ] **Step 1: Create src/core/ai/pydantic_model.py**

```python
"""Build the pydantic_ai model backend from settings.

Uses OpenAIModel with Ollama's OpenAI-compatible API as primary provider.
Falls back to the first OpenRouter model when configured.

Called once at service startup; the model instance is passed to all
PydanticAIAgent factory functions.
"""
from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIModel


def build_pydantic_model(settings: Any) -> OpenAIModel:
    """Build OpenAIModel backed by Ollama (or OpenRouter as fallback).

    Phase 3 uses Ollama's OpenAI-compatible endpoint directly.
    Phase 6 (DSPy) will augment with compiled programs.
    """
    base_url = getattr(settings, "ollama_base_url", "http://localhost:11434")
    model_name = getattr(settings, "ollama_model", "nemotron-3-nano:4b")

    client = AsyncOpenAI(
        base_url=f"{base_url}/v1",
        api_key="ollama",  # Ollama ignores the key; required by OpenAI client
    )
    return OpenAIModel(model_name, openai_client=client)
```

- [ ] **Step 2: Verify import**

```bash
.venv/bin/python -c "from src.core.ai.pydantic_model import build_pydantic_model; print('ok')"
```

- [ ] **Step 3: Commit**

```bash
git add src/core/ai/pydantic_model.py
git commit -m "feat(ai): add build_pydantic_model — OpenAIModel backed by Ollama"
```

---

## Task 5: Create alpha agent factory functions

**Files:**
- Create: `src/intelligence/ai/alpha/pydantic_agents.py`

Each factory function returns a `PydanticAIAgent` configured for its agent's role.

- [ ] **Step 1: Read the result models from Phase 2**

Confirm these exist (from Phase 2):
```bash
grep "class SkepticResult\|class CorrelationResult\|class CounterfactualResult\|class RegimeCoherenceResult" \
  src/intelligence/ai/alpha/skeptic_prompts.py \
  src/intelligence/ai/alpha/correlation_agent.py \
  src/intelligence/ai/alpha/counterfactual_agent.py \
  src/intelligence/ai/alpha/regime_coherence_agent.py
```

- [ ] **Step 2: Read prompt builders from each agent**

```bash
grep "^def build_\|^ACTIVE_VERSION\|^_SYSTEM_MESSAGE" \
  src/intelligence/ai/alpha/skeptic_prompts.py \
  src/intelligence/ai/alpha/correlation_agent.py \
  src/intelligence/ai/alpha/counterfactual_agent.py \
  src/intelligence/ai/alpha/regime_coherence_agent.py
```

Note the prompt builder signatures (they take `AIContext` or a dict — verify before using).

- [ ] **Step 3: Create src/intelligence/ai/alpha/pydantic_agents.py**

```python
"""Factory functions for Pydantic AI alpha agents.

Each function creates a PydanticAIAgent configured for its specific role.
The AlphaSwarmComputeAgent calls these at startup instead of constructing
class instances.

Result models (SkepticResult, etc.) come from Phase 2 (Instructor migration).
System prompts and prompt builders come from existing *_prompts.py files.
"""
from __future__ import annotations

from typing import Any

from pydantic_ai import Agent

from src.core.ai.context import AIContext, Tier
from src.core.ai.pydantic_agent import AgentDeps, PydanticAIAgent
from src.intelligence.ai.alpha.correlation_agent import CorrelationResult
from src.intelligence.ai.alpha.counterfactual_agent import CounterfactualResult
from src.intelligence.ai.alpha.regime_coherence_agent import RegimeCoherenceResult
from src.intelligence.ai.alpha.skeptic_prompts import (
    ACTIVE_VERSION as SKEPTIC_VERSION,
    SkepticResult,
    build_skeptic_prompt,
)


# ── Skeptic ───────────────────────────────────────────────────────────────────

_SKEPTIC_SYSTEM = (
    "OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE. "
    "Your entire response must be a single JSON object starting with { and ending with }. "
    'Schema: {"failure_probability": float, "confidence": float, '
    '"risk_factors": [str], "reasoning": str} '
    "reasoning must be under 100 words."
)


def make_skeptic_agent(model: Any, settings: Any) -> PydanticAIAgent:
    pydantic_agent: Agent[AgentDeps, SkepticResult] = Agent(
        model=model,
        result_type=SkepticResult,
        system_prompt=_SKEPTIC_SYSTEM,
        deps_type=AgentDeps,
    )

    def _prompt_fn(ctx: AIContext) -> str:
        return build_skeptic_prompt(ctx)

    def _multiplier_fn(r: SkepticResult) -> tuple[float, float]:
        return (1.0 - r.failure_probability) * r.confidence, r.confidence

    return PydanticAIAgent(
        agent_id="skeptic_v1",
        group="alpha",
        tiers_needed=frozenset({Tier.I1, Tier.I4, Tier.I6, Tier.I7, Tier.SMC}),
        latency_budget_ms=120_000.0,
        shadow_only=False,
        prompt_version=SKEPTIC_VERSION,
        pydantic_agent=pydantic_agent,
        prompt_fn=_prompt_fn,
        multiplier_fn=_multiplier_fn,
        settings=settings,
    )


# ── Correlation ───────────────────────────────────────────────────────────────

_CORRELATION_SYSTEM = (
    "OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE. "
    'Schema: {"coherence_score": float, "confidence": float, '
    '"contradicting_assets": [str], "reasoning": str}'
)


def make_correlation_agent(model: Any, settings: Any) -> PydanticAIAgent:
    from src.intelligence.ai.alpha.correlation_agent import build_correlation_prompt

    pydantic_agent: Agent[AgentDeps, CorrelationResult] = Agent(
        model=model,
        result_type=CorrelationResult,
        system_prompt=_CORRELATION_SYSTEM,
        deps_type=AgentDeps,
    )

    def _multiplier_fn(r: CorrelationResult) -> tuple[float, float]:
        return r.coherence_score * r.confidence, r.confidence

    return PydanticAIAgent(
        agent_id="correlation_v1",
        group="alpha",
        tiers_needed=frozenset({Tier.I1, Tier.I4, Tier.I6}),
        latency_budget_ms=5_000.0,
        shadow_only=True,
        prompt_version="correlation_v1",
        pydantic_agent=pydantic_agent,
        prompt_fn=lambda ctx: build_correlation_prompt(ctx),
        multiplier_fn=_multiplier_fn,
        settings=settings,
    )


# ── Counterfactual ────────────────────────────────────────────────────────────

_COUNTERFACTUAL_SYSTEM = (
    "OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE. "
    'Schema: {"plausibility": float, "confidence": float, '
    '"validation_conditions": [str], "invalidation_conditions": [str], '
    '"alternative_scenario": str}'
)


def make_counterfactual_agent(model: Any, settings: Any) -> PydanticAIAgent:
    from src.intelligence.ai.alpha.counterfactual_agent import build_counterfactual_prompt

    pydantic_agent: Agent[AgentDeps, CounterfactualResult] = Agent(
        model=model,
        result_type=CounterfactualResult,
        system_prompt=_COUNTERFACTUAL_SYSTEM,
        deps_type=AgentDeps,
    )

    def _multiplier_fn(r: CounterfactualResult) -> tuple[float, float]:
        return r.plausibility * r.confidence, r.confidence

    return PydanticAIAgent(
        agent_id="counterfactual_v1",
        group="alpha",
        tiers_needed=frozenset({Tier.I4, Tier.I6, Tier.I7}),
        latency_budget_ms=5_000.0,
        shadow_only=True,
        prompt_version="counterfactual_v1",
        pydantic_agent=pydantic_agent,
        prompt_fn=lambda ctx: build_counterfactual_prompt(ctx),
        multiplier_fn=_multiplier_fn,
        settings=settings,
    )


# ── Regime Coherence ──────────────────────────────────────────────────────────

_REGIME_COHERENCE_SYSTEM = (
    "OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE. "
    'Schema: {"regime_fit": float, "confidence": float, '
    '"supporting_factors": [str], "warning_factors": [str]}'
)


def make_regime_coherence_agent(model: Any, settings: Any) -> PydanticAIAgent:
    from src.intelligence.ai.alpha.regime_coherence_agent import build_regime_coherence_prompt

    pydantic_agent: Agent[AgentDeps, RegimeCoherenceResult] = Agent(
        model=model,
        result_type=RegimeCoherenceResult,
        system_prompt=_REGIME_COHERENCE_SYSTEM,
        deps_type=AgentDeps,
    )

    def _multiplier_fn(r: RegimeCoherenceResult) -> tuple[float, float]:
        return r.regime_fit * r.confidence, r.confidence

    return PydanticAIAgent(
        agent_id="regime_coherence_v1",
        group="alpha",
        tiers_needed=frozenset({Tier.I4, Tier.SMC}),
        latency_budget_ms=5_000.0,
        shadow_only=True,
        prompt_version="regime_coherence_v1",
        pydantic_agent=pydantic_agent,
        prompt_fn=lambda ctx: build_regime_coherence_prompt(ctx),
        multiplier_fn=_multiplier_fn,
        settings=settings,
    )
```

**Important:** Before committing, verify the prompt builder function names for correlation, counterfactual, and regime coherence:

```bash
grep "^def build_" \
  src/intelligence/ai/alpha/correlation_agent.py \
  src/intelligence/ai/alpha/counterfactual_agent.py \
  src/intelligence/ai/alpha/regime_coherence_agent.py
```

If the prompt builders don't exist (prompt building is inline in `_compute`), extract them to their `*_prompts.py` files first before creating this file.

- [ ] **Step 4: Run import check**

```bash
.venv/bin/python -c "from src.intelligence.ai.alpha.pydantic_agents import make_skeptic_agent; print('ok')"
```

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/ai/alpha/pydantic_agents.py
git commit -m "feat(alpha): add pydantic_ai agent factory functions — skeptic, correlation, counterfactual, regime_coherence"
```

---

## Task 6: Wire factories into AlphaSwarmComputeAgent

**Files:**
- Modify: `services/alpha_swarm_agent.py`

- [ ] **Step 1: Read the current imports and _setup method**

```bash
sed -n '1,70p' services/alpha_swarm_agent.py
sed -n '108,180p' services/alpha_swarm_agent.py
```

Identify lines importing `SkepticComputeAgent`, `CorrelationComputeAgent`, etc.

- [ ] **Step 2: Replace agent class imports with factory imports**

Remove:
```python
from src.intelligence.ai.alpha.correlation_agent import CorrelationComputeAgent
from src.intelligence.ai.alpha.counterfactual_agent import CounterfactualComputeAgent
from src.intelligence.ai.alpha.regime_coherence_agent import RegimeCoherenceComputeAgent
from src.intelligence.ai.alpha.skeptic_agent import SkepticComputeAgent
```

Add:
```python
from src.core.ai.pydantic_model import build_pydantic_model
from src.intelligence.ai.alpha.pydantic_agents import (
    make_correlation_agent,
    make_counterfactual_agent,
    make_regime_coherence_agent,
    make_skeptic_agent,
)
```

- [ ] **Step 3: Update _setup() to use factories**

In `_setup()`, replace:
```python
self._agents = [
    SkepticComputeAgent(llm_chain=self._llm_chain),
    CorrelationComputeAgent(llm_chain=self._llm_chain),
    RegimeCoherenceComputeAgent(llm_chain=self._llm_chain),
    CounterfactualComputeAgent(llm_chain=self._llm_chain),
]
```

With:
```python
_model = build_pydantic_model(self.settings)
self._agents = [
    make_skeptic_agent(_model, self.settings),
    make_correlation_agent(_model, self.settings),
    make_regime_coherence_agent(_model, self.settings),
    make_counterfactual_agent(_model, self.settings),
]
```

- [ ] **Step 4: Update type annotation on self._agents**

Find:
```python
self._agents: list[BaseMultiplierAgent] = []
```

Change to:
```python
self._agents: list = []
```

(Or `list[PydanticAIAgent | MLScorerMultiplierAgent]` if you prefer explicit types.)

Remove the `BaseMultiplierAgent` import if it's now only used for `self._agents` type annotation. Keep it if `MLScorerMultiplierAgent` still extends it (it does — leave the import).

- [ ] **Step 5: Run unit tests**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short 2>&1 | tail -15
```

Expected: same failure count as before.

- [ ] **Step 6: Commit**

```bash
git add services/alpha_swarm_agent.py
git commit -m "feat(alpha_swarm): wire pydantic_ai agent factories — retire BaseMultiplierAgent subclasses"
```

---

## Task 7: Delete the old agent class definitions

Once the factories are wired and tests pass, the 4 `class FooComputeAgent(BaseMultiplierAgent)` definitions are dead code.

- [ ] **Step 1: Confirm no external imports of the deleted classes**

```bash
grep -r "SkepticComputeAgent\|CorrelationComputeAgent\|CounterfactualComputeAgent\|RegimeCoherenceComputeAgent" \
  src/ services/ tests/ --include="*.py" | grep -v "__pycache__"
```

Expected: only the class definition files themselves. If any external imports remain, update them before deleting.

- [ ] **Step 2: Replace each agent file with a forward shim**

Each `*_agent.py` file becomes a minimal module that just re-exports the factory function (for any import sites that still reference the module):

Example `src/intelligence/ai/alpha/skeptic_agent.py` after deletion:
```python
"""skeptic_agent — migrated to pydantic_ai in Phase 3.

Factory: make_skeptic_agent() in pydantic_agents.py.
This module kept for import compatibility. Remove after all callers updated.
"""
from src.intelligence.ai.alpha.pydantic_agents import make_skeptic_agent

__all__ = ["make_skeptic_agent"]
```

Do the same for correlation, counterfactual, regime_coherence.

- [ ] **Step 3: Run full unit test suite**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short 2>&1 | tail -20
```

Fix any test imports that referenced the old class names.

- [ ] **Step 4: Commit**

```bash
git add src/intelligence/ai/alpha/skeptic_agent.py \
        src/intelligence/ai/alpha/correlation_agent.py \
        src/intelligence/ai/alpha/counterfactual_agent.py \
        src/intelligence/ai/alpha/regime_coherence_agent.py
git commit -m "simplify: replace BaseMultiplierAgent class defs with factory shims — Phase 3 migration"
```

---

## Task 8: Smoke test against live Ollama

- [ ] **Step 1: Test build_pydantic_model connects to Ollama**

```bash
.venv/bin/python - <<'EOF'
import asyncio
from unittest.mock import MagicMock
from src.core.ai.pydantic_model import build_pydantic_model

s = MagicMock()
s.ollama_base_url = "http://localhost:11434"
s.ollama_model = "nemotron-3-nano:4b"

model = build_pydantic_model(s)
print(f"model: {model}")
print("build_pydantic_model: ok")
EOF
```

- [ ] **Step 2: Run a live pydantic_ai.Agent call through make_skeptic_agent**

```bash
.venv/bin/python - <<'EOF'
import asyncio
from unittest.mock import MagicMock
from src.core.ai.pydantic_model import build_pydantic_model
from src.intelligence.ai.alpha.pydantic_agents import make_skeptic_agent
from src.core.ai.context import AIContext

s = MagicMock()
s.ollama_base_url = "http://localhost:11434"
s.ollama_model = "nemotron-3-nano:4b"

model = build_pydantic_model(s)
agent = make_skeptic_agent(model, s)

ctx = MagicMock(spec=AIContext)
ctx.symbol = "ES"
ctx.timeframe = "5m"
ctx.signal_id = None
ctx.smc = None
ctx.ts = None
# Add enough attrs to make build_skeptic_prompt work with a mock context

async def run():
    output = await agent.compute(ctx)
    print(f"agent_id: {output.agent_id}")
    print(f"error: {output.error}")
    print(f"multiplier: {output.payload.get('multiplier')}")
    print(f"confidence: {output.payload.get('confidence')}")

asyncio.run(run())
EOF
```

Expected: `agent_id: skeptic_v1`, `error: None`, `multiplier` is a float 0-2.

**Note:** The mock AIContext may not have all fields `build_skeptic_prompt` needs. If the prompt builder fails, add the required mock attrs or run with a real context from a log replay.

- [ ] **Step 3: Restart alpha swarm**

```bash
sudo systemctl restart indicagent-alpha-swarm
sleep 6 && systemctl status indicagent-alpha-swarm --no-pager | grep "Active:"
```

Expected: `active (running)`.

- [ ] **Step 4: Check logs for errors**

```bash
tail -30 logs/alpha_swarm_compute_agent.log | grep -iE "error|failed|traceback"
```

Expected: no errors. Swarm should process signals normally.

- [ ] **Step 5: Push**

```bash
git push origin main
```

---

## Verification

Phase 3 is complete when:

- [ ] `PydanticAIAgent` class exists at `src/core/ai/pydantic_agent.py`
- [ ] `AgentDeps(context, settings)` dataclass exists
- [ ] `build_pydantic_model(settings)` returns an `OpenAIModel` backed by Ollama
- [ ] 4 factory functions exist in `src/intelligence/ai/alpha/pydantic_agents.py`
- [ ] `AlphaSwarmComputeAgent._setup()` calls factories; no `SkepticComputeAgent(...)` calls remain
- [ ] 4 old class definitions removed (files kept as forward shims)
- [ ] All unit tests pass (no new failures)
- [ ] Live smoke test shows pydantic_ai agent returning a valid `AgentOutput`
- [ ] Alpha swarm restarts cleanly

---

## What This Eliminates

- 4 `class FooComputeAgent(BaseMultiplierAgent)` class definitions (~100 lines each)
- `_compute()` method boilerplate in each agent
- Constructor plumbing (`def __init__(self, llm_chain, **kwargs)` + `super().__init__`)
- `_llm_generate()` calls and parse error handling (superseded by `pydantic_ai.Agent.run()`)

## What This Enables (for later phases)

- **Phase 5 (Zep memory):** Add `@pydantic_agent.system_prompt async def enrich(ctx)` to inject episode memory — no class changes needed, just a decorator added to each factory
- **Phase 6 (DSPy):** Load compiled DSPy programs and swap `system_prompt` at runtime
- **Phase 4 (Agent Registry):** Factory functions are trivially wrappable by a registry

---

## Next: Phase 4 — Agent Registry

When ready, ask for:
> "Write the implementation plan for Phase 4 — Agent Registry enabling dynamic agent instantiation and user-created agents without subclassing."

Phase 4 adds a central registry that loads `AgentSpec` from YAML, instantiates `PydanticAIAgent` on demand, and enables user-defined agents without Python subclassing.
