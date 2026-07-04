# Phase 1: LiteLLM Backend Implementation Plan

**Version:** 1.0
**Status:** archived
**Last Updated:** 2026-05-20
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace custom `OllamaProvider`, `OpenRouterProvider`, and `LLMChain` internals with LiteLLM while preserving the `LLMProviderChain.generate()` public interface unchanged.

**Architecture:** Create `src/core/llm/litellm_backend.py` as a drop-in replacement for `LLMChain` + its provider classes. `LiteLLMBackend` wraps `litellm.acompletion()` with the existing `PluginCircuitBreaker` instances. `LLMProviderChain._generate_inner()` calls `LiteLLMBackend` instead of `LLMChain`. All callers (`BaseGroupService`, `BaseAIAgent`, tests) are unaffected.

**Tech Stack:** `litellm>=1.40`, existing `PluginCircuitBreaker`, `structlog`, `asyncio`

**Spec:** `docs/plans/2026-05-20-agent-platform-redesign.md` — Layer 1

**Note:** This is Phase 1 of 7. Phases 2-7 each have their own plan:
- Phase 2: Instructor structured output
- Phase 3: Pydantic AI agents
- Phase 4: Agent Registry
- Phase 5: Zep memory
- Phase 6: DSPy optimizer
- Phase 7: Guardrails AI

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `src/core/llm/litellm_backend.py` | LiteLLM wrapper with circuit breakers, `last_provider_id`, `last_token_usage` |
| Modify | `src/core/llm/chain.py` | Swap `LLMChain([...])` for `LiteLLMBackend(settings)` |
| Modify | `requirements.txt` | Add `litellm` |
| Create | `tests/unit/test_litellm_backend.py` | Unit tests for `LiteLLMBackend` |
| Keep | `src/core/llm/providers.py` | Untouched — circuit breakers imported from here |

---

## Task 1: Install LiteLLM

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add litellm to requirements.txt**

Open `requirements.txt` and add after the existing LLM-related entries:

```
litellm>=1.40.0
```

- [ ] **Step 2: Install it**

```bash
uv pip install litellm
```

Expected: installs without conflicts. LiteLLM pulls in `httpx`, `openai`, `tiktoken` — all compatible with existing deps.

- [ ] **Step 3: Verify import**

```bash
.venv/bin/python -c "import litellm; print(litellm.__version__)"
```

