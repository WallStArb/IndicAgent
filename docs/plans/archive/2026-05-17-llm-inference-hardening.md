# LLM Inference Hardening Implementation Plan

**Version:** 1.0
**Status:** archived
**Last Updated:** 2026-05-27
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate zombie Ollama runners, fix silent context truncation, cut alpha agent token waste by 75%, and wire OpenRouter as an automatic fallback — all without changing the `LLMProvider` protocol or anything above the provider layer.

**Architecture:** Switch `OllamaProvider` from sync urllib to native async httpx streaming so asyncio cancellation propagates to the HTTP socket (killing the Ollama runner). Add `OLLAMA_NUM_CTX` to Settings. Wire `openrouter_models` + `openrouter_api_key` (already in Settings) into `_build_providers`. Right-size alpha agent `max_tokens` and add `/no_think` prefix to suppress qwen3.5 chain-of-thought.

**Tech Stack:** Python 3.11, httpx>=0.27.0 (already in requirements), asyncio, pytest-asyncio.

---

## File Map

| File | Action | Change |
|---|---|---|
| `src/config/settings.py` | Modify | Add `ollama_num_ctx: int` field |
| `src/core/llm/providers.py` | Modify | `_call_llm_with_circuit_breaker`: add `retry_on` param + async callable support; `OllamaProvider`: async httpx streaming, shared client, `num_ctx`, `close()` |
| `src/core/llm/chain.py` | Modify | Import `OpenRouterProvider`; `_build_providers` wires full fallback chain; add `close()` |
| `src/intelligence/ai/alpha/skeptic_agent.py` | Modify | `max_tokens` 2000→500, prepend `/no_think` + concise reasoning to `_SYSTEM_MESSAGE` |
| `src/intelligence/ai/alpha/correlation_agent.py` | Modify | Same as skeptic |
| `src/intelligence/ai/alpha/regime_coherence_agent.py` | Modify | Same as skeptic |
| `src/intelligence/ai/alpha/counterfactual_agent.py` | Modify | Same as skeptic |
| `tests/unit/config/test_settings_llm.py` | Create | `OLLAMA_NUM_CTX` env loading |
| `tests/unit/intelligence/test_llm_providers.py` | Modify | Replace urllib mocks for Ollama with httpx mocks; add async-callable + retry_on tests |

---

## Task 1: Add `OLLAMA_NUM_CTX` to Settings

**Files:**
- Modify: `src/config/settings.py` (after `ollama_base_url` field, ~line 92)
- Create: `tests/unit/config/test_settings_llm.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/config/test_settings_llm.py
from __future__ import annotations

import pytest


class TestOllamaSettings:
    def test_ollama_num_ctx_default(self, monkeypatch):
        monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
        from importlib import reload
        import src.config.settings as s
        reload(s)
        settings = s.Settings()
        assert settings.ollama_num_ctx == 16384

    def test_ollama_num_ctx_env_override(self, monkeypatch):
        monkeypatch.setenv("OLLAMA_NUM_CTX", "8192")
        from importlib import reload
        import src.config.settings as s
        reload(s)
        settings = s.Settings()
        assert settings.ollama_num_ctx == 8192
```

- [ ] **Step 2: Run to verify it fails**

```bash
.venv/bin/pytest tests/unit/config/test_settings_llm.py -v
```
Expected: `AttributeError: 'Settings' object has no attribute 'ollama_num_ctx'`

- [ ] **Step 3: Add the field to Settings**

In `src/config/settings.py`, after the `ollama_base_url` field (~line 95):

