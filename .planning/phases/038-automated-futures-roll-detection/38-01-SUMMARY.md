---
phase: 038-automated-futures-roll-detection
plan: 01
subsystem: database
tags: [futures, roll-detection, contracts, kafka, timescaledb, settings, psycopg2]

# Dependency graph
requires:
  - phase: 036-per-contract-futures-storage
    provides: contract_metadata table schema (roll_gap, roll_from/roll_to already exist)
provides:
  - DB migration extending contract_metadata with is_front_month + system_events table
  - src/config/contracts.py: derive_roll_chain() covering quarterly/monthly/grain futures
  - topic_system_events() Kafka topic builder in stream_keys.py
  - get_active_contracts() returning list[Instrument] with DB-backed resolution + 60s cache
  - get_active_symbols() convenience wrapper returning list[str]
  - All service files migrated from direct settings.contracts to get_active_contracts/get_active_symbols
affects:
  - 038-02: roll detection engine (builds on derive_roll_chain + system_events + get_active_contracts)
  - 038-03: pipeline integration (depends on service call site migration)

# Tech tracking
tech-stack:
  added: [psycopg2 (sync DB query in settings module)]
  patterns:
    - "DB-backed contract resolution with 60s module-level cache and graceful fallback"
    - "get_active_contracts() returns list[Instrument]; get_active_symbols() returns list[str] for string-only call sites"
    - "FUTURES_ROLL_CYCLES + MONTH_CODE_TO_NUM as typed constants in src/config/contracts.py"

key-files:
  created:
    - production/migrations/038_roll_monitor_integration.sql
    - src/config/contracts.py
    - tests/unit/test_roll_chain_derivation.py
    - tests/unit/test_service_contract_resolution.py
  modified:
    - src/core/stream_keys.py (added topic_system_events)
    - src/config/settings.py (roll_monitor_* fields, get_active_contracts, get_active_symbols)
    - services/tws_daemon.py
    - services/indicator_service.py
    - services/market_analysis_service.py
    - services/feature_writer_service.py
    - services/signal_generator_service.py
    - services/signal_lifecycle_service.py
    - services/drift_monitor_service.py
    - services/ai_narrative_service.py
    - services/timeframes_builder_service.py

key-decisions:
  - "get_active_contracts() returns list[Instrument] (not list[str]) so callers always get full instrument metadata. get_active_symbols() provides list[str] for call sites that only need symbol names."
  - "ROLL_MONITOR_ENABLED=false default ensures zero behavior change for all services until roll detection engine (38-02) is ready and tested"
  - "Instrument reconstruction inherits config-file defaults (point_value, tick_size, session_id, exchange) by base_symbol lookup — DB only stores symbol/base_symbol/exchange; non-DB fields come from config"
  - "derive_roll_chain uses 1-digit year suffix (e.g. '6' for 2026) matching IBKR format"
  - "system_events table is separate from contract_metadata to keep roll event history independent of contract state"

patterns-established:
  - "Roll chain derivation: FUTURES_ROLL_CYCLES[base] → ordered month codes → (year, code) tuples starting from ref_month → 3-contract list with roll_from/roll_to linkage"
  - "Settings field naming: roll_monitor_* prefix with default=False/safe-defaults throughout"
  - "Service call sites: get_active_contracts(settings) for Instrument iteration, get_active_symbols(settings) for string-only uses"

requirements-completed: [ROLL-01, ROLL-02, ROLL-03]

# Metrics
duration: 8min
completed: 2026-03-18
---

# Phase 38 Plan 01: DB Foundation for Automated Roll Detection Summary

**Migration 038 extending contract_metadata + system_events table, derive_roll_chain() for quarterly/monthly/grain futures, topic_system_events() stream key, and get_active_contracts() returning list[Instrument] with 60s DB cache and config-file fallback**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-03-18T03:58:22Z
- **Completed:** 2026-03-18T04:06:42Z
- **Tasks:** 2
- **Files modified:** 15 (4 created, 11 modified)

## Accomplishments

- Created `production/migrations/038_roll_monitor_integration.sql` extending `contract_metadata` with `is_front_month`, `roll_direction`, `roll_detected_at`, `confirmation_count` and adding `system_events` audit table with two indexes
- Created `src/config/contracts.py` with `derive_roll_chain()` covering quarterly (ES/NQ/RTY/YM/ZN/ZF/ZB/ZT/VIX), monthly (CL/GC/SI/HG), and grain cycle (ZC/ZS/ZW) futures; returns 3-contract chains with correct roll_from/roll_to linkage and chronological sorting
- Added `topic_system_events()` to `src/core/stream_keys.py` following existing dot-separated naming pattern
- Rewrote `get_active_contracts()` to return `list[Instrument]` (was `list[str]`); added `get_active_symbols()` convenience wrapper; added 7 roll monitoring Settings fields with safe defaults; added 60s cache with psycopg2 DB query and graceful config-file fallback
- Migrated all 11 service files from direct `settings.contracts` access to `get_active_contracts()` / `get_active_symbols()` — zero direct `settings.contracts` accesses remain

