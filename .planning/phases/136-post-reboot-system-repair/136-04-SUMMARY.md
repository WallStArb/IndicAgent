---
phase: 136-post-reboot-system-repair
plan: "04"
subsystem: feature_writer
tags: [schema-guard, jsonb-dedup, ctf, data-integrity]
dependency_graph:
  requires: []
  provides: [feature_writer_schema_preflight, ctf_jsonb_exclusion]
  affects: [feature_writer, run_historical_pipeline, intelligence_features]
tech_stack:
  added: []
  patterns: [startup-preflight-check, pydantic-model_dump-exclude]
key_files:
  created: []
  modified:
    - services/feature_writer.py
    - production/scripts/run_historical_pipeline.py
decisions:
  - "table_schema='public' filter mandatory in information_schema query to avoid false negatives from same-named tables in other schemas"
  - "CTF exclusion applied only to cross_timeframe_context ($14); top-level columns ($34-$37) unaffected"
metrics:
  duration_minutes: 5
  completed_date: "2026-06-18"
  tasks_completed: 2
  files_modified: 2
---

# Phase 136 Plan 04: Feature Writer Schema Guard and CTF JSONB Dedup Summary

One-liner: Startup pre-flight raises RuntimeError on missing Phase-130 CTF columns; both live and replay JSONB write paths now exclude the four CTF keys from cross_timeframe_context.

## Tasks Completed

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | Add _verify_schema() pre-flight | 79723cd5 | services/feature_writer.py |
| 2 | Exclude CTF keys from both JSONB write paths | 3bfe76ce | services/feature_writer.py, production/scripts/run_historical_pipeline.py |

## What Was Built

**Task 1 - _verify_schema() pre-flight (2a)**

Added `_REQUIRED_COLUMNS` frozenset at module level containing the four Phase-130 CTF columns (`ctf_score`, `ctf_trend_alignment`, `ctf_structure_alignment`, `ctf_regime_agreement`).

Added `async def _verify_schema(self)` that queries `information_schema.columns WHERE table_name = 'intelligence_features' AND table_schema = 'public'`, computes the set difference against `_REQUIRED_COLUMNS`, and raises `RuntimeError` with a message naming `sorted(missing)` and referencing migration 130 if any columns are absent.

Called `await self._verify_schema()` in `_setup()` after `_connect_database()` and before `_setup_kafka_clients()`. This converts a silent multi-hour data loss (migration not applied, buffer overflow, data dropped) into a loud startup crash before any Kafka subscription begins.

**Task 2 - CTF key exclusion at both JSONB build sites (2b)**

In `services/feature_writer.py` at the `$14 cross_timeframe_context` build, changed `event.i6.model_dump(exclude_none=True)` to add `exclude={"ctf_score", "ctf_trend_alignment", "ctf_structure_alignment", "ctf_regime_agreement"}`. The four CTF values are still written to their dedicated top-level columns ($34-$37); only the JSONB duplication is eliminated.

In `production/scripts/run_historical_pipeline.py` at the replay cross_timeframe_context build (wrapped in `_sanitize_for_json` / `json.dumps`), applied the identical exclusion set. No other `model_dump` calls (i1/i3/i4/i5/smc/i2) were modified in either file.

This makes Migration 130 Statement 3 durable - live writes no longer reintroduce the duplicate keys immediately after the cleanup migration runs.

## Verification

- `ruff check` passes on both files
- `ast.parse` passes on both files
- `pytest tests/unit/ -q -k "feature_writer or historical"` - 131 passed, 4786 deselected
- All 8 pre-commit hooks passed on both commits

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check

### Files exist
- `services/feature_writer.py` - present, contains `_verify_schema` and `_REQUIRED_COLUMNS` and `exclude={"ctf_score"` at line 230
- `production/scripts/run_historical_pipeline.py` - present, contains `exclude={"ctf_score"` at line 752

### Commits exist
- 79723cd5 - feat(136-04): add _verify_schema() pre-flight to feature_writer
- 3bfe76ce - fix(136-04): exclude CTF keys from cross_timeframe_context JSONB in both write paths

## Self-Check: PASSED
