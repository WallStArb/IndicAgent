# Deferred Items — Phase 52.6 Plan 01

## Pre-existing Test Failures (Out of Scope)

These 6 test failures existed before Plan 01 execution and are unrelated to the rename task.
They represent behavioral mismatches between test expectations and current implementation.

### tests/unit/service_tests/test_feature_writer_service.py

1. **test_record_to_insert_params_serializes_ranked_signals_to_json**
   - Expects: `i7` column value is a JSON string
   - Actual: `_record_to_insert_params` returns Python list of dicts (correct for asyncpg native JSONB)
   - Note: Test is stale — it was written before the JSONB serialization fix (commit 482f2b3)

2. **test_record_to_insert_params_jsonb_columns_are_strings**
   - Expects: all JSONB columns (bar, i1, i2, ...) are JSON strings
   - Actual: columns are Python dicts (correct for asyncpg native JSONB — see feedback_jsonb_serialization_fix.md)
   - Note: Same stale test issue as above

3. **test_maybe_flush_force_calls_execute_batch**
   - execute_batch not called because `_kafka_consumer` mock is missing `commit` attribute
   - Fix: mock needs `mock_kafka = AsyncMock()` assigned to `svc._kafka_consumer`

4. **test_maybe_flush_time_based_calls_execute_batch**
   - Same missing `_kafka_consumer` issue as above

5. **test_topic_routing_only_handles_intelligence_record**
   - Expects local variable `intelligence_record_topic` to exist in `_process_loop`
   - Actual: variable is named `intelligence_journal_topic`
   - Test was written against a planned (not actual) variable name

6. **test_graceful_shutdown_sets_flag_and_flushes**
   - execute_batch not called because `_kafka_consumer` mock is missing `commit` attribute

### Resolution

These failures should be addressed in a future plan that:
1. Updates stale JSONB-as-string tests to reflect native dict pattern
2. Adds `_kafka_consumer = AsyncMock()` to flush test fixtures
3. Updates `intelligence_record_topic` variable name assertion
