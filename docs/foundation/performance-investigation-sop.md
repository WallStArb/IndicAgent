# Performance & Throughput Investigation SOP

**Version:** 1.0
**Status:** current
**Last Updated:** 2026-07-21

## Why this doc exists

Two independent throughput investigations two weeks apart (todo 149, 2026-07-20; todo 161,
2026-07-21) hit the **same shape of bug**: a batch write against a TimescaleDB hypertable
measured 30-350x slower than a naive back-of-envelope estimate predicted, for a reason that
was invisible until someone actually instrumented the running process instead of reasoning
about it. Both times the fix, once found, was small. Both times finding it took longer than it
should have because the investigation started with a guess-and-patch cycle (bigger batches,
different SQL shape) instead of measurement. This doc exists so the third time is faster.

**The pattern isn't "TimescaleDB is slow."** It's: at millions-of-rows scale, this codebase
consistently underestimates the cost of *mutating* data relative to the cost of *reading* it,
because our instincts (and our quick tests) are read-shaped. Corpus rebuilds, backfills,
counterfactual scoring, price-sanity corrections — every one of them is a write-heavy batch
job against a hypertable with hundreds to thousands of chunks. This is a load-bearing
operational category for the project (`docs/foundation/principles.md`'s "instrument
everything" / "empirical over theoretical"), not a one-off.

## The failure pattern, named

1. A backfill/migration/batch job is written, reasoned about in terms of row count and an
   assumed per-row cost (usually inferred from a `SELECT`/`EXPLAIN` that never touches disk or
   the hypertable's chunk-routing layer).
2. It runs far slower than that estimate — sometimes silently (todo 161: three attempts spanning
   ~18h that wrote *zero* rows, no error, no log line past startup).
3. The instinct is to patch the shape of the query (bigger batches, `UNNEST` bulk arrays,
   more parallelism) without first establishing *where* the time is actually going. This
   sometimes helps a little (todo 161's `UNNEST` test: only 3x, not the 100x+ a genuine
   round-trip-bound problem would show) and never explains the real gap.
4. The real cause turns out to be a TimescaleDB-specific cost invisible to a plain `EXPLAIN`
   on a *read*: compressed-chunk decompression-on-write (todo 149), or per-execution
   chunk-routing overhead scaling with chunk count (todo 161). Both are structural properties
   of the hypertable abstraction that only show up under a real write, at real scale, against
   a real chunk-populated table.

## The SOP

**Follow this order. Do not skip to step 4 because "it's probably X."**

### 1. Never trust a read-only test for a write-path question

A `SELECT`/`EXPLAIN` — even `EXPLAIN ANALYZE` — on a query shape that resembles your write does
not measure your write. Benchmark the **exact operation**: same statement type (`UPDATE`, not
`SELECT`), same table, same WHERE-clause shape, against real rows at realistic scale (hundreds
to thousands, not 5). A `SELECT` can be answered from a hot buffer or an index-only scan in a
way an `UPDATE` never can (it must also touch the heap, WAL, and — for a hypertable — the
chunk's own indexes and constraints).

### 2. Measure before theorizing — three tools, in this order

Before proposing *any* fix, run the actual write against real data and capture:

1. **`pg_stat_activity.wait_event_type` / `wait_event`**, sampled during the run (`state='active'`
   with an *empty* `wait_event` means the backend is on-CPU the whole time — not I/O, not lock
   wait; a populated `wait_event_type='IO'` or `'Lock'` means something else entirely). This one
   query eliminates entire categories of hypothesis in seconds.
2. **`iostat -x 1`** for the underlying disk, sampled concurrently. `%util` near 0 while a write
   is measurably slow rules out disk I/O as the bottleneck outright — don't chase a
   disk-locality theory the data already refutes (todo 161: chunk-locality was the leading
   hypothesis on paper; `iostat` refuted it in one command).
3. **`EXPLAIN (ANALYZE, BUFFERS)`** on the exact statement, on a single representative row.
   Cross-check its execution time against your measured per-row throughput — if EXPLAIN says
   sub-millisecond and you're measuring tens of milliseconds/row, the gap itself is the clue:
   something outside the query plan's own execution cost is eating the difference (todo 161:
   0.86ms EXPLAIN execution vs. ~34ms/row measured — that 40x gap was the whole investigation).

Guessing "it's probably disk" or "it's probably lock contention" without these three checks is
exactly the anti-pattern this doc exists to stop. This maps directly onto
`superpowers:systematic-debugging`'s Phase 1 (root cause investigation, multi-component
evidence gathering) — use that skill explicitly for any throughput investigation, not just
correctness bugs.

### 3. Isolate with a single-variable test before writing a fix

Once you have a hypothesis, test it with the smallest possible change: same rows, same
connection, same everything except the one variable you suspect. Todo 161's isolating test was
literally "run the identical `UPDATE` against `alpha_frames` vs. against the one underlying
chunk table those exact rows live in, same connection, same tuples" — a two-line change that
turned "probably chunk overhead" into "confirmed, 358x." Don't ship a fix built on a plausible
story; ship one built on a measured, isolated delta.

### 4. TimescaleDB-specific suspects to check, in rough order of how often they've actually hit us

- **Chunk count on the target hypertable.** `SELECT count(*) FROM timescaledb_information.chunks
  WHERE hypertable_name = '...'`. High chunk counts (hundreds+) mean per-execution
  chunk-routing/exclusion overhead is a real cost for point UPDATEs/DELETEs, paid on every
  execution regardless of prepared-statement reuse across a client-side batch. Confirmed fix:
  resolve the target chunk once (`timescaledb_information.chunks`' `range_start`/`range_end`)
  and write directly to `_timescaledb_internal.<chunk>` — see `services/counterfactual_tracker.py`'s
  `_load_chunk_index`/`_route_chunk` for the reusable pattern.
- **Compression status on the target chunks.** `SELECT is_compressed FROM
  timescaledb_information.chunks WHERE hypertable_name = '...'`. Any compressed chunk in your
  target range means every mutating row forces decompress-then-modify. `decompress_chunk()`
  the affected chunks first, or restructure the join to drive from the small known-target
  population rather than the full source table (todo 149's fix pattern).
- **A correlated subquery (`EXISTS`, `IN`) driven from the large table instead of the small
  target set.** This silently degrades into a near-full-table scan; always drive from the
  smaller, known population.

### 5. Verify the fix live, end-to-end, with the real code path — not just a mocked unit test

A passing unit test with a fake connection proves the *logic* is right (correct SQL generated,
correct grouping, correct fallback behavior). It says nothing about measured rows/sec. Both are
required before a throughput fix is declared done: run the actual production function against
real data on a symbol/partition untouched by prior manual testing, and record the number
(todo 161: 6,472.5 rows/sec measured via the real `_load_chunk_index`/`_route_chunk`, not the
mocked test, before restarting the actual backfill).

### 6. Capture the finding as a durable gotcha, not just a closed todo

A closed todo is invisible to the next session that hits the same symptom. Add a one- or
two-line entry to `docs/reference/gotchas.md` under the TimescaleDB section — see the entries
this doc's writing added for todos 149 and 161 as the template. The goal is that the *third*
occurrence of this pattern starts at step 4 of this SOP, not step 1.

## Case studies

- **Todo 149** (2026-07-20): `market_data_ohlcv` (~215M rows, 248/250 chunks compressed).
  Read-only tests looked fine; the real `UPDATE` for the price-sanity guard forced
  decompress-on-write plus a correlated `EXISTS` driven from the wrong side of the join. Fix:
  drive from the small target population, explicit `decompress_chunk()` first.
- **Todo 161** (2026-07-21): `alpha_frames` (23.16M open rows, 1034 chunks, uncompressed).
  Three backfill attempts (~18h cumulative) wrote zero rows — a separate ordering/visibility bug
  (`ProcessPoolExecutor.map()` submission-order stall, one-giant-implicit-transaction flush),
  fixed first. After that fix, throughput was *still* 28-84 rows/sec regardless of batching
  strategy. `iostat`/`wait_event` ruled out I/O and locks; an isolating test found writing
  directly to the resolved chunk table ran 358x faster (29 → 10,423 rows/sec) than writing
  through the hypertable. Full trail: `.planning/todos/completed/161-counterfactual-tracker-update-throughput.md`.

## See Also

- [Renaissance Principles](principles.md) — "instrument everything," "empirical over theoretical"
- `docs/reference/gotchas.md` — TimescaleDB section, where the durable one-liners from this
  doc's case studies live
- `superpowers:systematic-debugging` skill — the general debugging process this SOP specializes
  for throughput/latency investigations specifically
