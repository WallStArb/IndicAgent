---
phase: 95
reviewers: [codex, gemini]
reviewed_at: 2026-05-29T21:15:00Z
plans_reviewed:
  - 095-01-PLAN-UPDATED.md
  - 095-02-PLAN-UPDATED.md
  - 095-03-PLAN.md
  - 095-04-PLAN.md
  - 095-05-PLAN-UPDATED.md
---

# Cross-AI Plan Review — Phase 095

## Codex Review

### Summary

Overall risk is **HIGH**. Plans 03 and parts of 04 are directionally useful, but the -UPDATED plan variants for Plans 01, 02, and 05 reintroduce multi-tenant work (UserContext, AgentLimits, per-user quotas) that the phase scope explicitly says was extracted. More importantly, the adapter design does not resolve the central architectural tension: **Pydantic AI normally owns the LLM call, but IndicAgent requires every LLM call to go through `BaseAIAgent._llm_generate()` for audit persistence**. The current Plan 02 sketch either bypasses Pydantic AI by calling `_llm_generate()` and parsing manually, or would bypass audit if changed to `pydantic_agent.run()`. That must be fixed before execution.

Sources checked: current repo files including `src/core/ai/base_agent.py`, `src/intelligence/ai/alpha/skeptic_agent.py`, `src/intelligence/ai/alpha/skeptic_prompts.py`, `services/alpha_swarm_agent.py`, plus current Pydantic AI docs/PyPI. **Pydantic AI is currently at v1.104.0** (not 0.0.x as pinned); Python >=3.10, Pydantic 2 classifiers. API has changed substantially.

### Plan 01 (AgentDeps)

**Strengths:**
- `AgentDeps` as a frozen dataclass is the right shape for `RunContext[AgentDeps]`
- Including `signal_context`, `llm_chain`, `db_pool`, `memory_client` matches dependency injection goal
- Unit-level construction tests are appropriate and cheap

**Concerns:**
- **[HIGH]** UPDATED plan reintroduces `user_context` — contradicts phase scope. Use original 095-01-PLAN.md
- **[HIGH]** If `src.core.ai.user_context` does not exist yet, this blocks the adapter foundation
- **[MEDIUM]** `user_context` has no default — callers must pass it even with `UserContext.system()` described
- **[LOW]** File path for AgentDeps not specified; later plans imply `src/intelligence/ai/adapters/agent_deps.py`

**Suggestions:**
- Execute original 095-01-PLAN.md (not UPDATED). Remove `user_context` entirely from Phase 095
- Test that `AgentDeps` is passed to `pydantic_agent.run(..., deps=deps)`, not merely instantiated

**Risk: MEDIUM-HIGH**

### Plan 02 (PydanticAIAdapter)

**Strengths:**
- Identifies that adapter should preserve `BaseAIAgent.compute()` behavior
- Attempts to keep `_llm_generate()` in call path (critical audit constraint)
- Includes neutral fallback for failure conditions

**Concerns:**
- **[HIGH]** Adapter sketch does not use Pydantic AI execution — calls `_llm_generate()` directly and parses manually. Fails the goal of typed `RunContext[AgentDeps]`
- **[HIGH]** If changed to `await self._pydantic_agent.run(...)`, Pydantic AI performs model call itself — bypasses `_llm_generate()`, breaks audit trail
- **[HIGH]** Modifying `BaseAIAgent._llm_generate()` violates success criterion 5 ("BaseAIAgent unchanged")
- **[HIGH]** Multi-tenant quotas, permissions, concurrency — all from deferred Plan 00 (UPDATED plan is stale)
- **[MEDIUM]** `AgentLimits` mutable counters on adapter are unsafe for concurrent async requests
- **[MEDIUM]** `record_completion()` only called on success — failed calls may not count against quota

**Suggestions:**
- Decide adapter architecture before implementation:
  - **Option A:** Implement a Pydantic AI custom `Model`/provider wrapper whose request path calls `BaseAIAgent._llm_generate()`. Audit preserved, PydanticAI execution intact.
  - **Option B:** Downgrade goal to "Pydantic models for output validation." Keep `_llm_generate()` as sole LLM path.
- Remove all multi-tenant content from Plan 02 — use original 095-02-PLAN.md
- Add a test proving one Skeptic adapter run inserts an audited LLM call through `_llm_generate()`

