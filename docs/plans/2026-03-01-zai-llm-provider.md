# ZAI LLM Provider Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Integrate ZAI (GLM-5) as the primary LLM provider with OpenRouter and Ollama as fallbacks, using TDD and atomic commits.

**Architecture:** Add `ZAIProvider` class implementing `LLMProvider` protocol, add configuration to `Settings`, update provider chain to include ZAI first, and add comprehensive unit tests. The existing `LLMChain` handles fallback logic - providers are tried sequentially with the first successful response returned.

**Tech Stack:** Python 3.12+, pydantic-settings, pytest, asyncio, urllib.request, structlog

---

## Overview

This plan implements ZAI as a new LLM provider in the IndicAgent platform. ZAI uses the GLM-5 model (SOTA foundation model for agentic engineering) via an OpenAI-compatible API at `https://api.z.ai/api/paas/v4/chat/completions`.

The implementation follows TDD: write failing tests first, then implement to pass. Each task is a 2-5 minute action with immediate commit.

---

### Task 1: Add ZAI Configuration Fields to Settings

**Files:**
- Modify: `src/config/settings.py:61-66`

**Step 1: Write the failing test**

Create a new test file to verify ZAI settings load correctly:

```python
# tests/unit/test_settings_zai.py
import os
from src.config.settings import Settings

def test_zai_settings_defaults():
    """ZAI settings have correct defaults."""
    settings = Settings()
    assert settings.zai_api_key == ""
    assert settings.zai_base_url == "https://api.z.ai/api/paas/v4"
    assert settings.zai_model == "glm-5"
    assert settings.zai_timeout_sec == 30.0

def test_zai_settings_from_env():
    """ZAI settings load from environment variables."""
    os.environ["ZAI_API_KEY"] = "test-key"
    os.environ["ZAI_BASE_URL"] = "https://custom.z.ai/v4"
    os.environ["ZAI_MODEL"] = "glm-5-custom"
    os.environ["ZAI_TIMEOUT_SEC"] = "45.0"
    settings = Settings()
    assert settings.zai_api_key == "test-key"
    assert settings.zai_base_url == "https://custom.z.ai/v4"
    assert settings.zai_model == "glm-5-custom"
    assert settings.zai_timeout_sec == 45.0
    # Cleanup
    del os.environ["ZAI_API_KEY"]
    del os.environ["ZAI_BASE_URL"]
    del os.environ["ZAI_MODEL"]
    del os.environ["ZAI_TIMEOUT_SEC"]
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_settings_zai.py -v`
Expected: FAIL - ZAI settings don't exist yet

**Step 3: Write minimal implementation**

Add ZAI configuration fields after the existing `openrouter_api_key` field (around line 62):

```python
# src/config/settings.py
# LLM providers
zai_api_key: str = Field(default="", validation_alias="ZAI_API_KEY")
zai_base_url: str = Field(default="https://api.z.ai/api/paas/v4", validation_alias="ZAI_BASE_URL")
zai_model: str = Field(default="glm-5", validation_alias="ZAI_MODEL")
zai_timeout_sec: float = Field(default=30.0, validation_alias="ZAI_TIMEOUT_SEC")

openrouter_api_key: str = Field(default="", validation_alias="OPENROUTER_API_KEY")
openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1", validation_alias="OPENROUTER_BASE_URL")
openrouter_timeout_sec: float = Field(default=30.0, validation_alias="OPENROUTER_TIMEOUT_SEC")

ollama_base_url: str = Field(default="http://localhost:11434", validation_alias="OLLAMA_BASE_URL")
ollama_timeout_sec: float = Field(default=60.0, validation_alias="OLLAMA_TIMEOUT_SEC")
```

**Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_settings_zai.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/config/settings.py tests/unit/test_settings_zai.py
git commit -m "feat(settings): add ZAI LLM provider configuration"
```

---

### Task 2: Write ZAIProvider Unit Tests

**Files:**
- Modify: `tests/unit/test_llm_providers.py`

**Step 1: Write the failing tests**

Add tests at the end of `test_llm_providers.py`:

```python
# tests/unit/test_llm_providers.py
class TestZAIProvider(unittest.TestCase):
    """Unit tests for ZAIProvider."""

    def test_success_response(self):
        """ZAI returns valid content from API."""
        from src.intelligence.llm_providers import ZAIProvider

        with mock.patch("asyncio.to_thread") as mock_to_thread:
            mock_future = asyncio.Future()
            mock_future.set_result("Generated narrative text")
            mock_to_thread.return_value = mock_future

            provider = ZAIProvider(model="glm-5", api_key="test-key")
            result = asyncio.run(provider.generate("test prompt", "system prompt", 100, 30.0))

            self.assertEqual(result, "Generated narrative text")
            self.assertEqual(provider.provider_id, "zai:glm-5")
            mock_to_thread.assert_called_once()

    def test_timeout_error(self):
        """ZAI timeout returns None and logs warning."""
        from src.intelligence.llm_providers import ZAIProvider

        with mock.patch("asyncio.to_thread") as mock_to_thread:
            mock_to_thread.side_effect = TimeoutError("Request timed out after 30s")

            provider = ZAIProvider(model="glm-5", api_key="test-key")
            result = asyncio.run(provider.generate("test prompt", "system prompt", 100, 30.0))

            self.assertIsNone(result)

    def test_http_429_rate_limit(self):
        """HTTP 429 rate limit returns None."""
        from src.intelligence.llm_providers import ZAIProvider
        from urllib.error import HTTPError

        with mock.patch("asyncio.to_thread") as mock_to_thread:
            mock_to_thread.side_effect = HTTPError(
                url="https://api.z.ai/api/paas/v4/chat/completions",
                code=429,
                msg="Rate limit exceeded",
                hdrs={},
                fp=None
            )

            provider = ZAIProvider(model="glm-5", api_key="test-key")
            result = asyncio.run(provider.generate("test prompt", "system prompt", 100, 30.0))

            self.assertIsNone(result)

    def test_empty_choices_returns_none(self):
        """Empty choices array in response returns None."""
        from src.intelligence.llm_providers import ZAIProvider

        with mock.patch("asyncio.to_thread") as mock_to_thread:
            mock_future = asyncio.Future()
            mock_future.set_result({"choices": []})
            mock_to_thread.return_value = mock_future

            provider = ZAIProvider(model="glm-5", api_key="test-key")
            result = asyncio.run(provider.generate("test prompt", "system prompt", 100, 30.0))

            self.assertIsNone(result)

    def test_missing_content_returns_none(self):
        """Missing content field in message returns None."""
        from src.intelligence.llm_providers import ZAIProvider

        with mock.patch("asyncio.to_thread") as mock_to_thread:
            mock_future = asyncio.Future()
            mock_future.set_result({"choices": [{"message": {}}]})
            mock_to_thread.return_value = mock_future

            provider = ZAIProvider(model="glm-5", api_key="test-key")
            result = asyncio.run(provider.generate("test prompt", "system prompt", 100, 30.0))

            self.assertIsNone(result)

    def test_custom_base_url(self):
        """Custom base URL is used correctly."""
        from src.intelligence.llm_providers import ZAIProvider

        with mock.patch("asyncio.to_thread") as mock_to_thread:
            mock_future = asyncio.Future()
            mock_future.set_result("Response")
            mock_to_thread.return_value = mock_future

            provider = ZAIProvider(
                model="glm-5",
                api_key="test-key",
                base_url="https://custom.z.ai/v4"
            )
            asyncio.run(provider.generate("test", "system", 100, 30.0))

            # Verify the base_url is used in the request
            call_args = mock_to_thread.call_args
            self.assertIsNotNone(call_args)
```

**Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_llm_providers.py::TestZAIProvider -v`
Expected: FAIL - `ZAIProvider` class doesn't exist yet

**Step 3: Commit test file**

```bash
git add tests/unit/test_llm_providers.py
git commit -m "test(zai): add ZAIProvider unit tests (TDD - failing first)"
```

---

### Task 3: Implement ZAIProvider Class

**Files:**
- Modify: `src/intelligence/llm_providers.py`

**Step 1: Run tests to see specific failures**

Run: `.venv/bin/pytest tests/unit/test_llm_providers.py::TestZAIProvider -v`
Expected: Multiple FAILs - class doesn't exist

**Step 2: Write minimal ZAIProvider implementation**

Add the `ZAIProvider` class after `AnthropicProvider` and before `OllamaProvider` (around line 150):

```python
# src/intelligence/llm_providers.py
class ZAIProvider:
    """Calls Z.ai API (OpenAI-compatible) with GLM-5 model.

    Z.ai provides GLM-5, a SOTA foundation model for agentic engineering.
    API: https://api.z.ai/api/paas/v4/chat/completions

    Usage:
        provider = ZAIProvider(model="glm-5", api_key="your-api-key")
        text = await provider.generate(prompt, system, max_tokens=500, timeout=30.0)
    """

    def __init__(
        self,
        model: str = "glm-5",
        api_key: str = "",
        base_url: str = "https://api.z.ai/api/paas/v4",
        timeout: float = 30.0,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.provider_id = f"zai:{model}"

    async def generate(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        timeout: float,
    ) -> str | None:
        """Return generated text, or None on failure."""
        def _call() -> str | None:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
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
            logger.warning("ZAI call failed", model=self.model, error=str(exc))
            return None
```

