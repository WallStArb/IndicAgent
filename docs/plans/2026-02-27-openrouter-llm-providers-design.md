# OpenRouter LLM Provider Integration — Design

**Date:** 2026-02-27
**Status:** Approved
**Scope:** `src/intelligence/llm_providers.py`, `services/ai_narrative_service.py`

## Problem

Both LLM calls in the narrative service (per-signal via `qwen3:8b`, group synthesis via
`phi4-mini:3.8b`) run on local CPU via Ollama. Each call takes 30–60s, saturating the CPU
and causing system-wide lag. OpenRouter provides free cloud inference that is orders of
magnitude faster with no local CPU cost.

## Design

### Provider Abstraction (`src/intelligence/llm_providers.py`)

A `LLMProvider` protocol with a single async method:

```python
class LLMProvider(Protocol):
    async def generate(
        self, prompt: str, system: str, max_tokens: int, timeout: float
    ) -> str | None: ...
```

Two implementations:

- **`OpenRouterProvider`** — calls `https://openrouter.ai/api/v1/chat/completions` with
  `Authorization: Bearer <OPENROUTER_API_KEY>`. OpenAI-compatible request format.
- **`OllamaProvider`** — calls `http://localhost:11434/api/chat`. Existing logic extracted
  from `call_ollama_async`.

Both use `asyncio.to_thread` for the blocking HTTP call.

**`LLMChain`** accepts an ordered list of providers. `generate()` tries each in sequence,
returning the first non-None result. A failing provider logs a warning and yields to the
next. Never raises — if all fail, returns `None`.

### Provider Chains

```python
per_signal_chain = LLMChain([
    OpenRouterProvider("meta-llama/llama-3.3-70b-instruct:free"),
    OpenRouterProvider("arcee-ai/trinity-large-preview:free"),
    OllamaProvider("qwen3:8b"),
])

group_chain = LLMChain([
    OpenRouterProvider("stepfun/step-3.5-flash:free"),
    OpenRouterProvider("arcee-ai/trinity-large-preview:free"),
    OllamaProvider("phi4-mini:3.8b"),
])
```

### Config

```python
"per_signal_providers": [
    {"type": "openrouter", "model": "meta-llama/llama-3.3-70b-instruct:free"},
    {"type": "openrouter", "model": "arcee-ai/trinity-large-preview:free"},
    {"type": "ollama",     "model": "qwen3:8b"},
],
"group_providers": [
    {"type": "openrouter", "model": "stepfun/step-3.5-flash:free"},
    {"type": "openrouter", "model": "arcee-ai/trinity-large-preview:free"},
    {"type": "ollama",     "model": "phi4-mini:3.8b"},
],
"openrouter_timeout_sec": 30.0,
"ollama_timeout_sec": 60.0,
```

`OPENROUTER_API_KEY` read from `Settings` / `.env`.

### Narrative Service Changes

- Replace `call_ollama_async` at both call sites with the appropriate chain.
- `self.per_signal_chain` and `self.group_chain` built in `__init__` from config.
- Existing `call_ollama_async` function removed.
- `published_by` field added to stream messages (provider+model that succeeded).

### Error Handling

- Each provider catches all exceptions internally — logs warning with provider name and
  error, returns `None`.
- 429 rate-limit treated same as any other failure: fall through to next provider.
- No retry within a provider — the chain is the retry mechanism.
- If all providers fail: `None` returned, no narrative published. Fingerprint already
  saved before the call, so no retry loop.

## Testing

**Unit tests** (`tests/unit/test_llm_providers.py`):
- `OpenRouterProvider`: success, timeout, HTTP 429, HTTP 500
- `OllamaProvider`: success, timeout, error
- `LLMChain`: first-succeeds, first-fails-second-succeeds, all-fail-returns-None

Mock `asyncio.to_thread` at the provider level — no live HTTP calls in unit tests.

## Files Changed

| File | Change |
|------|--------|
| `src/intelligence/llm_providers.py` | **New** — protocol + 2 providers + chain |
| `services/ai_narrative_service.py` | Replace `call_ollama_async` with chains |
| `tests/unit/test_llm_providers.py` | **New** — unit tests |
