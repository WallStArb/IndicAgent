"""/api/research/summary: the research ledger by vintage and by attempt, and the legacy gates."""

from datetime import UTC, datetime, timedelta

import pytest

from src.api import cache
from src.api.routes.research import BOOK_KINDS
from src.intelligence.research.ledger import UNCHARGED_STATUSES

STARTED = datetime(2026, 9, 29, tzinfo=UTC)
FINISHED = STARTED + timedelta(hours=1)


@pytest.fixture(autouse=True)
def _fresh_cache():
    cache.clear()


def _run(group, finished_at=None):
    return {"run_group": group, "started_at": STARTED, "finished_at": finished_at}


def _answers(mock_db, *, fail_table=None):
    async def execute_query(sql, *args):
        if fail_table and f"FROM {fail_table}" in sql:
            raise TimeoutError("command_timeout")
        if "count(DISTINCT run_group)" in sql:
            return [{"run_groups": 40}]
        if "JOIN concept_registry" in sql:
            return [_run("a", FINISHED), _run("a"), _run("b")]
        if "FROM gate_evaluations" in sql:
            return [{"run_ts": STARTED}]
        return [{"newest": STARTED}]

    mock_db.execute_query.side_effect = execute_query


def _call(mock_db, fragment):
    return next(c for c in mock_db.execute_query.call_args_list if fragment in c.args[0])


def test_every_section_reports_its_source(client, mock_db):
    _answers(mock_db)
    body = client.get("/api/research/summary").json()
    assert body["vintages"]["source"] == "research_run"
    assert body["runs"]["source"] == "research_run, concept_registry"
    assert body["gates"]["source"] == "gate_evaluations"


def test_charged_looks_exclude_exactly_the_ledgers_uncharged_statuses(client, mock_db):
    _answers(mock_db)
    client.get("/api/research/summary")
    call = _call(mock_db, "AS charged")
    assert call.args[1] == list(UNCHARGED_STATUSES)


def test_runs_are_capped_but_count_the_whole_ledger(client, mock_db):
    _answers(mock_db)
    runs = client.get("/api/research/summary").json()["runs"]
    assert runs["meta"] == {"limit": 500, "run_groups": 40}
    call = next(
        c for c in mock_db.execute_query.call_args_list if c.args[0].rstrip().endswith("LIMIT $1")
    )
    assert call.args[1] == 500  # the ui.dashboard.research_rows default
    # A terminal update lands after its start, so the lineage dates from the latest finish.
    assert runs["as_of"].startswith(FINISHED.strftime("%Y-%m-%dT%H"))


def test_book_tests_are_the_whole_book_attempts_under_the_same_cap(client, mock_db):
    _answers(mock_db)
    body = client.get("/api/research/summary").json()
    call = next(c for c in mock_db.execute_query.call_args_list if "r.kind = ANY" in c.args[0])
    assert call.args[1:] == (list(BOOK_KINDS), 500)
    assert len(body["book_tests"]["rows"]) == 3


def test_headlines_fall_back_to_the_stored_decision(client, mock_db):
    # Rows written before migration 515 carry their headline only in evidence.decision, and the
    # append-only ledger cannot backfill them.
    _answers(mock_db)
    client.get("/api/research/summary")
    sql = _call(mock_db, "JOIN concept_registry").args[0]
    for column, key in (("decision_t", "t"), ("gross_sharpe", "annualized_sharpe")):
        assert f"coalesce(r.{column}, (r.evidence->'decision'->>'{key}')" in sql


def test_a_failing_gates_query_leaves_the_ledger_sections(client, mock_db):
    _answers(mock_db, fail_table="gate_evaluations")
    body = client.get("/api/research/summary").json()
    assert body["gates"]["meta"]["error"] == "TimeoutError"
    assert body["runs"]["rows"]
