---
phase: 58.1-contract-lifecycle-automation
plan: "01"
subsystem: core
tags: [trading-session, stream-keys, schemas, contract-lifecycle, tdd]
dependency_graph:
  requires: []
  provides:
    - TradingSession.session_window_for_date()
    - TradingSession.max_achievable_pct()
    - topic_contract_updates()
    - topic_roll_dlq()
    - ContractUpdateEvent schema
  affects:
    - src/core/models.py
    - src/core/stream_keys.py
    - src/core/schemas/market_events.py
tech_stack:
  added: []
  patterns:
    - TDD red/green with frozen dataclass method extension
    - UTC-aware datetime arithmetic via ZoneInfo
key_files:
  created:
    - tests/unit/test_models.py
  modified:
    - src/core/models.py
    - src/core/stream_keys.py
    - src/core/schemas/market_events.py
decisions:
  - All-day sessions (open==close) detected by equality check, return midnight-to-midnight UTC
  - Overnight sessions (open > close) start on prev_day in local time — correct for CME futures (Etc/GMT+6)
  - max_achievable_pct uses session_window_for_date with a fixed reference Monday (2026-03-02) to get total window, then subtracts break minutes
  - topic_contract_updates and topic_roll_dlq follow existing topic_roll_events() pattern exactly
  - ContractUpdateEvent has all 4 fields required (no defaults) — partial event must not flow downstream
metrics:
  duration_minutes: 3
  tasks_completed: 3
  files_changed: 4
  tests_added: 27
  completed_date: "2026-04-02"
requirements:
  - CLA-01
  - CLA-02
  - CLA-03
  - CLA-04
---

# Phase 58.1 Plan 01: Foundational Types for Contract Lifecycle Automation Summary

**One-liner:** UTC session window computation and ContractUpdateEvent schema enabling BarAuditorAgent gap detection and contract promotion broadcast.

## Tasks Completed

| # | Name | Commit | Files |
|---|------|--------|-------|
| 1 (RED) | Failing tests for TradingSession methods and ContractUpdateEvent | 56ebd69 | tests/unit/test_models.py |
| 2 (GREEN) | session_window_for_date + max_achievable_pct on TradingSession | f296703 | src/core/models.py |
| 3 (GREEN) | topic_contract_updates, topic_roll_dlq, ContractUpdateEvent | f296703 | src/core/stream_keys.py, src/core/schemas/market_events.py |

## What Was Built

**TradingSession.session_window_for_date(target_date) -> tuple[datetime | None, datetime | None]**

Returns UTC-aware (start, end) pair for a given calendar date. Handles three session geometries:
- All-day (open==close): midnight-to-midnight UTC — crypto_24_7, fx_24_5
- Same-day (open < close): converts local open/close to UTC — nyse (EDT=UTC-4), tse, hkex
- Overnight (open > close): start = prev_day open in UTC, end = target_date close in UTC — futures_24_5 (Etc/GMT+6=UTC-6, 18:00 Sun CST = 00:00 Mon UTC)
- Non-trading day: returns (None, None)

**TradingSession.max_achievable_pct() -> float**

Returns ratio of active trading minutes to total session window minutes. Used by BarAuditorAgent as a completeness ceiling to avoid false gap alerts during break periods. Sessions without breaks return 1.0; TSE and HKEX (60-min lunch break) return 330/390 = 0.846.

**New Kafka topic functions (stream_keys.py):**
- `topic_contract_updates(env_name)` -> `{env}.market.events.contract_update`
- `topic_roll_dlq(env_name)` -> `{env}.market.events.roll.dlq`

**ContractUpdateEvent (market_events.py):**
Pydantic model with 4 required fields: base_symbol, old_contract, new_contract, promoted_at (UTC datetime). Published by ContractMetadataWriterAgent after successful roll promotion.

## Verification

```
27 passed in 0.04s
```

All 27 unit tests pass. No ruff violations in modified files (pre-existing W191 tab indentation in ContractMetadata is out of scope per deviation boundary rule — existed before this plan).

## Deviations from Plan

**1. [Rule 2 - Pre-existing lint] ContractMetadata tab indentation W191 violations**
- **Found during:** ruff check after Task 2
- **Issue:** `ContractMetadata` dataclass in models.py (lines 483-509) uses tab indentation — pre-existing before this plan
- **Action:** Logged here; out of scope per deviation boundary rule (not caused by this plan's changes)
- **Impact:** None on plan deliverables; all new code uses spaces

## Known Stubs

None. All 4 deliverables are fully implemented:
- `session_window_for_date()` computes real UTC windows
- `max_achievable_pct()` computes real ratios from session geometry
- `topic_contract_updates()` and `topic_roll_dlq()` return correct topic strings
- `ContractUpdateEvent` is a complete Pydantic model

## Self-Check: PASSED

Files exist:
- tests/unit/test_models.py: FOUND
- src/core/models.py: FOUND (modified)
- src/core/stream_keys.py: FOUND (modified)
- src/core/schemas/market_events.py: FOUND (modified)

Commits exist:
- 56ebd69 (RED tests): FOUND
- f296703 (GREEN implementation): FOUND
