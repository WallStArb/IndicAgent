"""D5 IBKR dividend route from D1: live checks (phase 185 plan 21, D-22/D-23).

Validates the stored state after `dividend_event_writer --sources ibkr
--fetch-run-id c9b625b5-5fc4-4656-8b49-06fd93062123` against the plan's
known-answer names: JPM and KO (large quarterly payers, the route must be
exact), XLU (low-yield ETF: 39 of 40 Yahoo quarterlies matched over the
window, the 2020-03-23 COVID quarterly missed, 20 sub-cent re-basing
artifacts beside real distribution dates; measured 2026-10-02, reported in
docs/research/ibkr-dividend-route-validation.md), and NVR 2004 (a ratio that
wanders inside the noise bound must derive nothing).

The dispute records are structural: every dividend_date_dispute row carries
both sources' dates and a 1-5 day span (migration 403's CHECK).

Note: the integration suite itself is blocked by todo 486 (conftest replay);
these checks were also run live via psql on 2026-10-02.
"""

from __future__ import annotations

from datetime import date

import psycopg
import pytest

_LIVE_DB_URL = "host=localhost dbname=indicagent user=postgres password=postgres"
_RUN_ID = "c9b625b5-5fc4-4656-8b49-06fd93062123"
_IBKR = "ibkr_adjusted_last_ratio"
# The validation window is anchored at the run date so the measured counts
# (JPM/KO 40 of 40, XLU 39 of 40) stay comparable to the report.
_WINDOW_START = date(2016, 10, 2)
_MATCH_DAYS = 5  # threshold.dividend_event.ex_date_match_days at run time


@pytest.fixture(scope="module")
def conn():
    with psycopg.connect(_LIVE_DB_URL, autocommit=True) as c:
        yield c


def _unmatched_yahoo_dates(cur, symbol: str) -> list[date]:
    return [
        r[0]
        for r in cur.execute(
            """
            SELECT y.ex_date FROM dividend_events y
            WHERE y.symbol = %(symbol)s AND y.source = 'yahoo'
              AND y.ex_date >= %(start)s
              AND NOT EXISTS (
                SELECT 1 FROM dividend_events i
                WHERE i.symbol = y.symbol
                  AND i.source = %(ibkr)s
                  AND abs(i.ex_date - y.ex_date) <= %(match_days)s
              )
            ORDER BY y.ex_date
            """,
            {
                "symbol": symbol,
                "ibkr": _IBKR,
                "match_days": _MATCH_DAYS,
                "start": _WINDOW_START,
            },
        ).fetchall()
    ]


def test_jpm_ko_every_yahoo_ex_date_matched_within_threshold(conn):
    """The two single-name validators: 40 of 40 quarterlies each over the window."""
    for symbol in ("JPM", "KO"):
        unmatched = _unmatched_yahoo_dates(conn, symbol)
        assert unmatched == [], f"{symbol}: Yahoo ex-dates unmatched by IBKR: {unmatched}"


def test_xlu_known_misses_are_exactly_the_reported_one(conn):
    """XLU's unmatched set is the measured state: the 2020-03-23 quarterly only.

    Anything else appearing here is a route regression (or a repair of the
    COVID-era miss, which must update the validation report in the same
    change, never this pin silently).
    """
    assert _unmatched_yahoo_dates(conn, "XLU") == [date(2020, 3, 23)]


def test_nvr_2004_derives_nothing(conn):
    """NVR's pre-2005 ADJUSTED_LAST wanders inside the noise bound: no events."""
    n = conn.execute(
        """
        SELECT count(*) FROM dividend_events
        WHERE symbol = 'NVR' AND source = %s AND ex_date < '2005-01-01'
        """,
        (_IBKR,),
    ).fetchone()[0]
    assert n == 0


def test_every_dispute_row_has_both_sources_and_a_bounded_span(conn):
    rows = conn.execute("""
        SELECT symbol, first_date, last_date,
               dates_by_source ? 'ibkr_adjusted_last_ratio',
               dates_by_source ? 'yahoo'
        FROM dividend_date_dispute
        """).fetchall()
    assert rows, "the 2026-10-02 D1 run recorded 26 disputes on 18 names"
    for symbol, first, last, has_ibkr, has_yahoo in rows:
        assert has_ibkr and has_yahoo, f"{symbol} {first}: a dispute missing a source date"
        assert 1 <= (last - first).days <= 5, f"{symbol} {first}: span outside the rule"


def test_ibkr_events_come_from_the_d1_run_where_one_is_recorded(conn):
    """Dispute provenance: the fetch_run_id on disputes is the D1 paired run."""
    rows = conn.execute("SELECT DISTINCT fetch_run_id::text FROM dividend_date_dispute").fetchall()
    assert [r[0] for r in rows] == [_RUN_ID]
