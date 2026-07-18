---
status: pending
priority: P2
filed: 2026-07-17
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
