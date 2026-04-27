# Phase 73: AI LLM Layer B+ Architecture Refactor - Context

**Gathered:** 2026-04-26
**Status:** Ready for planning
**Source:** PRD Express Path (docs/plans/2026-04-26-ai-llm-layer-design.md)

<domain>
## Phase Boundary

This phase delivers the B+ Architecture Refactor of the AI/LLM layer. It:

1. Fixes 10 structural defects in the existing swarm/LLM layer
2. Creates a universal AI agent infrastructure (`src/core/ai/`) with shared base classes, context management, and safe wrapper
3. Reorganizes agents into mandate-based groups under `src/intelligence/ai/` (alpha, narrative, risk)
4. Applies 6 LLM chain fixes (cache key, rate limiter, guardrails, auto-audit, real token counts, watchdog violation)
5. Adds a narrative TF gate (5m+ only)
6. Deletes the dead `swarm_orchestrator_agent` service and its systemd unit
7. Renames `swarm_dispatch_service.py` → `alpha_swarm_agent.py` (and class `SwarmDispatchComputeAgent` → `AlphaSwarmComputeAgent`)
8. Enforces import boundary discipline: AI layer imports nothing from `src/intelligence/pipeline/` or tier plugins

Phase does NOT include Approach C (independent `src/ai/` package extraction) — that is future evolution.

</domain>

<decisions>
## Implementation Decisions

### Structural Defects to Fix (all locked)
- Fix D-01: Delete `services/swarm_orchestrator_agent.py` (zero agents, competing with active dispatch service)
- Fix D-02: Delete `/etc/systemd/system/indicagent-swarm-orchestrator.service`
- Fix D-03: Rename `swarm_dispatch_service.py` → `alpha_swarm_agent.py`; class `SwarmDispatchComputeAgent` → `AlphaSwarmComputeAgent`
- Fix D-04: LLM rate limiter — call `await limiter.acquire(tokens=max_tokens)` in `chain.py` before provider dispatch
- Fix D-05: Guardrails — remove dead branch; if no schema registered, skip `validate()` entirely
- Fix D-06: Auto-audit — add `audit_context: dict | None = None` param to LLMProviderChain; publish to `llm.calls` topic when provided
- Fix D-07: Real token counts — use `response_meta["usage"]["total_tokens"]` from OpenRouter when present
- Fix D-08: Cache key — `SHA-256(system + full_prompt + model)` — remove `[:200]` truncation in `semantic_cache.py`
- Fix D-09: Remove `WatchdogSec=60` + `NotifyAccess=main` from swarm-orchestrator systemd unit (already deleted by D-02, but any remaining unit files get cleaned)
- Fix D-10: Replace private `_context_cache._cache` access in `_find_lead_context` with public `AIContextCache.get_lead(symbol, tf)` method

### New Infrastructure: `src/core/ai/` (5 new files, all locked)
- `base_agent.py` — `BaseAIAgent` ABC + `IAIAgent` Protocol with exact interface from design doc
- `base_group_service.py` — `BaseGroupService` shared dispatcher (extends existing `BaseAgent`)
- `context.py` — `AIContext`, `AIContextCache`, `Tier` enum, `TierContext` models (frozen Pydantic)
- `output.py` — `AgentOutput` universal envelope (untyped `payload` dict by design)
- `safe_wrapper.py` — `SafeAgentWrapper` (timeout + exception isolation, replaces `src/intelligence/swarm/safety.py`)

### Module Reorganization (locked)
- MOVE `src/intelligence/swarm/agents/skeptic_agent.py` → `src/intelligence/ai/alpha/skeptic_agent.py`
- MOVE `src/intelligence/swarm/agents/correlation_agent.py` → `src/intelligence/ai/alpha/correlation_agent.py`
- MOVE `src/intelligence/swarm/agents/volume_agent.py` → `src/intelligence/ai/alpha/volume_agent.py`
- MOVE `src/intelligence/narrative/` → `src/intelligence/ai/narrative/` (narrative_agent.py, prompts.py, parsers.py)
- PLACEHOLDER `src/intelligence/ai/risk/__init__.py` — empty, marks future group
- KEEP `src/intelligence/swarm/aggregator.py` (used by AlphaSwarmComputeAgent)
- KEEP `src/intelligence/swarm/graduation.py` (called by graduation_loop)
- ABSORB `src/core/swarm/base_agent.py` → `src/core/ai/base_agent.py`
- ABSORB `src/intelligence/swarm/context.py` → `src/core/ai/context.py`

