# 345 - `backfill_feature_factory.py`'s decompress/GUC-prep phase is serialized in front of worker compute

**Filed:** 2026-08-21
**Source:** `/simplify`'s efficiency-angle review of the full session's code diff (todo 318's
follow-up).

## What

`run_compute_stage()`'s `with (_write_session(db_conn, "feature_vectors"), _make_worker_pool(...)
as pool):` enters `_write_session` fully (a multi-round-trip DB sequence: pause the hypertable's
compression job, read GUC-override config, `SET` session GUCs, decompress every currently-
compressed `feature_vectors` chunk) before `pool.map(...)` is even called -- so this entire
sequence's latency sits strictly in front of the parallel compute phase it precedes, with zero
overlap. None of this prep touches anything the workers need (workers open their own separate
connections and only read OHLCV/cross-asset data, never `feature_vectors`).

**Concrete cost:** every `run_compute_stage` invocation with `pending_symbols` pays this
decompress/GUC-pause sequence's full latency up front, back-to-back, before the first worker
even begins computing -- none of that time overlaps with the (typically much longer) parallel
compute phase. `compressed_hypertable_write_session`'s own docstring documents a sibling caller's
decompress alone taking long enough that a session "sat idle ~55min waiting on worker compute"
afterward -- i.e. the decompress cost is real and non-trivial on this table.

**Related, same root cause:** `pool.map(..., chunksize=1)` yields results in submission order,
not completion order. If an early-submitted symbol takes longer to compute than a later one,
already-computed-and-ready results from later symbols sit unwritten behind the slow one purely
due to submission order, narrowing the window where DB write I/O could overlap with still-running
compute.

## Fix shape (not yet decided)

Submit worker tasks via `pool.submit()` explicitly (not `pool.map()`) so compute starts
immediately, enter `_write_session` while those futures are already running, then consume
results via `concurrent.futures.as_completed(futures)` instead of ordered iteration -- lets
compute for the fastest symbols hide the write-session's entry latency, and lets ready results
get written without waiting on unrelated slower symbols.

## Why not fixed this session

This is a structural rewrite of the pool-dispatch/result-consumption shape (`pool.map()` →
explicit `submit()`+`as_completed()`), not a mechanical edit -- it changes the concurrency/
ordering semantics of a hot batch-write loop that was JUST reworked this session for todo 318's
write-isolation fix, and would require rewriting every existing test in
`tests/unit/services/test_backfill_feature_factory.py` that currently mocks
`mock_pool.map.return_value = [...]` (an ordered list) rather than a completion-order iterable.
Real risk to accept mid-`/simplify` rather than a scoped, tested follow-up.

## Where

- `services/backfill_feature_factory.py` -- `run_compute_stage()`'s `with (_write_session(...),
  _make_worker_pool(...) as pool): for result in pool.map(...):` block
- `services/_batch_utils.py` -- `compressed_hypertable_write_session` (the expensive entry-phase
  sequence this fix would overlap with compute)
