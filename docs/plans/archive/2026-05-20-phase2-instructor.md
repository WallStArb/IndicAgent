# Phase 2: Instructor Structured Output Implementation Plan

**Version:** 1.0
**Status:** archived
**Last Updated:** 2026-05-20
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace custom `_parse_multiplier_response` + `_validate_*_fields` boilerplate with Instructor-enforced structured output. Parse failures drop from ~17% to near-zero because Instructor injects validation errors back into the prompt and retries automatically.

**Architecture:** Add `_llm_generate_structured()` to `BaseAIAgent` alongside the existing `_llm_generate()`. A module-level `_INSTRUCTOR_CLIENT = instructor.from_litellm(acompletion)` singleton does the LLM calls with retry. Each alpha agent defines a typed Pydantic result model (replacing `_validate_*_fields`) and calls `_llm_generate_structured()` instead of `_llm_generate()` + `_parse_multiplier_response()`.

**Scope:** 4 LLM alpha agents (skeptic, correlation, counterfactual, regime_coherence). `ml_scorer_agent.py` is LightGBM-only — not touched.

**Spec:** `docs/plans/2026-05-20-agent-platform-redesign.md` — Layer 2 (Instructor)

**Phase dependencies:** Phase 1 (LiteLLM) must be merged first — `acompletion` from litellm is the LLM call path.

**Note:** This is Phase 2 of 7. Provider fallback and circuit breakers are handled by LiteLLM's built-in retry for the structured path. Phase 3 (Pydantic AI) will unify both paths under one architecture.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `src/core/ai/structured_client.py` | `instructor.from_litellm` singleton |
| Modify | `src/core/ai/base_agent.py` | Add `_llm_generate_structured[T]()` |
| Modify | `src/intelligence/ai/alpha/skeptic_prompts.py` | Add `SkepticResult` model, keep `build_skeptic_prompt` |
| Modify | `src/intelligence/ai/alpha/skeptic_agent.py` | Use structured call, remove parse boilerplate |
| Modify | `src/intelligence/ai/alpha/correlation_agent.py` | Add `CorrelationResult`, use structured call |
| Modify | `src/intelligence/ai/alpha/counterfactual_agent.py` | Add `CounterfactualResult`, use structured call |
| Modify | `src/intelligence/ai/alpha/regime_coherence_agent.py` | Add `RegimeCoherenceResult`, use structured call |
| Modify | `tests/unit/ai_agent_tests/test_skeptic_agent.py` | Update for new API (no `_parse_multiplier_response`) |
| Create | `tests/unit/ai_agent_tests/test_structured_client.py` | Unit tests for `_llm_generate_structured` |

---

## Task 1: Install Instructor

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add instructor to requirements.txt**

Open `requirements.txt` and add after the litellm entry:

```
instructor>=1.3.0
```

- [ ] **Step 2: Install it**

```bash
uv pip install instructor
```

Expected: installs without conflicts. Instructor depends on `pydantic>=2.0` and `openai>=1.0` — both compatible with the existing stack.

- [ ] **Step 3: Verify import**

```bash
.venv/bin/python -c "import instructor; print(instructor.__version__)"
```

