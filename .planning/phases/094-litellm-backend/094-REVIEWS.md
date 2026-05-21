---
phase: 094
reviewers: [gemini, codex]
reviewed_at: 2026-05-20T19:30:00Z
plans_reviewed: [093-01-PLAN.md, 093-02-PLAN.md]
---

# Cross-AI Plan Review — Phase 093: LiteLLM Backend

## Gemini Review

### Summary
The plan provides a clean, incremental, and TDD-driven approach to replacing the custom `LLMChain` architecture with `LiteLLM`. By isolating the transition into two waves — first building a compatible backend and then wiring it into the existing facade — the plan minimizes the risk of breaking critical `LLMProviderChain` consumers. The focus on preserving the side-effect-based state management (`last_provider_id`) while adhering to the existing return type (`str | None`) demonstrates a strong understanding of the system's existing architectural constraints.

### Strengths
- **Backward Compatibility:** The strict adherence to `str | None` return type and preservation of the side-effect attribute pattern ensures minimal disruption to the swarm agents.
- **Wave-based Progression:** Separation of backend creation (Wave 1) from facade integration (Wave 2) allows for clear verification points.
- **Circuit Breaker Continuity:** Explicitly retaining `PluginCircuitBreaker` instances aligns with existing platform standards for resiliency.
- **Test Coverage:** The TDD approach correctly identifies failure modes (provider failure, all-fail scenarios, fallback logic) that are critical for stability in a production environment.

### Concerns
- **MEDIUM:** `LiteLLMBackend` will now handle state internally. If `LiteLLMBackend` is used concurrently (e.g., multiple swarm agents calling the same instance), `last_provider_id` and `last_token_usage` will likely suffer from race conditions. The plan should ensure `LiteLLMBackend` is either stateless per request or that instance-per-chain isolation is maintained.
- **LOW:** LiteLLM brings in a large number of dependencies. Ensure the deployment pipeline supports this increased package size and that no conflicting versions exist in `uv.lock`.
- **MEDIUM:** While the plan mentions that Kafka audit callbacks are "preserved," it assumes `LiteLLMBackend` can trigger these exactly as `LLMChain` did. Ensure the hooks are called within `LiteLLMBackend.generate()` to maintain complete audit parity.
- **LOW:** Verify that the configuration parsing correctly maps existing settings (e.g., timeouts, base URLs) to the format expected by LiteLLM's `acompletion`.

### Suggestions
- Explicitly define `LiteLLMBackend` instances as scoped to an `LLMProviderChain` instance to avoid shared state mutations across concurrent requests.
- Add a specific test case to verify that a mock audit callback is successfully triggered by `LiteLLMBackend.generate()`, ensuring no loss of observability.
- Since the plan intends to delete `OllamaProvider` and `OpenRouterProvider` classes eventually, ensure that the `providers.py` cleanup is tracked as a formal sub-task once the unit tests no longer reference them.
- Keep `litellm` pinned to a specific minor version in `requirements.txt` to prevent auto-updates from breaking the model-string routing logic in production.

### Risk Assessment
**LOW.** The core architecture of the high-level `LLMProviderChain` is preserved, acting as a sandbox for the backend swap. The clear separation of concerns, combined with TDD, significantly reduces the probability of regression. The primary risks are related to side-effect state management and observability, both of which are addressed by the proposed unit testing strategy.

---

## Codex Review

### Summary
Both plans correctly identify the most important compatibility constraint: the replacement backend must keep `generate() -> str | None` and expose `last_provider_id` / `last_token_usage` as side-effect attributes. Plan 093-01 is a reasonable TDD slice for introducing the backend, but it underspecifies several LiteLLM-specific behaviors that affect correctness, audit parity, and security. Plan 093-02 has a larger problem: its stated scope conflicts with the phase success criteria because it explicitly keeps `OllamaProvider`, `OpenRouterProvider`, and `LLMChain` in `providers.py`, while the phase requires those classes deleted and `git grep` showing zero references.

### Plan 093-01 Strengths
- Correctly protects the critical return-value contract: `str | None`, not tuple.
- Tests cover primary success, fallback, total failure, provider list construction, and token usage.
- Separates backend creation from outer `LLMProviderChain`, which lowers migration risk.
- Preserves provider tracking through `last_provider_id` and `last_token_usage`.
- Calls out distinct circuit breaker thresholds for local Ollama vs remote providers.

