---
status: pending
priority: P3
filed: 2026-07-17
source: altitude finding from /simplify review of todo 128 (ic_engine cross-sectional
  connection-lifecycle fix); narrowed 2026-07-17 after a /simplify pass on todo 130's
  diff resolved the Settings-based half
---

# `ic_engine.py`'s 3 dsn-based worker connections still hand-rolled — extract a shared helper

## Problem (narrowed 2026-07-17 — main()-side half already fixed)

Originally filed against 5 hand-rolled `open → use → close` connection blocks: 3 dsn-based
ones inside worker functions (`_compute_symbol_tf` x2, `_compute_cross_sectional_tf` x1) plus
2 Settings-based ones in `main()` (`regime_list_conn`, `lifecycle_conn`). Todo 130's diff (same
day) added 4 more Settings-based instances of the same shape (`_write_symbol_results`,
`_write_cs_cell_results`, `backfill_conn`, `stats_conn`), growing the main()-side count to 6.

A `/simplify` pass on that diff (2026-07-17) added `_short_lived_conn(settings)` — a
`@contextmanager` right next to `_connect_db`, matching the file's existing `_observed_span`
idiom — and migrated all 6 Settings-based call sites onto it (`_write_symbol_results`,
`_write_cs_cell_results`, the checkpoint-resume loop, `regime_list_conn`,
`backfill_conn`/`stats_conn`/`lifecycle_conn` merged into one shared connection since they run
back-to-back with no intervening compute). That resolves the duplication and the
missing-try/finally gap for the main-process side.

**Still open:** the 3 dsn-based worker-side connections (`_compute_symbol_tf` x2,
`_compute_cross_sectional_tf` x1) are untouched — deliberately, not an oversight. Those
functions run inside a `ProcessPoolExecutor` worker (hence `dsn: str`, not `Settings`, since a
live connection/Settings object can't cross the process boundary) and are the multi-hour
compute-critical path a corpus run is actively executing against as of this same session —
too high-blast-radius to touch outside a dedicated, tested change. None of the 3 wrap their
fetch in `try/finally`, so an exception mid-fetch still leaks the connection in all three.

## Fix (not yet done)

Extract a shared `@contextmanager def short_lived_conn(dsn: str)` helper (natural home:
`services/_batch_utils.py`, next to `connect_db_from_url`) and migrate the 3 remaining
dsn-based call sites onto it, adding the missing `try/finally` in the process.

## References

- `services/ic_engine.py` — `_compute_symbol_tf` (todo 102), `_compute_cross_sectional_tf`
  (todo 128), `_short_lived_conn` (the new Settings-based helper, for reference/naming
  consistency)
- `services/_batch_utils.py` — `connect_db_from_url`, natural home for the new helper
- `.planning/todos/completed/102-...md`, `.planning/todos/completed/128-...md`,
  `.planning/todos/completed/130-...md`