## Task Commits

1. **Task 1: Migration 038 + Roll Chain Utility + Stream Key** - `9106bb9` (feat)
2. **Task 2: DB-Backed get_active_contracts() + Service Call Site Migration** - `1410a97` (feat)

## Files Created/Modified

- `production/migrations/038_roll_monitor_integration.sql` - Extends contract_metadata, adds system_events table + 2 indexes
- `src/config/contracts.py` - derive_roll_chain(), FUTURES_ROLL_CYCLES, MONTH_CODE_TO_NUM
- `src/core/stream_keys.py` - Added topic_system_events()
- `src/config/settings.py` - 7 roll_monitor_* fields, rewritten get_active_contracts(), new get_active_symbols(), cache variables
- `services/tws_daemon.py` - Migrated 2 settings.contracts accesses to get_active_contracts()
- `services/indicator_service.py` - Migrated instrument_map construction and config symbols
- `services/market_analysis_service.py` - Migrated instrument_map and active_contracts seed loop
- `services/feature_writer_service.py` - Migrated _build_expiry_map and config symbols
- `services/signal_generator_service.py` - Migrated seed loop and config symbols
- `services/signal_lifecycle_service.py` - Migrated config symbols
- `services/drift_monitor_service.py` - Migrated config symbols
- `services/ai_narrative_service.py` - Migrated config symbols
- `services/timeframes_builder_service.py` - Migrated _symbols construction
- `tests/unit/test_roll_chain_derivation.py` - 41 tests covering all derive_roll_chain behaviors
- `tests/unit/test_service_contract_resolution.py` - 16 tests covering DB/cache/fallback behaviors

## Decisions Made

- `get_active_contracts()` returns `list[Instrument]` not `list[str]` so callers always get full instrument metadata. This is a breaking signature change but all call sites were audited and migrated atomically.
- `get_active_symbols()` added as a convenience wrapper for the many call sites that only need symbol strings (logging, config dict population) — avoids forcing all code to do `[i.symbol for i in get_active_contracts()]`.
- `ROLL_MONITOR_ENABLED=false` default ensures zero behavior change for existing services. The DB path only activates when the roll detection engine (38-02) is deployed and validated.
- `derive_roll_chain` uses 1-digit year suffix matching IBKR format (e.g. `ESM6` not `ESM2026`).
- `system_events` is a separate table (not a column on `contract_metadata`) to preserve immutable history of all detected rolls independent of current contract state.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed incorrect RTY symbol length assertion in test**
- **Found during:** Task 1 (TDD RED phase verification)
- **Issue:** Test asserted RTY symbols have 6 chars but RTY+M+6 = 5 chars (RTYH6). The spec says "base + month_code + year_digit" — RTY is 3 chars + 1 + 1 = 5.
- **Fix:** Corrected expected length from 6 to 5 in the test assertion.
- **Files modified:** tests/unit/test_roll_chain_derivation.py
- **Verification:** All 41 tests pass
- **Committed in:** `9106bb9`

---

**Total deviations:** 1 auto-fixed (Rule 1 — test spec error)
**Impact on plan:** Trivial — test assertion matched wrong expected value. Implementation was correct.

## Issues Encountered

- Several service files had pre-existing ruff lint errors (E501 line-too-long, B007 unused loop variable, I001 import order) that pre-date this plan. Kept within scope boundary — only fixed errors directly caused by new code.

## Next Phase Readiness

- Migration 038 SQL is ready to apply: `docker cp production/migrations/038_roll_monitor_integration.sql timescaledb:/tmp/ && docker exec timescaledb psql -U postgres -d indicagent -f /tmp/038_roll_monitor_integration.sql`
- `derive_roll_chain()` is ready for use by the roll detection engine (38-02)
- `topic_system_events()` is ready for the roll event publisher
- `get_active_contracts()` + `get_active_symbols()` are ready — all call sites migrated, zero direct `settings.contracts` access remains
- 38-02 can build roll detection logic on top of this foundation without any additional call site work

---
*Phase: 038-automated-futures-roll-detection*
*Completed: 2026-03-18*
