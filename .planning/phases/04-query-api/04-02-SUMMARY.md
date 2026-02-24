---
phase: 04-query-api
plan: 02
subsystem: api
tags: [fastapi, postgresql, timescaledb, signal_ledger, intelligence_features, tdd]

# Dependency graph
requires:
  - phase: 02-feature-store
    provides: intelligence_features hypertable with tiered JSONB (bar/i1/i3/i4/i5/smc/i6)
  - phase: 03-historical-data
    provides: signal_ledger rows with feature_ts/feature_tf JOIN columns populated
provides:
  - GET /api/signals/{symbol} — signal history from signal_ledger (7 columns)
  - GET /api/signals/{symbol}?include_features=true — signals with LEFT JOIN to intelligence_features feature context
  - Base symbol resolution (ES → ESH6) via Settings.contracts
affects: [05-auth, 06-ml-scoring, dashboard-sse]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - test-local FastAPI app pattern (avoid main.py lifespan in unit tests)
    - dependency override via test_app.dependency_overrides[get_db_manager]
    - _DictRow helper for asyncpg Record-like access in mock rows

key-files:
  created:
    - src/api/routes/signals.py
    - tests/unit/api/test_signals_route.py
  modified: []

key-decisions:
  - "features key omitted from signal response when include_features=False (not present at all, not null)"
  - "NULL feature_ts → signal['features'] = None; non-null feature_ts → nested dict with parsed JSONB tiers"
  - "limit is $2 positional param (used in LIMIT $2 clause); from_ts=$3, to_ts=$4 — consistent with param ordering in both query branches"
  - "_parse_jsonb handles both str (asyncpg JSONB as string) and dict (already parsed) transparently"

patterns-established:
  - "test-local FastAPI app: from src.api.routes.X import router; test_app = FastAPI(); test_app.include_router(router, prefix='/api') — avoids lifespan"
  - "_DictRow(dict) subclass for mock asyncpg rows: supports both row['key'] and row.key access patterns"
  - "dependency override reset via test_app.dependency_overrides[dep] = lambda: mock in each test helper"

requirements-completed: [API-02]

# Metrics
duration: 2min
completed: 2026-02-24
---

# Phase 4 Plan 2: Signal History Route Summary

**FastAPI GET /api/signals/{symbol} with conditional LEFT JOIN to intelligence_features, TDD-driven with 7 unit tests covering base query, feature JOIN, NULL feature_ts safety, limit forwarding, empty result, and base symbol resolution**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-02-24T11:33:25Z
- **Completed:** 2026-02-24T11:35:34Z
- **Tasks:** 2 (RED + GREEN)
- **Files modified:** 2

## Accomplishments
- Implemented `GET /api/signals/{symbol}` with two query modes: base signal history and full feature context via LEFT JOIN
- NULL feature_ts signals (pre-Phase-2) correctly return `features: null` without crashing
- Base symbol resolution (ES → ESH6) via Settings.contracts lookup before DB query
- All 7 TDD unit tests pass; 0 ruff errors; full unit suite at 593 passing

## Task Commits

Each task was committed atomically:

1. **Task 1: RED — failing tests for signals route** - `74006bc` (test)
2. **Task 2: GREEN — implement signals.py** - `fe57f3d` (feat)

_TDD plan: RED commit (ImportError) → GREEN commit (7/7 pass)_

## Files Created/Modified
- `src/api/routes/signals.py` — GET /api/signals/{symbol} router with optional include_features LEFT JOIN
- `tests/unit/api/test_signals_route.py` — 7 unit tests, test-local FastAPI app pattern

## Decisions Made
- `features` key is omitted entirely when `include_features=False` (not set to null) — matches plan spec "does NOT include features key"
- NULL `feature_ts` short-circuits to `signal["features"] = None` before reading any feature column — prevents KeyError on pre-Phase-2 signals
- `limit` is `$2` (LIMIT clause), `from_ts` is `$3`, `to_ts` is `$4` — both query branches use same param ordering
- `_parse_jsonb` handles str → json.loads and pass-through for dict (future-proof if asyncpg returns native dict)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Signal history endpoint is functional and tested
- Router needs to be registered in `src/api/main.py` (planned for 04-03 or as part of auth integration in Phase 5)
- `include_features=true` query requires intelligence_features data to be populated (Phase 3 backfill)

## Self-Check: PASSED

- FOUND: src/api/routes/signals.py
- FOUND: tests/unit/api/test_signals_route.py
- FOUND: 04-02-SUMMARY.md
- FOUND: 74006bc (RED commit — test)
- FOUND: fe57f3d (GREEN commit — feat)

---
*Phase: 04-query-api*
*Completed: 2026-02-24*
