"""The data gate's fetch SQL against a real database (186-32).

The unit tests replace the fetch layer with fakes; this runs the real queries on indicagent_test:
in-session 5m counting on a half day (42 slots) with an out-of-session 23:55 UTC bar, the 1d
date cast, and the completed-answer read of ohlcv_ask_current (migration 581): only a complete
ask without partial bars counts; a failed or unterminated ask and a legacy request row do not.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import psycopg
import pytest

import services.corpus_rerun_data_gate as gate
from src.core.market_calendar import get_market_calendar
from src.intelligence.bars.gap_plan import COVERAGE_EVIDENCE
from tests.integration.conftest import TEST_DB_URL

pytestmark = pytest.mark.integration

_HALF_DAY = date(2015, 11, 27)  # NYSE closes 13:00 New York (18:00 UTC)
_FULL_DAY = date(2015, 11, 30)
_EVIDENCE = {source: (route, what) for source, route, what in COVERAGE_EVIDENCE}


def _session(day: date) -> gate.Session:
    open_ts, close_ts = get_market_calendar().session_bounds("NYSE", day)
    return gate.Session(day, open_ts.to_pydatetime(), close_ts.to_pydatetime())


@pytest.fixture()
def db():
    conn = psycopg.connect(TEST_DB_URL, autocommit=True)
    assert conn.execute("SELECT current_database()").fetchone()[0] == "indicagent_test"
    symbols = [f"ZZ32{uuid.uuid4().hex[:6].upper()}" for _ in range(2)]
    for symbol in symbols:
        conn.execute(
            "INSERT INTO instruments (symbol, base, is_active, contract_details) "
            'VALUES (%s, %s, false, \'{"asset_class": "test"}\'::jsonb)',
            (symbol, symbol),
        )
    try:
        yield conn, symbols
    finally:
        with conn.transaction():
            for table in ("ohlcv_request", "ohlcv_raw", "market_data_ohlcv"):
                conn.execute(f"DELETE FROM {table} WHERE symbol = ANY(%s)", (symbols,))
            conn.execute("DELETE FROM instruments WHERE symbol = ANY(%s)", (symbols,))
        conn.close()


def _raw(conn, symbol: str, vendor: str, kind: str, stamps: list[datetime]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO ohlcv_raw (timestamp, symbol, timeframe, vendor, kind, open, high, low, "
            "close, volume) VALUES (%s, %s, '5m', %s, %s, 10, 10, 10, 10, 100)",
            [(ts, symbol, vendor, kind) for ts in stamps],
        )


def _request(conn, symbol: str, source: str, start: datetime, end: datetime, n_bars: int) -> None:
    route, what = _EVIDENCE[source]
    now = datetime.now(UTC)
    conn.execute(
        "INSERT INTO ohlcv_request (request_id, fetch_run_id, symbol, timeframe, source, route, "
        "what_to_show, window_start, window_end, outcome, n_bars, caller, requested_at, "
        "answered_at) VALUES (%s, %s, %s, '5m', %s, %s, %s, %s, %s, 'bars', %s, 'test', %s, %s)",
        (uuid.uuid4(), uuid.uuid4(), symbol, source, route, what, start, end, n_bars, now, now),
    )


def _slots(session: gate.Session) -> list[datetime]:
    n = int(session.expected_slots)
    return [session.open + timedelta(minutes=5 * i) for i in range(n)]


def test_half_day_counts_its_42_in_session_bars_and_not_the_2355_bar(db):
    conn, (symbol, _) = db
    half = _session(_HALF_DAY)
    assert half.expected_slots == 42
    late = datetime.combine(_HALF_DAY, datetime.min.time(), tzinfo=UTC) + timedelta(
        hours=23, minutes=55
    )
    _raw(conn, symbol, "ibkr", "named", [*_slots(half), late, half.open - timedelta(minutes=5)])
    segments = {symbol: [gate.Segment(_HALF_DAY, _FULL_DAY, "ibkr", "named")]}
    rows = list(gate.iter_5m_session_bars(conn, "ibkr", "named", segments, [half]))
    assert rows == [(symbol, _HALF_DAY, 42)]


def test_1d_bar_stamped_midnight_utc_counts_on_its_session_date(db):
    conn, (symbol, _) = db
    conn.execute(
        "INSERT INTO market_data_ohlcv (timestamp, symbol, timeframe, open, high, low, close, "
        "volume, vendor, kind) VALUES (%s, %s, '1d', 10, 10, 10, 10, 100, 'ibkr', 'smart_trades')",
        (datetime.combine(_HALF_DAY, datetime.min.time(), tzinfo=UTC), symbol),
    )
    segments = {symbol: [gate.Segment(_HALF_DAY, _FULL_DAY, "ibkr", "named")]}
    counts = gate.fetch_1d_counts(conn, segments, [_HALF_DAY], datetime(2016, 1, 1, tzinfo=UTC))
    assert counts == {(symbol, 2015, "ibkr/named"): 1}


# Until migration 581 (todo 596) is on main, the ohlcv_ask_current contract is a temporary view
# on this connection with 581's definition over a page table; pg_temp is searched first. Once the
# real view exists, the pages go into ohlcv_request and the real view answers.
_ASK_FIXTURE_DDL = """
CREATE TEMP TABLE ask_pages (
    ask_id uuid, fetch_run_id uuid, symbol text, timeframe text, source text, route text,
    what_to_show text, window_start timestamptz, window_end timestamptz, outcome text,
    n_bars int, requested_at timestamptz, answered_at timestamptz, partial_bars jsonb,
    page_index smallint, terminal boolean
);
CREATE TEMP VIEW ohlcv_ask_current AS
SELECT ask_id, min(fetch_run_id::text)::uuid AS fetch_run_id, min(symbol) AS symbol,
       min(timeframe) AS timeframe, min(source) AS source, min(route) AS route,
       min(what_to_show) AS what_to_show,
       min(window_start) FILTER (WHERE page_index = 0) AS ask_start,
       max(window_end) AS ask_end, count(*)::int AS n_pages, sum(n_bars)::int AS n_bars,
       min(requested_at) AS requested_at, max(answered_at) AS answered_at,
       bool_or(outcome = 'bars') AS served_bars,
       bool_or(partial_bars IS NOT NULL AND partial_bars <> '[]'::jsonb) AS has_partial,
       bool_or(terminal) AND count(*) = max(page_index) + 1
           AND bool_and(outcome IN ('bars', 'no_data')) AND bool_or(page_index = 0) AS complete
