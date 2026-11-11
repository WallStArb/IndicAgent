# Bulk raw load path: set-based classification for the Massive load

Author: design subagent for the lead, 2026-11-11 (todo 600, admission step 5)
Status: build steps 1 to 4 built 2026-11-11 (section 14); step 5 (rerouting the fetcher, nightly and Tradier restore) not started. No real load has run under it yet.
Informed by: commit 6f2e0eba7, `scripts/ops/bars/ops_massive_load.py`, `services/bar_load.py`, `services/ohlcv_ingress_contract.py`, `services/ohlcv_raw_writer.py`, `services/bar_selection.py`, `src/intelligence/bars/selection.py`, `scripts/ops/bars/ops_selection_gate.py`, `scripts/infrastructure/backfill/_intraday_persist.py`, `docs/plans/2026-11-10-massive-admission-db-design.md` (sections 4, 8 step 5, 8b), `logs/massive_apply_5m_2024_06.log` and `logs/massive_5m_2024_06_size_pre.txt`, read-only schema queries and read-only timings (2026-11-11).

## 1. Problem and measured baseline

June 2024 5m (`--month 6 --apply`): 1,804,531 rows offered, all new, in 376 s wall, so 4.8k rows/s. The process used 205 s of user CPU at 52 percent CPU, so about half the wall time was spent waiting on the database. Max RSS was 6.95 GB. At this rate 2003-2025 5m takes about 27 h.

Component timings, measured read-only on 2026-11-11 (no writes):

| Component | Cost | Per June 2024 month |
|---|---|---|
| Day file read and 5m aggregation (`read_minute_file`, `frames`) | 0.4 + 0.2 s per file | about 12 s |
| Writer Python: `frame_to_raw_rows` 1.8 us, `_group_by_series` with validation 2.4 us, `classify` 0.7 us, `_raw_params` 2.0 us per row; grouping and classification run twice (preview, then write) | about 10 us per row | about 18 s |
| Selection per symbol-month: raw read 13 ms, `select_slots` 40 ms (4.8k candidates on average across 3 vendors), canonical read 4 ms, plus `bar_session_choice` writes | about 60 ms per symbol | about 80-90 s for about 1,400 symbols |
| Stored-row reads, two per series (`preview_series`, then `write_raw`) | a few ms each | about 10-15 s |
| Server-side INSERT (multi-row VALUES, 13 binds per row, 4 btree indexes, symbol FK, compressed target chunks) and per-statement overhead | not separable read-only | most of the remaining ~200 s |

Two smaller costs also show up. `account_day` builds a `datetime` and a tuple for every mapped bar (about 3 s), and the loader never configures structlog, so `bar_selection.session_choice` debug lines go to stdout for every non-plain session (visible in the June log). That breaks the per-row logging rule.

Selection alone takes about 25 percent of the wall time, and while Massive is unranked it writes nothing (section 6). Per-row Python takes another 10 percent. The database share can't be split read-only, so build step 1 measures it before anything else is changed (section 11).

## 2. Contract that must hold

Each of these is checked by the equivalence proof in section 10:

- last-wins by serve time: a changed offer answered at or after the stored `served_at` (or a stored NULL) replaces it, and the old values go to `ohlcv_revision` with origin `raw` and the old row's `request_id`. A changed offer that is older is logged as origin `superseded` under this load and request, and raw is not touched. The SQL serve-time guard on the upsert stays.
- the supersede guard applies row by row, using each row's own `answered_at` (per-file LastModified).
- one `ohlcv_load` row per (series, chunk of at most `CHUNK_ROWS`), with the same counts, first and last bar, caller, destination and lineage note. The counts are known before the row is inserted, because the role can INSERT but not UPDATE it.
- the restatement detector gets the same inputs, and flags land in `ohlcv_restatement_flag`.
- a key offered twice with different values raises before any SQL, and identical repeats collapse with the last occurrence winning.
- all validation stays: CVR codes, canonical-only kinds, placeholder sources, finite prices, non-negative integer volume, tz-aware stamps, the future guard, and a required `answered_at`.
- idempotent: a second run inserts 0 raw rows and 0 revisions.
- `ohlcv_raw` keeps one writer module (`services/ohlcv_raw_writer.py`), the per-series advisory lock, the bar-writer role, and the caller-owned transaction.

