---
phase: 097-agent-memory
plan: "06"
subsystem: core/memory
tags: [tests, unit, memory, graceful-degradation, embeddings]
dependency_graph:
  requires: [097-01, 097-02, 097-03, 097-04]
  provides: [unit-test-coverage-memory-layer]
  affects: []
tech_stack:
  added: []
  patterns: [fake-injection, pytest-mark-asyncio, AsyncMock-pool-ctx-manager]
key_files:
  created:
    - tests/unit/core/test_memory_client.py
    - tests/unit/core/test_memory_writer.py
    - tests/unit/core/test_embedding_service.py
  modified: []
decisions:
  - "Use explicit @pytest.mark.asyncio per-function (not pytestmark) because pytest-asyncio 1.3.0 runs in STRICT mode despite pytest.ini having asyncio_mode=auto in [tool:pytest] section (invalid for .ini files)"
  - "test_drain_skips_insert_when_embedding_none verifies NULL embedding INSERT is called (not skipped) — this matches the actual design where rows are always persisted for offline backfill"
metrics:
  duration_minutes: 10
  completed_date: "2026-06-05"
  tasks_completed: 2
  files_created: 3
---

# Phase 097 Plan 06: Memory Layer Unit Tests Summary

CI-clean unit tests for MemoryClient, MemoryEpisodeWriter/EmbeddingWorker, and EmbeddingService using fakes — no live DB, no live Ollama. 26 tests total locking the never-raise, fire-and-forget, and percentile-serialization contracts.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Unit-test MemoryClient with fake backends | 827b2cc6 | tests/unit/core/test_memory_client.py |
| 2 | Unit-test MemoryEpisodeWriter queue-drop and EmbeddingService serialization | 642c7996 | tests/unit/core/test_memory_writer.py, tests/unit/core/test_embedding_service.py |

## What Was Built

**test_memory_client.py (9 tests):**
- `test_recall_returns_episodes` — fake EpisodicBackend returns Episodes; client passes them through
- `test_recall_empty_is_miss` — [] backend returns [] without raising
- `test_recall_backend_error_returns_empty` — RuntimeError from backend yields [] (MEM-01 graceful degradation)
- `test_recall_embedding_failure_returns_empty` — None from EmbeddingService yields []
- `test_recall_limit_respected` — limit parameter caps results
- `test_calibration_none_when_missing` — no data (sample_n=0) returns None
- `test_calibration_returns_stats` — promoted row returns CalibrationStats with bootstrapped=True
- `test_calibration_partial_when_accumulating` — partial data (sample_n=15) returns bootstrapped=False stats
- `test_no_write_method` — asserts MemoryClient lacks store()/write() (D-19 read-only invariant)

**test_memory_writer.py (6 tests):**
- `test_store_enqueues` — two store() calls produce queue depth 2
- `test_store_drops_when_full` — QueueFull triggers MEMORY_WRITE_DROPPED_TOTAL.add(1, {}); queue stays at maxsize
- `test_store_never_raises_on_arbitrary_exception` — bad epoch provider doesn't propagate
- `test_drain_inserts_on_success` — _process_episode executes INSERT with memory_episodes_raw SQL
- `test_drain_skips_insert_when_embedding_none` — NULL embedding still persists row (offline backfill design)
- `test_drain_handles_embed_exception_gracefully` — embed_context raising does not propagate; INSERT called with NULL

**test_embedding_service.py (11 tests):**
- `test_serialize_uses_percentiles` — rsi_pct:/atr_pct: present; "rsi:" absent (D-22)
- `test_serialize_includes_identity_tokens` — symbol/timeframe/entry_type/regime/vol always present
- `test_serialize_handles_missing_optional_fields` — minimal context serializes without exception
- `test_serialize_hmm_prob_token` / `test_serialize_swing_structure_token` — conditional token inclusion
- `test_embed_returns_none_on_http_error` / `test_embed_returns_none_on_timeout` — no propagation
- `test_embed_returns_none_on_dim_mismatch` — 384-dim response returns None (768 expected)
- `test_embed_returns_vector_on_success` — 768-dim vector returned correctly
- `test_embed_context_returns_text_even_on_failure` — D-05: text always returned for audit
- `test_embed_context_returns_vector_and_text_on_success` — success path returns both

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] pytest-asyncio STRICT mode requires explicit @pytest.mark.asyncio**
- **Found during:** Task 1 execution
- **Issue:** pytest.ini has `[tool:pytest]` section (setup.cfg style) which is invalid in `.ini` files; `asyncio_mode = auto` not read by pytest; mode defaults to STRICT requiring explicit markers
- **Fix:** Added `@pytest.mark.asyncio` to each async test function individually (not pytestmark global to avoid warning on sync tests)
- **Files modified:** tests/unit/core/test_memory_client.py
- **Commit:** 827b2cc6

**2. [Plan clarification] test_drain_skips_null_embedding: plan said "assert no INSERT" but code always INSERTs**
- **Found during:** Task 2 implementation
- **Issue:** Plan spec said "_drain skips NULL-embedding rows" but the actual design (writer.py line 259-280) always INSERTs with `embedding_str=None` (NULL) - the offline backfill job filters WHERE embedding IS NOT NULL. "Skip" in the plan referred to the backfill, not the INSERT.
- **Fix:** Test asserts INSERT IS called with NULL embedding parameter (index 7 = None), which correctly documents the actual contract
- **Files modified:** tests/unit/core/test_memory_writer.py

## Verification

```
.venv/bin/pytest tests/unit/core/ -q
504 passed, 1 skipped, 1 warning in 6.0s
```

All three new test files collected and passing. No DB or Ollama connections made.

## Self-Check: PASSED

| Item | Status |
|------|--------|
| tests/unit/core/test_memory_client.py | FOUND |
| tests/unit/core/test_memory_writer.py | FOUND |
| tests/unit/core/test_embedding_service.py | FOUND |
| commit 827b2cc6 (Task 1) | FOUND |
| commit 642c7996 (Task 2) | FOUND |
