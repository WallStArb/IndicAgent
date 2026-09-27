# 185-01 write-rate and role measurements (RESEARCH assumptions A5, A7)

Status: complete, 2026-09-27. Harness: `scripts/ops/bars/ops_measure_ohlcv_write_rates.py`,
full log `/tmp/185_01_write_rates.log` (run 2026-09-27, evening EDT). The quota window killed
the executor subagent before the run, so the orchestrator session ran the harness inline
(owner instruction relayed 2026-09-27).

## Setup

- Schema `scratch_185`, hypertable `scratch_185.ohlcv`: market_data_ohlcv's column list, PK
  (`timestamp`, symbol, timeframe), both secondary indexes, 30-day chunks, and the live table's
  compression settings (segmentby `(symbol, timeframe)`, orderby `timestamp ASC`).
  TimescaleDB 2.27.1.
- Filled from `market_data_ohlcv_tradeable`: 20 ETFs, 2016-01-01 to 2026-01-01. 1d and 1h
  complete for all 20 (345,627 rows), 5m capped at 3M total (15 symbols). Total 3,078,498 rows.
- All 122 chunks older than 30 days compressed (`compress_chunk`, 3.6 s); after compression:
  122 compressed, 0 uncompressed.

## Results

Every row is a full (symbol, tf) segment worked in a single transaction; disk delta is
`hypertable_size` before/after; "chunks decompressed" is the drop in the is_compressed count
across the statement (0 everywhere: on this build, DML is served by the compressed-batch
merge path and never flips a chunk to uncompressed).

| method | segment (shift) | rows | seconds | rows/s | disk delta (bytes) | chunks decompressed |
|---|---|---|---|---|---|---|
| a1 COPY insert | SPY 1h (+30 min) | 15,021 | 0.23 | 65,458 | +8,994,816 | 0 |
| a2 multi-row INSERT ... SELECT | QQQ 1h (+45 min) | 17,535 | 0.16 | 110,275 | +1,982,464 | 0 |
| b native upsert (ON CONFLICT DO UPDATE) | IWM 1h (verbatim) | 17,535 | 0.27 | 65,556 | +16,637,952 | 0 |
| c DELETE then COPY reinsert | EEM 1h (verbatim) | 15,021 | 0.17 | 90,575 | +4,481,024 | 0 |
| d DELETE then COPY reinsert | EFA 5m (verbatim) | 195,324 | 1.76 | 111,180 | +66,461,696 | 0 |

Scratch table grew 115.0 MB to 213.6 MB across the five measurements. Shifts exist only to
avoid PK conflicts for the insert-only methods; (c) and (d) reinsert verbatim (shift 0), which
is the plan 12 shape.

## Role check (A7)

`scratch_185_writer` (NOLOGIN; USAGE on the schema; SELECT, INSERT, DELETE on the table only),
entered via `SET LOCAL ROLE` from the postgres connection: SUCCEEDED. It COPY-inserted 17,385
rows (+17 min shift) into compressed chunks and deleted GLD's full 1h segment, in one
transaction.

Answer: a NOLOGIN role with table grants CAN run DML against compressed chunks on this build.
Writer-role separation in the D-05 style is enforceable on the hypertable itself; plans 12 and
17 need no superuser-writes deviation. (The +17 min shift avoids the PK self-conflict a +60
min shift creates on 1h bars, and the mixed-grid collisions a +30 min shift can create.)

## EXPLAIN (ANALYZE, BUFFERS) samples (executed, then rolled back)

- Segment DELETE (SLV 1h): Custom Scan (ModifyHypertable), "Batches scanned: 122,
  Batches deleted: 122", shared hit=7,616, execution 13.6 ms. The node reports rows=0 because
  compressed-chunk deletes go through the batch path rather than the heap path; measurement (c)
  is the ground truth that rows were actually removed (the verbatim COPY reinsert would have
  violated the PK otherwise).
- Insert into compressed chunks (XLF 1h, +17 min): Custom Scan (ModifyHypertable),
  "Batches scanned: 17,535, Batches filtered after decompression: 17,413", shared hit=254,182
  dirtied=714 written=524, execution 177.6 ms for 17,535 rows. The source side reads the
  segment through ColumnarScan nodes on the compressed chunks (meta index per chunk), and the
  insert merges new rows into compressed batches.

## Contention during the run (accepted and noted)

The todo 449 chain (pid 237349, client 46, 1h+15m stage over the 698 names) was live in the
same cluster throughout. Evidence at the sampled instants: pg_stat_activity before and after
(c) showed no other active backends; iostat during (c) showed dm-0 at 6.5% util in the first
interval (about 9.7 MB/s writes, including this run's own flushes) and under 1% in the next
four; a post-run 60 s pg_stat window (18:51 EDT) measured 0 inserts into market_data_ohlcv
while the chain process was alive (the chain writes in bursts between IBKR pacing sleeps).
Conclusion: these numbers are close to uncontended and should be read as optimistic; the real
rewrites run under chain bursts, so the extrapolations below carry 10x headroom.

## Extrapolations

Corpus sizes per the phase RESEARCH: 1h about 8M rows, 15m about 27M rows, 1d 3.87M rows.

| workload | method | measured rate | ideal | with 10x headroom |
|---|---|---|---|---|
| D2b 1h full rewrite (plan 12) | c | 90,575 rows/s | ~88 s | ~15 min |
| D2b 15m full rewrite (plan 12) | d | 111,180 rows/s | ~4.1 min | ~41 min |
| D2 1d convergence pass (plan 17) | b | 65,556 rows/s | ~59 s | ~10 min |

Caveat: live chunks carry the whole universe per 30-day window (scratch chunks held 20 symbols,
about 25k rows each), so per-batch merges on live chunks touch more rows; the headroom column
absorbs that. The nightly plan 17 write is the changed-rows subset, typically far below the
full 3.87M convergence pass.

## Recommendation

- Plan 12 (D2b segment rewrite): DELETE + reinsert per (symbol, tf) segment in one transaction,
  the plan's archive -> checksum-verify -> delete -> insert shape. Measured 90-111k rows/s puts
  the whole-universe rewrite at minutes scale with per-symbol transactions bounding blast
  radius. Do not use native upsert here: it measured worst on disk (+16.6 MB vs +4.5 MB for a
  comparable segment) and buys nothing the transactional rewrite does not already give.
- Plan 17 (D2 1d writes): native upsert (method b) for the nightly changed-rows write; even a
  full 3.87M-row convergence pass is about a minute at the measured rate, and the nightly
  changed set is far smaller.
- Both can run under a NOLOGIN writer role on compressed chunks (A7 result), so plan 18's
  sole-writer fences plus role grants hold on the hypertable itself.

## Harness deviation and acceptance

- Post-run fix: `teardown()` originally ran `DROP OWNED BY scratch_185_writer` unguarded after
  `role_check()`'s finally block had already dropped the role, raising UndefinedObject at exit
  (the `| tee` pipeline masked the exit code). Guarded with a pg_roles existence check after
  the run; cleanup itself had already succeeded.
- Acceptance verified: `pg_namespace` count for scratch_185 = 0; `pg_roles` count for
  scratch_185_writer = 0; the script greps clean for INSERT/UPDATE/DELETE against
  market_data_ohlcv.
