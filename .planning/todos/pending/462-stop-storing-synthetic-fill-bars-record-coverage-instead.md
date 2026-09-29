---
status: pending
priority: P1
filed: 2026-09-29
source: todo 449 pace check (2026-09-29): 5m lane about to start, backfill writes about 5.5x more rows than IBKR returns
---

# Stop storing synthetic-fill bars; record coverage in a ledger instead

## What

`normalize_bars()` (`src/core/bar_normalizer.py`) inserts a flat bar (OHLC = prev_close, volume 0,
`source='synthetic_fill'`) for every interval slot with no real bar, on a continuous 24x7 calendar
grid, and the backfill stores them in `market_data_ohlcv`. Measured on the last 60 days: 1m, 5m,
15m and 1h are 81% to 83% placeholders; 1d is 33%. ETN 1h "stored 175175 bars" for 2006 to 2026 is
the full hourly grid, 4x that for 15m; IBKR did not return that many bars.

Why it is the wrong design here:

- Breaks `no_fill` (unified design section 12): fabricated rows sit in a permanent raw table and
  every reader must remember `market_data_ohlcv_tradeable`. A raw read that forgets it gets a
  silent wrong answer.
- The grid ignores sessions, so about 81% of slots are closed hours and "N gaps detected" is an
  artifact of the grid, not missing data.
- Stores use `ON CONFLICT DO NOTHING`. If a slot holds a synthetic bar and a real bar arrives
  later (old-venue routing per the CLAUDE.md listing-venue note, a late provider correction), the
  placeholder wins. Unverified; the mechanism is there and it fails silently.
- Cost: about 5.5x the rows of the real data in storage, WAL, compression and write time. The 768
  GB disk-full incident (migration 312) was this table.

What the fill provides is a coverage record ("this range was fetched, nothing traded"). That
belongs in a ledger at O(windows), not O(bars). `backfill_status` and `ohlcv_empty_history` are
partial versions of it.

## Steps

1. Consumer audit first (read-only). Who reads `market_data_ohlcv` raw, `synthetic_fill` or the
   canonical grid: `BarAuditor`, `bar_writer`, `bar_aggregator`, `bar_derivation` (already
   excludes `synthetic_fill`), `bar_history_seeder`, `backfill_feature_factory`,
   `_empty_history.py`, the streaming path, and the callers in
   `tests/unit/test_market_data_ohlcv_boundary.py`. Output: which need a contiguous series and
   which only need real bars.
2. Confirm or refute the late-real-bar hazard: find a slot with a `synthetic_fill` row where a
   real bar exists upstream, or prove the write path replaces the placeholder.
3. Design the coverage ledger (one row per symbol, tf, fetched window, real-bar count, fetched-at)
   and decide whether it extends `backfill_status` or is new. Gap-aware fetch reads the ledger,
   not the presence of filled slots.
4. Read-time grid: where a consumer needs a contiguous series, build it from real bars plus the
   exchange session calendar; derived, rebuildable, never stored.
5. Stop calling `normalize_bars()` in the backfill paths (`infrastructure_run_historical_pipeline.py`
   store pass and the one-time normalization pass, `backfill_feature_factory.py`).
6. Migration deleting `source = 'synthetic_fill'` rows: compressed hypertable, so
   decompress, delete, recompress, then a bare `VACUUM market_data_ohlcv;` last (CI-enforced,
   `docs/foundation/timescaledb-compressed-column-migration.md`). Measure chunk count and disk
   headroom first (performance SOP).

## Timing

Ideally lands before the todo 449 5m lane starts (HTF lane on attempt 23, about 221 of 698
symbols on 2026-09-29; the 5m lane follows in `intraday_chain.sh`). That avoids about 0.8B
placeholder rows for the 458 missing 5m names. Editing the backfill script under a live run:
`ic_engine` does not import it, but confirm before the edit. Step 1 and 2 can run now with no
edit.

## Related

Todo 449 (intraday backfill), todo 453 (pipelined persistence), todo 124 (tradeable view), todo
433 and phase 185 (backfill and `ohlcv_empty_history`), phase 186 (deletes the legacy
`forward_returns` table; check whether it also touches this).
