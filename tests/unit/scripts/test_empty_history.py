"""ohlcv_empty_history store (migration 354): gap subtraction, staleness, upsert shape."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from scripts.infrastructure.backfill import _empty_history as eh
from src.providers.ibkr import EmptyHistory

_D = timedelta(days=1)


def _dt(y, m, d):
    return datetime(y, m, d, tzinfo=UTC)


_EMPTY = eh.EmptyRange(_dt(2006, 9, 28), _dt(2024, 3, 26), _dt(2026, 9, 23))


@pytest.mark.parametrize(
    ("gaps", "expected"),
    [
        # the pre-history gap vanishes; the recent gap stays
        (
            [(_dt(2006, 9, 28), _dt(2024, 3, 26)), (_dt(2026, 8, 12), _dt(2026, 9, 23))],
            [(_dt(2026, 8, 12), _dt(2026, 9, 23))],
        ),
        # a gap straddling the range end keeps only the part after it
        ([(_dt(2024, 1, 1), _dt(2024, 6, 1))], [(_dt(2024, 3, 27), _dt(2024, 6, 1))]),
        # a gap starting before the range keeps only the part before it
        ([(_dt(2005, 1, 1), _dt(2007, 1, 1))], [(_dt(2005, 1, 1), _dt(2006, 9, 27))]),
        # entirely outside: untouched
        ([(_dt(2025, 1, 1), _dt(2025, 2, 1))], [(_dt(2025, 1, 1), _dt(2025, 2, 1))]),
    ],
)
def test_subtract_removes_only_the_verified_range(gaps, expected):
    assert eh.subtract(gaps, _EMPTY, _D) == expected


def test_freshness_is_bounded_by_reverify_days():
    now = _dt(2026, 12, 21)
    assert _EMPTY.is_fresh(now, reverify_days=90) is True
    assert _EMPTY.is_fresh(now + 2 * _D, reverify_days=90) is False


def test_load_reverify_days_fails_loudly_when_unset():
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = None
    with pytest.raises(RuntimeError, match="empty_history_reverify_days"):
        eh.load_reverify_days(conn)


def test_record_keeps_verified_and_inferred_parts_distinguishable():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    observed = EmptyHistory(
        verified_from=_dt(2023, 6, 1),
        empty_through=_dt(2024, 3, 26),
        n_confirming_chunks=2,
        reached_request_start=False,
    )
    eh.record(conn, "GEV", "5m", "ibkr", _dt(2006, 9, 28), observed)
    params = cur.execute.call_args.args[1]
    assert params == (
        "GEV",
        "5m",
        "ibkr",
        _dt(2006, 9, 28),
        _dt(2024, 3, 26),
        _dt(2023, 6, 1),
        2,
        False,
    )
