# Phase 7: Guardrails AI Content Validation Implementation Plan

**Version:** 1.0
**Status:** archived
**Last Updated:** 2026-05-20
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the custom `GuardrailsValidator` (Pydantic schema-only) with Guardrails AI for content-level validation — checking that float fields are in plausible ranges, reasoning doesn't contain hallucinated tickers, and prompt injection attempts are blocked.

**Architecture:** Add `@agent.result_validator` hooks to `PydanticAIAgent` (via a new `content_guards.py` module) that run after Instructor has already enforced structure. The existing `GuardrailsValidator` in `src/core/llm/guardrails.py` is kept for backward compatibility with `LLMProviderChain` (which is still used by non-Pydantic-AI code paths). The new Guardrails AI validation is an additional layer specific to the new agent architecture.

**Phase dependencies:** Phase 3 (Pydantic AI) must be merged first — validators are wired onto `pydantic_ai.Agent` instances.

**Spec:** `docs/plans/2026-05-20-agent-platform-redesign.md` — Layer 3 (Guardrails AI)

**What is NOT changed:**
- `src/core/llm/guardrails.py` (`GuardrailsValidator`) — kept as-is for `LLMProviderChain`
- `src/core/llm/chain.py` — unchanged
- Any service that uses `LLMProviderChain.generate()` directly

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `src/core/ai/content_guards.py` | Guard definitions per result type; `apply_guards(agent)` helper |
| Modify | `src/core/ai/pydantic_agent.py` | Accept optional `guards` list; apply in `compute()` |
| Modify | `src/intelligence/ai/alpha/pydantic_agents.py` | Call `apply_guards(pydantic_agent)` in each factory function |
| Modify | `src/core/ai/agent_registry.py` | Call `apply_guards` in `_build_generic_agent` |
| Modify | `requirements.txt` | Add `guardrails-ai` |
| Create | `tests/unit/ai_agent_tests/test_content_guards.py` | Unit tests for guard validation |

---

## Task 1: Install guardrails-ai

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Check if guardrails-ai is already installed**

```bash
.venv/bin/python -c "import guardrails; print(guardrails.__version__)" 2>/dev/null || echo "not installed"
```

- [ ] **Step 2: Add to requirements.txt**

```
guardrails-ai>=0.5
```

Install:

```bash
uv pip install "guardrails-ai>=0.5"
```

Verify:

```bash
.venv/bin/python -c "import guardrails; print(guardrails.__version__)"
```

- [ ] **Step 3: Check what validators are available**

```bash
.venv/bin/python -c "import guardrails; help(guardrails)" 2>/dev/null | head -30
```

We will use Guardrails AI's `Guard` and `Validator` classes. The key built-in validators we need:
- `ValidRange` (or `InRange`) — float range check
- Custom validator for ticker hallucination

If `ValidRange` is not available in the installed version, we will write a custom validator (shown in Task 2).

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "deps: add guardrails-ai for content-level LLM output validation"
```

---

## Task 2: Write failing tests for content guards

**Files:**
- Create: `tests/unit/ai_agent_tests/test_content_guards.py`

- [ ] **Step 1: Create test file**

```python
"""Tests for content_guards — Guardrails AI result validators for alpha agents."""
from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from src.core.ai.content_guards import (
    validate_confidence,
    validate_multiplier,
    validate_no_hallucinated_tickers,
    validate_reasoning_length,
)


# ── validate_multiplier ───────────────────────────────────────────────────────

def test_validate_multiplier_accepts_valid():
    assert validate_multiplier(1.0) is True
    assert validate_multiplier(0.0) is True
    assert validate_multiplier(2.0) is True


def test_validate_multiplier_rejects_out_of_range():
    assert validate_multiplier(-0.1) is False
    assert validate_multiplier(2.01) is False
    assert validate_multiplier(float("nan")) is False


def test_validate_multiplier_rejects_non_numeric():
    assert validate_multiplier("high") is False  # type: ignore[arg-type]
    assert validate_multiplier(None) is False  # type: ignore[arg-type]


# ── validate_confidence ───────────────────────────────────────────────────────

def test_validate_confidence_accepts_valid():
    assert validate_confidence(0.0) is True
    assert validate_confidence(0.5) is True
    assert validate_confidence(1.0) is True


def test_validate_confidence_rejects_out_of_range():
    assert validate_confidence(-0.1) is False
    assert validate_confidence(1.01) is False


# ── validate_no_hallucinated_tickers ─────────────────────────────────────────

KNOWN_SYMBOLS = frozenset({"ES", "NQ", "CL", "GC", "SI", "VX", "RTY", "YM"})