```python
    ollama_num_ctx: int = Field(
        default=16384,
        validation_alias="OLLAMA_NUM_CTX",
        description=(
            "Ollama context window (tokens). qwen3.5:4b supports 32K; "
            "16384 gives 14K headroom over the largest full-context prompts."
        ),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/config/test_settings_llm.py -v
```
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/config/settings.py tests/unit/config/test_settings_llm.py
git commit -m "feat(settings): add OLLAMA_NUM_CTX field, default 16384"
```

---

## Task 2: Extend `_call_llm_with_circuit_breaker` for async callables + configurable `retry_on`

**Files:**
- Modify: `src/core/llm/providers.py` (function signature + `_run` wrapper, ~lines 74–120)
- Modify: `tests/unit/intelligence/test_llm_providers.py` (add two new tests in `TestCallLLMWithCircuitBreaker`)

- [ ] **Step 1: Write the failing tests**

Add these two tests inside `TestCallLLMWithCircuitBreaker` in `tests/unit/intelligence/test_llm_providers.py`:

```python
    @pytest.mark.asyncio
    async def test_async_callable_is_awaited(self):
        """_call_llm_with_circuit_breaker accepts and awaits async callables."""
        _llm_circuit_breaker.plugin_states.clear()

        async def _async_fn():
            return "async result"

        result = await _call_llm_with_circuit_breaker("test:async", _async_fn)
        assert result == "async result"

    @pytest.mark.asyncio
    async def test_custom_retry_on_excludes_timeout(self):
        """TimeoutError is NOT retried when excluded from retry_on."""
        _llm_circuit_breaker.plugin_states.clear()
        call_count = [0]

        def _fn():
            call_count[0] += 1
            raise TimeoutError("slow model")

        result = await _call_llm_with_circuit_breaker(
            "test:no-retry-timeout",
            _fn,
            retry_on=(ConnectionError, BrokenPipeError),
        )
        assert result is None
        assert call_count[0] == 1  # called exactly once — no retries
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/unit/intelligence/test_llm_providers.py::TestCallLLMWithCircuitBreaker -v
```
Expected: 2 new tests fail (`TypeError: unexpected keyword argument 'retry_on'` and `AssertionError: call_count`)

- [ ] **Step 3: Update `_call_llm_with_circuit_breaker`**

In `src/core/llm/providers.py`, update the function signature and `_run` wrapper (lines 74–120):

```python
async def _call_llm_with_circuit_breaker(
    provider_id: str,
    call_fn: Callable,
    circuit_breaker: PluginCircuitBreaker | None = None,
    retry_on: tuple[type[Exception], ...] = (ConnectionError, TimeoutError, BrokenPipeError),
) -> str | None:
    """Call LLM provider with circuit breaker tracking and retry backoff.

    Args:
        provider_id: Unique provider identifier (e.g., "zai:glm-5")
        call_fn: Sync or async callable that performs the LLM HTTP call.
        circuit_breaker: Circuit breaker to use. Defaults to _llm_circuit_breaker
            (remote providers). Pass _ollama_circuit_breaker for local Ollama.
        retry_on: Exception types that trigger a retry. Omit TimeoutError for
            local providers where retrying a slow model adds load, not recovery.

    Returns:
        LLM response string or None on failure.
    """
    import asyncio as _asyncio

    cb = circuit_breaker or _llm_circuit_breaker
    plugin_state = cb.plugin_states[provider_id]
    previous_state = plugin_state.state

    # --- Pre-call: enforce OPEN / HALF_OPEN gate ---
    if plugin_state.state == CircuitState.OPEN:
        elapsed = time.monotonic() - _llm_open_since.get(provider_id, time.monotonic())
        if elapsed < cb.config.recovery_timeout:
            logger.warning(
                "llm_circuit_open.skipping",
                provider=provider_id,
                elapsed_s=round(elapsed, 1),
                recovery_timeout=cb.config.recovery_timeout,
            )
            return None
        plugin_state.state = CircuitState.HALF_OPEN
        logger.info("llm_circuit_half_open", provider=provider_id)

    async def _run() -> str | None:
        if _asyncio.iscoroutinefunction(call_fn):
            return await call_fn()
        return await to_thread(call_fn)

    try:
        result = await retry_with_backoff(
            _run,
            max_attempts=3,
            base_delay=1.0,
            max_delay=10.0,
            retry_on=retry_on,
        )
