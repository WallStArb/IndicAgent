---
phase: 138-ic-engine-forward-returns
plan: 01
subsystem: feature-vector-write-stack
tags: [feature-vectors, schema, migration, data-quality, observability, naming]
dependency_graph:
  requires: []
  provides: [feature_vectors_70col_schema, validate_feature_vector, feature_factory_version, momentum_z_slow, momentum_reversal_z, quarter_position, days_to_month_end, batch_job_checkpoints]
  affects: [backfill_feature_factory, feature_vector_writer, intelligence_pipeline, IC_engine]
tech_stack:
  added: [bar_close_ts_computation, _TF_SECONDS_mapping, validate_feature_vector, FEATURE_FACTORY_VERSION_versioning]
  patterns: [content-key-versioning, nan-guard-before-insert, scale-name-columns, canonical-persistence-module]
key_files:
  created: [production/migrations/159_foundation_hardening.sql]
  modified:
    - src/intelligence/schemas.py
    - src/intelligence/feature_factory.py
    - src/intelligence/features/feature_vector_persistence.py
    - services/feature_vector_writer.py
    - services/backfill_feature_factory.py
    - services/intelligence_pipeline.py
    - tests/unit/services/test_feature_vector_writer.py
    - tests/unit/services/test_feature_vector_writer_column_mapping.py
    - tests/unit/services/test_backfill_feature_factory.py
    - tests/unit/services/test_context_writer.py
    - tests/unit/test_feature_factory.py
    - tests/unit/intelligence/test_feature_factory_p7.py
    - tests/unit/pipeline/pipeline_helpers.py
decisions:
  - "Calendar constants (91.25 days/quarter, calendar.monthrange) are statistical constants, not APR parameters"
  - "validate_feature_vector() returns list of bad field names; caller decides action (ValueError in live path, skip+log in batch)"
  - "feature_factory_version column at $6 in INSERT (between pipeline_version and regime) per plan canonical order"
  - "bar_close_ts computed in persistence module, not caller site, for single source of truth"
  - "Pre-existing orchestrator test failures documented in deferred-items.md; pipeline_helpers.py updated with missing attrs to unblock AttributeErrors"
metrics:
  duration: ~90min
  completed: 2026-06-22
  tasks: 6
  files: 13
---

# Phase 138 Plan 01: Foundation Hardening Summary

Hardened the feature vector write stack before backfill runs. Addressed 12 council-review findings across data integrity, algorithm version tracking, observability, compute correctness, and schema completeness.

## One-Liner

NaN guard + feature_factory_version versioning + 7 new FeatureVector fields (momentum_z_slow/reversal, calendar, cross-sectional) + migration 159 expanding feature_vectors to 70 columns + 70-param canonical INSERT tuple.

## What Was Done

### Task 1: Code Quality (Findings 4, 5, 6) — commit c3d49e47

Three targeted non-logic fixes in `feature_vector_writer.py` and `schemas.py`:
- `FeatureVector` moved to module-level import (was inside `_parse_payload()`)
- `import time` added at module level; all `__import__("time").perf_counter()` replaced
- `FeatureVector` docstring field-group breakdown corrected (was summing to 52, now 54 with Volatility group added)

### Task 2: NaN/Inf Validator + Per-Symbol Counter (Findings 1, 3) — commit d0de167f

- `validate_feature_vector(vector) -> list[str]` added to `feature_vector_persistence.py`
- Called in `feature_vector_to_insert_params()` before building the tuple; raises `ValueError` listing bad fields
- `feature_writer_rows_parsed_by_symbol_tf_total` counter added to `FeatureVectorWriter.__init__`, incremented at parse time with `{symbol, tf}` labels

### Task 3: feature_factory_version Throughout (Findings 2, 10) — commit 94bb0bc1

- `FEATURE_FACTORY_VERSION = "1.0.0"` constant in `feature_factory.py`
- `FeatureVectorRecord` gains `feature_factory_version: str` field (Kafka wire envelope)
- Content-key SHA-256 formula updated: `SHA-256(symbol|tf|bar_ts_ns|pipeline_version|feature_factory_version)`
- Both write paths (`feature_vector_writer`, `backfill_feature_factory`) pass the constant

### Task 4: Naming Remediation + 7 New FeatureVector Fields (Findings 9, 11, 12) — commit 844ab2b7

Naming remediation:
- `momentum_z_5` → `momentum_z_fast`, `momentum_z_20` → `momentum_z_mid` (scale names, consistent with rsi_fast/mid/slow)
- `FeatureFactoryConfig`: `momentum_window_short/long` → `momentum_window_fast/mid`; added `momentum_window_slow`

New FeatureVector fields (61 total):
- `momentum_z_slow`: 60-bar return z-score (APR: `feature.momentum.window_slow`, default 60)
- `momentum_reversal_z`: 1-bar log return z-score (short-term reversal signal)
- `quarter_position`: position within calendar quarter [0, 1]; earnings/rebalancing cycle
- `days_to_month_end`: normalized days remaining to month end [0, 1]
- `momentum_rank_z`, `volume_rank_z`, `volatility_rank_z`: Optional cross-sectional (None until Phase 139)

`FeatureFactory.compute()` computes all 4 non-Optional fields deterministically.

