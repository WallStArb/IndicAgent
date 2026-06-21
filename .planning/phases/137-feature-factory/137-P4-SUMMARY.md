---
phase: 137-feature-factory
plan: 4
subsystem: feature-writer
tags: [persistence, kafka, timescaledb, feature-vectors, basewriter]
dependency_graph:
  requires: [137-P1, 137-P2]
  provides: [feature_writer-persists-feature_vectors, FeatureVector-dataclass, topic_feature_vectors]
  affects: [services/feature_writer.py, src/intelligence/schemas.py, src/core/stream_keys.py]
tech_stack:
  added: []
  patterns: [BaseWriter-batch-flush, consumer-group-rename, 42-column-insert]
key_files:
  created: []
  modified:
    - services/feature_writer.py
    - src/intelligence/schemas.py
    - src/core/stream_keys.py
    - tests/unit/services/test_feature_writer.py
decisions:
  - consumer group renamed to feature_vector_writer_group to prevent offset collision (T1)
  - FeatureVector/FeatureVectorRecord added to schemas.py as P2 dependency was missing
  - topic_feature_vectors/dlq added to stream_keys.py as P2 dependency was missing
metrics:
  duration: ~25m
  completed: 2026-06-20
  tasks: 2
  files: 4
---

# Phase 137 Plan 4: Feature Writer Retarget Summary

**One-liner:** Retarget feature_writer from intelligence_features to feature_vectors via 42-column INSERT, renamed consumer group, and FeatureVectorRecord deserialization.

## What Was Built

`services/feature_writer.py` retargeted from `intelligence_features` to the v3.0 `feature_vectors` hypertable. All proven BaseWriter infrastructure (batching, flush loop, DLQ, OTel metrics, health monitor) preserved unchanged. Only the topic, schema, INSERT SQL, consumer group, and parse/insert logic changed.

Also added the P2 transport contracts (FeatureVector dataclass, FeatureVectorRecord, topic functions) which were missing from their upstream wave - these were required blocking dependencies for P4 to function.

## Decisions Made

1. **Consumer group renamed to `feature_vector_writer_group`**: avoids offset collision with the old `feature_writer_group` which has committed offsets on `intelligence.journal`. New group starts at `earliest` on `intelligence.feature_vectors` with no prior state.

2. **FeatureVector has 36 fields, not 35**: The plan docstrings say "35 primitives" but the actual field list (14+4+7+3+5+3) sums to 36. The critical constraints in the P4 prompt explicitly state "FeatureVector has exactly 36 float fields (not 35)" - the 36-field implementation is correct.

3. **P2 artifacts bootstrapped in P4**: `FeatureVector`/`FeatureVectorRecord` dataclasses and `topic_feature_vectors`/`topic_feature_vectors_dlq` stream key functions were not present (P2 hadn't run). Added them inline as a Rule 3 auto-fix (blocking dependency). These are pure additive changes with no behavior risk.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Missing Dependency] P2 artifacts not present**
- **Found during:** Task 1 start (importing FeatureVector failed)
- **Issue:** `FeatureVector`, `FeatureVectorRecord` not in `schemas.py`; `topic_feature_vectors` not in `stream_keys.py` - P2 (wave 1) had not executed before P4 (wave 3)
- **Fix:** Added both dataclasses to `schemas.py` (end of file, after existing models) and both topic functions to `stream_keys.py` (after `topic_intelligence_journal` + DLQ block)
- **Files modified:** `src/intelligence/schemas.py`, `src/core/stream_keys.py`
- **Commit:** `39102c92`

**2. [Rule 3 - Missing Dependency] `.venv` symlink needed for pre-commit hook in worktree**
- **Found during:** First commit attempt
- **Issue:** Pre-commit hook uses `${REPO_ROOT}/.venv/bin/ruff` where REPO_ROOT resolves to the worktree path - no `.venv` there
- **Fix:** Created symlink `.venv -> /home/bg/dev/indicagent/.venv` in worktree root
- **Impact:** One-time setup, no code change

## Acceptance Criteria Verification

- `services/feature_writer.py` contains `INSERT INTO feature_vectors`: PASS
- No `intelligence_features`, `BarIntelligenceRecord`, `topic_cross_asset`, `_build_expiry_map`, `_process_cross_asset_message` in `feature_writer.py`: PASS (grep returns 0)
- `CONSUMER_GROUP == "feature_vector_writer_group"`: PASS
- `topics_consumed` returns list containing `topic_feature_vectors` output: PASS
- `_INSERT_FEATURE_VECTOR_SQL` has exactly 42 placeholders: PASS
- `_record_to_insert_params` returns 42-tuple: PASS
- `ruff check services/feature_writer.py` exits 0: PASS
- `pytest tests/unit/services/test_feature_writer.py -q` exits 0: PASS (21 passed)
- No `BarIntelligenceRecord`, `_build_expiry_map`, `intelligence_features` in test file: PASS

## Self-Check: PASSED

All files exist at expected paths. Both task commits verified in git log.
