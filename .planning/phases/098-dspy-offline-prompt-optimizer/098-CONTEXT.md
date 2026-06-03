# Phase 098: DSPy Offline Prompt Optimizer - Context

**Gathered:** 2026-06-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Build an offline, timer-triggered batch optimizer that reads labeled `(prompt, input, outcome)` tuples from `llm_calls`, compiles optimized prompt variants per agent using DSPy BootstrapFewShot, stores compiled variants in a new `prompt_versions` table, runs a 7-day A/B window against the baseline, and auto-promotes when the promotion criteria are met.

**In scope:**
- `services/dspy_optimizer.py` — oneshot batch entrypoint (mirrors `ml_training_agent.py` pattern)
- `src/intelligence/optimization/dspy_optimizer.py` — `DSPyOptimizer` core class
- Migration: `prompt_versions` table + status enum
- Per-agent data gate check (>= 500 labeled rows per agent in `llm_calls`)
- DSPy BootstrapFewShot compilation per eligible agent
- Compiled variant written to `prompt_versions` as JSONB
- A/B routing via `prompt_version` column already in `llm_calls`
- Auto-promotion after 7 days (with regime-balance guard)
- Comparison report: `logs/dspy_optimizer_report_{date}.json` + structlog summary
- `indicagent-dspy-optimizer.service` + `.timer` (weekly, Monday 2am ET)
- `job_completed_total{job="dspy-optimizer", status}` at exit

**Out of scope:**
- Hot-swap of prompts without service restart
- Cross-agent joint optimization (COPRO)
- LLM call budget tracking changes to `LLMProviderChain`
- New agent implementations

**Depends on:** Phase 096 (AgentRegistry — `AGENT_MODULES`, `agent_id` class registration)

</domain>

<decisions>
## Implementation Decisions

### D-01: DSPy Optimizer Class — BootstrapFewShot
Use `dspy.BootstrapFewShot` (not MIPROv2 or COPRO). Rationale: simplest optimizer that works for this use case. MIPROv2 requires meta-LLM calls during optimization (circular cost on local Ollama). BootstrapFewShot is deterministic, fast (minutes on 500 rows), interpretable, and composes directly with the existing `PROMPT_REGISTRY` template structure. One agent, one optimizer run, one compiled output — no hidden meta-optimization cost.

### D-02: Training Signal — `parse_success`
Optimize against `parse_success` (boolean column in `llm_calls`). Rationale: cleanest, most attributable signal. A failed parse is always a prompt problem. `pnl_r` and win rate are downstream of market conditions, regime, and the full I1–I7 pipeline — too noisy to attribute to prompt quality. `parse_success` is the correct SoC boundary: the optimizer owns parse quality, the ML layer owns alpha quality. Do not mix them.

### D-03: Per-Agent Independent Runs
Each agent is compiled independently. The optimizer loops over agents with sufficient data, skips ineligible ones (log row counts for skipped agents), and proceeds to optimize the rest. One ineligible agent never blocks another. Agents that run at different volumes (alpha vs narrative) are never coupled in the optimization loop.

### D-04: DSPy ↔ PROMPT_REGISTRY Interface
The optimizer imports each agent's `PROMPT_REGISTRY` and uses the `ACTIVE_VERSION` template as the DSPy `Signature`/module base. After compilation, the compiled DSPy program state (few-shot examples injected) is serialized to JSONB and written to `prompt_versions`. No Python prompt file is modified by the batch job — DB is the only output.

### D-05: `prompt_versions` Table Schema
Minimal schema:
- `version_id` UUID PK
- `agent_id` TEXT (references `agent_id` class attribute)
- `version_tag` TEXT UNIQUE (e.g., `correlation_v2_dspy_20260602`)
- `compiled_prompt` JSONB (full DSPy compiled program state including few-shot demos)
- `status` TEXT (`candidate` / `active` / `retired`) with CHECK constraint
- `created_at` TIMESTAMPTZ DEFAULT NOW()
- `promoted_at` TIMESTAMPTZ (null until promoted)

