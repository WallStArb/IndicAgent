"""ops_split_calendar_audit.py (todo 587): calendar splits judged against canonical, pure parts.

No database, no Yahoo: canonical, raw and calendar rows are literals.
"""

from __future__ import annotations

import asyncio
import csv
import json
import math
from datetime import UTC, date, datetime, timedelta

import pytest

from scripts.ops.bars import ops_split_calendar_audit as audit
from src.intelligence.bars.corporate_actions import SplitRatioRule

_RULE = SplitRatioRule(max_numerator=50, max_denominator=4, rel_tol=0.002)
_TOL = 0.3
_SESSIONS = 3
_PARAMS = audit.AuditParams(_RULE, _TOL, _SESSIONS)
_DAYS = [
    date(2005, 2, 14) + timedelta(days=i)
    for i in range(24)
    if (date(2005, 2, 14) + timedelta(days=i)).weekday() < 5
]
_ON = date(2005, 2, 28)  # AAPL's 2:1
_IBKR = ("ibkr", "smart_trades")
_ALPACA = ("alpaca", "sip_rth")


def _step(day, on, factor, adjusted):
    return 1.0 if (adjusted or day < on) else 1.0 / factor


def _series(on, factor, *, adjusted=False, days=_DAYS, pair=("ibkr", "named")):
    """Canonical (date, close, vendor, kind) at 100 stepping by 1/factor on `on` unless adjusted,
    the raw series canonical is served from, and the calendar's split-adjusted closes, which never
    step."""
    canonical = [(d, 100.0 * _step(d, on, factor, adjusted), *pair) for d in days]
    raw = [(d, close) for d, close, _, _ in canonical]
    calendar = [(d, 100.0 / factor, factor if d == on else 0.0) for d in days]
    return canonical, calendar, raw


def _judge(symbol, canonical, calendar, raw, excluded=()):
    return audit.judge_events(symbol, canonical, calendar, raw, _RULE, _TOL, _SESSIONS, excluded)


def test_an_unadjusted_two_for_one_is_confirmed_with_its_evidence():
    canonical, calendar, raw = _series(_ON, 2.0)
    [event] = _judge("AAPL", canonical, calendar, {_IBKR: raw})
    # effective_date is the last day on the old scale (migration 400): the Friday before.
    assert (event.verdict, event.ratio, event.effective_date) == (
        "confirmed",
        2.0,
        date(2005, 2, 25),
    )
    assert event.canonical_step == round(-math.log(2.0), 6)
    assert (event.canonical_vendor, event.canonical_kind) == ("ibkr", "named")
    assert json.loads(event.route_steps) == {"ibkr/smart_trades": round(-math.log(2.0), 6)}
    assert event.unadjusted_routes == "ibkr/smart_trades"


def test_an_adjusted_canonical_and_a_spin_off_record_nothing():
    canonical, calendar, raw = _series(_ON, 2.0, adjusted=True)
    assert _judge("AAPL", canonical, calendar, {_IBKR: raw})[0].verdict == "adjusted"
    canonical, calendar, raw = _series(_ON, 1.046)  # IBM 2021 Kyndryl as Yahoo writes it
    assert _judge("IBM", canonical, calendar, {_IBKR: raw})[0].verdict == "not_a_split_ratio"


def test_an_operator_listed_spin_off_is_excluded_never_a_row():
    """SNX-shaped: a clean ratio with an unadjusted step, but the operator's list names it a
    spin-off (todo 587 Decision point 2)."""
    canonical, calendar, raw = _series(_ON, 2.0)
    [event] = _judge("SNX", canonical, calendar, {_IBKR: raw}, {("SNX", _ON)})
    assert (event.verdict, event.unadjusted_routes) == ("excluded_spin_off", "ibkr/smart_trades")
    [event] = _judge("SNX", canonical, calendar, {_IBKR: raw}, {("SNX", date(2005, 3, 1))})
    assert event.verdict == "confirmed"


def test_the_spin_off_list_starts_with_snx_and_needs_reason_and_evidence(tmp_path):
    listed = audit.operator_list(audit.SPIN_OFF_EXCLUSIONS)
    assert listed == {
        ("SNX", date(2020, 12, 1)): "Concentrix spin-off, CNXC first lists the same week"
    }
    bad = tmp_path / "x.csv"
    bad.write_text("symbol,date,reason,evidence\nIBM,2021-11-04,Kyndryl,\n")
    with pytest.raises(ValueError):
        audit.operator_list(bad)
    bad.write_text("symbol,date,reason,evidence\nIBM,2021-11-04,a,b\nIBM,2021-11-04,a,b\n")
    with pytest.raises(ValueError):
        audit.operator_list(bad)


def test_every_series_before_the_date_is_measured_on_its_own():
    """The SNX seam (review 2026-11-04): an IBKR span before an Alpaca one is measured against the
    calendar, never assumed from the series canonical serves at the date."""
    canonical, calendar, alpaca = _series(_ON, 2.0, pair=("alpaca", "sip_rth"))
    ibkr_unadjusted = [row for row in alpaca if row[0] < date(2005, 2, 21)]
    [event] = _judge("SNX", canonical, calendar, {_ALPACA: alpaca, _IBKR: ibkr_unadjusted})
    # IBKR has no session after the date: its scale cannot be measured, so no row.
    assert event.verdict == "route_conflict"
    ibkr = list(alpaca)
    [event] = _judge("SNX", canonical, calendar, {_ALPACA: alpaca, _IBKR: ibkr})
    assert (event.verdict, event.unadjusted_routes) == (
        "confirmed",
        "alpaca/sip_rth;ibkr/smart_trades",
    )
    ibkr_adjusted = [(d, c / 2 if d < _ON else c) for d, c in alpaca]
    [event] = _judge("SNX", canonical, calendar, {_ALPACA: alpaca, _IBKR: ibkr_adjusted})
    assert (event.verdict, event.unadjusted_routes) == ("confirmed", "alpaca/sip_rth")
    ibkr_odd = [(d, c * 1.3 if d < _ON else c) for d, c in alpaca]
    [event] = _judge("SNX", canonical, calendar, {_ALPACA: alpaca, _IBKR: ibkr_odd})
    assert event.verdict == "route_conflict"


def test_a_series_that_started_after_the_date_is_not_measured():
    canonical, calendar, raw = _series(_ON, 2.0)
    later = [row for row in raw if row[0] >= _ON]
    [event] = _judge("AAPL", canonical, calendar, {_IBKR: raw, _ALPACA: later})
    assert set(json.loads(event.route_steps)) == {"ibkr/smart_trades"}


def test_a_route_step_never_crosses_another_calendar_event():
    canonical, calendar, raw = _series(_ON, 2.0)
    # A spin-off two weeks before: the series' ratio to the calendar before it is not measured.
    calendar = [(d, c * (1.2 if d < date(2005, 2, 21) else 1.0), f) for d, c, f in calendar]
    calendar = [(d, c, 1.2 if d == date(2005, 2, 21) else f) for d, c, f in calendar]
    events = _judge("AAPL", canonical, calendar, {_IBKR: raw})
    split = next(e for e in events if e.calendar_date == _ON)
    assert json.loads(split.route_steps) == {"ibkr/smart_trades": round(-math.log(2.0), 6)}


def test_a_series_bar_after_effective_date_and_before_the_date_is_unmeasurable():
    """The rule rescales on or before effective_date: a series bar canonical lacks between it and
    the calendar date would keep the old scale, so the event is no row."""
    canonical, calendar, raw = _series(_ON, 2.0)
    canonical = [row for row in canonical if row[0] != date(2005, 2, 25)]
    [event] = _judge("AAPL", canonical, calendar, {_IBKR: raw})
    assert event.effective_date == date(2005, 2, 24) and event.verdict == "route_conflict"


def test_a_split_with_no_canonical_session_nearby_is_unmeasured():
    canonical, calendar, raw = _series(_ON, 2.0)
    calendar.append((date(2010, 6, 1), 50.0, 3.0))
    events = _judge("AAPL", canonical, calendar, {_IBKR: raw})
    assert [e.verdict for e in events] == ["confirmed", "unmeasured"]


_LINE = {
    "symbol": "AAPL",
    "calendar_date": "2005-02-28",
    "calendar_factor": "2.0",
    "effective_date": "2005-02-25",
    "canonical_step": "-0.69",
    "calendar_adjusted_step": "0.01",
    "canonical_vendor": "ibkr",
    "canonical_kind": "named",
    "route_steps": '{"ibkr/smart_trades": -0.693147}',
    "unadjusted_routes": "ibkr/smart_trades",
    "verdict": "confirmed",
    "ratio": "2.0",
    "error": "",
}


def _write(path, lines):
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=[*audit.CalendarEvent.__dataclass_fields__, "error"])
        writer.writeheader()
        for line in lines:
            writer.writerow({**_LINE, **line})
    return path


def test_only_confirmed_lines_become_rows_in_the_tables_orientation(tmp_path):
    path = _write(
        tmp_path / "audit.csv",
        [
            {},
            {
                "symbol": "UNIT",
                "calendar_factor": "0.1",
                "canonical_step": "2.30",
                "calendar_adjusted_step": "0.0",
                "route_steps": '{"ibkr/smart_trades": 2.302585}',
                "ratio": "0.1",
            },
            {"symbol": "IBM", "calendar_factor": "1.046", "verdict": "not_a_split_ratio"},
            {"symbol": "XPO", "verdict": "conflict"},
            {"symbol": "SNX", "verdict": "excluded_spin_off"},
        ],
    )
    rows = audit.confirmed_rows(path, _PARAMS, excluded=set())
    assert [(r["symbol"], r["action_type"], r["factor"]) for r in rows] == [
        ("AAPL", "split", 2.0),
        ("UNIT", "reverse_split", 0.1),
    ]
    detail = rows[0]["detail"]
    assert detail["unadjusted_routes"] == [{"vendor": "ibkr", "kind": "smart_trades"}]
    assert "unadjusted_span" not in detail
    assert detail["audit_file"] == "audit.csv" and len(detail["audit_sha256"]) == 64
    assert detail["rel_tol"] == _TOL and detail["route_sessions"] == _SESSIONS


@pytest.mark.parametrize(
    "edit",
    [
        {"route_steps": '{"ibkr/smart_trades": -0.3}'},  # a series off both scales
        {"route_steps": '{"ibkr/smart_trades": null}'},  # an unmeasured series
        {"unadjusted_routes": ""},  # a hand-edited list
        {
            "route_steps": '{"alpaca/sip_rth": -0.69, "ibkr/smart_trades": 0.0}'
        },  # own series adjusted
    ],
)
def test_a_line_the_current_apr_would_not_confirm_raises(tmp_path, edit):
    path = _write(tmp_path / "audit.csv", [edit])
    with pytest.raises(ValueError):
        audit.confirmed_rows(path, _PARAMS, excluded=set())


def test_a_confirmed_line_the_spin_off_list_now_names_raises(tmp_path):
    path = _write(tmp_path / "audit.csv", [{}])
    with pytest.raises(ValueError):
        audit.confirmed_rows(path, _PARAMS, excluded={("AAPL", date(2005, 2, 28))})


def test_an_existing_row_of_any_state_near_the_date_blocks_a_second_one():
    # The base table, not the current view: a voided or superseded decision is still a decision.
    assert "FROM corporate_action\n" in audit._EXISTING_SQL
    assert "'calendar_audit'" in audit._INSERT_SQL


