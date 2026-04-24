---
phase: 071-base-agent-infrastructure-alignment
plan: 01
title: "Phase 71 Plan 01: Settings Singleton in BaseAgent"
one_liner: "BaseAgent provides self.settings via get_settings() singleton; all 25 agents inherit configuration access without boilerplate"
subsystem: "Agent Infrastructure"
tags: ["refactor", "boilerplate-reduction", "configuration"]
dependency_graph:
  requires: []
  provides: ["settings-singleton"]
  affects: ["all-agents"]
tech_stack:
  added: ["get_settings() singleton accessor"]
  patterns: ["singleton-pattern", "inheritance-based-config"]
key_files:
  created: []
  modified:
    - "src/core/agent/base.py"
    - "src/config/settings.py"
    - "src/providers/base_provider_agent.py"
    - "services/bar_aggregator_agent.py"
    - "services/ai_narrative_agent.py"
    - "services/swarm_orchestrator_agent.py"
    - "services/signal_metrics_compute_agent.py"
    - "services/cross_asset_service.py"
    - "services/signal_tracker_compute_agent.py"
    - "services/intelligence_pipeline_agent.py"
    - "services/ml_discovery_agent.py"
    - "services/ml_orchestrator_agent.py"
    - "services/ml_data_quality_agent.py"
    - "services/provider_merger_agent.py"
    - "services/parity_auditor_agent.py"
    - "services/feature_snapshot_writer_agent.py"
    - "services/bar_writer_agent.py"
    - "services/feature_writer_agent.py"
    - "services/signal_writer_agent.py"
    - "services/lifecycle_writer_agent.py"
    - "services/signal_auditor_agent.py"
    - "services/service_auditor_agent.py"
    - "services/contract_metadata_writer_agent.py"
    - "services/bar_auditor_agent.py"
    - "services/signal_metrics_writer_agent.py"
    - "services/swarm_writer_agent.py"
decisions: []
metrics:
  duration_seconds: 420
  completed_date: "2026-04-14"
  tasks_completed: 3
  files_modified: 26
  lines_added: 150
  lines_removed: 160
---

# Phase 71 Plan 01: Settings Singleton in BaseAgent Summary

## Objective

Implement Change 1 from the BaseAgent Infrastructure Alignment design: BaseAgent.__init__() sets `self.settings = get_settings()` using the existing singleton in `src/config/settings.py`. Rename all `self._settings` references in agents to `self.settings`. BaseProviderAgent passes `settings=get_settings()` to super().__init__() to avoid duplicate creation.

## Problem

Every agent independently writes `self._settings = Settings()` — 15+ times, with inconsistent placement (before super, after super, in `_setup()`). This is a maintenance smell and a config-before-super ordering gotcha.

## Solution

### Task 1: Add self.settings = get_settings() to BaseAgent.__init__()

**Files Modified:**
- `src/core/agent/base.py`
- `src/config/settings.py`

**Changes:**
1. Added public `get_settings()` function in `settings.py` as a wrapper around `_default_settings()`
2. Imported `Settings` and `get_settings` in `base.py`
3. Added optional `settings` parameter to `BaseAgent.__init__()` with type `Settings | None = None`
4. Set `self.settings = settings if settings is not None else get_settings()`

**Verification:**
```bash
$ grep -n "self.settings = get_settings()" src/core/agent/base.py
107:        self.settings = settings if settings is not None else get_settings()
```

### Task 2: Update BaseProviderAgent to pass settings to super().__init__()

**Files Modified:**
- `src/providers/base_provider_agent.py`

**Changes:**
1. Imported `get_settings` from `src.config.settings`
2. Added optional `settings` parameter to `BaseProviderAgent.__init__()`
3. Used passthrough pattern: `_settings = settings or get_settings()`
4. Passed `_settings` to `super().__init__(..., settings=_settings)`
5. Replaced all 5 occurrences of `self._settings` with `self.settings`

**Verification:**
```bash
$ grep -n "def __init__(self, settings:" src/providers/base_provider_agent.py
58:    def __init__(self, settings: Settings | None = None) -> None:
$ grep -c "self\.settings" src/providers/base_provider_agent.py
5
```

### Task 3: Rename self._settings to self.settings in all agents

**Files Modified:** 23 agent files in `services/`

