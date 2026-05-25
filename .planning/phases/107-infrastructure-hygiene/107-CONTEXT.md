# Phase 107: Infrastructure Hygiene — Context for GSD Workflows

**Gathered:** 2026-05-25
**Status:** Ready for planning
**Updated:** 2026-05-25 — Added execution strategy decisions from discussion

<domain>
## Phase Boundary

Audit and close accumulated DB and observability debt before AI platform work begins. Fix silent data loss, standardize service patterns, eliminate dead code, and ensure metrics correctness across 9 measurable criteria organized into 3 waves.

**Why this matters:** v2.8 AI platform (LiteLLM, DSPy, Zep memory, evolvable agents) requires a solid foundation. Silent data loss, corrupted metrics, and service inconsistencies will cause invisible regressions during LLM optimization.

**Dependencies:** Phase 106 (Foundation Hardening) — **COMPLETE**

</domain>

<decisions>
## Implementation Decisions

### Wave Execution Strategy
- **D-01:** Serial wave execution with verification gates — Wave 1 → deploy → verify → stabilize → Wave 2 → deploy → verify → stabilize → Wave 3 → deploy → verify
  - **Rationale:** Wave 1 changes (BaseAgent lifecycle, DatabaseManager pools) are high-risk. Parallel waves make rollback hell if Wave 2 reveals a Wave 1 bug. Serial waves with checkpoints prioritize debuggability over speed.
  - **Verification gate per wave:** Run the success SQL query from CONTEXT.md; only proceed if it returns TRUE.

### Dependencies
- **D-02:** Hard dependencies serialized — HYGIENE-07 (BaseAgent) before HYGIENE-01 (flush spans) on the same services; HYGIENE-08 (DatabaseManager) before HYGIENE-03 (AttributeError fixes) on the same services
  - **Rationale:** Can't add flush spans to services lacking proper teardown. Can't fix data loss bugs in services with broken DB connection handling.
- **D-03:** Within-wave parallelization allowed — HYGIENE-09 (agent ID labels) can run in parallel with HYGIENE-07/08 in Wave 1; Wave 2 criteria (HYGIENE-01/02/03) can run in parallel since they target disjoint services

### Scope
- **D-04:** Keep all 9 criteria — do not defer HYGIENE-05 (dead code deletion) to post-v2.8
  - **Rationale:** Dead code deletion is low-risk (git revert is trivial) and high-value (cognitive clarity during complex AI platform changes). Having ShadowRecorder, GuardrailsValidator, and 8 dead Settings fields around means developers constantly second-guess "Is this used?" and follow false trails.
- **D-05:** HYGIENE-09 (agent ID labels) is P1, not P3 — fleet-wide dashboards are broken today due to 50/50 label split; cannot observe system-wide behavior during v2.8 AI platform rollout if Grafana queries can't aggregate across all services

### Automation & Verification
- **D-06:** CI gates for static checks — Ruff checks for metric type violations (HYGIENE-02) and label consistency (HYGIENE-09); pre-commit hooks for dead code references (HYGIENE-05)
  - **Rationale:** Fail fast during development. CI must block PR merge if violations detected.
- **D-07:** Runtime queries with Grafana visibility — systemd timer runs verification queries every 15min; results written to `hygiene_status` table or logged to structlog; Grafana panel displays current state (green/red per criterion)
  - **Rationale:** "Zero tolerance for silent failures" means detecting failures automatically. For development/research, Grafana visibility is sufficient; no PagerDuty until production.
- **D-08:** Manual spot-checks for automation validation — bootstrap CI verification (HYGIENE-03), hand-calculation of `pnl_r` CI lower bound to validate query logic
  - **Rationale:** One-time validation that the automation itself is correct. Not a replacement for automated checks.

### Claude's Discretion
- Wave-to-wave stabilization time — let the system run for 1-2 hours after each wave deployment, monitor Grafana panels for anomalies before proceeding to next wave
- If any wave fails verification, rollback to previous wave's checkpoint before debugging — don't compound failures by pushing forward with broken foundation
- Verification queries can be refined during planning phase, but the binary success/failure nature must be preserved

### Prior Decisions from Project Context

**From Phase 104 (Storage Architecture Redesign):**
- Single source of truth principle — each fact lives in exactly one place (applies to metric definitions and DB queries)
- Separation of concerns — operational state vs analytical store are different workloads with different schemas

**From Phase 093 (Mathematical Correctness Audit):**
- Prove correctness via automated tests — every fix must have a verification query
- Renaissance principle: "If you can't measure it, you don't understand it"