class _Cursor:
    def __init__(self, conn):
        self.conn = conn
        self._row = None

    def execute(self, sql, params=None):
        self.conn.statements.append(sql)
        self._rows = []
        if "config_state" in sql:
            self._rows = [
                ("infra.backfill.split_ratio_max_numerator", "50"),
                ("infra.backfill.split_ratio_max_denominator", "4"),
                ("infra.backfill.split_ratio_rel_tol", "0.002"),
                ("threshold.split_continuity.rel_tol", "0.3"),
                ("threshold.split_calendar.route_sessions", "3"),
            ]
        # _routes_served's per-route observation check: the mock's every route is served.
        self._row = (True,) if "EXISTS" in sql else None

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._row

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Conn:
    def __init__(self):
        self.statements, self.committed, self.rolled_back = [], 0, 0

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _UndoneRouteConn(_Conn):
    """A conn whose route-served check finds no observations: apply_rows must refuse."""

    class Cursor(_Cursor):
        def execute(self, sql, params=None):
            super().execute(sql, params)
            if "EXISTS" in sql:
                self._row = (False,)

    def cursor(self):
        return self.Cursor(self)


def _audit_file(tmp_path):
    return _write(tmp_path / "audit.csv", [{}])


def test_no_calendar_audit_row_is_committed_without_commit(tmp_path, monkeypatch):
    """The guard (lead, todo 587): the default --apply runs the inserts and rolls them back."""
    conn = _Conn()
    monkeypatch.setattr(audit.psycopg, "connect", lambda *a, **k: conn)
    monkeypatch.setattr(audit, "Settings", lambda: type("S", (), {"database_url": "x"})())
    assert audit.main(["--apply", str(_audit_file(tmp_path))]) == 0
    assert (conn.committed, conn.rolled_back) == (0, 1)
    assert any("INSERT INTO corporate_action" in s for s in conn.statements)
    conn2 = _Conn()
    monkeypatch.setattr(audit.psycopg, "connect", lambda *a, **k: conn2)
    assert audit.main(["--apply", str(_audit_file(tmp_path)), "--commit"]) == 0
    assert (conn2.committed, conn2.rolled_back) == (1, 0)


def test_the_audit_mode_never_writes_the_table():
    source = audit.__file__ and open(audit.__file__).read()
    audit_body = source[source.index("def audit(") : source.index("def confirmed_rows(")]
    assert "INSERT" not in audit_body and "commit" not in audit_body


def test_every_unconfirmed_candidate_and_only_those_is_flagged(tmp_path):
    path = _write(
        tmp_path / "audit.csv",
        [
            {},
            {"symbol": "SNX", "verdict": "excluded_spin_off"},
            {"symbol": "JMSB", "verdict": "route_conflict"},
            {"symbol": "AA", "verdict": "conflict"},
            {"symbol": "MSFT", "verdict": "adjusted"},
            {"symbol": "IBM", "verdict": "not_a_split_ratio"},
        ],
    )
    got = audit.unconfirmed_candidates(path, bad_bars=())
    assert [(c["symbol"], c["detail"]["verdict"]) for c in got] == [
        ("SNX", "excluded_spin_off"),
        ("JMSB", "route_conflict"),
        ("AA", "conflict"),
    ]
    assert got[0]["effective_date"] == date(2005, 2, 25)


class _AsyncTx:
    def __init__(self, conn):
        self.conn = conn

    async def start(self):
        self.conn.events.append("begin")

    async def commit(self):
        self.conn.events.append("commit")

    async def rollback(self):
        self.conn.events.append("rollback")


class _AsyncConn:
    def __init__(self, rules, recorded=()):
        self.rules, self.events, self.recorded = rules, [], list(recorded)

    def transaction(self):
        return _AsyncTx(self)

    async def fetchval(self, sql, *args):
        if "quarantine_rules" in sql:
            return self.rules
        return datetime(2005, 2, 28, tzinfo=UTC)

    async def fetch(self, sql, *args):
        if "corporate_action_current" in sql:
            return self.recorded
        return [{"symbol": "GONE"}]


def test_the_quarantine_writes_through_bar_scrub_and_rolls_back_unless_commit(
    tmp_path, monkeypatch
):
    import services.bar_derivation_batch as batch
    import services.bar_scrub as scrub

    path = _write(tmp_path / "audit.csv", [{"symbol": "SNX", "verdict": "excluded_spin_off"}])
    monkeypatch.setattr(audit, "OPERATOR_BAD_BARS", _write_bad_bars(tmp_path))
    written = []

    async def fake_write_flags(conn, **kw):
        written.append((kw["symbol"], kw["rules_evaluated"], [f.quarantine for f in kw["flags"]]))
        return len(kw["flags"])

    async def fake_open(conn, **kw):
        return "b"

    async def fake_close(conn, *a, **kw):
        return None

    monkeypatch.setattr(scrub, "write_flags", fake_write_flags)
    monkeypatch.setattr(batch, "open_batch", fake_open)
    monkeypatch.setattr(batch, "close_batch", fake_close)
    both = '["unconfirmed_split", "operator_bad_bar"]'
    conn = _AsyncConn(both)
    assert asyncio.run(audit.quarantine_unconfirmed(conn, path, commit=False)) == 2
    # Both rules, each replaced globally: a name flagged today but absent from the files is
    # cleared; the unconfirmed candidate and the listed bad bar are quarantined.
    assert written == [
        ("CMCSA", frozenset({"operator_bad_bar"}), [True]),
        ("GONE", frozenset({"operator_bad_bar"}), []),
        ("GONE", frozenset({"unconfirmed_split"}), []),
        ("SNX", frozenset({"unconfirmed_split"}), [True]),
    ]
    assert conn.events == ["begin", "rollback"]
    conn = _AsyncConn(both)
    asyncio.run(audit.quarantine_unconfirmed(conn, path, commit=True))
    assert conn.events == ["begin", "commit"]
    for rules in ('["price_sanity"]', '["unconfirmed_split"]', '["operator_bad_bar"]'):
        with pytest.raises(ValueError, match="quarantine_rules"):
            asyncio.run(audit.quarantine_unconfirmed(_AsyncConn(rules), path, commit=True))


def test_a_listed_bad_bar_that_is_not_stored_refuses_the_quarantine(tmp_path, monkeypatch):
    path = _write(tmp_path / "audit.csv", [{"symbol": "MSFT", "verdict": "adjusted"}])
    monkeypatch.setattr(audit, "OPERATOR_BAD_BARS", _write_bad_bars(tmp_path))
    conn = _AsyncConn('["unconfirmed_split", "operator_bad_bar"]')

    async def no_bar(sql, *args):
        return conn.rules if "quarantine_rules" in sql else None

    conn.fetchval = no_bar
    with pytest.raises(ValueError, match="not a stored 1d bar"):
        asyncio.run(audit.quarantine_unconfirmed(conn, path, commit=True))
    assert conn.events == ["begin", "rollback"]


def test_a_listed_bad_bar_only_raw_holds_is_counted_not_refused(tmp_path, monkeypatch):
    path = _write(tmp_path / "audit.csv", [{"symbol": "MSFT", "verdict": "adjusted"}])
    monkeypatch.setattr(audit, "OPERATOR_BAD_BARS", _write_bad_bars(tmp_path))
    import services.bar_derivation_batch as batch
    import services.bar_scrub as scrub

    async def fake_write_flags(conn, **kw):
        return len(kw["flags"])

    async def fake_open(conn, **kw):
        return "b"

    async def fake_close(conn, *a, **kw):
        return None

    monkeypatch.setattr(scrub, "write_flags", fake_write_flags)
    monkeypatch.setattr(batch, "open_batch", fake_open)
    monkeypatch.setattr(batch, "close_batch", fake_close)
    conn = _AsyncConn('["unconfirmed_split", "operator_bad_bar"]')

    async def raw_only(sql, *args):
        if "quarantine_rules" in sql:
            return conn.rules
        return 1 if "FROM ohlcv_raw" in sql else None  # no canonical bar, raw has the date

    conn.fetchval = raw_only
    assert asyncio.run(audit.quarantine_unconfirmed(conn, path, commit=False)) == 0
    assert conn.events == ["begin", "rollback"]


def _patched_scrub(monkeypatch):
    import services.bar_derivation_batch as batch
    import services.bar_scrub as scrub

    async def fake_write_flags(conn, **kw):
        return len(kw["flags"])

    async def fake_open(conn, **kw):
        return "b"

    async def fake_close(conn, *a, **kw):
        return None

    monkeypatch.setattr(scrub, "write_flags", fake_write_flags)
    monkeypatch.setattr(batch, "open_batch", fake_open)
    monkeypatch.setattr(batch, "close_batch", fake_close)


def test_a_listed_bar_inside_the_canonical_series_is_never_moot(tmp_path, monkeypatch):
    # Canonical starts 2001-01-02, before the listed day: the missing bar is a typo or a gap,
    # not a series that starts later, so raw holding the date does not excuse it.
    path = _write(tmp_path / "audit.csv", [{"symbol": "MSFT", "verdict": "adjusted"}])
    monkeypatch.setattr(audit, "OPERATOR_BAD_BARS", _write_bad_bars(tmp_path))
    _patched_scrub(monkeypatch)
    conn = _AsyncConn('["unconfirmed_split", "operator_bad_bar"]')

    async def in_gap(sql, *args):
        if "quarantine_rules" in sql:
            return conn.rules
        if "min(" in sql:
            return datetime(2001, 1, 2, tzinfo=UTC)
        return 1 if "FROM ohlcv_raw" in sql else None

    conn.fetchval = in_gap
    with pytest.raises(ValueError, match="not a stored 1d bar"):
        asyncio.run(audit.quarantine_unconfirmed(conn, path, commit=True))


def test_a_candidate_with_no_canonical_bar_in_its_window_is_moot(tmp_path, monkeypatch):
    # The series starts after the event window (rebuild): the first-bar query is bounded to the
    # calendar date plus SAME_EVENT_DAYS and finds nothing, so no later bar is quarantined.
    path = _write(tmp_path / "audit.csv", [{"symbol": "OKE", "verdict": "excluded_spin_off"}])
    monkeypatch.setattr(audit, "OPERATOR_BAD_BARS", _write_bad_bars(tmp_path))
    _patched_scrub(monkeypatch)
    conn = _AsyncConn('["unconfirmed_split", "operator_bad_bar"]')
    seen = []

    async def window_empty(sql, *args):
        if "quarantine_rules" in sql:
            return conn.rules
        if sql == audit._FIRST_NEW_SCALE_SQL:
            seen.append(args)
            return None
        return datetime(2005, 2, 28, tzinfo=UTC)

    conn.fetchval = window_empty
    assert asyncio.run(audit.quarantine_unconfirmed(conn, path, commit=False)) == 1  # the bad bar
    [(symbol, effective, calendar_day, days)] = seen
    assert days == audit.SAME_EVENT_DAYS and calendar_day >= effective
    assert "$3::date + $4::int" in audit._FIRST_NEW_SCALE_SQL


