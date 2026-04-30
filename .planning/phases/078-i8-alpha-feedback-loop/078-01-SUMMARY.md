---
phase: 078-i8-alpha-feedback-loop
plan: "01"
subsystem: alpha-swarm
tags:
  - lineage-recorder
  - pool-fix
  - segment-key
  - lead-map
  - tdd

dependency_graph:
  requires:
    - "073-06: LineageRecorder + BaseGroupService infrastructure"
    - "073-05: BaseGroupService._setup() pool creation"
  provides:
    - "signal_lineage rows with event_type=agent_prediction for Plan 03 graduation loop"
    - "numeric segment_key (e.g. 1.5m) for per-regime graduation"
  affects:
    - services/alpha_swarm_agent.py
    - src/core/ai/lineage.py (consumed, not modified)

tech_stack:
  added: []
  patterns:
    - "LineageRecorder Kafka-first batch recording"
    - "_LEAD_MAP + _resolve_lead() for ES->NQ lead resolution"
    - "TDD RED/GREEN with __new__ bypass pattern for BaseGroupService subclass"

key_files:
  created:
    - tests/unit/service_tests/test_alpha_swarm_agent.py
  modified:
    - services/alpha_swarm_agent.py

decisions:
  - "LineageRecorder.record() is synchronous (batch buffer); flush() is async — record() called inline, flush() called in _teardown()"
  - "_LEAD_MAP simplified to ES->NQ only (plan requirement); _LEAD_INDEX_MAP with full multi-symbol mapping replaced"
  - "segment_key stored in metadata JSONB of lineage row (not a top-level field), consistent with LineageRecorder.record() signature"
  - "AIContextCache.build() called with frozenset() (no tier requirement change in this plan) — i4 enrichment from enriched context passed to _record_swarm_result"
  - "_find_lead_context preserved for CorrelationAgent lead enrichment; _LEAD_INDEX_MAP removed, _LEAD_MAP + _resolve_lead() used instead"
  - "Comments referencing removed classes cleaned from docstrings to satisfy grep-based acceptance criteria (grep -c counts comment lines)"

metrics:
  duration: "~15 minutes"
  completed: "2026-04-30"
  tasks_completed: 2
  files_modified: 2
  files_created: 1
  tests_added: 13
---

# Phase 78 Plan 01: Alpha Swarm LineageRecorder Migration Summary

Single-file refactor of `services/alpha_swarm_agent.py` — replaces dual ShadowRecorder + TransformRecorder write path with a single LineageRecorder writing `agent_prediction` events to `topic_signal_lineage()`. Fixes pool leak (double asyncpg.create_pool), removes volume profile stub, and hardens segment key construction to use numeric hmm_regime prefix.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 (RED) | Failing tests for LineageRecorder migration | 417c49ba | tests/unit/service_tests/test_alpha_swarm_agent.py (created) |
| 1+2 (GREEN) | LineageRecorder + segment key + lead map implementation | d196d96a | services/alpha_swarm_agent.py, tests/unit/service_tests/test_alpha_swarm_agent.py |

## What Was Built

**`services/alpha_swarm_agent.py` refactored:**

- `_setup()` calls `super()._setup()` exactly once; no second `asyncpg.create_pool` call (pool from `BaseGroupService`)
- Single `LineageRecorder(producer=self._producer, env_name=self.env_name)` stored as `self._lineage`
- `_record_swarm_result()` calls `self._lineage.record(event_type="agent_prediction", source=agent_id, ...)` — segment_key stored in `metadata` JSONB
- Segment key: `f"{hmm_regime}.{timeframe}"` — numeric prefix, never `"unknown.*"`
- Missing `hmm_regime=None` logs `kind="missing_hmm_regime"` warning and returns without recording (T-78-02 mitigation)
- `_teardown()` calls `await self._lineage.flush()` before `super()._teardown()`
- `_LEAD_MAP = {"ES": "NQ"}` + `_resolve_lead(symbol)` at module level; replaces `_LEAD_INDEX_MAP` inline conditionals
- `_extract_volume_profile()` removed; `_enrich_context()` no longer sets `volume_profile` field

**`tests/unit/service_tests/test_alpha_swarm_agent.py` created (13 tests):**

- Module import assertions: ShadowRecorder/TransformRecorder absent, LineageRecorder present, `_extract_volume_profile` absent
- `_record_swarm_result` publishes to `topic_signal_lineage("test")` with `event_type="agent_prediction"`
- Segment key carries numeric hmm_regime prefix
- Missing regime logs warning and publishes nothing
- `_LEAD_MAP` constant exists with `ES->NQ`; `_resolve_lead` behaves correctly for ES, NQ, and unmapped symbols
- Exact segment_key `"1.5m"` for regime=1, tf="5m"

## Deviations from Plan

**1. [Rule 1 - Bug] LineageRecorder.record() signature mismatch**
- **Found during:** Task 1 (GREEN)
- **Issue:** Plan action specified kwargs `agent_name=`, `prediction=`, `features_snapshot=`, `timestamp=` but actual `LineageRecorder.record()` signature uses `source:str`, `multiplier:float|None`, `metadata:dict|None`, `symbol:str`, `tf:str`
- **Fix:** Mapped `agent_name -> source`, `prediction/multiplier -> multiplier`, `features_snapshot + segment_key -> metadata JSONB`, omitted `timestamp` (LineageRecorder adds its own `ts`)
- **Files modified:** services/alpha_swarm_agent.py
- **Commit:** d196d96a

**2. [Rule 1 - Bug] grep -c counts comment lines as matches**
- **Found during:** Task 1 verification
- **Issue:** Acceptance criteria uses `grep -c "ShadowRecorder|TransformRecorder" | grep -q "^0$"` but grep counts comment/docstring occurrences too
- **Fix:** Removed all comment references to forbidden class names from docstrings; only the live Python module-namespace test verifies the behavioral contract
- **Files modified:** services/alpha_swarm_agent.py
- **Commit:** d196d96a

**3. [Note] _LEAD_INDEX_MAP removed**
- **Found during:** Task 2
- **Issue:** Existing `_LEAD_INDEX_MAP` had broader mappings (HO->CL, RB->CL, GC, ZN family) that the plan's `_LEAD_MAP` does not include
- **Decision:** Per plan spec `_LEAD_MAP = {"ES": "NQ"}` only; the `_find_lead_context()` method uses `_resolve_lead()` internally. The old `_LEAD_INDEX_MAP` is no longer referenced and was removed. Future plans can extend `_LEAD_MAP` if multi-symbol lead resolution is needed.

## TDD Gate Compliance

- RED gate: commit 417c49ba (`test(078-01):`) — 13 tests collected, 1 immediately failed
- GREEN gate: commit d196d96a (`feat(078-01):`) — 13/13 tests pass
- REFACTOR gate: not needed (no structural cleanup required beyond comment cleanup in GREEN)

## Known Stubs

None — `_extract_volume_profile()` was already returning `None` (stub) and is now fully removed.

## Threat Flags

None — no new network endpoints or auth paths introduced. `LineageRecorder` publishes to an existing Kafka topic (`topic_signal_lineage`) already defined in `stream_keys.py`.

## Self-Check

Files created/modified exist:
- services/alpha_swarm_agent.py — exists, 210 lines
- tests/unit/service_tests/test_alpha_swarm_agent.py — exists, 246 lines

Commits exist:
- 417c49ba — test RED gate
- d196d96a — feat GREEN gate

## Self-Check: PASSED
