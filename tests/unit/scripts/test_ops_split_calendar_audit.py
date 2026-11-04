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
_WITNESS = audit.Witness(windows=(2, 3), listing_sessions=2)
_PARAMS = audit.AuditParams(_RULE, _TOL, _WITNESS)
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


def _series(on, factor, *, adjusted=False, volume_steps=True, days=_DAYS, pair=("ibkr", "named")):
    """Canonical (date, close, vendor, kind) at 100 stepping by 1/factor on `on` unless adjusted,
    the raw series canonical is served from (volume 1000 stepping by factor unless the share
    count stays flat), and the calendar's split-adjusted closes, which never step."""
    canonical = [(d, 100.0 * _step(d, on, factor, adjusted), *pair) for d in days]
    raw = [
        (d, close, 1000 * (factor if (volume_steps and d >= on) else 1))
        for d, close, _, _ in canonical
    ]
    calendar = [(d, 100.0 / factor, factor if d == on else 0.0) for d in days]
    return canonical, calendar, raw


def _judge(symbol, canonical, calendar, raw, first_bars=None):
    return audit.judge_events(
        symbol, canonical, calendar, raw, first_bars or {}, _RULE, _TOL, _WITNESS
    )


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
    assert event.volume_stat == 1.0
    assert json.loads(event.volume_windows) == [round(math.log(2.0), 6)] * 2


def test_an_adjusted_canonical_and_a_spin_off_record_nothing():
    canonical, calendar, raw = _series(_ON, 2.0, adjusted=True)
    assert _judge("AAPL", canonical, calendar, {_IBKR: raw})[0].verdict == "adjusted"
    canonical, calendar, raw = _series(_ON, 1.046)  # IBM 2021 Kyndryl as Yahoo writes it
    assert _judge("IBM", canonical, calendar, {_IBKR: raw})[0].verdict == "not_a_split_ratio"


def test_a_flat_share_count_vetoes_only_with_a_spin_off_witness():
    """SNX-shaped: the price halves on the date, the share count does not move, and the spun-off
    company lists that week. Volume alone never vetoes (lead ruling 2026-11-04)."""
    canonical, calendar, raw = _series(_ON, 2.0, volume_steps=False)
    [event] = _judge("SNX", canonical, calendar, {_IBKR: raw})
    assert (event.verdict, event.volume_stat, event.co_listed) == ("confirmed", 0.0, "")
    spun = {"SNX": date(2000, 1, 3), "CNXC": date(2005, 3, 1), "OLD": date(2000, 1, 3)}
    [event] = _judge("SNX", canonical, calendar, {_IBKR: raw}, spun)
    assert (event.verdict, event.co_listed) == ("volume_veto", "CNXC")
    far = {"CNXC": date(2005, 3, 10)}  # five sessions after the date: outside two
    assert _judge("SNX", canonical, calendar, {_IBKR: raw}, far)[0].verdict == "confirmed"


def test_a_split_shaped_share_count_confirms_despite_a_co_listing():
    canonical, calendar, raw = _series(_ON, 2.0)
    [event] = _judge("AAPL", canonical, calendar, {_IBKR: raw}, {"NEW": _ON})
    assert (event.verdict, event.co_listed) == ("confirmed", "NEW")


def test_an_ambiguous_share_count_confirms_with_its_statistic():
    canonical, calendar, raw = _series(_ON, 2.0)
    ambiguous = [(d, c, int(1000 * 2**0.4) if d >= _ON else 1000) for d, c, _ in raw]
    [event] = _judge("AAPL", canonical, calendar, {_IBKR: ambiguous})
    assert event.verdict == "confirmed" and 0.25 < event.volume_stat < 0.5


def test_missing_share_count_evidence_never_vetoes():
    canonical, calendar, raw = _series(_ON, 2.0)
    short = [row for row in raw if row[0] >= date(2005, 2, 25)]  # one session before the date
    [event] = _judge("AAPL", canonical, calendar, {_IBKR: short})
    assert (event.verdict, event.volume_stat, event.volume_windows) == ("confirmed", None, "[]")