def test_the_shipped_bad_bar_list_is_exactly_the_reviewed_bars():
    # The list changes only through review. Structure, not a frozen literal: every bar's
    # evidence cites the todo that reviewed it, no (symbol, date) appears twice, the pinned
    # core from 587 and 592 is always present, and the count matches the reviewed-batch
    # constant (bump it in the same review commit that adds bars; the 592 sweep's 123
    # single-bar-reversal quarantines took it to 131 on 2026-11-10, the 2007-06-13 day-file class of todo 627 to 147).
    import re

    bad = audit.operator_list(audit.OPERATOR_BAD_BARS)
    pinned_core = {
        ("FTNT", date(2014, 1, 10)),
        ("CMCSA", date(2017, 2, 17)),
        ("CDE", date(2008, 11, 18)),
        ("CME", date(2008, 7, 14)),
        ("OKE", date(2005, 4, 13)),
        ("NEXN", date(2025, 2, 18)),
        ("MVBF", date(2014, 4, 2)),
        ("UHAL", date(2022, 11, 9)),
    }
    assert pinned_core <= set(bad)
    assert len(bad) == len(set(bad)), "duplicate (symbol, date) in the bad-bars list"
    assert len(bad) == 147, "bump the reviewed count in the same review commit"
    rows = audit.OPERATOR_BAD_BARS.read_text().splitlines()[1:]
    assert len(rows) == 147
    uncited = [row.split(",")[0] for row in rows if not re.search(r"todo \d{3}", row)]
    assert not uncited, f"bars with no todo citation in their evidence: {uncited}"


def _write_bad_bars(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("symbol,date,reason,evidence\nCMCSA,2017-02-17,jump,flat on Yahoo\n")
    return path


def test_a_conflict_caused_by_a_listed_bad_bar_is_not_an_unconfirmed_split(tmp_path):
    """CMCSA 2017-02-21 (review 2026-11-05): the conflict is the 2017-02-17 bad bar, the series
    is adjusted; the bar goes to operator_bad_bar, not unconfirmed_split."""
    cmcsa = {
        "symbol": "CMCSA",
        "calendar_date": "2017-02-21",
        "effective_date": "2017-02-17",
        "verdict": "conflict",
    }
    path = _write(tmp_path / "audit.csv", [cmcsa, {**cmcsa, "symbol": "OKE"}])
    bad = audit.operator_list(_write_bad_bars(tmp_path))
    assert [c["symbol"] for c in audit.unconfirmed_candidates(path, bad)] == ["OKE"]


_ROWS_LINE = {
    "symbol": "FBIZ",
    "effective_date": "2015-08-18",
    "factor": "0.5",
    "unadjusted_routes": "ibkr/smart_trades",
    "calendar_adjusted_step": "-0.000681",
    "reason": "vendor anchored the 2015-08-31 2:1 at 2015-08-19",
    "evidence": "Yahoo adjusted flat across both dates; IBKR steps 2x up at 08-19 (todo 592)",
}


def _write_rows(path, lines):
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=audit.OPERATOR_ROWS_COLUMNS)
        writer.writeheader()
        for line in lines:
            writer.writerow({**_ROWS_LINE, **line})
    return path


def test_operator_rows_become_rows_in_the_tables_orientation(tmp_path):
    rows = audit.operator_rows(
        _write_rows(
            tmp_path / "rows.csv",
            [
                {},
                {
                    "symbol": "WST",
                    "effective_date": "2004-09-29",
                    "factor": "2.0",
                    "unadjusted_routes": "ibkr/smart_trades;alpaca/sip_rth",
                    "calendar_adjusted_step": "0.014486",
                },
            ],
        )
    )
    assert [(r["symbol"], r["action_type"], r["factor"]) for r in rows] == [
        ("FBIZ", "reverse_split", 0.5),
        ("WST", "split", 2.0),
    ]
    detail = rows[0]["detail"]
    assert detail["unadjusted_routes"] == [{"vendor": "ibkr", "kind": "smart_trades"}]
    assert detail["calendar_adjusted_step"] == -0.000681
    assert detail["rows_file"] == "rows.csv" and len(detail["rows_sha256"]) == 64
    assert detail["todo"] == 592 and detail["reason"] and detail["evidence"]


@pytest.mark.parametrize(
    "edit",
    [
        {"evidence": ""},  # every line needs its evidence
        {"reason": ""},
        {"factor": "1.0"},  # a factor of 1 is no rescale
        {"factor": "0"},
        {"calendar_adjusted_step": "nan"},
        {"unadjusted_routes": "ibkr/smart_adjusted"},  # no rescalable series
        {"unadjusted_routes": "ibkr/smart_trades;alpaca/sip_rth;x/y"},
        {"effective_date": "not-a-date"},
    ],
)
def test_an_unusable_operator_row_raises(tmp_path, edit):
    with pytest.raises(ValueError):
        audit.operator_rows(_write_rows(tmp_path / "rows.csv", [edit]))


def test_an_operator_row_decided_twice_in_one_file_raises(tmp_path):
    with pytest.raises(ValueError, match="decided twice"):
        audit.operator_rows(_write_rows(tmp_path / "rows.csv", [{}, {}]))


def test_operator_rows_roll_back_unless_commit(tmp_path, monkeypatch):
    """The same guard as --apply (lead, todo 587): the default runs the inserts and rolls them
    back."""
    conn = _Conn()
    monkeypatch.setattr(audit.psycopg, "connect", lambda *a, **k: conn)
    monkeypatch.setattr(audit, "Settings", lambda: type("S", (), {"database_url": "x"})())
    assert audit.main(["--apply-rows", str(_write_rows(tmp_path / "rows.csv", [{}]))]) == 0
    assert (conn.committed, conn.rolled_back) == (0, 1)
    assert any("INSERT INTO corporate_action" in s for s in conn.statements)
    conn2 = _Conn()
    monkeypatch.setattr(audit.psycopg, "connect", lambda *a, **k: conn2)
    assert (
        audit.main(["--apply-rows", str(_write_rows(tmp_path / "rows.csv", [{}])), "--commit"]) == 0
    )
    assert (conn2.committed, conn2.rolled_back) == (1, 0)


_IBKR_ROUTE = [{"vendor": "ibkr", "kind": "smart_trades"}]


def _apply_rows_against(tmp_path, monkeypatch, nearby):
    """--apply-rows --commit for the FBIZ line (route ibkr/smart_trades) with `nearby` as
    _EXISTING_SQL's rows: (type, effective, factor, inferred_by, rows_file, id, routes)."""

    class _NearbyCursor(_Cursor):
        def execute(self, sql, params=None):
            super().execute(sql, params)
            if "BETWEEN" in sql:
                self._rows = nearby

    class _NearbyConn(_Conn):
        def cursor(self):
            return _NearbyCursor(self)

    conn = _NearbyConn()
    monkeypatch.setattr(audit.psycopg, "connect", lambda *a, **k: conn)
    monkeypatch.setattr(audit, "Settings", lambda: type("S", (), {"database_url": "x"})())
    path = _write_rows(tmp_path / "rows.csv", [{}])
    assert audit.main(["--apply-rows", str(path), "--commit"]) == 0
    return any("INSERT INTO corporate_action" in s for s in conn.statements)


_NEARBY = ("split", date(2015, 8, 19), 2.0, "calendar_audit", True, "id")


def test_apply_rows_skips_a_row_the_name_has_already_decided(tmp_path, monkeypatch):
    """The existing-row guard is --apply-rows' only double-decide protection (review 2026-11-09):
    a decided event is skipped, not inserted a second time."""
    assert not _apply_rows_against(tmp_path, monkeypatch, [(*_NEARBY, _IBKR_ROUTE)])


def test_apply_rows_a_same_route_row_of_any_kind_still_blocks(tmp_path, monkeypatch):
    market_named = ("split", date(2015, 8, 19), 2.0, "calendar_audit", False, "id")
    nearby = [(*market_named, [*_IBKR_ROUTE, {"vendor": "alpaca", "kind": "sip_rth"}])]
    assert not _apply_rows_against(tmp_path, monkeypatch, nearby)


def test_apply_rows_an_unrelated_market_row_or_other_route_never_blocks(tmp_path, monkeypatch):
    market = ("split", date(2015, 8, 19), 2.0, "nightly_overlap", False, "id", None)
    other_route = (*_NEARBY, [{"vendor": "alpaca", "kind": "sip_rth"}])
    assert _apply_rows_against(tmp_path, monkeypatch, [market, other_route])


def test_apply_rows_refuses_a_route_that_never_served_the_span(tmp_path, monkeypatch):
    conn = _UndoneRouteConn()
    monkeypatch.setattr(audit.psycopg, "connect", lambda *a, **k: conn)
    monkeypatch.setattr(audit, "Settings", lambda: type("S", (), {"database_url": "x"})())
    with pytest.raises(ValueError, match="no raw 1d observations"):
        audit.main(["--apply-rows", str(_write_rows(tmp_path / "rows.csv", [{}])), "--commit"])
    # The refusal raises while reading, before the transaction: nothing written, nothing committed.
    assert (conn.committed, conn.rolled_back) == (0, 0)
    assert not any("INSERT INTO corporate_action" in s for s in conn.statements)


# ---------------- The lone-break sweep (todo 592) ----------------
#
# classify_breaks is pure over the same shapes judge_events takes; each test mirrors one of the
# ten landed cases' evidence patterns. Breaks arrive as the corpus pass reads them:
# (date, step, prev vendor, prev kind, vendor, kind).


def _brk(day, step, before=("ibkr", "named"), after=("ibkr", "named")):
    return (day, round(step, 6), *before, *after)


def _flat_calendar(days, closes, events=()):
    """Yahoo priced rows at `closes` (a step never enters the adjusted close) plus events."""
    return [(d, c, dict(events).get(d, 0.0)) for d, c in zip(days, closes, strict=True)]


def test_a_next_session_reversal_is_the_odd_bar_class():
    days = _DAYS[:8]
    on = days[4]
    canonical = [
        (d, 10.0 if d < on else (20.0 if d == on else 10.0), "ibkr", "named") for d in days
    ]
    raw = {("ibkr", "smart_trades"): [(d, c) for d, c, _, _ in canonical]}
    (event,) = audit.classify_breaks(
        "X",
        canonical,
        _flat_calendar(days, [10.0] * 8),
        raw,
        [_brk(on, math.log(2.0))],
        _SESSIONS,
    )
    assert event.verdict == "single_bar_reversal"
    assert event.next_step == pytest.approx(-math.log(2.0), abs=1e-6)


def test_a_move_yahoo_adjusted_carries_is_real_and_left_alone():
    days = _DAYS[:8]
    on = days[4]
    canonical = [(d, 10.0 if d < on else 45.0, "ibkr", "named") for d in days]
    raw = {("ibkr", "smart_trades"): [(d, c) for d, c, _, _ in canonical]}
    step = math.log(4.5)
    (event,) = audit.classify_breaks(
        "X",
        canonical,
        _flat_calendar(days, [10.0] * 4 + [45.0] * 4),
        raw,
        [_brk(on, step)],
        _SESSIONS,
    )
    assert event.verdict == "real_move"
    assert event.witness_step == pytest.approx(step, abs=1e-6)


def test_a_junction_whose_pre_series_sits_off_scale_takes_a_rescale_row():
    # IJR: canonical served by ibkr/named at half the correct level, alpaca/sip_rth correct
    # after the seam; Yahoo adjusted flat at the correct level throughout.
    days = _DAYS[:12]
    on = days[6]
    canonical = [
        (d, 34.0, "ibkr", "named") if d < on else (d, 68.0, "alpaca", "sip_rth") for d in days
    ]
    raw = {
        ("ibkr", "smart_trades"): [(d, 34.0) for d in days if d < on],
        ("alpaca", "sip_rth"): [(d, 68.0) for d in days if d >= on],
    }
    (event,) = audit.classify_breaks(
        "X",
        canonical,
        _flat_calendar(days, [68.0] * 12),
        raw,
        [_brk(on, math.log(2.0), before=("ibkr", "named"), after=("alpaca", "sip_rth"))],
        _SESSIONS,
    )
    assert event.verdict == "junction_rescale"
    assert event.unadjusted_route == "ibkr/smart_trades"
    assert event.factor == pytest.approx(0.5, abs=1e-4)
    assert event.effective_date == days[5]


