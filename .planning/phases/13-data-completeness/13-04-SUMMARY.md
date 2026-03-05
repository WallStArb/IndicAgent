---
phase: 13-data-completeness
plan: "04"
subsystem: database
tags: [feature-store, timescaledb, redis-streams, consumer-groups, upsert, expiry]

requires:
  - phase: 13-01
    provides: stream_keys intelligence_i7/i8 constructors
  - phase: 13-02
    provides: signal_generator_service publishes to intelligence_i7 stream
  - phase: 13-03
    provides: ai_narrative_service publishes to intelligence_i8 stream

provides:
  - feature_writer_service subscribes to intelligence_i7/i8 enrichment streams
  - i7 JSONB column UPSERT via ON CONFLICT DO UPDATE SET i7
  - i8 JSONB column UPSERT via ON CONFLICT DO UPDATE SET i8
  - days_to_expiry INTEGER computed at write time from Settings.contracts expiry map
  - _build_expiry_map() and _compute_days_to_expiry() pure functions
  - Concurrent _enrich_process_loop() using separate ENRICH_CONSUMER_GROUP

affects:
  - phase-14-feedback-loop
  - ml-training-pipeline

tech-stack:
  added: []
  patterns:
    - "Separate consumer groups for base (feature_writer:persist) vs enrichment (feature_writer:enrich) streams"
    - "Expiry map built once at startup and cached for lifetime of service — no per-bar Settings() calls"
    - "UPSERT enrichment pattern: INSERT ON CONFLICT DO UPDATE SET col = EXCLUDED.col for async arrival"
    - "Concurrent asyncio tasks for base and enrich loops — both single xreadgroup calls, no sequential polling"

key-files:
  created: []
  modified:
    - services/feature_writer_service.py
    - tests/unit/service_tests/test_feature_writer_service.py

key-decisions:
  - "ENRICH_CONSUMER_GROUP ('feature_writer:enrich') separate from CONSUMER_GROUP — independent position tracking per stream type"
  - "_compute_days_to_expiry returns None for empty expiry_map (service not yet initialized) vs 0 for known non-futures"
  - "VX YYYYMM format → last calendar day of that month (conservative; consistent with CONTEXT.md decision)"
  - "18-tuple _event_to_insert_params with optional expiry_map kwarg (None defaults to empty dict → None days_to_expiry)"
  - "_process_i7_message validates JSON before UPSERT; _process_i8_message constructs i8_payload from individual fields"

patterns-established:
  - "Enrichment UPSERT: INSERT ... ON CONFLICT DO UPDATE — works whether base row exists or not; async arrival safe"
  - "Module-level SQL constants (_UPSERT_I7_SQL, _UPSERT_I8_SQL) alongside existing _INSERT_FEATURE_SQL"

requirements-completed:
  - DATA-01
  - DATA-02
  - DATA-03
  - DATA-04

duration: 4min
completed: "2026-03-05"
---

# Phase 13 Plan 04: feature_writer enrichment — i7/i8 UPSERT + days_to_expiry Summary

**feature_writer_service extended to subscribe to intelligence_i7/i8 streams via concurrent xreadgroup, UPSERT i7/i8 JSONB columns, and write days_to_expiry from startup-cached expiry map on every new base row**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-03-05T14:43:59Z
- **Completed:** 2026-03-05T14:47:13Z
- **Tasks:** 2 of 3 complete (Task 3 is human-verify checkpoint)
- **Files modified:** 2

## Accomplishments

