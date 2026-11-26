"""CI guard: every reader of dividend_events names the sources it reads (todo 651).

dividend_events holds three sources (yahoo, ibkr_adjusted_last_ratio and, from migration 608,
massive). A reader written for some of them that reads the table unfiltered changes its output
the day another source loads: before todo 651 two such readers would have returned NULL amounts
(backfill_feature_factory) and widened the explained dates (bar_reconciliation_audit). The
grep guard fails on any new read whose statement does not constrain `source`; the fixture tests
run the two fixed readers' SQL on a table holding all three sources and show their output is
today's.

CI-clean: no DB, no network (the fixture runs the readers' own SQL text in sqlite).
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date
from pathlib import Path

from services import backfill_feature_factory as factory
from services import bar_reconciliation_audit as audit
from tests.unit._scan_support import assert_scanned

_REPO_ROOT = Path(__file__).parent.parent.parent
_SEARCH_DIRS = ("services", "src", "scripts")
_READ = re.compile(r"\b(?:FROM|JOIN)\s+dividend_events\b(?!_)")
# A source predicate in the statement right after the table name (the same or the next string
# literal of the SQL constant).
_SOURCE_PREDICATE = re.compile(r"\bsource\s*(?:=|IN\b)", re.IGNORECASE)
_WINDOW = 160


def _reads() -> list[tuple[str, int, str]]:
    out = []
    files = assert_scanned(  # 404 on 2026-11-26
        (p for d in _SEARCH_DIRS for p in (_REPO_ROOT / d).rglob("*.py")),
        320,
        "services, src and scripts .py",
    )
    for path in sorted(files):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for m in _READ.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            rel = str(path.relative_to(_REPO_ROOT))
            out.append((rel, line, text[m.end() : m.end() + _WINDOW]))
    return out


def test_every_dividend_events_read_filters_by_source():
    reads = _reads()
    assert len(reads) >= 4, "the guard found no readers: its pattern or search dirs broke"
    unfiltered = [
        f"{path}:{line}" for path, line, tail in reads if not _SOURCE_PREDICATE.search(tail)
    ]
    assert not unfiltered, (
        f"dividend_events read without a source filter: {unfiltered}. Name the sources the "
        "reader was written for (yahoo, ibkr_adjusted_last_ratio, massive) in its WHERE clause."
    )


_ROWS = [
    # symbol, ex_date, source, amount
    ("A", "2024-03-01", "yahoo", 0.50),
    ("A", "2024-03-01", "ibkr_adjusted_last_ratio", 0.49),
    ("A", "2024-03-01", "massive", 0.51),
    ("A", "2024-06-03", "ibkr_adjusted_last_ratio", 0.40),  # an IBKR-only date
    ("A", "2024-06-03", "massive", 0.40),
    ("A", "2024-09-03", "massive", 0.60),  # a Massive-only date
    ("B", "2024-03-05", "massive", 0.10),  # a Massive-only symbol
]


def _db(with_massive: bool) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE dividend_events (symbol TEXT, ex_date TEXT, source TEXT, amount REAL)"
    )
    conn.execute("CREATE TABLE corporate_action_current (symbol TEXT, effective_date TEXT)")
    conn.executemany(
        "INSERT INTO dividend_events VALUES (?, ?, ?, ?)",
        [r for r in _ROWS if with_massive or r[2] != "massive"],
    )
    conn.execute("INSERT INTO corporate_action_current VALUES ('B', '2024-04-01')")
    return conn


def _factory_amounts(conn: sqlite3.Connection, symbol: str) -> dict:
    return dict(
        conn.execute(factory._DIVIDEND_AMOUNTS_SQL.replace("%s", "?"), (symbol,)).fetchall()
    )


def test_the_feature_factory_reads_only_yahoo_and_ibkr_amounts():
    today, loaded = _db(with_massive=False), _db(with_massive=True)
    for symbol in ("A", "B"):
        assert _factory_amounts(loaded, symbol) == _factory_amounts(today, symbol)
    assert _factory_amounts(loaded, "A") == {"2024-03-01": 0.50, "2024-06-03": 0.40}


def _explained(conn: sqlite3.Connection, symbols: list[str], since: date) -> set:
    sql = audit._EXPLAINED_DATES_SQL.replace(
        "= ANY($1::text[])", "IN (SELECT value FROM json_each(?1))"
    )
    sql = sql.replace("$2", "?2")
    return set(conn.execute(sql, (json.dumps(symbols), since.isoformat())).fetchall())


def test_the_reconciliation_audit_explains_only_yahoo_and_ibkr_ex_dates():
    today, loaded = _db(with_massive=False), _db(with_massive=True)
    since = date(2024, 1, 1)
    assert _explained(loaded, ["A", "B"], since) == _explained(today, ["A", "B"], since)
    assert _explained(loaded, ["A", "B"], since) == {
        ("A", "2024-03-01"),
        ("A", "2024-06-03"),
        ("B", "2024-04-01"),
    }
