# Deferred Items - Phase 137

## Pre-existing Test Failures (12 total)

These failures existed before P6 and are out of scope for the D-09 cutover.

### feature_writer tests (7 failures)

Files:
- `tests/unit/services/test_feature_writer_column_mapping.py` (5)
- `tests/unit/services/test_feature_writer_config.py` (2)

Root cause: Tests use `BarIntelligenceRecord` fixture but `feature_writer.py` was updated
in P4 to use `FeatureVectorRecord`. The tests also patch `services.feature_writer.get_active_contracts`
which was removed from that module in P4. These tests need updating to match the P4 API.

### orchestrator_integration tests (4 failures)

File: `tests/unit/pipeline/test_orchestrator_integration.py`

Root cause: Tests reference I7 topic routing behavior and old signal payload routing that
no longer exists after the D-09 cutover. These tests test v2.x orchestrator behavior.

### context_writer test (1 failure)

File: `tests/unit/services/test_context_writer.py::test_feature_writer_insert_includes_ctx_column`

Root cause: Same BarIntelligenceRecord vs FeatureVectorRecord mismatch as above.

## Backfill Run Pending

The actual historical backfill (P5 plan) requires live IBKR connection to run.
Command: `.venv/bin/python production/scripts/run_historical_pipeline.py --client-id 40`

## Live Smoke Test Pending

After merging to main and restarting `indicagent-intelligence-pipeline`:
- Verify `feature_vectors` rows appear in TimescaleDB
- Confirm `topic_feature_vectors` messages flow to `feature_writer`