Expected: prints a version like `1.3.x` or higher.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "deps: add instructor for structured LLM output"
```

---

## Task 2: Write failing tests

**Files:**
- Create: `tests/unit/ai_agent_tests/test_structured_client.py`

- [ ] **Step 1: Create test file**

```python
"""Tests for _llm_generate_structured on BaseAIAgent."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from src.core.ai.base_agent import BaseAIAgent
from src.core.ai.context import AIContext


class _SampleResult(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    label: str


def _make_agent() -> BaseAIAgent:
    """Minimal concrete BaseAIAgent for testing."""
    class _ConcreteAgent(BaseAIAgent):
        agent_id = "test_agent"
        group = "test"
        prompt_version = "v1"
        tiers_needed = frozenset()
        shadow_only = True
        latency_budget_ms = 5000.0

        async def _compute(self, context): ...

    agent = _ConcreteAgent.__new__(_ConcreteAgent)
    agent.logger = MagicMock()
    agent.tracer = MagicMock()
    agent.tracer.start_as_current_span.return_value.__enter__ = lambda s, *a: MagicMock()
    agent.tracer.start_as_current_span.return_value.__exit__ = lambda s, *a: False
    agent._agent_labels = {"agent_id": "test_agent"}
    agent._llm = MagicMock()
    agent._llm._inner = MagicMock()
    agent._llm._inner.providers = ["ollama/test-model"]
    return agent


def _make_context() -> AIContext:
    ctx = MagicMock(spec=AIContext)
    ctx.symbol = "ES"
    ctx.timeframe = "5m"
    ctx.signal_id = None
    ctx.smc = None
    return ctx


@pytest.mark.asyncio
async def test_generate_structured_returns_parsed_model():
    agent = _make_agent()
    ctx = _make_context()

    with patch("src.core.ai.base_agent._INSTRUCTOR_CLIENT") as mock_client:
        mock_client.chat.completions.create = AsyncMock(
            return_value=_SampleResult(score=0.75, label="bullish")
        )
        result = await agent._llm_generate_structured(
            ctx, _SampleResult, prompt="test", system="sys", max_tokens=100, timeout=5.0
        )

    assert result is not None
    assert result.score == 0.75
    assert result.label == "bullish"


@pytest.mark.asyncio
async def test_generate_structured_returns_none_on_exception():
    agent = _make_agent()
    ctx = _make_context()

    with patch("src.core.ai.base_agent._INSTRUCTOR_CLIENT") as mock_client:
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("LLM error")
        )
        result = await agent._llm_generate_structured(
            ctx, _SampleResult, prompt="test", system="sys", max_tokens=100, timeout=5.0
        )

    assert result is None


@pytest.mark.asyncio
async def test_generate_structured_returns_none_when_no_providers():
    agent = _make_agent()
    agent._llm._inner.providers = []
    ctx = _make_context()

    result = await agent._llm_generate_structured(
        ctx, _SampleResult, prompt="test", system="sys", max_tokens=100, timeout=5.0
    )

    assert result is None
```

- [ ] **Step 2: Run to confirm they fail**

```bash
.venv/bin/pytest tests/unit/ai_agent_tests/test_structured_client.py -v 2>&1 | head -20
```

Expected: `AttributeError: '_ConcreteAgent' object has no attribute '_llm_generate_structured'`

---

## Task 3: Create structured_client.py and add _llm_generate_structured to BaseAIAgent

**Files:**
- Create: `src/core/ai/structured_client.py`
- Modify: `src/core/ai/base_agent.py`

- [ ] **Step 1: Create src/core/ai/structured_client.py**

```python
"""Instructor-patched LiteLLM client for structured output with automatic retry.

Usage:
    from src.core.ai.structured_client import INSTRUCTOR_CLIENT
    result = await INSTRUCTOR_CLIENT.chat.completions.create(
        model="ollama/...",
        messages=[...],
        response_model=MyModel,
        max_retries=2,
    )
