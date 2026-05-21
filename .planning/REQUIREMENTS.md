# Milestone v2.7 Requirements — AI Agent Platform Modernization

**Milestone:** v2.7 — AI Agent Platform Modernization
**Status:** Active
**Created:** 2026-05-20
**Previous milestone:** v2.6 (archived, Phases 084-092)

---

## Design Contract (Renaissance Standard)

Every requirement in this milestone must satisfy:
1. **Measurable hypothesis** — adoption justified by a concrete metric (parse failure rate, latency, maintenance burden, LOC reduction)
2. **Shadow mode first** — no new behavior promoted to production without evidence gate
3. **Zero blast radius** — existing `BaseGroupService`, `CircuitBreaker`, `OTel`, `shadow_registry`, `signal_ledger`, `Kafka` topology unchanged
4. **Single responsibility** — each layer has one job; no two layers solve the same problem
5. **Compute cost justified** — external service dependencies (Zep, DSPy) only enabled if ROI is measurable

---

## Active Requirements

### LLM-INFRA — LiteLLM Provider Abstraction

- [ ] **LLM-INFRA-01**: `LiteLLMBackend` class wraps `litellm.acompletion()` with existing `PluginCircuitBreaker` instances; Ollama (primary) and OpenRouter (fallbacks) configured via model strings
- [ ] **LLM-INFRA-02**: `LLMProviderChain.generate()` public interface is unchanged after migration; `BaseGroupService` and all callers require zero modification
- [ ] **LLM-INFRA-03**: Kafka audit callbacks, `SemanticCache`, and `TokenBudget` integrations are preserved unchanged through the LiteLLM backend swap
- [ ] **LLM-INFRA-04**: `last_provider_id` and `last_token_usage` fields are populated by `LiteLLMBackend` to maintain parity with existing provider tracking
- [ ] **LLM-INFRA-05**: Custom `OllamaProvider`, `OpenRouterProvider`, and `LLMChain` internal classes are deleted after migration; no dead code remains

### STRUCT-OUT — Instructor Structured Output

- [ ] **STRUCT-OUT-01**: `InstructorClient` wraps `LiteLLMBackend` with Instructor's `from_litellm()` integration; all agent JSON parsing routes through Instructor retry loop
- [ ] **STRUCT-OUT-02**: On parse failure, Instructor injects the Pydantic `ValidationError` back into the prompt and retries up to `max_retries=3`; no agent implements its own retry loop
- [ ] **STRUCT-OUT-03**: Parse failure rate (measured via `llm_calls` table parse_success field) is observable before and after migration; metric exists to validate hypothesis
- [ ] **STRUCT-OUT-04**: Each agent declares one typed `BaseModel` result class; `_parse_multiplier_response` and `_validate_*_fields` boilerplate methods are deleted after migration

### AGENT-EXEC — Pydantic AI Agent Execution Layer

- [ ] **AGENT-EXEC-01**: `PydanticAIAdapter` provides a bridge that wraps `pydantic_ai.Agent[AgentDeps, ResultType]` behind the existing `_compute()` protocol; agents need not know about Pydantic AI internals
- [ ] **AGENT-EXEC-02**: `AgentDeps` typed dependency container threads `signal_context`, `llm_chain`, `db_pool`, and optional `memory_client` to agents via Pydantic AI's `RunContext[AgentDeps]`
- [ ] **AGENT-EXEC-03**: One agent (Skeptic) is migrated to Pydantic AI as the reference implementation; all other agents remain on existing `BaseAIAgent` until migrated individually
- [ ] **AGENT-EXEC-04**: Migrated agents run in shadow mode (`shadow_only=True`) until calibrated_confidence delta vs baseline is measured over >= 100 inferences; promotion requires explicit operator action
- [ ] **AGENT-EXEC-05**: `BaseAIAgent` is not deleted; it remains as the base for unmigrated agents; migration is incremental, not big-bang

### AGENT-REG — Agent Registry

