"""/api/data/summary: six sections, each from its writer's table, one cached response."""

from datetime import UTC, datetime, timedelta

import pytest

from src.api import cache

T = datetime.now(UTC) - timedelta(hours=1)
TABLES = {
    "feeds": "ohlcv_coverage",
    "failing": "ohlcv_coverage",
    "integrity": "integrity_monitor",
    "restatements": "ohlcv_restatement_flag",
    "listing_ends": "listing_end",
    "dividends": "dividend_event_coverage",
}


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.clear()


def _answers(mock_db, *, failing=0, fail_table=None):
    async def execute_query(sql, *args):
        if fail_table and f"FROM {fail_table}" in sql:
            raise TimeoutError("command_timeout")
        if "FROM ohlcv_coverage GROUP BY" in sql:
            return [
                {
                    "timeframe": "1d",
                    "provider": "ibkr",
                    "symbols": 10,
                    "newest_bar": T,
                    "last_fetch": T,
                    "failing": failing,
                }
            ]
        return [
            {
                "newest": T,
                "last_fetched_at": T,
                "evaluated_at": T,
                "flagged_at": T,
                "recorded_at": T,
                "checked_at": T,
            }
        ]

    mock_db.execute_query.side_effect = execute_query


def test_every_section_reports_its_source_table(client, mock_db):
    _answers(mock_db)
    body = client.get("/api/data/summary").json()
    assert {name: body[name]["source"] for name in TABLES} == TABLES


def test_feed_rows_carry_the_pipeline_status(client, mock_db):
    _answers(mock_db, failing=5)  # 5 of 10 names failing: above the 0.1 APR bound
    row = client.get("/api/data/summary").json()["feeds"]["rows"][0]
    assert row["status"] == "failing"


def test_a_failing_section_does_not_take_down_the_others(client, mock_db):
    _answers(mock_db, fail_table="integrity_monitor")
    body = client.get("/api/data/summary").json()
    assert body["integrity"]["meta"]["error"] == "TimeoutError"
    assert body["listing_ends"]["rows"]


def test_integrity_reads_each_checks_latest_run_only(client, mock_db):
    _answers(mock_db)
    client.get("/api/data/summary")
    sql = next(
        c.args[0] for c in mock_db.execute_query.call_args_list if "integrity_monitor" in c.args[0]
    )
    assert "max(evaluated_at)" in sql and "USING (monitor_type, metric_name, evaluated_at)" in sql
