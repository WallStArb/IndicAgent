---
status: pending
priority: P2
filed: 2026-07-17
source: altitude finding from /simplify review of todo 128 (ic_engine cross-sectional
  connection-lifecycle fix)
---

# `ic_engine.py` has 5 hand-rolled short-lived-connection blocks — extract a shared helper

## Problem

Todo 128 fixed `_compute_cross_sectional_tf` by applying the same "open short-lived
connection → fetch → close before compute" pattern already used in `_compute_symbol_tf`
(todo 102). That's now 3 hand-written instances of the identical shape in this one file,
plus 2 more one-off short-lived connections in `main()` (`regime_list_conn`,
`lifecycle_conn`) — 5 total, each written by hand with slightly different try/finally
discipline. None of the 3 fetch-phase blocks (`_compute_symbol_tf` x2, `_compute_cross_sectional_tf`
x1) wrap the fetch in `try/finally` — an exception mid-fetch leaks the connection instead of
closing it, in all three.

This is the second time the "don't hold a connection across compute-only phases" bug class has
had to be hand-fixed in this file (todo 102 → 128). Nothing structurally prevents a third
recurrence in a future function.

## Fix (not yet done)

Extract a shared `@contextmanager def short_lived_conn(dsn: str, tune_sql: list[str] | None = None)`
helper into `services/_batch_utils.py` (natural home — `connect_db_from_url` already lives
there). Migrate all 5 call sites in `ic_engine.py` onto it. This closes both the duplication
and the missing-try/finally gap structurally, rather than relying on the next person who
touches this file to notice and hand-copy the pattern correctly a fourth time.

## References

- `services/ic_engine.py` — `_compute_symbol_tf` (todo 102), `_compute_cross_sectional_tf`
  (todo 128), `main()`'s `regime_list_conn`/`lifecycle_conn`
- `services/_batch_utils.py` — `connect_db_from_url`, natural home for the new helper
- `.planning/todos/completed/102-...md`, `.planning/todos/completed/128-...md`