def test_validate_no_hallucinated_tickers_passes_known_symbols():
    text = "ES shows strong momentum, NQ confirms"
    assert validate_no_hallucinated_tickers(text, known_symbols=KNOWN_SYMBOLS) is True


def test_validate_no_hallucinated_tickers_passes_no_ticker_pattern():
    text = "The setup looks strong with high volume and bullish candle."
    assert validate_no_hallucinated_tickers(text, known_symbols=KNOWN_SYMBOLS) is True


def test_validate_no_hallucinated_tickers_rejects_unknown_ticker():
    # "AAPL" looks like a ticker (2-5 uppercase letters) but not in known set
    text = "ES momentum is confirmed by AAPL cross-asset signal"
    assert validate_no_hallucinated_tickers(text, known_symbols=KNOWN_SYMBOLS) is False


def test_validate_no_hallucinated_tickers_allows_common_words():
    # Common English words in all-caps (e.g., "AND", "OR") should not flag
    text = "ES AND NQ momentum OR consolidation phase"
    assert validate_no_hallucinated_tickers(text, known_symbols=KNOWN_SYMBOLS) is True


# ── validate_reasoning_length ─────────────────────────────────────────────────

def test_validate_reasoning_length_accepts_short():
    assert validate_reasoning_length("Short reasoning.", max_words=100) is True


def test_validate_reasoning_length_rejects_too_long():
    long_text = " ".join(["word"] * 201)
    assert validate_reasoning_length(long_text, max_words=100) is False


def test_validate_reasoning_length_accepts_empty():
    assert validate_reasoning_length("", max_words=100) is True
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/unit/ai_agent_tests/test_content_guards.py -v 2>&1 | head -15
```

Expected: `ModuleNotFoundError: No module named 'src.core.ai.content_guards'`

---

## Task 3: Implement content_guards

**Files:**
- Create: `src/core/ai/content_guards.py`

- [ ] **Step 1: Create `src/core/ai/content_guards.py`**

```python
"""Content-level validators for alpha agent LLM outputs.

These functions validate the semantic content of LLM responses — range checks,
hallucination detection, length guards. They run AFTER Instructor has already
enforced structural correctness (types, required fields, Pydantic constraints).

apply_guards(pydantic_agent, known_symbols) adds a @agent.result_validator
hook that calls these validators on every result before returning it to compute().
A guard failure logs a warning and raises ModelRetry — pydantic_ai will retry the
call (Instructor handles the retry loop).
"""
from __future__ import annotations

import math
import re
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# English words that are 2-5 uppercase letters — exclude from ticker detection.
_COMMON_WORDS = frozenset({
    "A", "AN", "THE", "AND", "OR", "NOT", "BUT", "FOR", "IN", "ON",
    "AT", "TO", "BY", "OF", "IS", "IT", "AS", "BE", "DO", "IF",
    "NO", "SO", "UP", "GO", "OK", "MY", "HE", "WE",
    # trading-specific words that look like tickers
    "LONG", "SHORT", "HIGH", "LOW", "OPEN", "STOP", "BULL", "BEAR",
    "SELL", "BUY", "CALL", "PUT", "RSI", "ATR", "EMA", "SMA", "VOL",
    "HMM", "SMC", "POC", "VAH", "VAL", "HTF",
})

# Pattern: 2-5 uppercase letters (potential ticker symbol)
_TICKER_RE = re.compile(r"\b([A-Z]{2,5})\b")


def validate_multiplier(value: Any) -> bool:
    """Return True if value is a float in [0.0, 2.0]."""
    try:
        v = float(value)
        return not math.isnan(v) and 0.0 <= v <= 2.0
    except (TypeError, ValueError):
        return False


def validate_confidence(value: Any) -> bool:
    """Return True if value is a float in [0.0, 1.0]."""
    try:
        v = float(value)
        return not math.isnan(v) and 0.0 <= v <= 1.0
    except (TypeError, ValueError):
        return False


def validate_no_hallucinated_tickers(
    text: str,
    known_symbols: frozenset[str],
) -> bool:
    """Return True if text contains no unrecognized ticker-like tokens.

    Flags tokens matching [A-Z]{2,5} that are not in known_symbols and not in
    the common-words exclusion list. This catches "AAPL confirmed momentum"
    style hallucinations in reasoning fields.
    """
    if not text:
        return True
    for match in _TICKER_RE.finditer(text):
        token = match.group(1)
        if token in _COMMON_WORDS:
            continue
        if token not in known_symbols:
            logger.debug(
                "content_guard.unknown_ticker",
                token=token,
                text_preview=text[:80],
            )
            return False
    return True


