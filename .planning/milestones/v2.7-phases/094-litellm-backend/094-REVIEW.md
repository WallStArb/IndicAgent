---
phase: 094-litellm-backend
reviewed: 2026-05-29T00:00:00Z
depth: standard
files_reviewed: 17
files_reviewed_list:
  - src/core/ai/base_agent.py
  - src/core/llm/chain.py
  - src/core/llm/__init__.py
  - src/core/llm/litellm_backend.py
  - src/core/llm/providers.py
  - src/intelligence/ai/alpha/correlation_agent.py
  - src/intelligence/ai/alpha/counterfactual_agent.py
  - src/intelligence/ai/alpha/regime_coherence_agent.py
  - src/intelligence/ai/alpha/skeptic_agent.py
  - src/intelligence/ai/alpha/skeptic_prompts.py
  - tests/unit/intelligence/test_llm_providers.py
  - tests/unit/services/test_correlation_agent.py
  - tests/unit/services/test_counterfactual_agent.py
  - tests/unit/services/test_regime_coherence_agent.py
  - tests/unit/services/test_skeptic_agent.py
  - tests/unit/test_litellm_backend.py
  - tools/duplicate_test_allowlist.txt
findings:
  critical: 4
  warning: 5
  info: 3
  total: 12
status: issues_found
---

# Phase 094: Code Review Report

**Reviewed:** 2026-05-29T00:00:00Z
**Depth:** standard
**Files Reviewed:** 17
**Status:** issues_found

## Summary

Phase 094 implements a LiteLLM-based backend replacing the old per-provider OllamaProvider/OpenRouterProvider classes, wires instructor for structured output, adds circuit breakers, and migrates four alpha agents (skeptic, correlation, counterfactual, regime_coherence) to use `_llm_generate_structured`. The overall design is sound. However four critical correctness defects were found: the `model` parameter passed to `_llm_generate_structured` by `BaseAIAgent` is silently dropped before it reaches `LiteLLMBackend`; `generate_structured` in `LLMProviderChain` skips both the semantic cache and the rate limiter; `_report_parse_failure` is incorrectly called after `_llm_generate_structured` succeeds and then returns `None` - that path already published a failure audit row, meaning a corrective "parse failed" event is published on top of an already-failed row; and `litellm.failure_callback` is never cleared alongside `success_callback`, leaving the telemetry suppression incomplete. Several warnings and info items follow.

---

## Critical Issues

### CR-01: `model` parameter silently dropped in `generate_structured` path

**File:** `src/core/ai/base_agent.py:309-317`

**Issue:** `_llm_generate_structured` accepts a `model` parameter at the `_llm_generate` level only - `BaseAIAgent._llm_generate_structured` never accepts a `model` kwarg at all. More critically, `LLMProviderChain.generate_structured` (chain.py:200-272) does not accept a `model` parameter and does not forward one to `LiteLLMBackend.generate_structured`. The `LiteLLMBackend.generate_structured` signature is also `(prompt, system, response_model, max_tokens, timeout)` with no `model` arg. This means the `model="default"` that `_llm_generate` passes through to the audit trail is never applied in the structured path; the `model` field in the audit row for structured calls is hardcoded to `"instructor"` (chain.py:246, 270) rather than the requested model. This is a silent behaviour divergence: callers expecting model selection via the structured path get no such routing.

**Fix:** Either document that `generate_structured` always uses the default provider order (acceptable), or add `model: str = "default"` to all three call sites and propagate it to `_instructor_client.chat.completions.create_with_completion` as a model override. At minimum, the audit row at chain.py:246 and chain.py:270 should log `"instructor"` in a separate field and pass `provider_id` (already computed at line 229) as the `model` field to `_publish_audit`, not the literal string `"instructor"`.

---

### CR-02: `generate_structured` in `LLMProviderChain` bypasses cache and rate limiter entirely

**File:** `src/core/llm/chain.py:200-272`

**Issue:** `LLMProviderChain.generate` goes through `_generate_inner` which checks the semantic cache (line 132-138) and acquires the rate limiter (lines 140-144). `generate_structured` calls `self._inner.generate_structured()` directly without either guard. Consequently:

1. Structured calls are never cached - identical prompts hit the LLM every call, wasting tokens and latency.
2. Structured calls are never rate-limited - they can saturate `LLM_RATE_LIMITS` regardless of configured RPM/TPM. Given that each structured call may consume 500+ tokens, this is a real risk when multiple agents share a chain instance.

The class docstring claims "SemanticCache -> RateLimiter -> LiteLLMBackend" but the structured path skips the first two stages.

**Fix:** Before calling `self._inner.generate_structured()`, apply the same cache lookup and rate limiter acquire that `_generate_inner` uses. Example:

```python
async def generate_structured(self, prompt, system, response_model, ...):
    # Cache check
    if self._cache_ttl > 0:
        cached = _cache.get(system=system, prompt=prompt, model="instructor")
        if cached is not None:
            # Deserialize and return -- or skip cache for structured (document it)
            ...
    # Rate limiter
    limiter = self._rate_limiters.get(self._inner.last_provider_id) or next(
        iter(self._rate_limiters.values()), None
    )
    if limiter is not None:
        await limiter.acquire(tokens=max_tokens)
    ...
```

---

### CR-03: Double-audit on structured output failure - `_report_parse_failure` called on an already-failed row

**File:** `src/core/ai/base_agent.py:311-317` and `src/intelligence/ai/alpha/correlation_agent.py:111-117`

**Issue:** When `_llm_generate_structured` returns `(None, call_id)`, the caller (all four alpha agents) invokes `await self._report_parse_failure(call_id)`. But `_report_parse_failure` calls `self._llm._publish_parse_failure(call_id)` which publishes `{"call_id": call_id, "parse_success": False, "_parse_update": True}` - a corrective update intended to flip a previously-succeeded row to parse_failed.

However when `generate_structured` in `chain.py` returns `None`, it already published an audit row with `"succeeded": False` and `"parse_success": False` (lines 239-247). The `llm_writer_service` would then receive two events for the same `call_id`: the original failure row AND a corrective `_parse_update` row. If the writer does an UPDATE on a row it already wrote as failed, this is benign but wasteful. More critically, if the writer interprets `_parse_update` as "a previously-succeeded call now failed parsing", it will apply an UPDATE that was never needed. This is a semantic mismatch: `_report_parse_failure` is designed for the `_llm_generate` (unstructured) path where the LLM returns a response but JSON parsing fails - the initial audit row is written as `parse_success=True` and then corrected. The structured path's failure audit is correct without the corrective update.

The four agents call `_report_parse_failure(call_id)` unconditionally when `result is None`, but that is only correct on the `_llm_generate` path. On the `_llm_generate_structured` path it is wrong.

**Fix:** Do not call `_report_parse_failure` after `_llm_generate_structured` returns `None`. Remove lines like:
```python
# correlation_agent.py:116, counterfactual_agent.py:121,
# regime_coherence_agent.py:118, skeptic_agent.py:88
await self._report_parse_failure(call_id)  # REMOVE - already handled by chain
```

---

### CR-04: `litellm.failure_callback` not cleared - telemetry suppression incomplete

**File:** `src/core/llm/litellm_backend.py:61-72`

**Issue:** `_configure_litellm` sets `litellm.success_callback = []` (line 71) to prevent LiteLLM from sending success telemetry. However `litellm.failure_callback` is never cleared. LiteLLM's default failure callback includes telemetry and logging to its hosted service. Any API key failure, timeout, or error will invoke the default failure callback and may send request metadata externally, including prompt snippets or error messages containing sensitive data (symbols, signal IDs).

```python
def _configure_litellm(settings) -> None:
    import litellm
    os.environ.setdefault("OLLAMA_API_BASE", settings.ollama_base_url)
    if settings.openrouter_api_key:
        os.environ.setdefault("OPENROUTER_API_KEY", settings.openrouter_api_key)
    litellm.telemetry = False
    litellm.success_callback = []
    # litellm.failure_callback never cleared <-- BUG
```

**Fix:**
```python
litellm.telemetry = False
litellm.success_callback = []
litellm.failure_callback = []  # add this line
```

---

## Warnings

### WR-01: Rate limiter uses stale `last_provider_id` (pre-call value) to select limiter

**File:** `src/core/llm/chain.py:140-144`

