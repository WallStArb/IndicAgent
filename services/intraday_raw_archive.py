"""Single writer of ohlcv_intraday_raw_archive (phase 185 plan 12, single_writer).

The archive stores raw provider observations of the 15m/1h grid: the stored
IBKR rows bar_derivation removes from market_data_ohlcv (D-15's flag-never-
delete spirit), and, from plan 12 on, every new 15m/1h fetch (they never
enter market_data_ohlcv again; the grid readers see is derived from 5m).

One owner module, two write shapes, because the two callers use different
drivers (services/bar_derivation.py is asyncpg, the historical pipeline and
its persist helper are psycopg):

- ARCHIVE_FROM_TABLE_SQL: plan 11's INSERT ... SELECT, imported back into
  bar_derivation. Archives the removable stored segment inside the per-symbol
  transaction, only for keys the archive does not already hold (plan 185-39
  replaced ON CONFLICT DO NOTHING by NOT EXISTS: the same semantics without a
  first-write-wins clause; a stored vendor row that disagrees with an archived
  one is recorded by the grid stage as ohlcv_revision origin archive_segment,
  plan 185-31, so the dead synthetic_fill filter is gone: migration 444 keeps
  synthetic fills out of market_data_ohlcv).
- insert_fetched_archive_rows(): a fetched chunk written by the ingress write
  contract (services/ohlcv_ingress_contract.py, plan 185-39). Stored rows for
  the chunk's keys are read; new rows are inserted; a changed row is rewritten
  (latest answer wins) with its old values in ohlcv_revision and one ohlcv_load
  row (destination archive) recording the counts; identical rows are not
  written; a chunk that revises more than the allowed share is refused with
  RevisionRefused. Synthetic fills are refused. batch_id stays NULL: a fetch
  replaces no stored segment and the column is nullable per migration 383.

UPDATE is allowed here because the archive keeps the latest answer and the old
values are kept in ohlcv_revision; DELETE and TRUNCATE are refused by trigger
(migration 448 replaced 383's UPDATE-or-DELETE ban). The single-owner boundary
is tests/unit/test_ohlcv_intraday_raw_archive_writer_boundary.py, which fails
CI on any INSERT/COPY into the table from outside this module.

batch_size mirrors the ObservationSink pattern: the default is a local
constant, and callers with APR access pass
infra.backfill.ohlcv_insert_batch_size (the pipeline does).
"""

from __future__ import annotations

from typing import Any

from services.ohlcv_ingress_contract import (
    DEFAULT_CALLER,
    DESTINATION_ARCHIVE,
    apply_ingress_contract,
)
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
# Plain multi-row INSERT of new rows; the contract has classified the chunk against stored rows.
_INSERT_FETCHED_SQL = (
    "INSERT INTO ohlcv_intraday_raw_archive " "(" + ", ".join(_COLUMNS) + ") VALUES " "{values}"
)
# The changed set: the latest answer wins (old values are already in ohlcv_revision).
# The conflict target is the full key including source (migration 468): two vendors may
# hold raw observations for the same slot, and one vendor's answer never revises another's.
_REPLACE_FETCHED_SQL = (
    _INSERT_FETCHED_SQL + ' ON CONFLICT ("timestamp", symbol, timeframe, source) DO UPDATE SET '
    "open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close, "
    "volume = EXCLUDED.volume, source = EXCLUDED.source, base = EXCLUDED.base, "
    "archived_at = now()"
)
_DEFAULT_BATCH_SIZE = 1000

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
  )
"""


def _write_rows(sql_template: str, cur: Any, rows: list[tuple], batch_size: int) -> None:
    for i in range(0, len(rows), batch_size):
        chunk = rows[i : i + batch_size]
        sql = sql_template.format(values=",".join([_ROW_PLACEHOLDERS] * len(chunk)))
        cur.execute(sql, [value for row in chunk for value in row])


def insert_fetched_archive_rows(
    cur: Any,
    rows: list[tuple],
    *,
    batch_size: int = _DEFAULT_BATCH_SIZE,
    caller: str = DEFAULT_CALLER,
) -> int:
    """Write one fetched chunk into the archive by the ingress write contract; return the
    number of rows offered.

    `rows` are 10-tuples (timestamp, symbol, timeframe, open, high, low,
    close, volume, source, base) with base normally NULL. A synthetic_fill
    source raises: the archive holds observations, never placeholders. Raises
    RevisionRefused (nothing written) when the chunk revises more than the
    allowed share of the rows it overlaps.
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
    return apply_ingress_contract(
        cur,
        rows,
        destination=DESTINATION_ARCHIVE,
        caller=caller,
        write_new=lambda c, new: _write_rows(_INSERT_FETCHED_SQL, c, new, batch_size),
        write_changed=lambda c, changed: _write_rows(_REPLACE_FETCHED_SQL, c, changed, batch_size),
    )