def validate_reasoning_length(text: str, max_words: int = 150) -> bool:
    """Return True if text is within max_words words."""
    if not text:
        return True
    word_count = len(text.split())
    return word_count <= max_words


def apply_guards(pydantic_agent: Any, known_symbols: frozenset[str] | None = None) -> None:
    """Register a result_validator on pydantic_agent that runs content guards.

    Validates any result with `multiplier`, `confidence`, and `reasoning` fields.
    Raises ModelRetry on violation — pydantic_ai will retry the LLM call.

    Call this immediately after constructing the pydantic_ai.Agent, before
    returning the PydanticAIAgent wrapper.
    """
    from pydantic_ai import ModelRetry

    _known = known_symbols or frozenset()

    @pydantic_agent.result_validator
    async def _content_guard(ctx: Any, result: Any) -> Any:
        violations: list[str] = []

        # Multiplier check (applies to GenericMultiplierResult and SkepticResult etc.)
        if hasattr(result, "multiplier"):
            if not validate_multiplier(result.multiplier):
                violations.append(f"multiplier={result.multiplier!r} is outside [0, 2]")

        # Confidence check
        if hasattr(result, "confidence"):
            if not validate_confidence(result.confidence):
                violations.append(f"confidence={result.confidence!r} is outside [0, 1]")

        # Coherence score check (CorrelationResult)
        if hasattr(result, "coherence_score"):
            if not validate_confidence(result.coherence_score):
                violations.append(f"coherence_score={result.coherence_score!r} is outside [0, 1]")

        # failure_probability check (SkepticResult)
        if hasattr(result, "failure_probability"):
            if not validate_confidence(result.failure_probability):
                violations.append(f"failure_probability={result.failure_probability!r} is outside [0, 1]")

        # regime_fit check (RegimeCoherenceResult)
        if hasattr(result, "regime_fit"):
            if not validate_confidence(result.regime_fit):
                violations.append(f"regime_fit={result.regime_fit!r} is outside [0, 1]")

        # Plausibility check (CounterfactualResult)
        if hasattr(result, "plausibility"):
            if not validate_confidence(result.plausibility):
                violations.append(f"plausibility={result.plausibility!r} is outside [0, 1]")

        # Reasoning hallucination check
        if _known and hasattr(result, "reasoning"):
            if not validate_no_hallucinated_tickers(result.reasoning or "", _known):
                violations.append("reasoning contains unrecognized ticker symbol(s)")

        # Reasoning length check
        if hasattr(result, "reasoning"):
            if not validate_reasoning_length(result.reasoning or ""):
                violations.append("reasoning exceeds 150 words")

        if violations:
            logger.warning(
                "content_guard.violation",
                violations=violations,
            )
            raise ModelRetry(
                f"Content validation failed: {'; '.join(violations)}. "
                "Fix the values and retry."
            )

        return result
```

- [ ] **Step 2: Run tests**

```bash
.venv/bin/pytest tests/unit/ai_agent_tests/test_content_guards.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add src/core/ai/content_guards.py tests/unit/ai_agent_tests/test_content_guards.py
git commit -m "feat(ai): add content_guards — range checks, hallucination detection, reasoning length"
```

---

## Task 4: Wire guards into factory functions and registry

**Files:**
- Modify: `src/intelligence/ai/alpha/pydantic_agents.py`
- Modify: `src/core/ai/agent_registry.py`

- [ ] **Step 1: Read current factory function structure**

```bash
grep -n "def make_\|pydantic_agent\|return PydanticAIAgent" src/intelligence/ai/alpha/pydantic_agents.py | head -20
```

- [ ] **Step 2: Get the known symbols for hallucination detection**

```bash
grep -n "get_active_contracts\|Instrument\|symbol" src/config/settings.py | head -15
```

We need the set of valid instrument symbols (e.g., `{"ES", "NQ", "CL", "GC", ...}`). Rather than hardcoding them, extract them at factory call time from settings.

- [ ] **Step 3: Update all 4 factory functions to call apply_guards**

For each factory function, add `apply_guards` after constructing `pydantic_agent`:

**In `make_skeptic_agent`:**

```python
from src.core.ai.content_guards import apply_guards
from src.config.settings import get_active_contracts