**Issue:** The rate limiter is acquired using `self._inner.last_provider_id` (line 140), which is the provider that served the *previous* call, not the provider that will serve the current call. `LiteLLMBackend.generate` resets `last_provider_id = None` at the start of each call (litellm_backend.py:129), so on the very first call, `last_provider_id` is `None` and the limiter falls back to `next(iter(self._rate_limiters.values()), None)` - effectively the first configured limiter. On subsequent calls, the limiter is keyed to the *previous* call's provider, not the current one. If the previous call used `ollama/` but the current call will use `openrouter/` (due to circuit breaker), the wrong limiter is applied.

**Fix:** Rate limiting should be applied per-provider inside `LiteLLMBackend.generate` where the actual provider is known, or rate limiter selection deferred until after `_inner.generate` returns. Alternatively, apply the limiter for each candidate provider inside the provider loop in the backend.

---

### WR-02: `_OLLAMA_CB_CONFIG` and `_REMOTE_CB_CONFIG` are dead code

**File:** `src/core/llm/litellm_backend.py:43-58`

**Issue:** `_OLLAMA_CB_CONFIG` and `_REMOTE_CB_CONFIG` are defined as module-level constants (lines 43-58) but are never referenced anywhere in the file or imported by any other module. The actual `_OLLAMA_CB` and `_REMOTE_CB` `CircuitBreaker` instances use their own hardcoded `failure_threshold`/`timeout_sec` values (lines 31-40) that differ from the configs (e.g., `_REMOTE_CB_CONFIG.recovery_timeout=300` vs `_REMOTE_CB.timeout_sec=300` - those match, but `_OLLAMA_CB_CONFIG.failure_threshold=5` and `_OLLAMA_CB_CONFIG.recovery_timeout=60` match by coincidence while `_OLLAMA_CB_CONFIG.failure_window=120`, `success_threshold=1`, `max_half_open_calls=3`, `performance_threshold_ms=120000` have no effect). If someone changes `_OLLAMA_CB_CONFIG`, it will have zero effect on behavior.

**Fix:** Remove the dead constants or derive the `CircuitBreaker` construction from them:
```python
_OLLAMA_CB = CircuitBreaker(
    failure_threshold=_OLLAMA_CB_CONFIG.failure_threshold,
    timeout_sec=_OLLAMA_CB_CONFIG.recovery_timeout,
    name="litellm_ollama",
)
```

---

### WR-03: `test_generate_structured_skips_open_circuit` mutates shared module-level circuit breaker state

**File:** `tests/unit/test_litellm_backend.py:389-431`

**Issue:** The test directly manipulates `_OLLAMA_CB._state` and `_OLLAMA_CB._failures` at the end (lines 430-431) to reset the shared module-level circuit breaker. Because `_OLLAMA_CB` is a module-level singleton, if any earlier assertion in the test fails (e.g., `assert not ollama_called` at line 425), the cleanup lines at 430-431 are never reached. Subsequent tests that rely on `_OLLAMA_CB` being closed (e.g., `test_generate_structured_falls_back_to_secondary_provider`, `test_generate_structured_failures_trip_same_circuit_breaker`) will see a polluted open circuit breaker and may fail or produce false results.

This is a test isolation failure that can cause false negatives in CI when tests run in order.

**Fix:** Use a `try/finally` block or a pytest fixture to ensure cleanup always runs:
```python
try:
    result = await backend.generate_structured(...)
    assert not ollama_called, "..."
finally:
    _OLLAMA_CB._state = CircuitState.CLOSED
    _OLLAMA_CB._failures = 0
```

---

### WR-04: `_llm_generate_structured` passes `extra_audit` twice - once already merged into `audit_context`, then passed again to `generate_structured`

**File:** `src/core/ai/base_agent.py:306-317`

**Issue:** In `_llm_generate_structured` (base_agent.py), `extra_audit` fields are merged into `audit_context` at lines 306-307:
```python
if extra_audit:
    audit_context.update(extra_audit)
```
Then at line 316, both `audit_context` (which already includes `extra_audit` fields) AND `extra_audit` are passed to `generate_structured`:
```python
result = await self._llm.generate_structured(
    ...
    audit_context=audit_context,
    extra_audit=extra_audit,   # <-- redundant
)
```
In `chain.generate_structured`, at lines 239-240 and 267-268, `extra_audit` is merged into `audit_context` again with `failure_audit.update(extra_audit or {})`. Since `audit_context` already contains those keys from the base agent merge, the second merge is a no-op - not harmful in itself, but it means `extra_audit` fields appear in `audit_context` via two separate code paths, and any future consumer of `extra_audit` in `chain.generate_structured` that expects it to contain *only* extra fields (not already-merged ones) would be misled.

