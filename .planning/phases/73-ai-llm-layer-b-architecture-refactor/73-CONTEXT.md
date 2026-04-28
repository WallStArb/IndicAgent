# Phase 73: AI LLM Layer B+ Architecture Refactor - Context

**Gathered:** 2026-04-28
**Status:** Ready for replanning (existing 6 plans need LineageRecorder updates)
**Source:** Updated from April 26 context; incorporates April 28 discussion decisions

<domain>
## Phase Boundary

This phase delivers the B+ Architecture Refactor of the AI/LLM layer. It:

1. Fixes 10 structural defects in the existing swarm/LLM layer
2. Creates a universal AI agent infrastructure (`src/core/ai/`) with shared base classes, context management, safe wrapper, and extension hooks for future observability/guardrails/security
3. Reorganizes agents into mandate-based groups under `src/intelligence/ai/` (alpha, narrative, risk)
4. Applies 6 LLM chain fixes (cache key, rate limiter, guardrails, auto-audit, real token counts, watchdog violation)
5. Adds a narrative TF gate (5m+ only)
6. Deletes the dead `swarm_orchestrator_agent` service and its systemd unit
7. Renames `swarm_dispatch_service.py` → `alpha_swarm_agent.py` (and class `SwarmDispatchComputeAgent` → `AlphaSwarmComputeAgent`)
8. Merges ShadowRecorder + TransformRecorder into unified `signal_lineage` table with Kafka-first `LineageRecorder`
9. Enforces import boundary discipline: AI layer imports nothing from `src/intelligence/pipeline/` or tier plugins

Phase does NOT include: Approach C (independent `src/ai/` package extraction), full AI observability/guardrails/security implementations (hooks only), or shadow governance (Phase 75).

</domain>

<decisions>
## Implementation Decisions

### Unified Signal Lineage (UPDATED 2026-04-28)
- **D-01:** Merge `alpha_multiplier_shadow` + `signal_transform_log` into single `signal_lineage` hypertable
- **D-02:** Schema: `signal_id`, `event_type` (transform | agent_prediction | lifecycle), `source` (transform_id or agent_id), `dag_order`, `multiplier`, `metadata` (JSONB for event-specific data), `is_shadow`, `ts`
- **D-03:** Single `LineageRecorder` class replaces both `ShadowRecorder` and `TransformRecorder` — Kafka-first, publishes to `topic_signal_lineage()`
- **D-04:** Single `LineageWriterAgent` consumes `topic_signal_lineage` and persists to `signal_lineage` — replaces `GraduationWriterAgent`'s write path and `swarm_writer_agent`'s shadow write path
- **D-05:** Deprecate `alpha_multiplier_shadow` table (write-only to `signal_lineage` going forward; old table kept for historical data)
- **D-06:** `graduation_loop` queries `signal_lineage WHERE event_type = 'agent_prediction'` for promotion/demotion data
- **D-07:** JSONB `metadata` holds event-specific fields: agent predictions store `{confidence, features, regime, path}`, transforms store `{before, after, segment_key}`, lifecycle stores `{outcome, pnl_r, mae, mfe}`

### Structural Defects to Fix (all locked)
- **D-08:** Delete `services/swarm_orchestrator_agent.py` (zero agents, competing with active dispatch service)
- **D-09:** Delete `/etc/systemd/system/indicagent-swarm-orchestrator.service`
- **D-10:** Rename `swarm_dispatch_service.py` → `alpha_swarm_agent.py`; class `SwarmDispatchComputeAgent` → `AlphaSwarmComputeAgent`
- **D-11:** LLM rate limiter — call `await limiter.acquire(tokens=max_tokens)` in `chain.py` before provider dispatch
- **D-12:** Guardrails — remove dead branch; if no schema registered, skip `validate()` entirely
- **D-13:** Auto-audit — add `audit_context: dict | None = None` param to LLMProviderChain; publish to `topic_llm_calls` when provided
- **D-14:** Real token counts — use `response_meta["usage"]["total_tokens"]` from OpenRouter when present; fallback to character-count estimate (len/4)
- **D-15:** Cache key — `SHA-256(system + full_prompt + model)` — remove `[:200]` truncation in `semantic_cache.py`
- **D-16:** Remove `WatchdogSec=60` + `NotifyAccess=main` from swarm-orchestrator systemd unit (already deleted by D-09)
- **D-17:** Replace private `_context_cache._cache` access in `_find_lead_context` with public `AIContextCache.get_lead(symbol, tf)` method