Expected: prints version like `1.40.x` or higher.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "deps: add litellm for provider abstraction"
```

---

## Task 2: Write failing tests for LiteLLMBackend

**Files:**
- Create: `tests/unit/test_litellm_backend.py`

- [ ] **Step 1: Create test file with failing tests**

```python
"""Tests for LiteLLMBackend — LiteLLM wrapper with circuit breaker."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.llm.litellm_backend import LiteLLMBackend


def _make_settings(
    ollama_enabled=True,
    ollama_model="nemotron-3-nano:4b",
    ollama_base_url="http://localhost:11434",
    ollama_num_ctx=4096,
    openrouter_api_key="",
    openrouter_models="",
):
    s = MagicMock()
    s.ollama_enabled = ollama_enabled
    s.ollama_model = ollama_model
    s.ollama_base_url = ollama_base_url
    s.ollama_num_ctx = ollama_num_ctx
    s.openrouter_api_key = openrouter_api_key
    s.openrouter_models = openrouter_models
    return s


def _make_litellm_response(content: str, prompt_tokens=100, completion_tokens=50):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = prompt_tokens
    resp.usage.completion_tokens = completion_tokens
    resp.usage.total_tokens = prompt_tokens + completion_tokens
    return resp


@pytest.mark.asyncio
async def test_generate_ollama_success():
    settings = _make_settings()
    backend = LiteLLMBackend(settings)
    mock_resp = _make_litellm_response('{"result": "ok"}')

    with patch("src.core.llm.litellm_backend.acompletion", new_callable=AsyncMock) as mock_ac:
        mock_ac.return_value = mock_resp
        result, provider_id = await backend.generate(
            prompt="test prompt",
            system="OUTPUT ONLY JSON",
            max_tokens=100,
            timeout=10.0,
        )

    assert result == '{"result": "ok"}'
    assert "ollama" in provider_id
    assert backend.last_provider_id == provider_id
    assert backend.last_token_usage["total_tokens"] == 150


@pytest.mark.asyncio
async def test_generate_falls_back_to_openrouter_on_ollama_failure():
    settings = _make_settings(
        openrouter_api_key="sk-test",
        openrouter_models="openai/gpt-4o-mini",
    )
    backend = LiteLLMBackend(settings)
    fallback_resp = _make_litellm_response("fallback response")

    call_count = 0

    async def side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if "ollama" in kwargs["model"]:
            raise ConnectionError("ollama down")
        return fallback_resp

    with patch("src.core.llm.litellm_backend.acompletion", side_effect=side_effect):
        result, provider_id = await backend.generate(
            prompt="test", system="system", max_tokens=100, timeout=10.0
        )

    assert result == "fallback response"
    assert "openrouter" in provider_id
    assert call_count == 2  # tried ollama, then openrouter


@pytest.mark.asyncio
async def test_generate_returns_none_when_all_providers_fail():
    settings = _make_settings()
    backend = LiteLLMBackend(settings)

    with patch(
        "src.core.llm.litellm_backend.acompletion",
        new_callable=AsyncMock,
        side_effect=ConnectionError("all down"),
    ):
        result, provider_id = await backend.generate(
            prompt="test", system="system", max_tokens=100, timeout=10.0
        )

    assert result is None
    assert backend.last_provider_id is None


@pytest.mark.asyncio
async def test_provider_list_ollama_only():
    settings = _make_settings(openrouter_api_key="", openrouter_models="")
    backend = LiteLLMBackend(settings)
    assert len(backend.providers) == 1
    assert backend.providers[0].startswith("ollama/")


@pytest.mark.asyncio
async def test_provider_list_with_openrouter():
    settings = _make_settings(
        openrouter_api_key="sk-test",
        openrouter_models="google/gemma-4b:free,nvidia/nemotron:free",
    )
    backend = LiteLLMBackend(settings)
    # ollama + 2 openrouter models
    assert len(backend.providers) == 3
    assert backend.providers[0].startswith("ollama/")
    assert "google/gemma-4b:free" in backend.providers[1]
    assert "nvidia/nemotron:free" in backend.providers[2]


@pytest.mark.asyncio
async def test_last_token_usage_none_on_failure():
    settings = _make_settings()
    backend = LiteLLMBackend(settings)

    with patch(
        "src.core.llm.litellm_backend.acompletion",
        new_callable=AsyncMock,
        side_effect=Exception("error"),
    ):
        await backend.generate(prompt="test", system="sys", max_tokens=100, timeout=5.0)

    assert backend.last_token_usage is None
```

- [ ] **Step 2: Run tests to confirm they fail (module not found)**

```bash
.venv/bin/pytest tests/unit/test_litellm_backend.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'src.core.llm.litellm_backend'`

---

## Task 3: Implement LiteLLMBackend

**Files:**
- Create: `src/core/llm/litellm_backend.py`

- [ ] **Step 1: Create the implementation**

```python
"""LiteLLMBackend — LiteLLM-based provider abstraction replacing LLMChain.