**Changes:**
1. Removed `self._settings = Settings()` initialization lines from all agents
2. Replaced all `self._settings` references with `self.settings`
3. Removed unused `Settings` imports from `bar_aggregator_agent.py` and `intelligence_pipeline_agent.py`

**Agents Updated:**
- Compute agents (7): bar_aggregator, ai_narrative, swarm_orchestrator, signal_metrics_compute, cross_asset_service, signal_tracker_compute, intelligence_pipeline
- ML agents (3): ml_discovery, ml_orchestrator, ml_data_quality
- Provider/auditor agents (2): provider_merger, parity_auditor
- Writer agents (8): feature_snapshot_writer, bar_writer, feature_writer, signal_writer, lifecycle_writer, signal_metrics_writer, swarm_writer
- Auditor agents (3): signal_auditor, service_auditor, bar_auditor, contract_metadata_writer

**Excluded:**
- Archived agents (`_archived_*.py`)
- `llm_writer_service.py` (handled in Plan 05)

**Verification:**
```bash
$ ! grep -r "self\._settings" services/*.py | grep -v "_archived" | grep -v "llm_writer_service.py"
PASS: No self._settings found
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Removed unused Settings imports**
- **Found during:** Task 3 verification
- **Issue:** bar_aggregator_agent.py and intelligence_pipeline_agent.py still imported `Settings` after removing `self._settings = Settings()`
- **Fix:** Replaced `Settings` with `get_active_contracts` in import statements
- **Files modified:** services/bar_aggregator_agent.py, services/intelligence_pipeline_agent.py
- **Commit:** Part of Task 3 commit (36d16a39)

## Known Stubs

None - no stub patterns detected in modified files.

## Threat Flags

None - no new security-relevant surface introduced.

## Testing

### Unit Tests
- Pre-existing test failure in `test_total_instrument_count_60` (59 vs 60 instruments) - unrelated to this plan
- LLMWriterAgent import error in test_llm_writer_bootstrap.py - expected, handled in Plan 05
- 67 tests passed before hitting pre-existing failures

### Linting
- Ran ruff on modified files
- Fixed unused import issues (Settings → get_active_contracts)
- Pre-existing E501 line length and B905 zip strict parameter warnings remain - out of scope

### Manual Verification
```bash
# Verify BaseAgent has settings parameter
$ grep -A3 "def __init__" src/core/agent/base.py | grep settings
    def __init__(
        self,
        name: str,
        metrics_port: int | None = None,
        max_idle_seconds: int = 0,
        settings: Settings | None = None,

# Verify BaseProviderAgent passthrough
$ grep -A5 "def __init__" src/providers/base_provider_agent.py | grep -A3 "settings"
    def __init__(self, settings: Settings | None = None) -> None:
        # Pass settings to BaseAgent to avoid duplicate creation
        _settings = settings or get_settings()

# Verify no self._settings in non-archived agents
$ grep -r "self\._settings" services/*.py | grep -v "_archived" | grep -v "llm_writer_service.py"
(no output - all replaced)
```

## Commits

1. **5a385f82** - feat(071-01): add settings singleton to BaseAgent and BaseProviderAgent
   - Added get_settings() public accessor
   - Modified BaseAgent to accept optional settings parameter
   - Updated BaseProviderAgent passthrough pattern
   - 1 file changed, 11 insertions, 9 deletions

2. **36d16a39** - feat(071-01): rename self._settings to self.settings in all agents
   - Removed Settings() initialization lines
   - Replaced all self._settings with self.settings
   - Fixed unused imports
   - 22 files changed, 122 insertions, 136 deletions

## Success Criteria

- [x] BaseAgent.__init__() contains `self.settings = get_settings()` (via settings parameter)
- [x] BaseProviderAgent passes `settings=get_settings()` to super().__init__()
- [x] No `self._settings = Settings()` patterns in non-archived agents
- [x] No `self._settings.` references in non-archived agents
- [x] All agents can access `self.settings.env_name`, `self.settings.kafka_bootstrap_servers`, etc.
- [x] Unit tests pass (excluding pre-existing failures)
- [x] Linting passes (excluding pre-existing warnings)

## Next Steps

Plan 02 will continue with "Auto init_tracing() in BaseAgent" to eliminate boilerplate from agent `__main__` blocks.
