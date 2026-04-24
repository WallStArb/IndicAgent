# Phase 71: BaseAgent Infrastructure Alignment - Context

**Gathered:** 2026-04-14
**Status:** Ready for planning
**Source:** PRD Express Path (docs/superpowers/specs/2026-04-14-base-agent-infrastructure-alignment-design.md)

<domain>
## Phase Boundary

6 targeted changes to eliminate boilerplate, fix bugs, and close observability gaps across the agent base class hierarchy. No new features, no new agents — purely refactoring the existing 4-class base hierarchy (BaseAgent, BaseProviderAgent, BaseWriterAgent, SwarmBaseAgent) so that adding a new agent requires zero tribal knowledge.

</domain>

<decisions>
## Implementation Decisions

### Change 1: Settings Singleton in BaseAgent
- BaseAgent.__init__() sets `self.settings = get_settings()` using existing singleton in `src/config/settings.py`
- Rename all `self._settings` references in agents to `self.settings`
- BaseProviderAgent passes `settings=get_settings()` to super().__init__; BaseAgent skips re-creation when settings kwarg is provided
- BaseWriterAgent and SwarmBaseAgent inherit self.settings automatically
- Files: `src/core/agent/base.py`, all 15 agent files in `services/`
- Risk: Low — `get_settings()` already returns a cached singleton

### Change 2: Auto init_tracing() in BaseAgent
- BaseAgent.start() calls `init_tracing(self.name)` before `_setup()`, guarded by module-level flag for idempotency
- Add `_tracing_initialized: bool = False` module-level flag in `base.py`
- Remove `init_tracing()` calls from `__main__` blocks in all agents
- Files: `src/core/agent/base.py`, 6-8 agent `__main__` blocks
- Risk: Low — `init_tracing()` is already idempotent

### Change 3: Default _report_consumer_lag() in BaseAgent
- BaseAgent provides working default `_report_consumer_lag()` that emits `PERSISTENCE_CONSUMER_LAG` with agent name
- BaseWriterAgent overrides to report buffer depth instead
- Cache `PERSISTENCE_CONSUMER_LAG.labels(agent_id=self.name)` at __init__ time
- Remove all 15 manual overrides
- Files: `src/core/agent/base.py`, `src/core/agent/base_writer.py`, 15 agent files
- Risk: Medium — lag reporting is observability-critical

### Change 4: Remove Vestigial setup_service_logging() Calls
- Remove manual `setup_service_logging()` calls from `__main__` blocks where BaseAgent already handles it
- Keep `setup_service_logging()` in LLMWriterService until it's migrated (Change 5)
- Files: 6-8 agent `__main__` blocks
- Risk: None — "first call wins" means removing the second call has zero effect

### Change 5: Migrate LLMWriterService to BaseWriterAgent
- Create `LLMWriterAgent(BaseWriterAgent)` class
- Implement `_topic_name()` → return primary topic (llm.calls)
- Implement `_consumer_group` → "llm_writer"
- Implement `_parse_payload()` → parse LLM call/outcome messages
- Implement `_flush_batch()` → batch INSERT to llm_calls / UPDATE outcomes
- Move score recomputation (15-min interval) to background task in `_run()`
- Wire `_dlq_topic()` → `topic_llm_writer_dlq()`
- Files: `services/llm_writer_service.py`, possibly systemd service file
- Risk: Medium — dual consumers + timer pattern more complex than typical writer

### Change 6: Remove Duplicate Lag Task Creation
- Remove manual `lag_task = asyncio.create_task(self._report_consumer_lag())` from 11 agents
- BaseAgent.start() already creates this task at line 155
- Files: 11 agent files (roll_compute_agent, signal_metrics_compute_agent, signal_metrics_writer_agent, service_auditor_agent, contract_metadata_writer_agent, bar_aggregator_agent, cross_asset_service, swarm_orchestrator_agent, ai_narrative_agent, signal_auditor_agent, parity_auditor_agent)
- Risk: Low — BaseAgent.start() task already calls overridden `_report_consumer_lag()`

### Execution Order
1. Changes 1 + 2 together (foundational, no dependencies)
2. Change 4 (depends on Changes 1+2)
3. Changes 3 + 6 together (3 depends on 6 to avoid conflicts)
4. Change 5 (depends on Changes 1-3 for full benefit)

### What We're NOT Doing
- No mixin decomposition — 4 base classes is enough
- No Protocol/ABC explosion
- No dependency injection framework
- No changes to SwarmBaseAgent
- No changes to BaseProviderAgent's adapter pattern (only Settings kwargs passthrough)

### Claude's Discretion
- Exact wave/plan grouping of tasks
- Test coverage details
- Migration strategy for LLMWriterService dual-consumer pattern

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Base Agent Hierarchy
- `src/core/agent/base.py` — BaseAgent with lifecycle contract, metrics, logging, start/stop
- `src/core/agent/base_writer.py` — BaseWriterAgent with buffer/flush/offset-commit/DLQ machinery
- `src/core/agent/base_provider.py` — BaseProviderAgent with adapter pattern
- `src/core/agent/swarm_base.py` — SwarmBaseAgent (Phase 56, not to be modified)

### Key Infrastructure
- `src/config/settings.py` — `get_settings()` singleton, `Settings` class
- `src/core/service_utils.py` — `setup_service_logging()`, `init_tracing()`
- `src/observability/metrics.py` — `PERSISTENCE_CONSUMER_LAG` and all Prometheus metrics
- `src/core/stream_keys.py` — All Kafka topic key construction

### Design Doc (PRD)
- `docs/superpowers/specs/2026-04-14-base-agent-infrastructure-alignment-design.md` — Full design with rationale, risk assessment, and execution order

</canonical_refs>

<specifics>
## Specific Ideas

- Settings singleton: `get_settings()` from `src/config/settings.py` already returns cached singleton via `@lru_cache(maxsize=1)` — no behavioral change
- Tracing: `init_tracing()` in `src/core/service_utils.py` creates OTel tracer provider — second call is a no-op
- Lag metric label key is `agent_id` (not `agent=`) — per `src/observability/metrics.py` label names
- 11 agents with duplicate lag tasks explicitly identified in design doc
- LLMWriterService dual-consumer pattern: calls + outcomes on different topics, plus 15-min score recomputation timer
- `setup_service_logging()` "first call wins" idempotency confirmed by WR-05 fix (Phase 067)

</specifics>

<deferred>
## Deferred Ideas

None — design doc covers phase scope completely.

</deferred>

---

*Phase: 071-base-agent-infrastructure-alignment*
*Context gathered: 2026-04-14 via PRD Express Path*