**From v2.8 requirements (REQUIREMENTS.md):**
- Evidence gates respected — no phase ships without measurable improvement
- Shadow mode first — all new behavior runs shadow_only=True until validated
- Compute costs counted — every byte written, every query executed metered

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Requirements & Success Criteria
- `.planning/ROADMAP.md` L839-850 — Phase 107 goal, requirements, success criteria
- `.planning/REQUIREMENTS.md` L35-43 — HYGIENE-01 through HYGIENE-04 requirement text
- `.planning/phases/107-infrastructure-hygiene/REQUIREMENTS.md` — Full 9-criteria Renaissance design (HYGIENE-01 through HYGIENE-09)
- `.planning/phases/107-infrastructure-hygiene/RENAISSANCE-DELTA.md` — Expansion rationale from 4 to 9 criteria

### Source of Truth for Findings
- `docs/ideas/architectural-weakness-assessment.md` — **CRITICAL** — All 36 findings with file locations and line numbers; source of truth for all 9 HYGIENE criteria

### Reference Implementations & Patterns
- `src/core/agent/base.py` — BaseAgent lifecycle contract (what to migrate to for HYGIENE-07)
- `src/core/database_manager.py` — DatabaseManager pool with JSONB codecs (what to use for HYGIENE-08)
- `src/observability/metrics.py` — Current metric definitions (what to fix for HYGIENE-02)
- `src/observability/spans.py` — Span infrastructure and observed_span wrapper (patterns to follow for HYGIENE-01)
- `services/service_auditor_agent.py` — DAG order registry, _DAG_ORDER, _LAG_THRESHOLDS (what to update for HYGIENE-04)

### Phase 106 Foundation (What Was Already Delivered)
- `.planning/phases/phase-106/106-04-SUMMARY.md` — Hot path spans, tier latency histograms, backpressure, O(1) state lookup

### Target Files (What Gets Modified)
- `services/signal_replay_auditor_agent.py` — HYGIENE-07, HYGIENE-08
- `services/bar_replay_provider_agent.py` — HYGIENE-07, HYGIENE-08
- `services/swarm_ledger_writer_agent.py` — HYGIENE-03, HYGIENE-08
- `services/ctx_writer_agent.py` — HYGIENE-01, HYGIENE-03
- `services/llm_writer_service.py` — HYGIENE-01, HYGIENE-03
- `services/feature_writer_agent.py` — HYGIENE-01, HYGIENE-03
- `services/shadow_auditor_agent.py` — HYGIENE-02, HYGIENE-06
- `services/service_auditor_agent.py` — HYGIENE-04 (_DAG_ORDER, _LAG_THRESHOLDS)
- `src/config/settings.py` — HYGIENE-05 (dead fields)
- `src/core/ml/shadow.py` — HYGIENE-05 (ShadowRecorder)
- `src/core/llm/guardrails.py` — HYGIENE-05 (GuardrailsValidator)
- `src/intelligence/ai/TEMPLATE_agent.py` — HYGIENE-05 (TEMPLATE bug)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **BaseAgent lifecycle** (`src/core/agent/base.py`): Provides SIGTERM handling, stall detection, DLQ routing, metrics_port, tracer, topic_manifest. 38/42 services already use this pattern. Target for HYGIENE-07 migration.
- **DatabaseManager pool wrapper** (`src/core/database_manager.py`): Provides asyncpg.create_pool() with JSONB codecs registered, connection pooling, retry logic. 3 services bypass this today (swarm_ledger_writer, bar_replay_provider, signal_replay_auditor). Target for HYGIENE-08 standardization.
- **observed_span wrapper** (`src/observability/spans.py`): OpenTelemetry span context manager with ERROR status auto-recording on exception. Used in Phase 106 for hot path spans. Pattern to follow for HYGIENE-01 flush span wrapping.

### Established Patterns
- **Service DAG**: All services have declared dependencies in `_DAG_ORDER` (service_auditor_agent.py). Restart order is derived from this. Missing 11 services today (74% completeness). Pattern: add service to list, specify lag threshold, map agent_id to systemd unit name.
- **Metric naming convention**: `indicagent_<service>_<metric>_<unit>` (e.g., `indicagent_feature_writer_persistence_latency_seconds`). Not consistently followed today — 5 shadow metrics use wrong instrument types (up_down_counter instead of gauge). Fix target for HYGIENE-02.
- **Writer flush pattern**: All `*_writer_agent.py` services have `_flush()` methods that batch-write to DB. No span coverage today. Pattern: wrap entire `_flush()` body in `observed_span("writer.flush")` for HYGIENE-01.

### Integration Points
- **Systemd service lifecycle**: Services managed via systemd units in `production/systemd/`. BaseAgent `_setup()` installs SIGTERM handlers for graceful drain. Custom lifecycle services (signal_replay_auditor, bar_replay_provider) lack this.
- **Kafka consumer groups**: Each service has a dedicated consumer group. Service Auditor monitors lag per group. Missing services in `_DAG_ORDER` are invisible to lag monitoring.
- **Prometheus scraping**: Each service exposes `/metrics` on dedicated port. Metric labels must use `"agent_id"` (not `"agent"`) for fleet-wide dashboards. 50/50 split today breaks aggregation.