FROM ask_pages WHERE ask_id IS NOT NULL GROUP BY ask_id;
"""


def _ask_table(conn) -> str:
    if conn.execute("SELECT to_regclass('public.ohlcv_ask_current')").fetchone()[0] is not None:
        return "ohlcv_request"
    conn.execute(_ASK_FIXTURE_DDL)
    return "ask_pages"


def _page(
    conn,
    table,
    symbol,
    source,
    start,
    end,
    n_bars,
    *,
    ask,
    page,
    terminal,
    outcome="bars",
    partial=None,
):
    """One page row of an ask (the migration 581 columns)."""
    route, what = _EVIDENCE[source]
    now = datetime.now(UTC)
    extra = ", request_id, caller" if table == "ohlcv_request" else ""
    values = ", %s, 'test'" if table == "ohlcv_request" else ""
    conn.execute(
        f"INSERT INTO {table} (fetch_run_id, symbol, timeframe, source, route, what_to_show, "
        "window_start, window_end, outcome, n_bars, requested_at, answered_at, partial_bars, "
        f"ask_id, page_index, terminal{extra}) VALUES (%s, %s, '5m', %s, %s, %s, %s, %s, %s, "
        f"%s, %s, %s, %s, %s, %s, %s{values})",
        (
            uuid.uuid4(),
            symbol,
            source,
            route,
            what,
            start,
            end,
            outcome,
            n_bars,
            now,
            now,
            partial,
            ask,
            page,
            terminal,
            *((uuid.uuid4(),) if table == "ohlcv_request" else ()),
        ),
    )


def test_only_complete_asks_without_partial_bars_count(db):
    """Through ohlcv_ask_current (the real view, or its 581-contract fixture): a one-page terminal ask counts; an ask whose
    next page failed (no terminal page), an ask with a failed page, an ask that held back partial
    bars, another vendor's ask and a legacy request row (no ask_id) do not."""
    conn, symbols = db
    table = _ask_table(conn)
    half = _session(_HALF_DAY)
    start = datetime.combine(_HALF_DAY, datetime.min.time(), tzinfo=UTC)
    end = start + timedelta(days=1)
    complete, incomplete = symbols
    _page(conn, table, complete, "alpaca", start, end, 10, ask=uuid.uuid4(), page=0, terminal=True)
    _page(
        conn, table, incomplete, "alpaca", start, end, 10, ask=uuid.uuid4(), page=0, terminal=False
    )
    failed = uuid.uuid4()
    _page(conn, table, incomplete, "alpaca", start, end, 10, ask=failed, page=0, terminal=False)
    _page(
        conn,
        table,
        incomplete,
        "alpaca",
        start,
        end,
        0,
        ask=failed,
        page=1,
        terminal=False,
        outcome="failed",
    )
    _page(
        conn,
        table,
        incomplete,
        "alpaca",
        start,
        end,
        10,
        ask=uuid.uuid4(),
        page=0,
        terminal=True,
        partial='[{"t": "2015-11-27T17:55:00+00:00"}]',
    )
    _page(conn, table, incomplete, "ibkr", start, end, 10, ask=uuid.uuid4(), page=0, terminal=True)
    _request(conn, incomplete, "alpaca", start, end, 10)  # legacy: not an ask
    answers = gate.fetch_answers(
        conn, [("alpaca", "sip_rth")], symbols, datetime(2016, 1, 1, tzinfo=UTC)
    )
    assert set(answers) == {(complete, "alpaca/sip_rth")}
    assert answers[(complete, "alpaca/sip_rth")].covers(half)