### New Infrastructure: `src/core/ai/` (5 new files + extension hooks)
- **D-18:** `base_agent.py` — `BaseAIAgent` ABC + `IAIAgent` Protocol with exact interface from design doc. Extension hooks: `_on_error(error)`, `_on_guardrail_violation(output)`, `_audit_payload: dict` property. `compute()` wrapper handles timing + error capture + hook dispatch.
- **D-19:** `base_group_service.py` — `BaseGroupService` shared dispatcher (extends existing `BaseAgent`). Extension hooks inherited from BaseAIAgent pattern.
- **D-20:** `context.py` — `AIContext`, `AIContextCache`, `Tier` enum, `TierContext` models (frozen Pydantic)
- **D-21:** `output.py` — `AgentOutput` universal envelope (untyped `payload` dict by design)
- **D-22:** `safe_wrapper.py` — `SafeAgentWrapper` (timeout + exception isolation, replaces `src/intelligence/swarm/safety.py`)

### Module Reorganization (locked)
- **D-23:** MOVE `src/intelligence/swarm/agents/skeptic_agent.py` → `src/intelligence/ai/alpha/skeptic_agent.py`
- **D-24:** MOVE `src/intelligence/swarm/agents/correlation_agent.py` → `src/intelligence/ai/alpha/correlation_agent.py`
- **D-25:** MOVE `src/intelligence/swarm/agents/volume_agent.py` → `src/intelligence/ai/alpha/volume_agent.py`
- **D-26:** MOVE `src/intelligence/narrative/` → `src/intelligence/ai/narrative/` (narrative_agent.py, prompts.py, parsers.py)
- **D-27:** PLACEHOLDER `src/intelligence/ai/risk/__init__.py` — empty, marks future group
- **D-28:** KEEP `src/intelligence/swarm/aggregator.py` (used by AlphaSwarmComputeAgent)
- **D-29:** KEEP `src/intelligence/swarm/graduation.py` (called by graduation_loop)
- **D-30:** ABSORB `src/core/swarm/base_agent.py` → `src/core/ai/base_agent.py`
- **D-31:** ABSORB `src/intelligence/swarm/context.py` → `src/core/ai/context.py`

### Group Services (locked)
- **D-32:** `AlphaSwarmComputeAgent` (in `services/alpha_swarm_agent.py`) extends `BaseGroupService`: group_id="alpha", has_graduation=True, aggregate_topic=topic_swarm_alpha, trigger_topics=[topic_intelligence_i7_signals], agents=[SkepticAgentComputeAgent, CorrelationAgentComputeAgent, VolumeAgentComputeAgent]
- **D-33:** `NarrativeGroupComputeAgent` (in `services/ai_narrative_agent.py`) extends `BaseGroupService`: group_id="narrative", has_graduation=False, aggregate_topic=None, trigger_topics=[topic_intelligence_journal], agents=[NarrativeComputeAgent]
- **D-34:** All existing swarm/narrative agents extend `BaseAIAgent` instead of `SwarmBaseAgent`

### Narrative TF Gate (locked)
- **D-35:** `NarrativeComputeAgent._compute()` rejects timeframes not in `{"5m", "15m", "1h", "4h", "1d"}` before any LLM call. Returns neutral AgentOutput when TF not in allowed set.

### Import Boundary Discipline (locked)
- **D-36:** `src/core/ai/` and `src/intelligence/ai/` import only from `src/intelligence/schemas.py` and `src/core/stream_keys.py`. Never import from `src/intelligence/pipeline/` or any tier plugin implementation.

### Shadow Mode Default (locked)
- **D-37:** All agents have `shadow_only=True` by default
- **D-38:** `graduation_loop` (every 15 min) auto-flips when Spearman gates pass (ρ ≥ 0.15, n ≥ 30, p < 0.05)

### Execution Order (UPDATED 2026-04-28)
- **D-39:** Phase 73 executes BEFORE Phase 75. Phase 73 reorganizes files/changes class names; Phase 75 builds governance on top of the new structure.
- **D-40:** Phase 75 needs minor adjustments after Phase 73: references to `signal_transform_log` become `signal_lineage`, file paths updated from `src/intelligence/swarm/agents/` to `src/intelligence/ai/alpha/`.

### LLM Chain Fixes — Verified Current (UPDATED 2026-04-28)
- **D-41:** All 6 LLM chain fixes verified against current `chain.py` (post-OllamaCloud addition, April 27). OllamaCloud only extended `_build_providers()` — no fix targets affected. Rate limiter now covers 3 provider types (OpenRouter, OllamaCloud, OllamaLocal).

