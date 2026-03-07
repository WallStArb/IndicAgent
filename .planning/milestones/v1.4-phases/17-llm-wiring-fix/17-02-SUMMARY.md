---
phase: 17-llm-wiring-fix
plan: "02"
subsystem: signal-pipeline
tags: [signal_id, llm-wiring, feedback-loop, tdd]
dependency_graph:
  requires: []
  provides: [signal_id-in-aggregated-stream, signal_id-in-llm-calls]
  affects: [signal_generator_service, ai_narrative_service, llm_writer_service]
tech_stack:
  added: []
  patterns: [hot-tier-first, compensating-transaction]
key_files:
  created: []
  modified:
    - services/signal_generator_service.py
    - services/ai_narrative_service.py
    - tests/unit/service_tests/test_signal_generator_service.py
    - tests/unit/service_tests/test_ai_narrative_helpers.py
decisions:
  - "stream xadd fires before insert_signals (hot tier before cold tier); xdel compensates on DB failure"
  - "signal_id sourced from winning LedgerEntry (was_selected=True); empty string when no winner"
  - "metric counters remain inside DB block — they measure persisted signals not stream publishes"
metrics:
  duration: "~3 minutes"
  completed: "2026-03-06"
  tasks_completed: 2
  files_modified: 4
requirements:
  - LLM-04
---

# Phase 17 Plan 02: Signal ID Threading Summary

**One-liner:** Thread winning LedgerEntry UUID through signals:aggregated stream into llm_calls.signal_id so outcome back-fill WHERE clause matches rows.

## What Was Built

3 surgical changes across 2 service files, zero schema changes, zero new services.

### Change 1 — signal_generator_service._process_bar()

Reordered execution: stream `xadd` now fires **before** `insert_signals` (hot tier first, cold tier second — consistent with platform architecture). Added `signal_id` injection from the winning `LedgerEntry`:

```python
selected_entry = next((e for e in entries if e.was_selected), None)
message["signal_id"] = selected_entry.signal_id if selected_entry else ""
stream_entry_id = await self.redis_client.xadd(stream_name, message, ...)
```

Added compensating transaction: if `insert_signals` raises, the stream entry is deleted via `xdel` so downstream `llm_writer_service` never sees a signal_id without a DB row.

### Change 2 — ai_narrative_service.parse_aggregated_signal()

Added `"signal_id": _get("signal_id")` to the return dict. Missing signal_id in stream returns `""` via the existing `_get()` helper default.

### Change 3 — ai_narrative_service._build_llm_call_payload()

Replaced hardcoded `""` with `str(sd.get("signal_id", ""))`. Removed stale comment "not in aggregated stream". Updated docstring.

## Test Coverage

5 new tests added (TDD: RED then GREEN):

| Test | File | Validates |
|------|------|-----------|
| test_build_ledger_entries_winning_entry_has_signal_id | test_signal_generator_service.py | UUID4 pattern on winning entry |
| test_parse_aggregated_signal_includes_signal_id | test_ai_narrative_helpers.py | signal_id key present in parse result |
| test_parse_aggregated_signal_signal_id_empty_when_missing | test_ai_narrative_helpers.py | empty string fallback |
| test_build_llm_call_payload_uses_signal_id_from_signal_data | test_ai_narrative_helpers.py | sd.get passthrough |
| test_build_llm_call_payload_empty_string_when_no_signal_id | test_ai_narrative_helpers.py | empty dict fallback |

**Suite result:** 1195 passing, 0 failures, 0 ruff errors.

## Deviations from Plan

None — plan executed exactly as written.

## Verification Results

1. `grep -n 'selected_entry.signal_id' services/signal_generator_service.py` — line 685 FOUND
2. `grep -n 'sd.get("signal_id"' services/ai_narrative_service.py` — line 212 FOUND
3. `grep -n '"signal_id": _get' services/ai_narrative_service.py` — line 156 FOUND
4. All signal_id tests GREEN
5. Full unit suite GREEN: 1195 passing
6. ruff: 0 errors

## Commits

- `5f764ad` test(17-02): add failing tests for signal_id threading
- `4a355ae` feat(17-02): thread signal_id through aggregated stream into llm_calls

## Self-Check: PASSED

- `services/signal_generator_service.py` — modified, contains `selected_entry.signal_id`
- `services/ai_narrative_service.py` — modified, contains `sd.get("signal_id", "")`
- Commits `5f764ad` and `4a355ae` verified in git log
- 1195 unit tests passing
