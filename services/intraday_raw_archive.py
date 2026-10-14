"""bar_derivation's archive-from-table statement (phase 185 plan 12; legacy since phase 191 plan 05).

The archive table (ohlcv_intraday_raw_archive) is retired by phase 191: its rows live in
`ohlcv_raw`, and the fetcher and the Alpaca loader write raw through the ingress contract
(services/ohlcv_ingress_contract.py). The only thing left here is plan 11's INSERT ... SELECT that
bar_derivation imports back, which archives the removable stored segment inside its per-symbol
transaction until plan 191-08 moves derivation onto raw. The module and the table go with plan
191-16.

The statement archives only keys the archive does not already hold (plan 185-39 replaced ON
CONFLICT DO NOTHING by NOT EXISTS: the same semantics without a first-write-wins clause); a
stored vendor row that disagrees with an archived one is recorded by the grid stage as
ohlcv_revision origin archive_segment (plan 185-31). Migration 444 keeps synthetic fills out of
market_data_ohlcv, so the old synthetic_fill filter is gone. The single-owner boundary is
tests/unit/test_ohlcv_intraday_raw_archive_writer_boundary.py.
"""

from __future__ import annotations

# Plan 11's per-symbol archive statement (the _INSERT_ARCHIVE_SQL that lived in
# services/bar_derivation.py; 185-39 swapped its ON CONFLICT clause for NOT EXISTS). asyncpg
# placeholders ($1, $2, $3): symbol, the timeframe list, the batch uuid.
ARCHIVE_FROM_TABLE_SQL = """
INSERT INTO ohlcv_intraday_raw_archive
    ("timestamp", symbol, timeframe, open, high, low, close, volume, source, base,
     price_sanity_status, batch_id)
SELECT "timestamp", symbol, timeframe, open, high, low, close, volume, source, base,
       price_sanity_status, $3::uuid
FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = ANY($2::text[])
  AND source <> 'derived_5m'
  AND NOT EXISTS (
      SELECT 1 FROM ohlcv_intraday_raw_archive a
      WHERE a."timestamp" = market_data_ohlcv."timestamp"
        AND a.symbol = market_data_ohlcv.symbol
        AND a.timeframe = market_data_ohlcv.timeframe
        AND a.source = market_data_ohlcv.source
  )
"""
