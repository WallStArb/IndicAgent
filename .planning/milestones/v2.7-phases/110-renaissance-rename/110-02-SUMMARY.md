---
phase: 110-renaissance-rename
plan: 02
subsystem: ai-infrastructure
tags: [rename, ring1, evaluator, signalcontext, alphabaseclasses, wave2]

# Dependency graph
requires:
  - phase: 110-01
    provides: BaseAIWorker (renamed from BaseAIAgent), BaseSwarmCoordinator (renamed from BaseGroupService), BaseDaemon (renamed from BaseAgent)
provides:
  - Evaluator abstract base at src/core/ai/evaluator.py (moved from multiplier_agent.py)
  - SkepticEvaluator, CorrelationAnalyzer, CounterfactualEvaluator, RegimeCoherenceAnalyzer, MLEvaluator (5 alpha agents renamed)
  - NarrativeSynthesizer (narrative LLM worker renamed)
  - SignalContext + SignalContextCache (AIContext/AIContextCache renamed in context.py)
  - All Wave 1 import regressions fixed (BaseAgent, BaseGroupService, BaseWriterAgent, BaseProviderAgent, BaseAIAgent)
affects: [095-pydantic-ai-agent-layer, 096-agent-registry, 094-litellm-instructor]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Evaluator abstract base pattern: concrete swarm agents inherit Evaluator, not BaseAIWorker directly"
    - "SignalContext replaces AIContext as the domain context carrier for AI agent computation"

key-files:
  created:
    - src/core/ai/evaluator.py
  modified:
    - src/core/ai/context.py
    - src/core/ai/base_agent.py
    - src/core/ai/base_group_service.py
    - src/intelligence/ai/alpha/skeptic_agent.py
    - src/intelligence/ai/alpha/correlation_agent.py
    - src/intelligence/ai/alpha/counterfactual_agent.py
    - src/intelligence/ai/alpha/regime_coherence_agent.py
    - src/intelligence/ai/alpha/ml_scorer_agent.py
    - src/intelligence/ai/narrative/narrative_agent.py
    - services/alpha_swarm_agent.py
    - services/narrative_group_compute_agent.py

key-decisions:
  - "Evaluator file rename only (multiplier_agent.py -> evaluator.py); file content rewritten in place via git mv to preserve history"
  - "SignalContext file stays at src/core/ai/context.py; ring placement change (Ring 0 -> Ring 1) deferred to Phase 095 per plan deferral note"
  - "NarrativeGroupComputeAgent deliberately preserved - only NarrativeComputeAgent renamed (word-boundary enforcement worked correctly)"
  - "Wave 1 import regressions auto-fixed in Task 3: BaseAgent->BaseDaemon, BaseGroupService->BaseSwarmCoordinator, BaseWriterAgent->BaseWriter, BaseProviderAgent->BaseProvider, BaseAIAgent->BaseAIWorker in all service importers"

patterns-established:
  - "Rule 1 auto-fix: Wave 1 renamed class definitions but missed updating all importers; fixed in Wave 2 Task 3"

requirements-completed: [RENAME-02]

# Metrics
duration: 7min
completed: 2026-05-30
---

# Phase 110 Plan 02: Renaissance Rename Wave 2 Summary

**Evaluator abstract base moved to src/core/ai/evaluator.py; 7 Ring 1 AI class identifiers + AIContext/AIContextCache renamed; 4049 unit tests green**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-05-30T19:39:00Z
- **Completed:** 2026-05-30T19:46:33Z
- **Tasks:** 3
- **Files modified:** 78

## Accomplishments

- Moved `BaseMultiplierAgent` -> `Evaluator` at `src/core/ai/evaluator.py` (git mv preserving history)
- Renamed 6 evaluator/synthesizer classes: SkepticEvaluator, CorrelationAnalyzer, CounterfactualEvaluator, RegimeCoherenceAnalyzer, MLEvaluator, NarrativeSynthesizer
- Renamed AIContext -> SignalContext and AIContextCache -> SignalContextCache (27 + 6 importers)
- NarrativeGroupComputeAgent preserved - word-boundary sed correctly left it untouched
- Fixed 4 Wave 1 import regressions where class definitions were renamed but importers were not updated
- All 4049 unit tests pass; ruff and black clean

## Task Commits

1. **Task 1: Move+rename BaseMultiplierAgent -> Evaluator** - `78246ebc` (refactor)
2. **Task 2: Rename Ring 1 AI evaluation identifiers** - `24ba843f` (refactor)
3. **Task 3: Wave 2 CI gate + fix Wave 1 import regressions** - `74fbd9be` (refactor)

## Files Created/Modified

