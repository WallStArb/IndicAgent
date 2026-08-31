---
status: closed
priority: P3
filed: 2026-08-23
closed: 2026-08-31
source: found while fixing the 2026-08-22 alpha_publisher OOM incident (unbounded
  Kafka-path accumulation) -- a separate, deeper question surfaced but deliberately
  not fixed in that same pass
---

# `alpha_publisher.py`'s chunked INSERTs run on a separate connection from the DELETE's transaction, weakening the "atomic replace" guarantee its own comment claims

## What

`_execute_inner`'s emission loop is structured as:

```python
async with conn.transaction():
    deleted = await conn.execute("DELETE FROM alpha_events WHERE weight_version = $1", ...)
    async for row in conn.cursor(...):
        ...
        _chunk.append({...})
        if len(_chunk) >= chunk_size:
            await self._flush_chunk(pool, _chunk, now, is_shadow, topic)  # uses wconn!
            _chunk.clear()
```

`_flush_chunk` does `async with pool.acquire() as wconn: await wconn.executemany(...)` --
a **different pooled connection** than `conn`, whose transaction is what the DELETE lives
in. The DELETE only commits when `async with conn.transaction():` exits (after the full
cursor loop finishes), but the chunked INSERTs on `wconn` commit immediately,
independently, each time a chunk flushes -- **before** the DELETE has committed.

This means during a run, `alpha_events` briefly shows the OLD (pre-DELETE) rows for this
`weight_version` UNION the NEW rows inserted so far (via already-committed `wconn`
chunks) -- not the atomic "never a partially-empty table visible to readers" property
the code's own comment (right above the DELETE) explicitly claims. A reader querying
mid-run could see duplicate/inconsistent rows for the same event, or (if the process
crashes mid-loop) a state where some new rows exist but the DELETE never committed,
leaving old+new rows mixed with no defined precedence.

## Why not fixed alongside the OOM fix

This is pre-existing behavior, unchanged by the 2026-08-22 fix -- the `skip_kafka=True`
path had this exact same `wconn`-vs-`conn` split before today (its own chunked
`executemany` already used a separate `pool.acquire()` connection inside the loop). The
memory-leak fix unified both paths onto the same `_flush_chunk` helper, which
faithfully preserves this pre-existing transaction-boundary behavior rather than
silently redesigning it -- conflating "fix the OOM" with "redesign the atomicity model"
in one diff would have made that fix harder to review and higher-risk. This todo exists
so the finding isn't lost, not because it was skipped by accident.

## Whether this is actually a live problem

Not yet verified. Two things would need checking before treating this as urgent:
1. Does anything actually read `alpha_events` mid-run today (live ingestion is
   separately stalled per project memory) -- if nothing reads it during a batch/corpus
   run, the visibility window is harmless in practice even though it's a real gap.
2. What does a mid-run crash actually leave behind -- confirmed empirically (2026-08-22
   incident): a full-run crash (OOM before ANY chunk flushed) left `alpha_events`
   cleanly empty, because the DELETE itself was still uncommitted (rolled back). The
   partial-run case (crash AFTER some chunks flushed but before the DELETE's `async with`
   block exits) has not been tested and could leave a genuinely inconsistent state --
   worth a targeted test before deciding this needs a fix.

## Fix shape (if confirmed worth doing)

Either (a) make `_flush_chunk` use `conn` (the same connection/transaction as the
DELETE) instead of acquiring `wconn`, so the whole replace is genuinely one Postgres
transaction -- requires checking whether holding one connection through the full
emission loop (rather than releasing/reacquiring per chunk) has its own pool-contention
cost the current design was avoiding; or (b) accept the two-connection design but stop
claiming atomicity in the comment, and rely on `ON CONFLICT (event_id, bar_ts) DO
NOTHING` plus a monotonic cutoff to make partial-replace states self-healing on the next
run instead.

## Closure (2026-08-31)

This "not yet confirmed live-impacting" risk turned out to be exactly what caused the
2026-08-23 AND 2026-08-30 `alpha_publisher` production failures (same signature both
times: `QueryCanceledError: canceling statement due to statement timeout` inside
`_flush_chunk`'s first `executemany`). Root-caused precisely as this todo's "Whether
this is actually a live problem" section anticipated it could: `event_id` encodes
`weight_version`, so a rerun's INSERTs target the exact PK rows the DELETE just
(uncommittedly) removed -- Postgres blocks the INSERT on `wconn` until `conn`'s
transaction resolves (`XactLockTableWait`), but `conn` can't resolve until the awaited
`_flush_chunk` call on `wconn` returns. Self lock-wait cycle within one process, broken
only by the server's 30min `statement_timeout` (confirmed via `SHOW statement_timeout`;
matches the 2026-08-30 failure's 1905.67s elapsed almost exactly). Zero new rows ever
landed on either failed run -- `alpha_events` was serving stale 2026-08-23-vintage data
for a full week until this was fixed.

**Fix landed: option (a).** `_flush_chunk` now takes `conn` directly instead of
`pool.acquire()`-ing a second connection (`services/alpha_publisher.py`). The
pool-contention concern option (a) flagged turned out to be moot -- holding one
connection through the full emission loop is exactly what the DELETE's own
`async with conn.transaction():` block already required; no separate connection was
ever needed for correctness, only removed. Verified live: rerun against the same
70.5M-row corpus completed cleanly in 78.5min with steady ~50K-row chunk flushes
every ~3s, no hang, `alpha_events` now holds `weight_version='run_2025122405150000'`
rows with `emitted_at` matching the fresh run, not the stale 2026-08-23 timestamp.
