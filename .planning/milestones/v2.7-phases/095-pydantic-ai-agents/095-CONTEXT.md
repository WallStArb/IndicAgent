# Phase 095: Pydantic AI Execution Layer - Context

**Gathered:** 2026-05-31
**Status:** Ready for planning

<domain>
## Phase Boundary

Add a typed, validated LLM execution path to `BaseAIWorker` and `Evaluator` subclasses. Three deliverables:

1. **`WorkerContext`** — frozen dep container at `src/core/ai/worker_context.py` carrying `(signal_context: Any, llm_chain: LLMProviderChain, db_pool: Any | None, memory_client: Any | None)`.
2. **`LLMAdapter`** — pydantic-ai `Model` protocol implementation at `src/core/ai/llm_adapter.py` that routes through `LLMProviderChain` (preserving circuit breaking, routing, and audit trail).
3. **`_run_typed()`** — method on `BaseAIWorker` plus `result_type: ClassVar = None` opt-in. Proven by migrating `SkepticEvaluator` from the instructor path to `_run_typed`.

**Not in scope:** Zep memory integration (Phase 097), DSPy prompt optimization (Phase 098), any other evaluator migrations beyond Skeptic.

**Naming corrections from Phase 110/111 (old plan names → current names):**
- `BaseAIAgent` → `BaseAIWorker`
- `AIContext` → `SignalContext` (now at `src/intelligence/ai/context.py`)
- `AgentContext` (old dep container) → `WorkerContext` (new name per Phase 110 intent)
- `BaseMultiplierAgent` → `Evaluator`
- `AlphaSwarmComputeAgent` → `AlphaSwarm`
- `alpha_swarm_agent.py` → `alpha_swarm.py`

</domain>

<decisions>
## Implementation Decisions

### WorkerContext (Ring 0 dep container)

- **D-01: Location** — `src/core/ai/worker_context.py`. Ring 0 portable infrastructure.
- **D-02: Implementation** — `@dataclass(frozen=True)`. Not a Pydantic model — this is an in-memory dep container that is never serialized or sent over the wire. Lightweight, correct immutability semantics.
- **D-03: Fields** — Four fields: `signal_context: Any`, `llm_chain: LLMProviderChain`, `db_pool: Any | None = None`, `memory_client: Any | None = None`. `signal_context` typed as `Any` to preserve Ring 0 boundary — Ring 0 cannot import Ring 1 (`SignalContext`) at runtime. Mirrors the `AgentOutput.payload: dict[str, Any]` pattern. `db_pool` and `memory_client` included now so Phase 097 (Zep memory) doesn't require a WorkerContext change touching all `_run_typed()` call sites.
- **D-04: Ring boundary** — Use `TYPE_CHECKING`-only import for `LLMProviderChain` type annotation (same pattern as `base_agent.py`). At runtime, `LLMProviderChain` is passed in as a concrete value — no import needed.

### LLMAdapter (pydantic-ai Model bridge)

- **D-05: Location** — `src/core/ai/llm_adapter.py`. Ring 0 infrastructure.
- **D-06: Routing** — `LLMAdapter` implements pydantic-ai's `Model` protocol. Its `request()` method calls `LLMProviderChain.generate()` — all actual LLM calls route through the chain. Circuit breaking, provider failover, rate limiting, and audit trail (`llm_calls` table) are fully preserved. Never bypass the chain.
- **D-07: Audit injection** — `LLMAdapter` is constructed with `WorkerContext`. `LLMAdapter.request()` reads `agent_id`, `prompt_version`, and `symbol` from the context to build `audit_context` before calling `chain.generate()`. Instrumentation is structural — impossible to forget. Mirrors `_llm_generate()` pattern on `BaseAIWorker`.
- **D-08: Retry** — Inherit pydantic-ai `Agent` retry defaults via `retries=` parameter. `LLMAdapter` is a thin bridge, not a retry controller. pydantic-ai owns validation retry; `LLMProviderChain` owns network circuit breaking. Clean separation of concerns.
- **D-09: Structured output** — Extract JSON schema from pydantic-ai's `model_request_parameters` (the `result_type` model schema), pass as `response_format` to `chain.generate()` for Ollama grammar-constrained generation. This gives pydantic-ai's validation layer clean, schema-enforced JSON without bypassing our chain.