## 3. Recommendation

Extend the one writer with a columnar, set-based classify-and-write, and run the ingress contract on it. Defer selection while the vendor is unranked:

1. A columnar `RawBatch` (numpy arrays plus scalar timeframe, vendor and kind) replaces `RawRow` lists on the bulk path. Validation, deduplication and the contradiction check are vectorized.
2. One transaction per packed group of whole series-chunks, at most `infra.ohlcv_observation.copy_batch_rows` rows (50,000; existing APR key, so no new key). In that transaction: binary COPY into a session temp table, take the series locks in sorted order, then run ONE classification join that reads the stored rows once. Then the load rows, then set-based revision, new-row and replacement inserts from the temp table. Rowcounts are checked against the classification.
3. Selection is deferred when the batch's vendor is ranked in no `bar_source_policy_current` row for the timeframe. In that state selection can't change canonical (section 6 proves it), so the load reports `RAW-ONLY`, never `APPLIED` or `UNSELECTED`. The UNSELECTED count moves unchanged in definition (the same `select_slots`) to the step 5 gate's `ops_selection_gate --compare`. A ranked vendor keeps per-symbol selection exactly as today.
4. After the Massive switch, `write_raw` and `apply_raw_contract` (fetcher, nightly, Tradier restore) are rerouted onto the same core, and the per-row classifier (`_classify_series`, `preview_series`, the classification use of `_read_stored`) is deleted in the same build. That leaves one implementation.

The expected rate is about 25-30k rows/s (section 9). The one figure that decides it, the server-side INSERT rate, is measured in build step 1, before the loader is switched.

## 4. Data carrier: `RawBatch`

```python
@dataclass(frozen=True)
class RawBatch:
    timeframe: str; vendor: str; kind: str              # one series family per batch
    symbols: np.ndarray        # object/str, per row
    ts_us: np.ndarray          # int64, UTC microseconds
    open: np.ndarray; high: np.ndarray; low: np.ndarray; close: np.ndarray  # float64
    volume: np.ndarray         # int64
    volume_null: np.ndarray    # bool (missing is None, never 0)
    served_us: np.ndarray      # int64, per-row answer time (the caller's answered_at when uniform)
    load_key: np.ndarray       # int32, the series-chunk index each row belongs to
```

- `frame_to_raw_batch(frames_by_symbol, ...)` is the columnar twin of `frame_to_raw_rows`. It uses the same vendor and kind resolution (label map, explicit kind checked against `VENDOR_SERVED_KINDS`) and the same `int(v)` truncation, as `astype(int64)` after a finite check. A non-finite volume raises, just as `int(nan)` raises today.
- Stamps come from `t_ns // 1000` with an assertion that `t_ns % 1000 == 0`. Today `to_pydatetime` drops nanoseconds silently. The bulk path raises instead, which is the one place it is stricter.
- Dedup: stable `lexsort` by (symbol, ts). Among equal keys the values (o, h, l, c, v) must be equal or the batch raises with the same message and count as `_group_by_series`, and the last occurrence in input order is kept. `n_offered` counts the input rows, and `n_bars` per load counts unique stamps, as today.
- Series-chunks: rows of one symbol in stamp order are cut every `CHUNK_ROWS` (10,000), which matches `load_frame`'s chunking. Each series-chunk gets one `load_id` and one `request_id`, both uuid4 and generated by the contract (today `persist_chunk_atomically` draws a fresh `request_id` per chunk when there are no request rows).

## 5. Writer and contract: exact SQL

All statements run in the caller's transaction after `SET LOCAL ROLE bar_derivation_writer`. PUBLIC holds TEMP on the database (checked), so the role can create session temp tables. The two temp tables are created once per session inside that role context, `IF NOT EXISTS`, `ON COMMIT DELETE ROWS`, so there is no per-transaction catalog churn:

```sql
CREATE TEMP TABLE IF NOT EXISTS ohlcv_raw_stage (
  ord integer NOT NULL, load_id uuid NOT NULL, request_id uuid NOT NULL,
  "timestamp" timestamptz NOT NULL, symbol text NOT NULL,
  open float8 NOT NULL, high float8 NOT NULL, low float8 NOT NULL, close float8 NOT NULL,
  volume bigint, served_at timestamptz NOT NULL
) ON COMMIT DELETE ROWS;
CREATE TEMP TABLE IF NOT EXISTS ohlcv_raw_stage_class (
  ord integer NOT NULL, cls smallint NOT NULL,          -- 0 new, 1 unchanged, 2 replace, 3 superseded
  old_open float8, old_high float8, old_low float8, old_close float8, old_volume bigint,
  old_request_id uuid
) ON COMMIT DELETE ROWS;
```

Per transaction, in this order:

1. Stage: `COPY ohlcv_raw_stage (...) FROM STDIN (FORMAT BINARY)` through psycopg `Copy.write_row` with `set_types`, rows ordered by (symbol, timestamp). COPY streams, so the 1 GiB query-buffer failure that `CHUNK_ROWS` guards against can't recur.
2. Lock: `SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))` through `executemany` (pipelined, one round trip) over the batch's series keys `symbol|timeframe|vendor|kind`, sorted. It is the same statement and key as `_lock_series`, so lock order and keys don't change.
3. Classify, reading the stored rows once. The subquery filters on every segment-by column (symbol, timeframe, vendor) plus kind and a constant time range, so TimescaleDB decompresses only this vendor's segments of these symbols in the 1-2 chunks the range touches. It runs with `prepare=False`, so the planner sees `lo`/`hi` as constants and excludes chunks at plan time:

```sql
INSERT INTO ohlcv_raw_stage_class
SELECT s.ord,
       CASE WHEN r."timestamp" IS NULL THEN 0
            WHEN (s.open, s.high, s.low, s.close) = (r.open, r.high, r.low, r.close)
                 AND s.volume IS NOT DISTINCT FROM r.volume THEN 1
            WHEN r.served_at IS NULL OR s.served_at >= r.served_at THEN 2
            ELSE 3 END,
       r.open, r.high, r.low, r.close, r.volume, r.request_id
FROM ohlcv_raw_stage s
LEFT JOIN (SELECT "timestamp", symbol, open, high, low, close, volume, served_at, request_id
           FROM ohlcv_raw
           WHERE timeframe = %(tf)s AND vendor = %(vendor)s AND kind = %(kind)s
             AND symbol = ANY(%(symbols)s)
             AND "timestamp" >= %(lo)s AND "timestamp" <= %(hi)s) r
  ON r.symbol = s.symbol AND r."timestamp" = s."timestamp";
```

   The equality semantics match `classify`. Python compares float64 `==` (stored doubles, exact, and -0.0 equals 0.0 in both), volume as int or None (`IS NOT DISTINCT FROM`), and NaN can't reach either side (validation and the `ohlcv_raw_finite` CHECK). The serve-time comparison is per row on microsecond timestamps, as `(row.answered_at or answered_at) >= stored_at` is today.
4. Read back: `SELECT array_agg(cls ORDER BY ord) FROM ohlcv_raw_stage_class` (one int2 array, decoded to numpy) and `SELECT ord, old_open, old_high, old_low, old_close, old_volume FROM ohlcv_raw_stage_class WHERE cls = 2 ORDER BY ord` (the changed rows only, normally none). Per-series counts come from `np.bincount` over (load_key, cls).
5. Detector, in Python, per series-chunk with at least one replace. `offered` is the non-superseded rows, and `stored` is the offered values of the unchanged rows plus the old values of the replaced rows. These are exactly `_stored_at_offer`'s inputs, built only for the series that need them. A series with no replace can't flag (share 0, zero changed bars), so it gets `Restatement(n_stored, 0, 0.0, (), None, None, None)`. A unit test pins that constant against `detect` with the current APR parameters, including `signature_min_bars >= 1`.
6. Load rows: `_INSERT_LOAD_SQL` via `executemany`, one row per series-chunk, with outcome, counts and the detail note built exactly as in `apply_raw_contract` (lineage note, restatement note, superseded note). These rows are inserted before the revisions, which reference them by foreign key.
7. Revisions, first, as today:

```sql
INSERT INTO ohlcv_revision (load_id, symbol, timeframe, "timestamp", old_open, old_high, old_low,
                            old_close, old_volume, old_source, vendor, kind, request_id, origin)
SELECT s.load_id, s.symbol, %(tf)s, s."timestamp",
       CASE c.cls WHEN 2 THEN c.old_open ELSE s.open END, ...high, low, close...,
       CASE c.cls WHEN 2 THEN c.old_volume ELSE s.volume END,
       %(token)s, %(vendor)s, %(kind)s,
       CASE c.cls WHEN 2 THEN c.old_request_id ELSE s.request_id END,
       CASE c.cls WHEN 2 THEN 'raw' ELSE 'superseded' END
FROM ohlcv_raw_stage s JOIN ohlcv_raw_stage_class c USING (ord)
WHERE c.cls IN (2, 3);
```

8. New rows, as a plain INSERT, as today (a racing insert would fail loudly on the primary key):

```sql
INSERT INTO ohlcv_raw ("timestamp", symbol, timeframe, vendor, kind, open, high, low, close,
                       volume, served_at, request_id, load_id)
SELECT s."timestamp", s.symbol, %(tf)s, %(vendor)s, %(kind)s, s.open, s.high, s.low, s.close,
       s.volume, s.served_at, s.request_id, s.load_id
FROM ohlcv_raw_stage s JOIN ohlcv_raw_stage_class c USING (ord)
WHERE c.cls = 0 ORDER BY s.symbol, s."timestamp";
```

9. Replacements: the same SELECT with `c.cls = 2`, followed by the unchanged `_UPSERT_TAIL` (ON CONFLICT DO UPDATE with the serve-time WHERE guard).
10. Check: the rowcount of 8 must equal `n_new`, the rowcount of 9 must equal `n_replace`, and the revision rowcount must equal `n_replace + n_superseded`. A shortfall raises `RuntimeError` and the transaction rolls back. This check replaces today's second stored read and preview-versus-write comparison. Both answer the same question (did the stored state move between classification and write), and under the series lock the answer is no unless some writer bypassed the lock. A bypass would now fail loudly.
11. Flags: `record_flag` per flagged series and the `RESTATEMENT_FLAGS` metric, unchanged.
12. Selection, or deferral (section 6).

Single writer: steps 1-4 and 7-10 live in `services/ohlcv_raw_writer.py` as `stage_and_classify(cur, batch, ...) -> Classified` and `write_classified(cur, classified)`. That is the same split as today's `preview_series` and `write_raw`, with the classification held server-side between the two calls. Steps 5, 6, 11 and 12 stay in `services/ohlcv_ingress_contract.py` (`apply_raw_contract_batch`), which already owns the `ohlcv_load` and flag INSERTs. `bar_load.load_batch` replaces the per-symbol `load_frame` loop for a loader and calls one transaction per packed group under `persist_chunk_atomically`'s rules: an idle connection, `conn.transaction()`, and `SET LOCAL ROLE`. No new module touches `ohlcv_raw`.

## 6. Selection: deferred while the vendor is unranked

Here is why selection can't change canonical while the vendor is unranked. In `select_slots`, only ranked vendors fill `by_vendor`, `session_slots`, the winners and the choices. An unranked vendor's on-grid rows can add three things:

- slots to `unselected` and `n_unselected` / `n_excluded`, when no ranked vendor holds the slot;
- the retraction of a canonical row at such a slot;
- a session date to `outcome.sessions`, which clears `bar_session_choice` rows of sessions no ranked vendor holds.

If canonical equals the selection of raw before the load (the standing `--compare` claim), the second and third touch nothing, because no canonical row or choice row exists where no ranked raw row exists. The only output of the per-chunk selection is then the unselected count. If canonical were inconsistent, the current path would silently repair part of it during the load, and the bulk path would leave it for the gate's `--compare` to report. That is the better behaviour: a repair should be visible, not a side effect of a load.

Guard: in each transaction, `SELECT EXISTS (SELECT 1 FROM bar_source_policy_current WHERE timeframe = %s AND %s IN (primary_source, fallback_source))`. The role holds SELECT on the view (checked). If it returns true, selection runs per symbol over that symbol's own window, exactly as `apply_raw_contract` does now, so the counts stay identical. If it returns false, selection is skipped. Today Massive appears in no policy row. Alpaca and IBKR are always ranked, so their paths always select.