- `src/core/ai/evaluator.py` - New location for Evaluator abstract base (moved from multiplier_agent.py)
- `src/core/ai/context.py` - SignalContext + SignalContextCache (renamed from AIContext/AIContextCache)
- `src/core/ai/base_agent.py` - Updated to use SignalContext
- `src/core/ai/base_group_service.py` - Updated to use SignalContextCache
- `src/intelligence/ai/alpha/skeptic_agent.py` - SkepticEvaluator(Evaluator)
- `src/intelligence/ai/alpha/correlation_agent.py` - CorrelationAnalyzer(Evaluator)
- `src/intelligence/ai/alpha/counterfactual_agent.py` - CounterfactualEvaluator(Evaluator)
- `src/intelligence/ai/alpha/regime_coherence_agent.py` - RegimeCoherenceAnalyzer(Evaluator)
- `src/intelligence/ai/alpha/ml_scorer_agent.py` - MLEvaluator(Evaluator)
- `src/intelligence/ai/narrative/narrative_agent.py` - NarrativeSynthesizer(BaseAIWorker)
- `services/alpha_swarm_agent.py` - Uses new Evaluator list, BaseSwarmCoordinator, SignalContext
- `services/narrative_group_compute_agent.py` - NarrativeSynthesizer, BaseSwarmCoordinator
- 30+ additional services/tests updated for Wave 1 import regressions

## Decisions Made

- SignalContext file stays at `src/core/ai/context.py` (Ring 0) per plan deferral; Ring 1 relocation is Phase 095 work
- Wave 1 import regressions fixed here (Task 3) rather than blocking this plan or creating a separate hotfix
- Used `sed -i` with word boundaries (`\b`) for all renames to prevent partial matches

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed Wave 1 import regressions: 4 renamed base classes not updated in importers**
- **Found during:** Task 3 (Wave 2 CI gate)
- **Issue:** Wave 1 renamed `BaseAgent->BaseDaemon`, `BaseGroupService->BaseSwarmCoordinator`, `BaseWriterAgent->BaseWriter`, `BaseProviderAgent->BaseProvider`, `BaseAIAgent->BaseAIWorker` in class definitions, but ~30 service/test files were still importing the old names. This caused `ImportError` during test collection, blocking CI gate from passing.
- **Fix:** Applied word-boundary sed substitutions for all 4 regressions across all `*.py` files. `BaseAgent->BaseDaemon` was the largest blast radius (services/*, tests/*).
- **Files modified:** 31 service files (alerting_agent, bar_aggregator, bar_auditor, bar_replay_provider, bar_writer, cross_asset_service, ctx_writer, dlq_drain, feature_writer, graduation_compute, graduation_writer, ibkr_provider, intelligence_pipeline, lifecycle_writer, lineage_writer, llm_writer, macro_compute, ml_data_quality, ml_discovery, ml_orchestrator, narrative_group, provider_merger, service_auditor, signal_auditor, signal_metrics_compute, signal_metrics_writer, signal_replay_auditor, signal_tracker_compute, signal_writer, swarm_ledger_writer)
- **Verification:** pytest tests/unit/ 4049 passed (was: 21 collection errors + 233 failures)
- **Committed in:** `74fbd9be` (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Fix was necessary to satisfy plan's "pytest tests/unit/ passes with zero failures" success criterion. No scope creep - all changes were symbol renames consistent with Wave 1 intent.

## Issues Encountered

- Pre-commit hooks require `.venv` to be accessible from worktree; resolved by creating symlink `.venv -> /home/bg/dev/indicagent/.venv`

## Next Phase Readiness

- Wave 2 complete; all Ring 1 AI evaluation identifiers use new names
- Wave 3 (Plan 03) can proceed: service/daemon class renames (Ring 2 layer)
- Phase 095 can write new evaluators using `Evaluator` and `SignalContext` from the correct locations
- `SignalContext` ring placement deferred to Phase 095 (file stays at `src/core/ai/context.py` until 095 separates Ring 0/Ring 1 imports)

## Self-Check

### Files Exist
- src/core/ai/evaluator.py: EXISTS
- src/core/ai/multiplier_agent.py: GONE (git mv)
- src/intelligence/ai/alpha/skeptic_agent.py contains SkepticEvaluator: VERIFIED
- src/core/ai/context.py contains SignalContext + SignalContextCache: VERIFIED

### Commits Exist
- 78246ebc: Task 1 (BaseMultiplierAgent->Evaluator)
- 24ba843f: Task 2 (Ring 1 identifier renames)
- 74fbd9be: Task 3 (CI gate + Wave 1 regression fixes)

## Self-Check: PASSED

---
*Phase: 110-renaissance-rename*
*Completed: 2026-05-30*
