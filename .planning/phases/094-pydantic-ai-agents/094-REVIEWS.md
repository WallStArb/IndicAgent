---
phase: 094
reviewers: [gemini, codex]
reviewed_at: 2026-05-21T00:00:00Z
plans_reviewed: [094-01-PLAN.md, 094-02-PLAN.md, 094-03-PLAN.md, 094-04-PLAN.md, 094-05-PLAN.md]
---

# Cross-AI Plan Review — Phase 094

## Gemini Review

### Summary
The plan effectively bridges the existing legacy `BaseAIAgent` infrastructure with the modern, type-safe Pydantic AI framework. By adopting an adapter pattern and utilizing native structured output (`NativeOutput` + grammar constraints), the plan prioritizes reliability and incremental adoption without requiring a "big-bang" migration. The validation strategy (shadow mode + calibrated confidence measurement) aligns well with the project's Renaissance-inspired approach to performance tuning.

### Strengths
- **Protocol Compliance**: The `PydanticAIAdapter` correctly implements the `BaseAIAgent` protocol, ensuring that existing service orchestration and OTel instrumentation remain functional for both migrated and legacy agents.
- **Dependency Injection**: `AgentDeps` provides a clean, type-safe container that replaces ad-hoc constructor injection, significantly improving testability.
- **Zero Parse Failures**: Leveraging `NativeOutput` with grammar-constrained decoding effectively eliminates the maintenance burden of hand-rolled retry/parsing logic.
- **Shadow Validation Gate**: The formal gate ($N \ge 100$ inferences + confidence calibration check) ensures that performance is empirically verified before promotion, meeting the project's rigorous observability standards.
- **Benchmark Completeness**: Including latency benchmarks (`p50/p95/p99`) directly addresses the "renaissance_engineering" requirement for measurable compute efficiency.

### Concerns
- **Ollama/Grammar Maturity (HIGH)**: Relying on llama.cpp grammar constraints via Ollama v0.5.0 is technically sound, but performance/stability can vary significantly across quantized models (like the 4B nemotron). The plan lacks a fallback if the 4B model struggles to adhere to complex constraints.
- **Shadow Mode "Contamination" (MEDIUM)**: While the plan ensures shadow agents don't write to `signal_ledger`, there is a risk that unmonitored shadow logs in `llm_calls` could grow excessively if shadow mode is enabled on high-frequency agents.
- **Dependency Versioning (LOW)**: The plan correctly notes `pydantic-ai` needs a version check; ensure the `requirements.txt` update accounts for potential conflicts with the existing `pydantic` v2.x pinned versions.

### Suggestions
- **Grammar Resilience**: Add a "Plan B" check in `PydanticAIAdapter`. If native schema enforcement repeatedly fails (e.g., model lacks sufficient headroom), the adapter could provide a log warning or temporarily fail-safe to `BaseAIAgent` rather than failing the inference entirely.
- **Shadow Registry Hygiene**: Consider adding a temporary `shadow_storage_limit` constraint to the `ShadowAuditorAgent` to prune logs for agents that fail shadow qualification, preventing `llm_calls` table bloat.
- **Integration Check**: Before beginning Wave 1, explicitly verify the environment's `ollama` version on the target machine, as this is the single point of failure for `NativeOutput`.

### Risk Assessment: LOW
**Justification**: The plan utilizes a proven adapter pattern that keeps the existing `BaseAIAgent` infrastructure intact. The "shadow-only" deployment methodology provides a clear safety path, and the statistical graduation gates ensure no performance regressions reach production. All migration steps are incremental and reversible.

---

## Codex Review

### Summary
The phase direction is sound: an incremental adapter, a typed `AgentDeps`, one shadow Skeptic migration, and no `BaseAIAgent` deletion are the right boundaries. But the current plans have several implementation-breaking mismatches with the repo and with Pydantic AI usage. The biggest risks are that the adapter bypasses existing LLM audit/rate-limit/guardrail infrastructure, `SkepticComputeAgentPydantic` calls multiplier helpers it does not inherit, `_compute()` forgets to await `_to_agent_output()`, and the tests as written will not pass because of `AIContext` and Pydantic validation details.

