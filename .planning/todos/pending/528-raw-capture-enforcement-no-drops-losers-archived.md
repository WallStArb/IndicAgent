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

## Progress (2026-10-10)

- Migration 468 applied live: archive PK is (timestamp, symbol, timeframe, source), 87/87 chunks recompressed, 95.67M rows intact.
- Engine no-drop landed (c070abacb): extended + first-writer-held rows archive through insert_fetched_archive_rows; counts report archived.
- /simplify applied (3727b07e0): split_series is the one non-authored definition (engine + backfill), archive_frame_to_tuples + archive_rows the one write path, the archive NOT EXISTS predicate gained source, the retired vendor-named shell deleted.
- Recovery backfill RUNNING over the 2026-10-10 scratch parquets (~55M/82M at 17:10 EDT); scratch stays until it completes.
- R6 completeness check landed: scripts/ops/bars/ops_capture_completeness.py.
- T4 landed (856bf2cb5): src/providers/alpaca.py leaf behind history_leaf, ops_bar_nightly runner (5m authors, 1d raw-only), APR seeds in 469 (applied live). Not scheduled: the pull hold owns the reopen; the runner's live wiring is exercised then.
- Remaining: refused-chunk archive routing (RevisionRefused grid chunks are served-but-unstored; visible in the completeness report's refused_bars column), 190-07 bookkeeping.
