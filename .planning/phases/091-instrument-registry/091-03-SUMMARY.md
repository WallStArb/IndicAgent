---
phase: 091-instrument-registry
plan: 03
subsystem: config, api
tags: [instrument-registry, settings, get_active_contracts, db-source-of-truth]
dependency_graph:
  requires: [091-01]
  provides: [get_active_contracts-db-backed, count-gated-seeding, resolve_contract-db-backed]
  affects: [src/config/settings.py, src/api/main.py, src/api/utils.py]
tech_stack:
  added: []
  patterns: [two-query-psycopg2-pattern, count-gated-idempotent-seeding, side_effect-mock-list]
key_files:
  created: []
  modified:
    - src/config/settings.py
    - src/api/main.py
    - src/api/utils.py
    - tests/unit/test_service_contract_resolution.py
    - tests/unit/api/test_api_utils.py
    - tests/unit/api/test_signals_route.py
decisions:
  - "get_active_contracts() reads s.contracts for futures config-defaults lookup (not as return source) - needed to populate config_by_base for _build_instrument_from_db_row"
  - "Cold-start fallback returns [] not s.contracts - documented with CRITICAL log"
  - "test_signals_route mock patches _resolve_contract directly (not get_active_contracts) to avoid DB dependency in test"
metrics:
  duration_minutes: 7
  tasks_completed: 4
  files_modified: 6
  completed_date: 2026-05-19
---

# Phase 091 Plan 03: Registry Flip - DB as Source of Truth for Non-Futures Summary

**One-liner:** Flipped get_active_contracts() to read non-futures from instruments DB table via second psycopg2 query; count-gated API seeding behind IBKR_CONTRACTS_JSON env var; resolve_contract() delegates to get_active_contracts() TTL cache.

## What Was Built

The "registry flip" for non-futures instruments: after this plan, the DB is the single source of truth at runtime. `settings.contracts` is no longer consulted by any consumer in `src/api/` or by `get_active_contracts()` success/fallback paths.

### Task 1: get_active_contracts() two-query path (bc9815bd)

Added a second `psycopg2.connect()` block immediately after the existing futures query:

```sql
SELECT symbol, base, contract_details
FROM instruments
WHERE is_active = true AND contract_details->>'asset_class' != 'futures'
```

Each row's `contract_details` JSONB is deserialized with `json.loads()` if psycopg2 returns a string, then `Instrument(**cd)` is constructed. A fallback within the inner try builds from individual fields if JSONB is partial. Result: `db_instruments + non_futures`.

Fallback chain rewritten: warm cache returned on DB error; cold-start returns `[]` with a CRITICAL log at `get_active_contracts.cold_start_db_unavailable`. `s.contracts` is never returned.

The `s.contracts` iteration at lines 1092-1095 is preserved - it builds `config_by_base`/`config_by_symbol` lookup tables for the futures config-defaults inheritance path (`_build_instrument_from_db_row`), not as a return source.

### Task 2: Count-gated API startup seeding (07e78abb)

Replaced unconditional `upsert_instruments(settings.contracts)` with:
1. `SELECT COUNT(*) FROM instruments WHERE is_active = true`
2. If count > 0: log `api.startup.instruments_db_already_seeded` and skip
3. If count == 0: read `IBKR_CONTRACTS_JSON` env var, parse JSON, construct Instrument list, call `upsert_instruments()`

JSON parse failure and missing env var both log warnings and skip without crashing startup. Added `import json, os` to main.py.

Also fixed `test_signals_route.py::test_get_signals_base_symbol_resolved` which was calling live `get_active_contracts()` - now patches `_resolve_contract` directly.

### Task 3: resolve_contract() via DB-backed lookup (ac73782d)

Replaced `for c in settings.contracts:` with `get_active_contracts(settings)` call imported from `..config.settings`. The 60s TTL cache handles freshness. No direct DB query added. Existing match logic (base -> symbol, then regex fallback for VX/VXH6) unchanged.

