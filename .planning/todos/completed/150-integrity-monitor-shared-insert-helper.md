---
status: completed
priority: P3
filed: 2026-07-19
source: /simplify altitude + reuse review of todo 148's forward_return_writer.py
  integrity_monitor fact emission
---

**Closed 2026-07-19:** extracted `emit_integrity_fact_sync`/`emit_integrity_fact_async`
into new Ring 0 module `src/core/integrity_monitor.py`. Two variants (not one) because
the 4 call sites split across sync psycopg2 (`ic_engine.py`, `forward_return_writer.py`)
and asyncpg (`vocabulary_drift.py`) connections with incompatible APIs. Guard behavior
(log-and-swallow on failure) and the `ON CONFLICT` SQL constant now live in exactly one
place. `idempotency_check` defaults off and is opt-in per call site: `ic_engine.py`'s two
sites already sit behind `_run_lifecycle_hook`'s own Step-0 pre-check one frame up (a
second check would be redundant, not wrong); `vocabulary_drift.py` intentionally records
one fact per run for calibration history rather than being idempotent; only
`forward_return_writer.py`'s price-sanity fact opts in, matching its original behavior.
`ic_engine.py`'s `guard_fail_fraction` batch site (`cur.executemany(...)`, ~30 rows per
deferred transaction) deliberately was NOT routed through the single-row helper --
doing so would have broken its one-executemany-then-one-commit atomicity and swallowed
a failure that must abort the whole transaction instead. It reuses the same
`INTEGRITY_MONITOR_INSERT_SQL` constant directly, so the fragile `ON CONFLICT` clause
still has exactly one source of truth either way.

# `integrity_monitor` INSERT is hand-copied at 4 independent call sites -- extract a
# shared helper

## Problem

The exact `INSERT INTO integrity_monitor (...) ON CONFLICT (monitor_type,
training_window_end, metric_name, COALESCE(subject, ''), evaluated_at) DO NOTHING`
statement shape is now independently reimplemented at 4 call sites:

- `services/ic_engine.py` (~line 2771-2782, `ic_lifecycle` monitor_type)
- `services/ic_engine.py` (~line 3050-3060, second call site)
- `src/config/vocabulary_drift.py` (~line 181-184, `vocabulary_drift` monitor_type)
- `services/forward_return_writer.py` `_emit_price_sanity_fact` (todo 148,
  `price_sanity` monitor_type) -- the 4th copy, added this session

None of the first 3 factored this into a shared helper either, so each addition has
copy-pasted the same fiddly composite `ON CONFLICT` clause (including the
`COALESCE(subject, '')` normalization) independently. Four independent hand-written
copies of a key constraint this specific is a correctness risk (a future copy
drifting from the real unique index), not just a style complaint.

## Fix

Extract `emit_integrity_fact(conn, monitor_type, subject, metric_name, metric_value,
threshold_value, passed, training_window_end)` as a shared helper (Ring 0 or Ring 1 --
no domain vocab needed, just a typed wrapper over one INSERT). Migrate the 4 existing
call sites to it. Guard behavior (log-and-continue on failure, never corrupt the
already-committed primary write) should live in the helper once, not be re-derived at
each call site.

## Sizing

Todo-sized: one new function, 4 call-site swaps, no schema change (the table and its
unique index already exist as of migration 211).

## References

- `production/migrations/211_integrity_monitor.sql` -- table + unique index
- `services/ic_engine.py`, `src/config/vocabulary_drift.py`,
  `services/forward_return_writer.py` -- the 4 call sites to consolidate