Store as JSONB for transparency and queryability (e.g., `jsonb_array_length(compiled_prompt->'demos')` tells you how many examples were injected). Status field enables A/B routing via a DB field flip with no application code change.

### D-06: Inference-Time Prompt Loading — Startup, Not Per-Call
At `BaseGroupCoordinator` startup, `AgentRegistry.build()` loads the `active` prompt version for each agent from `prompt_versions` and injects it via `AgentDependencies`. Cached in memory for the service lifetime. No DB read in the live inference path. DAG Invariant 3: live pipeline is DB-ignorant. Promotion takes effect on next systemd restart — same deployment mechanism as contract rolls and calibration curve updates.

### D-07: Data Gate — Per-Agent, Skip Ineligible
Gate: `COUNT(*) >= 500` in `llm_calls WHERE agent_id = ? AND outcome IS NOT NULL`. Per-agent check. Ineligible agents are skipped and logged (with exact row count). Eligible agents proceed. When zero agents are eligible, emit `job_completed_total{status="skipped_data_gate"}` with per-agent counts in the structlog event body, then exit cleanly. Do not abort.

### D-08: Run Schedule — Weekly, Monday 2am ET
Weekly cadence (Monday 02:00 ET). Rationale: prompt optimization is a slow signal — labeled outcomes require trade lifecycle to settle (1–5 days). Weekly gives sufficient accumulation time between runs. Nightly would hit the data gate most nights and produce redundant skipped runs. Monthly is too slow for prompt drift correction. Consistent with `ml-orchestrator` and `ml-discovery` batch cadence.

### D-09: Auto-Promotion with Regime-Balance Guard
Auto-promote a `candidate` version after 7 days of A/B traffic when all of the following hold:
1. `parse_success_candidate > parse_success_baseline + 0.02` (2pp improvement, not noise)
2. `n >= 100` inference calls in the A/B window for this agent
3. Regime balance: >= 20 examples from each of `bullish`, `bearish`, `ranging` regime in the A/B window (guards against confounded single-regime windows)

If regime balance is not met at 7 days, extend the window 7 more days before checking again. Auto-promotion is a second optimizer pass that checks these criteria and updates `prompt_versions.status` from `candidate` → `active` and retires the previous active version. Manual review is not required — if the criteria can be stated precisely, they can be automated.

### D-10: A/B Comparison Report
Write `logs/dspy_optimizer_report_{date}.json` with per-agent comparison stats (parse_success baseline vs candidate, win rate delta, parse failure delta, calibrated_confidence delta, regime breakdown, n per version). Also emit a structlog event with the summary. No new DB table — the source data is already queryable via `llm_calls GROUP BY prompt_version`. The report file is a derived audit artifact.

### D-11: Observability
Emit `job_completed_total{job="dspy-optimizer", status}` at exit (D-06 oneshot contract per CLAUDE.md). Status values: `success`, `failure`, `skipped_data_gate`. Structlog events for: per-agent gate check result (row count), per-agent compilation duration, per-agent variant written, per-agent promotion check result.

