# Phase 111: Full Naming Alignment - Context

**Gathered:** 2026-05-30
**Status:** Ready for planning
**Source:** Design doc `docs/plans/2026-05-30-phase-111-naming-alignment.md`

<domain>
## Phase Boundary

Phase 110 renamed class identifiers and file names. Phase 111 fixes all runtime surfaces that Phase 110 could not safely touch in one pass, plus enforces the Ring 0 boundary structurally.

Scope:
- `BaseDaemon` auto-derive for `agent_id` (eliminate 18 stale `name=` overrides)
- `setup_service_logging()` path auto-derive (eliminate 15 stale path overrides)
- 5 missing Phase 110 class+file renames + TEMPLATE rename
- Structlog event string prefix alignment across 20 files (~100 strings)
- Ring 0 boundary pre-commit enforcement
- 29 test file renames + 9 test class renames
- Grafana/alertmanager label value updates
- `ctx` → `audit_context`/`context` local variable cleanup (2 locations)
- CLAUDE.md log naming rule correction

</domain>

<decisions>
## Implementation Decisions

### D-01: BaseDaemon Auto-Derive
`BaseDaemon.__init__` accepts `name: str | None = None`. When `None`, derives `agent_id = _to_snake_case(self.__class__.__name__)`. A `_to_snake_case()` utility handles `MLDiscoveryAnalyzer` → `ml_discovery_analyzer`. All 18 `name=` overrides removed from services.

### D-02: Log Path Auto-Derive
`setup_service_logging()` path overrides in all 15 services are deleted. `BaseDaemon`'s existing auto-derive (`logs/{snake_case_name}.log`) takes over. No new code needed in services.

### D-03: _AGENT_NAME Constants Deleted
Both `_AGENT_NAME` module constants deleted (redundant post-auto-derive). The hardcoded `"feature_writer_agent"` metric label string in `feature_writer.py` fixed to use the derived name. 11 stale `_AGENT_ID_TO_UNIT` dict keys in `service_auditor.py` updated to new class-derived names.

### D-04: Missing Phase 110 Renames
| Old class | New class | Old file | New file |
|---|---|---|---|
| `DLQDrainAgent` | `DLQDrain` | `services/dlq_drain_agent.py` | `services/dlq_drain.py` |
| `MLSignalTrainingMaterializeAgent` | `MLSignalTrainingMaterializer` | `src/intelligence/services/ml_signal_training_materialize_agent.py` | `src/intelligence/services/ml_signal_training_materializer.py` |
| *(no class)* | n/a | `services/shadow_auditor_agent.py` | `services/shadow_auditor.py` |
| *(no class)* | n/a | `services/self_healing_agent.py` | `services/self_healer.py` |
| *(no class)* | n/a | `services/config_service_agent.py` | `services/config_service.py` |
| `TemplateComputeAgent` | `TemplateEvaluator` | `src/intelligence/ai/TEMPLATE_agent.py` | `src/intelligence/ai/TEMPLATE.py` |
Systemd ExecStart paths updated for all renamed files.

### D-05: Structlog Event String Convention
Convention: `"derived_agent_id.action"`. Sed pass per file, exact prefix match. 20 files affected:

| File | Old prefix | New prefix |
|---|---|---|
| `services/bar_aggregator.py` | `bar_aggregator_agent.` | `bar_aggregator.` |
| `services/bar_auditor.py` | `bar_auditor_agent.` | `bar_auditor.` |
| `services/bar_writer.py` | `bar_writer_agent.` | `bar_writer.` |
| `services/macro_analyzer.py` | `macro_compute_agent.` | `macro_analyzer.` |
| `services/narrative_swarm.py` | `narrative_group_compute_agent.` | `narrative_swarm.` |
| `services/feature_writer.py` | `feature_writer_agent.` | `feature_writer.` |
| `services/signal_writer.py` | `signal_writer_agent.` | `signal_writer.` |
| `services/signal_tracker.py` | various | `signal_tracker.` |
| `services/context_writer.py` | `ctx_writer_agent.` | `context_writer.` |
| `services/lineage_writer.py` | `lineage_writer_agent.` | `lineage_writer.` |
| `services/swarm_ledger_writer.py` | `swarm_ledger_writer_agent.` | `swarm_ledger_writer.` |
| `services/graduation_writer.py` | `graduation_writer_agent.` | `graduation_writer.` |
| `services/signal_auditor.py` | `signal_auditor_agent.` | `signal_auditor.` |
| `services/alert_monitor.py` | `alerting_agent.` | `alert_monitor.` |
| `services/data_quality_auditor.py` | `ml_data_quality_agent.` | `data_quality_auditor.` |
| `services/ml_discovery_analyzer.py` | `ml_discovery_agent.` | `ml_discovery_analyzer.` |
| `services/ml_orchestrator.py` | `ml_orchestrator_agent.` | `ml_orchestrator.` |
| `src/core/ai/base_agent.py` | `ai_agent.` | `ai_worker.` |
| `src/core/agent/base.py` | any `agent.` prefixes | `daemon.` |

(Files `graduation_compute.py`, `signal_metrics_compute.py` also likely have stale prefixes — verify during implementation.)

### D-06: Ring 0 Pre-Commit Hook
Add grep-based hook to `.git/hooks/pre-commit`:
```bash
# Ring 0 boundary check: src/core/ and src/observability/ must not import domain layers
RING0_VIOLATIONS=$(grep -rn \
  "from src\.intelligence\|from src\.config\|from src\.providers\|from src\.self_healing\|from services" \
  src/core/ src/observability/ --include="*.py" 2>/dev/null | grep -v "^\s*#" || true)
if [ -n "$RING0_VIOLATIONS" ]; then
  echo "FAILED: Ring 0 boundary violation"
  echo "$RING0_VIOLATIONS"
  exit 1
fi
```

