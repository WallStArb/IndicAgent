# LLM Inference Hardening Design

**Date:** 2026-05-17
**Status:** Approved
**Scope:** `src/core/llm/providers.py`, `src/core/llm/chain.py`, `src/config/settings.py`, alpha agent files (4x)

---

## Problem Statement

Five distinct failure classes were identified through live incident analysis (Ollama runner pinned at 203% CPU for 25+ minutes, 86°C temps, correlation agent JSON parse failures in production logs):

| # | Class | Symptom | Root Cause |
|---|---|---|---|
| 1 | Correctness | Zombie Ollama runners burn CPU indefinitely | `to_thread(urllib, stream=False)` — asyncio cancellation orphans the thread; socket never closes |
| 2 | Data quality | Truncated JSON → parse failures | `num_ctx` unset; Ollama defaults to 4096; full-context prompts + `max_tokens=2000` overflows |
| 3 | Compute waste | 5-10x token overspend per call | `max_tokens=2000` for agents with 200-400 token output schemas; model writes essays in `reasoning` |
| 4 | Thinking token leak | Silent wasted tokens per call | Alpha agent system messages missing `/no_think` prefix; `"think": False` API flag unreliable per existing comment |
| 5 | Single point of failure | Ollama outage = zero LLM inference | `_build_providers` ignores `settings.openrouter_models` / `settings.openrouter_api_key` already in Settings |

Evidence of failure 2 in live logs (2026-05-17):
```
"raw_response": "...\"reasoning\": \"EURUSD's downtrend aligns with risk-on conditions (falling ZN) and volatility contraction (low "
```
Response truncated mid-sentence at `num_predict=2000` limit, producing invalid JSON.

---

## Design

Five targeted fixes at five distinct layers. The `LLMProvider` protocol, `LLMChain`, `LLMProviderChain.generate()`, `BaseAIAgent`, all DAG services, Kafka topics, and DB schemas are unchanged.

---

### Fix 1 — Transport Layer: `OllamaProvider` async httpx streaming

**File:** `src/core/llm/providers.py`

Replace `to_thread(urllib, stream=False)` in `OllamaProvider.generate()` with native async `httpx.AsyncClient` streaming (`stream=True`). `httpx>=0.27.0` is already in requirements.

Key properties:
- **Shared client:** `httpx.AsyncClient` instantiated once per `OllamaProvider` instance (connection pool). Not per-request.
- **Cancellation propagates:** When `asyncio.wait_for` fires at `latency_budget_ms`, the coroutine cancels, the `async with client.stream(...)` context closes the socket, Ollama receives `ECONNRESET` and halts generation. Runner exits cleanly.
- **Streaming read:** Accumulate token chunks from `response.aiter_lines()` until `"done": true`. Strip thinking tags on the assembled response.
- **Lifecycle:** `OllamaProvider` gains an `async def close()` method; `LLMProviderChain` calls it on service shutdown.

`_OpenAICompatProvider` (OpenRouter, DeepSeek) stays `to_thread` + urllib. Remote providers close connections via network-level timeouts — the broken pattern is specific to localhost.

**Retry policy change:** Remove `TimeoutError` from Ollama's `retry_with_backoff` retry set. A timed-out Ollama call means the model is saturated — retrying adds load and delays fallback to OpenRouter. Fail fast.

---

### Fix 2 — Config Layer: `OLLAMA_NUM_CTX` in Settings

**File:** `src/config/settings.py`

Add:
```python
ollama_num_ctx: int = Field(
    default=16384,
    validation_alias="OLLAMA_NUM_CTX",
    description="Ollama context window size. qwen3.5:4b supports 32K; 16384 gives ~14K headroom for full-context prompts plus response.",
)
```

Pass in every Ollama API call:
```python
"options": {"num_predict": max_tokens, "num_ctx": self._num_ctx}
```

`self._num_ctx` set from `settings.ollama_num_ctx` at `OllamaProvider.__init__`. Default 16384 supports the largest alpha prompts (skeptic: ~2000 input tokens) plus max response with >13K headroom.

---

### Fix 3 — Agent Layer: right-size `max_tokens` + concise reasoning

**Files:** `src/intelligence/ai/alpha/skeptic_agent.py`, `correlation_agent.py`, `regime_coherence_agent.py`, `counterfactual_agent.py`

