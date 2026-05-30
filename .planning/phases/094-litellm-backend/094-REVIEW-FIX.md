---
phase: 094-litellm-backend
fixed_at: 2026-05-29T23:33:30Z
review_path: .planning/phases/094-litellm-backend/094-REVIEW.md
iteration: 1
findings_in_scope: 9
fixed: 9
skipped: 0
status: all_fixed
---

# Phase 094: Code Review Fix Report

**Fixed at:** 2026-05-29T23:33:30Z
**Source review:** .planning/phases/094-litellm-backend/094-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 9 (CR-01 through CR-04, WR-01 through WR-05)
- Fixed: 9
- Skipped: 0

## Fixed Issues

### CR-04: litellm.failure_callback not cleared

**Files modified:** `src/core/llm/litellm_backend.py`
**Commit:** 5c7d111c
**Applied fix:** Added `litellm.failure_callback = []` immediately after `litellm.success_callback = []` in `_configure_litellm()`. This prevents failure telemetry from leaking request metadata (prompt snippets, signal IDs) externally.

---

### CR-03: Double-audit _report_parse_failure called after _llm_generate_structured

**Files modified:** `src/intelligence/ai/alpha/correlation_agent.py`, `src/intelligence/ai/alpha/counterfactual_agent.py`, `src/intelligence/ai/alpha/regime_coherence_agent.py`, `src/intelligence/ai/alpha/skeptic_agent.py`
**Commit:** 23c83531
**Applied fix:** Removed `await self._report_parse_failure(call_id)` from the `result is None` branch in all four agents. Replaced with a comment explaining why it must not be called on the structured path - the chain already publishes a complete failure audit row with `succeeded=False` and `parse_success=False`. The `_report_parse_failure` corrective update is only correct on the unstructured `_llm_generate` path.

---

### CR-01: model parameter silently dropped in generate_structured audit rows

**Files modified:** `src/core/llm/chain.py`
**Commit:** af81a965
**Applied fix:** Changed both `_publish_audit` calls in `generate_structured` from passing the literal string `"instructor"` as the `model` field to passing `provider_id` (already computed at that point). Updated the H1 comment to explain that `generate_structured` always uses the default provider order (model selection not supported in the structured path). The audit row now correctly reflects which actual provider served the call.

---

### CR-02: generate_structured bypasses rate limiter

**Files modified:** `src/core/llm/chain.py`
**Commit:** 003774d5
**Applied fix:** Added rate limiter acquire before calling `self._inner.generate_structured()`, mirroring the pattern in `_generate_inner`. Cache is intentionally skipped for structured calls (Pydantic model instances cannot be round-tripped through the string cache without a schema-version dependency) - this decision is documented in the docstring. The docstring was updated to explain both decisions and note the WR-01 stale-provider limitation that applies to this path as well.

---

### WR-01: Rate limiter uses stale last_provider_id

**Files modified:** `src/core/llm/chain.py`
**Commit:** 1599c0ee
**Applied fix:** Added a detailed explanatory comment in `_generate_inner` at the rate limiter selection line documenting the stale-provider limitation: `last_provider_id` is the provider from the previous call, not the current one; on the first call it is `None` (backend resets it at the start of each call); with circuit-breaker failover the wrong per-provider limit may be applied. The fix notes that addressing this properly requires per-provider limiter selection inside `LiteLLMBackend` and is deferred to a future phase. The CR-02 fix docstring covers the same limitation for the structured path.

---

### WR-02: _OLLAMA_CB_CONFIG and _REMOTE_CB_CONFIG are dead code

**Files modified:** `src/core/llm/litellm_backend.py`
**Commit:** 247c6b7d
**Applied fix:** Reordered the module-level declarations so config constants come first, then circuit breakers are constructed from them (`failure_threshold=_OLLAMA_CB_CONFIG.failure_threshold`, `timeout_sec=_OLLAMA_CB_CONFIG.recovery_timeout`). The config constants remain in place because they carry additional fields (`success_threshold`, `max_half_open_calls`, `failure_window`, `performance_threshold_ms`) not yet wired into the `CircuitBreaker` implementation; these are preserved with a comment for future use as the circuit breaker matures.

---

### WR-03: test_generate_structured_skips_open_circuit mutates shared state without cleanup guarantee

**Files modified:** `tests/unit/test_litellm_backend.py`
**Commit:** 1a859ea9
**Applied fix:** Wrapped the test body in a `try/finally` block. The `finally` clause always resets `_OLLAMA_CB._state = CircuitState.CLOSED` and `_OLLAMA_CB._failures = 0`, even if an assertion fails mid-test. This prevents subsequent tests from seeing a polluted open circuit breaker. The `from src.observability.circuit_breaker import CircuitState` import was moved above the try block so it is available in the finally clause.

---

### WR-04: extra_audit passed twice to generate_structured

**Files modified:** `src/core/ai/base_agent.py`
**Commit:** 42257b5d
**Applied fix:** Removed the `if extra_audit: audit_context.update(extra_audit)` block from `_llm_generate_structured` in `BaseAIAgent`. The chain's `generate_structured` already merges `extra_audit` into the audit row via its own parameter. Pre-merging here and then passing `extra_audit` again caused the fields to appear in `audit_context` via two separate code paths. Replaced the removed block with a comment explaining why the pre-merge must not be done.

---

### WR-05: SkepticComputeAgent.shadow_only = False bypasses fail-closed contract

**Files modified:** `src/intelligence/ai/alpha/skeptic_agent.py`
**Commit:** 72890962
**Applied fix:** Changed `shadow_only = False` to `shadow_only: bool = True` with the same Phase 109 FAIL-CLOSED comment as the other three agents. Added `_apply_shadow_mode_config()` method identical to the pattern in `correlation_agent.py` - reads `ai.agent.skeptic_v1.shadow_mode` from config, defaults to `True` (shadow) on miss, normalizes bool/str inputs. This brings `SkepticComputeAgent` into compliance with CLAUDE.md D-37 ("always True, graduation_loop flips it").

---

## Skipped Issues

None.

---

_Fixed: 2026-05-29T23:33:30Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