Drop-in replacement for LLMChain + OllamaProvider + OpenRouterProvider.
Exposes the same interface: generate() -> (str | None, provider_id).
"""
from __future__ import annotations

import os
from typing import Any

import structlog
from litellm import acompletion

from src.core.plugin_circuit_breaker import CircuitBreakerConfig, PluginCircuitBreaker

logger = structlog.get_logger(__name__)

# Separate circuit breakers matching existing behavior in providers.py
_OLLAMA_CB = PluginCircuitBreaker(
    config=CircuitBreakerConfig(
        failure_threshold=5,
        recovery_timeout=60,
        success_threshold=1,
        max_half_open_calls=3,
        failure_window=120,
        performance_threshold_ms=120000.0,
    )
)

_REMOTE_CB = PluginCircuitBreaker(
    config=CircuitBreakerConfig(
        failure_threshold=3,
        recovery_timeout=300,
        success_threshold=2,
        max_half_open_calls=3,
        failure_window=60,
        performance_threshold_ms=60000.0,
    )
)


class LiteLLMBackend:
    """LiteLLM wrapper with per-provider circuit breakers and ordered fallback.

    Replaces LLMChain([OllamaProvider(...), OpenRouterProvider(...), ...]).
    Interface matches LLMChain: generate() returns (text | None, provider_id).
    """

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self.providers: list[str] = self._build_providers(settings)
        self.last_provider_id: str | None = None
        self.last_token_usage: dict | None = None
        self._configure_litellm(settings)

    def _build_providers(self, settings: Any) -> list[str]:
        providers: list[str] = []
        if settings is None:
            return [f"ollama/nemotron-3-nano:4b"]

        if getattr(settings, "ollama_enabled", True):
            providers.append(f"ollama/{settings.ollama_model}")

        if getattr(settings, "openrouter_api_key", ""):
            for model in getattr(settings, "openrouter_models", "").split(","):
                model = model.strip()
                if model:
                    providers.append(f"openrouter/{model}")

        return providers or [f"ollama/nemotron-3-nano:4b"]

    def _configure_litellm(self, settings: Any) -> None:
        if settings is None:
            return
        base_url = getattr(settings, "ollama_base_url", "http://localhost:11434")
        # LiteLLM reads OLLAMA_API_BASE for ollama provider routing
        os.environ.setdefault("OLLAMA_API_BASE", base_url)
        api_key = getattr(settings, "openrouter_api_key", "")
        if api_key:
            os.environ.setdefault("OPENROUTER_API_KEY", api_key)

    def _circuit_breaker_for(self, provider: str) -> PluginCircuitBreaker:
        return _OLLAMA_CB if provider.startswith("ollama/") else _REMOTE_CB

    async def generate(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        timeout: float,
        model: str = "default",
    ) -> tuple[str | None, str]:
        """Try providers in order, return (text, provider_id) or (None, 'unknown')."""
        self.last_provider_id = None
        self.last_token_usage = None

        for provider in self.providers:
            cb = self._circuit_breaker_for(provider)
            if not cb.allow_request():
                logger.debug("litellm_backend.circuit_open", provider=provider)
                continue

            try:
                kwargs: dict[str, Any] = {
                    "model": provider,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": max_tokens,
                    "timeout": timeout,
                }
                if provider.startswith("ollama/") and self._settings is not None:
                    kwargs["num_ctx"] = getattr(self._settings, "ollama_num_ctx", 4096)

                response = await acompletion(**kwargs)
                content = response.choices[0].message.content

                cb.record_success()
                self.last_provider_id = provider
                if hasattr(response, "usage") and response.usage:
                    self.last_token_usage = {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens,
                    }
                return content, provider

            except Exception as exc:
                cb.record_failure()
                logger.warning(
                    "litellm_backend.provider_failed",
                    provider=provider,
                    error=str(exc)[:120],
                )

        return None, "unknown"
```

- [ ] **Step 2: Run tests**

```bash
.venv/bin/pytest tests/unit/test_litellm_backend.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 3: Commit**

```bash
git add src/core/llm/litellm_backend.py tests/unit/test_litellm_backend.py
git commit -m "feat(llm): add LiteLLMBackend — provider abstraction via litellm"
```

---

## Task 4: Wire LiteLLMBackend into LLMProviderChain

**Files:**
- Modify: `src/core/llm/chain.py`

The goal is to replace `self._inner = LLMChain(providers)` with `self._inner = LiteLLMBackend(settings)`. The `_generate_inner()` method calls `self._inner.generate()` — interface is identical so no other changes needed.

- [ ] **Step 1: Write failing test confirming chain uses LiteLLMBackend**

Add to `tests/unit/test_litellm_backend.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.llm.chain import LLMProviderChain


@pytest.mark.asyncio
async def test_llm_provider_chain_uses_litellm_backend():
    """LLMProviderChain._inner must be a LiteLLMBackend, not LLMChain."""
    from src.core.llm.litellm_backend import LiteLLMBackend

    settings = _make_settings()
    chain = LLMProviderChain(call_type="alpha", settings=settings)
    assert isinstance(chain._inner, LiteLLMBackend)
```

Run: `.venv/bin/pytest tests/unit/test_litellm_backend.py::test_llm_provider_chain_uses_litellm_backend -v`
Expected: FAIL — `chain._inner` is `LLMChain`, not `LiteLLMBackend`.

- [ ] **Step 2: Update chain.py — swap provider construction**

In `src/core/llm/chain.py`, find `__init__` and replace the provider-building block:

Old (lines ~75-78):
```python
providers = self._build_providers(settings)
self._inner = LLMChain(providers)
```

New:
```python
from src.core.llm.litellm_backend import LiteLLMBackend
self._inner = LiteLLMBackend(settings)
```

Remove the `_build_providers` method entirely (it's now inside `LiteLLMBackend`).

Remove these imports from `chain.py` (no longer needed):
```python
from src.core.llm.providers import LLMChain, OllamaProvider, OpenRouterProvider
```

- [ ] **Step 3: Run full test**

```bash
.venv/bin/pytest tests/unit/test_litellm_backend.py -v
```

Expected: all 7 tests pass including `test_llm_provider_chain_uses_litellm_backend`.

- [ ] **Step 4: Run full unit suite to check for regressions**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short 2>&1 | tail -15
```

Expected: same failure count as before this phase (7 pre-existing failures, none new).

- [ ] **Step 5: Commit**

```bash
git add src/core/llm/chain.py
git commit -m "feat(llm): wire LiteLLMBackend into LLMProviderChain — retire OllamaProvider/OpenRouterProvider"
```

---

## Task 5: Smoke test against live Ollama

- [ ] **Step 1: Confirm Ollama is running**

```bash
docker exec ollama ollama ps
```

Expected: `nemotron-3-nano:4b` listed and loaded.

- [ ] **Step 2: Run a live generate through LiteLLMBackend**

```bash
.venv/bin/python - <<'EOF'
import asyncio, os
os.environ["OLLAMA_API_BASE"] = "http://localhost:11434"
from src.core.llm.litellm_backend import LiteLLMBackend
from unittest.mock import MagicMock

s = MagicMock()
s.ollama_enabled = True
s.ollama_model = "nemotron-3-nano:4b"
s.ollama_base_url = "http://localhost:11434"
s.ollama_num_ctx = 4096
s.openrouter_api_key = ""
s.openrouter_models = ""

backend = LiteLLMBackend(s)

async def run():
    result, provider = await backend.generate(
        prompt='Return exactly: {"ok": true}',
        system="OUTPUT ONLY RAW JSON.",
        max_tokens=50,
        timeout=30.0,
    )
    print(f"provider: {provider}")
    print(f"result: {result}")
    print(f"tokens: {backend.last_token_usage}")

asyncio.run(run())
EOF
```

Expected: provider shows `ollama/nemotron-3-nano:4b`, result is JSON, tokens populated.

- [ ] **Step 3: Restart intelligence-pipeline to pick up new chain**

```bash
sudo systemctl restart indicagent-intelligence-pipeline indicagent-alpha-swarm indicagent-narrative-compute
sleep 6 && systemctl status indicagent-intelligence-pipeline indicagent-alpha-swarm indicagent-narrative-compute --no-pager | grep "Active:"
```

Expected: all three `active (running)`.

- [ ] **Step 4: Check logs for errors**

```bash
tail -20 logs/alpha_swarm_compute_agent.log | grep -E "error|Error|failed|Failed|litellm"
```

Expected: no errors. LLM calls should continue flowing.

- [ ] **Step 5: Push**

```bash
git push origin main
```

---

## Verification

Phase 1 is complete when:

- [ ] `LiteLLMBackend` exists at `src/core/llm/litellm_backend.py`
- [ ] `LLMProviderChain._inner` is a `LiteLLMBackend` instance
- [ ] All unit tests pass (no new failures)
- [ ] Live smoke test shows `ollama/nemotron-3-nano:4b` as provider
- [ ] Services restart cleanly and LLM calls continue flowing
- [ ] `OllamaProvider`, `OpenRouterProvider`, and `LLMChain` are no longer instantiated by `chain.py`

---

## Next: Phase 2 — Instructor

When ready to start Phase 2, ask for the plan:
> "Write the implementation plan for Phase 2 — Instructor replacing _parse_multiplier_response and _validate_*_fields across all 5 alpha agents."

Phase 2 eliminates ~200 lines of custom parsing boilerplate and brings parse failures to near-zero.
