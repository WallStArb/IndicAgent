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
