---
phase: "110-renaissance-rename"
plan: "04"
subsystem: "services, systemd, API routes, dashboard, CLAUDE.md"
tags: ["rename", "ring-2", "file-names", "systemd", "api-routes", "claude-md"]
dependency_graph:
  requires: ["110-03"]
  provides: ["ring-2-file-renames-complete", "systemd-execstart-updated", "api-routes-tier3-fixed", "claude-md-updated"]
  affects: ["services/", "production/systemd/", "src/api/routes/", "dashboard/", "CLAUDE.md", "src/intelligence/services/", "src/config/"]
tech_stack:
  added: []
  patterns: ["git-mv-history-preservation", "mechanical-name-derivation", "agent-id-operational-exception"]
key_files:
  created: ["docs/foundation/naming-conventions.md (redirect stub)"]
  modified:
    - "services/ (30 Ring 2 daemon renames)"
    - "src/intelligence/services/ (ml_trainer.py, hmm_trainer.py, feature_validation_analyzer.py)"
    - "src/config/outbox_publisher.py (was outbox_dispatcher.py)"
    - "services/ml_training_agent.py (launcher import fix)"
    - "services/hmm_training_agent.py (launcher import fix)"
    - "services/feature_validation_agent.py (launcher import fix)"
    - "production/systemd/*.service (29 ExecStart updates)"
    - "tests/ (imports updated across 40+ test files; test_feature_validation_analyzer.py + test_hmm_trainer.py renamed)"
    - "src/api/routes/narrative.py (bar_ctx->bar_context, i7_ctx->i7_context, exc->error)"
    - "src/api/routes/health.py (resp->response)"
    - "src/api/routes/drift.py, ai_stats.py, signals.py (exc->error)"
    - "dashboard/src/hooks/use-observability-stream.ts (agent_id comment added)"
    - "CLAUDE.md (version bump, Pending renames removed, new vocabulary)"
decisions:
  - "Dashboard UNIT_TO_AGENT strings preserved unchanged per operational exception (naming-system.md Section 10) - these are Prometheus agent_id labels, not display names"
  - "Log file paths in renamed intelligence services updated (feature_validation_analyzer.log, hmm_trainer.log, ml_trainer.log) to satisfy zero-stale-references acceptance criterion"
  - "Launcher scripts (ml_training_agent.py, hmm_training_agent.py, feature_validation_agent.py) keep their names - they are the systemd ExecStart targets; only their internal imports changed"
  - "test_hmm_training_compute_agent.py renamed to test_hmm_trainer.py and imports fixed (discovered as Rule 1 fix during Task 1)"
  - "services/outbox_dispatcher_agent.py import fixed to src.config.outbox_publisher (discovered during outbox rename)"
metrics:
  duration: "~25 minutes"
  completed: "2026-05-30"
  tasks_completed: 5
  files_modified: 130+
---

# Phase 110 Plan 04: Wave 4 File Renames, ExecStart, API/Tier3, Dashboard, CLAUDE.md Summary

Wave 4 of the atomic rename: 30 Ring 2 service file renames, 3 intelligence service renames, 29 systemd ExecStart updates, API Tier 3 abbreviation expansion, dashboard agent_id documentation, and CLAUDE.md vocabulary update.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | git mv Ring 2 service files, fix imports + systemd ExecStart | 607618c9 | 121 files (30 service renames, 3 intelligence renames, 29 systemd units, 40+ test imports) |
| 2 | API route Tier 3 abbreviation fixes | d6c9ce08 | 5 API route files |
| 3 | Dashboard agent_id comment block (operational exception) | 5c12f91e | 1 dashboard TypeScript file |
| 4 | CLAUDE.md new vocabulary + naming-conventions.md redirect | 4fc712e8 | 2 docs files |
| 5 | CI green; log paths updated in renamed intelligence services | d964b10f | 3 intelligence service files |

## Service File Rename Mapping

