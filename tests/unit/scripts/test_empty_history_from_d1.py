"""Plan 185-19 (D-20): ohlcv_empty_history rows are derived from ohlcv_request outcomes.

A span is empty only when the SMART request and a request to every former venue other
than the primary all answered no_data; any row not so confirmed is removed (and so
re-asked), and a confirmed pre-history span is recorded. Runs against a scripted
fake connection; the live-DB check is tests/integration/test_d3_d4_live.py.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from scripts.infrastructure.backfill import _empty_history as eh

_VENUES = ["NYSE", "ARCA", "ISLAND", "AMEX", "BATS"]
_DAY = timedelta(days=1)


def _dt(y, m, d):
    return datetime(y, m, d, tzinfo=UTC)


class FakeConn:
    """Scripts the handful of statements _empty_history issues, keyed by SQL text."""

    def __init__(self, *, requests, rows=(), first_bar_exists=False, venues=_VENUES):
        self.requests = requests  # symbol -> [(run, route, primary, start, end)]
        self.rows = list(rows)  # (symbol, empty_from, empty_through, verified_from)
        self.first_bar_exists = first_bar_exists
        self.venues = venues
        self.writes: list[tuple[str, tuple]] = []
        self._last: list = []
        self.commits = 0

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def commit(self):
        self.commits += 1

    def execute(self, sql, params=()):
        text = " ".join(sql.split())
        if "FROM config_state" in text:
            self._last = [(json.dumps(self.venues),)]
        elif "SELECT DISTINCT symbol FROM ohlcv_request" in text:
            self._last = [(s,) for s in self.requests]
        elif "FROM ohlcv_request" in text:
            self._last = list(self.requests.get(params[0], []))
        elif "FROM ohlcv_empty_history" in text and text.startswith("SELECT"):
            wanted = params[2] if len(params) > 2 else None
            self._last = [r for r in self.rows if wanted is None or r[0] in wanted]
        elif "market_data_ohlcv_tradeable" in text:
            self._last = [(self.first_bar_exists,)]
        else:
            self.writes.append((text.split(" (")[0].split(" WHERE")[0], params))
            self._last = []

    def fetchall(self):
        return self._last

    def fetchone(self):
        return self._last[0] if self._last else None


def _answers(run, start, end, *, skip=(), primary="NASDAQ"):
    routes = ["SMART", *_VENUES]
    return [(run, route, primary, start, end) for route in routes if route not in skip]


def test_confirmed_spans_require_smart_and_every_non_primary_venue():
    conn = FakeConn(requests={"XYZ": _answers("r1", _dt(2010, 1, 1), _dt(2012, 1, 1), skip=())})
    (span,) = eh.confirmed_empty_spans(conn, "XYZ", "1d")
    assert (span[0], span[1]) == (_dt(2010, 1, 1), _dt(2012, 1, 1))


def test_the_primary_venue_is_not_required():
    # primary NASDAQ == route ISLAND: its answer is SMART's own, never asked as a venue
    conn = FakeConn(
        requests={"XYZ": _answers("r1", _dt(2010, 1, 1), _dt(2012, 1, 1), skip=("ISLAND",))}
    )
    assert len(eh.confirmed_empty_spans(conn, "XYZ", "1d")) == 1


def test_a_venue_that_did_not_answer_no_data_confirms_nothing():
    conn = FakeConn(
        requests={"XYZ": _answers("r1", _dt(2010, 1, 1), _dt(2012, 1, 1), skip=("ARCA",))}
    )
    assert eh.confirmed_empty_spans(conn, "XYZ", "1d") == []


def test_answers_from_different_runs_never_combine():
    smart = _answers("r1", _dt(2010, 1, 1), _dt(2012, 1, 1), skip=_VENUES)
    venues = [
        ("r2", route, "NASDAQ", _dt(2010, 1, 1), _dt(2012, 1, 1))
        for route in _VENUES
        if route != "ISLAND"
    ]
    conn = FakeConn(requests={"XYZ": smart + venues})
    assert eh.confirmed_empty_spans(conn, "XYZ", "1d") == []


def test_an_unbacked_row_is_deleted():
    row = ("XYZ", _dt(2006, 1, 1), _dt(2012, 1, 1), _dt(2010, 1, 1))
    conn = FakeConn(requests={}, rows=[row])
    counts = eh.reconcile_empty_history(conn, "1d", "ibkr")
    assert counts == {"kept": 0, "deleted": 1, "inserted": 0, "extended": 0}
    assert any(w[0].startswith("DELETE FROM ohlcv_empty_history") for w in conn.writes)


def test_a_backed_row_is_kept_untouched():
    row = ("XYZ", _dt(2006, 1, 1), _dt(2012, 1, 1), _dt(2010, 1, 1))
    conn = FakeConn(
        requests={"XYZ": _answers("r1", _dt(2010, 1, 1), _dt(2012, 1, 1), skip=("ISLAND",))},
        rows=[row],
    )
    counts = eh.reconcile_empty_history(conn, "1d", "ibkr")
    assert counts == {"kept": 1, "deleted": 0, "inserted": 0, "extended": 0}
    assert conn.writes == []


def test_a_row_whose_verified_span_grew_is_extended():
    row = ("XYZ", _dt(2006, 1, 1), _dt(2011, 1, 1), _dt(2010, 1, 1))
    conn = FakeConn(
        requests={"XYZ": _answers("r1", _dt(2010, 1, 1), _dt(2012, 1, 1), skip=("ISLAND",))},
        rows=[row],
    )
    counts = eh.reconcile_empty_history(conn, "1d", "ibkr")
    assert counts["extended"] == 1 and counts["deleted"] == 0
    assert any(w[0].startswith("INSERT INTO ohlcv_empty_history") for w in conn.writes)


def test_a_confirmed_pre_history_span_without_a_row_is_inserted():
    conn = FakeConn(
        requests={"XYZ": _answers("r1", _dt(2010, 1, 1), _dt(2012, 1, 1), skip=("ISLAND",))}
    )
    counts = eh.reconcile_empty_history(conn, "1d", "ibkr")
    assert counts == {"kept": 0, "deleted": 0, "inserted": 1, "extended": 0}


def test_a_confirmed_span_after_a_real_bar_is_not_recorded():
    conn = FakeConn(
        requests={"XYZ": _answers("r1", _dt(2010, 1, 1), _dt(2012, 1, 1), skip=("ISLAND",))},
        first_bar_exists=True,
    )
    counts = eh.reconcile_empty_history(conn, "1d", "ibkr")
    assert counts == {"kept": 0, "deleted": 0, "inserted": 0, "extended": 0}


def test_symbols_scope_limits_the_rows_considered():
    rows = [
        ("AAA", _dt(2006, 1, 1), _dt(2012, 1, 1), _dt(2010, 1, 1)),
        ("BBB", _dt(2006, 1, 1), _dt(2012, 1, 1), _dt(2010, 1, 1)),
    ]
    conn = FakeConn(requests={}, rows=rows)
    counts = eh.reconcile_empty_history(conn, "1d", "ibkr", symbols=["AAA"])
    assert counts["deleted"] == 1


def test_only_the_daily_timeframe_is_defined():
    with pytest.raises(ValueError, match="1d"):
        eh.reconcile_empty_history(FakeConn(requests={}), "15m", "ibkr")