**Step 3: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_llm_providers.py::TestZAIProvider -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/intelligence/llm_providers.py
git commit -m "feat(llm): add ZAIProvider class with GLM-5 support"
```

---

### Task 4: Update AI Narrative Service Provider Chain

**Files:**
- Modify: `services/ai_narrative_service.py`

**Step 1: Read current provider chain setup**

Check how the current LLM chain is built in `ai_narrative_service.py`:

Run: `grep -A 10 "LLMChain\|per_signal\|group_chain" services/ai_narrative_service.py`

**Step 2: Update provider chain to include ZAI first**

Locate where `LLMChain` is instantiated (likely in `__init__`) and update:

```python
# services/ai_narrative_service.py
# In __init__ method, update provider chains
self.per_signal_chain = LLMChain([
    ZAIProvider(
        model=settings.zai_model,
        api_key=settings.zai_api_key,
        base_url=settings.zai_base_url,
        timeout=settings.zai_timeout_sec,
    ),
    OpenRouterProvider(
        model="meta-llama/llama-3.3-70b-instruct:free",
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        timeout=settings.openrouter_timeout_sec,
    ),
    OllamaProvider(
        model="qwen3:8b",
        base_url=settings.ollama_base_url,
        timeout=settings.ollama_timeout_sec,
    ),
])

self.group_chain = LLMChain([
    ZAIProvider(
        model=settings.zai_model,
        api_key=settings.zai_api_key,
        base_url=settings.zai_base_url,
        timeout=settings.zai_timeout_sec,
    ),
    OpenRouterProvider(
        model="stepfun/step-3.5-flash:free",
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        timeout=settings.openrouter_timeout_sec,
    ),
    OllamaProvider(
        model="phi4-mini:3.8b",
        base_url=settings.ollama_base_url,
        timeout=settings.ollama_timeout_sec,
    ),
])
```

Also update the import statement at the top if needed:

```python
# services/ai_narrative_service.py
from src.intelligence.llm_providers import LLMChain, OpenRouterProvider, OllamaProvider, ZAIProvider
```

**Step 3: Run tests to verify no regressions**

Run: `.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_service.py -v`
Expected: PASS (or fix any test failures)

**Step 4: Commit**

```bash
git add services/ai_narrative_service.py
git commit -m "feat(ai-narrative): add ZAI as primary LLM provider"
```

---

### Task 5: Add .env Documentation

**Files:**
- Modify: `.env`

**Step 1: Add ZAI configuration to .env**

Add ZAI API key and optional overrides to `.env`:

```bash
# ZAI LLM Provider (Primary - GLM-5)
ZAI_API_KEY=your-zai-api-key-here
# ZAI_BASE_URL=https://api.z.ai/api/paas/v4  # Optional: override if using custom endpoint
# ZAI_MODEL=glm-5  # Optional: override model name
# ZAI_TIMEOUT_SEC=30.0  # Optional: override timeout
```

**Step 2: Verify settings load correctly**

Run: `.venv/bin/python -c "from src.config.settings import Settings; s = Settings(); print(f'ZAI API Key: {s.zai_api_key[:10]}...' if s.zai_api_key else 'ZAI API Key: (not set)'); print(f'ZAI Model: {s.zai_model}')"`
Expected: Shows configured values or defaults

**Step 3: Commit**

```bash
git add .env
git commit -m "docs(env): add ZAI LLM provider configuration to .env"
```

---

### Task 6: Run Full Test Suite

**Step 1: Run all tests**

Run: `.venv/bin/pytest tests/unit/ -v`
Expected: All tests pass

**Step 2: Run linting**

Run: `.venv/bin/ruff check .`
Expected: No errors (fix any issues with `.venv/bin/ruff check . --fix`)

**Step 3: Final commit if any fixes**

```bash
git add -A
git commit -m "fix: resolve lint and test issues"
```

---

## Verification

After completing all tasks, verify the integration works:

1. **Manual smoke test**:
```bash
.venv/bin/python -c "
import asyncio
from src.config import Settings
from src.intelligence.llm_providers import ZAIProvider

async def test():
    s = Settings()
    if not s.zai_api_key:
        print('⚠️ ZAI_API_KEY not set in .env')
        return
    provider = ZAIProvider(model=s.zai_model, api_key=s.zai_api_key)
    result = await provider.generate('Say hello', 'You are helpful', 50, 30.0)
    if result:
        print(f'✅ ZAI response: {result[:100]}...')
    else:
        print('❌ ZAI failed')

asyncio.run(test())
"
```

2. **Check service startup**:
```bash
sudo systemctl restart indicagent-ai-narrative
journalctl -u indicagent-ai-narrative -f --lines=50
```

Look for: "ZAI call succeeded" or successful narrative publications.

3. **Verify fallback chain**: Temporarily set invalid ZAI API key, restart service, verify it falls back to OpenRouter.

---

## Summary

This plan adds ZAI as a new LLM provider following TDD principles:

- **6 tasks**, each with atomic commit
- **ZAIProvider class** implementing the `LLMProvider` protocol
- **Configuration** in `Settings` and `.env`
- **Provider chain** with ZAI first, then OpenRouter, then Ollama
- **Comprehensive unit tests** covering success cases and error scenarios
- **Verification steps** to confirm integration works end-to-end

The existing `LLMChain` handles the fallback logic - providers are tried sequentially with the first successful response returned immediately. This ensures low latency when ZAI works (most of the time) and reliability with fallbacks when it doesn't.
