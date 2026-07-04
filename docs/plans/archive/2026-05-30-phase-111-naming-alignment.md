# Phase 111 — Full Naming Alignment

**Date:** 2026-05-30
**Status:** Design approved, ready for planning
**Follows:** Phase 110 (Renaissance rename — class identifiers + file names)

---

## Problem

Phase 110 renamed class identifiers and file names to role-noun conventions. It did not touch:

- `name=` constructor args that feed Prometheus `agent_id` labels (18 stale strings)
- `setup_service_logging()` path overrides that bypass `BaseDaemon`'s auto-derive (15 stale strings)
- Structlog event strings embedding old service names (~100 across 20 files)
- Grafana dashboards and alertmanager rules referencing old label values
- 5 services that were out of Phase 110 scope (added in Phase 109)
- 29 test file names + 9 test class names inside those files
- Ring 0 architectural boundary — documented but not enforced in pre-commit

**The root cause in every case is the same:** correctness enforced by discipline rather than structure. The architecture is mostly right; services are defeating it, and nothing catches the violation.

---

## Design Principles

A senior quant at Renaissance would demand:

1. **Encode the invariant once.** Don't patch 18 stale strings — fix the base class so drift is structurally impossible. Future subclasses require zero boilerplate to get the correct label.
2. **Observability must be trustworthy.** Grafana panels, log event strings, and Prometheus labels that disagree with class names are not a cosmetic problem — they erode operator trust in the monitoring layer.
3. **Enforcement over documentation.** Architectural rules that live only in CLAUDE.md will be violated. Put them in the pre-commit gate.
4. **Standard abbreviations are precision, not laziness.** `tf`, `ts`, `sym`, `dt`, `pnl_r`, `mae`, `mfe` are domain-standard quant codes — unambiguous, space-efficient, kept everywhere. `ctx`, `resp` as generic local variable names are noise — replaced where they lack domain specificity.

---

## Complete Surface Inventory

| Surface | Count | Issue |
|---|---|---|
| `name=` constructor args | 18 | Stale old-class strings, feed Prometheus agent_id |
| `setup_service_logging()` overrides | 15 | Bypass BaseDaemon auto-derive; stale paths |
| `_AGENT_NAME` module constants | 2 | One stale (`signal_metrics_compute`), both redundant |
| Hardcoded metric label string | 1 | `"feature_writer_agent"` in feature_writer.py |
| `_AGENT_ID_TO_UNIT` dict keys | 11 | Use old class-name strings |
| Grafana dashboard JSON | 4 files | Hardcode old agent_id label values |
| `alertmanager-rules.yml` | 1 file | References old label values |
| Structlog event strings | ~100 in 20 files | Embed old service names (e.g. `"bar_aggregator_agent.htf_bar_published"`) |
| Missing Phase 110 renames | 6 | DLQDrain, MLSignalTrainingMaterializer, shadow_auditor, self_healer, config_service, TEMPLATE |
| Test file names | 29 | Still use old `_agent` convention |
| Test class names (inside files) | 9 | Old patterns (e.g. `TestBarAuditorAgentInit`) |
| `ctx` local var (non-OTel) | 2 | `audit_context` in base_agent.py, `context` in prompt files |
| Ring 0 boundary enforcement | missing | Rule exists in docs, absent from pre-commit |
| CLAUDE.md log naming rule | 1 | States `_agent.log` suffix — outdated post-Phase 110 |

**Explicitly out of scope:**
- `tf`, `ts`, `sym`, `dt` — domain-standard quant codes, kept everywhere including function params
- `except Exception as exc` — standard Python exception idiom, kept
- `msg` in Kafka consumer loops — standard async messaging idiom, kept
- `resp` in aiohttp `async with session.get() as resp:` — standard aiohttp idiom, kept
- DB column names (`ts`, `tf`, `pnl_r`, etc.) — stable by convention
- Migration SQL comments — historical record, immutable
- `CircuitState` enum duplication — real smell but separate concern (Phase 112 candidate)

---

## Architecture: BaseDaemon Auto-Derive

The core fix lives entirely in `src/core/agent/base.py`.

**Add `_to_snake_case()` utility:**
```python
def _to_snake_case(name: str) -> str:
    """BarAggregator -> bar_aggregator, MLDiscoveryAnalyzer -> ml_discovery_analyzer"""
    s1 = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', name)
    s2 = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s1)
    return s2.lower()
```

