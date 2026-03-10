# OpenRouter LLM Provider Integration — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add OpenRouter (free models) as the primary LLM backend with Ollama as fallback, using a provider-chain abstraction.

**Architecture:** `LLMProvider` protocol + `OpenRouterProvider` + `OllamaProvider` + `LLMChain` in `src/intelligence/llm_providers.py`. Narrative service replaces both `call_ollama_async` call sites with two chains (per-signal and group synthesis).

**Tech Stack:** Python asyncio, `asyncio.to_thread`, stdlib `urllib.request`, `structlog`, `pytest`

---

### Task 1: Create `src/intelligence/llm_providers.py` — providers and chain

**Files:**
- Create: `src/intelligence/llm_providers.py`
- Test: `tests/unit/test_llm_providers.py`

**Step 1: Write the failing tests**

Create `tests/unit/test_llm_providers.py`:

```python
"""Tests for LLMProvider protocol, OpenRouterProvider, OllamaProvider, LLMChain."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.intelligence.llm_providers import (
    LLMChain,
    OllamaProvider,
    OpenRouterProvider,
)

SYSTEM = "You are a trading analyst."
PROMPT = "Summarize: bullish ES 5m"


# ---------------------------------------------------------------------------
# OpenRouterProvider
# ---------------------------------------------------------------------------

class TestOpenRouterProvider:
    def _make_provider(self):
        return OpenRouterProvider(
            model="meta-llama/llama-3.3-70b-instruct:free",
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
        )

    def _mock_response(self, text: str) -> MagicMock:
        payload = {"choices": [{"message": {"content": text}}]}
        resp = MagicMock()
        resp.read.return_value = json.dumps(payload).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    @pytest.mark.asyncio
    async def test_success(self):
        provider = self._make_provider()
        with patch("urllib.request.urlopen", return_value=self._mock_response("Bullish outlook.")):
            result = await provider.generate(PROMPT, SYSTEM, max_tokens=100, timeout=10.0)
        assert result == "Bullish outlook."

    @pytest.mark.asyncio
    async def test_empty_content_returns_none(self):
        provider = self._make_provider()
        with patch("urllib.request.urlopen", return_value=self._mock_response("   ")):
            result = await provider.generate(PROMPT, SYSTEM, max_tokens=100, timeout=10.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self):
        provider = self._make_provider()
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            result = await provider.generate(PROMPT, SYSTEM, max_tokens=100, timeout=10.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self):
        import urllib.error
        provider = self._make_provider()
        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
            url=None, code=429, msg="Too Many Requests", hdrs=None, fp=None
        )):
            result = await provider.generate(PROMPT, SYSTEM, max_tokens=100, timeout=10.0)
        assert result is None


# ---------------------------------------------------------------------------
# OllamaProvider
# ---------------------------------------------------------------------------

class TestOllamaProvider:
    def _make_provider(self):
        return OllamaProvider(
            model="qwen3:8b",
            base_url="http://localhost:11434",
        )

    def _mock_response(self, text: str) -> MagicMock:
        payload = {"message": {"content": text}}
        resp = MagicMock()
        resp.read.return_value = json.dumps(payload).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    @pytest.mark.asyncio
    async def test_success(self):
        provider = self._make_provider()
        with patch("urllib.request.urlopen", return_value=self._mock_response("Bearish signal.")):
            result = await provider.generate(PROMPT, SYSTEM, max_tokens=500, timeout=60.0)
        assert result == "Bearish signal."

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self):
        provider = self._make_provider()
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            result = await provider.generate(PROMPT, SYSTEM, max_tokens=500, timeout=60.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_error_returns_none(self):
        provider = self._make_provider()
        with patch("urllib.request.urlopen", side_effect=Exception("connection refused")):
            result = await provider.generate(PROMPT, SYSTEM, max_tokens=500, timeout=60.0)
        assert result is None


# ---------------------------------------------------------------------------
# LLMChain
# ---------------------------------------------------------------------------

class TestLLMChain:
    @pytest.mark.asyncio
    async def test_first_provider_succeeds(self):
        p1 = MagicMock()
        p1.generate = AsyncMock(return_value="result from p1")
        p2 = MagicMock()
        p2.generate = AsyncMock(return_value="result from p2")
        chain = LLMChain([p1, p2])
        result = await chain.generate(PROMPT, SYSTEM, max_tokens=100, timeout=10.0)
        assert result == "result from p1"
        p2.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_first_fails_second_succeeds(self):
        p1 = MagicMock()
        p1.generate = AsyncMock(return_value=None)
        p2 = MagicMock()
        p2.generate = AsyncMock(return_value="result from p2")
        chain = LLMChain([p1, p2])
        result = await chain.generate(PROMPT, SYSTEM, max_tokens=100, timeout=10.0)
        assert result == "result from p2"

    @pytest.mark.asyncio
    async def test_all_fail_returns_none(self):
        p1 = MagicMock()
        p1.generate = AsyncMock(return_value=None)
        p2 = MagicMock()
        p2.generate = AsyncMock(return_value=None)
        chain = LLMChain([p1, p2])
        result = await chain.generate(PROMPT, SYSTEM, max_tokens=100, timeout=10.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_winning_provider_name_tracked(self):
        p1 = MagicMock()
        p1.generate = AsyncMock(return_value=None)
        p1.provider_id = "openrouter:meta-llama/llama-3.3-70b-instruct:free"
        p2 = MagicMock()
        p2.generate = AsyncMock(return_value="success")
        p2.provider_id = "openrouter:arcee-ai/trinity-large-preview:free"
        chain = LLMChain([p1, p2])
        result = await chain.generate(PROMPT, SYSTEM, max_tokens=100, timeout=10.0)
        assert result == "success"
        assert chain.last_provider_id == "openrouter:arcee-ai/trinity-large-preview:free"
```

**Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/test_llm_providers.py -v 2>&1 | head -20
```

Expected: `ImportError` — `src/intelligence/llm_providers.py` does not exist yet.

**Step 3: Write the implementation**

Create `src/intelligence/llm_providers.py`:

```python
"""LLM provider abstraction — OpenRouter (primary) and Ollama (fallback).

Usage:
    chain = LLMChain([
        OpenRouterProvider("meta-llama/llama-3.3-70b-instruct:free", api_key="sk-..."),
        OpenRouterProvider("arcee-ai/trinity-large-preview:free",     api_key="sk-..."),
        OllamaProvider("qwen3:8b"),
    ])
    text = await chain.generate(prompt, system, max_tokens=500, timeout=30.0)
    # chain.last_provider_id tells you which provider succeeded
"""
from __future__ import annotations

import json
import urllib.request
from asyncio import to_thread
from typing import Protocol, runtime_checkable

import structlog

logger = structlog.get_logger(__name__)


@runtime_checkable
class LLMProvider(Protocol):
    """Minimal protocol every LLM backend must satisfy."""

    provider_id: str

    async def generate(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        timeout: float,
    ) -> str | None:
        """Return generated text, or None on failure."""
        ...


class OpenRouterProvider:
    """Calls OpenRouter /api/v1/chat/completions (OpenAI-compatible)."""

    def __init__(self, model: str, api_key: str, base_url: str = "https://openrouter.ai/api/v1") -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.provider_id = f"openrouter:{model}"

    async def generate(self, prompt: str, system: str, max_tokens: int, timeout: float) -> str | None:
        def _call() -> str | None:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt},
                ],
                "max_tokens": max_tokens,
                "stream": False,
            }
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())
            choices = result.get("choices") or []
            if not choices:
                return None
            return choices[0].get("message", {}).get("content", "").strip() or None

        try:
            return await to_thread(_call)
        except Exception as exc:
            logger.warning("OpenRouter call failed", model=self.model, error=str(exc))
            return None


class OllamaProvider:
    """Calls local Ollama /api/chat."""

    def __init__(self, model: str, base_url: str = "http://localhost:11434") -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.provider_id = f"ollama:{model}"

    async def generate(self, prompt: str, system: str, max_tokens: int, timeout: float) -> str | None:
        def _call() -> str | None:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": prompt},
                ],
                "stream": False,
                "options": {"num_predict": max_tokens},
            }
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"{self.base_url}/api/chat",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())
            return result.get("message", {}).get("content", "").strip() or None

        try:
            return await to_thread(_call)
        except Exception as exc:
            logger.warning("Ollama call failed", model=self.model, error=str(exc))
            return None


class LLMChain:
    """Try each provider in order; return first non-None result."""

    def __init__(self, providers: list[LLMProvider]) -> None:
        self.providers = providers
        self.last_provider_id: str | None = None

    async def generate(self, prompt: str, system: str, max_tokens: int, timeout: float) -> str | None:
        for provider in self.providers:
            result = await provider.generate(prompt, system, max_tokens, timeout)
            if result is not None:
                self.last_provider_id = provider.provider_id
                return result
        self.last_provider_id = None
        return None
```

**Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/unit/test_llm_providers.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add src/intelligence/llm_providers.py tests/unit/test_llm_providers.py
git commit -m "feat(llm): add LLMChain with OpenRouterProvider and OllamaProvider"
```

---

### Task 2: Wire chains into `ai_narrative_service.py`

**Files:**
- Modify: `services/ai_narrative_service.py`

**Step 1: Add provider config to `_load_config` default**

In `_load_config`, replace the `"ollama"` section with a `"providers"` section (keep `"ollama"` keys for backwards compat so nothing breaks if old config file used):

Find the `"ollama"` dict in `default_config` (around line 313) and add after it:

```python
"providers": {
    "openrouter_base_url": "https://openrouter.ai/api/v1",
    "openrouter_timeout_sec": 30.0,
    "ollama_base_url": "http://localhost:11434",
    "ollama_timeout_sec": 60.0,
    "per_signal": [
        {"type": "openrouter", "model": "meta-llama/llama-3.3-70b-instruct:free"},
        {"type": "openrouter", "model": "arcee-ai/trinity-large-preview:free"},
        {"type": "ollama",     "model": "qwen3:8b"},
    ],
    "group": [
        {"type": "openrouter", "model": "stepfun/step-3.5-flash:free"},
        {"type": "openrouter", "model": "arcee-ai/trinity-large-preview:free"},
        {"type": "ollama",     "model": "phi4-mini:3.8b"},
    ],
},
```

