"""Integration: D1 append-only guards and writer role against the live indicagent DB.

Runs against the production database (not indicagent_test) because the point is the
live schema's triggers and grants. Appends a tiny, clearly tagged set through the real
ObservationSink: 2 requests and 3 observations, symbol SPY, caller 'test-185-02', one
dedicated fetch_run_id per run. These rows are permanent by design and are never
cleaned up: D1 has no UPDATE, DELETE or TRUNCATE, which is exactly what this test
proves. Every later run appends its own fetch_run_id and passes the same assertions.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import psycopg
import pytest

from services.ohlcv_observation_writer import ObservationSink, new_fetch_run_id
from src.providers.base import OHLCVBar

_LIVE_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent"


def _record(fetch_run_id: str, request_id: str, *, what_to_show: str, outcome: str, n_bars: int):
    now = datetime.now(UTC)
    return type(
        "Record",
        (),
        {
            "request_id": request_id,
            "fetch_run_id": fetch_run_id,
            "symbol": "SPY",
            "timeframe": "1d",
            "route": "SMART",
            "what_to_show": what_to_show,
            "primary_exchange": "NYSE",
            "window_start": None,
            "window_end": now,
            "ib_req_id": None,
            "outcome": outcome,
            "error_code": None,
            "error_text": None,
            "n_bars": n_bars,
            "client_id": None,
            "requested_at": now,
            "answered_at": now,
        },
    )()


def _bars() -> list[OHLCVBar]:
    return [
        OHLCVBar(
            symbol="SPY",
            timeframe="1d",
            timestamp=datetime(2024, 1, 2 + i, 0, 0, tzinfo=UTC),
            open=100.0 + i,
            high=101.0 + i,
            low=99.0 + i,
            close=100.5 + i,
            volume=1_000 * (i + 1),
            source="ibkr",
        )
        for i in range(3)
    ]


def test_sink_append_then_guards_and_cross_role_refusal():
    fetch_run_id = uuid.UUID(new_fetch_run_id())
    with psycopg.connect(_LIVE_DB_URL) as conn:
        sink = ObservationSink(conn, caller="test-185-02")
        trades = _record(
            str(fetch_run_id), str(uuid.uuid4()), what_to_show="TRADES", outcome="bars", n_bars=3
        )
        adjusted = _record(
            str(fetch_run_id),
            str(uuid.uuid4()),
            what_to_show="ADJUSTED_LAST",
            outcome="no_data",
            n_bars=0,
        )
        sink.on_request(trades)
        sink.on_observation(trades, _bars())
        sink.on_request(adjusted)
        assert sink.flush() == (2, 3)
        assert sink.pending() == 0

        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM ohlcv_request "
                "WHERE fetch_run_id = %s AND caller = 'test-185-02'",
                (fetch_run_id,),
            )
            assert cur.fetchone()[0] == 2
            cur.execute(
                "SELECT count(*) FROM ohlcv_observation o "
                "JOIN ohlcv_request r USING (request_id) WHERE r.fetch_run_id = %s",
                (fetch_run_id,),
            )
            assert cur.fetchone()[0] == 3

        # Append-only: every rewrite shape raises on both tables. TRUNCATE on the
        # FK-referenced side (ohlcv_request) is refused by the planner before the
        # trigger can fire; both refusals prove TRUNCATE cannot succeed.
        for statement, expected in (
            ("UPDATE ohlcv_request SET n_bars = 0", (psycopg.errors.CheckViolation,)),
            ("DELETE FROM ohlcv_request", (psycopg.errors.CheckViolation,)),
            (
                "TRUNCATE ohlcv_request",
                (psycopg.errors.CheckViolation, psycopg.errors.FeatureNotSupported),
            ),
            ("UPDATE ohlcv_observation SET close = 0", (psycopg.errors.CheckViolation,)),
            ("DELETE FROM ohlcv_observation", (psycopg.errors.CheckViolation,)),
            ("TRUNCATE ohlcv_observation", (psycopg.errors.CheckViolation,)),
        ):
            with conn.cursor() as cur:
                with pytest.raises(expected):
                    cur.execute(statement)
            conn.rollback()

        # Cross-role: bar_derivation_writer can read D1 but cannot append to it.
        conn.rollback()  # close the implicit transaction the reads above opened
        with conn.cursor() as cur:
            cur.execute("SET LOCAL ROLE bar_derivation_writer")
            cur.execute(
                "SELECT count(*) FROM ohlcv_request WHERE fetch_run_id = %s",
                (fetch_run_id,),
            )
            assert cur.fetchone()[0] == 2  # reads pass under the role
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute(
                    "INSERT INTO ohlcv_request (request_id, fetch_run_id, symbol, "
                    "timeframe, source, route, what_to_show, window_end, outcome, "
                    "n_bars, caller, requested_at, answered_at) VALUES "
                    "(gen_random_uuid(), %s, 'SPY', '1d', 'ibkr', 'SMART', 'TRADES', "
                    "now(), 'failed', 0, 'test-185-02-role-probe', now(), now())",
                    (fetch_run_id,),
                )
        conn.rollback()
