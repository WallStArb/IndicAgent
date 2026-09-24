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


_EMPTY = eh.EmptyRange(_dt(2006, 9, 28), _dt(2024, 3, 26), _dt(2026, 9, 23), 2)


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
    assert eh.apply_empty_range(gaps, None, _dt(2026, 9, 24), 90, _D, 2) == gaps
    assert eh.apply_empty_range(gaps, _EMPTY, _dt(2027, 9, 24), 90, _D, 2) == gaps
    assert eh.apply_empty_range(gaps, _EMPTY, _dt(2026, 9, 24), 90, _D, 2) == []


def test_single_answer_range_is_not_applied_until_confirmed():
    """todo 049: one "no data" answer is not trusted; the range keeps being asked."""
    once = eh.EmptyRange(_dt(2006, 9, 28), _dt(2024, 3, 26), _dt(2026, 9, 23), 1)
    gaps = [(_dt(2006, 9, 28), _dt(2024, 3, 26))]
    assert eh.apply_empty_range(gaps, once, _dt(2026, 9, 24), 90, _D, 2) == gaps


_OBSERVED = EmptyHistory(_dt(2023, 6, 1), _dt(2024, 3, 26), 2, False)
_WINDOW = (_dt(2006, 9, 28), _dt(2024, 3, 26))
_SLIVER = (_dt(2024, 3, 28), _dt(2024, 4, 5))  # after the prior range, before the first bar


@pytest.mark.parametrize(
    ("window", "observed", "prior", "bar_before", "expected"),
    [
        (_WINDOW, None, None, False, []),  # nothing learned, nothing to undo: no DB query
        (_WINDOW, _OBSERVED, None, False, ["probe", "record"]),
        (_WINDOW, None, _EMPTY, False, ["probe", "drop"]),  # prior re-asked, not confirmed
        (_SLIVER, None, _EMPTY, False, []),  # a window elsewhere never drops the prior
        (_WINDOW, _OBSERVED, _EMPTY, True, ["probe"]),  # not pre-history: says nothing
    ],
)
def test_reconcile_decisions(monkeypatch, window, observed, prior, bar_before, expected):
    calls = []
    monkeypatch.setattr(eh, "has_bar_before", lambda *a: calls.append("probe") or bar_before)
    monkeypatch.setattr(eh, "record", lambda *a: calls.append("record"))
    monkeypatch.setattr(eh, "drop", lambda *a: calls.append("drop"))
    eh.reconcile(MagicMock(), "GEV", "1h", "ibkr", window, observed, prior, 2 * _D)
    assert calls == expected


def test_record_merges_an_adjoining_prior_and_accumulates_confirmations():
    """A sliver verified next to the prior range extends it; it never replaces it."""
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    sliver = EmptyHistory(_dt(2024, 3, 28), _dt(2024, 4, 5), 1, True)
    eh.record(conn, "GEV", "1h", "ibkr", _dt(2024, 3, 28), sliver, prior=_EMPTY)
    params = cur.execute.call_args.args[1]
    assert params[3] == _dt(2006, 9, 28)  # empty_from kept from the prior range
    assert params[4] == _dt(2024, 4, 5)  # empty_through extended
    assert params[6] == 3  # 2 prior confirmations + 1


def test_record_head_stores_only_a_successful_lookup():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    eh.record_head(conn, "GEV", "ibkr", _dt(2024, 3, 27))
    assert cur.execute.call_args.args[1] == ("GEV", "ibkr", _dt(2024, 3, 27))