### Task 5: Migration 159 (Findings 2, 7, 8, 9, 11, 12) — commit 9cad452f

`production/migrations/159_foundation_hardening.sql` applied to DB:
- Renamed `momentum_z_5` → `momentum_z_fast`, `momentum_z_20` → `momentum_z_mid`
- APR keys renamed: `feature.momentum.window_short/long` → `window_fast/mid`
- New APR key: `feature.momentum.window_slow = 60` inserted
- 9 new columns added: `feature_factory_version` (NOT NULL DEFAULT '1.0.0'), `bar_close_ts`, `momentum_z_slow`, `momentum_reversal_z`, `quarter_position`, `days_to_month_end`, `momentum_rank_z`, `volume_rank_z`, `volatility_rank_z`
- `batch_job_checkpoints` table created: `job_key TEXT PK, state JSONB NOT NULL DEFAULT '{}', updated_at TIMESTAMPTZ`
- `feature_vectors` now has 70 columns total

### Task 6: 70-Param INSERT Tuple + bar_close_ts (Findings 7, all) — commit e0e42a30

`feature_vector_to_insert_params()` expanded from 61 to 70 params:
- `_TF_SECONDS` mapping and `_compute_bar_close_ts()` added to persistence module
- `feature_factory_version` promoted to column `$6` (was arg-only in content-key)
- `bar_close_ts` computed as `bar_ts + TF_duration` at `$63`
- 4 computed fields at `$64-$67`, 3 cross-sectional nullables at `$68-$70`
- INSERT SQL updated to 70 placeholders; psycopg2 variant regenerated
- `_REQUIRED_COLUMNS` spot-check set updated with migration 159 columns
- All test tuple length and index assertions updated

## Council Review Findings Addressed

| Finding | Description | Status |
|---------|-------------|--------|
| F1 | NaN/Inf guard before INSERT | DONE — `validate_feature_vector()` in persistence module |
| F2 | feature_factory_version tracking | DONE — constant, wire field, content-key, column |
| F3 | Per-symbol observability counter | DONE — `feature_writer_rows_parsed_by_symbol_tf_total` |
| F4 | FeatureVector inline import in function | DONE — moved to module level |
| F5 | `__import__("time")` anti-pattern | DONE — `import time` at module level |
| F6 | FeatureVector docstring incorrect | DONE — corrected to 54 fields with all groups |
| F7 | bar_close_ts for forward returns | DONE — column added, computed in persistence |
| F8 | batch_job_checkpoints table | DONE — created in migration 159 |
| F9 | Cross-sectional nullable fields | DONE — 3 Optional fields added, None until Phase 139 |
| F10 | feature_factory_version in content-key | DONE — included in SHA-256 |
| F11 | Multi-scale momentum features | DONE — momentum_z_slow + momentum_reversal_z |
| F12 | Calendar cycle features | DONE — quarter_position + days_to_month_end |

## Final FeatureVector Field Count

61 fields total:
- 54 original fields (renamed 2: momentum_z_fast, momentum_z_mid)
- 4 new computed: momentum_z_slow, momentum_reversal_z, quarter_position, days_to_month_end
- 3 new Optional cross-sectional: momentum_rank_z, volume_rank_z, volatility_rank_z

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical Functionality] Test infrastructure gaps in pipeline_helpers.py**
- **Found during:** Task 4 verification
- **Issue:** `make_agent()` missing `_feature_factory_config`, `_feature_caches`, `_kafka_producer`, `_background_tasks`, `_bar_e2e_latency` attributes — AttributeError cascade in orchestrator tests
- **Fix:** Added all missing attributes to `make_agent()` with appropriate defaults/mocks
- **Files modified:** `tests/unit/pipeline/pipeline_helpers.py`
- **Commit:** 844ab2b7

**2. [Rule 1 - Bug] context_writer test reading SQL from writer source directly**
- **Found during:** Task 4 verification
- **Issue:** `test_feature_writer_insert_includes_ctx_column` read `feature_vector_writer.py` source and asserted `$1` is present; after SQL extraction to `feature_vector_persistence.py`, the `$1` is no longer in the writer source
- **Fix:** Updated test to check the persistence module (canonical source of truth) for `$1` and `feature_vector_id`
- **Files modified:** `tests/unit/services/test_context_writer.py`
- **Commit:** 844ab2b7

### Pre-existing Failures (Out of Scope)

4 tests in `tests/unit/pipeline/test_orchestrator_integration.py` were failing before 138-P1 started (confirmed by git stash test). They test routing and state propagation logic that doesn't match the current `_process_bar_compute` implementation. Documented in `deferred-items.md`. Pipeline_helpers.py was updated to unblock AttributeErrors, but the remaining semantic assertion failures are pre-existing.

## Self-Check

All 6 task acceptance criteria verified:
- `validate_feature_vector()` defined and called before INSERT
- `FEATURE_FACTORY_VERSION = "1.0.0"` in `feature_factory.py`
- Content-key includes `feature_factory_version` (different versions → different UUIDs)
- FeatureVector has 61 fields (7 new)
- Migration 159 applied: `feature_vectors` has 70 columns, `batch_job_checkpoints` exists
- `feature_vector_to_insert_params()` returns 70-element tuple
- All unit tests pass except 4 pre-existing orchestrator failures