**Make `name` optional in `BaseDaemon.__init__`:**
```python
def __init__(self, name: str | None = None, ...):
    if name is None:
        name = _to_snake_case(self.__class__.__name__)
    ...
```

**Result:**
- `BarAggregator()` → `agent_id = "bar_aggregator"`
- `MLDiscoveryAnalyzer()` → `agent_id = "ml_discovery_analyzer"`
- `SignalTracker()` → `agent_id = "signal_tracker"`
- `OutboxPublisher()` → `agent_id = "outbox_publisher"`

Every future subclass gets the correct label at zero cost. The `name=` override remains available for the rare legitimate case (e.g. DLQ drain running multiple instances) but is no longer required.

Log path auto-derive already exists in `BaseDaemon` (`log_path = f"logs/{log_name}.log"` at line 125). Services override it with hardcoded stale strings. Fix: delete the overrides.

---

## Missing Phase 110 Renames

| Old class | New class | Old file | New file |
|---|---|---|---|
| `DLQDrainAgent` | `DLQDrain` | `services/dlq_drain_agent.py` | `services/dlq_drain.py` |
| `MLSignalTrainingMaterializeAgent` | `MLSignalTrainingMaterializer` | `src/intelligence/services/ml_signal_training_materialize_agent.py` | `src/intelligence/services/ml_signal_training_materializer.py` |
| *(no class)* | n/a | `services/shadow_auditor_agent.py` | `services/shadow_auditor.py` |
| *(no class)* | n/a | `services/self_healing_agent.py` | `services/self_healer.py` |
| *(no class)* | n/a | `services/config_service_agent.py` | `services/config_service.py` |
| `TemplateComputeAgent` | `TemplateEvaluator` | `src/intelligence/ai/TEMPLATE_agent.py` | `src/intelligence/ai/TEMPLATE.py` |

Systemd ExecStart paths updated for all renamed files. Launcher scripts that reference these modules updated.

---

## Structlog Event Strings

Convention: `"service_name.action"` — the service name prefix must match the derived `agent_id`.

Affected files and their prefix replacement:

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

Sed pass per file using exact prefix match — no cross-file ambiguity.

---

## Ring 0 Boundary Enforcement

Add to `.git/hooks/pre-commit`:

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

This is a read-only grep — zero false positives for legitimate Ring 0 code, zero performance cost.

---

## Local Variable Cleanup

Two `ctx` usages that are not OTel or domain abbreviations:

1. `src/core/ai/base_agent.py:192` — `ctx: dict[str, Any] = {}` building the LLM audit context dict → rename to `audit_context`
2. `src/intelligence/ai/alpha/*_prompts.py` — `ctx` as a `SignalContext` parameter in 4 prompt builder functions → rename to `context`

---

## Wave Structure

| Plan | Scope | CI Gate |
|---|---|---|
| 01 | BaseDaemon auto-derive; remove all `name=` overrides; remove all `setup_service_logging()` overrides; delete `_AGENT_NAME` constants; fix hardcoded metric label; update `_AGENT_ID_TO_UNIT`; update Grafana + alertmanager | pytest green; verify derived label values match expectations |
| 02 | 5 missing service class renames + file renames; TEMPLATE rename; all systemd ExecStart + launcher import updates; 29 test file renames; 9 test class renames | pytest green; ruff clean; grep confirms zero old identifiers |
| 03 | Structlog event string prefix replacement across 20 files | pytest green; ruff clean; grep confirms zero old prefixes |
| 04 | Ring 0 pre-commit enforcement; `ctx` → `audit_context`/`context` local var cleanup; CLAUDE.md updates | pre-commit passes on full repo; pytest green |

---

## Acceptance Criteria

- `find src services tests -name '*.py' | xargs grep -lw "bar_aggregator_agent\|bar_writer_agent\|feature_writer_agent\|lineage_writer_agent\|SignalTrackerComputeAgent\|GraduationComputeAgent\|MLDiscoveryComputeAgent\|alerting_agent\|outbox_dispatcher_agent\|provider_merger_agent"` returns zero results
- `pytest tests/unit/ -q` — 4049+ passed, 0 failures
- `ruff check .` — clean
- Grafana dashboards load without "no data" on agent_id-filtered panels
- Ring 0 boundary check fires on a deliberate violation (smoke test the hook)
- `grep -rn "from src\.intelligence\|from src\.config" src/core/ --include="*.py"` returns zero results
- All structlog event strings in services match `{derived_agent_id}.{action}` pattern