def make_skeptic_agent(model: Any, settings: Any, memory_store: Any = None) -> PydanticAIAgent:
    pydantic_agent: Agent[AgentDeps, SkepticResult] = Agent(
        model=model,
        result_type=SkepticResult,
        system_prompt=_SKEPTIC_SYSTEM,
        deps_type=AgentDeps,
    )

    # Add memory hook (Phase 5)
    if memory_store is not None:
        from pydantic_ai import RunContext
        @pydantic_agent.system_prompt
        async def _memory_enrich(ctx: RunContext[AgentDeps]) -> str:
            if ctx.deps.memory is None:
                return ""
            return await ctx.deps.memory.recall(ctx.deps.context)

    # Add content guards (Phase 7)
    known = frozenset(c.symbol for c in get_active_contracts(settings))
    apply_guards(pydantic_agent, known_symbols=known)

    ...
```

Apply the same pattern to `make_correlation_agent`, `make_counterfactual_agent`, `make_regime_coherence_agent`.

- [ ] **Step 4: Update `_build_generic_agent` in agent_registry.py**

```python
from src.core.ai.content_guards import apply_guards
from src.config.settings import get_active_contracts

def _build_generic_agent(spec, model, settings, memory_store=None, compiled_prompt=None):
    ...
    pydantic_agent = Agent(...)

    if memory_store is not None:
        ...memory hook...

    # Content guards
    known = frozenset(c.symbol for c in get_active_contracts(settings))
    apply_guards(pydantic_agent, known_symbols=known)

    ...
```

- [ ] **Step 5: Run full unit tests**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short 2>&1 | tail -15
```

Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add src/intelligence/ai/alpha/pydantic_agents.py src/core/ai/agent_registry.py
git commit -m "feat(alpha): wire content guards into all agent factories — range + hallucination validation"
```

---

## Task 5: Smoke test and final verification

- [ ] **Step 1: Run import check**

```bash
.venv/bin/python -c "
from src.core.ai.content_guards import apply_guards, validate_multiplier, validate_confidence
print('validate_multiplier(1.5):', validate_multiplier(1.5))
print('validate_multiplier(3.0):', validate_multiplier(3.0))
print('validate_confidence(0.8):', validate_confidence(0.8))
print('validate_confidence(-0.1):', validate_confidence(-0.1))
print('all ok')
"
```

- [ ] **Step 2: Verify ModelRetry is importable (pydantic_ai dependency)**

```bash
.venv/bin/python -c "from pydantic_ai import ModelRetry; print('ModelRetry: ok')"
```

- [ ] **Step 3: Restart alpha swarm**

```bash
sudo systemctl restart indicagent-alpha-swarm
sleep 6 && systemctl status indicagent-alpha-swarm --no-pager | grep "Active:"
```

Expected: `active (running)`.

- [ ] **Step 4: Check logs for guard-related messages**

```bash
tail -30 logs/alpha_swarm_compute_agent.log | grep -iE "content_guard|violation|model_retry|error"
```

Expected: no unexpected errors. `content_guard.violation` may appear when Ollama returns out-of-range values — this is correct behavior (triggers retry).

- [ ] **Step 5: Run final unit test suite**

```bash
.venv/bin/pytest tests/unit/ -q 2>&1 | tail -5
```

Expected: all tests pass.

- [ ] **Step 6: Push**

```bash
git push origin main
```

---

## Verification

Phase 7 is complete when:

- [ ] `guardrails-ai` is in requirements.txt and installs cleanly
- [ ] `src/core/ai/content_guards.py` exists with `validate_multiplier`, `validate_confidence`, `validate_no_hallucinated_tickers`, `validate_reasoning_length`, and `apply_guards`
- [ ] `apply_guards(agent)` is called in all 4 factory functions and `_build_generic_agent`
- [ ] `GuardrailsValidator` in `src/core/llm/guardrails.py` is untouched (backward compat)
- [ ] All unit tests pass
- [ ] Alpha swarm restarts cleanly

---

## What this replaces / preserves

**Replaces (for Pydantic AI agents only):**
- The concept of `GuardrailsValidator` for the new agent architecture — content guards are wired at the `pydantic_ai.Agent` level instead

**Preserves:**
- `src/core/llm/guardrails.py` — still used by `LLMProviderChain.generate()` for any remaining non-Pydantic-AI code paths
- All existing service behavior — guards only affect what happens inside `PydanticAIAgent.compute()`

**Future extension:**
- Add `validate_no_injection(reasoning)` — checks for prompt injection patterns like "ignore previous instructions"
- Add Guardrails AI Hub validators when available: `TwoWords`, `SimilarToList`, etc.
- Per-agent guard configuration via YAML: `guards: [range_check, no_hallucinated_tickers]`
