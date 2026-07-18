---
status: completed
priority: P2
filed: 2026-07-17
resolved: 2026-07-18
source: phase 161 execution (161-04) — found while building the analogous /api/vocabulary route
---

# `GET /api/drift` throws ImportError on every request

## Finding

`src/api/routes/drift.py` imports a module-level `get_connection` from
`src/core/database_manager.py`. That symbol doesn't exist there — `database_manager.py` only
exposes `DatabaseManager.get_connection()` as an instance method. Every real request to
`GET /api/drift` currently raises an uncaught `ImportError` at import/call time.

Found while building `161-04`'s `/api/vocabulary/{namespace}` route, which used `drift.py` as
its stated analog. The 161-04 executor did not copy the broken pattern — it used the working
`Depends(get_db_manager)` pattern from `features.py` instead — so this bug is pre-existing and
outside 161-04's scope.

## Fix

Swap the module-level `get_connection` import for `Depends(get_db_manager)` (or equivalent),
matching the working pattern in `src/api/routes/features.py` and the new
`src/api/routes/vocabulary.py`. Small, contained fix — one file, no schema/migration involved.

## Resolution

Fixed via systematic-debugging + TDD: confirmed root cause (function-local import of a
nonexistent module-level symbol, raised before the route's own `try/except` could catch it),
wrote a failing regression test first (`tests/unit/api/test_drift_route.py`, red against the
broken import), then swapped to `Depends(get_db_manager)` + `db_manager.fetch(...)` mirroring
`vocabulary.py`. `/simplify` pass (4 parallel review agents) found and fixed one real
inefficiency in the pre-existing row loop (redundant `.isoformat()` calls / dict construction
per row); reuse and altitude passes were clean, altitude surfaced two follow-up gaps filed as
todos [137](../pending/137-api-routes-no-request-level-smoke-test.md) (no route-level smoke
test would catch this bug class elsewhere) and
[138](../pending/138-drift-route-swallows-db-errors-as-healthy-empty.md) (the route's
except-and-swallow makes a real DB outage indistinguishable from "no drift"). Full unit suite
green (`tests/unit/` — 3 pre-existing unrelated skips only).