**Step 2: Build chains in `__init__`**

After the existing metrics setup in `__init__`, add a `_build_chains()` call:

Replace the `self.ollama_base_url`, `self.ollama_model`, `self.ollama_timeout`, `self.group_model` lines with:

```python
self._build_chains()
```

Add new method to the class:

```python
def _build_chains(self) -> None:
    from src.intelligence.llm_providers import LLMChain, OllamaProvider, OpenRouterProvider

    settings = Settings()
    api_key = getattr(settings, "openrouter_api_key", None) or ""

    pcfg = self.config["providers"]
    or_url = pcfg["openrouter_base_url"]
    or_timeout = float(pcfg["openrouter_timeout_sec"])
    ol_url = pcfg["ollama_base_url"]
    ol_timeout = float(pcfg["ollama_timeout_sec"])

    def _make_provider(spec: dict):
        if spec["type"] == "openrouter":
            return OpenRouterProvider(spec["model"], api_key=api_key, base_url=or_url)
        return OllamaProvider(spec["model"], base_url=ol_url)

    self.per_signal_chain = LLMChain([_make_provider(s) for s in pcfg["per_signal"]])
    self.group_chain = LLMChain([_make_provider(s) for s in pcfg["group"]])

    # Timeouts stored separately — passed at call time
    self._or_timeout = or_timeout
    self._ol_timeout = ol_timeout
    # Per-call timeout: use OR timeout (faster); chain falls to Ollama with its own timeout
    self._per_signal_timeout = or_timeout
    self._group_timeout = or_timeout
```

**Step 3: Add `OPENROUTER_API_KEY` to `Settings`**

Open `src/config/settings.py` and add the field:

```python
openrouter_api_key: str = ""
```

(Pydantic-settings will auto-read `OPENROUTER_API_KEY` from env.)

**Step 4: Replace per-signal call site**

Find the per-signal call (around line 468):

```python
narrative_text = await call_ollama_async(
    self.ollama_base_url,
    self.ollama_model,
    prompt,
    self.ollama_timeout,
    int(self.config["ollama"].get("num_predict", 500)),
)
latency_ms = (time.time() - t0) * 1000
self.ollama_latency_ms.set(latency_ms)
```

Replace with:

```python
narrative_text = await self.per_signal_chain.generate(
    prompt,
    SYSTEM_PROMPT,
    max_tokens=500,
    timeout=self._per_signal_timeout,
)
latency_ms = (time.time() - t0) * 1000
self.ollama_latency_ms.set(latency_ms)
```

In the `if narrative_text:` block, update the `"model"` field to use the winning provider:

```python
"model": self.per_signal_chain.last_provider_id or "unknown",
```

**Step 5: Replace group synthesis call site**

Find the group call (around line 616):

```python
narrative_text = await call_ollama_async(
    self.ollama_base_url,
    self.group_model,
    prompt,
    self.ollama_timeout,
    300,
)
```

Replace with:

```python
narrative_text = await self.group_chain.generate(
    prompt,
    GROUP_SYSTEM_PROMPT,
    max_tokens=300,
    timeout=self._group_timeout,
)
```

In the `if narrative_text:` block, update `"model"`:

```python
"model": self.group_chain.last_provider_id or "unknown",
```

**Step 6: Remove `call_ollama_async` function and unused imports**

Delete the entire `call_ollama_async` function (lines ~188–226). Remove `from asyncio import to_thread` if no longer used elsewhere.

Run ruff to catch any remaining references:

```bash
.venv/bin/ruff check services/ai_narrative_service.py --fix
```

**Step 7: Run the full unit test suite**

```bash
.venv/bin/pytest tests/unit/ -v
```

Expected: All existing tests + new provider tests PASS. 0 errors.

**Step 8: Commit**

```bash
git add services/ai_narrative_service.py src/config/settings.py
git commit -m "feat(narrative): wire OpenRouter+Ollama LLMChain into narrative service"
```

---

### Task 3: Deploy and verify

**Step 1: Restart the narrative service**

```bash
sudo systemctl restart indicagent-ai-narrative
```

**Step 2: Tail logs for first synthesis**

```bash
tail -f logs/ai_narrative.log
```

Expected within ~90 seconds (30s loop wait + inference):
- `"Group narrative published"` with `"model": "openrouter:stepfun/step-3.5-flash:free"` (or arcee fallback)
- Latency should be 2–10s instead of 30–60s

**Step 3: Verify Ollama is NOT loaded (models idle)**

```bash
curl -s http://localhost:11434/api/ps | python3 -c "import sys,json; d=json.load(sys.stdin); print([m['name'] for m in d.get('models',[])])"
```

Expected: `[]` — no models loaded unless OpenRouter failed and Ollama was used as fallback.

**Step 4: Commit completion note**

```bash
git commit --allow-empty -m "chore: OpenRouter LLM provider integration complete — verified in production"
```