- Added `_build_expiry_map()` pure function: parses YYYYMMDD/YYYYMM expiry strings; excludes FX/CRYPTO; returns `dict[str, date]`
- Added `_compute_days_to_expiry()`: max(0, delta); returns None if expiry_map empty (uncached); 0 for non-futures
- Extended `_INSERT_FEATURE_SQL` and `_event_to_insert_params()` to 18-tuple with days_to_expiry at `$18`
- Added `_UPSERT_I7_SQL` and `_UPSERT_I8_SQL` ON CONFLICT DO UPDATE SET i7/i8 constants
- Added `_i7_stream_map`, `_i8_stream_map`, `_expiry_map` instance attributes to `FeatureWriterService`
- `_setup_consumer_groups()` now registers all i7/i8 streams under `ENRICH_CONSUMER_GROUP` and builds expiry map at startup
- Added `_process_i7_message()` and `_process_i8_message()` UPSERT coroutines
- Renamed `_process_loop` → `_base_process_loop`; added `_enrich_process_loop()` with concurrent xreadgroup
- `start()` now launches three tasks: base, enrich, and health_monitor
- 20 new unit tests (11 for new functions, 1 tuple-length update, 8 existing unchanged)
- 1137 tests passing (was 1117); ruff 0 errors

## Task Commits

Each task was committed atomically (TDD: RED then GREEN):

1. **Task 1+2 RED: Tests** - `bdf507d` (test) — 11 failing tests for expiry map, days_to_expiry, 18-tuple
2. **Task 1+2 GREEN: Implementation** - `628dd89` (feat) — full service extension; all 21 feature_writer tests pass

**Task 3 (human-verify checkpoint):** awaiting user verification of live i7/days_to_expiry in intelligence_features

## Files Created/Modified

- `services/feature_writer_service.py` — i7/i8 enrichment subscription, UPSERT handlers, days_to_expiry computation
- `tests/unit/service_tests/test_feature_writer_service.py` — 20 new tests (4 expiry map, 4 compute, 2 insert params, updated tuple-length test + existing 10 unchanged)

## Decisions Made

- Separate `ENRICH_CONSUMER_GROUP = "feature_writer:enrich"` from `CONSUMER_GROUP = "feature_writer:persist"` — independent stream position tracking required since i7/i8 arrive asynchronously after the base intelligence event
- `_compute_days_to_expiry` returns `None` for empty expiry_map and `0` for non-futures (not in map). This distinguishes "service not initialized yet" from "legitimately zero days" (expired or FX/crypto)
- `_process_i7_message` validates `data_raw` JSON before UPSERT (raises on malformed, logs error, does not write)
- `_process_i8_message` constructs i8 payload from individual fields (`model`, `confidence`, `summary`, `generated_at`)
- Expiry map built once in `_setup_consumer_groups()` — cached for service lifetime; Settings() call isolated with exception guard

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. All tests passed first run after implementation.

## Human Verify Checkpoint (Task 3)

**Awaiting user verification.** After restarting the three services, verify:

```bash
sudo systemctl restart indicagent-signal-generator indicagent-ai-narrative indicagent-feature-writer

# Wait ~2 minutes for bars to flow, then:
docker exec timescaledb psql -U postgres -d indicagent -c "
SELECT symbol, tf, ts,
       jsonb_array_length(CASE WHEN jsonb_typeof(i7) = 'array' THEN i7 ELSE '[]'::jsonb END) AS i7_signals,
       CASE WHEN i8 != '{}' THEN 'has_narrative' ELSE 'empty' END AS i8_status,
       days_to_expiry
FROM intelligence_features
WHERE ts > now() - interval '5 minutes'
ORDER BY ts DESC
LIMIT 20;"
```

Expected: `days_to_expiry` non-null for futures (ESH6, NQH6, etc.); `i7_signals` > 0 for bars where signals fired.

## Next Phase Readiness

- All DATA-01..04 requirements completed in code
- feature_writer_service now delivers complete feature vectors: i1-i8 + days_to_expiry
- intelligence_features rows from this point forward are fully populated training data
- Phase 14 (Feedback Loop) can begin: labeled outcomes in signal_ledger JOIN intelligence_features gives labeled ML dataset

---
*Phase: 13-data-completeness*
*Completed: 2026-03-05*
