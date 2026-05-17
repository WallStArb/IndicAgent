---
phase: "085"
plan: "01"
subsystem: persistence-schemas
tags: [pydantic, schemas, lineage, signal-metrics, discriminated-union]
dependency_graph:
  requires: []
  provides:
    - src/core/ai/lineage.py::LineageEvent
    - src/intelligence/schemas.py::SignalMetricsEvent
    - src/intelligence/schemas.py::MetricsComputedEvent
    - src/intelligence/schemas.py::ICComputedEvent
    - src/intelligence/schemas.py::MetricsDQFailureEvent
  affects:
    - services/lineage_writer_agent.py (Plan 04 sets payload_model = LineageEvent)
    - services/signal_metrics_writer_agent.py (Plan 04 sets payload_model = SignalMetricsEvent)
tech_stack:
  added: []
  patterns:
    - Pydantic discriminated union with Annotated + Field(discriminator=)
    - Co-located schema with sole producer (D-04 pattern)
key_files:
  created: []
  modified:
    - src/core/ai/lineage.py
    - src/intelligence/schemas.py
decisions:
  - "LineageEvent placed in lineage.py alongside LineageRecorder (D-04: schema lives with sole producer)"
  - "SignalMetricsEvent uses Pydantic Annotated discriminated union; X|Y syntax per ruff UP007"
  - "All three variant models use ConfigDict(extra='forbid') to reject unknown fields at validation boundary"
metrics:
  duration_minutes: 15
  tasks_completed: 2
  tasks_total: 2
  files_modified: 2
  completed_date: "2026-05-17"
---

# Phase 085 Plan 01: Persistence Payload Schemas Summary

**One-liner:** Pydantic payload schemas for lineage and signal-metrics writers - `LineageEvent` in `lineage.py` and `SignalMetricsEvent` discriminated union in `schemas.py`.

## What Was Built

Two Pydantic payload schemas that Plan 04 writer migrations depend on to get free DLQ routing and validation from `BaseWriterAgent`.

### Task 1: LineageEvent (lineage.py)

Added `LineageEvent(BaseModel)` to `src/core/ai/lineage.py` immediately above `LineageRecorder`. All 10 fields derived exactly from `LineageRecorder.record()` signature:

- `ts: str`, `signal_id: str`, `event_type: str`, `source: str` (required)
- `dag_order: int | None`, `multiplier: float | None`, `is_shadow: bool = True`
- `symbol: str = ""`, `tf: str = ""`
- `metadata: dict = Field(default_factory=dict)` — avoids mutable default

`ConfigDict(extra="forbid")` rejects unknown fields. Co-located with `LineageRecorder` per D-04.

### Task 2: SignalMetricsEvent discriminated union (schemas.py)

Added three variant models and the union to `src/intelligence/schemas.py`:

- `MetricsComputedEvent` - fields from `_handle_metrics_computed()`: track, setup_plugin, tf, regime_type, window_days, symbol, n, n_outliers, nullable metric fields, computed_at
- `ICComputedEvent` - fields from `_handle_ic_computed()`: setup_plugin, tf, regime_type, window_days, symbol, n, ic, p_value, is_significant, computed_at
- `MetricsDQFailureEvent` - fields from `_handle_dq_failure()`: signal_id, reason_code, and nullable entry_price/stop_loss/pnl_r/direction/hmm_regime/setup_plugin

Discriminated union uses `Annotated[M1 | M2 | M3, Field(discriminator="event_type")]` syntax.

## Verification

- `LineageEvent` validates valid payloads, raises `ValidationError` on missing required fields
- `SignalMetricsEvent` TypeAdapter correctly dispatches to variant by `event_type` discriminator
- Unknown `event_type` raises `ValidationError`
- 3260 unit tests passed, 0 regressions
- Ruff clean on both modified files

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | `188b4e9e` | feat(085-01): add LineageEvent Pydantic model to lineage.py |
| Task 2 | `63d3a787` | feat(085-01): add SignalMetricsEvent discriminated union to schemas.py |

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check

Files exist:
- `/home/bg/dev/indicagent/.claude/worktrees/agent-acf85c6f149a7426d/src/core/ai/lineage.py` - contains `class LineageEvent(BaseModel)`
- `/home/bg/dev/indicagent/.claude/worktrees/agent-acf85c6f149a7426d/src/intelligence/schemas.py` - contains `SignalMetricsEvent`

Commits: `188b4e9e` and `63d3a787` on branch `worktree-agent-acf85c6f149a7426d`.

## Self-Check: PASSED
