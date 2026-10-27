"""/api/universe: the map's per-name state and one name's data passport."""

from datetime import UTC, date, datetime, timedelta

import pytest

from src.api import cache
from src.api.routes.universe import name_state

NOW = datetime.now(UTC)
STALE_BEFORE = NOW - timedelta(hours=36)


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.clear()


def _row(**overrides):
    row = {
        "is_active": True,
        "listing_ended": None,
        "feeds": 2,
        "failing_feeds": 0,
        "newest_bar": NOW - timedelta(hours=1),
    }
    return {**row, **overrides}


@pytest.mark.parametrize(
    ("overrides", "state"),
    [
        ({}, "current"),
        ({"newest_bar": NOW - timedelta(days=3)}, "stale"),
        ({"failing_feeds": 1, "newest_bar": NOW - timedelta(days=3)}, "failing"),
        ({"listing_ended": date(2026, 10, 2), "failing_feeds": 1}, "ended"),
        ({"is_active": False, "listing_ended": date(2026, 10, 2)}, "inactive"),
        ({"feeds": 0, "newest_bar": None}, "no_data"),
    ],
)
def test_a_name_shows_its_most_severe_state(overrides, state):
    assert name_state(_row(**overrides), STALE_BEFORE) == state


def test_summary_reads_the_current_classification_and_listing_end(client, mock_db):
    mock_db.execute_query.return_value = [{"symbol": "AAPL", **_row()}]
    body = client.get("/api/universe/summary").json()
    sql = mock_db.execute_query.call_args.args[0]
    assert "listing_end_current" in sql and "valid_to IS NULL" in sql
    assert body["rows"][0]["state"] == "current"


def _passport_answers(mock_db, *, identity=True, fail_table=None):
    async def execute_query(sql, *args):
        if fail_table and f"FROM {fail_table}" in sql:
            raise TimeoutError("command_timeout")
        if "FROM instruments i" in sql:
            return [{"symbol": args[0], "name": "Apple Inc."}] if identity else []
        if "array_agg(session" in sql:
            return [
                {"timeframe": "1d", "vendor": "ibkr", "sessions": [date(2026, 10, 23)], "bars": [1]}
            ]
        if "array_agg(timestamp" in sql:
            return [{"t": [NOW], "close": [1.0]}]
        return []

    mock_db.execute_query.side_effect = execute_query


def test_passport_bars_come_from_the_tradeable_view(client, mock_db):
    _passport_answers(mock_db)
    body = client.get("/api/universe/aapl").json()
    assert body["identity"]["rows"][0]["symbol"] == "AAPL"
    assert body["lanes"]["source"] == body["closes"]["source"] == "market_data_ohlcv_tradeable"
    bar_sql = [c.args[0] for c in mock_db.execute_query.call_args_list if "ohlcv" in c.args[0]]
    assert all("market_data_ohlcv_tradeable" in s for s in bar_sql if "market_data" in s)


def test_an_unknown_name_is_a_404(client, mock_db):
    _passport_answers(mock_db, identity=False)
    assert client.get("/api/universe/NOPE").status_code == 404


def test_a_failing_section_does_not_take_down_the_passport(client, mock_db):
    _passport_answers(mock_db, fail_table="instrument_tags")
    body = client.get("/api/universe/AAPL").json()
    assert body["tags"]["meta"]["error"] == "TimeoutError"
    assert body["lanes"]["rows"]