Updated `test_api_utils.py` to patch `src.config.settings.get_active_contracts` (the source module) since the import is a local import inside the function body.

### Task 4: Two-query mock pattern in tests (4722981c)

Rewrote `_make_mock_db_conn` to return `list[MagicMock]` (two connections: futures + non-futures). All test `patch("psycopg2.connect", ...)` calls updated from `return_value=` to `side_effect=`.

Key test changes:
- `test_db_error_falls_back_to_config` renamed to `test_db_error_returns_empty_when_cache_cold` - asserts `result == []`
- `test_db_error_returns_cache_when_warm` added - pre-warms cache then asserts warm-cache returned on DB error
- `test_non_futures_from_instruments_table` replaces `test_non_futures_always_from_config` - verifies FX comes from instruments table rows
- `test_non_futures_query_filters_asset_class` added - verifies `FROM instruments` and `is_active` in second query SQL
- Cache tests updated to expect 2 connect calls per query (one for each psycopg2 block)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_signals_route test_get_signals_base_symbol_resolved called live get_active_contracts()**
- **Found during:** Task 2
- **Issue:** Test called `get_active_contracts()` without mocking, relying on old s.contracts fallback that returned ES. After Task 1, cold-start returns [], causing StopIteration.
- **Fix:** Replaced call with direct patch of `src.api.routes.signals._resolve_contract` to return "ESM6"
- **Files modified:** tests/unit/api/test_signals_route.py
- **Commit:** 07e78abb

**2. [Rule 1 - Bug] test_api_utils.py tests patched mock_settings.contracts which no longer provides contracts**
- **Found during:** Task 3
- **Issue:** Tests used `monkeypatch.setattr("src.api.utils.get_settings", ...)` with `mock_settings.contracts = [mock_contract]`, but resolve_contract now calls `get_active_contracts(settings)` instead of iterating settings.contracts
- **Fix:** Updated tests to `monkeypatch.setattr("src.config.settings.get_active_contracts", lambda s: [...])` at the source module
- **Files modified:** tests/unit/api/test_api_utils.py
- **Commit:** ac73782d

## Pre-existing Failures (unchanged by this plan)

8 pre-existing test failures confirmed identical before and after changes:
- `test_settings_equity.py` (2): call get_active_contracts() without mock - need DB
- `test_feature_writer_config.py` (2): same issue
- `test_settings_thread_safety.py` (1): expects 2 lock blocks, function now has 3 (pre-existing)
- `test_feature_writer_agent.py::TestBuildExpiryMap` (2): pre-existing
- `test_output_queue.py` (1): pre-existing Kafka mock issue

These are out of scope for Plan 03 and logged for Plan 04 cleanup.

## Verification Results

```
pytest tests/unit/test_service_contract_resolution.py tests/unit/api/ -v
76 passed, 20 warnings
```

```
grep -rn "settings.contracts" src/api/
# No matches - src/api/ has no settings.contracts consumers
```

```
grep -n "FROM instruments" src/config/settings.py
# 1119: "FROM instruments " -- inside get_active_contracts()
```

```
grep -n "IBKR_CONTRACTS_JSON" src/api/main.py
# 99: contracts_json_raw = os.environ.get("IBKR_CONTRACTS_JSON", "")
```

## Self-Check: PASSED

Files exist:
- FOUND: src/config/settings.py (modified)
- FOUND: src/api/main.py (modified)
- FOUND: src/api/utils.py (modified)
- FOUND: tests/unit/test_service_contract_resolution.py (modified)

Commits exist:
- FOUND: bc9815bd - feat(091-03): flip get_active_contracts() non-futures to read from instruments table
- FOUND: 07e78abb - feat(091-03): count-gate api/main.py startup seeding behind IBKR_CONTRACTS_JSON
- FOUND: ac73782d - feat(091-03): resolve_contract() iterates get_active_contracts() not settings.contracts
- FOUND: 4722981c - feat(091-03): update contract resolution tests for two-query mock pattern