### `_run_typed()` on BaseAIWorker

- **D-10: Placement** — `result_type: ClassVar[type[BaseModel] | None] = None` and `_run_typed()` live on `BaseAIWorker`. Universal opt-in for all AI agents (alpha, narrative, risk). Agents that don't set `result_type` are byte-for-byte unchanged. Future narrative/risk agents adopt without base class changes.
- **D-11: Signature** — `async def _run_typed(self, context: SignalContext, prompt: str, system: str, max_tokens: int | None = None) -> BaseModel`. `timeout` derived from `self._timeout_s` (already computed from `latency_budget_ms`) — budget always enforced, impossible to forget. `max_tokens` optional, falls back to a `_default_max_tokens: ClassVar[int] = 2048` on `BaseAIWorker`.
- **D-12: Return type** — Returns the `result_type` instance directly (validated Pydantic model). The caller (`_compute()`) converts to `AgentOutput` via `_build_multiplier_output()`. No double-wrapping. `_run_typed()` has one responsibility.
- **D-13: Error on misconfiguration** — Calling `_run_typed()` when `result_type is None` raises `RuntimeError` immediately. Loud failure, no silent fallback. Existing agents that never call `_run_typed` are unaffected.

### SkepticEvaluator — straight replacement, not parallel experiment

- **D-14: No parallel class** — `SkepticEvaluator` is migrated to use `_run_typed` directly. No `SkepticPydanticEvaluator`, no feature gate, no side-by-side running. pydantic-ai's grammar-constrained structured output is strictly more correct than instructor's post-hoc JSON parsing. When you have the better approach, commit to it.
- **D-15: Migration** — `SkepticEvaluator._compute()` replaces the `_llm_generate_structured` call with `await self._run_typed(context, prompt=..., system=...)`. `SkepticResult` stays in `skeptic_prompts.py`. `agent_id` renamed from `"skeptic_v1"` → `"skeptic"` — "v1" is a pre-rename artifact that violates Phase 110/111 naming conventions. The `shadow_registry` row for `"skeptic_v1"` is orphaned (shadow-only, no production history, no migration needed — let it decay).
- **D-16: No ENABLE_PYDANTIC_SKEPTIC gate** — The gate was designed for a parallel experiment that no longer exists. Remove it. `shadow_only` on the evaluator class controls aggregation containment.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Ring 0 AI Infrastructure (read first)
- `src/core/ai/base_agent.py` — `BaseAIWorker`, `IAIAgent` Protocol; `_llm_generate()` and `_llm_generate_structured()` are the patterns `_run_typed()` mirrors; TYPE_CHECKING import pattern for Ring 1 types
- `src/core/ai/evaluator.py` — `Evaluator` (extends `BaseAIWorker`); `_build_multiplier_output()` is what `SkepticEvaluator._compute()` calls after `_run_typed()` returns
- `src/core/ai/output.py` — `AgentOutput` schema; payload: Any pattern (Ring 0 precedent for typing)

### LLM Chain (LLMAdapter routes through this)
- `src/core/llm/chain.py` — `LLMProviderChain`; `generate()` and `generate_structured()` signatures; how `audit_context` is passed and published to `llm_calls`
- `src/core/llm/litellm_backend.py` — `LiteLLMBackend`; circuit breaker implementation that LLMAdapter must not bypass

### Domain Types (Ring 1 — TYPE_CHECKING only in Ring 0 files)
- `src/intelligence/ai/context.py` — `SignalContext` (formerly `AIContext`); this is the `signal_context` field type passed into WorkerContext at runtime
- `src/intelligence/ai/alpha/skeptic_agent.py` — current `SkepticEvaluator`; the migration target
- `src/intelligence/ai/alpha/skeptic_prompts.py` — `SkepticResult`, `build_skeptic_prompt`, `ACTIVE_VERSION`; result schema shared by migrated evaluator

