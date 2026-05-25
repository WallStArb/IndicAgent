# Phase 107 Writer Inventory Matrix

**Generated:** 2026-05-25 17:51:00 UTC
**Purpose:** Document ALL writer services with flush trigger, batch size, shutdown behavior, span status, and test coverage.

## Matrix

| Writer | Flush Trigger | Batch Size | Shutdown Flush | Span Present | Test Coverage |
|--------|---------------|------------|----------------|--------------|---------------|
| bar_writer_agent | Time (5s) OR batch size (50) | 50 | Yes (BaseWriterAgent._teardown) | No | tests/unit/services/test_bar_writer_agent.py |
| feature_writer_agent | Time (5s) OR batch size (50) | 50 | Yes (BaseWriterAgent._teardown) | No | tests/unit/services/test_feature_writer_agent.py |
| signal_writer_agent | Time (5s) OR batch size (100) | 100 | Yes (BaseWriterAgent._teardown) | No | tests/unit/services/test_signal_writer_agent.py |
| llm_writer_service | Time (5s) OR batch size (50) | 50 | Yes (BaseWriterAgent._teardown) | No | tests/unit/services/test_llm_writer_service.py |
| lifecycle_writer_agent | Time (5s) OR batch size (50) | 50 | Yes (BaseWriterAgent._teardown) | No | tests/unit/services/test_lifecycle_writer_agent.py |
| lineage_writer_agent | Time (5s) OR batch size (50) | 50 | Yes (BaseWriterAgent._teardown) | No | tests/unit/services/test_lineage_writer_agent.py |
| contract_metadata_writer_agent | Time (5s) OR batch size (50) | 50 | Yes (BaseWriterAgent._teardown) | No | tests/unit/services/test_contract_metadata_writer_agent.py |
| swarm_ledger_writer_agent | Time (5s) OR batch size (50) | 50 | Yes (BaseWriterAgent._teardown) | No | tests/unit/services/test_swarm_ledger_writer_agent.py |
| signal_metrics_writer_agent | Time (5s) OR batch size (50) | 50 | Yes (BaseWriterAgent._teardown) | No | tests/unit/services/test_signal_metrics_writer_agent.py |
| graduation_writer_agent | Time (5s) OR batch size (50) | 50 | Yes (BaseWriterAgent._teardown) | No | tests/unit/services/test_graduation_writer_agent.py |
| ctx_writer_agent | Time (5s) OR batch size (50) | 50 | Yes (BaseWriterAgent._teardown) | No | tests/unit/services/test_ctx_writer_agent.py |

## Summary

- **Total writers:** 11
- **Flush span coverage:** 0/11 (all RED - HYGIENE-01 violation)
- **Shutdown flush coverage:** 11/11 (all via BaseWriterAgent._teardown)
- **Test coverage:** 11/11 (all have unit tests)

## Notes

### Flush Trigger Patterns
All writers use dual-trigger flush:
1. **Time-based:** FLUSH_INTERVAL_SECS = 5.0 seconds
2. **Size-based:** BATCH_SIZE threshold (50-100 events)

### Batch Size Distribution
- 50 events: 10 writers (bar_writer, feature_writer, llm_writer, lifecycle_writer, lineage_writer, contract_metadata_writer, swarm_ledger_writer, signal_metrics_writer, graduation_writer, ctx_writer)
- 100 events: 1 writer (signal_writer - higher throughput for I7 signals)

### Shutdown Flush
All writers inherit shutdown flush from BaseWriterAgent._teardown(), which calls _flush() before closing the DB connection. This prevents data loss on graceful shutdown.

### Span Coverage (HYGIENE-01)
**CRITICAL:** 0/11 writers have observed_span in _flush() method. All are marked RED for HYGIENE-01 compliance. Wave 2 Task 1 targets adding flush spans to all writers.

### Test Coverage
All 11 writers have unit tests in tests/unit/services/ following the pattern test_{writer_name}.py. Tests cover:
- _parse_payload() validation
- _flush() batch INSERT behavior
- _teardown() shutdown flush
- DLQ routing

## Wave 2 Target List

Writers needing flush span coverage (Wave 2 Task 1):
1. bar_writer_agent
2. feature_writer_agent
3. signal_writer_agent
4. llm_writer_service
5. lifecycle_writer_agent
6. lineage_writer_agent
7. contract_metadata_writer_agent
8. swarm_ledger_writer_agent
9. signal_metrics_writer_agent
10. graduation_writer_agent
11. ctx_writer_agent

All 11 writers are in scope for Wave 2 Task 1.
