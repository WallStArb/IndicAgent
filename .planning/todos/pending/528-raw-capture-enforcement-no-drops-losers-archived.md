# 528: Raw capture enforcement: no drops, losers archived, completeness counted

Filed: 2026-10-10
Owner: pending
Priority: P1 (blocks scratch cleanup; data-loss defect)
Plan: docs/plans/2026-10-10-raw-capture-enforcement.md

The load engine silently discarded 81.7M vendor-served rows in the 2026-10-10
run (50.4M stored-held under first-writer-stays, 31.3M extended-hours), and
`ohlcv_intraday_raw_archive` structurally cannot hold a second source (PK has
no source dimension). Recoverable today only because the scratch parquets
still exist; scratch MUST NOT be cleaned until this lands.

Deliverables (per the plan doc):
1. Migration: PK -> (timestamp, symbol, timeframe, source), source NOT NULL,
   decompress/recompress + bare VACUUM per the template.
2. Engine: archive writer for stored-held and extended frames in the same
   transaction; unit tests assert no-drop.
3. Boundary test for the archive table.
4. Nightly completeness check (R6): served = authored + archived + refused,
   unexplained must be zero.
5. Backfill pass over the 2026-10-10 scratch parquets, then clean scratch.

Sequencing: after the 190-06 cutover; takes the next migration number then.

## Updates