| Agent | Current | New | Rationale |
|---|---|---|---|
| `skeptic_v1` | 2000 | 500 | Schema: `{float, float, [str], str}` — 200-400 tokens sufficient |
| `correlation_v1` | 2000 | 500 | Same schema shape |
| `regime_coherence_v1` | 2000 | 500 | Same schema shape |
| `counterfactual_v1` | 2000 | 500 | Same schema shape |
| `narrative_agent` | 300 | 300 | Already correctly sized — no change |

Add to each agent's `_SYSTEM_MESSAGE`: append `" Keep reasoning under 100 words."` This eliminates the truncated-JSON failure mode by keeping the `reasoning` field concise, while providing enough context for the multiplier logic.

---

### Fix 4 — Prompt Layer: `/no_think` prefix on alpha system messages

**Files:** `src/intelligence/ai/alpha/skeptic_agent.py`, `correlation_agent.py`, `regime_coherence_agent.py`, `counterfactual_agent.py`

Prepend `/no_think\n\n` to each agent's `_SYSTEM_MESSAGE` constant. This follows the established pattern in `narrative_prompts.py` and `src/intelligence/ai/narrative/prompts.py`. Suppresses qwen3.5's chain-of-thought at the model level, not just via unreliable API flag. System messages are not versioned — no prompt registry change needed.

---

### Fix 5 — Chain Layer: wire OpenRouter fallback

**File:** `src/core/llm/chain.py`

Replace `_build_providers` in `LLMProviderChain`:

```python
def _build_providers(self, settings: Any) -> list:
    providers = [OllamaProvider(model=settings.ollama_model, base_url=settings.ollama_base_url)]
    if settings.openrouter_api_key:
        for model in settings.openrouter_models:
            providers.append(OpenRouterProvider(model=model, api_key=settings.openrouter_api_key))
    return providers
```

`LLMChain` already handles ordered fallback — first non-None wins. When Ollama's circuit breaker opens (5 failures in 120s window), the chain falls through to OpenRouter free tier automatically. Zero operator intervention required.

Import `OpenRouterProvider` at the top of `chain.py` — it exists in `providers.py` but is not currently imported.

---

## What Changes / What Doesn't

**Changes:**
- `src/core/llm/providers.py` — `OllamaProvider`: urllib → httpx streaming, shared client, `num_ctx` option, remove TimeoutError from retry
- `src/config/settings.py` — add `OLLAMA_NUM_CTX` field
- `src/core/llm/chain.py` — `_build_providers` wires OpenRouter; import `OpenRouterProvider`
- `src/intelligence/ai/alpha/skeptic_agent.py` — `max_tokens` 2000→500, `/no_think` + concise reasoning in system message
- `src/intelligence/ai/alpha/correlation_agent.py` — same
- `src/intelligence/ai/alpha/regime_coherence_agent.py` — same
- `src/intelligence/ai/alpha/counterfactual_agent.py` — same

**Unchanged:**
- `LLMProvider` protocol
- `LLMChain`
- `LLMProviderChain.generate()` and all middleware (cache, rate limiter, guardrails, budget, audit)
- `BaseAIAgent` and `_llm_generate()`
- All other agent files
- All DAG services, systemd units, Kafka topics, DB schemas
- `_OpenAICompatProvider` (OpenRouter, DeepSeek transport)

---

## Observability

No new metrics needed — existing instrumentation captures the improvements:
- `ai_agent.timeout` log entries will stop appearing once timeout enforcement works
- `correlation_agent.json_parse_failed` / `skeptic_agent.json_parse_failed` counters should drop to near zero
- `AI_AGENT_DURATION_MS` histogram will show faster P95/P99 latencies once token waste is cut
- Circuit breaker transitions to OpenRouter will log via existing `llm_circuit_opened` / `llm_circuit_half_open` events

---

## Risk

Low. All changes are internal to the LLM provider layer. The `LLMProvider` protocol and everything above it are untouched. OpenRouter fallback is additive — if `openrouter_api_key` is empty, `_build_providers` returns Ollama-only (backward compatible).

One forward-looking note: `_OpenAICompatProvider` uses `stream=False` via `to_thread`. This is safe for remote providers today. If a second local provider is ever added (e.g., local vLLM), it must use the async httpx streaming pattern established here, not inherit from `_OpenAICompatProvider`.
