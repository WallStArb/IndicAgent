---
phase: 110-renaissance-rename
plan: "03"
subsystem: services
tags: [rename, wave-3, ring-2, daemon-classes, role-nouns]
dependency_graph:
  requires: ["110-02"]
  provides: ["110-04"]
  affects: [services/, src/intelligence/services/, src/config/outbox_dispatcher.py, tests/]
tech_stack:
  added: []
  patterns: [role-noun class naming, agent_id operational exception]
key_files:
  created: []
  modified:
    - services/intelligence_pipeline_agent.py
    - services/alpha_swarm_agent.py
    - services/narrative_group_compute_agent.py
    - services/bar_aggregator_agent.py
    - services/provider_merger_agent.py
    - services/cross_asset_service.py
    - services/macro_compute_agent.py
    - services/signal_metrics_compute_agent.py
    - services/graduation_compute_agent.py
    - services/ml_discovery_agent.py
    - services/signal_tracker_compute_agent.py
    - services/alerting_agent.py
    - services/ml_orchestrator_agent.py
    - services/bar_writer_agent.py
    - services/feature_writer_agent.py
    - services/signal_writer_agent.py
    - services/lifecycle_writer_agent.py
    - services/lineage_writer_agent.py
    - services/llm_writer_service.py
    - services/ctx_writer_agent.py
    - services/swarm_ledger_writer_agent.py
    - services/signal_metrics_writer_agent.py
    - services/graduation_writer_agent.py
    - services/bar_auditor_agent.py
    - services/signal_auditor_agent.py
    - services/signal_replay_auditor_agent.py
    - services/service_auditor_agent.py
    - services/bar_replay_provider_agent.py
    - services/ibkr_provider_agent.py
    - src/config/outbox_dispatcher.py
    - src/intelligence/services/ml_training_compute_agent.py
    - src/intelligence/services/hmm_training_compute_agent.py
    - src/intelligence/services/feature_validation_compute_agent.py
    - src/api/routes/validation.py
    - "...and 80+ downstream files (stream_keys, schemas, tests, etc.)"
decisions:
  - "agent_id operational exception: name= literals and _AGENT_ID_TO_UNIT dict keys intentionally preserved as old class-name strings to avoid breaking Grafana dashboards and Prometheus alert rules"
  - "pre-commit hook updated to add Trainer/Analyzer/Validator/Auditor/Writer/Publisher to the allowed class suffix list in src/intelligence/ checks"
  - "FeatureValidationAnalyzer added to Wave 3 scope (not in Section 9 table but carries ComputeAgent suffix)"
metrics:
  duration: "~7 minutes"
  completed_date: "2026-05-30"
  tasks_completed: 5
  files_modified: 114
---

# Phase 110 Plan 03: Wave 3 Ring 2 Daemon Class Renames Summary

Renamed all 33 Ring 2 daemon process classes (plus FeatureValidationAnalyzer) from their `ComputeAgent`/`WriterAgent`/`AuditorAgent`/`ProviderAgent`/`DispatcherAgent` suffixed forms to pure role-noun + category-suffix names per Section 9 of the naming spec. Class identifiers only - file names unchanged (deferred to Wave 4).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Rename 5 role-noun daemons (Pipeline, Swarm, NarrativeSwarm, Aggregator, Merger) | acc9c50b | 5 daemon files + downstream |
| 2 | Rename 11 Analyzers, Tracker, Monitor, Orchestrator, Trainers | acc9c50b | 11 daemon files + downstream |
| 3 | Rename 10 Writer daemons | acc9c50b | 10 writer files + downstream |
| 4 | Rename 8 Auditors, Providers, Publisher, DataQuality + fix _AGENT_ID_TO_UNIT | acc9c50b | 8 files + service_auditor_agent |
| 5 | Wave 3 CI gate: ruff, black, pytest, smoke imports, commit | acc9c50b | - |

## Rename Mapping Applied

**Role-noun daemons (Task 1):**
- `IntelligencePipelineComputeAgent` -> `IntelligencePipeline`
- `AlphaSwarmComputeAgent` -> `AlphaSwarm`
- `NarrativeGroupComputeAgent` -> `NarrativeSwarm`
- `BarAggregatorComputeAgent` -> `BarAggregator`
- `ProviderMergerComputeAgent` -> `ProviderMerger`

**Analyzers/Tracker/Monitor/Orchestrator/Trainers (Task 2):**
- `CrossAssetComputeAgent` -> `CrossAssetAnalyzer`
- `MacroComputeAgent` -> `MacroAnalyzer`
- `SignalMetricsComputeAgent` -> `SignalMetricsAnalyzer`
- `GraduationComputeAgent` -> `GraduationAnalyzer`
- `MLDiscoveryComputeAgent` -> `MLDiscoveryAnalyzer`
- `SignalTrackerComputeAgent` -> `SignalTracker`
- `AlertingComputeAgent` -> `AlertMonitor`
- `MLOrchestratorComputeAgent` -> `MLOrchestrator`
- `MLTrainingComputeAgent` -> `MLTrainer`
- `HMMTrainingComputeAgent` -> `HMMTrainer`
- `FeatureValidationComputeAgent` -> `FeatureValidationAnalyzer`