Reporting: `LoadResult` gains `n_selection_deferred` (series-chunks not selected), and `load_status` returns `RAW-ONLY (selection deferred: vendor unranked; unselected is counted by ops_selection_gate --compare)` when it is nonzero. `n_unselected` stays 0 for a deferred load, but the status word stops anyone from reading that 0 as "no unselected slots". The lineage note records `"horizon": null, "selection": "deferred_unranked"`: no selection ran, so recording a horizon would be a false claim.

Step 5 gate, amended (one dated note in the admission doc):

- The status for every Massive year while unranked is `RAW-ONLY`.
- Unselected: `ops_selection_gate --compare --start <Y-01-01> --end <Y+1-01-01>` runs before and after the year. The gate is `after.unselected_slots - before.unselected_slots == sum(massive_only)` from the dry run, and every other compare total is unchanged, which means canonical was not touched. This uses the same `select_slots` and is stricter than today's check, which compared a load count against the dry run without subtracting slots that were already unselected in the touched sessions. `--start/--end` is a small new window on the read-only tool, cut at NYSE session boundaries.
- Row balance: unchanged.

Without deferral, selection alone (about 60 ms per symbol-month) holds the run below about 20k rows/s even if every other cost goes to zero. Deferral is required for the target, not an optional tuning.

## 7. Loader changes (`ops_massive_load.py`)

