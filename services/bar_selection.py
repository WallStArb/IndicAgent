"""The canonical vendor-row writer for direct timeframes (1m, 5m, 4h), phase 191 plan 02.

Design: docs/plans/2026-10-12-unified-raw-bar-table-design.md (Canonical section, single_writer).
Selection, not authoring: the canonical row of each slot is chosen from `ohlcv_raw` by
src/intelligence/bars/selection.py (a pure function of raw rows and bar_source_policy) and
written to market_data_ohlcv. 1d is the daily rule's and 15m/1h are the grid's, so they are
refused here.

The caller owns the connection and its transaction; this module never commits. Policy rows and
the CVR bar_kind sort_order arrive as arguments (read-only inputs the caller loads), which keeps
the writer testable. New slots INSERT; a slot whose selected row differs from the stored one is
replaced by a plain multi-row INSERT ... ON CONFLICT DO UPDATE (never an UPDATE statement), the
shape _history_fetch.py and the ingress contract already use. A replaced canonical row is not
logged to ohlcv_revision: ohlcv_raw holds both vendors' values, and canonical is rebuildable
from raw. A selected row with NULL volume is skipped and counted, not filled: market_data_ohlcv
volume is NOT NULL and missing is never a placeholder.

Until plan 13 renames the column, the canonical row carries the `source` label of its
(vendor, kind). `canonical_columns` and `_INSERT_HEAD` are the only two places that change then.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.intelligence.bars.selection import Candidate, PolicyRow, select_all
from src.intelligence.bars.sources import DERIVATION_OWNED_TIMEFRAMES
from src.intelligence.bars.vendor_kind import vendor_kind_to_label

DIRECT_TIMEFRAMES = frozenset({"1m", "5m", "4h"}) - DERIVATION_OWNED_TIMEFRAMES

_INSERT_HEAD = (
    "INSERT INTO market_data_ohlcv "
    "(timestamp, symbol, timeframe, open, high, low, close, volume, source) VALUES "
)
_UPSERT_TAIL = (
    " ON CONFLICT (timestamp, symbol, timeframe) DO UPDATE SET "
    "open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close, "
    "volume = EXCLUDED.volume, source = EXCLUDED.source"
)
_ROW = "(%s,%s,%s,%s,%s,%s,%s,%s,%s)"
_PARAMS_PER_ROW = _ROW.count("%s")
_MAX_PARAMS = 65535  # psycopg's bind-parameter limit per statement

_READ_RAW_SQL = (
    'SELECT "timestamp", symbol, timeframe, vendor, kind, open, high, low, close, volume '
    'FROM ohlcv_raw WHERE symbol = %s AND timeframe = %s AND "timestamp" >= %s '
    'AND "timestamp" < %s'
)
_READ_CANONICAL_SQL = (
    'SELECT "timestamp", open, high, low, close, volume, source FROM market_data_ohlcv '
    'WHERE symbol = %s AND timeframe = %s AND "timestamp" >= %s AND "timestamp" < %s'
)


@dataclass(frozen=True)
class SelectionResult:
    new: int
    changed: int
    unchanged: int
    skipped_null_volume: int


def canonical_columns(vendor: str, kind: str) -> str:
    """The `source` label a canonical row carries for a selected (vendor, kind)."""
    return vendor_kind_to_label(vendor, kind)


def _canonical_row(c: Candidate) -> tuple:
    return (
        c.timestamp,
        c.symbol,
        c.timeframe,
        c.open,
        c.high,
        c.low,
        c.close,
        c.volume,
        canonical_columns(c.vendor, c.kind),
    )


def _write(cur: Any, rows: list[tuple], *, batch_rows: int, tail: str = "") -> None:
    size = min(batch_rows, _MAX_PARAMS // _PARAMS_PER_ROW)
    for start in range(0, len(rows), size):
        chunk = rows[start : start + size]
        cur.execute(
            _INSERT_HEAD + ",".join([_ROW] * len(chunk)) + tail,
            [value for row in chunk for value in row],
        )


def select_and_write(
    conn: Any,
    *,
    symbols: Sequence[str],
    timeframe: str,
    start: datetime,
    end: datetime,
    policy_rows: Sequence[PolicyRow],
    kind_order: Mapping[str, int],
    batch_rows: int,
) -> SelectionResult:
    """Select the canonical rows of [start, end) for `symbols` from ohlcv_raw and write them.

    Raises ValueError for a timeframe other than 1m, 5m or 4h and LookupError when a held slot
    has no policy row (nothing for that symbol is written before the raise).
    """
    if timeframe not in DIRECT_TIMEFRAMES:
        raise ValueError(
            f"bar_selection writes direct timeframes {sorted(DIRECT_TIMEFRAMES)} only; "
            f"{timeframe!r} belongs to the daily rule or the grid"
        )
    if batch_rows < 1:
        raise ValueError(f"batch_rows must be >= 1, got {batch_rows}")
    n_new = n_changed = n_unchanged = n_skipped = 0
    with conn.cursor() as cur:
        for symbol in sorted(symbols):
            cur.execute(_READ_RAW_SQL, (symbol, timeframe, start, end))
            candidates = [Candidate(*row) for row in cur.fetchall()]
            winners = select_all(candidates, policy_rows, kind_order)
            if not winners:
                continue
            cur.execute(_READ_CANONICAL_SQL, (symbol, timeframe, start, end))
            stored = {row[0]: tuple(row[1:]) for row in cur.fetchall()}
            new_rows: list[tuple] = []
            changed_rows: list[tuple] = []
            for winner in winners:
                if winner.volume is None:
                    n_skipped += 1
                    continue
                row = _canonical_row(winner)
                old = stored.get(winner.timestamp)
                if old is None:
                    new_rows.append(row)
                elif old == row[3:]:
                    n_unchanged += 1
                else:
                    changed_rows.append(row)
            _write(cur, new_rows, batch_rows=batch_rows)
            _write(cur, changed_rows, batch_rows=batch_rows, tail=_UPSERT_TAIL)
            n_new += len(new_rows)
            n_changed += len(changed_rows)
    return SelectionResult(n_new, n_changed, n_unchanged, n_skipped)