### Extension Hooks in Base Classes (NEW 2026-04-28)
- **D-42:** `BaseAIAgent` includes `_on_error(error)` hook — future phase wires to OTel span + alert
- **D-43:** `BaseAIAgent` includes `_on_guardrail_violation(output)` hook — future phase wires to content filtering
- **D-44:** `BaseAIAgent` includes `_audit_payload: dict` property — future phase uses for data classification
- **D-45:** Timer context manager already in `compute()` wrapper (latency budget tracking)

### Architectural Decisions (Locked Post-Research)
- **D-46:** `LineageRecorder.record()` publishes to `topic_signal_lineage()` Kafka topic (DAG-correct). Hot path never writes to DB directly.
- **D-47:** `graduation_loop` is a background task (every 15 min) — direct `asyncpg` query to `signal_lineage` is acceptable (not on hot path).
- **D-48:** All agents MUST start and remain at `shadow_only=True`. Build graduation_loop fully but don't promote until gates pass with real data.
- **D-49:** New stream_keys.py functions: `topic_swarm_alpha()`, `topic_swarm_graduation()`, `topic_signal_lineage()`, `topic_signal_lineage_dlq()`
- **D-50:** `AgentResult` → `AgentOutput` migration is atomic — same plan updates aggregator, multiplier, and writer.
- **D-51:** Latency baseline: default 5000ms ceiling. Alpha agents target 3000ms, narrative 60000ms — tuned to 2× measured P95 after profiling.

### Claude's Discretion
- Order of migration steps within execution (can be sequenced for minimal service disruption)
- Whether to update CLAUDE.md service table with renamed services
- Systemd unit file name for renamed alpha swarm agent
- DB migration number for signal_lineage table
- Whether to keep `GraduationWriterAgent` as-is or absorb into `LineageWriterAgent`
- Exact schema of JSONB `metadata` field per event_type

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design Specification
- `docs/plans/2026-04-26-ai-llm-layer-design.md` — Full B+ architecture spec: interfaces, data flow, migration checklist, module structure, success criteria (primary source of truth)

### Existing Source to Modify
- `src/core/llm/chain.py` — LLM chain (6 fixes applied here; OllamaCloud provider added April 27 — verify fixes apply cleanly)
- `src/core/llm/semantic_cache.py` — cache key fix (prompt[:200] → full prompt)
- `src/core/llm/guardrails.py` — guardrails dead branch fix
- `src/core/llm/providers.py` — real token counts extraction
- `src/core/ml/shadow.py` — ShadowRecorder being deprecated (replaced by LineageRecorder)
- `src/core/ml/transform_recorder.py` — TransformRecorder being deprecated (replaced by LineageRecorder)
- `src/intelligence/swarm/` — agents and infrastructure being reorganized
- `src/intelligence/narrative/` — being moved to `src/intelligence/ai/narrative/`
- `services/swarm_dispatch_service.py` — being renamed to `alpha_swarm_agent.py`
- `services/swarm_orchestrator_agent.py` — being deleted
- `services/ai_narrative_agent.py` — being refactored to extend BaseGroupService
- `services/graduation_writer_agent.py` — may be absorbed into LineageWriterAgent

### Architecture Standards
- `CLAUDE.md` — naming conventions (agent role suffixes, systemd units, service map), systemd watchdog discipline rule (no WatchdogSec without sd_notify), import rules
- `src/core/stream_keys.py` — all stream/topic key construction (must use for any new topics)
- `src/intelligence/schemas.py` — canonical typed bus schemas (`IntelligenceEvent`)
- `src/config/settings.py` — Settings, get_active_contracts()

### Existing Patterns (read before implementing)
- `src/core/swarm/base_agent.py` — current swarm base being absorbed (understand what to preserve)
- `src/intelligence/swarm/context.py` — current SwarmContext being generalized to AIContext
- `src/intelligence/swarm/safety.py` — current SafeAgentWrapper being moved to `src/core/ai/`
- `src/intelligence/swarm/graduation.py` — graduation logic (kept, called by graduation_loop)
- `src/core/agent/base.py` — BaseAgent that BaseGroupService extends
- `src/core/agent/base_writer.py` — BaseWriterAgent pattern for LineageWriterAgent reference

