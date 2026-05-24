# Milestone v2.8 Requirements — Infrastructure Hardening + AI Platform

**Milestone:** v2.8 — Infrastructure Hardening + AI Platform
**Status:** Active
**Created:** 2026-05-24
**Previous milestone:** v2.7 (archived, Phases 093, 100, 100.5, 104, 105)

---

## Design Contract (Renaissance Standard)

Every requirement must satisfy:
1. **Measurable hypothesis** — each AI platform phase states the metric it must move (parse failure rate, latency, maintenance burden, LOC reduction). No phase earns its place without naming the measurement.
2. **Shadow mode first** — no new behavior promoted without evidence gate. Gate criterion stated in the requirement.
3. **Zero blast radius** — `BaseGroupService`, `CircuitBreaker`, `OTel`, `shadow_registry`, `signal_ledger`, Kafka topology unchanged unless explicitly listed.
4. **Compute cost counted** — new external service dependencies (Zep, DSPy) must justify their RAM/latency overhead before enabling. Estimate stated in requirement.
5. **Evidence gates respected** — phases 097, 098, 099 each gate on measurable outcomes from prior phases. If the gate fails, the phase is deferred, not bypassed.
6. **Microservices DAG discipline** — no new Kafka topics without a clear producer-consumer pair. No new systemd daemons without a named replacement or explicit justification. Compute is in-process; persistence is the DAG boundary.

---

## Active Requirements

### FOUND — Foundation Hardening (Phase 106)

Close structural debt that would create drag or failures during AI platform phases.

- [ ] **FOUND-01**: Dead code deleted: `ShadowRecorder`, stale `GuardrailsValidator` class, and 7 dead `Settings` fields; zero orphaned classes or fields remain after Phase 106
- [ ] **FOUND-02**: `_DAG_ORDER` in `service_auditor_agent.py` accurately lists all deployed services; `_ONESHOT_UNITS` guard prevents oneshot (ML batch) services from being restarted by the auditor; lag thresholds and agent-id label keys corrected
- [ ] **FOUND-03**: `bar_aggregator_agent` retry loop replaced with `BaseAgent._setup_with_retry`; 3 JSONB `asyncpg.create_pool` bypasses consolidated to the DB pool wrapper — shared retry and pool infrastructure reused, not re-implemented
- [ ] **FOUND-04**: `intelligence_pipeline_agent` and `journal_writer_agent` use `enqueue_blocking` (bounded backpressure); `PluginStateManager` uses O(1) symbol index dict; `process_bar_inner` traced via `observed_span` for hot-path visibility
- [ ] **FOUND-05**: `PluginCircuitBreaker` populated from the `circuit_breakers` dict in the intelligence pipeline; shadow-mode trip enabled flag controls live circuit breaking; OTel `UpDownCounter` emits breaker state per plugin
- [ ] **FOUND-06**: Regression suite covers Phase 106 changes; `pytest tests/unit/` green after all plans execute

### HYGIENE — Infrastructure Hygiene (Phase 107)

Audit and close accumulated DB and observability debt before AI platform work begins.

- [ ] **HYGIENE-01**: Audit query identifies all DB tables with zero live writers or readers for >= 30 days (cross-check against service DAG); confirmed-unused tables dropped via numbered migration with rollback script
- [ ] **HYGIENE-02**: All agents stuck at `shadow_only=True` indefinitely audited — root cause documented per agent (insufficient data, criteria threshold, code bug); at least one concrete, evidence-backed path to graduation unblocked per agent; zombie agents (no path to graduation) demoted via shadow_registry
- [ ] **HYGIENE-03**: `shadow_registry` bootstrap CI computation verified end-to-end: correct column read (`pnl_r` from `signal_ledger`), correct stats function, result matches manual calculation; any code bug fixed; graduation criteria reviewed against available data volume
- [ ] **HYGIENE-04**: Metrics naming audit: all shadow-related metrics use correct OTel instrument types; no `Counter` measuring a level quantity, no `UpDownCounter` misused where a `Gauge` is correct; metric names follow `indicagent_<service>_<metric>_<unit>` convention; ruff check passes on all metric call sites

### LLM-INFRA — LiteLLM Provider Abstraction (Phase 094)

