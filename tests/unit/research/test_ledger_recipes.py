"""The ledger's refusals about recipes and the informing attempt (plan 187-11 Task 2), before
anything is written. The writes themselves are covered against the database in
tests/integration/test_research_ledger.py."""

import asyncio
import dataclasses
from pathlib import Path
from uuid import uuid4

import pytest

from src.intelligence.research.ledger import Identity, LedgerRefusal, PostgresLedger, RunRequest
from src.intelligence.research.recipe import RecipeContent


def _recipe(name, **cvr):
    return RecipeContent(
        name, "m:f", {}, {}, (), None, cvr or {"research_timeframe": "15m"}, None, ()
    )


def _request(recipes=(), informed_by=None):
    return RunRequest(
        kind="evidence",
        spec_path="research/specs/x.yaml",
        spec_hash="0" * 64,
        spec_blob="b",
        code_commit="0" * 40,
        vintage="test",
        recipes={r.concept: r for r in recipes},
        informed_by=informed_by,
    )


class FakeConn:
    def __init__(self, vocabulary=(("research_timeframe", "15m"),), run_status=None):
        self.vocabulary, self.run_status = vocabulary, run_status
        self.writes = 0

    async def fetch(self, sql, *args):
        return [{"namespace": n, "code": c} for n, c in self.vocabulary]

    async def fetchval(self, sql, *args):
        return self.run_status

    async def execute(self, *args):
        self.writes += 1


def _check(conn, request, names=("member.f.a",), run_concepts=("member.f.a",)):
    ids = [Identity(n, "member", "d") for n in names]
    asyncio.run(PostgresLedger._check_recipes(conn, request, ids, list(run_concepts)))


def test_known_codes_and_no_informing_attempt_pass():
    _check(FakeConn(), _request([_recipe("member.f.a")]))


def test_an_unregistered_cvr_code_is_refused_naming_it():
    conn = FakeConn()
    with pytest.raises(LedgerRefusal, match="research_timeframe.*4h"):
        _check(conn, _request([_recipe("member.f.a", research_timeframe="4h")]))
    assert conn.writes == 0


def test_a_recipe_for_a_concept_the_run_does_not_name_is_refused():
    with pytest.raises(LedgerRefusal, match="not an identity"):
        _check(FakeConn(), _request([_recipe("member.f.other")]))


def test_a_run_concept_without_a_recipe_is_refused_once_any_recipe_is_given():
    with pytest.raises(LedgerRefusal, match="no recipe"):
        _check(
            FakeConn(),
            _request([_recipe("member.f.a")]),
            names=("member.f.a", "member.f.b"),
            run_concepts=("member.f.a", "member.f.b"),
        )


def test_no_recipes_is_the_old_behaviour():
    _check(FakeConn(), _request())


@pytest.mark.parametrize("status", [None, "started"])
def test_informed_by_must_be_a_terminal_run(status):
    request = dataclasses.replace(_request(), informed_by=str(uuid4()))
    with pytest.raises(LedgerRefusal, match="not a terminal"):
        _check(FakeConn(run_status=status), request)


def test_informed_by_accepts_a_terminal_run():
    request = dataclasses.replace(_request(), informed_by=str(uuid4()))
    _check(FakeConn(run_status="completed"), request)


def test_a_malformed_informed_by_is_a_refusal_not_a_crash():
    request = dataclasses.replace(_request(), informed_by="not-a-uuid")
    with pytest.raises(LedgerRefusal, match="not a run id"):
        _check(FakeConn(), request)


def test_the_research_modules_read_no_apr_directly():
    """A recipe pins the APR values a run's definition depends on, and run_spec hands them in
    through RunContext.apr_values. A research module that read ConfigService itself would depend
    on an APR key no recipe records (plan 187-11)."""
    root = Path(__file__).resolve().parents[3] / "src/intelligence/research"
    readers = sorted(
        p.name
        for p in root.rglob("*.py")
        if "ConfigService" in p.read_text() or "config_service" in p.read_text()
    )
    assert readers == []


def test_seed_recipes_refuses_a_recipe_filed_under_another_concept():
    with pytest.raises(LedgerRefusal, match="different concept"):
        asyncio.run(
            PostgresLedger("postgresql://unused").seed_recipes(
                "feature", {"a": _recipe("b")}, code_commit="0" * 40, author="x"
            )
        )