### Service integration
- `services/alpha_swarm.py` — `AlphaSwarm` (formerly `AlphaSwarmComputeAgent`); how evaluators are constructed in `_setup()` and called in the swarm loop
- `docs/foundation/naming-system.md` — Ring 0/Ring 1 boundary rules; no version suffixes in class names

### Naming alignment (prior phase decisions)
- `.planning/phases/110-renaissance-rename/110-CONTEXT.md` — canonical rename table; all class/file names used in Phase 095 must match Wave 1/2 renames
- `.planning/phases/111-naming-alignment/111-CONTEXT.md` — Ring 0 boundary enforcement; `src/core/ai/` is Ring 0, `src/intelligence/` is Ring 1

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `BaseAIWorker._build_audit_context()` — builds the `audit_context` dict injected into every `chain.generate()` call. `LLMAdapter.request()` should use the same logic (or call this method via the context).
- `BaseAIWorker._timeout_s` — already computed from `latency_budget_ms / 1000.0` in `__init__`. `_run_typed()` reads this directly — no recalculation.
- `BaseAIWorker._llm_generate_structured()` — the instructor-path predecessor to `_run_typed()`. Read its audit injection pattern before implementing `_run_typed()`.
- `Evaluator._build_multiplier_output()` — the output builder `SkepticEvaluator._compute()` calls after `_run_typed()`. Signature: `(context, multiplier, confidence, payload, prompt_version) -> AgentOutput`.
- `SkepticResult` in `skeptic_prompts.py` — existing Pydantic model; becomes the `result_type` for `SkepticEvaluator`.

### Established Patterns
- **Ring 0 TYPE_CHECKING imports** — `if TYPE_CHECKING: from src.intelligence.ai.context import SignalContext`. Runtime annotations use string form. `WorkerContext` must follow this for `LLMProviderChain` and any Ring 1 types.
- **`audit_context` injection** — `chain.generate(audit_context={call_id, agent_id, prompt_version, symbol, ...})`. This is how every LLM call lands in `llm_calls`. `LLMAdapter` must inject this.
- **`shadow_only = True`** — class attribute on every evaluator. Graduation loop flips it. Phase 095 does not touch shadow promotion logic.

### Integration Points
- `BaseAIWorker.__init__` — `_run_typed()` relies on `self._llm` (set by swarm in `_setup()`) and `self._timeout_s`. These are inherited; no init changes needed.
- `AlphaSwarm._setup()` — constructs `SkepticEvaluator(llm_chain=self._llm_chain)`. No change needed after migration — interface stays the same.
- `pydantic-ai` — NOT yet installed. Plan must add `pydantic-ai>=1.0,<2` to `requirements.txt` as first task.

</code_context>

<specifics>
## Specific Ideas

- **Use pydantic-ai fully** — don't rebuild retry logic, validation, or schema handling that pydantic-ai already provides correctly. Add value only where pydantic-ai has no opinion (audit trail, circuit breaking).
- **Straight replacement for Skeptic** — no parallel V1/V2 experiment. When you have the better approach, commit. Running both doubles Ollama load with no additional data value once the approach is validated at the framework level.
- **Compute cost discipline** — every inference costs. `_default_max_tokens` ClassVar should be conservative (2048 default). Evaluators that need more override it explicitly.

</specifics>

<deferred>
## Deferred Ideas

- **Narrative/risk agent typed output** — `_run_typed` will be available to them via `BaseAIWorker`, but migration of those agents is not Phase 095 scope.
- **Zep episodic memory** — `memory_client` field on `WorkerContext` reserved for Phase 097.
- **DSPy prompt optimization** — reads from `llm_calls` audit trail. Phase 098.
- **Qualitative pipeline todos** (P-CTX-03a, P-CTX-03b, P-CTX-04) — scored 0.4-0.6 on keyword match but are out of Phase 095 scope. Reviewed and deferred.

</deferred>

---

*Phase: 095-pydantic-ai-agents*
*Context gathered: 2026-05-31*
