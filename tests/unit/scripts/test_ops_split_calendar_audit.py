"""ops_split_calendar_audit.py (todo 587): calendar splits judged against canonical, pure parts.

No database, no Yahoo: canonical and calendar rows are literals.
"""

from __future__ import annotations

import csv
import math
from datetime import date, timedelta

from scripts.ops.bars import ops_split_calendar_audit as audit
from src.intelligence.bars.corporate_actions import SplitRatioRule

_RULE = SplitRatioRule(max_numerator=50, max_denominator=4, rel_tol=0.002)
_TOL = 0.3
_DAYS = [
    date(2005, 2, 22) + timedelta(days=i)
    for i in range(10)
    if (date(2005, 2, 22) + timedelta(days=i)).weekday() < 5
]


def _series(split_on: date, factor: float, *, adjusted: bool):
    """Canonical (date, close, vendor, kind) at 100, stepping by 1/factor on split_on unless
    adjusted; the calendar's split-adjusted closes never step."""
    canonical = [
        (d, 100.0 / factor if (d >= split_on or adjusted) else 100.0, "ibkr", "named")
        for d in _DAYS
    ]
    calendar = [(d, 50.0, factor if d == split_on else 0.0) for d in _DAYS]
    return canonical, calendar


def test_an_unadjusted_two_for_one_is_confirmed_with_its_evidence():
    on = date(2005, 2, 28)  # AAPL's 2:1
    canonical, calendar = _series(on, 2.0, adjusted=False)
    [event] = audit.judge_events("AAPL", canonical, calendar, _RULE, _TOL)
    # effective_date is the last day on the old scale (migration 400): the Friday before.
    assert (event.verdict, event.ratio, event.effective_date) == (
        "confirmed",
        2.0,
        date(2005, 2, 25),
    )
    assert event.canonical_step == round(-math.log(2.0), 6)
    assert (event.unadjusted_vendor, event.unadjusted_kind) == ("ibkr", "named")


def test_an_adjusted_canonical_and_a_spin_off_record_nothing():
    on = date(2005, 2, 28)
    canonical, calendar = _series(on, 2.0, adjusted=True)
    assert audit.judge_events("AAPL", canonical, calendar, _RULE, _TOL)[0].verdict == "adjusted"
    canonical, calendar = _series(on, 1.046, adjusted=False)  # IBM 2021 Kyndryl as Yahoo writes it
    assert audit.judge_events("IBM", canonical, calendar, _RULE, _TOL)[0].verdict == (
        "not_a_split_ratio"
    )


def test_a_split_with_no_canonical_session_nearby_is_unmeasured():
    canonical, calendar = _series(date(2005, 2, 28), 2.0, adjusted=False)
    calendar.append((date(2010, 6, 1), 50.0, 3.0))
    events = audit.judge_events("AAPL", canonical, calendar, _RULE, _TOL)
    assert [e.verdict for e in events] == ["confirmed", "unmeasured"]


def test_only_confirmed_lines_become_rows_in_the_tables_orientation(tmp_path):
    path = tmp_path / "audit.csv"
    fields = [*audit.CalendarEvent.__dataclass_fields__, "error"]
    lines = [
        [
            "AAPL",
            "2005-02-28",
            "2.0",
            "2005-02-28",
            "-0.69",
            "0.01",
            "ibkr",
            "named",
            "confirmed",
            "2.0",
        ],
        [
            "UNIT",
            "2025-08-04",
            "0.1",
            "2025-08-04",
            "2.30",
            "0.0",
            "ibkr",
            "named",
            "confirmed",
            "0.1",
        ],
        [
            "IBM",
            "2021-11-04",
            "1.046",
            "2021-11-04",
            "-0.04",
            "0.0",
            "alpaca",
            "sip_rth",
            "not_a_split_ratio",
            "",
        ],
        [
            "XPO",
            "2021-08-02",
            "1.718",
            "2021-08-02",
            "-0.50",
            "0.0",
            "alpaca",
            "sip_rth",
            "conflict",
            "1.75",
        ],
    ]
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(fields)
        for line in lines:
            writer.writerow([*line, ""])
    rows = audit.confirmed_rows(path, _RULE, _TOL)
    assert [(r["symbol"], r["action_type"], r["factor"]) for r in rows] == [
        ("AAPL", "split", 2.0),
        ("UNIT", "reverse_split", 0.1),
    ]
    assert rows[0]["detail"]["unadjusted_span"] == {"vendor": "ibkr", "kind": "named"}
    assert rows[0]["detail"]["audit_file"] == "audit.csv"
    assert len(rows[0]["detail"]["audit_sha256"]) == 64 and rows[0]["detail"]["rel_tol"] == _TOL


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
    path = tmp_path / "audit.csv"
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow([*audit.CalendarEvent.__dataclass_fields__, "error"])
        writer.writerow(
            [
                "AAPL",
                "2005-02-28",
                "2.0",
                "2005-02-25",
                "-0.69",
                "0.01",
                "ibkr",
                "named",
                "confirmed",
                "2.0",
                "",
            ]
        )
    return path


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
