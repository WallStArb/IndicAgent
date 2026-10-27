"""/api/pipeline/summary: one row per DAG stage, status read from stored rows, never computed."""

from datetime import UTC, datetime, timedelta

import pytest

from src.api import cache

FRESH = datetime.now(UTC) - timedelta(hours=1)
OLD = datetime.now(UTC) - timedelta(days=30)


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.clear()


def _db_answers(mock_db, *, failing=0, ic_newest=None, research=True):
    async def execute_query(sql, *args):
        if "FROM ohlcv_coverage" in sql:
            return [
                {
                    "timeframe": "1d",
                    "provider": "ibkr",
                    "symbols": 10,
                    "newest_bar": FRESH,
                    "last_fetch": FRESH,
                    "failing": failing,
                }
            ]
        if "FROM feature_vectors" in sql:
            return [
                {"store": "feature_vectors", "newest_bar": OLD},
                {"store": "feature_vectors_v2", "newest_bar": None},
            ]
        if "FROM market_regimes" in sql:
            return [{"newest_bar": FRESH}]
        if "FROM concept_registry" in sql:
            return [{"status": "active", "count": 3}]
        if "FROM feature_ic_scores_v2" in sql:
            return [{"ic_rows": 0, "newest": ic_newest}]
        if "FROM research_run" in sql:
            return [{"status": "completed", "runs": 2, "newest": FRESH}] if research else []
        raise AssertionError(f"unexpected query: {sql}")

    mock_db.execute_query.side_effect = execute_query


def _stages(client):
    resp = client.get("/api/pipeline/summary")
    assert resp.status_code == 200
    return {s["stage"]: s for s in resp.json()["stages"]}


def test_every_stage_reports_its_source_table(client, mock_db):
    _db_answers(mock_db)
    stages = _stages(client)
    assert list(stages) == ["ingest", "feature", "regime", "measure", "research", "book"]
    assert stages["ingest"]["source"] == "ohlcv_coverage"
    assert stages["regime"]["source"] == "market_regimes"
    assert stages["book"]["status"] == "not_built"


def test_status_reads_freshness_and_failures(client, mock_db):
    _db_answers(mock_db, failing=0)
    stages = _stages(client)
    assert stages["ingest"]["status"] == "ok"
    assert stages["feature"]["status"] == "stale"  # newest feature row 30 days old, bound 36 h
    assert stages["regime"]["status"] == "ok"

    _db_answers(mock_db, failing=1)  # 1 of 10 rows: at the 0.1 bound, not above it
    cache.clear()
    ingest = _stages(client)["ingest"]
    assert ingest["status"] == "ok" and ingest["meta"]["failing_rows"] == 1

    _db_answers(mock_db, failing=4)
    cache.clear()
    assert _stages(client)["ingest"]["status"] == "failing"


def test_a_table_with_no_rows_is_empty_not_ok(client, mock_db):
    _db_answers(mock_db, research=False)
    assert _stages(client)["research"]["status"] == "empty"


def test_refresh_interval_is_served_from_apr(client, mock_db):
    _db_answers(mock_db)
    body = client.get("/api/pipeline/summary").json()
    assert body["refresh_seconds"] == 60 and body["stale_hours"] == 36
    assert client.get("/api/pipeline/config").json() == {"refresh_seconds": 60, "stale_hours": 36}


def test_summary_is_cached_for_one_refresh_interval(client, mock_db):
    _db_answers(mock_db)
    client.get("/api/pipeline/summary")
    calls = mock_db.execute_query.call_count
    client.get("/api/pipeline/summary")
    assert mock_db.execute_query.call_count == calls


def test_one_dead_feed_is_not_hidden_by_a_healthy_one(client, mock_db):
    async def execute_query(sql, *args):
        if "FROM ohlcv_coverage" in sql:
            return [
                {
                    "timeframe": "1d",
                    "provider": "ibkr",
                    "symbols": 1000,
                    "newest_bar": FRESH,
                    "last_fetch": FRESH,
                    "failing": 0,
                },
                {
                    "timeframe": "5m",
                    "provider": "alpaca",
                    "symbols": 10,
                    "newest_bar": OLD,
                    "last_fetch": FRESH,
                    "failing": 0,
                },
            ]
        return [
            {
                "newest_bar": FRESH,
                "status": "x",
                "count": 1,
                "runs": 1,
                "newest": FRESH,
                "ic_rows": 0,
                "store": "feature_vectors",
            }
        ]

    mock_db.execute_query.side_effect = execute_query
    ingest = _stages(client)["ingest"]
    assert ingest["status"] == "stale"  # the 5m feed's bars are 30 days old, fetched or not
    assert [r["status"] for r in ingest["rows"]] == ["ok", "stale"]


def test_a_failing_stage_query_marks_only_that_stage(client, mock_db):
    _db_answers(mock_db)
    answer = mock_db.execute_query.side_effect

    async def execute_query(sql, *args):
        if "FROM market_regimes" in sql:
            raise TimeoutError("command_timeout")
        return await answer(sql, *args)

    mock_db.execute_query.side_effect = execute_query
    stages = _stages(client)
    assert stages["regime"]["status"] == "error"
    assert stages["regime"]["meta"]["error"] == "TimeoutError"
    assert stages["ingest"]["status"] == "ok" and stages["measure"]["status"] == "ok"
