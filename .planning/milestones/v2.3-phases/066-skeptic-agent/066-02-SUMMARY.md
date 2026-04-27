---
phase: 066-skeptic-agent
plan: 02
subsystem: swarm
tags: [llm, pydantic, asyncio, shadow-recording]

# Dependency graph
requires:
  - phase: 066-01
    provides: SwarmDispatchService, SwarmBaseAgent, SwarmContext with D-16 enrichment, SkepticAgent pattern
provides:
  - CorrelationAgentComputeAgent pure compute class (SwarmBaseAgent subclass)
  - VolumeAgentComputeAgent pure compute class (SwarmBaseAgent subclass)
  - Versioned prompt registries (correlation_v1, volume_v1)
  - 3-agent registry in SwarmDispatchService (skeptic + correlation + volume)
  - 19 new unit tests (10 correlation + 9 volume)
affects: [066-03, 066-04]

# Tech tracking
tech-stack:
  added: []
patterns:
  - "Prompt template string concatenation to avoid E501 line-length violations in multi-line prompts"
  - "Agent registry: adding agent = SwarmBaseAgent subclass + 2 lines in SwarmDispatchService._agents"

key-files:
  created:
    - src/intelligence/swarm/agents/correlation_prompts.py
    - src/intelligence/swarm/agents/correlation_agent.py
    - src/intelligence/swarm/agents/volume_prompts.py
    - src/intelligence/swarm/agents/volume_agent.py
    - tests/unit/test_correlation_agent.py
    - tests/unit/test_volume_agent.py
  modified:
    - services/swarm_dispatch_service.py

key-decisions:
  - "Used string concatenation for prompt templates to satisfy ruff E501 line-length limit while preserving LLM-readable formatting"
  - "Adopted _fmt(val, spec) pattern from skeptic_prompts.py for all prompt field formatting"

patterns-established:
  - "Multi-agent registry: SwarmDispatchService._agents list grows by 2 lines per agent, validates single-service architecture"
  - "Context enrichment via D-16 fields: agents read context.lead_context and context.volume_profile without infrastructure code"

requirements-completed: [D-01, D-02, D-03, D-04, D-05, D-06, D-07, D-15, D-16]

# Metrics
duration: 6min
completed: 2026-04-24
---

# Phase 066 Plan 02: CorrelationAgent + VolumeAgent Summary

**Two swarm agents (correlation + volume) as pure compute classes registered in SwarmDispatchService, validating the single-service multi-agent architecture with zero new infrastructure**

## Performance

- **Duration:** 6 min
- **Started:** 2026-04-24T22:14:35Z
- **Completed:** 2026-04-24T22:20:46Z
- **Tasks:** 1
- **Files modified:** 7

## Accomplishments
- CorrelationAgentComputeAgent reads context.lead_context for cross-asset decorrelation detection
- VolumeAgentComputeAgent reads context.volume_profile for fake-out sweep vs true breakout detection
- Both registered in SwarmDispatchService._agents alongside SkepticAgent (3 agents total)
- 19 new unit tests (10 correlation + 9 volume) -- all 34 swarm tests pass
- Adding agents required exactly 2 imports + 2 registry lines -- validates single-service architecture
- Versioned prompt registries (correlation_v1, volume_v1) with prompt_version in metadata

## Task Commits

Each task was committed atomically:

1. **Task 1: Create CorrelationAgent + VolumeAgent compute classes with prompts** - `516e7ec0` (feat)

## Files Created/Modified
- `src/intelligence/swarm/agents/correlation_prompts.py` - Versioned prompt registry with lead index context fields
- `src/intelligence/swarm/agents/correlation_agent.py` - CorrelationAgentComputeAgent (SwarmBaseAgent subclass)
- `src/intelligence/swarm/agents/volume_prompts.py` - Versioned prompt registry with VP fields
- `src/intelligence/swarm/agents/volume_agent.py` - VolumeAgentComputeAgent (SwarmBaseAgent subclass)
- `services/swarm_dispatch_service.py` - Added CorrelationAgent + VolumeAgent to _agents registry
- `tests/unit/test_correlation_agent.py` - 10 tests: prompts, lead context, JSON parse, validation, get_lead_index
- `tests/unit/test_volume_agent.py` - 9 tests: prompts, volume profile, JSON parse, validation

## Decisions Made
- Used Python string concatenation for prompt template values in PROMPT_REGISTRY to satisfy ruff E501 line-length limit while preserving the multi-line prompt format for LLM readability
- Adopted `_fmt(val, spec)` pattern from skeptic_prompts.py for consistent numeric formatting across all agent prompts

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed ruff E501 line-length violations in prompt template strings**
- **Found during:** Task 1 (ruff check)
- **Issue:** Long lines in prompt template strings exceeded 100-char limit (lines 16, 50, 63, 65 in correlation_prompts; lines 15, 53, 66, 68 in volume_prompts)
- **Fix:** Used Python string concatenation (implicit join) for prompt template values, splitting long lines at natural sentence boundaries
- **Files modified:** src/intelligence/swarm/agents/correlation_prompts.py, src/intelligence/swarm/agents/volume_prompts.py
- **Verification:** ruff check passes with zero errors on all files
- **Committed in:** 516e7ec0 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Auto-fix necessary for lint compliance. No scope creep.

## Issues Encountered
None beyond the E501 deviation documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- SwarmDispatchService ready for Plan 03 to add more agents (same 2-line pattern)
- All 3 agents running in shadow mode, producing shadow recordings for future analysis
- Context enrichment pipeline validated: _find_lead_context + _extract_volume_profile working for all agents
- Systemd unit ready for deployment (after all agents registered)

---
*Phase: 066-skeptic-agent*
*Completed: 2026-04-24*

## Self-Check: PASSED

- All 6 created files verified present on disk
- Modified file (services/swarm_dispatch_service.py) verified present
- Task commit (516e7ec0) verified in git log
- No unintended file deletions in commit
- All 34 unit tests passing (19 new + 15 prior)
- ruff check clean on all files
