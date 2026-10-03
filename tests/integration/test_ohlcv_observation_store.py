"""Integration: D1 append-only guards and writer role against the replayed indicagent_test DB.

Runs against indicagent_test, never the production database: the schema (triggers,
grants) comes from the migration replay, and the rows this test appends are permanent
by design (D1 has no UPDATE, DELETE or TRUNCATE, which is exactly what it proves). On
production they are not inert: bar_derivation derives each 1d bar from the latest
TRADES observation, so fixture rows on real SPY dates become canonical bars. This test
did that until 2026-10-03 (27 fixture rows on SPY 2024-01-02 to 01-04); the session
rebuild of indicagent_test discards them each run. Appends a tiny, clearly tagged set
through the real ObservationSink: 2 requests and 3 observations, symbol SPY, caller
'test-185-02', one dedicated fetch_run_id per run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import psycopg
import pytest

from services.ohlcv_observation_writer import ObservationSink, new_fetch_run_id
from src.providers.base import OHLCVBar

_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent_test"


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
    with psycopg.connect(_TEST_DB_URL) as conn:
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

        # Mutable since migration 438: the writer role can correct its own rows.
        with conn.cursor() as cur:
            cur.execute("SET LOCAL ROLE ohlcv_observation_writer")
            cur.execute(
                "UPDATE ohlcv_request SET n_bars = n_bars WHERE fetch_run_id = %s",
                (fetch_run_id,),
            )
            assert cur.rowcount == 2
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
