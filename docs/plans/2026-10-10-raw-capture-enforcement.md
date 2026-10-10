# Raw capture enforcement: no drops, losers archived, completeness counted

Status: draft (filed 2026-10-10, todo 528)
Author: Brandon with Claude Code (session indicagent-49)
Informed by: the 2026-10-10 all-names Alpaca load audit; the data-layer
end-state design's standing rule that capture is universal and authoring is
single-source; owner directive 2026-10-10: "we need the raw data saved in all
sources if it exists" and "we need better rules, clear and enforced".

## The defect, measured

The load engine (`services/bar_load.load_series`) silently discards two
categories of vendor-served bars, returning only counters:

- **stored-held rows** (another source already authored the stamp under
  first-writer-stays): 50,382,257 rows dropped in the 2026-10-10 run.
- **extended-hours rows** (outside the RTH grid): 31,271,117 rows dropped in
  the same run.

81.7M rows of vendor-served raw hit the floor with no persistence. The raw
archive that should hold them (`ohlcv_intraday_raw_archive`, 95.67M
ibkr_named 15m/1h rows, compressed hypertable) structurally cannot: its
primary key `(timestamp, symbol, timeframe)` has no source dimension, so a
second vendor's row for an already-keyed slot is unrepresentable.

Why this matters: multiple data sources exist to disagree productively, i.e.
vendor-agreement audits (d2/D7 basis machinery), depth extension past vendor
floors, and restatement. Every one requires keeping the non-canonical tape.
First-writer-stays must pick the canonical author, never destroy the loser.
This also violates the foundation principle "never drop data that could
contain signal".

Containment: nothing is permanently lost. The scratch parquets
(`data/scratch/alpaca-pilot/depth/`) hold every served bar for all 1,502
pulled names plus the 27-name completion pull. **Scratch must not be cleaned
until the archive backfill lands.**

## Rules (the contract, stated once)

- **R1 Raw capture is universal and multi-vendor.** Every vendor's served
  bars for every active instrument, RTH and extended, are persisted per
  source at pipeline time. Scratch is staging, never storage: a pull product
  is either canonical-authored or raw-archived in the same run. Nothing hits
  the floor.
- **R2 Authoring is single-source per span.** `market_data_ohlcv` keeps
  first-writer-stays unchanged; the losing source's rows go to the raw
  archive carrying their `source`.
- **R3 Derivation owns derived timeframes** (15m/1h, the daily stage),
  computed from canonical only, exactly as today.
- **R4 Compute never reads the archive.** The grid view remains the only
  compute surface; the boundary test gains the archive.
- **R5 Retention.** The raw archive is permanent, subject only to the
  written exclusion policy. Scratch may be deleted only after its archive
  summary row is written (the derived-data-cache rule, applied to capture).
- **R6 Completeness is counted, not assumed.** A nightly completeness check:
  vendor-served rows = authored + archived + vendor-refused (no_data
  tombstones), per (source, timeframe), zero unexplained loss.

## Enforcement design

1. **Migration: source into the archive key.** Decompress, extend the PK to
   `(timestamp, symbol, timeframe, source)`, recompress, then bare
   `VACUUM ohlcv_intraday_raw_archive;` (compressed-hypertable column/PK
   template; the migration-312 lesson is CI-enforced). Existing rows are
   already `source='ibkr_named'` (verified: no NULLs); the column becomes
   NOT NULL in the same migration.
2. **Engine: no drop path.** `load_series` gains an archive writer: the
   stored-held frame and the extended frame go to
   `ohlcv_intraday_raw_archive` with `source=policy.vendor` in the same
   `persist_chunk_atomically` transaction as the canonical write. Unit
   tests assert: stored-held count == archived count; extended count ==
   archived count; canonical store unchanged by losers.
3. **Boundary test**: `ohlcv_intraday_raw_archive` joins the raw-read
   allow-list test so compute can never grow a read path to it.
4. **Completeness check**: a small ops script (R6) over `ohlcv_load` +
   `ohlcv_intraday_raw_archive` + `market_data_ohlcv`, runnable nightly and
   after any campaign; output is one row per (source, timeframe) with the
   three-way split and an explicit `unexplained` column that must be zero.

## Backfill of the already-dropped rows

The 81.7M rows from the 2026-10-10 run are re-derivable from scratch
parquet without re-hitting the vendor: one archive-only pass over the
parquets (stored-held and extended frames), no first-writer-stays involved.
Runs after the migration, before any scratch cleanup.

## Sequencing

1. 190-06 cutover (owner gate) lands first; this migration follows it and
   takes the next migration number at execution time.
2. Engine change and migration land together (the engine's archive writer
   requires the wider key).
3. Backfill pass over scratch, then R6 check, then scratch is cleanable.
4. The 2026-10-10 27-name completion pull loads canonically now
   (uncontested names); their extended rows archive via the backfill pass.
