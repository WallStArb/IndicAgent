"""ohlcv_empty_history store (migration 354): gap subtraction, staleness, upsert shape."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from scripts.infrastructure.backfill import _empty_history as eh
from src.providers.base import EmptyHistory

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
    assert eh.is_fresh(_EMPTY.verified_at, now, reverify_days=90) is True
    assert eh.is_fresh(_EMPTY.verified_at, now + 2 * _D, reverify_days=90) is False


def test_apply_empty_range_ignores_missing_or_stale_ranges():
    gaps = [(_dt(2006, 9, 28), _dt(2024, 3, 26))]
    assert eh.apply_empty_range(gaps, None, _dt(2026, 9, 24), 90, _D) == gaps
    assert eh.apply_empty_range(gaps, _EMPTY, _dt(2027, 9, 24), 90, _D) == gaps
    assert eh.apply_empty_range(gaps, _EMPTY, _dt(2026, 9, 24), 90, _D) == []


_OBSERVED = EmptyHistory(_dt(2023, 6, 1), _dt(2024, 3, 26), 2, False)


@pytest.mark.parametrize(
    ("observed", "prior", "bar_before", "expected"),
    [
        (None, None, False, None),  # nothing to learn or undo: no DB query at all
        (_OBSERVED, None, False, "record"),
        (None, _EMPTY, False, "drop"),  # asked again, not confirmed empty
        (_OBSERVED, _EMPTY, True, None),  # not pre-history: says nothing
    ],
)
def test_reconcile_decisions(monkeypatch, observed, prior, bar_before, expected):
    calls = []
    monkeypatch.setattr(eh, "has_bar_before", lambda *a: calls.append("probe") or bar_before)
    monkeypatch.setattr(eh, "record", lambda *a: calls.append("record"))
    monkeypatch.setattr(eh, "drop", lambda *a: calls.append("drop"))
    eh.reconcile(MagicMock(), "GEV", "1h", "ibkr", _dt(2006, 9, 28), observed, prior)
    if observed is None and prior is None:
        assert calls == []
    else:
        assert calls == ["probe"] + ([expected] if expected else [])


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


def test_record_head_stores_only_a_successful_lookup():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    eh.record_head(conn, "GEV", "ibkr", _dt(2024, 3, 27))
    assert cur.execute.call_args.args[1] == ("GEV", "ibkr", _dt(2024, 3, 27))