### Plan 093-01 Concerns
- **HIGH:** LiteLLM provider configuration is underspecified. The plan does not say how `ollama_base_url`, `ollama_num_ctx`, `think=False`, OpenRouter API key, and OpenRouter model prefixing are passed to `litellm.acompletion()`. Those details are needed for parity with the current providers.
- **HIGH:** Provider ID format is vague. Tests only assert `"ollama"` / `"openrouter"` containment, but audit rows, rate limit lookup, metrics labels, and dashboards may depend on stable IDs like `ollama:<model>` and `openrouter:<model>`.
- **HIGH:** Token usage extraction is underspecified. LiteLLM may return usage as an object, dict-like structure, or model object depending on version/provider. Tests should force normalization to a plain dict with expected keys.
- **MEDIUM:** "Automatic retries" are part of the phase goal, but the plan only mentions circuit breakers. It should specify whether retries are LiteLLM retries, existing `retry_with_backoff`, or both, and ensure fallback does not multiply retry counts excessively.
- **MEDIUM:** Failure handling should reset `last_provider_id` and `last_token_usage` at the start of each call or after all providers fail. Otherwise stale values can leak into audit/metrics after exceptions.
- **MEDIUM:** Circuit breaker behavior is not fully test-covered. The listed tests do not prove open-circuit short-circuiting, threshold behavior, half-open recovery, or that Ollama and OpenRouter use separate breakers.
- **MEDIUM:** Security/privacy behavior is missing. LiteLLM has logging/callback features; the plan should explicitly disable verbose prompt logging and avoid leaking prompts/API keys.
- **LOW:** `uv pip install litellm` is an environment step; if the repo uses a lock file, the plan should update it too.
- **LOW:** The version floor `litellm>=1.40.0` may be too loose for consistent response schemas.

### Plan 093-01 Suggestions
- Specify exact model strings and provider IDs separately: LiteLLM model `ollama/<model>`, provider ID `ollama:<model>`; LiteLLM model `openrouter/<model>`, provider ID `openrouter:<model>`.
- Add tests for: `ollama_enabled=False` skips Ollama; OpenRouter model strings whitespace-stripped; `last_provider_id` reset on total failure; `last_token_usage` normalizes both object and dict usage; LiteLLM called with `api_base`, `api_key`, `max_tokens`, timeout, and Ollama options.
- Add a small `_normalize_usage(response) -> dict | None` helper.
- Disable or configure LiteLLM logging/telemetry explicitly.

### Plan 093-01 Risk Assessment: MEDIUM
Without stronger tests around provider config, token usage normalization, retries, and provider ID stability, it may pass unit tests while failing audit parity or live calls.

### Plan 093-02 Strengths
- Correctly keeps `LLMProviderChain.generate()` and `_generate_inner()` unchanged.
- Correctly recognizes that `LiteLLMBackend.providers` is `list[str]`, so `close()` cannot iterate provider objects.
- Adds a wire-up test proving `LLMProviderChain` constructs `LiteLLMBackend`.
- Includes live smoke testing and service restart verification.
- Calls out zero modifications for `BaseGroupService` and swarm agents.

### Plan 093-02 Concerns
- **HIGH:** The scope boundary directly conflicts with the phase success criteria and LLM-INFRA-05. The phase says `OllamaProvider`, `OpenRouterProvider`, and `LLMChain` classes are deleted and `git grep` finds zero references. Plan 093-02 says not to delete them from `providers.py`.
- **HIGH:** "All existing unit tests pass" is incompatible with deleting `_build_providers` and moving away from provider objects unless existing tests are updated. Current tests directly cover `LLMChain`, `OllamaProvider`, `OpenRouterProvider`, and `LLMProviderChain._build_providers`.
- **HIGH:** Leaving old classes in `providers.py` means custom HTTP code remains, violating success criterion 1: "no custom HTTP code remains."
- **MEDIUM:** `close()` as `pass` may be acceptable, but the plan should confirm LiteLLM has no persistent client cleanup requirement. A `pass` with a comment is better than bare `pass`.
- **MEDIUM:** `_generate_inner()` uses `self._inner.last_provider_id` before the call to pick a rate limiter. If provider IDs change format (from `ollama:model` to `ollama/model`), this may silently miss rate limit buckets.
- **MEDIUM:** The grep assertion allows references inside `providers.py`, but the phase wants zero references after deletion.
- **MEDIUM:** Smoke test depends on local Ollama; the plan should define skip/diagnostic behavior if Ollama is not running.
- **LOW:** Restarting systemd services from a phase plan may not be autonomous in every environment.
- **LOW:** Documentation references such as `src/intelligence/CLAUDE.md` mention the old provider chain and are not updated.

### Plan 093-02 Suggestions
- Split Plan 093-02 into two explicit substeps: (1) wire chain.py to LiteLLMBackend; (2) delete old provider classes and update all imports/tests/docs.
- Replace the scope boundary with the actual phase requirement: delete `OllamaProvider`, `OpenRouterProvider`, and `LLMChain` from `providers.py`.
- Update `tests/unit/intelligence/test_llm_providers.py`: remove or rewrite old provider tests; move provider-list tests to `LiteLLMBackend`.
- Strengthen grep acceptance: `git grep 'class OllamaProvider\|class OpenRouterProvider\|class LLMChain' -- src/core/llm` expected zero matches.
- Add a test proving `last_provider_id` and token usage flow into audit payload after a LiteLLM-backed call.
- Use an async no-op close with a short comment, not bare `pass`.