def test_a_junction_whose_post_series_sits_off_scale_is_reported_not_fixed():
    days = _DAYS[:12]
    on = days[6]
    canonical = [
        (d, 68.0, "ibkr", "named") if d < on else (d, 34.0, "alpaca", "sip_rth") for d in days
    ]
    raw = {
        ("ibkr", "smart_trades"): [(d, 68.0) for d in days if d < on],
        ("alpaca", "sip_rth"): [(d, 34.0) for d in days if d >= on],
    }
    (event,) = audit.classify_breaks(
        "X",
        canonical,
        _flat_calendar(days, [68.0] * 12),
        raw,
        [_brk(on, -math.log(2.0), before=("ibkr", "named"), after=("alpaca", "sip_rth"))],
        _SESSIONS,
    )
    assert event.verdict == "reported"
    assert "POST" in event.evidence


def test_a_tape_switching_scale_under_a_calendar_event_is_the_fbiz_class():
    # FBIZ: the same ibkr series serves both sides but the vendor switched its adjustment at
    # its own anchor; Yahoo adjusted never moves and its calendar holds the event nearby.
    days = _DAYS[:12]
    on = days[6]
    canonical = [(d, 11.0 if d < on else 22.0, "ibkr", "named") for d in days]
    raw = {("ibkr", "smart_trades"): [(d, c) for d, c, _, _ in canonical]}
    calendar = _flat_calendar(days, [22.0] * 12, events={days[10]: 2.0})
    (event,) = audit.classify_breaks(
        "X",
        canonical,
        calendar,
        raw,
        [_brk(on, math.log(2.0))],
        _SESSIONS,
    )
    assert event.verdict == "inseries_rescale"
    assert event.factor == pytest.approx(0.5, abs=1e-4)
    assert event.unadjusted_route == "ibkr/smart_trades"
    assert event.effective_date == days[5]


def test_a_tape_scale_switch_with_no_calendar_is_an_unrecorded_reverse_split_on_the_jump_side():
    # UHAL's 11-10: the raw tape jumps 10x where no calendar record exists; factor < 1 means
    # reverse_split, measured, never assumed from the direction.
    days = _DAYS[:12]
    on = days[6]
    canonical = [(d, 5.2 if d < on else 52.0, "ibkr", "named") for d in days]
    raw = {("ibkr", "smart_trades"): [(d, c) for d, c, _, _ in canonical]}
    (event,) = audit.classify_breaks(
        "X",
        canonical,
        _flat_calendar(days, [52.0] * 12),
        raw,
        [_brk(on, math.log(10.0))],
        _SESSIONS,
    )
    assert event.verdict == "unrecorded_split"
    assert event.factor == pytest.approx(0.1, abs=1e-4)
    assert event.factor < 1


def test_a_flat_tape_against_a_stepping_canonical_is_reported():
    days = _DAYS[:12]
    on = days[6]
    canonical = [(d, 10.0 if d < on else 20.0, "ibkr", "named") for d in days]
    raw = {("ibkr", "smart_trades"): [(d, 10.0) for d in days]}
    (event,) = audit.classify_breaks(
        "X",
        canonical,
        _flat_calendar(days, [20.0] * 12),
        raw,
        [_brk(on, math.log(2.0))],
        _SESSIONS,
    )
    assert event.verdict == "reported"


def test_a_break_yahoo_cannot_bracket_is_reported():
    days = _DAYS[:8]
    on = days[4]
    canonical = [(d, 10.0 if d < on else 20.0, "ibkr", "named") for d in days]
    raw = {("ibkr", "smart_trades"): [(d, c) for d, c, _, _ in canonical]}
    calendar = [(d, 10.0, 0.0) for d in days[:2]]  # Yahoo ends before the break
    (event,) = audit.classify_breaks(
        "X",
        canonical,
        calendar,
        raw,
        [_brk(on, math.log(2.0))],
        _SESSIONS,
    )
    assert event.verdict == "reported"
    assert event.witness_step is None


# ---------------- --apply-massive (todo 600, admission step 4) ----------------

_SERVED = datetime(2026, 11, 10, 16, 43, 40, 310597, tzinfo=UTC)
_MASSIVE_LINE = {
    "symbol": "NVDA",
    "action_type": "split",
    "effective_date": "2024-06-07",
    "factor": "10.0",
    "recorded_at": _SERVED.isoformat(),
    "event_id": "E1",
    "execution_date": "2024-06-10",
    "attribution": "span",
    "bulk_ticker": "NVDA",
    "v3_ticker": "NVDA",
    "adjustment_type": "forward_split",
    "families": "bulk,v3",
    "reference_raw_ids": "00000000-0000-0000-0000-000000000001",
    "tape": "tape_step",
    "tape_level_step": "-2.194",
    "status": "proposed",
    "guard_skip": "",
}


def _massive_file(tmp_path, *edits):
    path = tmp_path / "proposed_rows.csv"
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(audit.PROPOSED_COLUMNS))
        writer.writeheader()
        for edit in edits or ({},):
            writer.writerow({**_MASSIVE_LINE, **edit})
    return path


def test_a_proposed_massive_line_becomes_a_reference_row_with_its_capture_time(tmp_path):
    (row,) = audit.massive_rows(_massive_file(tmp_path), _RULE)
    assert (row["symbol"], row["action_type"], row["effective_date"], row["factor"]) == (
        "NVDA",
        "split",
        date(2024, 6, 7),
        10.0,
    )
    # The announcement-time rule: knowable from the capture, never from the effective date.
    assert row["recorded_at"] == _SERVED
    assert row["detail"]["reference_raw_ids"] == ["00000000-0000-0000-0000-000000000001"]
    assert row["detail"]["todo"] == 600 and len(row["detail"]["proposed_sha256"]) == 64
    assert "rows_file" not in row["detail"]  # the key that marks a 592 operator row
    (reverse,) = audit.massive_rows(
        _massive_file(tmp_path, {"factor": "0.1", "action_type": "reverse_split"}), _RULE
    )
    assert reverse["action_type"] == "reverse_split"


@pytest.mark.parametrize(
    "edit, match",
    [
        ({"status": "not_a_split_ratio"}, "not a proposed row"),
        ({"tape": "tape_flat"}, "not a proposed row"),
        ({"factor": "1.391"}, "no recognised split ratio"),  # YUM 2016: a spin-off adjustment
        ({"action_type": "reverse_split"}, "reverse_split for factor"),
        ({"execution_date": "2024-06-07"}, "not before execution"),
        ({"recorded_at": "2026-11-10T16:43:40"}, "has no zone"),
        ({"reference_raw_ids": ""}, "missing"),
    ],
)
def test_a_massive_line_the_audit_would_not_propose_is_refused(tmp_path, edit, match):
    with pytest.raises(ValueError, match=match):
        audit.massive_rows(_massive_file(tmp_path, edit), _RULE)


def test_an_operator_listed_spin_off_never_becomes_a_reference_row(tmp_path):
    # The vendor serves SNX's 2020-12-01 Concentrix spin-off as a 2:1 split.
    snx = {
        "symbol": "SNX",
        "effective_date": "2020-11-30",
        "execution_date": "2020-12-01",
        "factor": "2.0",
    }
    listed = {("SNX", date(2020, 12, 1))}
    with pytest.raises(ValueError, match="spin-off"):
        audit.massive_rows(_massive_file(tmp_path, snx), _RULE, listed)
    # The shipped list names it.
    assert ("SNX", date(2020, 12, 1)) in audit.operator_list(audit.SPIN_OFF_EXCLUSIONS)


def test_a_massive_line_proposed_twice_is_refused(tmp_path):
    with pytest.raises(ValueError, match="proposed twice"):
        audit.massive_rows(_massive_file(tmp_path, {}, {}), _RULE)


class _ServedCursor(_Cursor):
    served: list = []

    def execute(self, sql, params=None):
        super().execute(sql, params)
        if "FROM reference_raw" in sql:
            self._rows = list(self.served)


class _ServedConn(_Conn):
    def __init__(self, served):
        super().__init__()
        self.served = served

    def cursor(self):
        cur = _ServedCursor(self)
        cur.served = self.served
        return cur


def test_apply_massive_checks_lineage_inserts_and_never_commits(tmp_path, monkeypatch):
    path = _massive_file(tmp_path)
    monkeypatch.setattr(audit, "Settings", lambda: type("S", (), {"database_url": "x"})())
    conn = _ServedConn([("00000000-0000-0000-0000-000000000001", _SERVED)])
    monkeypatch.setattr(audit.psycopg, "connect", lambda *a, **k: conn)
    assert audit.main(["--apply-massive", str(path)]) == 0
    assert (conn.committed, conn.rolled_back) == (0, 1)
    inserts = [s for s in conn.statements if "INSERT INTO corporate_action" in s]
    assert inserts and all("'massive_reference'" in s and "recorded_at" in s for s in inserts)
    # The consumers read massive_reference (d2-v6), so --commit writes; the gate is derived from
    # the one table of split meanings, and a code outside it refuses before any write.
    assert audit.MASSIVE_REFERENCE_CONSUMERS_READY
    committed = _ServedConn([("00000000-0000-0000-0000-000000000001", _SERVED)])
    monkeypatch.setattr(audit.psycopg, "connect", lambda *a, **k: committed)
    assert audit.main(["--apply-massive", str(path), "--commit"]) == 0
    assert (committed.committed, committed.rolled_back) == (1, 0)
    monkeypatch.setattr(audit, "MASSIVE_REFERENCE_CONSUMERS_READY", False)
    with pytest.raises(SystemExit, match="refused"):
        audit.main(["--apply-massive", str(path), "--commit"])
    # A cited page not stored, or a serve time that is not the row's, refuses the batch.
    for served in ([], [("00000000-0000-0000-0000-000000000001", _SERVED - timedelta(1))]):
        monkeypatch.setattr(audit.psycopg, "connect", lambda *a, s=served, **k: _ServedConn(s))
        with pytest.raises(ValueError, match="not stored|serve time"):
            audit.main(["--apply-massive", str(path)])


# The five Massive splits the writer's guard held (lead ruling 2026-11-11): each sits within
# SAME_EVENT_DAYS of a todo 592 operator row that corrects one incumbent route.
# (symbol, effective, execution, factor, the operator row's (effective, factor, action type))
_GUARD_CASES = [
    ("ELS", "2019-10-15", "2019-10-16", 2.0, (date(2019, 10, 15), 0.500018, "reverse_split")),
    ("IJR", "2017-01-18", "2017-01-19", 2.0, (date(2017, 1, 17), 0.5, "reverse_split")),
    ("OKE", "2012-06-01", "2012-06-04", 2.0, (date(2012, 6, 1), 0.504145, "reverse_split")),
    ("UHAL", "2022-11-09", "2022-11-10", 10.0, (date(2022, 11, 9), 10.0, "split")),
    ("WST", "2004-09-29", "2004-09-30", 2.0, (date(2004, 9, 29), 2.0, "split")),
]


class _GuardCursor(_ServedCursor):
    existing: list = []

    def execute(self, sql, params=None):
        super().execute(sql, params)
        if "FROM corporate_action\n" in sql:
            self._rows = [e for e in self.existing if e[0] == params[0]]
            self._rows = [e[1:] for e in self._rows]


