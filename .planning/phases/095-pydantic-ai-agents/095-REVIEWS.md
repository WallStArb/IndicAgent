---
phase: 095
reviewers: [codex, gemini]
reviewed_at: 2026-05-31T08:25:00Z
plans_reviewed:
  - 095-01-PLAN.md
  - 095-02-PLAN.md
  - 095-03-PLAN.md
  - 095-04-PLAN.md
  - 095-05-PLAN.md
---

# Cross-AI Plan Review — Phase 095

## Codex Review

**Summary**

The plans are directionally sound and match the phase goal: introduce a typed Pydantic AI execution path without migrating every agent. The main risks are in Plan 02 and Plan 05. Plan 02 assumes `LLMProviderChain.generate()` can accept `response_format`, but the current repo signature does not; without expanding the file scope, the adapter will fail at runtime. Plan 05 under-scopes the `skeptic_v1` rename: there are live references in API stats, alpha swarm tests, and an integration graduation test beyond the listed files. Pydantic AI API usage is mostly correct: current docs confirm `Agent(..., output_type=...)`, `result.output`, and FunctionModel-style `ModelResponse` usage.

**Strengths**

- Wave ordering is good: dependency/context first, adapter next, real Agent integration before `BaseAIWorker`, then one concrete migration.
- `WorkerContext.signal_context: Any` is the right compromise for the Ring 0/Ring 1 boundary.
- Building the Pydantic AI agent per call is correct for fresh audit context and avoids stale symbol/signal metadata.
- `RuntimeError` for missing `result_type` is a good fail-fast guard.
- The Skeptic migration is intentionally straight-line and avoids a parallel feature-gated path.
- The plan calls out the two important Pydantic AI 1.x API changes: `output_type=` and `result.output`.

**Concerns**

- **HIGH: Plan 02 file scope is incomplete.** Current `src/core/llm/chain.py::generate()` and `src/core/llm/litellm_backend.py::generate()` do not accept `response_format`. Calling `chain.generate(..., response_format=schema)` will raise `TypeError` unless the chain/backend signatures are updated.
- **HIGH: Adapter request shape is underspecified.** Pydantic AI model callbacks receive `ModelRequest` parts, not a plain `prompt`. The plan should specify how `ModelRequest` parts are converted into the prompt string sent to `LLMProviderChain.generate()`.
- **HIGH: Retry audit semantics are unclear.** If Pydantic AI retries output validation, the adapter may call `chain.generate()` multiple times with the same prebuilt `call_id`. Audit trails should either allocate one `call_id` per physical LLM request or explicitly model retry attempts.
- **HIGH: Plan 05 under-scopes the `skeptic_v1` rename.** Existing references also appear in `src/api/routes/ai_stats.py`, `tests/unit/services/test_alpha_swarm.py`, and `tests/integration/test_swarm_graduation_loop.py`. Leaving them unchanged may break tests or create split operational identity.
- **MEDIUM: Pydantic AI output mode assumption needs a guard.** The plan assumes `model_request_parameters.output_tools[0]` exists. That is true only if Pydantic AI selects tool-style structured output. Tests should cover empty output tools with a clear error.
- **MEDIUM: `LLMAdapter` protocol compliance may be fragile.** Using `FunctionModel` as a base may be safer than hand-implementing all required `Model` attributes and methods.
- **MEDIUM: `max_tokens=None` conflicts with current chain API.** Current `generate()` requires `max_tokens: int`. `_run_typed()` should resolve `None` to `_default_max_tokens` before invoking the adapter/chain.
- **MEDIUM: Failure behavior changes from structured path.** Current `generate_structured()` returns `None` after provider exhaustion; the new path raises. Acceptable if `compute()` neutralizes it, but tests should cover `None` responses and validation exhaustion.
- **LOW: WorkerContext import isolation tests can be flaky.** If the test process already imported `SignalContext`, checking `sys.modules` directly may false-fail. Use a subprocess or clear module state carefully.
- **LOW: "byte-for-byte unchanged" is too strict.** Better to assert unmigrated agent runtime behavior and avoid touching their files.

**Suggestions**

- Expand Plan 02 file list to include `src/core/llm/chain.py`, `src/core/llm/litellm_backend.py`, and backend tests — or remove `response_format` from the adapter requirement and use a different structured output path.
- Add a Plan 02 must-have: `LLMAdapter` handles `None` from `chain.generate()` by raising a typed exception so Pydantic AI can retry or fail cleanly.
- Add a Plan 02/03 test for retry audit behavior: two validation failures must not publish duplicate audit rows with the same `call_id` unless intentional.
- Make adapter extraction rules explicit: latest user prompt from `ModelRequest` parts, ignore or reject unsupported multipart content, keep caller-provided `system` as the system prompt.
- Add a guard for `model_request_parameters.output_tools`: raise `RuntimeError("typed output tool schema missing")` with context if empty.
- In `_run_typed()`, build audit context via `_build_audit_context(context, prompt, call_id)` to preserve `signal_id`, `regime`, `agent_id`, `prompt_version`, and prompt text consistently with `_llm_generate()`.
- Update Plan 05 scope to include all `skeptic_v1` operational references — especially `src/api/routes/ai_stats.py` and graduation tests — or explicitly document that historical tests remain pinned to old IDs.
- Add a regression test that `SkepticEvaluator.compute()` returns neutral on Pydantic validation failure, not only on mocked `_run_typed()` exceptions.

**Risk Assessment: MEDIUM-HIGH**

