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


def _call(mock_db, fragment):
    return next(c for c in mock_db.execute_query.call_args_list if fragment in c.args[0])


def test_integrity_takes_each_subjects_newest_result_near_the_checks_newest_run(client, mock_db):
    # A run commits per row, so it spans many timestamps: the window is anchored at the check's own
    # newest row (not now), and each subject counts once, at its newest result.
    _answers(mock_db)
    body = client.get("/api/data/summary").json()
    call = _call(mock_db, "FROM integrity_monitor")
    assert "DISTINCT ON (m.monitor_type, m.metric_name, m.subject)" in call.args[0]
    assert "l.evaluated_at - make_interval(hours => $1)" in call.args[0]
    assert call.args[1] == 12  # the ui.dashboard.integrity_window_hours default
    assert body["integrity"]["meta"]["window_hours"] == 12


def test_failing_lists_only_names_with_fetch_failures(client, mock_db):
    _answers(mock_db)
    client.get("/api/data/summary")
    assert "WHERE consecutive_failures > 0" in _call(mock_db, "consecutive_failures,").args[0]


def test_restatements_lists_only_unreviewed_flags(client, mock_db):
    _answers(mock_db)
    client.get("/api/data/summary")
    assert "WHERE reviewed_at IS NULL" in _call(mock_db, "FROM ohlcv_restatement_flag").args[0]
