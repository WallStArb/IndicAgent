---
status: pending
priority: P1
filed: 2026-10-06
source: 185 session, found while closing 185-18
---

# Unit tests can still spawn live writers: add a CI guard

## What

Three unit-level leaks reached the live database during 185-18: test_nightly_lease ran a real
`bar_derivation --stage grid --apply` (nine runs, 2026-10-03), test_ohlcv_observation_store appended
permanent fixture rows to the live D1 ledger on every run (27 rows on SPY, now excluded from D2 by caller),
and tests/unit/scripts/test_ohlcv_coverage_atomic_write.py still writes to the live database with a
self-cleaning sentinel. Each was fixed one by one; the class is open.

## Fix

A conftest-level guard for tests/unit/: patch subprocess.run/Popen to refuse a command naming
services/bar_derivation.py, the pipeline or ops scripts unless the test opts in, and a boundary test that
no tests/unit file connects to the live DSN (5432/indicagent without _test) with a write statement, allow-list
with a reason like the market_data_ohlcv boundary test. Move the atomic-write test to indicagent_test.

## Guard landed (research lane, 2026-11-01)

Two conftest guards in tests/unit/conftest.py plus the static boundary test
tests/unit/test_live_db_write_boundary.py:

- `_refuse_live_writer_spawns`: subprocess.run/Popen/call/check_call/check_output naming a live
  writer (`bar_derivation`, `feature_vector_pipeline`, `scripts/ops`, `scripts.ops`) raise with a
  todo 494 message; a test opts out with the `live_writer_subprocess` marker. The third incident's
  fix predates this (the atomic-write test moved to tests/integration in plan 185-39).
- `_live_dsn_connections_are_read_only`: psycopg.connect and asyncpg.connect are wrapped; a
  connection to the live `indicagent` database (not `indicagent_test`) gets
  `SET default_transaction_read_only = on`, so a write statement fails loud. Advisory locks and
  session SETs are not writes, so the lock tests keep working. Opt-out is the `live_db` marker.

The guard caught a fourth leak immediately: `test_bar_source_policy_retirement.py` and
`test_bar_derivation_policy_change_sql.py` run DDL and fixture writes against the live database
(self-rolling-back: TEMP copies and shadow tables inside a transaction the fixture always aborts,
the real trigger function included). Both carry the `live_db` marker with the design documented;
nothing persists. The boundary test allow-lists every tests/unit file holding a live-DSN literal
with its reason (ten files: three marker-carrying, five read-only, two mock-only literals), fails
on a new unlisted literal and on a stale entry, and checks the conftest guards exist.

Markers registered in pytest.ini. Known limit, stated in the boundary test's docstring: a write
through a driver the conftest does not patch would reach the live database; a new driver in
tests/unit is a conftest change, not a test-local connect.

Done when all three bullets are closed: the subprocess guard and the boundary test are this todo;
the atomic-write move landed in 185-39. Remaining: none in code; the todo closes with this entry.
