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

## Closed 2026-10-10 (late session)

- Recovery pass completed: 81,992,087 rows archived (50,170,732 stored-held,
  31,821,355 extended) over the 1,529-symbol scratch parquets; extended-hours
  data is fully stored in the raw archive.
- Refused-chunk archive routing landed (ccc60bfa7): RevisionRefused carries the
  offered rows; the persist helper's second transaction routes them to the raw
  archive unconditionally (latest answer wins, synthetic fills still refused);
  ohlcv_load.n_archived (migration 470, applied live) records the count; the R6
  report folds it in via the refused bucket.
- Report archive-side correction (c661b67cb): unchanged re-offers and recorded
  removals net out of archive_served; the R6 formula change plus the one-time
  ledger correction (n_removed on the first botched pass's 2,196 rows,
  88,272,321 rows, applied live; identity exact: 189,178,601 - 18,914,193 -
  88,272,321 = 81,992,087 = the archive store) takes alpaca 5m to zero
  unexplained.
- Scratch cleaned: depth/ (8.0G) and root parquets deleted after the pass and
  the R6 balance; logs and alpaca_pilot_results.json kept.
- Follow-up filed as todo 530: the R6 monitor surfaces pre-existing unexplained
  rows (derived 15m/1d/1h, ibkr 5m 7.3M, tradier 1d 416K) -- grid-side
  ledger-vs-store artifacts predating the capture law, needing triage.
