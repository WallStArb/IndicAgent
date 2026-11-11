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
    def __init__(self, rules):
        self.rules, self.events = rules, []

    def transaction(self):
        return _AsyncTx(self)

    async def fetchval(self, sql, *args):
        if "quarantine_rules" in sql:
            return self.rules
        return datetime(2005, 2, 28, tzinfo=UTC)

    async def fetch(self, sql, *args):
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


def test_the_shipped_bad_bar_list_is_exactly_the_reviewed_bars():
    # The list changes only through review. Structure, not a frozen literal: every bar's
    # evidence cites the todo that reviewed it, no (symbol, date) appears twice, the pinned
    # core from 587 and 592 is always present, and the count matches the reviewed-batch
    # constant (bump it in the same review commit that adds bars; the 592 sweep's 123
    # single-bar-reversal quarantines took it to 131 on 2026-11-10).
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
    assert len(bad) == 131, "bump the reviewed count in the same review commit"
    rows = audit.OPERATOR_BAD_BARS.read_text().splitlines()[1:]
    assert len(rows) == 131
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


def test_apply_rows_skips_a_row_the_name_has_already_decided(tmp_path, monkeypatch):
    """The existing-row guard is --apply-rows' only double-decide protection (review 2026-11-09):
    a decided event is skipped, not inserted a second time."""

    class _DecidedCursor(_Cursor):
        def execute(self, sql, params=None):
            super().execute(sql, params)
            if "BETWEEN" in sql:  # _EXISTING_SQL: the name has a row near the date
                self._rows = [("split",)]

    class _DecidedConn(_Conn):
        def cursor(self):
            return _DecidedCursor(self)

    conn = _DecidedConn()
    monkeypatch.setattr(audit.psycopg, "connect", lambda *a, **k: conn)
    monkeypatch.setattr(audit, "Settings", lambda: type("S", (), {"database_url": "x"})())
    assert (
        audit.main(["--apply-rows", str(_write_rows(tmp_path / "rows.csv", [{}])), "--commit"]) == 0
    )
    assert (conn.committed, conn.rolled_back) == (1, 0)
    assert not any("INSERT INTO corporate_action" in s for s in conn.statements)


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
    assert event.yahoo_step == pytest.approx(step, abs=1e-6)


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
    assert event.yahoo_step is None


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
