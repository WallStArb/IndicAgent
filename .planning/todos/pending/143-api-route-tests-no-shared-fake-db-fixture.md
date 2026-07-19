---
status: pending
priority: P3
filed: 2026-07-19
source: /simplify altitude review after todo 137's smoke test
---

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
