"""/api/concepts/summary: the registry with each concept's latest evidence, and the IC store."""

from datetime import UTC, datetime, timedelta

import pytest

from src.api import cache

EVALUATED = datetime(2026, 9, 24, tzinfo=UTC)
TRIGGERED = EVALUATED + timedelta(days=1)


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.clear()


def _answers(mock_db, *, fail_table=None):
    async def execute_query(sql, *args):
        if fail_table and f"FROM {fail_table}" in sql:
            raise TimeoutError("command_timeout")
        if "FROM feature_ic_scores_v2" in sql:
            return []
        return [
            {"name": "a", "status": "active", "evaluated_at": EVALUATED, "triggered_at": None},
            {"name": "b", "status": "candidate", "evaluated_at": None, "triggered_at": TRIGGERED},
        ]

    mock_db.execute_query.side_effect = execute_query


def test_concepts_carry_their_latest_evidence_and_transition(client, mock_db):
    _answers(mock_db)
    body = client.get("/api/concepts/summary").json()
    section = body["concepts"]
    assert section["source"] == "concept_registry, concept_evaluation, concept_transition_log"
    assert len(section["rows"]) == 2
    # as_of is the newest record of either kind, not just the newest evaluation.
    assert section["as_of"].startswith("2026-09-25")
    sql = next(
        c.args[0]
        for c in mock_db.execute_query.call_args_list
        if "FROM concept_registry" in c.args[0]
    )
    # The newest window, the one the lifecycle judges on, not the newest re-evaluation.
    assert "ORDER BY window_end DESC" in sql and "ORDER BY triggered_at DESC" in sql


def test_an_empty_ic_store_says_what_fills_it(client, mock_db):
    _answers(mock_db)
    ic = client.get("/api/concepts/summary").json()["ic"]
    assert ic["source"] == "feature_ic_scores_v2"
    assert ic["rows"] == [] and ic["as_of"] is None
    assert "186-26" in ic["meta"]["detail"]


def test_a_failing_section_does_not_take_down_the_other(client, mock_db):
    _answers(mock_db, fail_table="feature_ic_scores_v2")
    body = client.get("/api/concepts/summary").json()
    assert body["ic"]["meta"]["error"] == "TimeoutError"
    assert body["concepts"]["rows"]
