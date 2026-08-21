# 343 - Per-cell write-isolation pattern duplicated between `regime_writer.py` and `backfill_feature_factory.py`

**Filed:** 2026-08-21
**Source:** `/simplify`'s reuse-angle review of the full session's code diff (todos 318/251/300
combined).

## What

`services/backfill_feature_factory.py`'s `run_compute_stage()` aggregation loop (added this
session, todo 318 Bug 2) implements a "iterate `pool.map()` results, per-cell `try`/write/
`except: log + rollback + continue`" shape that is structurally near-identical to
`services/regime_writer.py`'s existing aggregation loop (`main()`, lines ~2545-2596) -- both
wrap the loop in `_write_session(write_conn, "feature_vectors")` + `_make_worker_pool`, both
isolate one cell's write failure from aborting the whole pool span. Neither implementation lives
in `services/_batch_utils.py` as a shared "write-per-cell-with-isolation" helper; this session's
diff is now the second independent implementation of that shape.

**Concrete cost:** any future fix to this control flow (e.g. the idle-session-timeout/rollback
interaction already hard-won across todos 306/312/318) has to be applied and re-verified in two
places that can silently drift.

## Why not fixed inline with todo 318

Not a clean 1:1 extraction: `backfill_feature_factory.py`'s version also has to execute
`_MARK_COMPUTE_COMPLETE_SQL`/`_MARK_COMPUTE_FAILED_SQL` against `backfill_status` (a side table
`regime_writer.py` doesn't have), so a literal shared helper isn't drop-in. Extracting it
properly means modifying `regime_writer.py` too -- a live, unrelated batch writer well outside
this session's diff -- to point at the same shared mechanism, which is real refactor risk to
accept mid-`/simplify` rather than a mechanical dedup.

## Fix shape (not yet decided)

Design a shared `write_cell_with_isolation(conn, write_fn, symbol, tf, on_success, on_failure)`-
style helper in `services/_batch_utils.py` that owns the try/except/rollback/log skeleton, taking
the actual write operation and the two side-table bookkeeping calls (mark-complete vs
mark-failed) as callables/callbacks. Would need dedicated test coverage for both call sites
before landing (this is a hot write path for both the corpus's regime relabeling and its feature
backfill).

## Where

- `services/backfill_feature_factory.py` -- `run_compute_stage()`'s aggregation loop
- `services/regime_writer.py` -- `main()`'s aggregation loop (lines ~2545-2596)
- `services/_batch_utils.py` -- natural home for the shared helper
