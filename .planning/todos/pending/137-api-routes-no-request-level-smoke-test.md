---
status: pending
priority: P2
filed: 2026-07-18
source: /simplify altitude review during todo 130's fix (drift.py broken import)
---

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