**Writers (Task 3):**
- `BarWriterAgent` -> `BarWriter`
- `FeatureWriterAgent` -> `FeatureWriter`
- `SignalWriterAgent` -> `SignalWriter`
- `LifecycleWriterAgent` -> `LifecycleWriter`
- `LineageWriterAgent` -> `LineageWriter`
- `LLMWriterAgent` -> `LLMWriter`
- `CtxWriterAgent` -> `ContextWriter`
- `SwarmLedgerWriterAgent` -> `SwarmLedgerWriter`
- `SignalMetricsWriterAgent` -> `SignalMetricsWriter`
- `GraduationWriterAgent` -> `GraduationWriter`

**Auditors/Providers/Publisher/DataQuality (Task 4):**
- `BarAuditorAgent` -> `BarAuditor`
- `SignalAuditorAgent` -> `SignalAuditor`
- `SignalReplayAuditorAgent` -> `SignalReplayAuditor`
- `ServiceAuditorAgent` -> `ServiceAuditor`
- `MLDataQualityAuditorAgent` -> `DataQualityAuditor`
- `IBKRProviderAgent` -> `IBKRProvider`
- `BarReplayProviderAgent` -> `BarReplayProvider`
- `OutboxDispatcherAgent` -> `OutboxPublisher`

## Agent ID Operational Exception

The following `name=` literals and `_AGENT_ID_TO_UNIT` dict keys were intentionally preserved as old class-name strings (Grafana/Prometheus depend on these values):

| Preserved name= literal | Value |
|--------------------------|-------|
| `services/cross_asset_service.py` | `"CrossAssetComputeAgent"` |
| `services/signal_tracker_compute_agent.py` | `"SignalTrackerComputeAgent"` |
| `services/macro_compute_agent.py` | `"MacroComputeAgent"` |
| `services/graduation_compute_agent.py` | `"GraduationComputeAgent"` |
| `services/ml_discovery_agent.py` | `"MLDiscoveryComputeAgent"` |
| `services/ml_orchestrator_agent.py` | `"MLOrchestratorComputeAgent"` |
| `src/intelligence/services/ml_training_compute_agent.py` | `"MLTrainingComputeAgent"` |

Snake_case `name=` literals (`"bar_writer_agent"`, `"feature_writer_agent"`, etc.) were not at risk - the word-boundary sed only targeted class-name form strings.

`_AGENT_ID_TO_UNIT` keys preserved: `"SignalTrackerComputeAgent"`, `"CrossAssetComputeAgent"`, `"AlphaSwarmComputeAgent"`, `"NarrativeGroupComputeAgent"`, `"MacroComputeAgent"`, `"GraduationComputeAgent"`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Pre-commit hook missing Trainer/Analyzer/Validator/Auditor/Writer/Publisher suffixes**
- **Found during:** Task 5 (CI gate)
- **Issue:** Pre-commit hook's plugin class naming check in `src/intelligence/` did not include the new `Trainer`, `Analyzer`, or `Analyzer` suffixes, causing `MLTrainer`, `HMMTrainer`, and `FeatureValidationAnalyzer` (all in `src/intelligence/services/`) to fail check 1.
- **Fix:** Added `Trainer|Analyzer|Validator|Auditor|Writer|Publisher` to the exclusion pattern in `/home/bg/dev/indicagent/.git/hooks/pre-commit`
- **Commit:** acc9c50b

**2. [Rule 3 - Blocking] Worktree missing .venv symlink for pre-commit hook**
- **Found during:** Task 5 (CI gate)
- **Issue:** Pre-commit hook uses `${REPO_ROOT}/.venv/bin/ruff` but worktree has no `.venv`. Hook blocked with "ruff not found".
- **Fix:** Created `$WORKTREE_ROOT/.venv` symlink pointing to `/home/bg/dev/indicagent/.venv`

**3. [Rule 1 - Bug] _AGENT_ID_TO_UNIT keys renamed by word-boundary sed**
- **Found during:** Task 1 and Task 2 execution
- **Issue:** `sed -i 's/\bAlphaSwarmComputeAgent\b/AlphaSwarm/g'` also matched the dict key `"AlphaSwarmComputeAgent"` (and similarly for NarrativeGroupComputeAgent, CrossAssetComputeAgent, MacroComputeAgent, GraduationComputeAgent, SignalTrackerComputeAgent).
- **Fix:** Restored all incorrectly renamed dict keys to their original agent_id values after each sed operation.

## CI Results

- `ruff check .`: All checks passed
- `black .`: No format changes needed
- `pytest tests/unit/ -q`: 4049 passed, 31 skipped
- Wave 3 smoke import: `Wave 3 smoke: OK`
- `_AGENT_ID_TO_UNIT` keys: 6 critical old-form keys preserved

## Self-Check: PASSED

Files exist:
- services/bar_aggregator_agent.py contains `class BarAggregator(BaseDaemon):` - FOUND
- services/feature_writer_agent.py contains `class FeatureWriter(BaseWriter):` - FOUND
- services/service_auditor_agent.py contains `class ServiceAuditor(BaseDaemon):` - FOUND
- services/ibkr_provider_agent.py contains `class IBKRProvider(BaseProvider):` - FOUND
- src/intelligence/services/feature_validation_compute_agent.py contains `class FeatureValidationAnalyzer:` - FOUND

Commits exist:
- acc9c50b: refactor(110): rename 33 Ring 2 daemon classes to role nouns (Wave 3) - FOUND