- [ ] **AGENT-REG-01**: `agents.yaml` defines all agent identities: `agent_id`, `group`, `model_override`, `shadow_only`, `latency_budget_ms`, `prompt_version`; runtime reads this at startup
- [ ] **AGENT-REG-02**: `AgentRegistry` class instantiates agents from YAML spec; operator can add an agent by editing `agents.yaml` and restarting the service — no Python file changes required
- [ ] **AGENT-REG-03**: `AgentRegistry` enforces that all registered agents implement the `_compute()` protocol; startup fails fast if any agent spec is invalid
- [ ] **AGENT-REG-04**: `shadow_registry` DB table remains the promotion/demotion authority; `agents.yaml` controls identity and config, not graduation status

### MEM — Episodic Memory (Zep)

- [ ] **MEM-01**: `ZepMemoryClient` provides `recall(context: AIContext) -> list[Episode]` and `store(episode: Episode)` interface; agents receive it via `AgentDeps.memory_client`
- [ ] **MEM-02**: Memory recall is scoped by `(regime_type, symbol, setup_type)` to surface contextually relevant past setups
- [ ] **MEM-03**: Memory is gated behind a feature flag (`ZEP_MEMORY_ENABLED`); disabled by default; enabled only after shadow-mode recall quality is validated
- [ ] **MEM-04**: Memory latency is measured per-call via OTel histogram; recall must complete within 50ms p95 to remain within agent `latency_budget_ms`

### OPT — DSPy Offline Prompt Optimizer

- [ ] **OPT-01**: `DSPyOptimizer` reads labeled (prompt, result, outcome) tuples from `llm_calls` table where `outcome` is non-null; compiles optimized prompt variants offline
- [ ] **OPT-02**: Optimized prompts are stored in `prompt_versions` table with A/B test assignment; `prompt_version` field in `llm_calls` enables controlled comparison
- [ ] **OPT-03**: DSPy optimizer runs as a timer-triggered batch job (not a daemon); optimizer does not touch the live inference path
- [ ] **OPT-04**: A/B comparison report (win rate delta, parse failure delta, calibrated_confidence delta) must show measurable improvement before any optimized prompt is promoted to default

### GUARD — Guardrails AI Output Validation

- [ ] **GUARD-01**: `GuardrailsAIValidator` implements the same interface as existing `GuardrailsValidator`; drop-in replacement with zero call-site changes
- [ ] **GUARD-02**: Guardrails AI replaces custom field-level validation in `_validate_*_fields` methods; total custom validation LOC is reduced
- [ ] **GUARD-03**: Latency overhead of Guardrails AI validation is measured and documented; must not exceed 10ms p95 vs existing validator

---

## Future Requirements (deferred)

| Requirement | Reason for deferral |
|-------------|---------------------|
| Multi-agent orchestration (CrewAI / AutoGen) | Not needed until agent count justifies coordination overhead |
| Fine-tuned local models | Requires labeled dataset accumulation — minimum 10K resolved signals per setup type |
| Streaming structured output | No consumer needs token-level streaming today |
| External user-created agents (plugin marketplace) | Future milestone — requires auth layer first |
| RAG over market data | No evidence that document retrieval improves signal quality vs episodic memory |

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| Replacing BaseGroupService | It owns Kafka, DB pool, metrics — it works; no justification for replacement |
| Replacing CircuitBreaker | LiteLLM's failure handling lacks true half-open state; existing CircuitBreaker is superior |
| Replacing OTel / structlog | Infrastructure layer — no AI-specific reason to change |
| Removing shadow_registry / graduation | Core quality gate — cannot be removed |
| Real-time prompt optimization | DSPy is an offline compiler; online optimization is a different problem class |

---

## Traceability

| Phase | Requirements covered |
|-------|---------------------|
| 093 | LLM-INFRA-01–05 |
| 094 | AGENT-EXEC-01–05 |
| 095 | AGENT-REG-01–04 |
| 096 | MEM-01–04 |
| 097 | OPT-01–04 |
| 098 | GUARD-01–03 |
