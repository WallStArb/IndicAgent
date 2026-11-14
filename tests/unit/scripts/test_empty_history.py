"""ohlcv_empty_history: the surviving module reads only (the writer left with the IBKR fetcher)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from scripts.infrastructure.backfill import _empty_history as eh
from src.providers.base import EmptyHistory

_D = timedelta(days=1)


def _dt(y, m, d):
    return datetime(y, m, d, tzinfo=UTC)


_EMPTY = eh.EmptyRange(_dt(2006, 9, 28), _dt(2024, 3, 26), _dt(2026, 9, 23), 2)


_OBSERVED = EmptyHistory(_dt(2023, 6, 1), _dt(2024, 3, 26), 2, False)
_WINDOW = (_dt(2006, 9, 28), _dt(2024, 3, 26))
_SLIVER = (_dt(2024, 3, 28), _dt(2024, 4, 5))  # after the prior range, before the first bar


# ---------------------------------------------------------------------------
# Provider heads: per-(symbol, timeframe) verified rows; seeded floors are not heads
# ---------------------------------------------------------------------------


# --- raw is per source: pre-history and real-bar probes read the asking vendor's rows -------


def _probe_conn(answer: bool = False):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (answer,)
    return conn, cur


def test_has_bar_between_reads_only_the_vendors_own_raw_rows():
    conn, cur = _probe_conn(False)
    assert eh.has_bar_between(conn, "GEV", "1d", _dt(2024, 1, 1), _dt(2024, 2, 1), "ibkr") is False
    sql, params = cur.execute.call_args.args
    assert "FROM ohlcv_raw" in sql and "vendor = %s" in sql
    assert params == ("GEV", "1d", "ibkr", _dt(2024, 1, 1), _dt(2024, 2, 1))
