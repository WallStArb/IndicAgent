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

**NOTE:** HYGIENE requirements redefined in Phase 107 CONTEXT.md Renaissance design from 4 to 9 criteria. See `.planning/phases/107-infrastructure-hygiene/REQUIREMENTS.md` for full specification.

- [x] **HYGIENE-01**: Writer flush path observability — All `*_writer_agent.py:_flush()` methods wrapped in `observed_span("writer.flush")` with batch_size and flush_ms attributes; DB operations emit child spans; flush errors set ERROR span status
- [x] **HYGIENE-02**: Metric type correctness — Shadow metrics (SHADOW_WIN_RATE, SHADOW_N_RESOLVED, SHADOW_EV_R, SHADOW_EV_CI_LOWER, SHADOW_DAYS_TO_GATE) changed from up_down_counter to gauge; latency metrics use histogram not counter; all metrics follow naming convention
- [x] **HYGIENE-03**: Silent data loss elimination — AttributeError bugs fixed (.inc() → .add(), self._pool → db_manager); ghost-run prevented (feature_writer raises on DB failure); super()._teardown() called; offset correctness with manual commit
- [x] **HYGIENE-04**: DAG topology correctness — All deployed services in _DAG_ORDER (current: 31, target: 42+); After= dependencies only valid units; priority levels match data flow; agent ID mapping consistent
- [ ] **HYGIENE-05**: Dead code elimination — ShadowRecorder, GuardrailsValidator, 8 dead Settings fields deleted; TEMPLATE agent fixed (self._llm.generate() → self._llm_generate()); pre-commit hook enforcement
- [ ] **HYGIENE-06**: Shadow registry integrity — Promotion/demotion queries filter shadows via `AND is_shadow = FALSE`; swarm agents skip signal_ledger queries (use signal_ai_enrichment); bootstrap CI validated
- [ ] **HYGIENE-07**: Service lifecycle consistency — All services inherit from BaseAgent (migrate signal_replay_auditor, bar_replay_provider); SIGTERM handling, stall detection, DLQ routing standardized
- [ ] **HYGIENE-08**: DatabaseManager pool standardization — All services use DatabaseManager.create_pool() (fix swarm_ledger_writer, bar_replay_provider, signal_replay_auditor bypass); JSONB codecs registered; pool gauges emitted
- [ ] **HYGIENE-09**: Agent ID label standardization — All metrics use `agent_id` label (not `agent`); BaseAgent and BaseWriterAgent label consistency fixed; fleet-wide Grafana dashboards work

### HEAL — Self-Healing Hardening (Phase 108)

**Hypothesis:** Three failure classes — undetected daemon death, unrecoverable DB loss, and infinite retry loops — remain unaddressed after Phase 107. Adding systemd WatchdogSec, nightly pg_dump, and runtime self-healing mechanisms closes all three. Metric: mean time to recovery for each failure class.

- [ ] **HEAL-01**: WatchdogSec rollout — All 39 daemon `.service` unit files gain `WatchdogSec=60`; `BaseAgent` heartbeat loop calls `sd_notify(WATCHDOG=1)` every 30s; `systemd-analyze verify` passes on all modified units
- [ ] **HEAL-02**: DB backup — `indicagent-db-backup.service` + `.timer` perform nightly `pg_dump` to `/var/backups/indicagent/`; `.sql.gz` exists and is < 25h old; retention script prunes files older than 7 days automatically
- [ ] **HEAL-03**: Circuit breaker health events — When `PluginCircuitBreaker` opens, an event is published to `system.health.events` with `type=circuit_breaker_open`, `plugin_id`, `failure_count`, `opened_at`; ServiceAuditor logs CB open events
- [ ] **HEAL-04**: DLQ quarantine + stuck consumer detection — Messages re-delivered > `DLQ_MAX_RETRIES` (default 3) are quarantined to `<topic>.dead-final` with metadata; ServiceAuditor emits a `consumer_stall` alert when consumer lag stops decreasing for > `STALL_TIMEOUT_SEC` (default 120s)

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

