---
phase: 04-query-api
plan: 01
subsystem: api
tags: [fastapi, intelligence-features, parquet, tdd, query-api]
dependency_graph:
  requires:
    - intelligence_features hypertable (Phase 2)
    - src/api/dependencies.py (get_db_manager)
    - src/core/database_manager.py (DatabaseManager)
  provides:
    - GET /api/features/{symbol}/{timeframe} — paginated JSON with JSONB tiers parsed
    - GET /api/features/export — Parquet binary with tier columns expanded
    - src/api/routes/features.py (router export)
  affects:
    - requirements.txt (pyarrow added)
    - Future: main.py will include this router (Plan 03)
tech_stack:
  added:
    - pyarrow>=23.0.0 (Parquet serialization via pandas)
  patterns:
    - FastAPI router with explicit route ordering (export before path param)
    - JSONB string parsing via _parse_jsonb() helper
    - Base symbol resolution via _resolve_contract()
    - TDD: RED commit then GREEN commit
key_files:
  created:
    - src/api/routes/features.py
    - tests/unit/api/test_features_route.py
  modified:
    - requirements.txt
decisions:
  - "route ordering critical: /features/export registered before /features/{symbol}/{timeframe} to prevent FastAPI matching 'export' as {symbol} path param"
  - "test_app pattern: minimal FastAPI instance mounts router directly — avoids main.py lifespan startup (no DB/Redis in unit tests)"
  - "JSONB returned as dict always: _parse_jsonb() handles None, JSON string, and pre-parsed dict (asyncpg future-proofing)"
  - "router NOT wired into main.py in this plan — that is Plan 03's responsibility"
metrics:
  duration: 2min
  completed: 2026-02-24
  tasks_completed: 2
  files_created: 2
  files_modified: 1
---

# Phase 4 Plan 01: Intelligence Features Query Route Summary

**One-liner:** Paginated JSON query and Parquet export for intelligence_features hypertable via two FastAPI endpoints with JSONB tier parsing and route-ordering guard.

## What Was Built

- `src/api/routes/features.py` — FastAPI router with two endpoints:
  - `GET /features/export` — registered first; accepts `symbol` + `timeframe` as query params; streams a Parquet binary with all 7 JSONB tiers expanded into flat prefixed columns (e.g. `i4_garch_sigma`)
  - `GET /features/{symbol}/{timeframe}` — paginated JSON (default 100, max 1000); JSONB tiers returned as parsed dicts; supports `from`/`to` ISO 8601 date range filters
- `tests/unit/api/test_features_route.py` — 7 unit tests using `TestClient` with a local `test_app` (no lifespan) and `dependency_overrides` for `get_db_manager`
- `requirements.txt` — `pyarrow>=23.0.0` added after pandas line

## Task Execution

| Task | Type | Commit | Result |
|------|------|--------|--------|
| 1 RED: Write failing tests | TDD RED | ef88be1 | 7 tests, all fail ImportError |
| 2 GREEN: Implement features.py | TDD GREEN | d98be73 | 7 tests pass, 0 ruff errors |

## Success Criteria Verification

- [x] GET /api/features/{symbol}/{timeframe} returns paginated JSON with JSONB tiers as dicts (not strings)
- [x] GET /api/features/export returns application/octet-stream Parquet binary with tier columns expanded
- [x] /features/export route registered before /{symbol}/{timeframe} — no path collision (test_export_route_does_not_conflict_with_symbol_path passes)
- [x] 7 unit tests pass, 0 ruff errors
- [x] pyarrow>=23.0.0 in requirements.txt

## Deviations from Plan

None — plan executed exactly as written. The preferred test_app approach (local FastAPI + router mount) was used from the start.

## Self-Check

Verified files exist:
- `src/api/routes/features.py` — created
- `tests/unit/api/test_features_route.py` — created
- `requirements.txt` — modified with pyarrow

Verified commits:
- ef88be1 — test(04-01): add failing tests for features route
- d98be73 — feat(04-01): implement GET /api/features endpoints with Parquet export

## Self-Check: PASSED