- `MonthBatch` keeps columnar arrays per day (from `FlatBars`: the mapped mask, symbol per row, t_ns, OHLCV, and the file's LastModified broadcast to `served_us`), instead of one DataFrame per ticker per day. At flush time it concatenates once and builds one `RawBatch` per month. The per-symbol lineage (files list, ticker events, epochs, untraded total) is unchanged and is handed over as `lineage_by_symbol`.
- Packing: whole series-chunks, in symbol order, are grouped into transactions of at most `copy_batch_rows` rows. A 5m transaction then touches about 40 symbols. A 1d transaction (about 21 rows per symbol-month) touches up to about 2,400 series, so about 2,400 advisory locks, inside the shared lock table of 64 x 200 connections = 12,800.
- `account_day` is vectorized: incumbent slots as int64 microsecond stamps per symbol code, checked with `np.isin`. The integer result is unchanged.
- The loader calls `setup_service_logging`, so selection debug lines no longer reach stdout.
- `ArchiveIndex` memory, a probable cause of the 6.95 GB RSS (to be confirmed with tracemalloc first): `judge_span` calls `present_on` for every session inside every span, and the cache holds a frozenset of about 8-10k fresh `str` objects for each of up to 5,829 sessions, about 0.8 MB each, so several GB. If confirmed, the fix is a ticker-id by session bitset (about 15k x 5,829 bits, about 11 MB) with the same `present_on` answers.

## 8. Failure, restart, memory, compression

Failure and restart. Each packed transaction is atomic: stage, classification, load rows, revisions, raw rows and flags. Any exception, a kill or a lost connection rolls it back, and the session temp tables empty on commit or disappear with the session. Rerunning the same command is the resume. Committed groups classify as unchanged (0 inserts, 0 revisions) and get their `ohlcv_load` rows again with `n_unchanged`, as today. A rerun only reads compressed Massive segments, so it costs a fraction of a load. One connection and no process pool means no orphaned workers. Rule from CLAUDE.md: never edit a module the running loader imports. `_read` imports `massive_flat` lazily, so that module stays untouched while any sweep runs.

Memory bounds. Client: about 100 bytes per row in a month's arrays (1.8M rows, about 180 MB for June 2024, the largest 5m month), plus one day file being read (about 550 MB peak measured), plus the ArchiveIndex fix. That puts the target under 1.5 GB RSS, against 6.95 GB today, with about 7 GB free. Server: the stage table is at most 50k rows (about 6 MB) and stays in `temp_buffers` (8 MB) or spills to local temp files. The classification hash join is bounded by the transaction rows, within `work_mem` (128 MB).

Compression. `ohlcv_raw` uses 30-day chunks, compressed after 60 days (job 1076, every 12 h), with segment_by (symbol, timeframe, vendor) and order_by timestamp. 338 of 341 chunks are compressed, every 2024 chunk among them.

- New rows land in the target chunk's uncompressed heap and the chunk becomes partial. The unique check probes only the matching segment, which on a first load is the empty Massive segment, so it is cheap.
- A replacement decompresses the affected Massive batches (about 1,000 tuples each) into the heap. Transaction packing bounds this to the touched symbols' batches, at most about 40 symbols x 2 batches for 5m. `timescaledb.max_tuples_decompressed_per_dml_transaction` is 0 (unlimited) on this server. The design does not depend on that, because the bound stays under its default of 100k.
- The idempotent rerun does no DML on compressed data.
- After each loaded year, `CALL run_job(1076)` recompresses the partial chunks before the next year, so the uncompressed heap stays bounded at about one year of Massive rows. Each year also starts with a disk headroom check (645 GB free today; `ohlcv_raw` is 24 GB).

## 9. Expected throughput

Per June 2024 month (1.8M rows): file read and aggregation about 12 s; accounting about 1 s; batch build and validation about 2 s; binary COPY about 3-4 s client and server; classification of new rows over empty segments about 3 s; INSERT ... SELECT of 1.8M rows (4 indexes, symbol FK, chunk dispatch) not yet measured, budgeted at 40k rows/s, about 45 s. That totals about 65-70 s, roughly 26-28k rows/s, and about 5 h for 2003-2025 instead of 27 h.

If build step 1 measures the server INSERT below about 25k rows/s, the target fails no matter how the client is designed. The named levers, in order:

1. Overlap the next month's file reading with the current transaction (one reader thread; pyarrow releases the GIL). This takes about 15 s per month off the critical path.
2. Drop `ohlcv_raw_timestamp_idx`. It is redundant: the primary key leads with `"timestamp"` and a btree scans backwards. This is a migration, and it needs an EXPLAIN check of the readers first. It cuts index maintenance by about a quarter.

Parallel writers are not a lever: concurrent writers on one hypertable deadlock on index pages (CLAUDE.md key rules).

## 10. Equivalence proof

Harness: `tests/integration/test_raw_bulk_equivalence.py`, run against the indicagent database. Every run happens inside a transaction that is always rolled back. It runs while the sweep is not writing June 2024, since it takes the same series locks.

Sample: 40 June 2024 mapped 5m symbols, drawn with a recorded seed and forced to include AAPL, NVDA (10:1 split on 2024-06-10) and BRK.B (dotted ticker). Inside each transaction, set up as the login user before `SET LOCAL ROLE`:

| Group | Symbols | Setup | Exercises |
|---|---|---|---|
| new | 10 | their Massive June rows deleted inside the transaction | plain insert, compressed-chunk insert |
| unchanged | 10 | re-offered as stored | idempotence |
| replace | 8 | close plus one tick on 3 percent of bars, answered 1 day after stored `served_at`; one symbol all prices x2 (price-ratio flag), one shifted by one bar (time-shift flag) | revisions `raw`, upsert guard, detector, flags |
| superseded | 8 | same perturbation, answered 1 day before stored `served_at` | revisions `superseded`, raw untouched |
| mixed serve time | 2 | per-row `answered_at` split around the stored `served_at` within one series | row-by-row guard |
| duplicates | 2 | an identical repeat (collapses) and a contradicting repeat (both paths raise the same `ValueError`, each in a savepoint) | dedup semantics |

The current path runs `apply_raw_contract` once per series-chunk in today's call shape. The bulk path runs `apply_raw_contract_batch` over the same offers. Both get the same deterministic `request_id` per series-chunk (uuid5 of symbol and chunk ordinal), and one extra call uses `chunk_rows=1000` to exercise chunk splitting. Before rollback each path captures:

- `ohlcv_raw` for the 40 series in June: every column, digested with `float8send` and epoch microseconds, so the comparison is bit-identical. `load_id` is replaced by its (symbol, chunk ordinal) label.
- `ohlcv_revision` for the captured load ids: every column, with the same label mapping.
- `ohlcv_load` rows: every column except `load_id`, the insert time and the detail note's `horizon` and `selection` fields.
- `ohlcv_restatement_flag` rows, and the `LoadResult` and `IngressResult` counts.
- `market_data_ohlcv` and `bar_session_choice` digests for the 40 symbols in June. These must be identical, and both paths write none.

Pass: every digest equal and every count equal. The only allowed differences are the deferral fields: `n_unselected` (current) against `n_selection_deferred` plus `--compare`'s unselected for the same window, which must equal the current path's `n_unselected`. A third transaction runs the bulk path twice and asserts the second run has `n_new == n_changed == n_superseded == 0`, zero revision rows and an unchanged raw digest.

The harness also records per-stage timings and `EXPLAIN (ANALYZE, BUFFERS)` of the classification and INSERT statements, which is build step 1's measurement. Throughput is then confirmed on the first real month loaded with the bulk path. A rolled-back full month would only create WAL and bloat to prove a number the next real load gives anyway.

Alpaca and IBKR regression, as part of build step 5: replay a recorded Alpaca nightly 5m frame (5 symbols, last session) and an IBKR 10-year 1d offer through both paths, rolled back. Raw, revision, load and canonical digests must be equal. The 10-year 1d classification must take no longer than the current per-year read (about 3 s measured 2026-10-27), which guards against the 22 s unpruned-read regression.

## 11. Build plan

Every step is built in a scratch worktree off `origin/main`. Each step lands only between sweep invocations, after checking that no running or resumable fingerprinted batch writer imports `services/ohlcv_raw_writer.py` or `services/ohlcv_ingress_contract.py` (`code_content_key`). Each step gets /simplify, /review and `pytest tests/unit/ -n auto`. No research or statistics code moves, so `repro_frozen` is not needed.

1. `RawBatch`, `frame_to_raw_batch`, vectorized validation and dedup, in `ohlcv_raw_writer.py` and `bar_load.py`. Unit tests: parity with `_validate_row` and `_group_by_series` over table-driven and seeded random batches, covering every refusal message, contradiction counts, last-occurrence wins, nanosecond refusal and NaN volume.
2. `stage_and_classify` and `write_classified` (section 5), `apply_raw_contract_batch` with the deferral guard, `LoadResult.n_selection_deferred` and `load_status` `RAW-ONLY`. Unit tests: the classification CASE against `classify` plus the serve-time split on a fake cursor that evaluates the SQL contract; the detector constant; the rowcount-mismatch raise; status words.
3. The equivalence harness (section 10), run, with its report committed under `logs/`. Gate: bit-identical, and the per-stage timings decide whether the section 9 levers are needed. The loader does not switch before this gate passes.
4. Loader: columnar `MonthBatch`, packing, vectorized `account_day`, logging, the ArchiveIndex bitset (after tracemalloc confirms the cause), `run_job(1076)` and the disk check per year. `ops_selection_gate --compare --start/--end`. A dated step 5 amendment goes into the admission doc. Tests: packing never splits a series-chunk, rows per transaction never exceed the APR value, and account totals are unchanged against the June 2024 dry-run JSON.
5. Reroute `write_raw` and `apply_raw_contract` (the RawRow API, kept for fetcher, nightly and Tradier restore) through `RawBatch` onto the same core. Delete `_classify_series`, `preview_series` and the classification use of `_read_stored` (`read_stored_closes` keeps it). Tests: the existing writer and contract suites unchanged, plus the Alpaca and IBKR replays from section 10. This step closes the window in which two classification implementations coexist. It ships in this build, not as a later todo.

## 12. What could break the Alpaca and IBKR paths

- Step 5 reroutes them. Their chunks are small (at most 10k rows, one series), so the staged path costs about the same as today. The risks are count drift, which would break the request-row digest (`_with_digest`) and coverage upserts, and `new_timestamps`, which the adapter must still return as a sorted tuple. The replay digests and the unchanged unit suites cover both.
- Temp tables under `SET LOCAL ROLE`: they must be created inside the role context, or a later transaction under the role can't read them. A pooled connection reused by the login user doesn't need them. The tests cover a first transaction that rolls back after `CREATE TEMP TABLE` (the table disappears and the next transaction recreates it).
- psycopg prepared statements: after 5 executions psycopg prepares, and a generic plan would leave `lo`/`hi` to runtime chunk exclusion. The classification statement uses `prepare=False`.
- The deferral guard must never fire for a ranked vendor. A unit test asserts selection runs for `alpaca` and `ibkr` under today's policy rows, and an integration assertion checks that the nightly replay's `selected_slots` is equal across paths.
- Lock contention: Massive bulk transactions hold Massive series keys only. Vendor is part of the key, so they never block a nightly or fetcher writer on Alpaca or IBKR keys. Selection locks are not taken while deferred.
- The 1d ledger refresh (`refresh_1d_bounds`) and coverage upserts stay in `persist_chunk_atomically` and are untouched. The Massive loader passes `coverage=False`.

## 13. Risks

- The server-side INSERT rate is unmeasured, and the target depends on it (section 9). It is measured at build step 3, before the loader is switched.
- The amended step 5 gate moves the UNSELECTED number from the load to `--compare`. The definition is the same function, but the evidence now lives in a gate run, and a skipped gate run would leave Massive-only slots uncounted. `RAW-ONLY` stops anyone reading a deferred load as complete. The step 7 switch requires the per-year compare reports.
- The deferral proof assumes canonical equals the selection of raw before each year. The before-year compare checks this, so the gate fails loudly where the current path would repair silently.
- Rerouting the fetcher and nightly (step 5) touches the nightly Alpaca capture. It lands only after its replay digests match, and outside the 04:40 UTC nightly window.
- The ArchiveIndex diagnosis is a likely explanation, not a measurement, and it is confirmed by tracemalloc before the fix.

## 14. Build record 2026-11-11 (steps 1 to 4)

Built as designed, with these departures:

- The harness is `scripts/ops/bars/ops_raw_bulk_equivalence.py`, not a `tests/integration` file: the integration conftest rebuilds `indicagent_test` for every session, and the proof must run against the live database. Everything it does runs in transactions that always roll back. The SQL edge cases (signed zero, NULL volume on either side, a stored NULL `served_at`, an equal serve time, a one-ulp change, a stored row moved under the lock) are pinned against the row path on TEMP shadows in `tests/unit/services/test_ohlcv_raw_bulk_live.py`.
- BRK.B is on the identity gap list and has no Massive rows, so AXON (served as AAXN before its rename) is the forced mapped-name symbol.
- Series-chunks are cut over unique bars; `load_frame` cuts over offered rows. The two differ only for an offer that repeats a key, which Massive never does. The chunk-splitting scenario offers the identical-repeat series without its repeats.
- A rerun logs an offer older than the stored answer as superseded again, as the row path does, so the idempotence criterion is "the second run inserts and replaces nothing and logs only superseded revisions", not zero revisions.
- The deferral decision reads the policy under the batch's selection locks (`lock_selections`), as `select_and_write` does, so a `--reselect` that ranks Massive cannot slip between the check and the commit.
- `incumbent_slots` leaves never-selected kinds (`iex_rth`) out: a slot only they hold becomes unselected once Massive lands, so it is Massive-only for the gate.
- The ArchiveIndex cause was confirmed first: tracemalloc measured 1.07 MB per cached session, 6.2 GB for 5,829 sessions. With the bitset the June 2024 dry run peaks at 1.42 GB RSS and its day reports equal the stored dry-run JSON field for field.
- The year-start disk check is the free-space floor from the existing APR keys (`infra.compressed_hypertable_write_session.disk_path`, `.min_free_after_fraction`); a refusal stops before the year and still writes the report of the years already loaded.

Equivalence, June 2024 5m, 40 symbols, seed 20261111 (`logs/raw_bulk_equivalence_2024-06.json`): `ohlcv_raw`, `ohlcv_revision`, `ohlcv_load` and `ohlcv_restatement_flag` bit-identical between the paths at `chunk_rows` 10,000 and 1,000; LoadResult counts equal; canonical and `bar_session_choice` untouched by both; the row path's `n_unselected` (0) equals the windowed `--compare` count after the bulk path (0; June 2024 has no Massive-only slot, so this check is exercised only by the unit tests); the second bulk run inserts and replaces nothing; the contradicting repeat raises the same `ValueError` on both paths. Wall time for the 52,000 offered rows: row path 4.1 s, bulk path 0.67 s.

Measured rates (53,477 rows offered as new, rolled back): server INSERT 44.8k rows/s (EXPLAIN ANALYZE, 1,193 ms) while the 2024 sweep was writing, 60.5k rows/s with it idle; classification join 48 ms; binary COPY stage 0.07 s; bulk path end to end 41.7k rows/s (55.2k idle) without the file read. The section 9 ladder is not needed. Projected for a 1.8M-row month: about 12 s reading, 2 s staging and classifying, 40 s inserting, so about 55 to 60 s, roughly 30k rows/s and 5 h for 2003-2025.
