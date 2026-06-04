# Phase 110: Renaissance Rename — Context

**Gathered:** 2026-05-30
**Status:** Ready for planning
**Source:** Design spec `docs/plans/2026-05-30-renaissance-naming-system-design.md` (Sections 9 + 11)

<domain>
## Phase Boundary

Rename the entire codebase vocabulary to match the Ring/taxonomy naming system established in `docs/foundation/naming-system.md`. This is a clean-break rename executed in one atomic branch — no compatibility aliases, no systemd stubs. All callers updated in the same branch.

**Scope includes:**
- Ring 0: 7 infrastructure base class renames (e.g. `BaseAgent` → `BaseDaemon`)
- Ring 1: 9 AI evaluation layer renames (e.g. `SkepticComputeAgent` → `SkepticEvaluator`) + 2 context carriers
- Ring 2: 33 daemon process renames (e.g. `BarAggregatorComputeAgent` → `BarAggregator`) + file names
- Wave 4: systemd unit file renames, API imports, dashboard display strings, Tier 3 abbreviation fixes

**Scope excludes:**
- `agent_id` metric labels and structlog fields — operational exception (Section 2 of naming spec)
- `i1`–`i8` tier codes, `smc` topic keys — domain abbreviations retained by exception
- DB column names, Kafka topic strings — not subject to class rename
- Phase 095 infrastructure (`AgentContext`, `BaseAIWorker`) is renamed here; Phase 095 writes new evaluators using correct names

</domain>

<decisions>
## Implementation Decisions

### Execution approach
- **Atomic branch**: all 4 waves in a single branch `rename/phase-110`. No intermediate merges.
- **Clean break**: no compatibility aliases, no `_agent` stubs, no `__all__` re-exports. Not a production system.
- **All callers updated in the same branch**: the CI suite is the contract — if it passes, the rename is complete.

### Wave structure (sequential)
- **Wave 1 — Ring 0 base classes (7 renames)**: `BaseAgent`→`BaseDaemon`, `BaseWriterAgent`→`BaseWriter`, `BaseProviderAgent`→`BaseProvider`, `BaseAIAgent`→`BaseAIWorker`, `BaseGroupService`→`BaseSwarmCoordinator`, `AgentContext`→`WorkerContext`, `AgentProtocol`→`AIWorkerProtocol`
- **Wave 2 — Ring 1 AI evaluation (9 class renames + 2 context carriers)**: `BaseMultiplierAgent`→`Evaluator` (abstract, Ring 0), `SkepticComputeAgent`→`SkepticEvaluator`, `CorrelationComputeAgent`→`CorrelationAnalyzer`, `CounterfactualComputeAgent`→`CounterfactualEvaluator`, `RegimeCoherenceComputeAgent`→`RegimeCoherenceAnalyzer`, `MLScorerMultiplierAgent`→`MLEvaluator`, `NarrativeComputeAgent`→`NarrativeSynthesizer`, `AIContext`→`SignalContext`, `AIContextCache`→`SignalContextCache`
- **Wave 3 — Ring 2 daemon processes (33 renames)**: all `*ComputeAgent` → role noun + category suffix; `*WriterAgent` → `*Writer`; `*AuditorAgent` → `*Auditor`; `*ProviderAgent` → `*Provider`. Full table in naming spec Section 9.
- **Wave 4 — File names, systemd, imports, Ring 3**: file names follow class rename (retire `_agent` suffix from Ring 2 files); systemd unit names unchanged (already role-noun); API import updates; dashboard display string updates; Tier 3 abbreviation fixes (`bar_ctx`→`bar_context`, `i7_ctx`→`i7_context`, `resp`→`response`)

### File naming rule
`bar_aggregator_agent.py` → `bar_aggregator.py`. The `_agent` suffix is retired from Ring 2 file names. Class name derives file name mechanically.

### CLAUDE.md update
CLAUDE.md "Pending renames" section lists old names because Phase 110 hasn't shipped yet. Wave 4 includes updating CLAUDE.md to remove the pending renames table and update all name references to the new names.

### CI gate
Every wave must pass: `pytest tests/unit/ -q` + `ruff check .` + `mypy src/ --ignore-missing-imports` before Wave N+1 begins. This prevents compound breakage.

### Operational exception
`agent_id` metric label key and structlog field are preserved as-is (existing Grafana dashboards, Prometheus alert rules, OTel pipelines). All new metric labels introduced after Phase 110 use role-specific identifiers.

### Claude's Discretion
- How to split the 33 Ring 2 renames across plan files (by category: Writers, Auditors, Analyzers, etc. or by wave)
- Whether Wave 3 needs one plan or multiple plans based on file dependency graph
- Exact ordering within Wave 3 (reverse dependency order to avoid import errors)
- Test strategy (run pytest after each sub-wave or only at wave boundaries)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Naming System (source of truth)
- `docs/foundation/naming-system.md` — full naming spec; Section 9 = complete rename table; Section 11 = migration guidelines; Section 8 = CI verification checks

### Rename Design
- `docs/plans/2026-05-30-renaissance-naming-system-design.md` — Section 9 (pending renames, all 4 rings), Section 11 (migration guidelines, wave structure, clean break rationale)

### Key implementation files (Ring 0 — read before Wave 1)
- `src/core/agent/base.py` — `BaseAgent` definition (rename to `BaseDaemon`)
- `src/core/agent/base_writer.py` — `BaseWriterAgent` (rename to `BaseWriter`)
- `src/core/agent/base_provider.py` — `BaseProviderAgent` (rename to `BaseProvider`)
- `src/core/ai/base_ai_agent.py` — `BaseAIAgent` (rename to `BaseAIWorker`)
- `src/core/ai/base_group_service.py` — `BaseGroupService` (rename to `BaseSwarmCoordinator`)
- `src/core/ai/agent_context.py` — `AgentContext` (rename to `WorkerContext`)
- `src/core/ai/agent_protocol.py` — `AgentProtocol` (rename to `AIWorkerProtocol`)

### Dashboard (Ring 3 — Wave 4)
- `dashboard/src/hooks/use-observability-stream.ts` — display string updates (4 strings + 1 key reference)

### API (Ring 3 — Wave 4)
- `src/api/routes/narrative.py` — import `NarrativeSynthesizer`; fix `bar_ctx`→`bar_context`, `i7_ctx`→`i7_context`
- `src/api/routes/health.py` — fix `resp`→`response`

</canonical_refs>

<specifics>
## Specific Ideas

- Run `grep -rn "class BaseAgent"` after Wave 1 to confirm zero results before proceeding to Wave 2.
- Wave 3 has ~33 renames — consider batching by category (Writers in one plan, Auditors+Analyzers in another) to keep plans manageable. Each plan should end with a passing CI gate.
- The `Evaluator` abstract class moves from Ring 1 to Ring 0 (`src/core/ai/evaluator.py`) — this is a file move, not just a rename. The planner must account for this.
- `BaseMultiplierAgent` → `Evaluator` is both a rename AND a ring boundary move (Ring 1 `src/intelligence/ai/` → Ring 0 `src/core/ai/`). Wave 2 plan must handle the file move.

</specifics>

<deferred>
## Deferred Ideas

- `BaseAIWorker` is an interim name — full architectural separation of evaluator class hierarchy from daemon hierarchy is Phase 2 work (post-Phase 095). Not in scope for Phase 110.
- New metric label conventions (`daemon_id`, `service_id`) are not backfilled on existing metrics — only new metrics introduced after Phase 110 use the new labels.

</deferred>

---

*Phase: 110-renaissance-rename*
*Context gathered: 2026-05-30 from design spec Section 9 + 11*