class _GuardConn(_ServedConn):
    def __init__(self, served, existing):
        super().__init__(served)
        self.existing = existing

    def cursor(self):
        cur = _GuardCursor(self)
        cur.served, cur.existing = self.served, self.existing
        return cur


def _guard_file(tmp_path):
    lines = [
        {
            "symbol": s,
            "effective_date": eff,
            "execution_date": exe,
            "factor": str(f),
            "action_type": "split",
        }
        for s, eff, exe, f, _row in _GUARD_CASES
    ]
    return _massive_file(tmp_path, *lines)


def _inserted(conn):
    return [s for s in conn.statements if "INSERT INTO corporate_action" in s]


def test_an_incumbent_route_correction_never_blocks_the_markets_split(tmp_path, monkeypatch):
    path = _guard_file(tmp_path)
    monkeypatch.setattr(audit, "Settings", lambda: type("S", (), {"database_url": "x"})())
    served = [("00000000-0000-0000-0000-000000000001", _SERVED)]
    # Each operator row as _EXISTING_SQL returns it: (action_type, effective, factor,
    # inferred_by, detail ? 'rows_file'), keyed by symbol for the fake.
    corrections = [
        (s, kind, eff, factor, "calendar_audit", True)
        for s, _e, _x, _f, (eff, factor, kind) in _GUARD_CASES
    ]
    conn = _GuardConn(served, corrections)
    monkeypatch.setattr(audit.psycopg, "connect", lambda *a, **k: conn)
    assert audit.main(["--apply-massive", str(path)]) == 0
    assert len(_inserted(conn)) == 5
    # A market split already recorded at the same event still decides it.
    decided = [(s, kind, eff, f, "nightly_overlap", False) for s, kind, eff, f, *_ in corrections]
    conn = _GuardConn(served, decided)
    monkeypatch.setattr(audit.psycopg, "connect", lambda *a, **k: conn)
    assert audit.main(["--apply-massive", str(path)]) == 0
    assert _inserted(conn) == []


# ---------------- redate: a recorded split dated sessions off the vendor's (todo 608 item 7) ------

_OLD_ID = "2d79eb70-61f4-42a5-9f37-46151ae599b4"
_ITA = {
    "symbol": "ITA",
    "effective_date": "2026-11-04",
    "execution_date": "2026-11-05",
    "factor": "3.0",
    "supersedes": _OLD_ID,
}
_ITA_CURRENT = ("ITA", "split", date(2026, 11, 3), 3.0, "nightly_overlap")


def _redate_file(tmp_path, name="redate_rows.csv", **edit):
    path = tmp_path / name
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=[*audit.PROPOSED_COLUMNS, "supersedes"])
        writer.writeheader()
        writer.writerow({**_MASSIVE_LINE, **_ITA, **edit})
    return path


def test_a_redate_line_carries_the_row_it_replaces(tmp_path):
    (row,) = audit.massive_rows(_redate_file(tmp_path), _RULE)
    assert row["supersedes"] == _OLD_ID
    (plain,) = audit.massive_rows(_massive_file(tmp_path), _RULE)
    assert plain["supersedes"] is None
    with pytest.raises(ValueError, match="badly formed"):
        audit.massive_rows(_redate_file(tmp_path, supersedes="not-a-uuid"), _RULE)


@pytest.mark.parametrize(
    "current, match",
    [
        (None, "not a current"),
        (("QUAL", "split", date(2026, 11, 3), 3.0, "nightly_overlap"), "is a split of QUAL"),
        (("ITA", "reverse_split", date(2026, 11, 3), 3.0, "nightly_overlap"), "is a reverse_split"),
        (("ITA", "split", date(2026, 11, 3), 3.0, "massive_reference"), "never replaces"),
        (("ITA", "split", date(2026, 11, 3), 3.0, "calendar_audit"), "never replaces"),
        (("ITA", "split", date(2026, 11, 3), 4.0, "nightly_overlap"), "has factor 4.0"),
        (("ITA", "split", date(2026, 10, 1), 3.0, "nightly_overlap"), "outside the same event"),
    ],
)
def test_a_redate_only_replaces_a_current_restatement_row_of_the_same_event(
    tmp_path, current, match
):
    (row,) = audit.massive_rows(_redate_file(tmp_path), _RULE)
    with pytest.raises(ValueError, match=match):
        audit.check_redate(row, current)
    audit.check_redate(row, _ITA_CURRENT)


class _RedateCursor(_ServedCursor):
    current: tuple | None = _ITA_CURRENT
    nearby: list = []

    def execute(self, sql, params=None):
        super().execute(sql, params)
        if "FROM corporate_action_current" in sql:
            self._row = self.current
        elif "FROM corporate_action\n" in sql:
            self._rows = self.nearby


class _RedateConn(_ServedConn):
    def __init__(self, nearby, current=_ITA_CURRENT):
        super().__init__([("00000000-0000-0000-0000-000000000001", _SERVED)])
        self.nearby, self.current = nearby, current

    def cursor(self):
        cur = _RedateCursor(self)
        cur.served, cur.nearby, cur.current = self.served, self.nearby, self.current
        return cur


def _nearby(*extra):
    # _EXISTING_SQL's columns: type, effective, factor, inferred_by, rows_file, action_id.
    return [("split", date(2026, 11, 3), 3.0, "nightly_overlap", False, _OLD_ID), *extra]


def test_a_redate_supersedes_the_row_that_would_block_it(tmp_path, monkeypatch):
    path = _redate_file(tmp_path)
    monkeypatch.setattr(audit, "Settings", lambda: type("S", (), {"database_url": "x"})())
    conn = _RedateConn(_nearby())
    monkeypatch.setattr(audit.psycopg, "connect", lambda *a, **k: conn)
    assert audit.main(["--apply-massive", str(path)]) == 0
    (insert,) = _inserted(conn)
    assert "supersedes" in insert and "'massive_reference'" in insert
    # The same line without the replaced id is blocked by the recorded row (the guard stands).
    plain = _redate_file(tmp_path, supersedes="", name="plain.csv")
    conn = _RedateConn(_nearby())
    monkeypatch.setattr(audit.psycopg, "connect", lambda *a, **k: conn)
    assert audit.main(["--apply-massive", str(plain)]) == 0
    assert _inserted(conn) == []
    # Another row of the event still blocks the redate: only the replaced one is set aside.
    other = ("split", date(2026, 11, 4), 3.0, "seam_audit", False, "other-id")
    conn = _RedateConn(_nearby(other))
    monkeypatch.setattr(audit.psycopg, "connect", lambda *a, **k: conn)
    assert audit.main(["--apply-massive", str(path)]) == 0
    assert _inserted(conn) == []
    # A replaced row that is not current refuses the whole batch.
    conn = _RedateConn(_nearby(), current=None)
    monkeypatch.setattr(audit.psycopg, "connect", lambda *a, **k: conn)
    with pytest.raises(ValueError, match="not a current"):
        audit.main(["--apply-massive", str(path)])


def test_a_supersedes_without_recorded_at_is_refused_not_double_inserted(monkeypatch):
    # Only the massive_reference insert has a supersedes column; a calendar-path row carrying one
    # would drop the old row from the blockers and add a second current row.
    monkeypatch.setattr(audit.psycopg, "connect", lambda *a, **k: _RedateConn(_nearby()))
    row = {
        "symbol": "ITA",
        "action_type": "split",
        "effective_date": date(2026, 11, 4),
        "factor": 3.0,
        "supersedes": _OLD_ID,
        "detail": {},
    }
    settings = type("S", (), {"database_url": "x"})()
    with pytest.raises(ValueError, match="needs a recorded_at"):
        audit._apply_decided(settings, lambda conn: [row], commit=False)


# ---------------- the Massive witness (todo 608 before step 7) ----------------


def test_the_massive_witness_is_the_route_canonical_serves_with_its_split_events():
    from src.intelligence.bars.split_rescale import SplitFactor

    days = [date(2024, 6, 5), date(2024, 6, 6), date(2024, 6, 7), date(2024, 6, 10)]
    closes = list(zip(days, [1200.0, 1210.0, 1205.0, 121.0], strict=True))
    # NVDA's 10:1: last old-scale session 2024-06-07, the new scale from 2024-06-10.
    witness = audit.massive_witness(closes, [SplitFactor(date(2024, 6, 7), 10.0)])
    assert witness == [
        (date(2024, 6, 5), 120.0, 0.0),
        (date(2024, 6, 6), 121.0, 0.0),
        (date(2024, 6, 7), 120.5, 0.0),
        (date(2024, 6, 10), 121.0, 10.0),
    ]
    assert audit.massive_witness(closes, []) == [(d, c, 0.0) for d, c in closes]


def test_a_break_the_massive_witness_carries_is_a_real_move_in_its_name():
    days = _DAYS[:8]
    on = days[4]
    canonical = [(d, 10.0 if d < on else 45.0, "ibkr", "named") for d in days]
    raw = {("ibkr", "smart_trades"): [(d, c) for d, c, _, _ in canonical]}
    (event,) = audit.classify_breaks(
        "X",
        canonical,
        _flat_calendar(days, [10.0] * 4 + [45.0] * 4),
        raw,
        [_brk(on, math.log(4.5))],
        _SESSIONS,
        witness="Massive",
    )
    assert event.verdict == "real_move"
    assert event.evidence.startswith("Massive adjusted steps")


def test_a_massive_served_break_is_reported_never_an_operator_rescale_row():
    # Its remedy is a market split row (ops_massive_split_audit), since an operator row never
    # rescales Massive (corporate_actions.is_market_split).
    days = _DAYS[:10]
    on = days[5]
    canonical = [(d, 10.0 if d < on else 5.0, "massive", "sip_flat_adj") for d in days]
    (event,) = audit.classify_breaks(
        "X",
        canonical,
        _flat_calendar(days, [10.0] * 10),
        {},
        [_brk(on, -math.log(2.0), *[("massive", "sip_flat_adj")] * 2)],
        _SESSIONS,
        witness="Massive",
    )
    assert event.verdict == "reported" and event.unadjusted_route is None


def test_a_split_ending_before_the_first_massive_bar_is_no_event():
    from src.intelligence.bars.split_rescale import SplitFactor

    closes = [(date(2024, 1, 2), 50.0), (date(2024, 1, 3), 51.0)]
    witness = audit.massive_witness(closes, [SplitFactor(date(2023, 6, 1), 2.0)])
    assert [f for _d, _c, f in witness] == [0.0, 0.0]


def _break(symbol, day, verdict, step=-0.79):
    return audit.SweepBreak(symbol, day, step, verdict)


DAY = date(2026, 7, 21)


ACTIVE = {"CLBK", "DONE", "FAR", "WRONG", "REVERSE", "DOUBLE", "EDGE", "SBR", "SBRLISTED", "REP"}