</code_context>

<specifics>
## Specific Ideas

### Renaissance Engineering Principles
- **Zero tolerance for silent failures** — data loss = alpha leakage = trading on incomplete information
- **Instrumentation before optimization** — measure the problem before fixing (flush spans reveal data loss; metric type fixes prevent false alerts)
- **Every component must earn its keep** — justify existence with measurements (dead code deleted; shadow governance queries fixed)
- **Simplicity over complexity** — smallest fix that solves the problem (serial waves over parallel waves; targeted fixes over architectural redesign)
- **Technical debt is quantifiable** — measure it, don't guess (verification queries return binary TRUE/FALSE for each criterion)

### Wave 1: Service Consistency (30%)
- **HYGIENE-07:** Migrate 2 services to BaseAgent — signal_replay_auditor_agent, bar_replay_provider_agent. Missing SIGTERM handling, stall detection, DLQ routing today.
- **HYGIENE-08:** Fix 3 services bypassing DatabaseManager.create_pool() — swarm_ledger_writer_agent, bar_replay_provider_agent, signal_replay_auditor_agent. Missing JSONB codecs → silent double-serialization.
- **HYGIENE-09:** Standardize all metrics on `agent_id` label (not `agent`). 50/50 split today breaks fleet-wide dashboards.

### Wave 2: Silent Failure Elimination (35%)
- **HYGIENE-01:** Wrap all `*_writer_agent.py:_flush()` in `observed_span("writer.flush")` — ctx_writer, llm_writer, feature_writer. Flush failures invisible today.
- **HYGIENE-02:** Fix 5 shadow metrics (up_down_counter → gauge), fix latency metrics (counter → histogram). Wrong metric types → alerts fire incorrectly.
- **HYGIENE-03:** Fix AttributeError bugs (ctx_writer `.inc()`, llm_writer `self._pool`), prevent ghost-run (feature_writer `db_manager = None`), add `super()._teardown()` (ctx_writer). Silent data loss = alpha leakage.

### Wave 3: Complexity Reduction (35%)
- **HYGIENE-04:** Add 11 missing services to `_DAG_ORDER`, fix systemd dependencies, resolve cyclic dependency. Wrong restart order → race conditions → silent data corruption.
- **HYGIENE-05:** Delete ShadowRecorder, GuardrailsValidator, 8 dead Settings fields, fix TEMPLATE agent. Dead code inflates maintenance burden.
- **HYGIENE-06:** Fix promotion/demotion queries (add `AND is_shadow = FALSE`), skip swarm agent ledger queries. Shadow signals contaminate live track → optimize for wrong objective.

### Success Criteria (Binary Verification)
**Single SQL query determines success:**
```sql
SELECT
  base_agent_adoption >= 100 AND
  db_manager_adoption >= 100 AND
  agent_id_consistency >= 100 AND
  writer_flush_coverage >= 100 AND
  metric_violations = 0 AND
  data_loss_rate = 0.00 AND
  dag_completeness >= 100 AND
  dead_violations = 0 AND
  shadow_violations = 0
as phase_107_success;
```

If query returns TRUE → Phase 107 complete → unblock v2.8 AI platform.
If query returns FALSE → Phase 107 incomplete → fix gaps.

</specifics>

<deferred>
## Deferred Ideas

### Reviewed Todos (not folded)
The following todos were reviewed but are out of scope for Phase 107:

- **013-earnings-provider-lane.md** (score 0.6) — Qualitative lane for earnings data integration. Belongs in future qualitative provider phase, not infrastructure hygiene.
- **014-macro-event-provider-lane.md** (score 0.6) — Qualitative lane for macro events (FOMC, CPI, NFP). Belongs in future qualitative provider phase.
- **015-qualitative-shadow-evaluation.md** (score 0.6) — Shadow evaluation gate for qualitative lanes. Belongs with qualitative provider work.
- **017-unified-intelligence-layer-modularization.md** (score 0.4) — Quant pipeline modularization. Architecture evolution, not infrastructure hygiene.
- **005-bi-analytics-layer-apache-superset.md** (score 0.2) — BI analytics layer. Tooling addition, not infrastructure debt.

### Other Deferred Ideas
- Kafka topic lifecycle management (process fix, not Phase 107 infrastructure debt)
- Test infrastructure health (design debt, not Phase 107 scope)
- Documentation audit (automate instead of manual audit)
- Health monitor standardization (too low priority for Phase 107)

</deferred>

---

**Phase: 107-Infrastructure Hygiene**
**Context gathered:** 2026-05-25 (Renaissance-designed: 9 criteria, 3 waves, measurement-driven)
**Updated:** 2026-05-25 (Execution strategy decisions: serial waves, all 9 criteria, automation with Grafana visibility)