### Group Services (locked)
- `AlphaSwarmComputeAgent` (in `services/alpha_swarm_agent.py`) extends `BaseGroupService`: group_id="alpha", has_graduation=True, aggregate_topic=topic_swarm_alpha, trigger_topics=[topic_intelligence_i7_signals], agents=[SkepticAgentComputeAgent, CorrelationAgentComputeAgent, VolumeAgentComputeAgent]
- `NarrativeGroupComputeAgent` (in `services/ai_narrative_agent.py`) extends `BaseGroupService`: group_id="narrative", has_graduation=False, aggregate_topic=None, trigger_topics=[topic_intelligence_journal], agents=[NarrativeComputeAgent]
- All existing swarm/narrative agents extend `BaseAIAgent` instead of `SwarmBaseAgent`

### Narrative TF Gate (locked)
- `NarrativeComputeAgent._compute()` rejects timeframes not in `{"5m", "15m", "1h", "4h", "1d"}` before any LLM call
- Returns neutral AgentOutput when TF not in allowed set

### Import Boundary Discipline (locked)
- `src/core/ai/` and `src/intelligence/ai/` import only from `src/intelligence/schemas.py` and `src/core/stream_keys.py`
- Never import from `src/intelligence/pipeline/` or any tier plugin implementation

### Shadow Mode Default (locked)
- All agents have `shadow_only=True` by default
- `graduation_loop` (every 15 min) auto-flips when Spearman gates pass (ρ ≥ 0.15, n ≥ 30, p < 0.05)

### Architectural Decisions (Locked Post-Research)

**ShadowRecorder persistence: Kafka-first (DAG-correct)**
- `ShadowRecorder.record(AgentOutput)` publishes to `intelligence.shadow_recordings` Kafka topic
- Existing `swarm_writer_agent` (or renamed `shadow_writer_agent`) consumes and persists to `signal_transform_log`
- Hot path (dispatch loop) NEVER writes to DB directly — this is a hard constraint from Renaissance DAG principles
- `stream_keys.py` needs `topic_shadow_recordings()` function

**graduation_loop DB access: pragmatic direct read (acceptable)**
- `graduation_loop` is a background task running every 15 minutes — NOT on the bar dispatch hot path
- Direct `asyncpg` query to `signal_transform_log` inside `BaseGroupService._graduation_loop()` is acceptable
- This is a deliberate exception to the DAG rule, consistent with how graduation was always conceived

**Shadow promotion: build the full mechanism, no prod flips yet**
- All agents MUST start and remain at `shadow_only=True`
- Build `graduation_loop`, `evaluate_all()`, signal_transform_log recording fully and correctly
- The loop will run, evaluate, log findings — but won't promote until Spearman gates pass with real data
- Zero code change needed when prod data accumulates: system self-activates automatically
- This is the Renaissance approach: instrument everything, let the system run

**`ShadowRecorder` Kafka topic naming:** `intelligence.shadow_recordings` (dots only, via `topic_shadow_recordings()` in `stream_keys.py`)

**New stream_keys.py functions needed (from research):**
- `topic_swarm_alpha()` — AlphaSwarmComputeAgent aggregate topic (AlphaMultiplier output)
- `topic_swarm_graduation()` — graduation flip events published by graduation_loop
- `topic_shadow_recordings()` — ShadowRecorder publishes here; writer consumes

**AgentResult → AgentOutput migration is atomic:**
- `SwarmAggregator.aggregate()` must be updated in the same plan as the schema migration
- `AlphaMultiplier.contributors` type changes from `dict[str, AgentResult]` → `dict[str, AgentOutput]`
- `swarm_writer_agent.py` updated in the same wave — zero intermediate broken state