**Hypothesis:** Hand-rolled `OllamaProvider`/`OpenRouterProvider`/`LLMChain` internals total ~450 LOC of bespoke provider logic. LiteLLM reduces this to configuration. Metric: provider LOC before vs after; parse failure rate unchanged.

- [ ] **LLM-INFRA-01**: `LiteLLMBackend` wraps `litellm.acompletion()` with existing `PluginCircuitBreaker` instances; Ollama and OpenRouter configured via model strings, no bespoke connection logic
- [ ] **LLM-INFRA-02**: `LLMProviderChain.generate()` public interface unchanged after migration; `BaseGroupService` and all callers require zero modification
- [ ] **LLM-INFRA-03**: Kafka audit callbacks, `SemanticCache`, and `TokenBudget` integrations preserved unchanged through the LiteLLM swap
- [ ] **LLM-INFRA-04**: `last_provider_id` and `last_token_usage` fields populated by `LiteLLMBackend` to maintain parity with existing provider tracking
- [ ] **LLM-INFRA-05**: `OllamaProvider`, `OpenRouterProvider`, and `LLMChain` internal classes deleted after migration; LOC delta confirms reduction >= 300 lines net

### STRUCT-OUT — Instructor Structured Output (Phase 094/095)

**Hypothesis:** Manual `_parse_multiplier_response()` methods total ~200 LOC across agents and have an unquantified parse failure rate. Instructor's validation-error retry loop reduces parse failures measurably. Metric: `llm_calls.parse_success` rate before vs after.

- [ ] **STRUCT-OUT-01**: `InstructorClient` wraps `LiteLLMBackend` with `instructor.from_litellm()`; all agent JSON parsing routes through Instructor retry loop
- [ ] **STRUCT-OUT-02**: On parse failure, Instructor injects the Pydantic `ValidationError` back into the prompt and retries up to `max_retries=3`; no agent implements its own retry loop
- [ ] **STRUCT-OUT-03**: Parse failure rate measured via `llm_calls.parse_success` before Phase 094 ships and after; improvement documented; if no improvement, STRUCT-OUT is not promoted
- [ ] **STRUCT-OUT-04**: Each agent declares one typed `BaseModel` result class; `_parse_multiplier_response` and `_validate_*_fields` boilerplate methods deleted; LOC reduction confirmed

### AGENT-EXEC — Pydantic AI Agent Execution Layer (Phase 095)

**Hypothesis:** `BaseAIAgent._compute()` boilerplate (context construction, error handling, neutral fallback) is repeated per agent. Pydantic AI's `RunContext[AgentDeps]` eliminates this. Metric: boilerplate LOC reduction in migrated agents; shadow calibrated_confidence delta unchanged.

- [ ] **AGENT-EXEC-01**: `PydanticAIAdapter` wraps `pydantic_ai.Agent[AgentDeps, ResultType]` behind the existing `_compute()` protocol; agents need not know about Pydantic AI internals
- [ ] **AGENT-EXEC-02**: `AgentDeps` typed dependency container threads `signal_context`, `llm_chain`, `db_pool`, and optional `memory_client` via `RunContext[AgentDeps]`
- [ ] **AGENT-EXEC-03**: One agent (Skeptic) migrated to Pydantic AI as the reference implementation; all other agents remain on `BaseAIAgent` until individually migrated
- [ ] **AGENT-EXEC-04**: Migrated agents run shadow-only until `calibrated_confidence` delta vs baseline is measured over >= 100 inferences; promotion requires explicit operator action
- [ ] **AGENT-EXEC-05**: `BaseAIAgent` not deleted; migration is incremental; `PydanticAIAdapter` and `BaseAIAgent` coexist until all agents migrate

### AGENT-REG — Agent Registry (Phase 096)

**Hypothesis:** Adding a new agent today requires Python file creation, service restart with code deploy. YAML registry decouples agent identity from code. Metric: operator can add an agent with zero Python changes.

- [ ] **AGENT-REG-01**: `agents.yaml` defines all agent identities (`agent_id`, `group`, `model_override`, `shadow_only`, `latency_budget_ms`, `prompt_version`); runtime reads at startup
- [ ] **AGENT-REG-02**: `AgentRegistry` instantiates agents from YAML spec; operator adds an agent by editing `agents.yaml` and restarting the service — no Python file changes required
- [ ] **AGENT-REG-03**: `AgentRegistry` enforces that all registered agents implement `_compute()` protocol; startup fails fast on invalid spec
- [ ] **AGENT-REG-04**: `shadow_registry` DB table remains the promotion/demotion authority; `agents.yaml` controls identity and config, not graduation status

