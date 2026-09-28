"""Integration: the historical D2a scrub pass's live state (phase 185 plan 10).

Read-only against the live indicagent DB (skips when unreachable). The known
answers are the committed todo-151 dry-run report and the known-answer CSV:
every CONFIRMED_CORRUPT and MARKET_EVENT key must carry a quarantine flag and
be hidden from the tradeable view, no AMBIGUOUS key may be quarantined, the 15
legacy 1d confirmed_corrupt keys stay quarantined, both timeframes' scrub
batches completed, and the tradeable view's anti-join admits no quarantined
bar anywhere.
"""

from __future__ import annotations

import csv
from pathlib import Path

import psycopg
import pytest

_LIVE_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent"
_DRY_RUN = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "bars"
    / ("corrupt_1d_dry_run_2026_09_26.txt")
)
_STATUS_CSV = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "bars"
    / ("price_sanity_status_rows.csv")
)

pytestmark = pytest.mark.integration


def _dry_run_keys() -> dict[str, list[tuple[str, str, str]]]:
    """Section name -> (symbol, timeframe, timestamp) rows from the txt tables."""
    sections: dict[str, list[tuple[str, str, str]]] = {}
    current = None
    for line in _DRY_RUN.read_text().splitlines():
        if line.startswith("## "):
            current = line[3:].split(" (")[0].strip()
            sections.setdefault(current, [])
        elif line.startswith("|") and current is not None and "---" not in line:
            cells = [c.strip() for c in line.split("|")]
            if len(cells) > 4 and cells[1] not in ("symbol", ""):
                sections[current].append((cells[1], cells[2], cells[3]))
    return sections


def _csv_keys(status: str, timeframe: str) -> list[tuple[str, str, str]]:
    with _STATUS_CSV.open() as fh:
        return [
            (row["symbol"], row["timeframe"], row["timestamp"])
            for row in csv.DictReader(fh)
            if row["price_sanity_status"] == status and row["timeframe"] == timeframe
        ]


@pytest.fixture(scope="module")
def conn():
    try:
        c = psycopg.connect(_LIVE_DB_URL)
    except Exception as error:  # reachability probe; any failure means skip
        pytest.skip(f"live database not reachable: {error}")
    with c:
        c.execute("SET default_transaction_read_only = on")
        yield c


def _quarantined(c, key) -> bool:
    return c.execute(
        "SELECT EXISTS (SELECT 1 FROM bar_quality_flag WHERE symbol = %s"
        ' AND timeframe = %s AND "timestamp" = %s::timestamptz AND quarantine)',
        key,
    ).fetchone()[0]


def _in_tradeable(c, key) -> bool:
    return c.execute(
        "SELECT EXISTS (SELECT 1 FROM market_data_ohlcv_tradeable WHERE symbol = %s"
        ' AND timeframe = %s AND "timestamp" = %s::timestamptz)',
        key,
    ).fetchone()[0]


def test_fixture_sizes_pinned() -> None:
    sections = _dry_run_keys()
    assert len(sections["CONFIRMED_CORRUPT"]) == 45
    assert len(sections["MARKET_EVENT"]) == 27
    assert len(sections["AMBIGUOUS"]) == 1864


def test_all_72_dry_run_keys_quarantined_and_hidden(conn) -> None:
    sections = _dry_run_keys()
    keys = sections["CONFIRMED_CORRUPT"] + sections["MARKET_EVENT"]
    not_flagged = [k for k in keys if not _quarantined(conn, k)]
    still_visible = [k for k in keys if _in_tradeable(conn, k)]
    assert not_flagged == [], f"unflagged: {not_flagged[:5]}"
    assert still_visible == [], f"visible in tradeable: {still_visible[:5]}"


def test_no_ambiguous_key_is_quarantined(conn) -> None:
    quarantined = [k for k in _dry_run_keys()["AMBIGUOUS"] if _quarantined(conn, k)]
    assert quarantined == [], f"AMBIGUOUS keys wrongly quarantined: {quarantined[:5]}"


def test_15_legacy_1d_keys_quarantined(conn) -> None:
    keys = _csv_keys("confirmed_corrupt", "1d")
    assert len(keys) == 15
    assert all(_quarantined(conn, k) for k in keys)


def test_both_timeframes_have_completed_scrub_batches(conn) -> None:
    rows = conn.execute(
        "SELECT detail->>'tf' FROM bar_derivation_batch"
        " WHERE stage = 'scrub' AND status = 'completed'"
    ).fetchall()
    tfs = {r[0] for r in rows}
    assert {"1d", "5m"} <= tfs


def test_integrity_facts_recorded_per_timeframe(conn) -> None:
    rows = conn.execute(
        "SELECT subject FROM integrity_monitor"
        " WHERE monitor_type = 'bar_scrub' AND metric_name = 'historical_pass_complete'"
        " AND passed"
    ).fetchall()
    subjects = {r[0] for r in rows}
    assert {"tf=1d", "tf=5m"} <= subjects


def test_tradeable_view_admits_no_quarantined_bar(conn) -> None:
    n = conn.execute(
        "SELECT count(*) FROM market_data_ohlcv_tradeable t"
        ' JOIN bar_quality_flag q USING (symbol, timeframe, "timestamp")'
        " WHERE q.quarantine"
    ).fetchone()[0]
    assert n == 0
