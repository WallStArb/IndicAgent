---
phase: 56
plan: "08"
subsystem: ml-core
tags: [ml, feature-extraction, shadow-recording, model-registry, training-data, no-train-serve-skew]
dependency_graph:
  requires: [56-03, 56-06]
  provides: [src/core/ml/extractor.py, src/core/ml/shadow.py, src/core/ml/registry.py, src/core/ml/training_data.py]
  affects: [SwarmBaseAgent (56-04), future swarm agents that call recorder.record()]
tech_stack:
  added: []
  patterns: [Pydantic v2 frozen model, asyncpg batch insert, structlog, TYPE_CHECKING import guard]
key_files:
  created:
    - src/core/ml/extractor.py
    - src/core/ml/shadow.py
    - src/core/ml/registry.py
    - src/core/ml/training_data.py
    - tests/unit/test_ml_core.py
  modified:
    - src/core/ml/__init__.py
decisions:
  - FeatureExtractor uses _safe() helper to gracefully handle None i-tier objects — no per-field null checks needed
  - ShadowRecorder breaks SQL column list across two lines to satisfy ruff E501 (100-char limit)
  - ModelRegistry.load_latest() lazy-imports mlflow to avoid import cost at module load
  - TrainingDataQuery exposes _NO_LOOKAHEAD_SQL and _BASE_SQL as class attributes for testability
metrics:
  duration_minutes: 5
  completed_date: "2026-04-10"
  tasks_completed: 4
  files_created: 5
  files_modified: 1
---

# Phase 56 Plan 08: ML Core (`src/core/ml/`) Summary

**One-liner:** Complete `src/core/ml/` package — `FeatureExtractor` (identical training/inference extraction), `ShadowRecorder` (async batch writes to `alpha_multiplier_shadow`), `ModelRegistry` (thin MLflow wrapper), and `TrainingDataQuery` (JOIN with no-lookahead guard).

## What Was Built

### FeatureExtractor (`src/core/ml/extractor.py`)
Two entry points with identical extraction logic — eliminates train/serve skew:
- `from_event(IntelligenceEvent) → FeatureVector` — real-time inference path, extracts from i1/i2/i3/i4/i5/i6/i7 tiers using `_safe()` helper
- `from_row(dict) → FeatureVector` — training/batch path, maps flattened DB column names to FeatureVector fields

Both paths produce identical FeatureVector for the same underlying data — verified by `test_extractor_from_event_same_result_from_row`.

### ShadowRecorder (`src/core/ml/shadow.py`)
Async batch writer for `alpha_multiplier_shadow` table:
- Accumulates rows in `_pending` list, flushes when `batch_size` reached (default 100)
- `flush()` public method for graceful SIGTERM drain
- Uses `ON CONFLICT (signal_id, agent_id) DO NOTHING` for idempotent writes
- Called by `AIBaseAgent` — zero per-swarm-agent boilerplate

### ModelRegistry (`src/core/ml/registry.py`)
Thin wrapper hiding the MLflow API behind 4 methods:
- `register()` — inserts to `ml_models` table, returns model_id UUID
- `load_latest()` — queries `ml_models` for production status, loads via `mlflow.pyfunc`
- `promote()` — sets status to `'production'` + timestamps `promoted_at`
- `revert()` — sets status to `'retired'`

### TrainingDataQuery (`src/core/ml/training_data.py`)
Labeled training data JOIN with strict no-lookahead enforcement:
- SQL enforces `f.ts < sl.activated_at` — features must predate signal activation
- Exposes `_NO_LOOKAHEAD_SQL` and `_BASE_SQL` as class attributes for test inspection
- Returns polars DataFrame; optional `regime` filter via `$5` parameter
- Only returns rows where `sl.outcome IS NOT NULL` (lifecycle-complete signals only)

### Package Init (`src/core/ml/__init__.py`)
Exports all 5 components: `FeatureVector`, `FeatureExtractor`, `ShadowRecorder`, `ModelRegistry`, `TrainingDataQuery`.

## Tests

6 tests in `tests/unit/test_ml_core.py`, all passing:
- `test_extractor_from_event_returns_feature_vector` — type + field value assertions
- `test_extractor_from_event_same_result_from_row` — no train/serve skew verification
- `test_extractor_returns_none_for_missing_fields_gracefully` — None i-tiers don't crash
- `test_shadow_recorder_record_queues_row` — batch_size=1 triggers immediate flush
- `test_shadow_recorder_writes_correct_columns` — tuple column ordering verified
- `test_training_data_query_enforces_no_lookahead` — SQL constant inspection

## Commits

| Hash | Message |
|------|---------|
| 57f8c995 | feat(56-08): add FeatureExtractor — identical training/inference extraction |
| 66ad8d33 | feat(56-08): add ShadowRecorder — batched async shadow prediction writes |
| aac0fee4 | feat(56-08): add ModelRegistry + TrainingDataQuery, finalize src/core/ml/ package |
| 65257059 | style(56-08): lint + black fixes for src/core/ml/ |

## Deviations from Plan

None — plan executed exactly as written. SQL column list in `shadow.py` split across two lines (deviation from plan's single-line version) to satisfy ruff E501 line-length limit — functionally identical.

## Known Stubs

None. All components have real implementations. `ModelRegistry.load_latest()` returns `None` when no production model exists — this is correct behavior (caller must handle), not a stub.

## Threat Flags

None. No new network endpoints, auth paths, or external trust boundaries introduced. `ModelRegistry` connects to MLflow tracking URI (localhost:5000 default) — internal only.

## Self-Check: PASSED

Files exist:
- src/core/ml/extractor.py — FOUND
- src/core/ml/shadow.py — FOUND
- src/core/ml/registry.py — FOUND
- src/core/ml/training_data.py — FOUND
- tests/unit/test_ml_core.py — FOUND

Commits verified:
- 57f8c995 — FOUND
- 66ad8d33 — FOUND
- aac0fee4 — FOUND
- 65257059 — FOUND

All 6 tests: PASSED