**Fix:** In `base_agent._llm_generate_structured`, do not pre-merge `extra_audit` into `audit_context` before passing to `chain.generate_structured`. Instead let chain handle the merging (as it already does). Or remove the `extra_audit` parameter from `chain.generate_structured` and rely on it being pre-merged by the caller.

---

### WR-05: `SkepticComputeAgent.shadow_only = False` - live agent without config-driven promotion gate

**File:** `src/intelligence/ai/alpha/skeptic_agent.py:55`

**Issue:** `SkepticComputeAgent` hardcodes `shadow_only = False` at the class level. The three other alpha agents (correlation, counterfactual, regime_coherence) all default to `shadow_only = True` and implement `_apply_shadow_mode_config()` for config-driven promotion with fail-closed semantics per Phase 109 design. The skeptic agent bypasses this entirely - it is live from the moment the service starts, regardless of config. The docstring comment "live agent - not in shadow mode" gives no rationale for why it is exempt from the Phase 109 fail-closed rule.

CLAUDE.md states: "D-37: always True, graduation_loop flips it". A class-level `False` contradicts this contract.

**Fix:** Apply the same pattern as the other three agents: default `shadow_only = True`, implement `_apply_shadow_mode_config()`, and require an explicit config entry to promote to live.

---

## Info

### IN-01: `_SYSTEM_MESSAGE` for skeptic does not end with "Begin your response with { and end with }."

**File:** `src/intelligence/ai/alpha/skeptic_agent.py:25-32`

**Issue:** CLAUDE.md requires: "Also add 'Begin your response with { and end with }.' at end of user prompt." The skeptic v2 prompt template in `skeptic_prompts.py` (line 101) includes this instruction, but the `_SYSTEM_MESSAGE` system prompt does not. The correlation, counterfactual, and regime_coherence agents' system messages all end with `"Your entire response must be a single JSON object starting with { and ending with }."` which satisfies the rule. The skeptic system message ends at `'reasoning must be under 100 words.'` without the start/end reminder. Minor risk since gemma4:e4b may still emit prose preamble.

**Fix:** Add to `_SYSTEM_MESSAGE` in `skeptic_agent.py`:
```python
_SYSTEM_MESSAGE = (
    "OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE. "
    "Your entire response must be a single JSON object starting with { and ending with }. "
    "Schema: "
    '{"failure_probability": float, "confidence": float, '
    '"risk_factors": [str], "reasoning": str} '
    "reasoning must be under 100 words."
)
```
(The `{ and ending with }` clause needs to be added explicitly.)

---

### IN-02: `src/core/llm/providers.py` is now an empty stub that could be removed

**File:** `src/core/llm/providers.py`

**Issue:** The file contains only a module docstring and `from __future__ import annotations`. All provider classes were removed in Phase 094-02. Any import of `from src.core.llm.providers import ...` will now raise `ImportError`. If it is truly dead, it should be removed to avoid confusion. If it is kept as a migration anchor, it should at minimum export something or raise a helpful error.

**Fix:** Delete the file if no consumers remain, or add deprecation warnings.

---

### IN-03: `test_build_prompt_fills_fields` assertion `assert "N/A" not in prompt` is fragile

**File:** `tests/unit/services/test_skeptic_agent.py:61`

**Issue:** The test asserts `"N/A" not in prompt` after constructing a v1 dict with all fields populated. However `fmt(None, spec)` returns `"N/A"` for `None` values. Several dict keys in the test (`ts`, `vol_percentile`, `garch_vol_regime`, `kalman_trend`, `kalman_slope`, `ctf_score`, `ctf_structure_alignment`, `ctf_timeframes_aligned`) are set to `None`. None of these keys are present in the v1 prompt template, so `N/A` will not appear - the test passes, but only because the template does not reference those keys. If the v1 template is updated to reference any of them, the `None` entries will produce `N/A` and the test will silently break the assertion. The test provides false confidence about complete field coverage.

**Fix:** Remove the `N/A` assertion or explicitly only populate the fields the v1 template actually uses.

---

_Reviewed: 2026-05-29T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
