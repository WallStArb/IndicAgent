---
phase: 071-base-agent-infrastructure-alignment
plan: 05
status: complete
completed: "2026-04-14"
commits:
  - 3fa37cb9 feat(071-05): migrate LLMWriterService to LLMWriterAgent(BaseWriterAgent)
---

# Summary: LLMWriterService → LLMWriterAgent(BaseWriterAgent)

## What Was Done

Migrated the only active agent that didn't inherit from BaseAgent. `LLMWriterService` was rolling its own signal handling, metrics server, logging setup, shutdown, and lag reporting. Now `LLMWriterAgent(BaseWriterAgent)` gets all of that for free.

### Changes

**Class declaration:** `LLMWriterService` → `LLMWriterAgent(BaseWriterAgent)`

**Removed (now provided by BaseAgent/BaseWriterAgent):**
- `signal.signal()` calls in `__init__`
- `start_metrics_server()` call
- `setup_service_logging()` call
- `start()` method (replaced by `_run()`)
- `self.running` / `self.shutdown_requested` attributes
- Manual `_shutdown()` (replaced by `_teardown()` override)

**Added abstract method implementations:**
- `_topic_name()` → `topic_llm_calls(self._env_name)`
- `_consumer_group` property → `"llm_writer"`
- `_parse_payload()` → parses llm.calls payloads
- `_flush_batch()` → batch INSERT to `llm_calls`
- `_dlq_topic()` → `topic_llm_writer_dlq(self._env_name)`

**Custom `_run()`:** Connects DB, sets up Kafka, then gathers 4 tasks (process_loop, score_recompute_loop, health_monitor_loop, stall_watchdog)

**Custom `_teardown()`:** Calls `super()._teardown()` (final buffer flush), then closes consumer, DLQ producer, and DB

**Buffer migration:** `self._calls_buffer` → `self._buffer` (BaseWriterAgent standard). Using `_buffer_rows([params])` instead of direct `.append()` to keep `_buffer_depth_gauge` updated.

**Shutdown condition:** `self.shutdown_requested` → `self._stop_event.is_set()` everywhere in loops

**Backward compat alias:** `LLMWriterService = LLMWriterAgent` (existing tests unaffected)

### Preserved Unchanged
- All SQL constants
- All pure functions (`_parse_llm_call_fields`, `_parse_outcome_fields`, `_build_score_insert_params`)
- `_load_config()`, `_connect_database()`
- `_process_calls_message()`, `_process_outcome_message()`, `_process_i8_message()`
- `_flush_i8()`, `_recompute_scores()`, `_send_to_dlq()`
- All Prometheus metric names (dashboard/alerting compatibility)

## Decisions

- **`_calls_buffer` → `self._buffer`**: Standard BaseWriterAgent buffer for offset-commit/DLQ safety
- **`_i8_buffer` kept separate**: i8 updates use `_UPDATE_I8_SQL` (different SQL), not `_INSERT_LLM_CALL_SQL`
- **`_setup_kafka_clients()` assigns `self._consumer`**: Required for BaseWriterAgent offset commits
- **`_send_to_dlq()` kept with original 3-arg signature**: Different from BaseAgent's 2-arg version; LLM writer owns its DLQ routing logic (multi-topic context)
- **Test fix**: `test_llm_writer_buffer_depth_gauge` was using direct `.extend()` which bypasses `_buffer_rows()` — fixed to use `_buffer_rows()` correctly

## Verification

- 21/21 LLM writer tests pass
- No `signal.signal` calls remain
- `LLMWriterAgent(BaseWriterAgent)` class confirmed
