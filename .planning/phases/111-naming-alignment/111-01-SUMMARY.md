---
phase: 111-naming-alignment
plan: 01
subsystem: infra
tags: [basedaemon, prometheus, otel, structlog, grafana, systemd, naming]

# Dependency graph
requires:
  - phase: 110-renaissance-rename
    provides: "Phase 110 class renames (BaseDaemon, BaseWriter, BaseAIWorker, NarrativeSwarm, etc.)"
provides:
  - "_to_snake_case() module-level utility for PascalCase -> snake_case conversion"
  - "BaseDaemon auto-derives agent_id from class name when name= is omitted"
  - "BaseWriter accepts optional name= (pass-through to BaseDaemon)"
  - "All 21+ stale name= overrides removed from services"
  - "All 9 stale setup_service_logging() path overrides removed"
  - "Stale Environment=LOG_FILE= removed from macro-compute systemd unit"
  - "Hardcoded feature_writer_agent metric label replaced with self._agent_label"
  - "_AGENT_ID_TO_UNIT keys updated to auto-derived agent_id values"
  - "Grafana dashboard label filter expressions updated to current agent_id values"
affects:
  - 111-02-PLAN
  - 111-03-PLAN
  - monitoring
  - observability

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "BaseDaemon auto-derive: name=None -> _to_snake_case(ClassName) at zero per-service cost"
    - "_agent_label in __getattr__ fallback so tests that bypass __init__ via __new__ get correct derived value"
    - "BaseWriter uses self.name (post-super) for metric naming, not the local name arg"

key-files:
  created: []
  modified:
    - src/core/agent/base.py
    - src/core/agent/base_writer.py
    - services/bar_aggregator.py
    - services/bar_auditor.py
    - services/bar_writer.py
    - services/bar_replay_provider.py
    - services/signal_tracker.py
    - services/signal_auditor.py
    - services/signal_replay_auditor.py
    - services/signal_metrics_analyzer.py
    - services/signal_metrics_writer.py
    - services/signal_writer.py
    - services/lifecycle_writer.py
    - services/llm_writer.py
    - services/lineage_writer.py
    - services/graduation_writer.py
    - services/swarm_ledger_writer.py
    - services/context_writer.py
    - services/graduation_analyzer.py
    - services/ml_discovery_analyzer.py
    - services/data_quality_auditor.py
    - services/ml_orchestrator.py
    - services/shadow_auditor_agent.py
    - services/alert_monitor.py
    - services/feature_writer.py
    - services/provider_merger.py
    - services/intelligence_pipeline.py
    - services/macro_analyzer.py
    - services/narrative_swarm.py
    - services/service_auditor.py
    - services/cross_asset_analyzer.py
    - src/intelligence/ai/alpha/counterfactual_agent.py
    - src/intelligence/ai/narrative/narrative_agent.py
    - production/systemd/indicagent-macro-compute.service
    - production/grafana/dashboards/pipeline-health.json
    - production/grafana/dashboards/operations.json
    - tests/unit/services/test_service_auditor_agent.py

key-decisions:
  - "BaseDaemon.__init__ accepts name: str | None = None; derives from class when None using _to_snake_case"
  - "BaseWriter metric names built from self.name (post-super) to handle None arg correctly"
  - "_agent_label added to BaseDaemon.__getattr__ so tests using __new__ bypass get correct derived value"
  - "CrossAssetAnalyzer name= override missed in initial Task 2 sweep; fixed during Task 3 verification"
  - "ibkr_provider_agent Grafana labels left unchanged - BaseProvider uses explicit _agent_name() method, not in scope"
  - "macOS-style LOG_FILE env-var override in macro_analyzer.py Python code left intact; systemd stale override removed"

patterns-established:
  - "All future BaseDaemon subclasses auto-derive correct Prometheus label and log path at zero cost"
  - "Drift is structurally impossible: no service can pass a stale string"

requirements-completed:
  - ALIGN-01

# Metrics
duration: 18min
completed: 2026-05-30
---

# Phase 111 Plan 01: BaseDaemon Auto-Derive Infrastructure Summary

**BaseDaemon auto-derives agent_id via _to_snake_case(ClassName); BaseWriter accepts optional name= pass-through; all 21+ stale name= overrides, 9 setup_service_logging path overrides, and stale systemd LOG_FILE= removed; Grafana and _AGENT_ID_TO_UNIT aligned to derived values**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-05-30T20:32:00Z
- **Completed:** 2026-05-30T20:47:45Z
- **Tasks:** 3
- **Files modified:** 38

## Accomplishments
- `_to_snake_case()` module-level function added with two-pass regex for `MLDiscoveryAnalyzer -> ml_discovery_analyzer`
- `BaseDaemon.__init__` now accepts `name: str | None = None`; auto-derives from class when omitted
- `BaseWriter.__init__` now accepts `name: str | None = None`; passes through to BaseDaemon
- 21+ stale `name=` overrides removed from service `__init__` methods (including BLOCKER 1: signal_writer/lifecycle_writer/llm_writer)
- 2 redundant AI worker `name=` overrides removed (CounterfactualEvaluator, NarrativeSynthesizer)
- 2 `_AGENT_NAME` module constants deleted from signal_metrics_analyzer + signal_metrics_writer
- 9 stale `setup_service_logging("logs/...")` path overrides removed from service `__init__` and `main()`
- `"feature_writer_agent"` hardcoded metric label string replaced with `self._agent_label` (3 sites)
- `Environment=LOG_FILE=logs/macro_compute_agent.log` removed from systemd macro-compute unit
- 19 `_AGENT_ID_TO_UNIT` keys updated from stale class-name strings to derived values
- Grafana `pipeline-health.json` and `operations.json` label filter expressions updated
- All 4049 unit tests green; ruff clean