### MEM — Episodic Memory (Phase 097)

**Hypothesis:** Agents lack cross-inference context; the same regime + setup conditions produce inconsistent confidence because the agent has no memory of prior outcomes. Zep episodic memory surfaces relevant past episodes. Metric: agent calibrated_confidence stability (variance reduction) in shadow mode over >= 200 inferences.

**Compute cost gate (must document before enabling):** Zep service RAM footprint vs available headroom; recall p95 latency must remain <= 50ms (agent latency budget); if p95 > 50ms, feature stays disabled.

- [ ] **MEM-01**: `ZepMemoryClient` provides `recall(context: AIContext) -> list[Episode]` and `store(episode: Episode)`; agents receive it via `AgentDeps.memory_client`
- [ ] **MEM-02**: Memory recall scoped by `(regime_type, symbol, setup_type)` to surface contextually relevant episodes
- [ ] **MEM-03**: Memory gated behind `ZEP_MEMORY_ENABLED` feature flag, default `False`; enabled only after shadow-mode recall quality metric (confidence stability) is measured and shows improvement
- [ ] **MEM-04**: Recall latency measured per-call via OTel histogram; p95 documented; must not exceed 50ms

### OPT — DSPy Offline Prompt Optimizer (Phase 098)

**Hypothesis:** Prompts are hand-authored. DSPy can compile better variants using labeled (prompt, result, outcome) data from `llm_calls`. Metric: A/B win rate delta, parse failure delta, calibrated_confidence delta for optimized vs baseline prompts.

**Data gate:** At least 500 resolved, labeled rows per agent in `llm_calls` (outcome != NULL) before running optimizer. If data gate not met, phase is deferred.

- [ ] **OPT-01**: `DSPyOptimizer` reads labeled `(prompt, result, outcome)` tuples from `llm_calls` where `outcome IS NOT NULL`; compiles optimized prompt variants offline; data gate verified before first run
- [ ] **OPT-02**: Optimized prompts stored in `prompt_versions` table; `prompt_version` field in `llm_calls` enables controlled A/B comparison
- [ ] **OPT-03**: Optimizer runs as a timer-triggered batch job; zero coupling to live inference path; uses in-process DB connection, no new service required
- [ ] **OPT-04**: A/B report shows measurable improvement (win rate delta, parse failure delta, calibrated_confidence delta) before any optimized prompt is promoted to default

### GUARD — Guardrails AI Output Validation (Phase 099)

**Evidence gate:** GUARD-01 through GUARD-03 execute **only if** post-Instructor parse failure rate (STRUCT-OUT-03) remains above 1%. If Instructor already brings parse failures below 1%, Phase 099 is deferred — adding another validation layer without evidence is waste.

**Hypothesis (conditional):** Residual post-Instructor parse failures indicate field-level validation Instructor cannot handle. Guardrails AI handles these as a drop-in validator. Metric: parse failure rate further reduced vs post-Instructor baseline.

- [ ] **GUARD-01**: `GuardrailsAIValidator` implements same interface as existing `GuardrailsValidator`; drop-in replacement, zero call-site changes
- [ ] **GUARD-02**: Guardrails AI replaces custom `_validate_*_fields` methods; total custom validation LOC reduced vs post-Instructor baseline
- [ ] **GUARD-03**: Latency overhead measured; must not exceed 10ms p95 vs existing validator

### FIT — Composite Fitness Function (Phase 101)

**Hypothesis:** Current shadow graduation (n >= 100, bootstrap_ci_lower(pnl_r) > 0) is a blunt gate. A composite fitness function across 5 dimensions produces a ranked population — prerequisite for any evolutionary approach. Metric: fitness score discriminates between agents (variance across agents >= 0.2).

**Gate for 102-103:** Phase 102 and 103 do not begin until Phase 101's composite score shows discriminative power across the live agent population. If all agents score within 0.1 of each other, the fitness function is not ready.

