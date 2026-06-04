---
phase: 111-naming-alignment
plan: 02
subsystem: infra
tags: [naming, services, tests, systemd, rename]

# Dependency graph
requires:
  - phase: 111-naming-alignment
    plan: 01
    provides: "BaseDaemon auto-derive infrastructure; name= override removal"
provides:
  - "5 Phase-109 service files renamed to Phase-110 conventions (dlq_drain, shadow_auditor, self_healer, config_service, ml_signal_training_materializer)"
  - "TEMPLATE_agent.py renamed to TEMPLATE.py with class TemplateEvaluator"
  - "MLSignalTrainingMaterializer class; launcher ml_signal_training_agent.py updated to import it"
  - "DLQDrain class (renamed from DLQDrainAgent; name= override removed)"
  - "All 5 systemd ExecStart paths updated to renamed files"
  - "Stale ml_signal_training_materialize_agent.log paths updated in systemd unit"
  - "29 test files renamed to drop _agent suffix (services + core)"
  - "9 test class names updated to drop Agent suffix"
  - "All shadow_auditor import paths in test file updated to new module name"
affects:
  - 111-03-PLAN
  - 111-04-PLAN
  - services/
  - tests/unit/

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "MLSignalTrainingMaterializer uses super().__init__() for auto-derive (no positional string arg)"
    - "DLQDrain uses super().__init__(max_idle_seconds=600) - no name= override needed"

key-files:
  created: []
  modified:
    - services/dlq_drain.py
    - services/shadow_auditor.py
    - services/self_healer.py
    - services/config_service.py
    - src/intelligence/services/ml_signal_training_materializer.py
    - src/intelligence/ai/TEMPLATE.py
    - services/ml_signal_training_agent.py
    - production/systemd/indicagent-dlq-drain.service
    - production/systemd/indicagent-shadow-auditor.service
    - production/systemd/indicagent-self-healing-agent.service
    - production/systemd/indicagent-config-service.service
    - production/systemd/indicagent-ml-signal-training-materialize.service
    - tests/unit/services/test_bar_aggregator.py
    - tests/unit/services/test_bar_writer.py
    - tests/unit/services/test_bar_auditor.py
    - tests/unit/services/test_feature_writer.py
    - tests/unit/services/test_signal_writer.py
    - tests/unit/services/test_signal_tracker.py
    - tests/unit/services/test_signal_auditor.py
    - tests/unit/services/test_lifecycle_writer.py
    - tests/unit/services/test_swarm_ledger_writer.py
    - tests/unit/services/test_alert_monitor.py
    - tests/unit/services/test_graduation_analyzer.py
    - tests/unit/services/test_signal_metrics_writer.py
    - tests/unit/services/test_signal_metrics_analyzer.py
    - tests/unit/services/test_shadow_auditor.py
    - tests/unit/services/test_alpha_swarm.py
    - tests/unit/services/test_ml_discovery_analyzer.py
    - tests/unit/services/test_ml_orchestrator.py
    - tests/unit/services/test_data_quality_auditor.py
    - tests/unit/services/test_context_writer.py
    - tests/unit/services/test_macro_analyzer.py
    - tests/unit/services/test_service_auditor.py
    - tests/unit/services/test_service_auditor_webhooks.py
    - tests/unit/services/test_provider_merger.py
    - tests/unit/services/test_base_provider.py
    - tests/unit/services/test_ibkr_provider.py
    - tests/unit/services/test_correlation.py
    - tests/unit/services/test_regime_coherence.py
    - tests/unit/core/test_base_writer.py
    - tests/unit/core/test_multiplier.py

key-decisions:
  - "MLSignalTrainingMaterializeAgent super().__init__() changed from positional string to keyword-less call; BaseDaemon auto-derives ml_signal_training_materializer from class name"
  - "DLQDrainAgent name='dlq_drain_agent' override removed; BaseDaemon now auto-derives dlq_drain"
  - "shadow_auditor_agent.py has no class to rename - module-level functions; only file renamed"
  - "self_healing_agent.py and config_service_agent.py are FastAPI apps with no daemon class; only files renamed"
  - "4 WARNING-3 test files intentionally kept: test_base_agent.py, test_core_ai_base_agent.py, test_counterfactual_agent.py, test_skeptic_agent.py - domain/infra-correct names"
  - "TemplateComputeAgent -> TemplateEvaluator; agent_id updated from template_v1 to template_evaluator"
  - "Installed systemd units updated via sudo cp + systemctl daemon-reload"

# Metrics
duration: 15min
completed: 2026-05-30
---

# Phase 111 Plan 02: Service Renames + Test File Renames Summary

**5 Phase-109 services renamed to Phase-110 conventions (DLQDrain, shadow_auditor, self_healer, config_service, MLSignalTrainingMaterializer); TEMPLATE.py class updated; 29 test files renamed; 9 test class names updated; systemd ExecStart paths aligned**

## Performance

- **Duration:** ~15 min
- **Completed:** 2026-05-30
- **Tasks:** 2
- **Files modified:** 41 (12 in Task 1, 29 in Task 2)

