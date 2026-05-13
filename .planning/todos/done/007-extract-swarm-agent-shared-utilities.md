---
name: Extract swarm agent shared utilities
priority: low
created: 2026-04-24
status: pending
trigger: Adding a 4th+ agent to SwarmDispatchService
---

# Extract Swarm Agent Shared Utilities

## Problem

Phase 66 shipped 3 swarm agents (Skeptic, Correlation, Volume) with correct but duplicated code across all agent + prompt files:

- `_DIRECTION_LABELS` dict — in all 3 prompt files
- `_LEAD_INDEX_MAP` dict — in `correlation_prompts.py` AND `swarm_dispatch_service.py`
- `_fmt()` helper — in `skeptic_prompts.py` and `volume_prompts.py`
- `_JSON_BLOCK_RE` regex — in all 3 agent files
- `_parse_*_response()` / `_validate_*_fields()` — near-identical in all 3 agent files
- `_SYSTEM_MESSAGE` pattern — near-identical in all 3 agent files

## Solution

Create `src/intelligence/swarm/agents/shared.py` containing:

1. `DIRECTION_LABELS` constant
2. `LEAD_INDEX_MAP` constant (imported by both `correlation_prompts.py` and `swarm_dispatch_service.py`)
3. `fmt_field(val, spec)` formatting helper
4. `JSON_BLOCK_RE` compiled regex
5. `parse_llm_json(raw)` — generic JSON parser with preamble fallback
6. `validate_agent_fields(data)` — generic field validator with clamping
7. `make_system_message(agent_role)` — factory for system messages

Then update all 3 agents + 3 prompt files to import from shared module.

## Trigger

When adding a 4th agent to `SwarmDispatchService._agents` — that's the point where copy-paste becomes a maintenance liability. Before that, the duplication is harmless and consistent.

## Scope

- New file: `src/intelligence/swarm/agents/shared.py`
- Modify: 3 agent files, 3 prompt files, `swarm_dispatch_service.py`
- Tests: extract shared test helpers, update existing tests