The architecture is coherent, but the adapter assumes a `response_format` capability that the current chain does not expose. The Pydantic AI surface is easy to get subtly wrong around output tools, retries, and message conversion. The Skeptic agent ID rename has broader blast radius than Plan 05 lists. Addressing the chain signature, retry/audit semantics, and rename scope would reduce this to MEDIUM.

---

## Gemini Review

**Summary**

The plan is highly coherent and demonstrates a deep understanding of both the existing Ring 0/1 architectural constraints and the specific API nuances of pydantic-ai 1.0. The decision to use a lightweight `LLMAdapter` that implements the `Model` protocol as a bridge to the existing `LLMProviderChain` is technically sound, as it preserves the platform's established auditing, circuit-breaking, and rate-limiting infrastructure while enabling structured output. The proposed migration of `SkepticEvaluator` is appropriately direct, adhering to the principle of "straight replacement" rather than introducing unnecessary abstraction layers.

**Strengths**

- **Architectural Integrity:** Excellent handling of the Ring 0/1 boundary by using `TYPE_CHECKING` for `SignalContext` in `WorkerContext` and maintaining it as a frozen dataclass.
- **API Precision:** Correctly identifies the transition from 0.x to 1.0 conventions (`output_type=` instead of `result_type=`, `result.output` instead of `result.data`).
- **Design for Auditability:** The per-call `Agent` instantiation pattern is crucial for maintaining accurate `audit_context` injection, which is a core requirement of the IndicAgent platform.
- **Infrastructure Reuse:** Leveraging the existing `LLMProviderChain` via `LLMAdapter` prevents fragmentation of LLM provider logic (e.g., failover, circuit breaking).

**Concerns**

- **MEDIUM: Error handling in LLMAdapter for non-structured errors.** If `LLMProviderChain` produces a protocol error or unexpected text that fails validation, the adapter may need to provide specific feedback to the pydantic-ai retry mechanism to ensure validation-based retries are effective.
- **LOW: Gemma4 prose preambles.** Relying solely on the system message ("OUTPUT ONLY RAW JSON") might be insufficient. If structured output is strictly required, the system might need a robust parsing layer (e.g., regex extraction of the JSON block) if the model persists in including preamble text.
- **LOW: ClassVar result_type only fails at runtime.** Consider if a metaclass or `__init_subclass__` check could enforce configuration at class-definition time instead of at the first `_run_typed()` call.

**Suggestions**

- In `LLMAdapter.request()`, consider implementing a simple fallback parser (search for the first `{` and last `}`) as a safety mechanism against model preambles, before passing text to the Pydantic validator.
- Add a test in Plan 04 to verify that `result_type` ClassVar is correctly defined on `SkepticEvaluator` before the first call, perhaps adding an `__init_subclass__` check in `BaseAIWorker`.
- Ensure that `WorkerContext` includes a mechanism for per-call `audit_context` fields (like `call_id`) that are generated per call, not just static ones like `agent_id`.

**Risk Assessment: LOW**

The design aligns well with existing patterns, reuses existing robust infrastructure, and explicitly addresses the API changes in pydantic-ai 1.0. The primary risks (LLM formatting variability, configuration errors) are manageable and localized.

---

## Consensus Summary

### Agreed Strengths

- pydantic-ai 1.x API assumptions are correct: `output_type=` and `result.output` are right
- Thin-bridge LLMAdapter design preserving LLMProviderChain (circuit breaking / audit trail) is right
- Per-call Agent construction (not class-level) is correct for fresh audit context
- `WorkerContext.signal_context: Any` correctly preserves Ring 0 boundary
- `RuntimeError` on missing `result_type` is the right fail-fast pattern
- SkepticEvaluator direct migration (no parallel class, no feature gate) is right

### Agreed Concerns

1. **Audit context completeness** — Both reviewers flag that `call_id` must be generated per-call and flow through the full chain; it cannot be static on WorkerContext.
2. **LLMAdapter error path clarity** — Both flag that the adapter's behavior when `chain.generate()` fails or returns unexpected output needs to be explicit so pydantic-ai's retry loop gets actionable feedback.

### Divergent Views

**Codex (MEDIUM-HIGH) vs Gemini (LOW)** — significant disagreement on overall risk. The divergence is explained by scope: Codex checked the actual `chain.generate()` signature and found `response_format` is not accepted — a concrete runtime failure. Gemini reviewed the design in isolation and found it architecturally sound. Codex's finding takes precedence here because it is grounded in the live codebase.

**Codex-only critical findings (not flagged by Gemini):**
- `chain.generate()` / `litellm_backend.generate()` do not accept `response_format` — Plan 02 file scope must be expanded or the approach changed
- `skeptic_v1` rename blast radius extends to `src/api/routes/ai_stats.py`, `test_alpha_swarm.py`, `test_swarm_graduation_loop.py`
- Retry audit semantics: multiple `chain.generate()` calls per pydantic-ai validation cycle may create duplicate/ambiguous `llm_calls` rows

### Top Actions Before Execution

1. Verify `chain.generate()` signature — add `response_format` kwarg or change LLMAdapter to embed schema in the prompt instead
2. Specify how `ModelRequest` parts are decoded into the plain string prompt the chain expects
3. Decide retry `call_id` policy: one per physical LLM request, or one per `_run_typed()` invocation
4. Run `grep -r "skeptic_v1" .` before Plan 05 to find all rename targets
5. Guard `model_request_parameters.output_tools` access with a clear error if empty
