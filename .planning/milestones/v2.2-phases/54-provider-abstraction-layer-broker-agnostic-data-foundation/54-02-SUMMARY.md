---
phase: 54-provider-abstraction-layer-broker-agnostic-data-foundation
plan: "02"
subsystem: providers
tags: [ibkr, provider-adapter, bar-message, session-type, settings, tdd]

requires:
  - phase: 54-01
    provides: DataProviderAdapter Protocol, BarMessage with SOURCE_IBKR_GENERIC, stream_keys

provides:
  - IBKRAdapter class implementing DataProviderAdapter Protocol
  - 5s RTB aggregation state machine moved from DataProviderAgent into adapter
  - Nested provider_meta format (provider_meta['ibkr']['trading_class'])
  - fetch_historical converting OHLCVBar to BarMessage with SOURCE_IBKR_NAMED
  - IBKRProvider.qualify_instrument updated to read nested + legacy flat fallback

affects:
  - 54-03 (BaseProviderAgent uses IBKRAdapter)
  - services/data_provider_agent.py (RTB loop can be removed once cutover)
  - src/providers/CLAUDE.md (VIX provider_meta format updated)

tech-stack:
  added: []
  patterns:
    - "_SESSION_ID_TO_TYPE dict maps Instrument.session_id to SessionType enum for bar construction"
    - "asyncio.timeout + aclose() pattern for async generator testing"
    - "Legacy flat provider_meta fallback in IBKRProvider for backward compat"

key-files:
  created:
    - src/providers/ibkr_adapter.py
    - tests/unit/providers/test_ibkr_adapter.py
  modified:
    - src/config/settings.py
    - src/providers/ibkr.py

key-decisions:
  - "IBKRAdapter._provider wraps IBKRProvider directly — no DI container needed at this scale"
  - "session_id to SessionType mapping via _SESSION_ID_TO_TYPE dict (futures_24_5→RTH, fx_24_5→FX, crypto_24_7→CRYPTO, nyse→RTH)"
  - "Legacy flat provider_meta fallback in IBKRProvider.qualify_instrument — IBKRProvider callers who haven't migrated still work"
  - "asyncio.ensure_future for background tasks (official bars + heartbeat) inside stream_bars generator"

patterns-established:
  - "Adapter wraps existing provider, does not replace it — DataProviderAgent still uses IBKRProvider directly until Plan 54-03 cutover"
  - "provider_meta key hierarchy: provider_meta[provider_name][key] — always read via self.provider_name"

requirements-completed: []

duration: 9min
completed: "2026-03-28"
---

# Phase 54 Plan 02: IBKRAdapter + provider_meta Migration Summary

**IBKRAdapter wrapping IBKRProvider with 5s-RTB-to-1m aggregation state machine and nested provider_meta['ibkr'] format**

## Performance

- **Duration:** 9 min
- **Started:** 2026-03-28T21:26:27Z
- **Completed:** 2026-03-28T21:35:50Z
- **Tasks:** 2 (TDD: 1 RED + 1 GREEN)
- **Files modified:** 4

## Accomplishments

- `IBKRAdapter` implementing `DataProviderAdapter` Protocol: `provider_name="ibkr"`, `stream_bars()`, `fetch_historical()`, `qualify_instrument()`
- 5s RTB → 1m OHLCV aggregation state machine extracted from `DataProviderAgent._rtb_loop()` into `IBKRAdapter.stream_bars()`
- VXJ6 `provider_meta` migrated from flat `{"trading_class": "VX"}` to nested `{"ibkr": {"trading_class": "VX"}}`
- `IBKRProvider.qualify_instrument` reads `provider_meta["ibkr"]["trading_class"]` with backward-compat flat fallback
- 11 TDD tests: protocol compliance, stream_bars, fetch_historical, qualify_instrument, settings validation

## Task Commits

1. **Task 1: Write IBKRAdapter and provider_meta tests (RED)** - `584447e` (test)
2. **Task 2: Implement IBKRAdapter, migrate provider_meta (GREEN)** - `854155c` (feat)

## Files Created/Modified

- `src/providers/ibkr_adapter.py` — IBKRAdapter: DataProviderAdapter implementation wrapping IBKRProvider, 5s RTB aggregation, session_id→SessionType mapping
- `tests/unit/providers/test_ibkr_adapter.py` — 11 TDD tests covering protocol, stream_bars, fetch_historical, qualify_instrument, settings
- `src/config/settings.py` — VXJ6 provider_meta migrated to nested `{"ibkr": {"trading_class": "VX"}}`
- `src/providers/ibkr.py` — qualify_instrument reads `provider_meta.get("ibkr", {}).get("trading_class")` with flat fallback

## Decisions Made

- `_SESSION_ID_TO_TYPE` dict maps `Instrument.session_id` to `SessionType` enum for bar construction. `session_id` is a calendar identifier (`futures_24_5`, `fx_24_5`, `crypto_24_7`, `nyse`) — not a SessionType value — so a mapping table is needed at adapter level.
- Legacy flat provider_meta fallback added to `IBKRProvider.qualify_instrument` — other callers (DataProviderAgent, backfill scripts) may still use the old format during the transition window.
- `asyncio.ensure_future` for official bars background task and heartbeat loop inside `stream_bars` — both tasks are cleanup-cancelled in the generator's `finally` block.
- Test helper uses `asyncio.timeout` + `gen.aclose()` pattern to collect one bar without hanging on the infinite queue.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed SessionType construction from session_id**
- **Found during:** Task 2 GREEN phase (test run)
- **Issue:** `SessionType(instrument.session_id)` fails — session_id is `"futures_24_5"` but SessionType enum values are `"rth"`, `"fx"`, `"crypto"`, etc.
- **Fix:** Added `_SESSION_ID_TO_TYPE` dict mapping session_id strings to SessionType enum values; removed incorrect `normalize_session_type` call
- **Files modified:** `src/providers/ibkr_adapter.py`
- **Verification:** All 4 stream_bars tests pass after fix

**2. [Rule 1 - Bug] Fixed test helper hanging on async generator**
- **Found during:** Task 1 (RED phase) — tests timed out
- **Issue:** `async for bar in adapter.stream_bars(...)` blocks forever; background tasks (heartbeat) run infinitely
- **Fix:** `_collect_one_bar` helper uses `asyncio.timeout` context and `gen.aclose()` in finally block; mock also stubs `stream_official_bars`
- **Files modified:** `tests/unit/providers/test_ibkr_adapter.py`
- **Verification:** All 4 stream_bars tests complete in <1s

---

**Total deviations:** 2 auto-fixed (both Rule 1 - bugs)
**Impact on plan:** Both fixes necessary for test correctness. No scope creep.

## Issues Encountered

- Pre-existing `test_default_settings` failure in `tests/unit/config/test_settings.py` (checks `settings.redis_host` which was removed in a prior phase). Not caused by this plan's changes. Logged as out-of-scope.

## Known Stubs

None — IBKRAdapter is fully wired. `stream_bars` yields real BarMessage instances from mock RTB data in tests. `fetch_historical` delegates to IBKRProvider. No placeholder returns.

## Next Phase Readiness

- IBKRAdapter is ready to be consumed by `BaseProviderAgent` (Plan 54-03)
- `DataProviderAgent._rtb_loop()` can be removed/simplified in 54-03 once cutover is complete
- VXJ6 nested provider_meta format is the new canonical format — all new instruments should use `{"ibkr": {...}}`

---
*Phase: 54-provider-abstraction-layer-broker-agnostic-data-foundation*
*Completed: 2026-03-28*
