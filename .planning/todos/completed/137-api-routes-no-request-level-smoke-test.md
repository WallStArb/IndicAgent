---
status: completed
priority: P2
filed: 2026-07-18
closed: 2026-07-19
source: /simplify altitude review during todo 130's fix (drift.py broken import)
---

## Resolution

Added `tests/unit/api/test_api_routes_smoke.py`: builds a minimal FastAPI app from
the same routers `src/api/main.py` registers (excluding `sse.router` -- `/api/sse/events`
is an infinite SSE stream, structurally incompatible with a single-request check),
mocks `get_db_manager` with a fake that mirrors `DatabaseManager`'s async interface,
and hits all 29 registered GET routes, asserting none returns 500.

Building the fake DB double surfaced a real, unrelated bug it was designed to catch
a *different* class of: `GET /api/market-data/{symbol}/{timeframe}` raises its own
`HTTPException(404)` inside a `try` block whose `except Exception` re-caught it and
re-wrapped it as a 500 -- a legitimate 404 masquerading as a server error, same
silent-failure shape as todo 138. Fixed with the `except HTTPException: raise` guard
already used by `narrative.py`/`ai_stats.py`/`validation.py`/`signals.py` for the
same pattern, plus a regression test (`tests/unit/api/test_market_data_route.py`).

Full `tests/unit/` suite (4191 tests) still green after the change.

# No generic guard catches a broken function-local import in an API route

## Finding

Todo 130's bug (`src/api/routes/drift.py` importing a nonexistent `get_connection`
symbol) survived undetected because the bad import was inside the function body
(`from src.core.database_manager import get_connection`), not at module scope. An
import-time smoke test (`import src.api.main`) would not have caught it — it only
raised on an actual request. `drift.py` now has a request-level regression test
(`tests/unit/api/test_drift_route.py`), but that only closes the gap for this one
route. The same bug class (a function-scoped import that's wrong, only triggered at
request time) could recur in any other route under `src/api/routes/`.

## Fix

A lightweight parametrized test that iterates every router registered in
`src/api/main.py`, builds a minimal test app with mocked dependencies
(`dependency_overrides` for `get_db_manager`/`get_kafka_broadcaster`), hits each
GET route once, and asserts the response is not a 500. Doesn't need to assert
response shape — just that the route doesn't blow up on import/first invocation.

## Gate

None, independent, small change.