**Latency baseline first:**
- Before hardcoding `latency_budget_ms`, a profiling task must measure actual gemma4:e4b latency on target hardware
- Default 5000ms is a safe starting ceiling; tuned to 2× measured P95 after profiling
- Alpha agents target 3000ms, narrative 60000ms — these are confirmed after measurement

### Claude's Discretion
- Order of migration steps within execution (can be sequenced for minimal service disruption)
- Whether to update CLAUDE.md service table with renamed services
- Systemd unit file name for renamed alpha swarm agent
- Whether to update `swarm_writer_agent.py` in-place or rename to `shadow_writer_agent.py`

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design Specification
- `docs/plans/2026-04-26-ai-llm-layer-design.md` — Full B+ architecture spec: interfaces, data flow, migration checklist, module structure, success criteria (primary source of truth)

### Existing Source to Modify
- `src/core/llm/chain.py` — LLM chain (6 fixes applied here)
- `src/core/llm/semantic_cache.py` — cache key fix
- `src/intelligence/swarm/` — agents and infrastructure being reorganized
- `src/intelligence/narrative/` — being moved to `src/intelligence/ai/narrative/`
- `services/swarm_dispatch_service.py` — being renamed to `alpha_swarm_agent.py`
- `services/swarm_orchestrator_agent.py` — being deleted
- `services/ai_narrative_agent.py` — being refactored to extend BaseGroupService

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

</canonical_refs>

<specifics>
## Specific Ideas

### Exact Class/Interface Definitions (from design doc)
- `Tier` enum: BAR, I1, I2, I3, I4, I5, I6, I7 (str Enum)
- `IAIAgent` Protocol: agent_id, group, tiers_needed (frozenset[Tier]), shadow_only, latency_budget_ms, async compute(AIContext) -> AgentOutput
- `BaseAIAgent.compute()` is a concrete wrapper (timing + error capture); `_compute()` is the abstract method agents implement
- `AIContext` is a frozen Pydantic model with universal fields + optional tier contexts
- `AgentOutput.payload` is untyped dict by design (alpha aggregator reads payload["multiplier"], narrative reads payload["text"])
- `BaseGroupService` has abstract properties: agents, trigger_topics, output_topic; concrete: _setup, _run, _handle_trigger, _graduation_loop, _teardown

### LLM Chain Fix Details
1. Cache key: `SHA-256(system + full_prompt + model)` — remove `[:200]` truncation
2. Rate limiter: `await limiter.acquire(tokens=max_tokens)` before provider dispatch
3. Guardrails: if no schema registered, skip `validate()` entirely (remove dead branch)
4. Auto-audit: `audit_context: dict | None = None` param; publish to `topic_llm_calls` when provided
5. Real token counts: use `response_meta["usage"]["total_tokens"]` from OpenRouter when present
6. Watchdog: Remove `WatchdogSec=60` + `NotifyAccess=main` from swarm-orchestrator unit

### Data Flow (from design doc)
- Bar arrives → bar_loop → AIContextCache.update(IntelligenceEvent)
- Trigger event → BaseGroupService._handle_trigger → build AIContext per agent → asyncio.gather → AgentOutput × N → publish per-agent + aggregate
- LLM call inside _compute → rate_limiter.acquire → semantic_cache.get → budget check → provider → guardrails → budget.record → semantic_cache.put → auto-audit publish
- Background graduation_loop (15 min): query signal_transform_log → graduation.evaluate_all → auto-flip shadow_only

</specifics>

<deferred>
## Deferred Ideas

- **Approach C (Independent AI Package):** Extract `src/ai/` from `src/core/ai/` + `src/intelligence/ai/` with `AILayerRouter` — deferred until qualitative intelligence stack arrives and agent stable exceeds ~10 agents
- **i2, i3, i5 tier contexts in AIContext:** Added as placeholder comment only; actual models added when first agent declares them
- **RiskSwarmComputeAgent:** Placeholder `src/intelligence/ai/risk/__init__.py` only; full implementation is future work
- **Qualitative intelligence group:** Future group, not in scope

</deferred>

---

*Phase: 73-ai-llm-layer-b-architecture-refactor*
*Context gathered: 2026-04-26 via PRD Express Path*
