"""Integration: the truthful paginated-answer ledger (todo 596, migration 581) under the real roles.

A page's ohlcv_request row (ask id, page index, terminal) commits through the load engine in the
same transaction as that page's bars, and the raw rows it writes carry its request_id;
ohlcv_ask_current calls an ask complete only when its terminal page arrived, no page is missing
and no page failed or timed out. Rows without an ask id (every row before 581) never appear.

Runs on indicagent_test only; synthetic ZZ596 symbols are removed afterwards (ohlcv_request
refuses DELETE by trigger, so cleanup runs under session_replication_role = replica).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pandas as pd
import psycopg
import pytest

from services.bar_load import load_frame
from services.ohlcv_request_writer import RequestSink, _request_row
from src.providers.base import RequestRecord
from tests.integration.conftest import TEST_DB_URL

pytestmark = pytest.mark.integration

_START = datetime(2021, 3, 1, 14, 30, tzinfo=UTC)
_END = datetime(2021, 3, 6, tzinfo=UTC)


@pytest.fixture()
def db():
    conn = psycopg.connect(TEST_DB_URL, autocommit=True)
    assert conn.execute("SELECT current_database()").fetchone()[0] == "indicagent_test"
    symbol = f"ZZ596{uuid.uuid4().hex[:6].upper()}"
    conn.execute(
        "INSERT INTO instruments (symbol, base, is_active, contract_details) "
        'VALUES (%s, %s, false, \'{"asset_class": "test"}\'::jsonb)',
        (symbol, symbol),
    )
    # Canonical selection of the 5m rows needs a policy row; the test database holds none.
    conn.execute(
        "INSERT INTO bar_source_policy (timeframe, symbol, valid_from, ingress_mode, "
        "primary_source, reason) VALUES ('5m', %s, '1990-01-01', 'direct', 'alpaca', 'test')",
        (symbol,),
    )
    try:
        yield conn, symbol
    finally:
        with conn.transaction():
            conn.execute("DELETE FROM ohlcv_coverage WHERE symbol = %s", (symbol,))
            conn.execute("DELETE FROM market_data_ohlcv WHERE symbol = %s", (symbol,))
            conn.execute("DELETE FROM bar_session_choice WHERE symbol = %s", (symbol,))
            conn.execute("DELETE FROM ohlcv_raw WHERE symbol = %s", (symbol,))
            conn.execute("DELETE FROM ohlcv_revision WHERE symbol = %s", (symbol,))
            conn.execute("DELETE FROM ohlcv_restatement_flag WHERE symbol = %s", (symbol,))
            conn.execute("DELETE FROM ohlcv_load WHERE symbol = %s", (symbol,))
            conn.execute("SET LOCAL session_replication_role = replica")
            conn.execute("DELETE FROM ohlcv_request WHERE symbol = %s", (symbol,))
            conn.execute("DELETE FROM bar_source_policy WHERE symbol = %s", (symbol,))
            conn.execute("SET LOCAL session_replication_role = origin")
            conn.execute("DELETE FROM instruments WHERE symbol = %s", (symbol,))
        conn.close()


def _page(symbol, ask_id, index, *, terminal, outcome="bars", n_bars=1, start=_START):
    now = datetime.now(UTC)
    return RequestRecord(
        request_id=str(uuid.uuid4()),
        fetch_run_id=ask_id or str(uuid.uuid4()),  # one run per ask, as the leaf writes it
        symbol=symbol,
        timeframe="5m",
        route="SIP",
        what_to_show="5Min",
        primary_exchange=None,
        window_start=start,
        window_end=_END,
        ib_req_id=None,
        outcome=outcome,
        error_code=None,
        error_text=None,
        n_bars=n_bars,
        client_id=None,
        requested_at=now,
        answered_at=now,
        ask_id=ask_id,
        page_index=index,
        terminal=terminal,
    )


def _write(conn, *records):
    sink = RequestSink(conn, caller="test-596", source="alpaca")
    for record in records:
        sink.on_request(record)
    sink.flush()


def _complete(conn, ask_id):
    row = conn.execute(
        "SELECT complete, ask_start, ask_end, n_pages FROM ohlcv_ask_current WHERE ask_id = %s",
        (ask_id,),
    ).fetchone()
    return row


def test_an_ask_is_complete_only_with_its_terminal_page_every_page_and_no_failure(db):
    conn, symbol = db
    whole = str(uuid.uuid4())
    _write(
        conn,
        _page(symbol, whole, 0, terminal=False),
        _page(symbol, whole, 1, terminal=True, start=_START + timedelta(days=2)),
    )
    assert _complete(conn, whole) == (True, _START, _END, 2)

    stopped = str(uuid.uuid4())  # a budget stop after page 0
    _write(conn, _page(symbol, stopped, 0, terminal=False))
    assert _complete(conn, stopped)[0] is False

    failed = str(uuid.uuid4())
    _write(
        conn,
        _page(symbol, failed, 0, terminal=False),
        _page(symbol, failed, 1, terminal=False, outcome="failed", n_bars=0),
    )
    assert _complete(conn, failed)[0] is False

    gap = str(uuid.uuid4())  # page 1 never landed
    _write(conn, _page(symbol, gap, 0, terminal=False), _page(symbol, gap, 2, terminal=True))
    assert _complete(conn, gap)[0] is False

    empty = str(uuid.uuid4())  # one terminal no_data page is a complete answer
    _write(conn, _page(symbol, empty, 0, terminal=True, outcome="no_data", n_bars=0))
    assert _complete(conn, empty)[0] is True


def test_a_legacy_row_is_not_an_ask(db):
    conn, symbol = db
    legacy = _page(symbol, None, None, terminal=None)
    _write(conn, legacy)
    assert conn.execute(
        "SELECT count(*) FROM ohlcv_ask_current WHERE symbol = %s", (symbol,)
    ).fetchone() == (0,)


def test_a_failed_page_cannot_be_terminal(db):
    conn, symbol = db
    with pytest.raises(psycopg.errors.CheckViolation):
        _write(conn, _page(symbol, str(uuid.uuid4()), 0, terminal=True, outcome="failed"))


def test_a_page_row_commits_with_its_bars_and_the_bars_name_it(db):
    conn, symbol = db
    stamps = [pd.Timestamp(_START + timedelta(minutes=5 * i)) for i in range(4)]
    frame = pd.DataFrame({"t": stamps, "o": 10.0, "h": 11.0, "l": 9.0, "c": 10.5, "v": 100})
    record = _page(symbol, str(uuid.uuid4()), 0, terminal=True, n_bars=4)
    request_rows = [_request_row(record, caller="test-596", source="alpaca")]
    load_frame(
        conn,
        symbol,
        frame,
        vendor="alpaca",
        timeframe="5m",
        caller="test-596",
        write=True,
        answered_at=record.answered_at,
        coverage=False,
        kind="sip_rth",
        request_rows=request_rows,
    )
    assert conn.execute(
        "SELECT count(*), count(DISTINCT request_id), min(request_id::text) FROM ohlcv_raw "
        "WHERE symbol = %s",
        (symbol,),
    ).fetchone() == (4, 1, record.request_id)
    assert conn.execute(
        "SELECT ask_id::text, page_index, terminal, content_digest IS NOT NULL "
        "FROM ohlcv_request WHERE symbol = %s",
        (symbol,),
    ).fetchone() == (record.ask_id, 0, True, True)


def test_an_empty_page_commits_its_row_alone_and_a_dry_run_writes_nothing(db):
    conn, symbol = db
    empty = pd.DataFrame(
        {"t": pd.to_datetime([], utc=True), "o": [], "h": [], "l": [], "c": [], "v": []}
    )
    record = _page(symbol, str(uuid.uuid4()), 0, terminal=True, outcome="no_data", n_bars=0)
    rows = [_request_row(record, caller="test-596", source="alpaca")]
    kwargs = dict(vendor="alpaca", timeframe="5m", caller="test-596", kind="sip_rth")
    load_frame(conn, symbol, empty, write=False, request_rows=rows, **kwargs)
    assert conn.execute(
        "SELECT count(*) FROM ohlcv_request WHERE symbol = %s", (symbol,)
    ).fetchone() == (0,)
    load_frame(
        conn, symbol, empty, write=True, answered_at=record.answered_at, request_rows=rows, **kwargs
    )
    assert _complete(conn, record.ask_id)[0] is True


def test_a_page_that_does_not_fit_one_chunk_is_refused_before_any_write(db):
    conn, symbol = db
    stamps = [pd.Timestamp(_START + timedelta(minutes=5 * i)) for i in range(3)]
    frame = pd.DataFrame({"t": stamps, "o": 10.0, "h": 11.0, "l": 9.0, "c": 10.5, "v": 100})
    record = _page(symbol, str(uuid.uuid4()), 0, terminal=True, n_bars=3)
    with pytest.raises(ValueError, match="exceed one chunk"):
        load_frame(
            conn,
            symbol,
            frame,
            vendor="alpaca",
            timeframe="5m",
            caller="test-596",
            write=True,
            answered_at=record.answered_at,
            kind="sip_rth",
            chunk_rows=2,
            request_rows=[_request_row(record, caller="test-596", source="alpaca")],
        )
    assert conn.execute(
        "SELECT count(*) FROM ohlcv_request WHERE symbol = %s", (symbol,)
    ).fetchone() == (0,)


def test_ask_fields_are_set_together_or_not_at_all(db):
    conn, symbol = db
    with pytest.raises(psycopg.errors.CheckViolation):
        _write(conn, _page(symbol, str(uuid.uuid4()), None, terminal=False))