| Requirement | Phase | Status |
|-------------|-------|--------|
| FOUND-01 | 106 — Foundation Hardening | Pending |
| FOUND-02 | 106 — Foundation Hardening | Pending |
| FOUND-03 | 106 — Foundation Hardening | Pending |
| FOUND-04 | 106 — Foundation Hardening | Pending |
| FOUND-05 | 106 — Foundation Hardening | Pending |
| FOUND-06 | 106 — Foundation Hardening | Pending |
| HYGIENE-01 | 107 — Infrastructure Hygiene | Complete |
| HYGIENE-02 | 107 — Infrastructure Hygiene | Complete |
| HYGIENE-03 | 107 — Infrastructure Hygiene | Complete |
| HYGIENE-04 | 107 — Infrastructure Hygiene | Complete |
| HYGIENE-05 | 107 — Infrastructure Hygiene | Pending |
| HYGIENE-06 | 107 — Infrastructure Hygiene | Pending |
| HYGIENE-07 | 107 — Infrastructure Hygiene | Pending |
| HYGIENE-08 | 107 — Infrastructure Hygiene | Pending |
| HYGIENE-09 | 107 — Infrastructure Hygiene | Pending |
| HEAL-01 | 108 — Self-Healing Hardening | Pending |
| HEAL-02 | 108 — Self-Healing Hardening | Pending |
| HEAL-03 | 108 — Self-Healing Hardening | Pending |
| HEAL-04 | 108 — Self-Healing Hardening | Pending |
| LLM-INFRA-01 | 094 — LiteLLM + Instructor | Pending |
| LLM-INFRA-02 | 094 — LiteLLM + Instructor | Pending |
| LLM-INFRA-03 | 094 — LiteLLM + Instructor | Pending |
| LLM-INFRA-04 | 094 — LiteLLM + Instructor | Pending |
| LLM-INFRA-05 | 094 — LiteLLM + Instructor | Pending |
| STRUCT-OUT-01 | 094 — LiteLLM + Instructor | Pending |
| STRUCT-OUT-02 | 094 — LiteLLM + Instructor | Pending |
| STRUCT-OUT-03 | 094 — LiteLLM + Instructor | Pending |
| STRUCT-OUT-04 | 094 — LiteLLM + Instructor | Pending |
| AGENT-EXEC-01 | 095 — Pydantic AI Agent Execution Layer | Pending |
| AGENT-EXEC-02 | 095 — Pydantic AI Agent Execution Layer | Pending |
| AGENT-EXEC-03 | 095 — Pydantic AI Agent Execution Layer | Pending |
| AGENT-EXEC-04 | 095 — Pydantic AI Agent Execution Layer | Pending |
| AGENT-EXEC-05 | 095 — Pydantic AI Agent Execution Layer | Pending |
| AGENT-REG-01 | 096 — Agent Registry | Pending |
| AGENT-REG-02 | 096 — Agent Registry | Pending |
| AGENT-REG-03 | 096 — Agent Registry | Pending |
| AGENT-REG-04 | 096 — Agent Registry | Pending |
| MEM-01 | 097 — Zep Episodic Memory | Pending |
| MEM-02 | 097 — Zep Episodic Memory | Pending |
| MEM-03 | 097 — Zep Episodic Memory | Pending |
| MEM-04 | 097 — Zep Episodic Memory | Pending |
| OPT-01 | 098 — DSPy Offline Optimizer | Pending |
| OPT-02 | 098 — DSPy Offline Optimizer | Pending |
| OPT-03 | 098 — DSPy Offline Optimizer | Pending |
| OPT-04 | 098 — DSPy Offline Optimizer | Pending |
| GUARD-01 | 099 — Guardrails AI (conditional: parse failure rate > 1%) | Pending |
| GUARD-02 | 099 — Guardrails AI (conditional: parse failure rate > 1%) | Pending |
| GUARD-03 | 099 — Guardrails AI (conditional: parse failure rate > 1%) | Pending |
| FIT-01 | 101 — Composite Fitness Function | Pending |
| FIT-02 | 101 — Composite Fitness Function | Pending |
| FIT-03 | 101 — Composite Fitness Function | Pending |
| FIT-04 | 101 — Composite Fitness Function | Pending |
| FIT-05 | 101 — Composite Fitness Function | Pending |
| FIT-06 | 101 — Composite Fitness Function (gates Phases 102-103) | Pending |
| GENE-01 | 102 — Genetic Infrastructure (gated on FIT-06) | Pending |
| GENE-02 | 102 — Genetic Infrastructure (gated on FIT-06) | Pending |
| GENE-03 | 102 — Genetic Infrastructure (gated on FIT-06) | Pending |
| GENE-04 | 102 — Genetic Infrastructure (gated on FIT-06) | Pending |
| REPRO-01 | 103 — Reproductive Operators (gated on FIT-06 + GENE-01–04) | Pending |
| REPRO-02 | 103 — Reproductive Operators (gated on FIT-06 + GENE-01–04) | Pending |
| REPRO-03 | 103 — Reproductive Operators (gated on FIT-06 + GENE-01–04) | Pending |
| REPRO-04 | 103 — Reproductive Operators (gated on FIT-06 + GENE-01–04) | Pending |