### Claude's Discretion
- DSPy `Signature` field naming conventions for this domain
- Internal retry/timeout handling if Ollama is unavailable during optimization
- Exact JSONB structure of `compiled_prompt` field (DSPy's native serialization format)
- Whether to run compilation with the same Ollama model used in production or a dedicated optimization model

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Batch Job Pattern
- `services/ml_training_agent.py` — canonical oneshot entrypoint pattern (`JOB_COMPLETED_TOTAL`, `asyncio.run`, no daemon)
- `src/intelligence/services/ml_trainer.py` — pattern for a training service class consumed by the oneshot entrypoint

### Prompt Versioning Infrastructure
- `src/intelligence/ai/alpha/correlation_prompts.py` — reference implementation of `ACTIVE_VERSION`, `PROMPT_REGISTRY`, template structure that DSPy reads
- `src/intelligence/ai/TEMPLATE.py` — mandatory agent attrs including `prompt_version` class attribute
- `production/migrations/087_llm_calls_agent_attrs.sql` — `llm_calls` schema: `agent_id`, `prompt_version`, `parse_success`, `outcome` columns

### Agent Registry (Phase 096 dependency)
- `.planning/phases/096-agent-registry/096-CONTEXT.md` — D-01 through D-06: `AgentRegistry`, `AgentDependencies`, `AGENT_MODULES`, `BaseGroupCoordinator._setup()` wiring

### Core Rules
- `CLAUDE.md` §Done-Coding SOP + "Oneshot contract (D-06)" — `job_completed_total{job, status}` at script exit, `job` label matches systemd unit `%n` suffix exactly
- `CLAUDE.md` §DAG Invariants — Invariant 3 (no DB in live path), Invariant 6 (all timestamps UTC)
- `docs/foundation/naming-system.md` — service naming rules

### Migration Patterns
- `production/migrations/084_ai_enrichment_tables.sql` — pattern for AI-owned tables added alongside quant tables
- `production/migrations/099_dlq_quarantine.sql` — pattern for status-enum-driven tables with CHECK constraints

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `services/ml_training_agent.py` + `src/intelligence/services/ml_trainer.py`: copy the exact entrypoint pattern — `Settings()`, agent instantiation, `asyncio.run(agent.start())`, `JOB_COMPLETED_TOTAL`, `flush_and_shutdown_metrics()`
- `production/systemd/indicagent-ml-training.service` + `.timer`: template for the new `indicagent-dspy-optimizer.service` + `.timer`
- `src/core/database_manager.py`: asyncpg connection pool for reading `llm_calls` and writing `prompt_versions`

### Established Patterns
- All timer-triggered scripts are oneshot, not daemons — `Type=oneshot` in systemd unit
- `job_completed_total{job, status}` is mandatory at exit — any missing counter is a D-06 violation
- Agent startup loads config from DB once; no live DB reads during inference — prompt version follows the same rule
- `AGENT_MODULES` in `register_agents.py` is the explicit import list — no filesystem scanning

### Integration Points
- `llm_calls.prompt_version` is already written by `LLMProviderChain` via `base_agent.py` `_llm_generate()` — the A/B assignment path needs to inject the correct `prompt_version` string at agent startup, not per-call
- `AgentDependencies` dataclass (Phase 096) is the injection point for the loaded prompt version — extend it with `compiled_prompt: dict | None = None`
- `BaseGroupCoordinator._setup()` is where prompt version is loaded from DB and injected into `AgentDependencies` — one read per service startup

</code_context>

<specifics>
## Specific Ideas

- The 2pp parse_success improvement threshold for auto-promotion was explicitly chosen (not "any improvement") to avoid noise-driven promotions
- Regime balance guard (>= 20 examples per regime type) is the specific mechanism preventing confounded A/B windows
- `logs/dspy_optimizer_report_{date}.json` is the report format — consistent with existing log file naming in the system
- `version_tag` format: `{agent_id}_dspy_{YYYYMMDD}` (e.g., `correlation_v2_dspy_20260602`)

</specifics>

<deferred>
## Deferred Ideas

- Cross-agent joint prompt optimization (COPRO) — would require shared context between agents, violates SoC, belongs in a future phase if parse failures remain after per-agent optimization
- Hot-swap prompts without service restart — would require a `contracts.updated`-style Kafka topic for prompt updates; deferred per MEDIUM-02 in architecture review
- Prompt optimization for I1–I6 (non-LLM) plugins — not applicable, no prompts

</deferred>

---

*Phase: 098-dspy-offline-prompt-optimizer*
*Context gathered: 2026-06-02*