def test_a_recorded_row_relabels_the_break_it_never_resolves_it():
    """The sweep reads canonical, so a break it finds is still there: a row of its own size inside
    the window is a record not applied (D7 unadjusted), a row of the opposite sign is D7
    double_adjusted, and a row of another size or outside the window explains nothing."""
    events = [
        _break("CLBK", DAY, "unrecorded_split"),  # nothing recorded
        _break("DONE", DAY, "unrecorded_split"),  # a 2.2 row 20 days off
        _break("FAR", DAY, "unrecorded_split"),  # a 2.2 row 31 days off: outside the window
        _break("EDGE", DAY, "unrecorded_split"),  # a 2.2 row exactly 30 days off: inside
        _break("WRONG", DAY, "unrecorded_split"),  # a 4.0 row 20 days off: another event
        _break("REVERSE", DAY, "unrecorded_split", step=0.69),  # a 0.5 row: its own size
        _break("DOUBLE", DAY, "unrecorded_split", step=0.79),  # a 2.2 row, the step the other way
    ]
    recorded = {
        "DONE": [(DAY - timedelta(days=20), 2.2)],
        "FAR": [(DAY + timedelta(days=31), 2.2)],
        "EDGE": [(DAY - timedelta(days=30), 2.2)],
        "WRONG": [(DAY - timedelta(days=20), 4.0)],
        "REVERSE": [(DAY, 0.5)],
        "DOUBLE": [(DAY, 2.2)],
    }
    left = audit.unresolved_breaks(events, recorded, {}, ACTIVE)
    assert [(e.symbol, e.verdict) for e in left] == [
        ("CLBK", "unrecorded_split"),
        ("DONE", "recorded_unapplied"),
        ("FAR", "unrecorded_split"),
        ("EDGE", "recorded_unapplied"),
        ("WRONG", "unrecorded_split"),
        ("REVERSE", "recorded_unapplied"),
        ("DOUBLE", "recorded_double_adjusted"),
    ]


def test_an_undecided_break_or_a_bad_bar_on_an_active_name_is_gated_unless_ruled():
    events = [
        _break("REP", DAY, "reported"),  # undecided: gated
        _break("REPRULED", DAY, "reported"),  # undecided, ruled by an operator line
        _break("RULED", DAY, "inseries_rescale"),
        _break("SBR", DAY, "single_bar_reversal"),  # an unquarantined bad bar: gated
        _break("SBRLISTED", DAY, "single_bar_reversal"),  # listed, quarantine not applied
        _break("MOVE", DAY, "real_move"),  # decided: not gated
        _break("INACTIVE", DAY, "unrecorded_split"),  # not an active name
    ]
    ruled = {("REPRULED", DAY): "real_move", ("RULED", DAY): "real_move"}
    active = {"REP", "REPRULED", "RULED", "SBR", "SBRLISTED", "MOVE"}
    left = audit.unresolved_breaks(events, {}, ruled, active, {("SBRLISTED", DAY)})
    assert [(e.symbol, e.verdict) for e in left] == [
        ("REP", "reported"),
        ("SBR", "single_bar_reversal"),
        ("SBRLISTED", "recorded_unapplied"),
    ]


def test_a_disposition_matching_no_break_is_reported_unused():
    events = [_break("A", DAY, "reported")]
    ruled = {("A", DAY): "x", ("A", DAY + timedelta(days=1)): "typo", ("B", DAY): "stale"}
    assert audit.unused_dispositions(events, ruled) == [
        ("A", DAY + timedelta(days=1)),
        ("B", DAY),
    ]


def test_disposition_class_defaults_to_real_move_and_rejects_unknown(tmp_path):
    old = tmp_path / "old.csv"
    old.write_text(f"symbol,date,reason,evidence\nA,{DAY},r,e\n")
    assert audit.sweep_dispositions(old) == {("A", DAY): "real_move"}
    new = tmp_path / "new.csv"
    new.write_text(
        f"symbol,date,class,reason,evidence\nA,{DAY},identity,r,e\nB,{DAY},,r,e\n"
        f"C,{DAY},real_move,r,e\nD,{DAY}, ,r,e\n"
    )
    assert audit.sweep_dispositions(new) == {
        ("A", DAY): "identity",
        ("B", DAY): "real_move",
        ("C", DAY): "real_move",
        ("D", DAY): "real_move",
    }
    bad = tmp_path / "bad.csv"
    bad.write_text(f"symbol,date,class,reason,evidence\nA,{DAY},identiy,r,e\n")
    with pytest.raises(ValueError, match="unknown class"):
        audit.sweep_dispositions(bad)


def test_an_unused_identity_disposition_fails_strict_but_a_live_one_does_not():
    assert audit.strict_failure(_counts(identity_dispositions=3)) == []
    assert audit.strict_failure(_counts(identity_dispositions=3, unused_identity_dispositions=1))


def _counts(**over):
    return dict.fromkeys(audit.GATE_COUNTS, 0) | {"active_names": 1500, "breaks_read": 40} | over


def test_strict_passes_only_a_sweep_that_read_something_and_left_nothing():
    assert audit.strict_failure(_counts()) == []
    assert audit.strict_failure(_counts(unresolved=2))
    assert audit.strict_failure(_counts(witness_error=1))
    assert audit.strict_failure(_counts(crowded_days=1))
    assert audit.strict_failure(_counts(breaks_read=0)), "an empty sweep must not pass"
    assert audit.strict_failure(_counts(active_names=0)), "no active names must not pass"


@pytest.mark.parametrize(
    "missing", ["active_names", "breaks_read", "witness_error", "unresolved", "crowded_days"]
)
def test_a_missing_gate_count_raises_and_never_reads_as_zero(missing):
    counts = _counts()
    del counts[missing]
    with pytest.raises(KeyError):
        audit.strict_failure(counts)


def test_the_class_counts_the_failure_message_reports_must_be_present_too():
    counts = _counts(unresolved=1)
    del counts["recorded_unapplied"]
    with pytest.raises(KeyError):
        audit.strict_failure(counts)


def test_the_frozen_market_wide_list_is_the_one_recorded_in_the_todo():
    todo = next((audit.project_root / ".planning/todos/pending").glob("622-*.md")).read_text()
    assert audit._MARKET_WIDE_DATES == {date(2020, 3, 9)}
    assert all(day.isoformat() in todo for day in audit._MARKET_WIDE_DATES)


def _main_with(monkeypatch, tmp_path, counts, argv):
    monkeypatch.setattr(audit, "Settings", lambda: object())
    seen = {}

    def fake_sweep(settings, out, rows_out, symbols, witness, dispositions):
        seen["args"] = (symbols, witness, dispositions)
        audit.write_unresolved(
            audit.unresolved_path(out), [_break("CLBK", DAY, "unrecorded_split")]
        )
        return counts

    monkeypatch.setattr(audit, "sweep", fake_sweep)
    return audit.main(["--sweep", "--out", str(tmp_path / "sweep.csv"), *argv]), seen


@pytest.mark.parametrize(
    "counts",
    [
        _counts(unresolved=1),
        _counts(witness_error=1),
        _counts(breaks_read=0),
        _counts(active_names=0),
    ],
)
def test_strict_exits_3_on_a_gated_sweep_and_names_the_unresolved_breaks(
    monkeypatch, tmp_path, counts, capsys
):
    code, _ = _main_with(monkeypatch, tmp_path, counts, ["--strict"])
    out = capsys.readouterr().out
    assert code == 3 and "strict:" in out and "CLBK" in out and "unrecorded_split" in out


def test_without_strict_the_same_sweep_exits_0_and_a_clean_strict_sweep_exits_0(
    monkeypatch, tmp_path
):
    assert _main_with(monkeypatch, tmp_path, _counts(unresolved=3), [])[0] == 0
    assert _main_with(monkeypatch, tmp_path, _counts(), ["--strict"])[0] == 0


@pytest.mark.parametrize(
    "argv",
    [["--strict", "--symbols", "AAPL"], ["--symbols", "AAPL", "--strict"]],
)
def test_strict_refuses_a_partial_universe(monkeypatch, tmp_path, argv):
    with pytest.raises(SystemExit) as stopped:
        _main_with(monkeypatch, tmp_path, _counts(), argv)
    assert stopped.value.code == 2


def test_strict_refuses_the_massive_witness_that_cannot_witness_its_own_tape(monkeypatch, tmp_path):
    """Under --witness massive a break on a Massive-served bar reads real_move by construction (the
    witness is raw Massive divided by the scales selection applies), so an unrecorded split there
    would pass; strict needs the independent Yahoo witness."""
    with pytest.raises(SystemExit) as stopped:
        _main_with(monkeypatch, tmp_path, _counts(), ["--strict", "--witness", "massive"])
    assert stopped.value.code == 2
    assert _main_with(monkeypatch, tmp_path, _counts(), ["--strict", "--witness", "yahoo"])[0] == 0
    # the Massive witness stays available to the ungated sweep
    assert _main_with(monkeypatch, tmp_path, _counts(), ["--witness", "massive"])[0] == 0


@pytest.mark.parametrize("flag", [["--strict"], ["--dispositions", "d.csv"]])
def test_the_sweep_flags_need_a_sweep(monkeypatch, tmp_path, flag):
    monkeypatch.setattr(audit, "Settings", lambda: object())
    with pytest.raises(SystemExit) as stopped:
        audit.main(["--audit", "--out", str(tmp_path / "o.csv"), *flag])
    assert stopped.value.code == 2


def test_dispositions_are_validated_before_the_database_is_opened(monkeypatch, tmp_path):
    bad = tmp_path / "disp.csv"
    bad.write_text("symbol,date,reason,evidence\nCLBK,2026-07-21,,\n")

    def refuse(*args, **kwargs):
        raise AssertionError("the database was opened before the dispositions were read")

    monkeypatch.setattr(audit.psycopg, "connect", refuse)
    with pytest.raises(ValueError, match="needs one line with reason and evidence"):
        audit.sweep(
            type("S", (), {"database_url": "x"})(), tmp_path / "o.csv", None, None, "yahoo", bad
        )


class _SweepConn:
    """The sweep's queries answered from canned rows, keyed by the SQL the script runs."""

    def __init__(self, *, steps, crowded, active, recorded):
        self._rows = {
            audit._SWEEP_STEPS_SQL: steps,
            audit._SWEEP_CROWDED_SQL: crowded,
            audit._ACTIVE_SQL: [(s,) for s in active],
            audit._GATE_SCOPE_SQL: [(s,) for s in active],
            audit._RECORDED_SQL: recorded,
        }

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        return list(self._rows.get(sql, []))


def _drive_sweep(monkeypatch, tmp_path, conn, events, errors=(), dispositions=None):
    """Run sweep() end to end on a fake connection; classify_breaks is stubbed to `events`."""
    monkeypatch.setattr(audit.psycopg, "connect", lambda *a, **k: conn)
    monkeypatch.setattr(audit, "_apr", lambda c: type("P", (), {"route_sessions": 3})())
    monkeypatch.setattr(audit, "_raw_series", lambda c, symbol: {})
    monkeypatch.setattr(
        audit, "_fetch_calendar", lambda symbol: ([], "boom" if symbol in errors else None)
    )
    monkeypatch.setattr(
        audit,
        "classify_breaks",
        lambda symbol, canonical, calendar, raw, breaks, route_sessions, witness: [
            e for e in events if e.symbol == symbol
        ],
    )
    monkeypatch.setattr(audit, "OPERATOR_BAD_BARS", tmp_path / "bad_bars.csv")
    (tmp_path / "bad_bars.csv").write_text("symbol,date,reason,evidence\n")
    settings = type("S", (), {"database_url": "x"})()
    out = tmp_path / "sweep.csv"
    return audit.sweep(settings, out, None, None, "yahoo", dispositions), out