```

The rest of the function body (success/failure tracking, circuit breaker state transitions, metrics) is unchanged — leave everything after `result = await retry_with_backoff(...)` as-is.

- [ ] **Step 4: Run all provider tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_llm_providers.py -v
```
Expected: all tests pass (existing tests unaffected — default `retry_on` preserves old behavior)

- [ ] **Step 5: Commit**

```bash
git add src/core/llm/providers.py tests/unit/intelligence/test_llm_providers.py
git commit -m "feat(llm): add retry_on param and async callable support to circuit breaker helper"
```

---

## Task 3: Rewrite `OllamaProvider` with async httpx streaming

**Files:**
- Modify: `src/core/llm/providers.py` (`OllamaProvider` class, ~lines 341–387)
- Modify: `tests/unit/intelligence/test_llm_providers.py` (`TestOllamaProvider` and `TestLLMChain`)

- [ ] **Step 1: Update `TestOllamaProvider` tests for httpx**

Replace the entire `TestOllamaProvider` class and update `TestLLMChain.test_chain_falls_through_to_second_on_failure` in `tests/unit/intelligence/test_llm_providers.py`:

```python
import contextlib
import json as _json


def _make_ollama_stream_lines(content: str) -> list[str]:
    """Build Ollama streaming NDJSON lines for a given content string."""
    lines = [_json.dumps({"message": {"content": content}, "done": False})]
    lines.append(_json.dumps({"message": {"content": ""}, "done": True}))
    return lines


def _make_mock_stream(lines: list[str]):
    """Return an async context manager that yields a mock httpx streaming response."""

    @contextlib.asynccontextmanager
    async def _stream(*args, **kwargs):
        class _Resp:
            def raise_for_status(self):
                pass

            async def aiter_lines(self):
                for line in lines:
                    yield line

        yield _Resp()

    return _stream


class TestOllamaProvider:
    def _make_provider(self) -> "OllamaProvider":
        return OllamaProvider(
            model="qwen3.5:9b",
            base_url="http://fake-ollama.local",
            num_ctx=4096,
        )

    @pytest.mark.asyncio
    async def test_generate_success(self):
        """generate() assembles streamed chunks into a single response."""
        _ollama_circuit_breaker.plugin_states.clear()
        provider = self._make_provider()

        with patch.object(
            provider._client, "stream", _make_mock_stream(_make_ollama_stream_lines("Ollama reply"))
        ):
            result = await provider.generate("prompt", "system", 100, 30.0)

        assert result == "Ollama reply"
        await provider.close()

    @pytest.mark.asyncio
    async def test_generate_failure_returns_none(self):
        """generate() returns None when httpx raises ConnectError."""
        _ollama_circuit_breaker.plugin_states.clear()
        provider = self._make_provider()

        import httpx

        @contextlib.asynccontextmanager
        async def _failing_stream(*args, **kwargs):
            raise httpx.ConnectError("refused")
            yield  # make it a generator

        with patch.object(provider._client, "stream", _failing_stream):
            result = await provider.generate("prompt", "system", 100, 30.0)

        assert result is None
        await provider.close()

    @pytest.mark.asyncio
    async def test_failure_tracked_in_circuit_breaker(self):
        """ConnectError increments failure_count in the ollama-specific circuit breaker."""
        _ollama_circuit_breaker.plugin_states.clear()
        provider = self._make_provider()

        import httpx

        @contextlib.asynccontextmanager
        async def _failing_stream(*args, **kwargs):
            raise httpx.ConnectError("refused")
            yield

        with patch.object(provider._client, "stream", _failing_stream):
            await provider.generate("prompt", "system", 100, 30.0)

        state = _ollama_circuit_breaker.plugin_states[provider.provider_id]
        assert state.failure_count >= 1
        await provider.close()

    @pytest.mark.asyncio
    async def test_num_ctx_passed_in_options(self):
        """generate() passes num_ctx from provider config in Ollama options."""
        _ollama_circuit_breaker.plugin_states.clear()
        provider = OllamaProvider(
            model="qwen3.5:9b", base_url="http://fake-ollama.local", num_ctx=8192
        )
        captured = {}

        @contextlib.asynccontextmanager
        async def _capture_stream(method, url, *, json, timeout, **kwargs):
            captured.update(json)

            class _Resp:
                def raise_for_status(self): pass
                async def aiter_lines(self):
                    yield _json.dumps({"message": {"content": "ok"}, "done": True})

            yield _Resp()

        with patch.object(provider._client, "stream", _capture_stream):
            await provider.generate("prompt", "system", 100, 30.0)

        assert captured["options"]["num_ctx"] == 8192
        assert captured["options"]["num_predict"] == 100
        await provider.close()

    @pytest.mark.asyncio
    async def test_think_false_in_payload(self):
        """generate() sets think=False to suppress qwen chain-of-thought at API level."""
        _ollama_circuit_breaker.plugin_states.clear()
        provider = self._make_provider()
        captured = {}

        @contextlib.asynccontextmanager
        async def _capture_stream(method, url, *, json, timeout, **kwargs):
            captured.update(json)

            class _Resp:
                def raise_for_status(self): pass
                async def aiter_lines(self):
                    yield _json.dumps({"message": {"content": "ok"}, "done": True})

            yield _Resp()

        with patch.object(provider._client, "stream", _capture_stream):
            await provider.generate("prompt", "system", 100, 30.0)

        assert captured["think"] is False
        await provider.close()

    @pytest.mark.asyncio
    async def test_timeout_not_retried(self):
        """TimeoutError from Ollama returns None without retrying (no added load)."""
        _ollama_circuit_breaker.plugin_states.clear()
        provider = self._make_provider()
        call_count = [0]

        @contextlib.asynccontextmanager
        async def _timeout_stream(*args, **kwargs):
            call_count[0] += 1
            raise TimeoutError("model slow")
            yield

        with patch.object(provider._client, "stream", _timeout_stream):
            result = await provider.generate("prompt", "system", 100, 1.0)

        assert result is None
        assert call_count[0] == 1  # no retries
        await provider.close()
```