"""
from __future__ import annotations

import instructor
from litellm import acompletion

INSTRUCTOR_CLIENT = instructor.from_litellm(acompletion)
```

- [ ] **Step 2: Add _llm_generate_structured to BaseAIAgent**

In `src/core/ai/base_agent.py`, add after the `from src.observability.spans import ...` import block:

```python
from typing import TypeVar
from src.core.ai.structured_client import INSTRUCTOR_CLIENT
_T = TypeVar("_T")
```

Then add `_INSTRUCTOR_CLIENT = INSTRUCTOR_CLIENT` as a module-level alias (so tests can patch it easily):

```python
# Module-level alias — tests patch this name
_INSTRUCTOR_CLIENT = INSTRUCTOR_CLIENT
```

Then add the method to `BaseAIAgent`, after `_llm_generate`:

```python
async def _llm_generate_structured(
    self,
    context: AIContext,
    result_type: type[_T],
    prompt: str,
    system: str,
    max_tokens: int,
    timeout: float,
    max_retries: int = 2,
) -> _T | None:
    """LLM call with Instructor-enforced structured output and automatic retry.

    On parse failure, Instructor injects the validation error back into the
    prompt and retries (up to max_retries times) before raising. Replaces the
    _parse_multiplier_response + _validate_*_fields boilerplate in each agent.

    Returns None when all providers are exhausted or timeout is exceeded.
    Circuit breaker logic for the structured path is delegated to LiteLLM's
    built-in retry. Phase 3 (Pydantic AI) will unify both paths.
    """
    providers = getattr(getattr(self._llm, "_inner", None), "providers", None) or []
    if not providers:
        return None

    with self.tracer.start_as_current_span(
        "agent.llm_generate_structured",
        attributes={
            ATTR_AGENT_ID: self.agent_id,
            ATTR_SYMBOL: context.symbol,
            ATTR_TF: context.timeframe,
        },
    ) as span:
        try:
            result = await asyncio.wait_for(
                _INSTRUCTOR_CLIENT.chat.completions.create(
                    model=providers[0],
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    response_model=result_type,
                    max_tokens=max_tokens,
                    max_retries=max_retries,
                ),
                timeout=timeout,
            )
            return result
        except Exception as exc:
            span.set_status(StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            logger.warning(
                "agent.structured_generate_failed",
                agent_id=self.agent_id,
                error=str(exc)[:120],
            )
            return None
```

- [ ] **Step 3: Run tests**

```bash
.venv/bin/pytest tests/unit/ai_agent_tests/test_structured_client.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/core/ai/structured_client.py src/core/ai/base_agent.py
git commit -m "feat(ai): add _llm_generate_structured via Instructor — structured output with retry"
```

---

## Task 4: Skeptic agent — add SkepticResult model and migrate to structured call

**Files:**
- Modify: `src/intelligence/ai/alpha/skeptic_prompts.py`
- Modify: `src/intelligence/ai/alpha/skeptic_agent.py`

- [ ] **Step 1: Add SkepticResult to skeptic_prompts.py**

In `src/intelligence/ai/alpha/skeptic_prompts.py`, add after the imports:

```python
from pydantic import BaseModel, Field, field_validator
from src.core.ai.prompt_utils import clamp

class SkepticResult(BaseModel):
    failure_probability: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    risk_factors: list[str] = Field(default_factory=list)
    reasoning: str = Field(max_length=500)

    @field_validator("risk_factors", mode="before")
    @classmethod
    def coerce_to_list(cls, v: object) -> list[str]:
        if not isinstance(v, list):
            return [str(v)]
        return [str(x) for x in v]
```

Delete the `_validate_skeptic_fields` function entirely — `SkepticResult` replaces it.

Remove `_validate_skeptic_fields` from `__all__` (if present) and from the import in `skeptic_agent.py`.

- [ ] **Step 2: Update skeptic_agent.py**

In `src/intelligence/ai/alpha/skeptic_agent.py`:

1. Replace the import of `_validate_skeptic_fields`:
   ```python
   # Remove: from src.intelligence.ai.alpha.skeptic_prompts import (
   #     ACTIVE_VERSION, _validate_skeptic_fields, build_skeptic_prompt,
   # )
   # Add:
   from src.intelligence.ai.alpha.skeptic_prompts import (
       ACTIVE_VERSION, SkepticResult, build_skeptic_prompt,
   )
   ```

2. Remove `output_schema: ClassVar[dict]` — no longer needed.

3. Replace the `_compute` body after the prompt build:

   **Old:**
   ```python
   response, call_id = await self._llm_generate(
       context, prompt=prompt, system=_SYSTEM_MESSAGE, max_tokens=500,
       timeout=self.latency_budget_ms / 1000.0,
   )
   if not response:
       return self._neutral(error="LLM returned empty response", latency_ms=0.0)

   parsed = self._parse_multiplier_response(response, _validate_skeptic_fields)
   if parsed is None:
       logger.warning("skeptic_agent.json_parse_failed", ...)
       await self._report_parse_failure(call_id)
       return self._neutral(error="JSON parse failed", latency_ms=0.0)

   failure_probability = parsed["failure_probability"]
   llm_confidence = parsed["confidence"]
   ```

   **New:**
   ```python
   result = await self._llm_generate_structured(
       context,
       SkepticResult,
       prompt=prompt,
       system=_SYSTEM_MESSAGE,
       max_tokens=500,
       timeout=self.latency_budget_ms / 1000.0,
   )
   if result is None:
       return self._neutral(error="Structured parse failed", latency_ms=0.0)

   failure_probability = result.failure_probability
   llm_confidence = result.confidence
   ```

4. Update `_build_multiplier_output` payload to use result attributes:
   ```python
   return self._build_multiplier_output(
       context=context,
       multiplier=multiplier,
       confidence=llm_confidence,
       payload={
           "failure_probability": failure_probability,
           "risk_factors": result.risk_factors,
           "reasoning": result.reasoning,
       },
       prompt_version=ACTIVE_VERSION,
   )
   ```

- [ ] **Step 3: Run unit tests**

```bash
.venv/bin/pytest tests/unit/ai_agent_tests/ -v -k "skeptic" 2>&1 | tail -20
```

Fix any failures (likely related to mock setup changes).

- [ ] **Step 4: Commit**

```bash
git add src/intelligence/ai/alpha/skeptic_prompts.py src/intelligence/ai/alpha/skeptic_agent.py
git commit -m "feat(skeptic): migrate to Instructor structured output — remove _validate_skeptic_fields"
```

---

## Task 5: Correlation agent — add CorrelationResult and migrate

**Files:**
- Modify: `src/intelligence/ai/alpha/correlation_agent.py`

- [ ] **Step 1: Add CorrelationResult model**

In `correlation_agent.py`, add after imports:

```python
from pydantic import BaseModel, Field, field_validator

class CorrelationResult(BaseModel):
    coherence_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    contradicting_assets: list[str] = Field(default_factory=list)
    reasoning: str = Field(default="")

    @field_validator("contradicting_assets", mode="before")
    @classmethod
    def coerce_to_list(cls, v: object) -> list[str]:
        if not isinstance(v, list):
            return [str(v)]
        return [str(x) for x in v]
```

Delete `_validate_correlation_fields` function entirely.

- [ ] **Step 2: Migrate _compute to structured call**

Replace in `_compute`:

**Old:**
```python
response, call_id = await self._llm_generate(...)
if not response:
    return self._neutral(error="LLM returned empty response", latency_ms=0.0)
parsed = self._parse_multiplier_response(response, _validate_correlation_fields)
if parsed is None:
    ...
    return self._neutral(error="JSON parse failed", latency_ms=0.0)
coherence_score = parsed["coherence_score"]
llm_confidence = parsed["confidence"]
```

**New:**
```python
result = await self._llm_generate_structured(
    context, CorrelationResult, prompt=prompt, system=_SYSTEM_MESSAGE,
    max_tokens=400, timeout=self.latency_budget_ms / 1000.0,
)
if result is None:
    return self._neutral(error="Structured parse failed", latency_ms=0.0)
coherence_score = result.coherence_score
llm_confidence = result.confidence
```

Remove `output_schema: ClassVar[dict]` from the class.

Update payload dict to use `result.contradicting_assets`, `result.reasoning`.

- [ ] **Step 3: Run tests and commit**

```bash
.venv/bin/pytest tests/unit/ai_agent_tests/ -v -k "correlation" 2>&1 | tail -15
git add src/intelligence/ai/alpha/correlation_agent.py
git commit -m "feat(correlation): migrate to Instructor structured output — remove _validate_correlation_fields"
```

---

## Task 6: Counterfactual agent — add CounterfactualResult and migrate

**Files:**
- Modify: `src/intelligence/ai/alpha/counterfactual_agent.py`

- [ ] **Step 1: Add CounterfactualResult model**

```python
from pydantic import BaseModel, Field, field_validator

class CounterfactualResult(BaseModel):
    plausibility: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    validation_conditions: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    alternative_scenario: str = Field(default="")

    @field_validator("validation_conditions", "invalidation_conditions", mode="before")
    @classmethod
    def coerce_to_list(cls, v: object) -> list[str]:
        if not isinstance(v, list):
            return [str(v)]
        return [str(x) for x in v]
```

Delete `_validate_counterfactual_fields` function.

- [ ] **Step 2: Migrate _compute**

Same pattern: replace `_llm_generate` + `_parse_multiplier_response` with `_llm_generate_structured(context, CounterfactualResult, ...)`.

Replace `parsed["plausibility"]` → `result.plausibility`, etc.

Remove `output_schema: ClassVar[dict]`.

- [ ] **Step 3: Run tests and commit**

```bash
.venv/bin/pytest tests/unit/ai_agent_tests/ -v -k "counterfactual" 2>&1 | tail -15
git add src/intelligence/ai/alpha/counterfactual_agent.py
git commit -m "feat(counterfactual): migrate to Instructor structured output — remove _validate_counterfactual_fields"
```

---

## Task 7: Regime coherence agent — add RegimeCoherenceResult and migrate

**Files:**
- Modify: `src/intelligence/ai/alpha/regime_coherence_agent.py`

- [ ] **Step 1: Add RegimeCoherenceResult model**

```python
from pydantic import BaseModel, Field, field_validator

class RegimeCoherenceResult(BaseModel):
    regime_fit: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    supporting_factors: list[str] = Field(default_factory=list)
    warning_factors: list[str] = Field(default_factory=list)

    @field_validator("supporting_factors", "warning_factors", mode="before")
    @classmethod
    def coerce_to_list(cls, v: object) -> list[str]:
        if not isinstance(v, list):
            return [str(v)]
        return [str(x) for x in v]
```

Delete `_validate_regime_coherence_fields` function.

- [ ] **Step 2: Migrate _compute**

Replace the LLM call + parse block with:

```python
result = await self._llm_generate_structured(
    context, RegimeCoherenceResult, prompt=prompt, system=_SYSTEM_MESSAGE,
    max_tokens=400, timeout=self.latency_budget_ms / 1000.0,
)
if result is None:
    return self._neutral(error="Structured parse failed", latency_ms=0.0)
regime_fit = result.regime_fit
llm_confidence = result.confidence
```

Remove `output_schema: ClassVar[dict]`.

- [ ] **Step 3: Run tests and commit**

```bash
.venv/bin/pytest tests/unit/ai_agent_tests/ -v -k "regime" 2>&1 | tail -15
git add src/intelligence/ai/alpha/regime_coherence_agent.py
git commit -m "feat(regime_coherence): migrate to Instructor structured output — remove _validate_regime_coherence_fields"
```

---

## Task 8: Clean up BaseMultiplierAgent boilerplate

**Files:**
- Modify: `src/core/ai/multiplier_agent.py`

Now that all 4 agents use `_llm_generate_structured`, the `_parse_multiplier_response` method on `BaseMultiplierAgent` is dead code.

- [ ] **Step 1: Remove _parse_multiplier_response**

Delete the method from `BaseMultiplierAgent`. Also remove the `parse_llm_json` import from `prompt_utils` if it's now unused.

Check no other callers remain:

```bash
grep -r "_parse_multiplier_response\|parse_llm_json" src/ --include="*.py" | grep -v "__pycache__"
```

Expected: no results (or only non-alpha callers — check before deleting).

- [ ] **Step 2: Remove output_schema ClassVar requirement from docstring**

Update the class docstring to remove the `output_schema` requirement since agents no longer need it.

- [ ] **Step 3: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short 2>&1 | tail -15
```

Expected: same failure count as before this phase.

- [ ] **Step 4: Commit**

```bash
git add src/core/ai/multiplier_agent.py
git commit -m "simplify: remove dead _parse_multiplier_response from BaseMultiplierAgent"
```

---

## Task 9: Smoke test against live Ollama

- [ ] **Step 1: Confirm Instructor can reach Ollama**

```bash
.venv/bin/python - <<'EOF'
import asyncio
import os
os.environ["OLLAMA_API_BASE"] = "http://localhost:11434"

import instructor
from litellm import acompletion
from pydantic import BaseModel, Field

class TestResult(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    label: str

client = instructor.from_litellm(acompletion)

async def run():
    result = await client.chat.completions.create(
        model="ollama/nemotron-3-nano:4b",
        messages=[
            {"role": "system", "content": "Return ONLY valid JSON matching the schema."},
            {"role": "user", "content": "Rate this market signal: strong bullish momentum."},
        ],
        response_model=TestResult,
        max_tokens=100,
        max_retries=2,
    )
    print(f"score: {result.score}")
    print(f"label: {result.label}")
    print(f"type: {type(result)}")

asyncio.run(run())
EOF
```

Expected: `score` is a float 0-1, `label` is a string, `type` is `<class 'TestResult'>`.

- [ ] **Step 2: Restart alpha swarm**

```bash
sudo systemctl restart indicagent-alpha-swarm
sleep 6 && systemctl status indicagent-alpha-swarm --no-pager | grep "Active:"
```

Expected: `active (running)`.

- [ ] **Step 3: Check logs for parse failures**

```bash
tail -30 logs/alpha_swarm_compute_agent.log | grep -iE "parse_failed|structured_generate_failed|error"
```

Expected: no parse failures. If Instructor retries succeed, no errors appear.

- [ ] **Step 4: Push**

```bash
git push origin main
```

---

## Verification

Phase 2 is complete when:

- [ ] `_INSTRUCTOR_CLIENT` singleton exists at module level in `src/core/ai/base_agent.py`
- [ ] `_llm_generate_structured()` is on `BaseAIAgent`
- [ ] `SkepticResult`, `CorrelationResult`, `CounterfactualResult`, `RegimeCoherenceResult` Pydantic models exist
- [ ] `_validate_skeptic_fields`, `_validate_correlation_fields`, `_validate_counterfactual_fields`, `_validate_regime_coherence_fields` are deleted
- [ ] `_parse_multiplier_response` is deleted from `BaseMultiplierAgent`
- [ ] All `output_schema: ClassVar[dict]` removed from the 4 migrated agents
- [ ] All unit tests pass (no new failures)
- [ ] Live smoke test shows Instructor parsing a `TestResult` from Ollama
- [ ] Alpha swarm restarts cleanly and runs without parse failure log lines

---

## What This Eliminates

- ~80 lines of custom `_validate_*_fields` boilerplate across 4 agents
- `_parse_multiplier_response()` + `parse_llm_json()` fallback chain in `multiplier_agent.py`
- `output_schema: ClassVar[dict]` redundant type declarations
- `_report_parse_failure()` calls — Instructor retries before ever returning None
- `if parsed is None: return self._neutral(...)` defensive checks in every `_compute()`

---

## Next: Phase 3 — Pydantic AI

When ready to start Phase 3, ask for the plan:
> "Write the implementation plan for Phase 3 — Pydantic AI agents replacing BaseAIAgent and BaseMultiplierAgent with typed Agent[AgentDeps, ResultType]."

Phase 3 replaces the `BaseAIAgent` / `BaseMultiplierAgent` classes themselves with `pydantic_ai.Agent` instances, giving typed deps injection, tool use, and built-in result validation.