def test_sweep_counts_what_it_gates_and_writes_the_unresolved_breaks(monkeypatch, tmp_path):
    """The wiring: every gate count comes out of the sweep itself, and strict_failure reads them."""
    day = DAY
    steps = [  # (symbol, day, step, prev vendor, prev kind, vendor, kind): the lone breaks read
        ("CLBK", day, -0.79, "massive", "sip_flat_adj", "massive", "sip_flat_adj"),
        ("DONE", day, -0.79, "massive", "sip_flat_adj", "massive", "sip_flat_adj"),
        ("SBR", day, -0.5, "massive", "sip_flat_adj", "massive", "sip_flat_adj"),
        ("INACT", day, -0.79, "massive", "sip_flat_adj", "massive", "sip_flat_adj"),
        ("WERR", day, -0.6, "massive", "sip_flat_adj", "massive", "sip_flat_adj"),
        ("RULED", day, -0.79, "massive", "sip_flat_adj", "massive", "sip_flat_adj"),
    ]
    events = [
        _break("CLBK", day, "unrecorded_split"),
        _break("DONE", day, "unrecorded_split"),
        _break("SBR", day, "single_bar_reversal"),
        _break("INACT", day, "unrecorded_split"),
        _break("RULED", day, "inseries_rescale"),
    ]
    disp = tmp_path / "disp.csv"
    disp.write_text(
        "symbol,date,reason,evidence\n"
        f"RULED,{day},continuous in the vendor close,filing\n"
        f"STRAY,{day},typo,none\n"
    )
    conn = _SweepConn(
        steps=steps,
        crowded=[(date(2020, 3, 9), 22), (date(2021, 5, 5), 25)],  # one listed, one not
        active=["CLBK", "DONE", "SBR", "WERR", "RULED"],
        recorded=[("DONE", day - timedelta(days=5), 2.2)],
    )
    counts, out = _drive_sweep(
        monkeypatch, tmp_path, conn, events, errors={"WERR"}, dispositions=disp
    )
    assert counts["breaks_read"] == 6  # five classified events plus the witness-error break
    assert counts["active_names"] == 5
    assert counts["witness_error"] == 1
    assert counts["recorded_unapplied"] == 1 and counts["recorded_double_adjusted"] == 0
    assert counts["unresolved"] == 4  # CLBK, DONE (recorded, unapplied), SBR, WERR (reported)
    assert counts["crowded_days"] == 1  # 2021-05-05 only; 2020-03-09 is on the frozen list
    assert counts["unused_dispositions"] == 1  # STRAY
    listed = list(csv.DictReader(audit.unresolved_path(out).open()))
    assert {r["symbol"]: r["verdict"] for r in listed} == {
        "CLBK": "unrecorded_split",
        "DONE": "recorded_unapplied",
        "SBR": "single_bar_reversal",
        "WERR": "reported",
    }
    assert audit.strict_failure(counts)


def test_sweep_counts_identity_dispositions_and_the_stale_ones(monkeypatch, tmp_path):
    steps = [("LIVE", DAY, -0.79, "massive", "sip_flat_adj", "massive", "sip_flat_adj")]
    events = [_break("LIVE", DAY, "reported")]
    disp = tmp_path / "disp.csv"
    disp.write_text(
        "symbol,date,class,reason,evidence\n"
        f"LIVE,{DAY},identity,seam,witness\n"
        f"GONE,{DAY},identity,seam,witness\n"
        f"STRAY,{DAY},real_move,typo,none\n"
    )
    conn = _SweepConn(steps=steps, crowded=[], active=["LIVE"], recorded=[])
    counts, _ = _drive_sweep(monkeypatch, tmp_path, conn, events, dispositions=disp)
    assert counts["identity_dispositions"] == 2
    assert counts["unused_dispositions"] == 2
    assert counts["unused_identity_dispositions"] == 1  # GONE only; STRAY is real_move
    assert counts["unresolved"] == 0  # the undecided LIVE break is ruled by its identity line
    assert any("identity dispositions" in r for r in audit.strict_failure(counts))


def test_an_identity_line_rules_only_an_undecided_break():
    events = [
        _break("UND", DAY, "reported"),
        _break("CONF", DAY, "unrecorded_split"),
        _break("RES", DAY, "inseries_rescale"),
        _break("SBR", DAY, "single_bar_reversal"),
    ]
    ruled = {(e.symbol, DAY): "identity" for e in events}
    left = audit.unresolved_breaks(events, {}, ruled, {e.symbol for e in events})
    assert [e.symbol for e in left] == ["CONF", "RES", "SBR"]
    as_move = {key: "real_move" for key in ruled}
    assert audit.unresolved_breaks(events, {}, as_move, {e.symbol for e in events}) == []


def test_a_stale_identity_line_exits_3_under_strict(monkeypatch, tmp_path, capsys):
    code, _ = _main_with(
        monkeypatch, tmp_path, _counts(unused_identity_dispositions=1), ["--strict"]
    )
    assert code == 3 and "identity dispositions" in capsys.readouterr().out


def test_a_sweep_that_reads_nothing_is_not_clean(monkeypatch, tmp_path):
    conn = _SweepConn(steps=[], crowded=[], active=[], recorded=[])
    counts, _ = _drive_sweep(monkeypatch, tmp_path, conn, [])
    assert counts["unresolved"] == 0
    assert audit.strict_failure(counts), "an empty read must fail the gate"


# --- calendar_market (todo 630): a calendar-listed market split on a Massive-served series ---

_MASSIVE = ("massive", "sip_flat_adj")


def _massive_case(on=_ON, factor=2.0, incumbents=({_IBKR: True},), canonical_pair=_MASSIVE):
    """XHE-shaped: canonical (Massive, unadjusted) steps by 1/factor on `on`; each incumbent raw
    series is adjusted (flat against the calendar) or, when its flag is False, unadjusted."""
    canonical, calendar, _ = _series(on, factor, pair=canonical_pair)
    raw = {}
    for pair, adjusted in incumbents[0].items() if incumbents else []:
        raw[pair] = _series(on, factor, adjusted=adjusted)[2]
    return canonical, calendar, raw


def test_a_massive_split_the_incumbents_carry_adjusted_is_market_unadjusted():
    canonical, calendar, raw = _massive_case()
    [event] = _judge("XHE", canonical, calendar, raw)
    assert (event.verdict, event.ratio, event.effective_date) == (
        "market_unadjusted",
        2.0,
        date(2005, 2, 25),
    )
    assert json.loads(event.route_steps) == {"ibkr/smart_trades": 0.0}
    assert event.unadjusted_routes == ""


@pytest.mark.parametrize(
    "case",
    [
        {"incumbents": ({},)},  # no incumbent measured (MDU 2003): a report, not a row
        {"incumbents": ({_IBKR: False},)},  # an incumbent unadjusted too: conflict stays a report
        {"canonical_pair": ("ibkr", "named")},  # canonical is not Massive
        {"factor": 1.046},  # no recognised split ratio
    ],
)
def test_every_guard_keeps_the_event_a_report(case):
    canonical, calendar, raw = _massive_case(**case)
    [event] = _judge("XHE", canonical, calendar, raw)
    assert event.verdict != "market_unadjusted"


def test_a_break_not_on_the_calendar_day_stays_a_report():
    # the calendar lists the Saturday; canonical's first new-scale session is the Monday
    saturday = date(2005, 2, 26)
    canonical, calendar, raw = _massive_case(on=date(2005, 2, 28))
    calendar = [(d, c, f if d == date(2005, 2, 28) else 0.0) for d, c, f in calendar]
    calendar.append((saturday, 50.0, 2.0))
    calendar.sort()
    events = _judge("XHE", canonical, calendar, raw)
    assert all(e.verdict != "market_unadjusted" for e in events if e.calendar_date == saturday)


_MARKET_LINE = {
    "symbol": "XHE",
    "canonical_vendor": "massive",
    "canonical_kind": "sip_flat_adj",
    "route_steps": '{"ibkr/smart_trades": 0.0}',
    "unadjusted_routes": "",
    "verdict": "market_unadjusted",
}


def test_market_rows_re_judge_each_line_and_carry_the_evidence(tmp_path):
    path = _write(tmp_path / "audit.csv", [_MARKET_LINE, {}])
    rows = audit.market_rows(path, _PARAMS, excluded=set())
    assert [(r["symbol"], r["action_type"], r["factor"]) for r in rows] == [("XHE", "split", 2.0)]
    detail = rows[0]["detail"]
    assert detail["canonical_route"] == {"vendor": "massive", "kind": "sip_flat_adj"}
    assert detail["route_steps"] == {"ibkr/smart_trades": 0.0} and detail["todo"] == 630
    assert "unadjusted_routes" not in detail and len(detail["audit_sha256"]) == 64
    assert audit.market_rows(path, _PARAMS, excluded=set()) == rows  # idempotent


@pytest.mark.parametrize(
    "edit",
    [
        {"route_steps": '{"ibkr/smart_trades": -0.693147}'},  # an incumbent unadjusted
        {"route_steps": '{"ibkr/smart_trades": null}'},  # an unmeasured incumbent
        {"route_steps": "{}"},  # nothing measured
        {"canonical_vendor": "ibkr"},
        {"effective_date": "2005-02-10"},  # not the session before the calendar day
        {"canonical_step": "-0.3"},  # the calendar no longer confirms the step
    ],
)
def test_a_market_line_the_current_apr_would_not_accept_raises(tmp_path, edit):
    path = _write(tmp_path / "audit.csv", [{**_MARKET_LINE, **edit}])
    with pytest.raises(ValueError):
        audit.market_rows(path, _PARAMS, excluded=set())


def test_a_market_line_the_spin_off_list_names_raises(tmp_path):
    path = _write(tmp_path / "audit.csv", [{**_MARKET_LINE, "symbol": "XHE"}])
    with pytest.raises(ValueError):
        audit.market_rows(path, _PARAMS, excluded={("XHE", date(2005, 2, 28))})


def test_apply_market_inserts_calendar_market_rows_and_rolls_back_unless_commit(
    tmp_path, monkeypatch
):
    path = _write(tmp_path / "audit.csv", [_MARKET_LINE])
    monkeypatch.setattr(audit, "_apr", lambda conn: _PARAMS)
    monkeypatch.setattr(audit, "_with_canonical_closes", lambda conn, rows: list(rows))
    monkeypatch.setattr(audit, "operator_list", lambda p: {})
    conn = _Conn()
    monkeypatch.setattr(audit.psycopg, "connect", lambda *a, **k: conn)
    monkeypatch.setattr(audit, "Settings", lambda: type("S", (), {"database_url": "x"})())
    assert audit.main(["--apply-market", str(path)]) == 0
    assert (conn.committed, conn.rolled_back) == (0, 1)
    assert any("'calendar_market'" in s for s in conn.statements)


def test_calendar_market_means_what_massive_reference_means():
    from services.bar_derivation import split_record
    from src.intelligence.bars.corporate_actions import SPLIT_SOURCES, is_market_split

    assert "calendar_market" in SPLIT_SOURCES
    assert is_market_split("calendar_market", operator_rows_file=False)
    record = split_record(
        {
            "effective_date": date(2015, 9, 10),
            "recorded_at": datetime(2026, 11, 18, tzinfo=UTC),
            "factor": 2.0,
            "evidence_request_ids": [],
            "inferred_by": "calendar_market",
            "unadjusted_routes": None,
            "calendar_adjusted_step": 0.004568,
            "operator_rows_file": False,
        }
    )
    # rescales Massive (a market split), rescales and stales no incumbent
    assert record.market_fact and not record.stales and not record.rescale_routes