## Accomplishments

**Task 1: Service renames**
- `dlq_drain_agent.py` → `dlq_drain.py`; `DLQDrainAgent` → `DLQDrain`; stale `name="dlq_drain_agent"` override removed
- `shadow_auditor_agent.py` → `shadow_auditor.py` (module-level functions, no class rename)
- `self_healing_agent.py` → `self_healer.py` (FastAPI app, no class rename)
- `config_service_agent.py` → `config_service.py` (FastAPI app, no class rename)
- `ml_signal_training_materialize_agent.py` → `ml_signal_training_materializer.py`; `MLSignalTrainingMaterializeAgent` → `MLSignalTrainingMaterializer`; positional `super().__init__("MLSignalTrainingMaterializeAgent")` changed to `super().__init__()` for auto-derive
- `TEMPLATE_agent.py` → `TEMPLATE.py`; `TemplateComputeAgent` → `TemplateEvaluator`; `agent_id` updated
- Launcher `ml_signal_training_agent.py` import + instantiation updated to `MLSignalTrainingMaterializer`
- 5 systemd ExecStart paths updated
- Stale `ml_signal_training_materialize_agent.log` paths updated to `ml_signal_training_materializer.log` in systemd unit
- Installed systemd units updated in `/etc/systemd/system/` + daemon-reload

**Task 2: Test file renames**
- 27 `tests/unit/services/*_agent.py` files renamed to drop `_agent` suffix
- 2 `tests/unit/core/*_agent.py` files renamed: `test_base_writer`, `test_multiplier`
- 9 test class names updated: `TestBarAuditorAgentInit`, `TestSignalMetricsComputeAgent`, 4 `TestAlerting*` → `TestAlertMonitor*`, `TestSignalWriterAgentStructure`, `TestSignalWriterAgentFlush`, `TestLifecycleWriterAgentStructure`, `TestFeatureWriterAgentLifecycle`, `TestBaseWriterAgentAbstract`
- All `services.shadow_auditor_agent` module references in test file updated to `services.shadow_auditor`
- 4 intentionally-excluded test files preserved with `_agent` suffix (WARNING-3)

## Task Commits

1. **Task 1: Rename 5 service files + TEMPLATE; update classes and systemd ExecStart** - `d825b85b` (refactor)
2. **Task 2: Rename 29 test files and update Agent class names** - `5056122e` (refactor)

## Intentionally Excluded Files (WARNING-3)

These 4 test files retain `_agent` suffix because the name is domain/infra-correct:
- `tests/unit/core/test_base_agent.py` - tests `BaseDaemon` base class infrastructure
- `tests/unit/core/test_core_ai_base_agent.py` - tests `BaseAIWorker` infrastructure
- `tests/unit/services/test_counterfactual_agent.py` - tests domain AI evaluator (agent is correct domain noun)
- `tests/unit/services/test_skeptic_agent.py` - tests domain AI evaluator (agent is correct domain noun)

## Deferred Exceptions (services/_agent.py files NOT renamed)

These 5 service files are thin oneshot entrypoints/launchers with no daemon class to rename:
- `services/outbox_dispatcher_agent.py` - deferred (original Phase 111 deferral)
- `services/ml_signal_training_agent.py` - launcher; systemd ExecStart points at it
- `services/ml_training_agent.py` - oneshot nightly timer entrypoint
- `services/feature_validation_agent.py` - oneshot daily timer entrypoint
- `services/hmm_training_agent.py` - oneshot monthly timer entrypoint

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_shadow_auditor.py had 3 additional `services.shadow_auditor_agent` module references not caught by top-level import fix**
- **Found during:** Task 2 (pytest run after renames)
- **Issue:** Tests at lines 171, 194, 280-335 used inline `import services.shadow_auditor_agent` and `patch("services.shadow_auditor_agent.*")` inside test functions; these failed with ModuleNotFoundError
- **Fix:** Replaced all occurrences of `services.shadow_auditor_agent` with `services.shadow_auditor` using replace_all
- **Files modified:** `tests/unit/services/test_shadow_auditor.py`
- **Committed in:** `5056122e` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Necessary for test correctness. No scope creep.

## Verification Results

- `find services/ -name "*_agent.py"` → exactly 5 deferred exceptions
- `find tests/ -name "*_agent*.py"` → exactly 4 intentionally-excluded domain/infra files
- `grep -rn "class DLQDrainAgent|class MLSignalTrainingMaterializeAgent|class TemplateComputeAgent"` → zero results
- `pytest tests/unit/ -q` → 4049 passed, 31 skipped
- `ruff check .` → All checks passed

## Next Phase Readiness

- Plan 03 (AUTHORING.md + TEMPLATE.py reference updates) can proceed - TEMPLATE.py class name is now TemplateEvaluator
- Plan 04 (pre-commit hook wave) has a clean baseline - no _agent suffix files except documented exceptions

---
*Phase: 111-naming-alignment*
*Completed: 2026-05-30*