| Old file | New file |
|----------|----------|
| services/intelligence_pipeline_agent.py | services/intelligence_pipeline.py |
| services/alpha_swarm_agent.py | services/alpha_swarm.py |
| services/narrative_group_compute_agent.py | services/narrative_swarm.py |
| services/bar_aggregator_agent.py | services/bar_aggregator.py |
| services/provider_merger_agent.py | services/provider_merger.py |
| services/cross_asset_service.py | services/cross_asset_analyzer.py |
| services/macro_compute_agent.py | services/macro_analyzer.py |
| services/signal_metrics_compute_agent.py | services/signal_metrics_analyzer.py |
| services/graduation_compute_agent.py | services/graduation_analyzer.py |
| services/ml_discovery_agent.py | services/ml_discovery_analyzer.py |
| services/signal_tracker_compute_agent.py | services/signal_tracker.py |
| services/alerting_agent.py | services/alert_monitor.py |
| services/ml_orchestrator_agent.py | services/ml_orchestrator.py |
| services/bar_writer_agent.py | services/bar_writer.py |
| services/feature_writer_agent.py | services/feature_writer.py |
| services/signal_writer_agent.py | services/signal_writer.py |
| services/lifecycle_writer_agent.py | services/lifecycle_writer.py |
| services/lineage_writer_agent.py | services/lineage_writer.py |
| services/llm_writer_service.py | services/llm_writer.py |
| services/ctx_writer_agent.py | services/context_writer.py |
| services/swarm_ledger_writer_agent.py | services/swarm_ledger_writer.py |
| services/signal_metrics_writer_agent.py | services/signal_metrics_writer.py |
| services/graduation_writer_agent.py | services/graduation_writer.py |
| services/bar_auditor_agent.py | services/bar_auditor.py |
| services/signal_auditor_agent.py | services/signal_auditor.py |
| services/signal_replay_auditor_agent.py | services/signal_replay_auditor.py |
| services/service_auditor_agent.py | services/service_auditor.py |
| services/ml_data_quality_agent.py | services/data_quality_auditor.py |
| services/bar_replay_provider_agent.py | services/bar_replay_provider.py |
| services/ibkr_provider_agent.py | services/ibkr_provider.py |
| src/intelligence/services/ml_training_compute_agent.py | src/intelligence/services/ml_trainer.py |
| src/intelligence/services/hmm_training_compute_agent.py | src/intelligence/services/hmm_trainer.py |
| src/intelligence/services/feature_validation_compute_agent.py | src/intelligence/services/feature_validation_analyzer.py |
| src/config/outbox_dispatcher.py | src/config/outbox_publisher.py |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_hmm_training_compute_agent.py imports broken by rename**
- Found during: Task 1
- Issue: Test file `tests/unit/services/test_hmm_training_compute_agent.py` imported from `src.intelligence.services.hmm_training_compute_agent` which was renamed
- Fix: Renamed test file to `test_hmm_trainer.py` and updated all imports to new module path
- Files modified: tests/unit/services/test_hmm_trainer.py
- Commit: 607618c9

**2. [Rule 1 - Bug] services/outbox_dispatcher_agent.py import broken by outbox rename**
- Found during: Task 1
- Issue: `services/outbox_dispatcher_agent.py` launcher imported from `src.config.outbox_dispatcher` which was renamed to `outbox_publisher`
- Fix: Updated import to `src.config.outbox_publisher`
- Files modified: services/outbox_dispatcher_agent.py
- Commit: 607618c9

**3. [Rule 1 - Bug] services/feature_validation_agent.py import broken by rename**
- Found during: Task 1
- Issue: Launcher imported from `src.intelligence.services.feature_validation_compute_agent`
- Fix: Updated import to `src.intelligence.services.feature_validation_analyzer`
- Files modified: services/feature_validation_agent.py
- Commit: 607618c9

**4. [Rule 2 - Missing update] Log paths in renamed intelligence services**
- Found during: Task 5
- Issue: `setup_service_logging()` calls still referenced old module-name-based log paths (e.g. `logs/feature_validation_compute_agent.log`)
- Fix: Updated to new names (feature_validation_analyzer.log, hmm_trainer.log, ml_trainer.log)
- Files modified: src/intelligence/services/feature_validation_analyzer.py, hmm_trainer.py, ml_trainer.py
- Commit: d964b10f

### Intentional Deviation from Plan Section 9 (Dashboard)

The plan (Section 9) specified updating `UNIT_TO_AGENT` values and `agentAge` keys in `use-observability-stream.ts` to new class names. This was NOT done.

**Reason:** These strings are matched against the Prometheus `agent` label (`r.labels["agent"]`), which equals the `name="..."` constructor argument. Wave 3 (Plan 03) preserved all `name=` arguments unchanged under the operational exception (naming-system.md Section 10). Changing these dashboard strings would break the Prometheus lookup.

**Resolution:** Added a comment block above `UNIT_TO_AGENT` documenting this as an intentional operational exception. This is the correct interpretation: Section 10 explicitly overrides Section 9 for these specific strings.

## CI Results

- `pytest tests/unit/ -q`: 4049 passed, 31 skipped, 0 failures
- `ruff check .`: All checks passed
- `black .`: All files unchanged (787 files)
- Full-repo grep for retired base class identifiers in class/import lines: 0 results
- Non-Python surfaces (Makefile, docker YAML): 0 hits

## Self-Check: PASSED

- services/bar_aggregator.py: FOUND
- services/service_auditor.py: FOUND
- services/context_writer.py: FOUND
- services/ibkr_provider.py: FOUND
- src/intelligence/services/feature_validation_analyzer.py: FOUND
- src/intelligence/services/ml_trainer.py: FOUND
- src/intelligence/services/hmm_trainer.py: FOUND
- production/systemd/indicagent-bar-aggregator.service ExecStart: services/bar_aggregator.py (verified)
- Task 1 commit 607618c9: FOUND
- Task 2 commit d6c9ce08: FOUND
- Task 3 commit 5c12f91e: FOUND
- Task 4 commit 4fc712e8: FOUND
- Task 5 commit d964b10f: FOUND
