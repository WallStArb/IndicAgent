# ZAI LLM Provider Integration — Design

**Date:** 2026-03-01
**Status:** Approved
**Scope:** `src/intelligence/llm_providers.py`, `src/config/settings.py`, `tests/unit/test_llm_providers.py`

## Problem

ZAI is a new paid LLM subscription using the GLM-5 model (SOTA foundation model for agentic engineering, on par with Claude Opus 4.5). The user wants to use ZAI as the primary LLM for all LLM usage in the system, with OpenRouter and Ollama as fallbacks. The solution must be low-latency (no unnecessary chain iteration) and extensible for adding more providers in the future.

## Design

### Architecture & Components

**Files to modify/create**:
| File | Change |
|------|--------|
| `src/intelligence/llm_providers.py` | Add `ZAIProvider` class (new) |
| `src/config/settings.py` | Add ZAI config fields |
| `tests/unit/test_llm_providers.py` | Add `ZAIProvider` unit tests |
| `.env` | Add `ZAI_API_KEY` env var |

**New class**: `ZAIProvider`

Implements the `LLMProvider` protocol:
- Calls `https://api.z.ai/api/paas/v4/chat/completions` (OpenAI-compatible API)
- Model: `glm-5` (configurable)
- Authentication: `Authorization: Bearer {api_key}`
- Error handling: catch all exceptions, log warning, return `None`

**Provider chain order** (for all LLM usage):
1. **ZAIProvider** (primary - paid GLM-5 subscription)
2. **OpenRouterProvider** (fallback #1)
3. **OllamaProvider** (fallback #2 - local)

**Extensibility**: New providers can be added anywhere in the chain by creating a new class implementing `LLMProvider`.

### Settings & Configuration

**New Settings fields**:

```python
# ZAI (primary)
zai_api_key: str = Field(default="", validation_alias="ZAI_API_KEY")
zai_base_url: str = Field(default="https://api.z.ai/api/paas/v4", validation_alias="ZAI_BASE_URL")
zai_model: str = Field(default="glm-5", validation_alias="ZAI_MODEL")
zai_timeout_sec: float = Field(default=30.0, validation_alias="ZAI_TIMEOUT_SEC")

# OpenRouter timeout (existing, add this)
openrouter_timeout_sec: float = Field(default=30.0, validation_alias="OPENROUTER_TIMEOUT_SEC")

# Ollama timeout (existing, add this)
ollama_timeout_sec: float = Field(default=60.0, validation_alias="OLLAMA_TIMEOUT_SEC")
```

### Provider Implementation

**ZAIProvider class**:

```python
class ZAIProvider:
    """Calls Z.ai API (OpenAI-compatible) with GLM-5 model.

    Z.ai provides GLM-5, a SOTA foundation model for agentic engineering.
    API: https://api.z.ai/api/paas/v4/chat/completions
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

### Provider Chains & Integration

**Provider chain construction** (in services that use LLM):

```python
self.llm_chain = LLMChain([
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
```

**Latency behavior**: Since ZAI is first in the chain, if it works (most of the time) the loop exits immediately on first success. No iteration overhead on the happy path.

### Error Handling

**Provider-level**:
- Each provider catches ALL exceptions internally (HTTP errors, JSON parsing, missing data)
- Logs warning with provider name + error
- Returns `None` on any failure

**LLMChain-level**:
- Tries providers in sequence
- If provider returns `None`, moves to next provider
- Never raises - if ALL fail, returns `None` with `last_provider_id = None`
- Tracks which provider succeeded via `last_provider_id`

**Service-level**:
```python
result = await self.llm_chain.generate(prompt, system, max_tokens, timeout)
if result is None:
    logger.warning("All LLM providers failed", symbol=symbol, timeframe=timeframe)
    return  # Skip this narrative
# Publish successful narrative
await self.redis.xadd(stream_key, {...})
```

**No retries within provider** - the chain IS the retry mechanism.

### Testing

**Unit tests** (`tests/unit/test_llm_providers.py`):

- `test_success_response` - ZAI returns valid content
- `test_timeout_error` - Timeout returns None
- `test_http_429_rate_limit` - HTTP 429 returns None
- `test_empty_choices_returns_none` - Empty choices array returns None

Mock `asyncio.to_thread` at the provider level - no live HTTP calls in unit tests.

**Run**: `.venv/bin/pytest tests/unit/test_llm_providers.py -v`

## Files Changed

| File | Change |
|------|--------|
| `src/intelligence/llm_providers.py` | Add `ZAIProvider` class |
| `src/config/settings.py` | Add ZAI config fields |
| `tests/unit/test_llm_providers.py` | Add `ZAIProvider` unit tests |
| `.env` | Add `ZAI_API_KEY` |

## Future Work

- Add ZAI-specific features like thinking mode (`"thinking": {"type": "enabled"}`)
- Add more providers by inserting new classes into the chain