Also update `TestLLMChain.test_chain_falls_through_to_second_on_failure` — Ollama is now second in the chain and uses httpx, not urllib. Replace it with:

```python
    @pytest.mark.asyncio
    async def test_chain_falls_through_to_second_on_failure(self):
        """LLMChain falls through to Ollama when OpenRouter fails."""
        _llm_circuit_breaker.plugin_states.clear()
        _ollama_circuit_breaker.plugin_states.clear()

        or_provider = OpenRouterProvider("m1", "k1", base_url="http://fake.local")
        ollama_provider = OllamaProvider("qwen3.5:9b", base_url="http://fake-ollama.local", num_ctx=4096)
        chain = LLMChain([or_provider, ollama_provider])

        @contextlib.asynccontextmanager
        async def _ollama_mock_stream(*args, **kwargs):
            class _Resp:
                def raise_for_status(self): pass
                async def aiter_lines(self):
                    yield _json.dumps({"message": {"content": "Fallback reply"}, "done": True})
            yield _Resp()

        with (
            patch("urllib.request.urlopen", side_effect=ConnectionError("openrouter down")),
            patch.object(ollama_provider._client, "stream", _ollama_mock_stream),
        ):
            result = await chain.generate("prompt", "system", 100, 30.0)

        assert result == "Fallback reply"
        assert chain.last_provider_id == ollama_provider.provider_id
        await ollama_provider.close()
```

- [ ] **Step 2: Run to verify tests fail**

```bash
.venv/bin/pytest tests/unit/intelligence/test_llm_providers.py::TestOllamaProvider -v
```
Expected: failures (old urllib-based tests now broken; new tests fail because `OllamaProvider` still uses urllib)

- [ ] **Step 3: Rewrite `OllamaProvider`**

Replace the entire `OllamaProvider` class in `src/core/llm/providers.py`:

```python
class OllamaProvider:
    """Calls local Ollama /api/chat using async httpx streaming.

    Streaming (stream=True) ensures asyncio cancellation propagates to the
    HTTP socket — when the caller's wait_for fires, the connection closes and
    Ollama stops generating. Non-streaming (stream=False) with urllib left
    the runner alive for the full generation duration.
    """

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        timeout: float | None = None,
        num_ctx: int = 4096,
    ) -> None:
        import httpx

        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout or _default_llm_timeout()
        self._num_ctx = num_ctx
        self.provider_id = f"ollama:{model}"
        self._circuit_breaker = _ollama_circuit_breaker
        self._client = httpx.AsyncClient()

    async def generate(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        timeout: float,
    ) -> str | None:
        import httpx

        async def _call() -> str | None:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "stream": True,
                "think": False,
                "options": {"num_predict": max_tokens, "num_ctx": self._num_ctx},
            }
            try:
                chunks: list[str] = []
                async with self._client.stream(
                    "POST",
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=timeout,
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        data = json.loads(line)
                        content = data.get("message", {}).get("content", "")
                        if content:
                            chunks.append(content)
                        if data.get("done"):
                            break
                return _strip_thinking_tags("".join(chunks)) or None
            except httpx.TimeoutException as exc:
                raise TimeoutError(f"Ollama request timed out: {exc}") from exc
            except httpx.ConnectError as exc:
                raise ConnectionError(f"Ollama connection failed: {exc}") from exc
            except httpx.HTTPStatusError as exc:
                raise ConnectionError(f"Ollama HTTP {exc.response.status_code}") from exc

        return await _call_llm_with_circuit_breaker(
            self.provider_id,
            _call,
            circuit_breaker=self._circuit_breaker,
            retry_on=(ConnectionError, BrokenPipeError),
        )

    async def close(self) -> None:
        """Close the shared httpx client. Call on service shutdown."""
        await self._client.aclose()
```

- [ ] **Step 4: Add `import httpx` at module level and add `json` import check**

At the top of `src/core/llm/providers.py`, verify `import json` is present (it is — line 14). No new top-level import needed; httpx is imported inside `__init__` and `generate` to avoid import-time cost when the module is loaded in non-LLM contexts.

- [ ] **Step 5: Run all provider tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_llm_providers.py -v
```
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add src/core/llm/providers.py tests/unit/intelligence/test_llm_providers.py
git commit -m "feat(llm): OllamaProvider async httpx streaming — timeout kills runner, num_ctx configurable"
```

---

## Task 4: Wire OpenRouter fallback in `LLMProviderChain._build_providers`

**Files:**
- Modify: `src/core/llm/chain.py` (~line 18 imports; `_build_providers` method; add `close()`)
- Modify: `tests/unit/intelligence/test_llm_providers.py` (add `TestLLMProviderChainBuildProviders`)

- [ ] **Step 1: Write the failing tests**

Add this class at the bottom of `tests/unit/intelligence/test_llm_providers.py`:

```python
class TestLLMProviderChainBuildProviders:
    """Tests for LLMProviderChain._build_providers fallback wiring."""

    def _make_settings(self, *, api_key: str = "", models: str = "") -> object:
        from unittest.mock import MagicMock
        s = MagicMock()
        s.ollama_model = "qwen3.5:4b"
        s.ollama_base_url = "http://localhost:11434"
        s.ollama_num_ctx = 16384
        s.openrouter_api_key = api_key
        s.openrouter_models = models
        return s

    def test_ollama_only_when_no_api_key(self):
        """No OpenRouter providers when openrouter_api_key is empty."""
        from src.core.llm.chain import LLMProviderChain
        from src.core.llm.providers import OllamaProvider

        chain = LLMProviderChain(call_type="test", settings=self._make_settings())
        providers = chain._inner.providers
        assert len(providers) == 1
        assert isinstance(providers[0], OllamaProvider)

    def test_openrouter_appended_when_api_key_set(self):
        """OpenRouter providers appended after Ollama when api_key is present."""
        from src.core.llm.chain import LLMProviderChain
        from src.core.llm.providers import OllamaProvider, OpenRouterProvider

        settings = self._make_settings(
            api_key="sk-test",
            models="google/gemma-4-31b-it:free,nvidia/nemotron:free",
        )
        chain = LLMProviderChain(call_type="test", settings=settings)
        providers = chain._inner.providers

        assert len(providers) == 3
        assert isinstance(providers[0], OllamaProvider)
        assert isinstance(providers[1], OpenRouterProvider)
        assert providers[1].model == "google/gemma-4-31b-it:free"
        assert isinstance(providers[2], OpenRouterProvider)
        assert providers[2].model == "nvidia/nemotron:free"

    def test_ollama_num_ctx_passed_through(self):
        """OllamaProvider receives num_ctx from settings."""
        from src.core.llm.chain import LLMProviderChain
        from src.core.llm.providers import OllamaProvider

        settings = self._make_settings()
        settings.ollama_num_ctx = 8192
        chain = LLMProviderChain(call_type="test", settings=settings)
        ollama = chain._inner.providers[0]
        assert isinstance(ollama, OllamaProvider)
        assert ollama._num_ctx == 8192

    def test_whitespace_stripped_from_model_names(self):
        """Model names with surrounding whitespace are stripped."""
        from src.core.llm.chain import LLMProviderChain
        from src.core.llm.providers import OpenRouterProvider

        settings = self._make_settings(
            api_key="sk-test",
            models=" google/gemma-4-31b-it:free , nvidia/nemotron:free ",
        )
        chain = LLMProviderChain(call_type="test", settings=settings)
        or_providers = [p for p in chain._inner.providers if isinstance(p, OpenRouterProvider)]
        assert or_providers[0].model == "google/gemma-4-31b-it:free"
        assert or_providers[1].model == "nvidia/nemotron:free"
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/unit/intelligence/test_llm_providers.py::TestLLMProviderChainBuildProviders -v
```
Expected: failures (`AssertionError` — only 1 provider built, no OpenRouter)

- [ ] **Step 3: Update `chain.py`**

In `src/core/llm/chain.py`:

Add import at the top (after existing imports from providers):
```python
from src.core.llm.providers import LLMChain, OllamaProvider, OpenRouterProvider
```

Replace the `_build_providers` method:
```python
    def _build_providers(self, settings: Any) -> list:
        """Build ordered provider list: Ollama first, OpenRouter models as fallback.

        LLMChain tries providers in order — first non-None response wins.
        OpenRouter fallback activates automatically when Ollama's circuit opens.
        """
        if settings is None:
            return [OllamaProvider(model="nemotron-3-nano:4b", num_ctx=4096)]

        providers: list = [
            OllamaProvider(
                model=settings.ollama_model,
                base_url=settings.ollama_base_url,
                num_ctx=settings.ollama_num_ctx,
            )
        ]

        if settings.openrouter_api_key:
            for model in settings.openrouter_models.split(","):
                model = model.strip()
                if model:
                    providers.append(
                        OpenRouterProvider(model=model, api_key=settings.openrouter_api_key)
                    )

        return providers
```

Add `close()` method to `LLMProviderChain` (after `_publish_parse_failure`):
```python
    async def close(self) -> None:
        """Close any provider clients that hold persistent connections (e.g. httpx)."""
        for provider in self._inner.providers:
            if hasattr(provider, "close"):
                await provider.close()
```

- [ ] **Step 4: Run all tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_llm_providers.py -v
```
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add src/core/llm/chain.py tests/unit/intelligence/test_llm_providers.py
git commit -m "feat(llm): wire OpenRouter fallback chain and add LLMProviderChain.close()"
```

---

## Task 5: Right-size alpha agents — `/no_think`, `max_tokens`, concise reasoning

**Files:**
- Modify: `src/intelligence/ai/alpha/skeptic_agent.py`
- Modify: `src/intelligence/ai/alpha/correlation_agent.py`
- Modify: `src/intelligence/ai/alpha/regime_coherence_agent.py`
- Modify: `src/intelligence/ai/alpha/counterfactual_agent.py`
- Modify: `tests/unit/intelligence/test_llm_providers.py` (add `TestAlphaAgentSystemMessages`)