### D-07: Local Variable Cleanup
Two `ctx` usages replaced:
1. `src/core/ai/base_agent.py:192` — `ctx: dict[str, Any] = {}` → `audit_context: dict[str, Any] = {}`
2. `src/intelligence/ai/alpha/*_prompts.py` — `ctx` SignalContext param in 4 prompt builder functions → `context`

### D-08: Test File + Class Renames
29 test files renamed (drop `_agent` suffix or align to new class names). 9 test class names inside those files updated (e.g. `TestBarAuditorAgentInit` → `TestBarAuditorInit`). Imports updated throughout.

### D-09: Grafana + Alertmanager Updates
4 Grafana dashboard JSON files updated: old `agent_id` label values replaced with new derived values. `alertmanager-rules.yml` updated similarly.

### D-10: CLAUDE.md Log Naming Rule
CLAUDE.md currently states `logs/<agent_snake_case>_agent.log`. Post-Phase-110 and this phase, the `_agent` suffix is gone. Correct to `logs/<snake_case_class_name>.log`.

### D-11: Wave Sequence
Sequential waves (each blocked on prior):
- Wave 1: BaseDaemon auto-derive infrastructure + Grafana + alertmanager
- Wave 2: Missing service renames + TEMPLATE + test renames
- Wave 3: Structlog event string prefix replacements
- Wave 4: Ring 0 pre-commit + ctx cleanup + CLAUDE.md

### Claude's Discretion
- Exact `_to_snake_case` regex — use design doc's implementation (`re.sub` two-pass)
- Whether to keep `name=` override support as a keyword arg (yes — rare legitimate uses like multi-instance DLQ drain)
- Whether Wave 2 test renames are done by `git mv` or by write (use `git mv` to preserve history)
- Verification grep patterns can be refined during implementation

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Naming System
- `docs/foundation/naming-system.md` — full Ring/taxonomy naming spec (source of truth for all naming decisions)
- `CLAUDE.md` — Ring rule, log naming rule (to be updated in Wave 4)

### Architecture
- `src/core/agent/base.py` — `BaseDaemon` implementation (central to Wave 1)
- `src/core/service_utils.py` — `setup_service_logging()` signature
- `services/service_auditor.py` — `_AGENT_ID_TO_UNIT` dict (Wave 1 update target)

### Phase 110 Output
- `.planning/phases/110-renaissance-rename/` — what Wave 4 shipped (avoid re-doing completed work)

### Design Doc
- `docs/plans/2026-05-30-phase-111-naming-alignment.md` — full surface inventory with counts and file-level detail

</canonical_refs>

<specifics>
## Specific Ideas

### Complete Surface Inventory (from design doc)
| Surface | Count | Issue |
|---|---|---|
| `name=` constructor args | 18 | Stale old-class strings, feed Prometheus agent_id |
| `setup_service_logging()` overrides | 15 | Bypass BaseDaemon auto-derive; stale paths |
| `_AGENT_NAME` module constants | 2 | One stale, both redundant |
| Hardcoded metric label string | 1 | `"feature_writer_agent"` in feature_writer.py |
| `_AGENT_ID_TO_UNIT` dict keys | 11 | Use old class-name strings |
| Grafana dashboard JSON | 4 files | Hardcode old agent_id label values |
| `alertmanager-rules.yml` | 1 file | References old label values |
| Structlog event strings | ~100 in 20 files | Embed old service names |
| Missing Phase 110 renames | 6 | DLQDrain, MLSignalTrainingMaterializer, shadow_auditor, self_healer, config_service, TEMPLATE |
| Test file names | 29 | Still use old `_agent` convention |
| Test class names | 9 | Old patterns |
| `ctx` local var (non-OTel) | 2 | audit_context in base_agent.py, context in prompt files |
| Ring 0 boundary enforcement | missing | Rule exists in docs, absent from pre-commit |
| CLAUDE.md log naming rule | 1 | States `_agent.log` suffix — outdated |

### Acceptance Criteria (from design doc)
- `find src services tests -name '*.py' | xargs grep -lw "bar_aggregator_agent\|bar_writer_agent\|feature_writer_agent\|lineage_writer_agent\|SignalTrackerComputeAgent\|GraduationComputeAgent\|MLDiscoveryComputeAgent\|alerting_agent\|outbox_dispatcher_agent\|provider_merger_agent"` returns zero results
- `pytest tests/unit/ -q` — 4049+ passed, 0 failures
- `ruff check .` — clean
- Ring 0 boundary check fires on deliberate violation
- All structlog event strings in services match `{derived_agent_id}.{action}` pattern

</specifics>

<deferred>
## Deferred Ideas

### Explicitly Out of Scope (design doc §2)
- `tf`, `ts`, `sym`, `dt`, `pnl_r`, `mae`, `mfe` — domain-standard quant codes, kept everywhere
- `except Exception as exc` — standard Python idiom
- `msg` in Kafka consumer loops — standard async messaging idiom
- `resp` in aiohttp `async with session.get() as resp:` — standard idiom
- DB column names — stable by convention
- Migration SQL comments — immutable historical record
- `CircuitState` enum duplication — Phase 112 candidate

</deferred>

---

*Phase: 111-naming-alignment*
*Context gathered: 2026-05-30 from design doc*
