---
phase: 182-security-classification-hierarchy-todo-384
plan: 05
subsystem: config
tags: [classification, instruments, sector, psycopg, asyncpg, reference-data]

# Dependency graph
requires:
  - phase: 182-01
    provides: "current_level_name_sql(), label_or_unclassified(), unclassified_code() in src/config/classification_service.py; instrument_classification / classification_node tables"
provides:
  - "get_active_contracts() and get_all_futures_contracts() build Instrument.sector from the indicagent_v1 level-2 node name, or indicagent_v1:unclassified (D-10, D-08)"
  - "cache_manager._instrument_from_row() sets sector from a classification_sector column selected by _reload_instruments_cache() (D-10)"
  - "src/api/routes/signals.py sector grouping inherits the fix with no edit"
affects: [182-06, 182-07]

tech-stack:
  added: []
  patterns:
    - "Classification read as one extra correlated scalar-subquery column on queries the builders already run, not via a process-global ClassificationService (no prewarm dependency in sync psycopg callers)"
    - "Classification module imported lazily inside settings.py functions, same as psycopg, so importing settings does not pull in asyncpg/database_manager/OTel metrics"

key-files:
  created: []
  modified:
    - src/config/settings.py
    - src/intelligence/pipeline/cache_manager.py
    - tests/unit/config/test_settings_active_contracts_dimension.py
    - tests/unit/services/test_service_contract_resolution.py
    - tests/unit/pipeline/test_cache_manager.py
    - .planning/phases/182-security-classification-hierarchy-todo-384/deferred-items.md

key-decisions:
  - "get_all_futures_contracts() also moved onto the classification: it parsed the same futures templates with Instrument(**cd), so leaving it would have kept a second sector definition. Template query and parsing extracted into _futures_template_sql() / _index_futures_templates(), shared by both functions."
  - "Sector override applied as Instrument(**{**cd, 'sector': ...}) so every other contract_details field still flows through unchanged; the fallback constructor path uses the same computed value."
  - "Row column 4 is indexed strictly (row[3]); every real query selects it, and a shape mismatch should surface rather than silently default."
  - "tests/unit/config/test_settings_equity.py needed no change: it patches get_active_contracts wholesale and never exercises the row builders."

requirements-completed: [D-10, D-08]

duration: 12min
completed: 2026-09-25
---

# Phase 182 Plan 05: Instrument.sector from the classification Summary

Both `Instrument.sector` builders (`get_active_contracts()` and `cache_manager._instrument_from_row()`) now read the level-2 node name of the symbol's current indicagent_v1 assignment through `current_level_name_sql("instruments")`, and fall back to `indicagent_v1:unclassified`, never `contract_details->>'sector'`.

## Performance

- Duration: about 12 min
- Completed: 2026-09-25
- Tasks: 2
- Files modified: 6

## Accomplishments

- `get_active_contracts()`: the futures-template query and the non-futures query each select the classification fragment as a 4th column; non-futures rows (both the `Instrument(**cd)` path and the explicit fallback constructor) set `sector = label_or_unclassified(row[3])`; front months inherit their template's classified sector via `model_copy`; a front month with no template gets `unclassified_code()`.
- `get_all_futures_contracts()` shares the same template helper, so it agrees with `get_active_contracts()`.
- `cache_manager._reload_instruments_cache()` selects `... AS classification_sector`; `_instrument_from_row()` reads it with the unclassified fallback when NULL or absent.
- Live smoke (migration 365 not yet applied, `instrument_classification` empty): `get_active_contracts(dimension='backfill')` returns 273 instruments, all with sector `indicagent_v1:unclassified`, no crash.
- Remaining `contract_details->>'sector'` reads in `src/` and `services/`: only `src/intelligence/research/snapshot.py` (frozen provenance, out of scope per Pitfall 5), plus a docstring mention in settings.py.

## Task commits

1. Task 1: get_active_contracts reads sector from the classification
   - `a2c641a64` test (RED)
   - `c09540771` feat (GREEN)
2. Task 2: cache_manager reads sector from the classification
   - `082c85b06` test (RED)
   - `20ff3a98f` feat (GREEN), includes the deferred-items entry

## Deviations from plan

### Auto-fixed issues

**1. [Rule 2 - Missing critical functionality] get_all_futures_contracts also read the flat sector**
- Found during: Task 1
- Issue: it built futures templates with `Instrument(**cd)`, carrying `contract_details.sector` into every futures Instrument it returned, a second sector definition the plan did not list.
- Fix: extracted `_futures_template_sql()` and `_index_futures_templates()`; both functions use them.
- Files modified: src/config/settings.py
- Commit: c09540771

**2. Test fixture adjustments**
- The fallback-constructor test triggers the fallback by removing `symbol` from contract_details (Instrument ignores unknown keys, so an extra key does not trigger it).
- The cache_manager fixture carries `session_id: "nyse"` because `_instrument_from_row`'s default `"equity_regular"` is not a registered session (logged as deferred, see below).

## Deferred issues

- `cache_manager._instrument_from_row` defaults `session_id` to `"equity_regular"` and settings.py's fallback constructor to `"equity_rth"`; neither is in `SESSION_REGISTRY`. Logged in `deferred-items.md`, not fixed (unrelated to sector).

## Notes for downstream plans

- `signals.py:838` groups by `c.sector or c.asset_class.value`. Sector is now never empty, so the asset_class fallback no longer fires; until Plan 07 seeds the classification, every symbol groups under `indicagent_v1:unclassified`. Expected per the plan; the endpoint belongs to the archived pipeline.
- `get_active_contracts` caches for 60 s per dimension, so a running process picks up Plan 07's seed within a minute.

## Threat flags

None. The only interpolated SQL is `current_level_name_sql("instruments")` with a hardcoded alias, validated by Plan 01's function (T-182-17).

## Self-Check: PASSED

- Files: all modified files exist
- Commits: a2c641a64, c09540771, 082c85b06, 20ff3a98f present in git log

Publish note: the post-rebase full unit run had one failure, `tests/unit/research/test_portfolio_r1.py::test_rank_vol_neutral_returns_meets_performance_target` (phase 183, a 2.0s wall-clock budget, measured 3.99s/4.69s while a concurrent session held several cores at 100%). It does not import any module this plan touched; every other test passed.
