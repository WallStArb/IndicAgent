---
status: fixed
priority: P0
filed: 2026-08-04
fixed: 2026-08-04
source: found running todo 253's authoritative-tier fix -- forward_return_writer.py failed on
  every single cell of the first real invocation against a non-empty forward_returns table
---

# `forward_return_writer.py`'s high-water-mark computation used a parameterized `INTERVAL`
# literal -- fails with a SQL syntax error on every incremental (non-first) run

## What

`_label_symbol_tf`'s high-water-mark logic (recompute the tail window on a subsequent run so
previously-incomplete rows get completeness updates) issued:

```python
cur.execute(
    "SELECT %s::timestamptz - INTERVAL %s",
    (max_bar_ts, f"{lookback_minutes} minutes"),
)
```

PostgreSQL does not accept a bind parameter as an `INTERVAL` literal this way --
`syntax error at or near "$2"`. This branch only executes when `max_bar_ts is NOT None`, i.e.
`forward_returns` already has at least one row for that (symbol, tf) -- every genuinely
incremental run, not a first-time backfill.

## How this was found

Running todo 253's authoritative-tier `forward_return_writer.py` invocation (populate the OOS
region for Phase 167's re-verification) against the live 15m equity universe: every single one
of 80 cells failed identically with this exact syntax error, confirmed in `logs/forward_return_writer.log`.

## Why this was never caught before

Requires a live DB with pre-existing `forward_returns` rows for the (symbol, tf) being processed
-- unit tests mock the connection and never exercise this branch's actual SQL against a real
Postgres backend (CLAUDE.md gotcha: "never trust a read-only test for a write-path question").
Every real corpus run in recent memory started from a freshly `TRUNCATE`d `forward_returns`
(`scripts/infrastructure/backfill/infrastructure_truncate_derived_tables.sh`, run repeatedly
during recent corpus-rebuild cycles -- todo 208's ET-session-boundary fix, this investigation's
own corpus questions), so `max_bar_ts` was always `NULL` and the buggy branch was never actually
executed end-to-end until this run.

## Fix -- APPLIED 2026-08-04

Eliminated the SQL round-trip entirely rather than fixing the parameterization: `max_bar_ts` is
already a native Python `datetime` (psycopg adapts `timestamptz` columns directly), so computing
`max_bar_ts - timedelta(minutes=lookback_minutes)` is plain Python arithmetic with zero reason to
ask Postgres to do it. Extracted into a standalone pure function, `_compute_high_water_mark()`,
directly unit-testable without a DB connection (matching this file's existing pattern of testing
pure computation separately from I/O). `_TF_MINUTES` promoted from a function-local dict rebuilt
on every call to a module-level constant.

3 new regression tests (`tests/unit/test_forward_return_writer.py`): epoch-on-first-run,
correct `(max_n + 1) * minutes_per_bar` arithmetic across all 4 tfs, and the return type staying
a native `datetime` (not accidentally stringified) on the non-epoch branch. Full `tests/unit/`
suite green (27/27 in this file, no regressions elsewhere), ruff/black clean.

## Blast radius

Confined to the high-water-mark tail-window recompute on incremental runs -- the SQL that
actually computes and inserts forward returns (`_build_forward_return_sql`,
`_build_insert_sql`) was never affected; those queries build and execute independently of this
bug. No corpus data was written incorrectly -- every affected cell failed loudly (exception,
caught per-cell, logged, moved to the next symbol) rather than silently producing wrong rows,
consistent with this project's "silent wrong answers are worse than loud crashes" principle.
Zero blast radius on any existing `forward_returns` row.

## Cross-refs

- [todo 253](253-forward-returns-frozen-at-oos-boundary-corpus-rebuild-skipped-step3.md) -- the
  investigation that surfaced this; todo 253's own authoritative-tier run is what hit the bug