- [ ] **Step 1: Write the failing tests**

Add this class at the bottom of `tests/unit/intelligence/test_llm_providers.py`:

```python
class TestAlphaAgentSystemMessages:
    """Alpha agents must suppress thinking and use concise token budgets."""

    def test_skeptic_no_think_prefix(self):
        from src.intelligence.ai.alpha.skeptic_agent import _SYSTEM_MESSAGE
        assert _SYSTEM_MESSAGE.startswith("/no_think")

    def test_skeptic_max_tokens(self):
        import inspect
        import src.intelligence.ai.alpha.skeptic_agent as m
        src_text = inspect.getsource(m.SkepticComputeAgent._compute)
        assert "max_tokens=500" in src_text
        assert "max_tokens=2000" not in src_text

    def test_correlation_no_think_prefix(self):
        from src.intelligence.ai.alpha.correlation_agent import _SYSTEM_MESSAGE
        assert _SYSTEM_MESSAGE.startswith("/no_think")

    def test_correlation_max_tokens(self):
        import inspect
        import src.intelligence.ai.alpha.correlation_agent as m
        src_text = inspect.getsource(m.CorrelationComputeAgent._compute)
        assert "max_tokens=500" in src_text
        assert "max_tokens=2000" not in src_text

    def test_regime_coherence_no_think_prefix(self):
        from src.intelligence.ai.alpha.regime_coherence_agent import _SYSTEM_MESSAGE
        assert _SYSTEM_MESSAGE.startswith("/no_think")

    def test_regime_coherence_max_tokens(self):
        import inspect
        import src.intelligence.ai.alpha.regime_coherence_agent as m
        src_text = inspect.getsource(m.RegimeCoherenceComputeAgent._compute)
        assert "max_tokens=500" in src_text
        assert "max_tokens=2000" not in src_text

    def test_counterfactual_no_think_prefix(self):
        from src.intelligence.ai.alpha.counterfactual_agent import _SYSTEM_MESSAGE
        assert _SYSTEM_MESSAGE.startswith("/no_think")

    def test_counterfactual_max_tokens(self):
        import inspect
        import src.intelligence.ai.alpha.counterfactual_agent as m
        src_text = inspect.getsource(m.CounterfactualComputeAgent._compute)
        assert "max_tokens=500" in src_text
        assert "max_tokens=2000" not in src_text

    def test_concise_reasoning_instruction_present(self):
        """All four system messages instruct the model to keep reasoning brief."""
        from src.intelligence.ai.alpha.skeptic_agent import _SYSTEM_MESSAGE as sm1
        from src.intelligence.ai.alpha.correlation_agent import _SYSTEM_MESSAGE as sm2
        from src.intelligence.ai.alpha.regime_coherence_agent import _SYSTEM_MESSAGE as sm3
        from src.intelligence.ai.alpha.counterfactual_agent import _SYSTEM_MESSAGE as sm4
        for msg in (sm1, sm2, sm3, sm4):
            assert "100 words" in msg
```

- [ ] **Step 2: Run to verify they fail**

```bash
.venv/bin/pytest tests/unit/intelligence/test_llm_providers.py::TestAlphaAgentSystemMessages -v
```
Expected: all 9 tests fail

- [ ] **Step 3: Update `skeptic_agent.py`**

Replace `_SYSTEM_MESSAGE` and update the `max_tokens` call in `src/intelligence/ai/alpha/skeptic_agent.py`:

```python
_SYSTEM_MESSAGE = (
    "/no_think\n\n"
    "You are a financial trading risk analyst specializing in identifying "
    "signal weaknesses. Always respond with valid JSON. "
    '{"failure_probability": float, "confidence": float, '
    '"risk_factors": [str], "reasoning": str} '
    "Keep reasoning under 100 words."
)
```

