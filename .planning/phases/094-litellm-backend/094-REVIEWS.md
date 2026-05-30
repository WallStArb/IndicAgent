---
phase: 094
reviewers: [gemini, codex]
reviewed_at: 2026-05-29T00:00:00Z
plans_reviewed: [094-01-PLAN.md, 094-02-PLAN.md, 094-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 094: LiteLLM + Instructor Structured Output

## Gemini Review

### Summary
The plan set is well-structured, follows a robust TDD methodology, and demonstrates a clear understanding of IndicAgent's strict operational and performance requirements. By decoupling the LLM provider layer, moving to a structured output pattern via Instructor, and incorporating rigorous validation and observability gates, this plan effectively addresses the goals of reducing technical debt and improving signal parsing success rates.

### Strengths
- **TDD Focus:** Using a TDD approach for all three waves ensures that the critical `str | None` interface constraint for `LLMChain`/`LiteLLMBackend` is strictly enforced.
- **Latency-Conscious:** Explicitly setting `max_retries=1` in `generate_structured()` is a vital mitigation against the ~50s latency of the local model, keeping swarm agents within their 120s budget.
- **Observability First:** Capturing a baseline `parse_failure` rate before any code changes, and providing clear, actionable success criteria for post-migration measurement (STRUCT-OUT-03), demonstrates a data-driven approach to technical debt reduction.
- **Safety & Security:** The plan proactively addresses threat vectors including LiteLLM telemetry disabling, API key masking in error logs, and the avoidance of thread-safety issues via instance-local attributes.

### Concerns
- **MEDIUM: Complexity of Wave 3 Migration.** Migrating 4 agents simultaneously in one wave is high-risk. If any agent migration introduces a subtle validation drift, it could destabilize the signal ledger across the entire swarm.
- **LOW: Narrative Agent Stability.** While the plan correctly excludes the narrative agent, the shared `BaseAgent` infrastructure is being modified. Ensure that `_llm_generate_structured` behaves as a complete no-op or is explicitly unreachable for the narrative agent to prevent accidental feature creep.
- **MEDIUM: Circuit Breaker Integration.** Ensure that `generate_structured` uses the *exact* same circuit breaker state as `generate`. If `generate_structured` fails, it *must* count towards the same `_OLLAMA_CB`/`_REMOTE_CB` failure tally to prevent an agent from bypassing breakers by switching methods.

### Suggestions
- **Stagger Wave 3:** Consider migrating one agent at a time, starting with Skeptic as the reference implementation.
- **Circuit Breaker Verification:** Add a test case in Wave 3 to verify that `generate_structured` failures successfully trip the same circuit breaker instance used by the standard `generate` path.
- **Audit Trail Verification:** Ensure the `LineageWriterAgent` is tested to handle the new `instructor` source-tag in the `llm_calls` table.

### Risk Assessment
**Risk Level: MEDIUM** — The design is solid, but the simultaneous migration of 4 swarm agents and the replacement of core parsing boilerplate carries inherent operational risk. Strict adherence to the TDD sequence and the provided validation gates will mitigate these risks effectively.

---

## Codex Review

### Summary
The plan set is directionally strong: it separates backend introduction, chain wiring, and structured-output migration into dependency-ordered waves, keeps the legacy `LLMProviderChain.generate()` contract stable, and explicitly calls out the critical Instructor retry latency constraint. The main risks are around behavioral drift from the old provider implementation, incomplete audit continuity on structured failures, inadequate fallback behavior in `generate_structured()`, and test/acceptance inconsistencies that could let regressions slip through. Plan 03 is the highest-risk wave because it changes runtime semantics for all four alpha agents and touches audit, metrics, parsing, and service behavior at once.

### Strengths
- Clear wave ordering: Plan 01 builds the backend, Plan 02 swaps the facade, Plan 03 layers Instructor and migrates agents.
- Good emphasis on preserving `LLMProviderChain.generate()` return type as `str | None`; this avoids a subtle but serious integration break.
- `last_provider_id` and `last_token_usage` side-effect attributes are explicitly retained, which protects audit and token-budget paths.
- Instructor `max_retries=1` is repeatedly specified and tested, which directly addresses the 120s latency budget.
- Baseline and post-migration parse failure measurements are included, satisfying the intent of STRUCT-OUT-03.
- Narrative agent exclusion is justified: it returns prose, not JSON, so Instructor would add cost and failure modes without obvious value.
- The plans include useful grep-based acceptance checks for deleting old classes and stale validator references.

### Concerns
- **HIGH: `generate_structured()` only uses the primary provider.** Plan 03 proposes `provider = self.providers[0]`, so structured calls lose the fallback behavior that Plan 01/02 preserve for plain `generate()`. If Ollama is down or malformed for Instructor, OpenRouter is never tried.
- **HIGH: Structured failure may not create an audit row.** In Plan 03, `LLMProviderChain.generate_structured()` calls `_publish_audit()` only on success. If Instructor returns `None`, `_report_parse_failure(call_id)` publishes a corrective update, but there may be no original `llm_calls` row to update. That weakens parse failure measurement exactly where it matters.
- **HIGH: Plan 03 parse failure semantics are blurry.** Instructor validation failure is not the same as "LLM returned text but JSON parsing failed." The proposed flow reports parse failure on `None`, but `None` may also mean provider unavailable, circuit open, timeout, or Instructor exception. Those should be distinguishable in audit fields.
- **MEDIUM: Circuit breaker integration is less complete than the old provider path.** The old path records detailed circuit metrics and state transitions through a dedicated method. The new plan only calls `allow_request()`, `record_success()`, and `record_failure()`.
- **MEDIUM: Provider behavior may drift.** The old Ollama provider strips `<think>` tags, uses `think=False`, sets `options.num_ctx`, and avoids retrying local timeouts. The LiteLLM plan does not explicitly preserve these behaviors.
- **MEDIUM: Rate limiter lookup may become less effective.** Existing provider IDs use colon-style (e.g. `ollama:nemotron-3-nano:4b`); LiteLLM uses slash-style (`ollama/nemotron-3-nano:4b`). If `LLM_RATE_LIMITS` keys still use the old format, per-provider rate limiting silently falls back to the first limiter.
- **MEDIUM: Token usage for Instructor path is probably missing.** Plan 03 uses `self._inner.last_token_usage`, but Instructor's returned Pydantic model may not expose usage the same way LiteLLM's raw response does.
- **MEDIUM: Test counts are inconsistent.** Plan 01 says 8 tests but one bullet says 6 async tests. Plan 02 says all 7 tests after wire-up, but Plan 01 already has 8, so it should be 9. Plan 03 says 9+4=13, which is right only if Plan 02 corrected the count.
- **MEDIUM: Plan 03 omits `extra_audit` parity.** `BaseAgent._llm_generate()` supports `extra_audit`; the proposed `_llm_generate_structured()` does not.
- **MEDIUM: Pydantic validators may not preserve legacy rejection semantics.** The old `_validate_*_fields` functions return `None` for missing required fields; the proposed models coerce many values without always specifying defaults.
- **LOW: Dependency versions are loose.** `litellm>=1.40.0` and `instructor>=0.6.0` may pull newer incompatible behavior.

### Suggestions
- Make `LiteLLMBackend.generate_structured()` iterate through all providers with the same fallback semantics as `generate()`.
- Publish an audit record for structured attempts even when Instructor validation fails. Include `call_id`, `succeeded=False`, `parse_success=False`, provider, latency, model, and error category.
- Add explicit failure taxonomy for structured calls: provider failure, circuit open, timeout, validation failure. Only validation/parse failures should count as `parse_success=False`.
- Preserve old provider behavior: `think=False`, `num_ctx`, `<think>` stripping, reasoning suppression for OpenRouter.
- Add tests for structured fallback: primary provider fails, secondary succeeds; circuit-open primary is skipped; all providers fail returns `None`.
- Add chain-level tests for `generate_structured()` audit: success publishes `parse_success=True`; validation failure results in measurable parse failure path.
- Add agent-level tests for each migrated alpha agent: valid model builds same multiplier/payload; `None` calls `_report_parse_failure(call_id)`.
- Fix acceptance count inconsistencies before execution.
- Consider pinning upper bounds for `litellm` and `instructor`.
- Update docs that still describe `LLMChain`, `OllamaProvider`, or colon-format provider IDs.

### Plan-Specific Notes

**Plan 01:** Good foundational plan. Biggest gaps: old behavior preservation (`think=False`, `<think>` stripping, retry semantics) are not explicitly covered. Unit tests should verify exact kwargs sent to LiteLLM for Ollama and OpenRouter.

**Plan 02:** The chain swap is well scoped. Risk: deleting provider classes may break tests and docs beyond `tests/unit/intelligence/test_llm_providers.py`. Verify rate-limit key compatibility after provider ID format changes.

**Plan 03:** Highest-risk plan. `max_retries=1` enforcement is strong. However: structured calls need multi-provider fallback, audit-on-failure, token usage capture, and clearer parse-failure semantics. Without those, STRUCT-OUT-03 may produce misleading results.

### Risk Assessment
**Risk Level: MEDIUM-HIGH** — Well decomposed and test-driven, but replaces low-level provider behavior in production daemons that feed audit, metrics, and alpha-swarm decisions. Plans 01 and 02 are medium risk if compatibility details are tightened. Plan 03 is high risk until structured-output fallback and failure auditing are made first-class.

---

## Consensus Summary

Both reviewers independently reviewed all three plans.

### Agreed Strengths
- `max_retries=1` constraint is correctly identified and tested — critical for staying within the 120s latency budget
- Wave ordering (backend → chain → instructor/agents) is correct and safe
- Narrative agent exclusion is well-justified — prose output, no JSON parsing, Instructor adds nothing
- Baseline parse failure measurement before any code changes is the right approach for STRUCT-OUT-03
- TDD approach with failing tests written before implementation reduces integration risk

### Agreed Concerns (HIGH PRIORITY)

1. **Audit trail gap on structured failures (HIGH)** — Both reviewers flagged that `_publish_audit()` is only called on success in `generate_structured()`. A failed structured call must still create an initial `llm_calls` row before `_report_parse_failure()` can back-fill `parse_success=False`. Without this, STRUCT-OUT-03 measurement is broken for the failure case.

2. **Single-provider fallback for `generate_structured()` (HIGH/MEDIUM)** — Codex flagged explicitly; Gemini flagged circuit breaker continuity. `providers[0]`-only in `generate_structured()` loses the multi-provider fallback that `generate()` provides. If the primary fails, no retry on secondary.

3. **Circuit breaker state shared between `generate()` and `generate_structured()` (MEDIUM)** — Both reviewers want confirmation that a failure on the structured path trips the same `_OLLAMA_CB`/`_REMOTE_CB` as the standard path. An agent using both paths must share circuit state.

4. **Simultaneous 4-agent migration in Plan 03 (MEDIUM)** — Gemini recommends staggering; Codex flags it as the highest-risk change. A validation drift in one agent's BaseModel could affect all 4 simultaneously.

### Divergent Views
- **Gemini** focuses on operational staggering risk (migrate agents one-by-one vs. all 4 at once).
- **Codex** focuses more on implementation gaps: token usage capture from Instructor, `extra_audit` parity, rate-limiter key format mismatch (colon vs. slash provider IDs), and `<think>` tag stripping preservation.
- **Gemini** trusts the existing circuit breaker integration more; **Codex** calls for explicit multi-provider fallback in `generate_structured()`.

### Recommended Pre-Execution Actions
Before executing Plan 03, address these items:

1. **Audit row on failure:** In `LLMProviderChain.generate_structured()`, publish an initial audit row (with `parse_success=None` or `succeeded=False`) before returning `None`, so `_report_parse_failure()` has a row to update.
2. **Multi-provider fallback:** Implement the same provider iteration loop in `generate_structured()` as exists in `generate()`.
3. **Failure taxonomy:** Distinguish between provider-failure `None` and validation-failure `None` in the audit/metrics so STRUCT-OUT-03 is actionable.
4. **Token usage from Instructor:** Verify that `last_token_usage` is populated correctly when using the instructor client (may need `create_with_completion()` to access the raw completion object).