- [ ] **FIT-01**: Bootstrap CI, Sharpe ratio, and win rate with statistical significance computed per agent; stored in `agent_fitness` table; all three observable before Phase 102 begins
- [ ] **FIT-02**: Novelty score computed as decorrelation from live agent population; prevents redundant agents from surviving genetic selection
- [ ] **FIT-03**: Calibration metric: confidence vs realized outcome alignment per agent via reliability diagram; stored per agent
- [ ] **FIT-04**: Regime specificity: performance segmented by `hmm_regime` label (bull/bear/sideways/volatile); agents with regime-specific edge identified
- [ ] **FIT-05**: Efficiency metric: output quality / (latency × tokens); penalizes expensive agents with marginal edge; compute cost counted explicitly
- [ ] **FIT-06**: Composite score: weighted sum of FIT-01–05 stored in `agent_fitness`; discriminative power gate (cross-agent score variance >= 0.2) must pass before Phase 102 can proceed

### GENE — Genetic Infrastructure (Phase 102)

**Depends on:** FIT-06 discriminative power gate passed.

- [ ] **GENE-01**: `agent_genomes` TimescaleDB table stores full genome serialization (prompt, config, tool set, `agent_id`) for every graduated agent; schema versioned
- [ ] **GENE-02**: Gene bank catalogs best-performing chromosome segments extracted from demoted agents; queryable by segment type and historical fitness
- [ ] **GENE-03**: Decomposition algorithm extracts highest-fitness chromosomes from failed agents with documented extraction criteria
- [ ] **GENE-04**: Resurrection evaluation: demoted agents tested against new data; candidates with fitness > promotion threshold flagged for operator review; no automatic promotion

### REPRO — Reproductive Operators (Phase 103)

**Depends on:** FIT-06 gate passed; GENE-01–04 operational.

All offspring start at `shadow_only=True`. No offspring are promoted without explicit fitness validation via Phase 101 composite score >= parent fitness.

- [ ] **REPRO-01**: Mutation operator applies perturbations to prompts, configs, and parameters; offspring registered in `shadow_registry` as `shadow_only=True`
- [ ] **REPRO-02**: Recombination operator crosses two parent agents to create offspring inheriting best chromosomes; offspring evaluated via FIT composite score before any promotion
- [ ] **REPRO-03**: LLM-directed operator analyzes parent performance data from `llm_calls` and proposes targeted improvements; output is a candidate genome, not an auto-deployed agent
- [ ] **REPRO-04**: Adaptive operator selection tracks per-operator fitness improvement rate over >= 50 offspring; budget allocated proportionally to operator success rate

---

## Future Requirements (deferred)

| Requirement | Reason for deferral |
|-------------|---------------------|
| Multi-agent orchestration (CrewAI / AutoGen) | Agent count does not justify coordination overhead yet |
| Fine-tuned local models | Requires >= 10K labeled signals per setup type |
| Streaming structured output | No consumer needs token-level streaming |
| External user-created agents (plugin marketplace) | Requires auth layer first |
| RAG over market data | No evidence document retrieval outperforms episodic memory |
| Population-level genetic selection (generation-over-generation) | Requires >= 20 graduated agents; current population is 4-5 |

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| Replacing BaseGroupService | It owns Kafka, DB pool, metrics — it works; no justification |
| Replacing CircuitBreaker | LiteLLM failure handling lacks true half-open state; ours is superior |
| Replacing OTel / structlog | Infrastructure layer — no AI-specific reason to change |
| Removing shadow_registry / graduation | Core quality gate — cannot be removed |
| Real-time prompt optimization | DSPy is an offline compiler; online optimization is a different problem class |
| Auto-promotion of genetic offspring | Evidence gate required; operator must confirm |

---

## Traceability

| Phase | Requirements |
|-------|-------------|
| 106 | FOUND-01–06 |
| 107 | HYGIENE-01–04 |
| 094 | LLM-INFRA-01–05, STRUCT-OUT-01–04 |
| 095 | AGENT-EXEC-01–05 |
| 096 | AGENT-REG-01–04 |
| 097 | MEM-01–04 |
| 098 | OPT-01–04 |
| 099 | GUARD-01–03 (gated on STRUCT-OUT-03 parse failure rate) |
| 101 | FIT-01–06 |
| 102 | GENE-01–04 (gated on FIT-06) |
| 103 | REPRO-01–04 (gated on FIT-06 + GENE-01–04) |