In `_compute`, change:
```python
        response, call_id = await self._llm_generate(
            context,
            prompt=prompt,
            system=_SYSTEM_MESSAGE,
            max_tokens=500,
            timeout=self.latency_budget_ms / 1000.0,
        )
```

- [ ] **Step 4: Update `correlation_agent.py`**

Replace `_SYSTEM_MESSAGE` in `src/intelligence/ai/alpha/correlation_agent.py`:

```python
_SYSTEM_MESSAGE = (
    "/no_think\n\n"
    "You are a cross-asset coherence analyst. Output strictly valid JSON. "
    "Phase 80 policy: discount-only — coherence_score and confidence in [0.0, 1.0]. "
    "Keep reasoning under 100 words."
)
```

In `_compute`, change:
```python
        response, call_id = await self._llm_generate(
            context,
            prompt=prompt,
            system=_SYSTEM_MESSAGE,
            max_tokens=500,
            timeout=self.latency_budget_ms / 1000.0,
        )
```

- [ ] **Step 5: Update `regime_coherence_agent.py`**

Replace `_SYSTEM_MESSAGE` in `src/intelligence/ai/alpha/regime_coherence_agent.py`:

```python
_SYSTEM_MESSAGE = (
    "/no_think\n\n"
    "You are a regime-coherence analyst. Output strictly valid JSON. "
    "Phase 80 policy: discount-only — regime_fit and confidence in [0.0, 1.0]. "
    "Keep reasoning under 100 words."
)
```

In `_compute`, change `max_tokens=2000` to `max_tokens=500`.

- [ ] **Step 6: Update `counterfactual_agent.py`**

Replace `_SYSTEM_MESSAGE` in `src/intelligence/ai/alpha/counterfactual_agent.py`:

```python
_SYSTEM_MESSAGE = (
    "/no_think\n\n"
    "You are a counterfactual reasoning analyst. Output strictly valid JSON. "
    "Phase 80 policy: discount-only — plausibility and confidence in [0.0, 1.0]. "
    "Keep reasoning under 100 words."
)
```

In `_compute`, change `max_tokens=2000` to `max_tokens=500`.

- [ ] **Step 7: Run all new and existing tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_llm_providers.py -v
```
Expected: all tests pass

- [ ] **Step 8: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -q
```
Expected: green

- [ ] **Step 9: Commit**

```bash
git add src/intelligence/ai/alpha/skeptic_agent.py \
        src/intelligence/ai/alpha/correlation_agent.py \
        src/intelligence/ai/alpha/regime_coherence_agent.py \
        src/intelligence/ai/alpha/counterfactual_agent.py \
        tests/unit/intelligence/test_llm_providers.py
git commit -m "feat(agents): right-size alpha agent max_tokens 2000→500, add /no_think + concise reasoning"
```

---

## Self-Review

**Spec coverage check:**
- Fix 1 (httpx streaming): Task 3 ✓
- Fix 2 (OLLAMA_NUM_CTX): Task 1 ✓
- Fix 3 (max_tokens + concise reasoning): Task 5 ✓
- Fix 4 (/no_think prefix): Task 5 ✓
- Fix 5 (OpenRouter fallback): Task 4 ✓
- `retry_on` param / no timeout retry: Task 2 ✓
- Shared httpx client (connection pool): Task 3 — `OllamaProvider.__init__` creates `self._client = httpx.AsyncClient()` once ✓
- `close()` lifecycle: Task 3 (`OllamaProvider.close()`), Task 4 (`LLMProviderChain.close()`) ✓
- Backward compat when `openrouter_api_key` empty: Task 4 — guarded by `if settings.openrouter_api_key` ✓

**Placeholder scan:** None found.

**Type consistency:**
- `OllamaProvider(num_ctx=...)` used in Task 3, Task 4, and test helpers — consistent ✓
- `provider._client` accessed in tests — matches `self._client = httpx.AsyncClient()` in Task 3 ✓
- `retry_on` parameter added in Task 2, used in Task 3 — consistent ✓
- `_SYSTEM_MESSAGE` constant name used in tests — matches agent files ✓