## Task Commits

1. **Task 1: Add _to_snake_case to BaseDaemon, make name optional, make BaseWriter pass name through** - `aaa90cdb` (feat)
2. **Task 2: Remove all name= overrides, setup_service_logging path overrides, and stale systemd LOG_FILE override** - `9c23a07d` (refactor)
3. **Task 3: Update _AGENT_ID_TO_UNIT keys and Grafana/alertmanager label values** - `54ac1f8b` (refactor)

## Files Created/Modified
- `src/core/agent/base.py` - Added `_to_snake_case()`, moved `import re` to module level, BaseDaemon name optional, `_agent_label` in `__getattr__` fallback
- `src/core/agent/base_writer.py` - BaseWriter name optional, metric names via `self.name` (post-super)
- `services/service_auditor.py` - 19 _AGENT_ID_TO_UNIT keys updated to derived values; comment updated
- `services/cross_asset_analyzer.py` - Remove stale `name="CrossAssetComputeAgent"` override
- `services/feature_writer.py` - Remove name= override; replace 3 hardcoded `"feature_writer_agent"` metric labels with `self._agent_label`
- `services/signal_metrics_analyzer.py` - Delete `_AGENT_NAME` constant; replace 3 usages with `self._agent_label`
- `services/signal_metrics_writer.py` - Delete `_AGENT_NAME` constant; remove `name=_AGENT_NAME` from super
- `production/systemd/indicagent-macro-compute.service` - Remove stale `Environment=LOG_FILE=` line
- `production/grafana/dashboards/pipeline-health.json` - Fix 2 stale agent label filter values
- `production/grafana/dashboards/operations.json` - Fix 1 stale metric name (signal_writer_agent_ prefix)
- 24 additional service files: each had `name=` override and/or stale `setup_service_logging()` path call removed

## Decisions Made
- Added `_agent_label` to `BaseDaemon.__getattr__` fallback so tests using `__new__` bypass (`signal_metrics_analyzer`, `feature_writer` tests) get correct derived value without modifying test setup
- `BaseWriter` metric names built from `self.name` (resolved after super) rather than the local `name` arg to handle `None` correctly
- `CrossAssetAnalyzer` name= override was missed in the initial Task 2 sweep; caught during Task 3 verification grep and fixed atomically with Task 3 commit
- IBKR provider Grafana labels left unchanged: `IBKRProvider` inherits `BaseProvider._agent_name()` which returns `"ibkr_provider_agent"` explicitly - not a phase 111 target
- `macro_analyzer.py` env-var-driven `setup_service_logging()` call left intact; only the systemd `Environment=LOG_FILE=` override that forced a stale path was removed

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added _agent_label to BaseDaemon.__getattr__ for test-bypass pattern**
- **Found during:** Task 2 (full test run after removing name= overrides)
- **Issue:** Tests that create agents via `__new__` (bypassing `__init__`) were missing `_agent_label`; signal_metrics_analyzer and feature_writer tests failed with AttributeError/flush failure
- **Fix:** Added `if name == "_agent_label": return _to_snake_case(type(self).__name__)` to `BaseDaemon.__getattr__` alongside existing test-bypass fallbacks
- **Files modified:** `src/core/agent/base.py`
- **Verification:** All 4 previously failing tests now pass; 4049 total green
- **Committed in:** `9c23a07d` (part of Task 2 commit)

**2. [Rule 1 - Bug] CrossAssetAnalyzer name= override missed in initial Task 2 sweep**
- **Found during:** Task 3 (grep verification of acceptance criteria)
- **Issue:** `services/cross_asset_analyzer.py` had `name="CrossAssetComputeAgent"` override not caught by the original Task 2 grep pattern (file not in explicit task 2 scope)
- **Fix:** Removed the stale override; also updated corresponding `_AGENT_ID_TO_UNIT` key from `"CrossAssetComputeAgent"` to `"cross_asset_analyzer"`
- **Files modified:** `services/cross_asset_analyzer.py`, `services/service_auditor.py`
- **Committed in:** `54ac1f8b` (Task 3 commit)

**3. [Rule 1 - Bug] Stale test assertion for feature_writer_agent key in service_auditor**
- **Found during:** Task 3 (test run after _AGENT_ID_TO_UNIT update)
- **Issue:** `test_agent_id_to_unit_feature_writer_key` asserted the old stale key `"feature_writer_agent"` and that `"feature_writer"` was NOT present - both now wrong
- **Fix:** Updated test to assert `_AGENT_ID_TO_UNIT["feature_writer"] == "indicagent-feature-writer"` and that `"feature_writer_agent"` is NOT present
- **Files modified:** `tests/unit/services/test_service_auditor_agent.py`
- **Committed in:** `54ac1f8b` (Task 3 commit)

---

**Total deviations:** 3 auto-fixed (1 missing critical, 2 bugs)
**Impact on plan:** All auto-fixes necessary for correctness. No scope creep.

## Issues Encountered
- Worktree pre-commit hook failed initially because `.venv` symlink didn't exist in worktree path; fixed by symlinking `/home/bg/dev/indicagent/.venv` into worktree directory

## Next Phase Readiness
- Plan 02 (file renames: DLQDrain, shadow_auditor, self_healer, etc.) can proceed - Wave 1 infrastructure complete
- `dlq_drain` key in `_AGENT_ID_TO_UNIT` already set to derived value ahead of Plan 02 rename
- BaseDaemon auto-derive means Plan 02 class renames automatically produce correct Prometheus labels

---
*Phase: 111-naming-alignment*
*Completed: 2026-05-30*