### Plan 093-02 Risk Assessment: HIGH
The integration plan preserves the public interface, but it does not actually complete the phase because it keeps the old provider classes and custom HTTP implementation. Existing tests will fail unless explicitly rewritten.

### Overall Assessment
The phase is achievable, but the plans need tighter acceptance criteria around deletion, provider ID stability, LiteLLM request configuration, usage normalization, and existing test migration.

---

## Consensus Summary

### Agreed Strengths (both reviewers)
- **Return type protection:** Both reviewers explicitly called out that the `str | None` return type constraint is correctly enforced at multiple layers (docstring, must_haves, tests, acceptance criteria). This is the highest-risk integration point and is well-protected.
- **Wave separation:** Both reviewers agreed the Wave 1 (backend creation) / Wave 2 (integration) split is sound and reduces migration risk.
- **Circuit breaker continuity:** Both reviewed the PluginCircuitBreaker reuse positively.
- **TDD discipline:** Both reviewers confirmed the RED-before-GREEN test sequencing is sound.

### Agreed Concerns (both reviewers or HIGH from one)

1. **Provider ID format stability (HIGH - Codex; LOW - Gemini):** The existing code uses `ollama:model` format (e.g., from `OllamaProvider.provider_id`). LiteLLM's model string format uses `ollama/model`. The `LLMProviderChain._generate_inner()` rate limiter lookup `self._rate_limiters.get(self._inner.last_provider_id)` and audit payload both depend on a stable `provider_id` format. If the format changes from `:` to `/` separator, rate limiter lookups silently miss and dashboards break.

2. **Dead-code removal completeness (HIGH - Codex; LOW - Gemini):** Plan 02's scope boundary ("do NOT delete class definitions from providers.py") conflicts with LLM-INFRA-05 and success criterion 1 ("no custom HTTP code remains"). The plan needs to either (a) delete the classes or (b) explicitly defer deletion to a follow-up and note the conflict with success criteria.

3. **Concurrent state safety (MEDIUM - both):** `last_provider_id` and `last_token_usage` are instance attributes mutated per-call. If a single `LiteLLMBackend` instance is shared across concurrent callers (e.g., two swarm agents fire simultaneously), values will cross-contaminate between calls. Since `LiteLLMBackend` is constructed inside `LLMProviderChain.__init__()` and each chain instance is per-agent, this is likely safe — but the plan should confirm this explicitly.

4. **Token usage normalization (HIGH - Codex; implicit - Gemini):** LiteLLM may return `response.usage` as a Pydantic model object rather than a plain dict. The `isinstance(token_usage, dict)` check in `_generate_inner()` at line 210 may then always be False, causing `actual_total` to always be None and falling back to the estimated formula. Tests should force normalization.

### Divergent Views

- **Overall risk level:** Gemini assessed LOW risk; Codex assessed MEDIUM/HIGH. The divergence is explained by Codex specifically flagging the `providers.py` deletion gap (which Gemini didn't weigh as heavily) and the provider ID format change risk.

- **Dead-code scope:** Gemini suggested providers.py cleanup as a "formal sub-task tracked for later." Codex said it must happen in this phase to satisfy LLM-INFRA-05. The ROADMAP success criteria support Codex's position.

### Priority Actions Before Execution

1. **Resolve providers.py deletion scope** — Either update Plan 02 to include deleting `OllamaProvider`, `OpenRouterProvider`, `LLMChain` from `providers.py` (and updating existing provider tests), or explicitly note in the plan that LLM-INFRA-05 "zero references" applies only to `chain.py` and production callers (not test files or `providers.py` class definitions themselves). Get explicit alignment on which interpretation is intended.

2. **Lock provider_id format** — Decide: will `LiteLLMBackend.last_provider_id` use `ollama/<model>` (LiteLLM model string) or `ollama:<model>` (current format used by rate limiter bucket keys and audit payloads)? Update tests to pin the exact format, and verify `_rate_limiters.get(last_provider_id)` still finds the right bucket.

3. **Token usage normalization** — Add `_normalize_usage()` helper in `LiteLLMBackend` that handles both `dict` and Pydantic-model `response.usage`, returning a `dict | None`.

4. **Concurrent safety confirmation** — Add a comment in `LiteLLMBackend` confirming it is NOT thread-safe at the instance level; one instance per `LLMProviderChain`; verify that `LLMProviderChain.__init__` always creates a new `LiteLLMBackend` (not a shared singleton).
