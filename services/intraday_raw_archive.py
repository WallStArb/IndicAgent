"""Single writer of ohlcv_intraday_raw_archive (phase 185 plan 12, single_writer).

The archive stores raw provider observations of the 15m/1h grid: the stored
IBKR rows bar_derivation removes from market_data_ohlcv (D-15's flag-never-
delete spirit), and, from plan 12 on, every new 15m/1h fetch (they never
enter market_data_ohlcv again; the grid readers see is derived from 5m).

One owner module, two write shapes, because the two callers use different
drivers (services/bar_derivation.py is asyncpg, the historical pipeline and
its persist helper are psycopg):

- ARCHIVE_FROM_TABLE_SQL: plan 11's INSERT ... SELECT, moved here
  byte-identical and imported back into bar_derivation (its tests pass
  unchanged). Archives the removable stored segment inside the per-symbol
  transaction, excluding synthetic-fill placeholders (they are not
  observations and the rewrite does not keep them; the masked-slot baseline
  in the plan 12 SUMMARY records them before the rewrite deletes them).
- insert_fetched_archive_rows(): one multi-row VALUES insert for a fetched
  chunk, ON CONFLICT DO NOTHING, synthetic fills refused. batch_id stays
  NULL: a fetch replaces no stored segment and the column is nullable per
  migration 383. The append-only boundary is the table's own triggers plus
  tests/unit/test_ohlcv_intraday_raw_archive_writer_boundary.py, which fails
  CI on any INSERT/COPY into the table from outside this module.

batch_size mirrors the ObservationSink pattern: the default is a local
constant, and callers with APR access pass
infra.backfill.ohlcv_insert_batch_size (the pipeline does).
"""

from __future__ import annotations

from typing import Any

from src.core.bar_normalizer import SOURCE_SYNTHETIC_FILL

_COLUMNS = (
    '"timestamp"',
    "symbol",
    "timeframe",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source",
    "base",
)
_ROW_PLACEHOLDERS = "(" + ",".join(["%s"] * len(_COLUMNS)) + ")"
_INSERT_FETCHED_SQL = (
    "INSERT INTO ohlcv_intraday_raw_archive "
    "(" + ", ".join(_COLUMNS) + ") VALUES "
    "{values} ON CONFLICT DO NOTHING"
)
_DEFAULT_BATCH_SIZE = 1000

# Plan 11's per-symbol archive statement, byte-identical to the
# _INSERT_ARCHIVE_SQL that lived in services/bar_derivation.py. asyncpg
# placeholders ($1, $2, $3): symbol, the timeframe list, the batch uuid.
ARCHIVE_FROM_TABLE_SQL = """
INSERT INTO ohlcv_intraday_raw_archive
    ("timestamp", symbol, timeframe, open, high, low, close, volume, source, base,
     price_sanity_status, batch_id)
SELECT "timestamp", symbol, timeframe, open, high, low, close, volume, source, base,
       price_sanity_status, $3::uuid
FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = ANY($2::text[])
  AND source <> 'synthetic_fill' AND source <> 'derived_5m'
ON CONFLICT DO NOTHING
"""


def insert_fetched_archive_rows(
    cur: Any, rows: list[tuple], *, batch_size: int = _DEFAULT_BATCH_SIZE
) -> int:
    """Insert one fetched chunk's rows into the archive; return the row count.

    `rows` are 10-tuples (timestamp, symbol, timeframe, open, high, low,
    close, volume, source, base) with base normally NULL. A synthetic_fill
    source raises: the archive holds observations, never placeholders.
    """
    if not rows:
        return 0
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")
    offenders = sorted({str(row[8]) for row in rows if row[8] == SOURCE_SYNTHETIC_FILL})
    if offenders:
        raise ValueError(
            "insert_fetched_archive_rows refuses synthetic fills (the archive stores "
            f"observations only): {len([r for r in rows if r[8] == SOURCE_SYNTHETIC_FILL])} "
            f"placeholder row(s), source(s) {offenders}"
        )
    if len(rows[0]) != len(_COLUMNS):
        raise ValueError(
            f"archive rows must have {len(_COLUMNS)} columns "
            f"(timestamp, symbol, timeframe, open, high, low, close, volume, source, base); "
            f"got {len(rows[0])}"
        )
    for i in range(0, len(rows), batch_size):
        chunk = rows[i : i + batch_size]
        sql = _INSERT_FETCHED_SQL.format(values=",".join([_ROW_PLACEHOLDERS] * len(chunk)))
        cur.execute(sql, [value for row in chunk for value in row])
    return len(rows)
