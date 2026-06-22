---
phase: 138-ic-engine-forward-returns
plan: "00"
subsystem: database
tags: [timescaledb, uuid, sha256, content-key, feature-vectors, backfill, batch-writer]

# Dependency graph
requires:
  - phase: 137-feature-factory
    provides: feature_vectors hypertable schema (60 columns, 54 typed float features)
provides:
  - feature_vector_id UUID column on feature_vectors (content-key, idempotent across replays)
  - FeatureVectorWriter service (renamed from FeatureWriter, 61-param INSERT)
  - Identical SHA-256 content-key formula in live path and batch backfill path
  - Migration 158 applied to TimescaleDB
affects:
  - 138-P1 (IC engine tables migration numbers shifted 157->159, 158->160)
  - Any future phase reading feature_vectors (content-key enables dedup + replay idempotency)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Content-key UUID: SHA-256(symbol|tf|bar_ts_ns|pipeline_version)[:32] cast to uuid.UUID"
    - "TimescaleDB hypertable unique index workaround: non-unique partial index; uniqueness at app layer"
    - "APR-backed batch params via cfg.get_sync() in _load_apr_config()"
    - "point_gauge() factory from observability/metrics.py (never raw _meter.create_gauge())"
    - "Log event taxonomy: feature_vector_writer.<event>"

key-files:
  created:
    - production/migrations/158_feature_vector_id.sql
    - services/feature_vector_writer.py
    - tests/unit/services/test_feature_vector_writer.py
    - tests/unit/services/test_feature_vector_writer_column_mapping.py
    - tests/unit/services/test_feature_vector_writer_config.py
  modified:
    - services/backfill_feature_factory.py
    - services/service_auditor.py
    - tests/unit/services/test_backfill_feature_factory.py
    - tests/unit/services/test_context_writer.py
    - tests/unit/services/test_service_auditor.py
    - tests/unit/intelligence/test_feature_factory_p7.py
    - .planning/phases/138-ic-engine-forward-returns/138-P1-PLAN.md
    - .planning/phases/138-ic-engine-forward-returns/138-P2-PLAN.md
    - .planning/phases/138-ic-engine-forward-returns/138-P3-PLAN.md
    - .planning/phases/138-ic-engine-forward-returns/138-P4-PLAN.md

key-decisions:
  - "Non-unique partial index instead of UNIQUE: TimescaleDB hypertables cannot carry a unique index unless the partitioning column (bar_ts) is included; SHA-256 collision resistance makes app-layer uniqueness sufficient"
  - "feature_vector_id as first column ($1) in 61-param INSERT: positional binding clarity, matches column order in CREATE TABLE"
  - "bar_ts_ns computed as int(bar_ts.timestamp() * 1e9) to avoid sub-nanosecond drift across Python runtimes"
  - "_TARGET_TFS renamed _TARGET_TIMEFRAMES and coverage_gate renamed coverage_threshold in backfill_feature_factory for consistent terminology"
  - "Migration 158 allocated for feature_vector_id; P1 migrations bumped to 159/160 to avoid collision"

patterns-established:
  - "Content-key UUID pattern: module-level pure function _make_feature_vector_id() returns deterministic uuid.UUID; same function or equivalent used in all write paths"
  - "61-param tuple: _record_to_insert_params() returns fixed-length tuple; column-mapping tests pin exact indices"

requirements-completed: []

# Metrics
duration: 90min
completed: 2026-06-22
---

# Phase 138 Plan 00: Feature Vector ID and FeatureVectorWriter Summary

**SHA-256 content-key UUID added to feature_vectors (migration 158), FeatureWriter renamed to FeatureVectorWriter with 61-param INSERT, identical key formula in live and batch paths**

## Performance

- **Duration:** ~90 min
- **Started:** 2026-06-22T12:00:00Z
- **Completed:** 2026-06-22T14:40:00Z
- **Tasks:** 5
- **Files modified:** 19

## Accomplishments

- Migration 158 applied to live TimescaleDB: `feature_vector_id UUID` column added to `feature_vectors` with partial non-unique index
- `FeatureWriter` renamed to `FeatureVectorWriter` with 61-column INSERT; `feature_vector_id` ($1) is the content-key UUID prepended before all structural and feature columns
- `backfill_feature_factory.py` updated with identical SHA-256 formula so live and batch write paths produce the same UUID for the same bar
- P1-P4 migration numbers bumped (157->159, 158->160) to prevent collision with newly allocated migration 158
- 64 new/updated unit tests all passing; 4 pre-existing orchestrator integration failures confirmed out-of-scope

## Task Commits