def test_every_series_before_the_date_is_measured_on_its_own():
    """The SNX seam (review 2026-11-04): an IBKR span before an Alpaca one is measured against the
    calendar, never assumed from the series canonical serves at the date."""
    canonical, calendar, alpaca = _series(_ON, 2.0, pair=("alpaca", "sip_rth"))
    ibkr_unadjusted = [row for row in alpaca if row[0] < date(2005, 2, 21)]
    [event] = _judge("SNX", canonical, calendar, {_ALPACA: alpaca, _IBKR: ibkr_unadjusted})
    # IBKR has no session after the date: its scale cannot be measured, so no row.
    assert event.verdict == "route_conflict"
    ibkr = [(d, c, v) for d, c, v in alpaca]
    [event] = _judge("SNX", canonical, calendar, {_ALPACA: alpaca, _IBKR: ibkr})
    assert (event.verdict, event.unadjusted_routes) == (
        "confirmed",
        "alpaca/sip_rth;ibkr/smart_trades",
    )
    ibkr_adjusted = [(d, c / 2 if d < _ON else c, v) for d, c, v in alpaca]
    [event] = _judge("SNX", canonical, calendar, {_ALPACA: alpaca, _IBKR: ibkr_adjusted})
    assert (event.verdict, event.unadjusted_routes) == ("confirmed", "alpaca/sip_rth")
    ibkr_odd = [(d, c * 1.3 if d < _ON else c, v) for d, c, v in alpaca]
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
    raw = [(d, c, v) for d, c, v in raw]
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
    "volume_stat": "0.94",
    "volume_windows": "[0.65]",
    "co_listed": "",
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
                "volume_stat": "",
                "volume_windows": "[]",
                "ratio": "0.1",
            },
            {"symbol": "IBM", "calendar_factor": "1.046", "verdict": "not_a_split_ratio"},
            {"symbol": "XPO", "verdict": "conflict"},
            {"symbol": "SNX", "verdict": "volume_veto", "co_listed": "CNXC"},
        ],
    )
    rows = audit.confirmed_rows(path, _PARAMS)
    assert [(r["symbol"], r["action_type"], r["factor"]) for r in rows] == [
        ("AAPL", "split", 2.0),
        ("UNIT", "reverse_split", 0.1),
    ]
    detail = rows[0]["detail"]
    assert detail["unadjusted_routes"] == [{"vendor": "ibkr", "kind": "smart_trades"}]
    assert "unadjusted_span" not in detail
    assert detail["audit_file"] == "audit.csv" and len(detail["audit_sha256"]) == 64
    assert detail["rel_tol"] == _TOL
    assert detail["witness"] == {"windows": (2, 3), "listing_sessions": 2}
    assert detail["co_listed"] == []
    assert (detail["volume"], rows[1]["detail"]["volume"]) == (0.94, "unmeasured")


@pytest.mark.parametrize(
    "edit",
    [
        {"volume_stat": "0.05", "co_listed": "CNXC"},  # a distribution: two witnesses
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
        audit.confirmed_rows(path, _PARAMS)


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
                ("threshold.split_calendar.volume_windows", "[2, 3]"),
                ("threshold.split_calendar.spin_off_listing_sessions", "2"),
            ]
        self._row = None

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
            {"symbol": "SNX", "verdict": "volume_veto", "co_listed": "CNXC", "volume_stat": "0.2"},
            {"symbol": "JMSB", "verdict": "route_conflict"},
            {"symbol": "AA", "verdict": "conflict", "volume_stat": ""},
            {"symbol": "MSFT", "verdict": "adjusted"},
            {"symbol": "IBM", "verdict": "not_a_split_ratio"},
        ],
    )
    got = audit.unconfirmed_candidates(path)
    assert [(c["symbol"], c["detail"]["verdict"]) for c in got] == [
        ("SNX", "volume_veto"),
        ("JMSB", "route_conflict"),
        ("AA", "conflict"),
    ]
    assert got[0]["detail"]["co_listed"] == ["CNXC"] and got[0]["effective_date"] == date(
        2005, 2, 25
    )


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

    path = _write(tmp_path / "audit.csv", [{"symbol": "SNX", "verdict": "volume_veto"}])
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
    conn = _AsyncConn('["unconfirmed_split"]')
    assert asyncio.run(audit.quarantine_unconfirmed(conn, path, commit=False)) == 1
    # A name flagged today but absent from the file is cleared; the candidate is quarantined.
    assert written == [
        ("GONE", frozenset({"unconfirmed_split"}), []),
        ("SNX", frozenset({"unconfirmed_split"}), [True]),
    ]
    assert conn.events == ["begin", "rollback"]
    conn = _AsyncConn('["unconfirmed_split"]')
    asyncio.run(audit.quarantine_unconfirmed(conn, path, commit=True))
    assert conn.events == ["begin", "commit"]
    with pytest.raises(ValueError, match="quarantine_rules"):
        asyncio.run(audit.quarantine_unconfirmed(_AsyncConn('["price_sanity"]'), path, commit=True))
