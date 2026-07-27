---
status: closed
priority: P3
filed: 2026-07-19
closed: 2026-07-27
source: /simplify altitude review after todo 137's smoke test
---

## RESULT (2026-07-27): fixed, with a scope revision from the original ask.

By the time this was picked up, the actual duplication landscape had shifted since filing --
re-surveyed `tests/unit/api/` (13 files now touch some form of DB fake, not 4) and found 3
genuinely distinct patterns, not near-duplicates of one design:
1. `test_market_data_route.py`/`test_features_route.py`/`test_drift_route.py`/
   `test_vocabulary_api.py` -- identical `mock_db`/`client` fixture pair, each building its
   OWN minimal single-router `FastAPI()` instance out of a stated (and, on inspection, unfounded)
   worry about triggering `main.py`'s lifespan DB connection.
2. `test_api_routes_smoke.py`'s `_FakeConn`/`_FakePool`/`_FakeDatabaseManager` -- a fixed
   "always benign" fake for a route-smoke-test that hits every route once.
3. `test_narrative_route.py`'s `_FakeConn`/`_FakeAcquireCtx` -- a per-test-configurable fake
   (fetchrow_return/fetchrow_raises at construction) for testing specific 404/500/cached paths.

(2) and (3) solve genuinely different problems with genuinely different designs -- forcing a
single shared class hierarchy over both would be exactly the premature/wrong-fit abstraction
this project's principles warn against. Left both alone.

**What WAS fixed**: (1)'s worry is unfounded -- `TestClient(app)` only runs `lifespan()` when
used as a context manager (`with TestClient(app) as c:`), which none of these files do (all use
the bare non-context-managed form). Confirmed safe by `test_signals_api_detail.py`'s pre-existing
use of the real `src.api.main.app` this same way. Created `tests/unit/api/conftest.py` with
shared `mock_db`/`client` fixtures against the REAL app (better fidelity than 4 independent
minimal reconstructions, not just less code) and migrated all 4 files onto it, deleting their
local fixture definitions. Full `tests/unit/api/` suite green (139 tests) after the migration.

# `tests/unit/api/` has 4 independent hand-rolled DB test doubles, no shared conftest fixture

## Finding

`tests/unit/api/test_api_routes_smoke.py`'s `_FakeConn`/`_FakePool`/`_FakeDatabaseManager`
(todo 137) is the 4th independent DB test double in `tests/unit/api/` (after plain
`AsyncMock()` fakes in `test_market_data_route.py`, `test_features_route.py`,
`test_drift_route.py`) and the most complete one -- the only one implementing
`pool.acquire()`/`get_connection()` context-manager surface plus the args-present/absent
`fetchrow()` realism distinction (a bare aggregate query always returns exactly one row in
real Postgres; a parameterized WHERE-lookup can genuinely miss). No `tests/unit/api/conftest.py`
exists to share any of this.

## Fix

Extract `_FakeConn`/`_FakePool`/`_FakeDatabaseManager` into `tests/unit/api/conftest.py` as a
shared fixture, so future route tests (and ideally the 3 existing plain-`AsyncMock` files) get
the same connection-context-manager + aggregate-vs-lookup fidelity instead of each reinventing
a thinner mock.

## Gate

None, independent. Deliberately not done inline during todo 137 -- at the time only one file
in the diff would have consumed the shared fixture (test_api_routes_smoke.py itself);
promoting a single-consumer helper to conftest.py preemptively is speculative generalization.
Revisit once a second file would genuinely benefit (e.g. the next new API route test, or a
migration of the existing 3 plain-AsyncMock files).
