# Deferred Items — Phase 138 P1

## Pre-existing Test Failures (out of scope for 138-P1)

Discovered during Task 4 test verification. Confirmed pre-existing by git stash check.

### tests/unit/pipeline/test_orchestrator_integration.py (4 tests)

**Status:** Failing before 138-P1 work started (confirmed by stash + rerun).

**Failures:**
- `test_orchestrator_routes_signals_payload_to_i7_topic` — asserts `enqueue_blocking` called with i7/signals topic, but routing uses `_out_queue` differently
- `test_orchestrator_routes_dlq_payload_to_dlq_topic` — same routing mismatch
- `test_orchestrator_checkpoint_assembly_excludes_plugin_states` — asserts `kalman_state` in checkpoint extra, but checkpoint only has `last_bar_offset`
- `test_orchestrator_state_update_flow_through_executor_to_state_manager` — asserts executor state updates propagate to state manager; propagation path has changed

**Root cause:** `pipeline_helpers.make_agent()` uses `__new__()` bypass and was missing many `__init__` attributes. 138-P1 added `_feature_factory_config`, `_feature_caches`, `_kafka_producer`, `_background_tasks`, `_bar_e2e_latency` to unblock AttributeErrors. Remaining failures are semantic test/impl mismatches that require updating test assertions to match how IntelligencePipeline now routes data.

**Recommended fix:** Update test assertions in `test_orchestrator_integration.py` to reflect current `_process_bar_compute` routing. Or use `_wire_agent` to mock `_kafka_producer.publish` and `_out_queue.enqueue_blocking` and verify call args match actual code path.

## Pre-existing Test Failures (out of scope for 138-P8)

### tests/unit/services/test_pipeline_backpressure.py::test_intel_and_journal_use_blocking_enqueue

**Status:** Failing before 138-P8 work started (confirmed — no code changes in P8).

**Failure:** `FileNotFoundError: No such file or directory: 'services/intelligence_pipeline.py'`

**Root cause:** Test reads `services/intelligence_pipeline.py` source for a text assertion. That file was renamed to `feature_vector_pipeline.py` during the IntelligencePipeline -> FeatureVectorPipeline rename. Test was not updated.

**Recommended fix:** Update test to read `services/feature_vector_pipeline.py` instead.