### Phase Dependency Context
- `.planning/phases/75-shadow-governance-system-automated-promotion-demotion/75-CONTEXT.md` — Phase 75 depends on Phase 73 output; needs signal_lineage table and moved file paths

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `TransformRecorder` (Phase 72): batch flush pattern with asyncio.Task — reuse for LineageRecorder
- `ShadowRecorder` (Phase 56): same batch pattern, agent prediction capture — schema design reference for agent_prediction event_type
- `BaseWriterAgent` (Phase 68): consumer loop + offset commit + DLQ — LineageWriterAgent follows this pattern
- `BaseAgent` (Phase 52.6): lifecycle contract (setup/teardown, metrics_port, tracer, topics) — BaseGroupService extends this
- `GraduationComputeAgent` (Phase 72): timer pattern + graduation.evaluate_all() — keep for graduation_loop

### Established Patterns
- Batch writers: configurable batch_size (default 100) + flush_interval_s (default 2.0) + asyncio.Task
- Kafka-first hot path: compute agents publish, writer agents consume and persist (DAG discipline)
- Shadow mode: all new agents start shadow_only=True, graduation_loop auto-promotes
- Timer agents: systemd timer + service unit (e.g., ml-data-quality, signal-metrics-compute)
- Agent rename: git mv + class rename + systemd unit rename + CLAUDE.md update

### Integration Points
- `swarm_dispatch_service.py` currently dual-writes to ShadowRecorder + TransformRecorder — replace with single LineageRecorder
- `intelligence_pipeline_agent.py` wires TransformRecorder into 6 math transforms — update to LineageRecorder
- `graduation_loop` in BaseGroupService queries signal_transform_log — update to signal_lineage
- `swarm_writer_agent.py` consumes topic_swarm_results — verify compatibility with AgentOutput schema
- Phase 75's `ShadowAuditorAgent` will query `signal_lineage` (not signal_transform_log) after Phase 73 ships

</code_context>

<specifics>
## Specific Ideas

### Unified Lineage Schema Design
```sql
CREATE TABLE signal_lineage (
    ts            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    signal_id     UUID NOT NULL,
    event_type    TEXT NOT NULL CHECK (event_type IN ('transform', 'agent_prediction', 'lifecycle')),
    source        TEXT NOT NULL,       -- transform_id or agent_id
    dag_order     SMALLINT,
    multiplier    FLOAT,
    metadata      JSONB DEFAULT '{}',  -- event-specific data
    is_shadow     BOOLEAN DEFAULT TRUE,
    symbol        TEXT,
    tf            TEXT
);
SELECT create_hypertable('signal_lineage', 'ts');
```

### Extension Hook Signatures
```python
class BaseAIAgent(BaseAgent, ABC):
    async def _on_error(self, error: Exception) -> None: ...
    async def _on_guardrail_violation(self, output: AgentOutput) -> None: ...
    @property
    def _audit_payload(self) -> dict: return {}
```

### LLM Chain Fix Details
1. Cache key: `SHA-256(system + full_prompt + model)` — remove `[:200]` truncation
2. Rate limiter: `await limiter.acquire(tokens=max_tokens)` before provider dispatch (covers OpenRouter + OllamaCloud + OllamaLocal)
3. Guardrails: if no schema registered, skip `validate()` entirely
4. Auto-audit: `audit_context: dict | None = None` param; publish to `topic_llm_calls` when provided
5. Real token counts: `response_meta["usage"]["total_tokens"]` from OpenRouter; fallback `len(text) // 4` estimate
6. Watchdog: Remove from swarm-orchestrator unit (deleted by D-09)

</specifics>

<deferred>
## Deferred Ideas

- **AI Agent full observability** (OTel spans per agent, quality dashboards, cost tracking per model) — future phase; hooks wired in Phase 73
- **Advanced guardrails** (prompt injection detection, content filtering, jailbreak resistance) — future phase; hooks wired in Phase 73
- **Security & data protection** (input sanitization, access control, data classification) — future phase; hooks wired in Phase 73
- **Evaluation QA** (automated quality scoring of individual agent outputs) — future phase
- **Governance** (model versioning, rollback, policy enforcement) — Phase 75 covers shadow governance; broader AI governance is future work
- **Approach C (Independent AI Package):** Extract `src/ai/` from `src/core/ai/` + `src/intelligence/ai/` with `AILayerRouter` — deferred until agent count exceeds ~10
- **RiskSwarmComputeAgent:** Placeholder `src/intelligence/ai/risk/__init__.py` only; full implementation is future work
- **i2, i3, i5 tier contexts in AIContext:** Added as placeholder comment only; actual models added when first agent declares them

</deferred>

---

*Phase: 73-ai-llm-layer-b-architecture-refactor*
*Context gathered: 2026-04-26 via PRD Express Path; updated 2026-04-28 via discuss-phase*