@pytest.mark.parametrize(
    ("closes", "factor"),
    [
        ((93.91, 47.17), 2.0),  # XHE 2015-09-10 and 2015-09-11
        ((33.98, 22.61), 1.5),  # AAON 2013-07-02 and 2013-07-03
        ((57.37, 38.23), 1.5),  # ROL 2018-12-10 and 2018-12-11
    ],
)
def test_a_reselect_after_recording_makes_the_massive_series_continuous(closes, factor):
    from src.intelligence.bars.selection import Candidate
    from src.intelligence.bars.split_rescale import canonicalize_winners, split_row, splits_known_at

    old = Candidate(
        datetime(2015, 9, 10, 19, 55, tzinfo=UTC),
        "XHE",
        "5m",
        "massive",
        "sip_flat_agg",
        closes[0],
        closes[0],
        closes[0],
        closes[0],
        1000,
    )
    new = Candidate(
        datetime(2015, 9, 11, 13, 30, tzinfo=UTC),
        "XHE",
        "5m",
        "massive",
        "sip_flat_agg",
        closes[1],
        closes[1],
        closes[1],
        closes[1],
        1000,
    )
    row = split_row(
        date(2015, 9, 10),
        factor,
        datetime(2026, 11, 18, tzinfo=UTC),
        "calendar_market",
        False,
        None,
    )
    splits = splits_known_at([row], datetime(2026, 11, 18, 12, tzinfo=UTC))
    first, second = canonicalize_winners([old, new], {"XHE": splits})
    assert abs(math.log(second.close / first.close)) < 0.01  # continuous within a real day's move
    assert first.close == pytest.approx(closes[0] / factor)


def _quarantine_fakes(monkeypatch):
    import services.bar_derivation_batch as batch
    import services.bar_scrub as scrub

    written = []

    async def fake_write_flags(conn, **kw):
        written.append((kw["symbol"], kw["rules_evaluated"], [f.quarantine for f in kw["flags"]]))
        return len(kw["flags"])

    async def fake_open(conn, **kw):
        return "b"

    async def fake_close(conn, *a, **kw):
        return None

    monkeypatch.setattr(scrub, "write_flags", fake_write_flags)
    monkeypatch.setattr(batch, "open_batch", fake_open)
    monkeypatch.setattr(batch, "close_batch", fake_close)
    return written


@pytest.mark.parametrize("verdict", ["route_conflict", "market_unadjusted", "conflict"])
def test_a_candidate_with_a_recorded_market_split_nearby_is_not_quarantined(
    tmp_path, monkeypatch, verdict
):
    written = _quarantine_fakes(monkeypatch)
    path = _write(tmp_path / "audit.csv", [{"symbol": "XHE", "verdict": verdict}])
    monkeypatch.setattr(audit, "OPERATOR_BAD_BARS", _write_bad_bars(tmp_path))
    both = '["unconfirmed_split", "operator_bad_bar"]'
    market = [{"inferred_by": "calendar_market", "rows_file": False}]
    conn = _AsyncConn(both, recorded=market)
    asyncio.run(audit.quarantine_unconfirmed(conn, path, commit=False))
    assert not any(
        s == "XHE" and r == frozenset({"unconfirmed_split"}) and q for s, r, q in written
    )
    written.clear()
    route_fix = [
        {"inferred_by": "calendar_audit", "rows_file": True}
    ]  # an operator route correction
    asyncio.run(
        audit.quarantine_unconfirmed(_AsyncConn(both, recorded=route_fix), path, commit=False)
    )
    assert any(s == "XHE" and r == frozenset({"unconfirmed_split"}) and q for s, r, q in written)


class _CloseCur:
    def __init__(self, closes):
        self.closes = closes

    def execute(self, sql, params):
        self.params = params

    def fetchall(self):
        return self.closes


class _CloseConn:
    def __init__(self, closes):
        self.cur = _CloseCur(closes)

    def cursor(self):
        return self.cur


def _market_row(effective=date(2015, 9, 10), step=-0.688579):
    return {
        "symbol": "XHE",
        "effective_date": effective,
        "detail": {"calendar_date": "2015-09-11", "canonical_step": step},
    }


def test_the_canonical_closes_must_be_the_effective_date_and_the_calendar_day():
    good = _CloseConn([(date(2015, 9, 10), 93.91), (date(2015, 9, 11), 47.17)])
    [row] = audit._with_canonical_closes(good, [_market_row()])
    assert row["detail"]["canonical_closes"] == {"2015-09-10": 93.91, "2015-09-11": 47.17}
    # MGEE shape: effective Friday, calendar Monday
    mgee = _market_row(date(2014, 2, 7), round(math.log(36.81 / 55.25), 6))
    mgee["detail"]["calendar_date"] = "2014-02-10"
    [row] = audit._with_canonical_closes(
        _CloseConn([(date(2014, 2, 7), 55.25), (date(2014, 2, 10), 36.81)]), [mgee]
    )
    assert len(row["detail"]["canonical_closes"]) == 2


@pytest.mark.parametrize(
    "closes",
    [
        [(date(2015, 9, 10), 93.91)],  # the calendar day is missing
        [(date(2015, 9, 9), 92.84), (date(2015, 9, 11), 47.17)],  # dated one session early
        [(date(2015, 9, 10), 93.91), (date(2015, 9, 11), 93.9)],  # canonical already continuous
    ],
)
def test_a_row_one_session_off_or_already_continuous_is_refused(closes):
    with pytest.raises(ValueError):
        audit._with_canonical_closes(_CloseConn(closes), [_market_row()])


def test_the_reference_sources_are_one_named_set_every_guard_reads():
    from services import bar_derivation
    from src.intelligence.bars.corporate_actions import MARKET_REFERENCE_SOURCES

    assert MARKET_REFERENCE_SOURCES == {"massive_reference", "calendar_market"}
    assert "'calendar_market'" in bar_derivation._SELECT_REVISION_WAIVER_SQL
    assert "'massive_reference'" in bar_derivation._SELECT_REVISION_WAIVER_SQL


# ---------------- Massive-route operator rows (todo 633) ----------------

_ROW633_LINE = {
    "symbol": "ENOV",
    "effective_date": "2022-04-04",
    "factor": "0.333333333333",
    "unadjusted_routes": "massive/sip_flat",
    "calendar_adjusted_step": "0.047553",
    "reason": "1-for-3 reverse split after the ESAB distribution",
    "evidence": "filing; Alpaca/Massive ratio 3.0008",
}


def _row633_file(tmp_path, line=None, combined="0.581"):
    path = tmp_path / "rows.csv"
    cols = (*audit.OPERATOR_ROWS_COLUMNS, *audit.OPERATOR_ROWS_OPTIONAL)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        writer.writerow({**_ROW633_LINE, "calendar_factor": combined, **(line or {})})
    return path


def test_a_massive_route_line_is_a_calendar_market_row_with_the_combined_factor_as_evidence(
    tmp_path,
):
    [row] = audit.operator_rows(_row633_file(tmp_path))
    assert row["inferred_by"] == "calendar_market" and row["action_type"] == "reverse_split"
    assert row["factor"] == pytest.approx(1 / 3)  # the split alone, never the combined 0.581
    detail = row["detail"]
    assert "unadjusted_routes" not in detail and detail["todo"] == 633
    assert detail["calendar_factor"] == 0.581
    assert detail["residual_factor"] == pytest.approx(0.581 * 3)
    assert detail["canonical_route"] == {"vendor": "massive", "kind": "sip_flat"}


def test_an_incumbent_line_stays_a_calendar_audit_row_and_a_file_without_the_column_parses(
    tmp_path,
):
    [row] = audit.operator_rows(_write_rows(tmp_path / "rows.csv", [{}]))
    assert "inferred_by" not in row and row["detail"]["unadjusted_routes"]
    [row] = audit.operator_rows(_row633_file(tmp_path, combined=""))
    assert "calendar_factor" not in row["detail"]


def test_the_massive_route_never_shares_a_line_with_an_incumbent_route(tmp_path):
    line = {"unadjusted_routes": "massive/sip_flat;alpaca/sip_rth"}
    with pytest.raises(ValueError, match="only route"):
        audit.operator_rows(_row633_file(tmp_path, line))


def _row633_conn(closes, existing=()):
    class Cursor(_Cursor):
        def execute(self, sql, params=None):
            super().execute(sql, params)
            if "LIMIT 2" in sql:
                self._rows = list(closes)
            if "BETWEEN" in sql and "corporate_action" in sql:
                self._rows = list(existing)

    class Conn(_Conn):
        def cursor(self):
            return Cursor(self)

    return Conn()


def _apply_row633(monkeypatch, conn, path, *extra):
    monkeypatch.setattr(audit.psycopg, "connect", lambda *a, **k: conn)
    monkeypatch.setattr(audit, "Settings", lambda: type("S", (), {"database_url": "x"})())
    return audit.main(["--apply-rows", str(path), *extra])


# ENOV: the day's real move 0.047553 plus the 1-for-3 step ln 3 = 1.098612
_ROW633_CLOSES = [(date(2022, 4, 4), 20.0), (date(2022, 4, 5), 20.0 * math.exp(1.146165))]


def test_apply_rows_writes_a_massive_route_split_as_calendar_market(tmp_path, monkeypatch):
    conn = _row633_conn(_ROW633_CLOSES)
    assert _apply_row633(monkeypatch, conn, _row633_file(tmp_path), "--commit") == 0
    assert conn.committed == 1
    assert any("'calendar_market'" in s for s in conn.statements)
    assert not any("'calendar_audit'" in s for s in conn.statements)


def test_a_combined_factor_applied_as_one_step_is_refused(tmp_path, monkeypatch):
    path = _row633_file(tmp_path, {"factor": "0.581"})
    with pytest.raises(ValueError, match="recognised split ratio"):
        _apply_row633(monkeypatch, _row633_conn(_ROW633_CLOSES), path)


@pytest.mark.parametrize(
    "closes",
    [
        [(date(2022, 4, 4), 20.0), (date(2022, 4, 5), 20.0 * math.exp(0.047553))],  # rescaled
        [(date(2022, 4, 1), 20.0), (date(2022, 4, 4), 60.0)],  # not the effective date
        [(date(2022, 4, 4), 20.0)],  # no next session
    ],
)
def test_a_massive_row_the_stored_canonical_does_not_confirm_is_refused(
    tmp_path, monkeypatch, closes
):
    with pytest.raises(ValueError):
        _apply_row633(monkeypatch, _row633_conn(closes), _row633_file(tmp_path))


def test_reapplying_a_massive_row_is_skipped_before_it_is_re_judged(tmp_path, monkeypatch):
    decided = [("reverse_split", date(2022, 4, 4), 1 / 3, "calendar_market", True, "id")]
    conn = _row633_conn([], existing=decided)  # canonical already rescaled: would raise
    assert _apply_row633(monkeypatch, conn, _row633_file(tmp_path), "--commit") == 0
    assert not any("INSERT INTO corporate_action" in s for s in conn.statements)


def test_an_incumbent_route_correction_nearby_never_blocks_a_massive_row(tmp_path, monkeypatch):
    nearby = [("reverse_split", date(2022, 4, 4), 1 / 3, "calendar_audit", True, "id")]
    conn = _row633_conn(_ROW633_CLOSES, existing=nearby)
    assert _apply_row633(monkeypatch, conn, _row633_file(tmp_path)) == 0
    assert any("INSERT INTO corporate_action" in s for s in conn.statements)


def test_the_sweep_gate_scope_is_active_names_and_universe_members():
    sql = audit._GATE_SCOPE_SQL
    assert "is_active" in sql and "universe_membership" in sql