**Sources checked for Pydantic AI API shape:** [Pydantic AI Output](https://ai.pydantic.dev/output/), [Pydantic AI Dependencies](https://ai.pydantic.dev/dependencies/), [Pydantic AI Agent API](https://ai.pydantic.dev/api/agent/).

#### 094-01 AgentDeps

**Strengths**
- Clean, small scope.
- Good dependency direction: `AgentDeps` does not pull Pydantic AI into core code.
- Defaults for `db_pool` and `memory_client` fit incremental rollout.

**Concerns**
- **LOW**: `TYPE_CHECKING` imports mean runtime annotations are strings due to `from __future__ import annotations`; fine, but tests cannot assert actual runtime types from annotations without resolving them.
- **LOW**: Threat model overstates "read-only" protection. `AgentDeps` is a plain dataclass; immutability is not enforced.
- **LOW**: Test examples use undefined `mock_context`, `mock_llm_chain`, etc.

**Suggestions**
- Use `@dataclass(frozen=True)` unless mutable dependency swapping is intentionally needed.
- Add explicit pytest fixtures using `Mock()` or real minimal `AIContext(symbol="ES", timeframe="5m", ts=datetime.now(UTC))`.
- Consider `db_pool: asyncpg.Pool | None` under `TYPE_CHECKING` if the dependency is stable; `memory_client` can remain `Any`.

**Risk Assessment: LOW**
This plan is easy to correct and does not touch runtime behavior.

#### 094-02 PydanticAIAdapter

**Strengths**
- Correct high-level adapter idea.
- Keeps `BaseAIAgent` as the lifecycle wrapper.
- `_build_deps()` centralizes dependency construction.

**Concerns**
- **HIGH**: `_compute()` returns `self._to_agent_output(...)` without `await`, but `_to_agent_output()` is async. This will return a coroutine instead of `AgentOutput`.
- **HIGH**: It bypasses `BaseAIAgent._llm_generate()`, so existing audit publishing to `llm_calls`, parse tracking, provider fallback, rate limiting, semantic cache, guardrails, and token budget observability are not preserved.
- **MEDIUM**: `user_prompt=str(context)` does not match the legacy Skeptic path. The legacy agent uses `build_skeptic_prompt(context)`, so success criterion 1 "same AgentOutput as legacy `_compute()` path" is unlikely.
- **MEDIUM**: The adapter hardcodes `db_pool=None` and `memory_client=None`, but Phase 094 requires `AgentDeps` to carry these dependencies. There is no constructor path to inject them.
- **MEDIUM**: Test plan imports `SkepticComputeAgent` but does not use it.
- **LOW**: Verification says `grep -q "extends BaseAIAgent"` but the code only says `class PydanticAIAdapter(BaseAIAgent)`. That grep will fail unless the docstring contains that exact phrase.

**Suggestions**
- Fix `_compute()`:
  ```python
  return await self._to_agent_output(result, context)
  ```
- Add adapter constructor params for `llm_chain`, `db_pool`, and `memory_client`, and pass `llm_chain` to `super`/deps consistently.
- Decide explicitly whether Pydantic AI may bypass `LLMProviderChain`. If yes, add replacement audit emission for `llm_calls`; if no, create a custom Pydantic AI model/provider wrapper around existing `LLMProviderChain.generate()`.
- Let subclasses provide `_build_user_prompt(context)` so Skeptic can use `build_skeptic_prompt(context)`.
- Add a test that calls `_compute()` with a fake pydantic agent whose `run()` returns a fake result, proving the output is an `AgentOutput`, not a coroutine.

**Risk Assessment: HIGH**
The adapter is central to the phase and currently breaks both runtime output and existing observability semantics.

#### 094-03 SkepticResult

**Strengths**
- Good placement next to Skeptic prompt/validation logic.
- `risk_factors` coercion is useful for LLM variance.
- `reasoning` length cap is a sensible safety control.

**Concerns**
- **HIGH**: The proposed tests instantiate `SkepticResult(risk_factors=None)` without required `failure_probability` and `confidence`; they will fail.
- **MEDIUM**: Plan text says `Field(ge=0.0, le=1.0)` "clamps" values. It does not clamp; it raises `ValidationError`.
- **MEDIUM**: This changes behavior from legacy `_validate_skeptic_fields`, which clamps out-of-range floats. That may violate "same AgentOutput as legacy `_compute()` path" unless intentionally accepted.
- **LOW**: `reasoning` max length is 500 characters while instructions mention "max 100 words"; those are not equivalent.

**Suggestions**
- Choose one behavior:
  - For legacy parity, add validators that clamp floats before validation.
  - For strict structured output, update tests and docs to expect `ValidationError`.
- Fix tests to include required fields in every instantiation.
- Add tests for missing required floats, non-string reasoning, and overlong reasoning.
- Keep `_validate_skeptic_fields` untouched for legacy path, but add a parity test comparing valid legacy parsed dict to `SkepticResult`.

**Risk Assessment: MEDIUM**
The model is straightforward, but incorrect test expectations and clamp/reject ambiguity will cause churn.

#### 094-04 SkepticComputeAgentPydantic

**Strengths**
- Keeps new Skeptic in `shadow_only=True`.
- Reuses `ACTIVE_VERSION` and `SkepticResult`.
- Transfer function matches legacy formula: `(1.0 - failure_probability) * confidence`.

**Concerns**
- **HIGH**: `SkepticComputeAgentPydantic` extends `PydanticAIAdapter`, which extends `BaseAIAgent`, but `_to_agent_output()` calls `_build_multiplier_output()`, which exists on `BaseMultiplierAgent`, not `BaseAIAgent`. This will raise `AttributeError`.
- **HIGH**: `model=llm_chain._llm` is invalid for the current repo. `LLMProviderChain` has `_inner`, not `_llm`, and Pydantic AI expects a known model name or Pydantic AI model object.
- **HIGH**: `deps_type=None` directly contradicts AGENT-EXEC-02. The point is `RunContext[AgentDeps]`; this agent opts out.
- **HIGH**: It imports `pydantic_ai` at runtime in Plan 04, but `pydantic-ai` is not added to requirements until Plan 05. Dependency ordering is wrong.
- **HIGH**: It imports `BaseMultiplierAgent` but does not inherit from it.
- **MEDIUM**: `build_skeptic_prompt` is imported but unused; the adapter sends `str(context)`, so prompt parity is lost.
- **MEDIUM**: Tests instantiate the real `SkepticComputeAgentPydantic`, which imports Pydantic AI and constructs an agent. This makes unit tests depend on the external package and valid model configuration.
- **LOW**: Exact float assertion `0.24` may be brittle; use `pytest.approx(0.24)`.

**Suggestions**
- Add `pydantic-ai` dependency before any runtime import, or make Plan 04 depend on Plan 05's dependency task.
- Either:
  - Make a `PydanticAIMultiplierAdapter(BaseMultiplierAgent)` for multiplier agents, or
  - Have `SkepticComputeAgentPydantic._to_agent_output()` manually construct `AgentOutput`.
- Configure Pydantic AI with `deps_type=AgentDeps`.
- Build the user prompt with `build_skeptic_prompt(context)`.
- Do not use `llm_chain._llm`. Use a Pydantic AI Ollama model configured from settings, or build a custom bridge around `LLMProviderChain`.
- In unit tests, bypass `__init__` complexity or inject a fake Pydantic agent/model so transfer function tests stay pure.

**Risk Assessment: HIGH**
This plan will not run as written and fails multiple phase requirements despite having the right conceptual target.

#### 094-05 Service Registration + Dependency

**Strengths**
- Registers new Skeptic alongside legacy Skeptic rather than replacing it.
- Adds transform mapping for lineage attribution.
- Explicitly preserves `BaseAIAgent`.
- Includes shadow validation and latency measurement concepts.

**Concerns**
- **HIGH**: Adding another LLM agent increases per-signal latency/cost immediately. `asyncio.gather()` may run it in parallel, but semaphore capacity and local Ollama throughput can still degrade production.
- **HIGH**: The "shadow validation test" only stores SQL strings and makes no assertions. It documents a process but does not verify anything.
- **HIGH**: Queries compare `agent_id IN ('skeptic_v2', 'skeptic_v2_pydantic')`, but the actual legacy agent ID in repo is `skeptic_v1`.
- **HIGH**: `llm_calls.confidence` is populated from audit context, but the new Pydantic path as planned does not publish audit context through `LLMProviderChain._publish_audit()`. The validation queries may see no rows or incomplete rows.
- **MEDIUM**: `pydantic-ai>=0.0.1` is too loose for production. It can install incompatible APIs.
- **MEDIUM**: The expected latency comment says Pydantic AI should be faster, but the research says framework overhead may add latency. The benchmark should measure without assuming direction.
- **MEDIUM**: `BaseAIAgent` preservation test uses file I/O and checks `"class BaseMultiplierAgent"` inside `src/core/ai/base_agent.py`, but `BaseMultiplierAgent` lives in `src/core/ai/multiplier_agent.py`. That assertion will fail.
- **LOW**: Verification grep typo: `verify_base_aiaagent_preserved` vs function name `test_verify_base_aiagent_preserved`.

**Suggestions**
- Pin a real version range, e.g. `pydantic-ai>=x,<y`, after verifying compatibility.
- Gate registration with a setting such as `ENABLE_PYDANTIC_SKEPTIC_SHADOW`, default false for first deploy.
- Fix comparison IDs to `skeptic_v1` and `skeptic_v2_pydantic`, unless the legacy ID is intentionally renamed.
- Add an integration test that imports `AlphaSwarmComputeAgent`, runs `_setup()` with mocks, and verifies both agents are present and the Pydantic one is shadow-only.
- Move "manual SQL protocol" into a checked-in ops runbook or a test that validates SQL text only by name. Do not call it a verification test unless it executes against a test DB.
- Fix BaseAIAgent preservation test to import classes directly:
  ```python
  from src.core.ai.base_agent import BaseAIAgent
  from src.core.ai.multiplier_agent import BaseMultiplierAgent
  ```

**Risk Assessment: HIGH**
Wiring a broken adapter into the live swarm risks runtime failures and degraded local LLM throughput. The validation artifacts are mostly documentation, not executable safeguards.

#### Cross-Plan Issues

- **HIGH**: Wave/dependency metadata is inconsistent. Roadmap says 3 waves; plan files show waves 1 through 5. Also Plan 02 is described as Wave 1 in the roadmap but has `wave: 2`.
- **HIGH**: The phase success criterion says `adapter.run(context)`, but the plans implement `_compute()`/`compute()`, not `run(context)`. Either update success criteria or add a `run()` method.
- **HIGH**: AGENT-EXEC-01 says agents need not know Pydantic AI internals, but `SkepticComputeAgentPydantic` directly constructs `pydantic_ai.Agent`. That may be acceptable for migrated agents, but it contradicts the wording.
- **MEDIUM**: No startup check for Ollama structured output compatibility is actually implemented despite being called out in research.
- **MEDIUM**: No explicit operator promotion mechanism is added. `shadow_only=True` exists, but "promotion requires explicit operator action" should be represented by config, registry state, or runbook.
- **MEDIUM**: No test actually verifies "same `AgentOutput` as legacy `_compute()` path" against Skeptic. Current tests only validate transfer math.
- **MEDIUM**: Pydantic AI native output may not support tools at the same time for all providers; future `RunContext[AgentDeps]` tool use needs provider-specific tests.

### Overall Risk Assessment: HIGH
The architecture is directionally good, but the executable plans are not ready. The main blockers are concrete code incompatibilities with the existing repo, incomplete preservation of LLM audit/observability, dependency ordering, and validation tests that would either fail or not verify the claimed behavior. I would revise Plans 02, 04, and 05 before implementation; Plan 01 can proceed with minor cleanup, and Plan 03 can proceed once clamp-vs-reject behavior is decided.

---

## Consensus Summary

### Agreed Strengths
- **Adapter pattern approach**: Both reviewers agree that the adapter pattern bridging `BaseAIAgent` and Pydantic AI is architecturally sound.
- **Shadow validation strategy**: Both reviewers agree that shadow-only deployment with statistical validation gates is the right approach.
- **Dependency injection via AgentDeps**: Both reviewers agree that `AgentDeps` improves testability and dependency management.
- **Incremental migration philosophy**: Both reviewers agree that preserving `BaseAIAgent` and migrating one agent at a time reduces risk.

### Agreed Concerns
- **HIGH: Async/await bug in PydanticAIAdapter._compute()**: Codex identified that `_compute()` returns `self._to_agent_output(...)` without `await`, which will return a coroutine instead of `AgentOutput`.
- **HIGH: LLM audit trail bypass**: Codex identified that bypassing `BaseAIAgent._llm_generate()` loses audit publishing to `llm_calls`, parse tracking, provider fallback, rate limiting, and guardrails.
- **HIGH: Dependency ordering issue**: Codex identified that Plan 04 imports `pydantic_ai` at runtime, but the dependency isn't added until Plan 05.
- **HIGH: AgentDeps not wired to actual usage**: Both reviews identified that `AgentDeps` is created but `deps_type=None` contradicts AGENT-EXEC-02.
- **HIGH: Validation tests are not executable**: Codex identified that shadow validation test only stores SQL strings without assertions.
- **HIGH: Wave/dependency inconsistency**: Codex identified mismatch between roadmap (3 waves) and plan files (5 waves).

### Divergent Views
- **Overall risk assessment**: Gemini rated overall risk as **LOW**, citing the proven adapter pattern and reversible deployment. Codex rated overall risk as **HIGH**, citing multiple implementation-breaking issues that need resolution before execution.
- **Grammar constraint maturity**: Gemini raised concerns about Ollama v0.5.0 grammar constraints varying across quantized models. Codex focused more on concrete code incompatibilities rather than model maturity.

### Priority Actions
Before executing these plans, address these HIGH-severity issues:
1. Fix async/await bug in `PydanticAIAdapter._compute()`
2. Preserve LLM audit trail by either routing through `LLMProviderChain` or adding replacement audit emission
3. Fix dependency ordering (add `pydantic-ai` before Plan 04 or make Plan 04 depend on Plan 05)
4. Wire `AgentDeps` to actual Pydantic AI usage (`deps_type=AgentDeps`)
5. Make shadow validation tests executable (add assertions or move to runbook)
6. Resolve wave/dependency inconsistency (update roadmap or plan wave numbers)
7. Fix test failures in Plans 03 and 04 (missing required fields, wrong assertion patterns)

---

*Review completed: 2026-05-21*
*Reviewers: gemini, codex*
*Phase: 094 - Pydantic AI Agent Adapter*