**Risk: HIGH** — central plan with unresolved audit trail architecture.

### Plan 03 (SkepticResult)

**Strengths:**
- Narrow, well-scoped, aligned with phase goals
- Strict `Field(ge=0.0, le=1.0)` validation (rejects, not clamps) is correct distinction
- `risk_factors` coercion handles realistic LLM output variation
- Tests cover valid input, coercion, bounds rejection, reasoning length

**Concerns:**
- **[MEDIUM]** Threat model says "reject non-serializable types" but validator stringifies — a dict becomes a string, not a rejection
- **[MEDIUM]** No `extra="forbid"` model config — extra fields not rejected
- **[LOW]** Test path for skeptic prompts may diverge from where existing tests live

**Suggestions:**
- Add `model_config = ConfigDict(extra="forbid")` for strict NativeOutput enforcement
- Add tests for missing required floats, extra fields

**Risk: LOW-MEDIUM** — strongest plan.

### Plan 04 (SkepticComputeAgentPydantic)

**Strengths:**
- Correctly avoids inheriting from `BaseMultiplierAgent`
- Preserves Skeptic transfer function: `(1.0 - failure_probability) * confidence`
- Keeps `shadow_only=True`; uses `build_skeptic_prompt()` for prompt parity
- `deps_type=AgentDeps` consistent with Pydantic AI docs

**Concerns:**
- **[HIGH]** `pydantic-ai>=0.0.1` is invalid — current version is ~1.104.0, APIs changed substantially
- **[HIGH]** Tests claim to avoid real Pydantic AI agents but `__init__` creates real `pydantic_ai.Agent`
- **[HIGH]** `NativeOutput` requires Ollama v0.5.0+ for structured output — no environment check
- **[HIGH]** Depends on unresolved Plan 02 adapter design
- **[MEDIUM]** `get_settings().OLLAMA_MODEL` returns raw tag (e.g., `gemma4:e4b`) — Pydantic AI expects `ollama:<tag>` or `OllamaModel(...)`
- **[MEDIUM]** Manually constructed `AgentOutput` omits `symbol`, `timeframe`, `ts`, `signal_id`

**Suggestions:**
- Pin after testing: `pydantic-ai>=1.0,<2` (or exact tested version)
- Add adapter-level seam for injecting fake `pydantic_agent` in unit tests
- Use `OllamaModel(settings.OLLAMA_MODEL, provider=OllamaProvider(...))` or normalize raw tags
- Populate `AgentOutput` metadata from `AIContext`

**Risk: HIGH**

### Plan 05 (Service Registration)

**Strengths:**
- `ENABLE_PYDANTIC_SKEPTIC_SHADOW` feature gate is correct rollout mechanism
- Leaving other agents on `BaseAIAgent` unchanged matches phase goal
- Recognizes n >= 100 gate before promotion

**Concerns:**
- **[HIGH]** UPDATED plan has multi-tenant queues, per-user metrics — out of scope. Use original 095-05-PLAN.md
- **[HIGH]** Per-user queue implementation is not a durable queue — `_process_user_queue()` called directly
- **[HIGH]** Mutating `agent._user_context` per request is unsafe — shared service instances, concurrent overwrites
- **[HIGH]** Shadow outputs must be explicitly excluded from `_compute_final_multiplier`; no test verifies this
- **[MEDIUM]** `AlphaSwarmComputeAgent._agents: list[BaseMultiplierAgent]` — `PydanticAIAdapter` may not fit

**Suggestions:**
- Reduce Plan 05: add feature gate, register agent, ensure shadow excluded from live aggregation, add n >= 100 comparison query
- Add a test proving shadow outputs do not change final multiplier
- Defer all multi-tenant queueing and cost accounting

**Risk: HIGH**

### Cross-Plan Gaps

- **Adapter contract underspecified:** Need one definitive flow: `BaseAIAgent.compute()` → adapter `_compute()` → Pydantic AI run → `_llm_generate()` audit → `AgentOutput`
- **Version pinning:** Replace `>=0.0.1` with tested modern range — current is 1.104.x
- **Phase numbering:** Plans reference `094-*` artifacts in several places. Fix before execution.
- **Promotion criteria not implemented:** Plans mention n >= 100 and confidence delta but don't define the query, metric name, or operator action path