1. **Task 1: Migration 158 - feature_vector_id column** - `0f40d378` (feat)
2. **Task 2: FeatureVectorWriter with 61-param INSERT** - `0f40d378` (feat, combined)
3. **Task 3: service_auditor + test renames** - `0f40d378` (feat, combined)
4. **Task 4: backfill_feature_factory content-key + renames** - `0f40d378` (feat, combined)
5. **Task 5: P1 migration number bump + tests green** - `0f40d378` (feat, combined)

All tasks committed atomically: `0f40d378`

## Files Created/Modified

- `production/migrations/158_feature_vector_id.sql` - Adds feature_vector_id UUID column with partial index; applied to live DB
- `services/feature_vector_writer.py` - Replaces feature_writer.py; 61-param async batch INSERT; APR-backed batch params; point_gauge() metrics; database_url from Settings
- `services/backfill_feature_factory.py` - Added _make_feature_vector_id(), prepended UUID to _vector_to_params(), _TARGET_TIMEFRAMES, coverage_threshold
- `services/service_auditor.py` - _AGENT_ID_TO_UNIT key renamed "feature_writer" -> "feature_vector_writer"
- `tests/unit/services/test_feature_vector_writer.py` - 61-element tuple assertions, determinism, UUID type, parse_payload
- `tests/unit/services/test_feature_vector_writer_column_mapping.py` - Pins exact indices for all 61 columns
- `tests/unit/services/test_feature_vector_writer_config.py` - No _load_config, no config_file param, no hardcoded DSN
- `tests/unit/services/test_backfill_feature_factory.py` - Updated for _TARGET_TIMEFRAMES, 61-param tuple, shifted indices
- `tests/unit/intelligence/test_feature_factory_p7.py` - Updated tuple length assertion 60->61

## Decisions Made

- **Non-unique partial index instead of UNIQUE:** TimescaleDB hypertables reject unique indexes unless the partitioning column is included. Unique constraint was dropped in favor of a non-unique partial index (`WHERE feature_vector_id IS NOT NULL`). Application-layer uniqueness via SHA-256 is sufficient; collisions are astronomically unlikely.
- **bar_ts_ns via `int(bar_ts.timestamp() * 1e9)`:** Consistent nanosecond representation avoids platform drift; same formula used in both write paths.
- **`feature_vector_id` as $1 (first param):** Positional clarity. INSERT column order matches the conceptual "row identity comes first" principle.
- **P1/P2 migration numbers shifted:** 157 -> 159, 158 -> 160 to avoid collision with migration 158 (feature_vector_id) allocated in this plan.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] TimescaleDB unique index rejected on hypertable**
- **Found during:** Task 1 (migration 158)
- **Issue:** `CREATE UNIQUE INDEX feature_vectors_content_key_uq ON feature_vectors (feature_vector_id)` failed with `ERROR: cannot create a unique index without the column "bar_ts" (used in partitioning)`
- **Fix:** Replaced with non-unique partial index: `CREATE INDEX IF NOT EXISTS feature_vectors_content_key_idx ON feature_vectors (feature_vector_id) WHERE feature_vector_id IS NOT NULL`. Added comment explaining uniqueness is enforced at application layer.
- **Files modified:** production/migrations/158_feature_vector_id.sql
- **Verification:** Migration applied successfully; column and index confirmed in information_schema
- **Committed in:** 0f40d378

**2. [Rule 1 - Bug] Duplicate test function name rejected by pre-commit hook**
- **Found during:** Commit (Done-Coding SOP)
- **Issue:** `test_no_load_config_method` appeared in both test_feature_vector_writer.py and test_feature_vector_writer_config.py; pre-commit hook rejected
- **Fix:** Renamed to `test_no_load_config_method_in_config_module` in the config test file
- **Files modified:** tests/unit/services/test_feature_vector_writer_config.py
- **Verification:** Pre-commit duplicate check passed; commit succeeded
- **Committed in:** 0f40d378

---

**Total deviations:** 2 auto-fixed (2 Rule 1 - bugs)
**Impact on plan:** Both necessary for correctness. No scope creep.

## Issues Encountered

- 4 pre-existing `test_orchestrator_integration.py` failures (`_feature_factory_config not prewarmed`, `kalman_state` assertion). Confirmed pre-existing via `git stash` test before P0 work began. Logged, not fixed (out of scope).

## Next Phase Readiness

- P1 (IC engine tables: alpha_events, forward_returns, alpha_ic_apr_keys) ready; migration numbers corrected to 159/160
- `feature_vector_id` available on all feature_vectors rows going forward; backfill rows written before migration 158 have NULL (expected, documented in column comment)
- FeatureVectorWriter systemd unit name unchanged (`indicagent-feature-writer`); only agent_id key in service_auditor changed

---
*Phase: 138-ic-engine-forward-returns*
*Completed: 2026-06-22*