---

## Gemini Review

### Summary

The -UPDATED plans successfully integrate multi-tenant support (UserContext) via `RunContext[AgentDeps]`. Design is internally consistent. However, modifying `BaseAIAgent._llm_generate()` is a significant breaking change requiring a fleet-wide migration across 121+ plugins that is not currently planned.

### Strengths

- `RunContext[AgentDeps]` is idiomatic Pydantic AI dependency injection
- Quota/permission checks inside adapter `_compute()` enforce security before inference
- Including `user_context` in `_llm_generate` captures multi-tenant data in `llm_calls`
- Defaulting to `UserContext.system()` preserves backward compatibility

### Concerns

- **[HIGH]** Breaking API change to `BaseAIAgent._llm_generate()` — all existing agents must be updated; no consolidated migration plan
- **[MEDIUM]** `_neutral()` for quota failures loses information — downstream cannot distinguish "quota exceeded" from "LLM failure"
- **[MEDIUM]** Cost estimation `(char_count / 1000) * 0.0001` will diverge significantly from actual token costs

### Suggestions

- Add explicit task: grep all `_llm_generate` call sites and update (fleet-wide migration)
- Use actual token count from provider rather than character estimation
- Define structured error type for quota failures so dispatcher can implement specific handling

**Risk: MEDIUM** (treating multi-tenant as in-scope per the UPDATED plans reviewed)

---

## Consensus Summary

### Agreed Strengths

- `AgentDeps` frozen dataclass + `RunContext[AgentDeps]` is the correct Pydantic AI pattern
- `SkepticResult` (Plan 03) is the strongest plan — narrow, well-tested, correct validation semantics
- `ENABLE_PYDANTIC_SKEPTIC_SHADOW` feature gate is the right rollout mechanism
- `shadow_only=True` on the Pydantic Skeptic is correctly scoped

### Agreed Concerns (priority order)

1. **[CRITICAL] The -UPDATED plan variants (01, 02, 05) contain deferred multi-tenant scope** — they are stale. Use original 095-01-PLAN.md, 095-02-PLAN.md, 095-05-PLAN.md for execution.

2. **[CRITICAL] Audit trail architecture is unresolved** — PydanticAI's `pydantic_agent.run()` owns the LLM call; IndicAgent's `_llm_generate()` must be in the call path. These conflict unless a Pydantic AI custom model/provider wrapper is implemented. Decide before writing Plan 02.

3. **[HIGH] pydantic-ai version is wrong** — plans pin `>=0.0.1`; current is ~1.104.0. Test against real version, pin narrow range (`>=1.0,<2` or exact).

4. **[HIGH] Ollama structured output requires v0.5.0+** — NativeOutput will fail silently on older Ollama. Add environment check.

5. **[HIGH] Phase numbering inconsistency** — several plan files reference `094-*` artifacts. Fix before execution.

6. **[HIGH] Shadow outputs not provably excluded from live aggregation** — add an explicit test proving `shadow_only=True` Pydantic Skeptic does not affect `_compute_final_multiplier`.

### Divergent Views

- **Codex** reviewed the -UPDATED plans, recognized the scope conflict with deferred Plan 00, and rated risk HIGH
- **Gemini** reviewed the -UPDATED plans as authoritative (multi-tenant in-scope) and rated risk MEDIUM
- **Resolution:** The -UPDATED plans are stale. Codex's reading is correct — use original non-UPDATED plans.

### Recommended Pre-Execution Decisions

Before starting Wave 1:

1. **Choose adapter architecture** — Custom Pydantic AI Model wrapper routing through `_llm_generate()` (Option A), OR Pydantic for output validation only with `_llm_generate()` as sole LLM path (Option B). Document the decision in a CONTEXT.md.
2. **Pin pydantic-ai version** — Install and test against current release (~1.104.x), pin to `>=1.0,<2` or exact.
3. **Verify Ollama v0.5.0+** — Confirm structured output works with current Ollama container (`docker exec ollama ollama --version`).
4. **Use original plans** — 095-01-PLAN.md, 095-02-PLAN.md, 095-05-PLAN.md are execution targets (not the UPDATED variants).
