"""Integration tests: the research_run ledger's database-level rules (phase 183, migration 366).

Proves in the database, not only in Python: a spec runs once (D-02, the partial unique index
and ledger.start_runs), rows are append-only (D-07, the guard triggers), and the vintage budget
charges book tests unless they ended refused or guard_failed (D-08). A trigger nobody has
fired is a claim, not a mechanism.

Runs against indicagent_test (migrations replayed by tests/integration/conftest.py). Cleanup
cannot DELETE research_run rows, by design; teardown disables the table's user triggers inside
one transaction on the test database only, deletes this test's rows, and re-enables them.

Run: pytest tests/integration/test_research_ledger.py -m integration
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import AsyncIterator
from uuid import uuid4

import asyncpg
import numpy as np
import pytest

from src.core.database_manager import connect_with_codecs
from src.intelligence.research.ledger import (
    AttemptSeries,
    Identity,
    LedgerRefusal,
    PostgresLedger,
    RunRequest,
)

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent_test"


def _name() -> str:
    return f"_p183_{uuid4().hex[:8]}"


def _hash() -> str:
    return uuid4().hex * 2


def _commit() -> str:
    return (uuid4().hex * 2)[:40]


class _Scope:
    """Names and vintages this test created, for teardown."""

    def __init__(self) -> None:
        self.names: list[str] = []
        self.vintages: list[str] = []

    def identities(self, n_members: int = 1) -> tuple[list[Identity], list[str]]:
        family = _name()
        members = [_name() for _ in range(n_members)]
        self.names += [family, *members]
        ids = [Identity(family, "family", "test family")] + [
            Identity(m, "member", "test member", {"window": 5}, parents=(family,)) for m in members
        ]
        return ids, members

    def request(self, kind: str = "evidence", *, vintage: str | None = None, **kw) -> RunRequest:
        if vintage is None:
            vintage = _name()
        self.vintages.append(vintage)
        if kind == "book_test":
            kw.setdefault("budget_m", 3)
            kw.setdefault("screen_alpha", 0.05)
        return RunRequest(
            kind=kind,
            spec_path="research/specs/test.yaml",
            spec_hash=_hash(),
            spec_blob="members: []",
            code_commit=_commit(),
            vintage=vintage,
            **kw,
        )


@pytest.fixture
async def scope() -> AsyncIterator[_Scope]:
    tracked = _Scope()
    try:
        yield tracked
    finally:
        conn = await asyncpg.connect(_TEST_DB_URL)
        try:
            ids = [
                r["concept_id"]
                for r in await conn.fetch(
                    "SELECT concept_id FROM concept_registry "
                    "WHERE domain = ANY(ARRAY['family','member','combiner','construction_rule','book']) "
                    "AND name = ANY($1::text[])",
                    tracked.names,
                )
            ]
            async with conn.transaction():
                await conn.execute("ALTER TABLE research_run_series DISABLE TRIGGER USER")
                await conn.execute(
                    "DELETE FROM research_run_series WHERE run_id IN (SELECT run_id FROM "
                    "research_run WHERE concept_id = ANY($1::uuid[]) OR vintage = ANY($2::text[]))",
                    ids,
                    tracked.vintages,
                )
                await conn.execute("ALTER TABLE research_run_series ENABLE TRIGGER USER")
                await conn.execute("ALTER TABLE research_run DISABLE TRIGGER USER")
                await conn.execute(
                    "DELETE FROM research_run WHERE concept_id = ANY($1::uuid[]) "
                    "OR vintage = ANY($2::text[])",
                    ids,
                    tracked.vintages,
                )
                await conn.execute("ALTER TABLE research_run ENABLE TRIGGER USER")
                await conn.execute("ALTER TABLE concept_recipe DISABLE TRIGGER USER")
                await conn.execute(
                    "DELETE FROM concept_recipe WHERE concept_id = ANY($1::uuid[])", ids
                )
                await conn.execute("ALTER TABLE concept_recipe ENABLE TRIGGER USER")
            await conn.execute(
                "DELETE FROM concept_parent WHERE child_concept_id = ANY($1::uuid[]) "
                "OR parent_concept_id = ANY($1::uuid[])",
                ids,
            )
            await conn.execute(
                "DELETE FROM concept_registry WHERE concept_id = ANY($1::uuid[])", ids
            )
        finally:
            await conn.close()


@pytest.fixture
def ledger() -> PostgresLedger:
    return PostgresLedger(_TEST_DB_URL)


async def _row(run_id: str) -> asyncpg.Record:
    conn = await connect_with_codecs(_TEST_DB_URL)
    try:
        return await conn.fetchrow("SELECT * FROM research_run WHERE run_id = $1::uuid", run_id)
    finally:
        await conn.close()


async def _execute(sql: str, *args) -> None:
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        await conn.execute(sql, *args)
    finally:
        await conn.close()


async def _started(ledger, scope, kind="evidence", **kw) -> str:
    ids, members = scope.identities()
    runs = await ledger.start_runs(scope.request(kind, **kw), ids, members)
    return runs[members[0]]


async def test_spec_once_python(ledger, scope):
    ids, members = scope.identities()
    request = scope.request()
    await ledger.start_runs(request, ids, members)
    assert await ledger.has_real_run(request.spec_hash)
    with pytest.raises(LedgerRefusal, match="spec already run"):
        await ledger.start_runs(request, ids, members)


async def test_spec_once_index(ledger, scope):
    run_id = await _started(ledger, scope)
    row = await _row(run_id)
    with pytest.raises(asyncpg.UniqueViolationError):
        await _execute(
            "INSERT INTO research_run (run_group, concept_id, kind, mode, spec_path, spec_hash, "
            "spec_blob, code_commit, vintage) VALUES ($1, $2, 'evidence', 'real', 'x', $3, 'x', "
            "$4, $5)",
            uuid4(),
            row["concept_id"],
            row["spec_hash"],
            row["code_commit"],
            row["vintage"],
        )


async def test_trigger_started_to_terminal_once(ledger, scope):
    run_id = await _started(ledger, scope)
    await ledger.finish_run(run_id, status="completed", snapshot_hash="abc", evidence={"e": 1.0})
    with pytest.raises(asyncpg.PostgresError, match="append-only"):
        await ledger.finish_run(run_id, status="failed", snapshot_hash="abc", evidence={})
    assert (await _row(run_id))["status"] == "completed"


async def test_trigger_rejects_other_column_edits(ledger, scope):
    run_id = await _started(ledger, scope)
    for column, value in (("spec_hash", _hash()), ("code_commit", _commit())):
        with pytest.raises(asyncpg.PostgresError, match="append-only"):
            await _execute(
                f"UPDATE research_run SET {column} = $2, status = 'completed', "
                "finished_at = now() WHERE run_id = $1::uuid",
                run_id,
                value,
            )
    await _execute(
        "UPDATE research_run SET snapshot_hash = 'first', status = 'completed', "
        "finished_at = now() WHERE run_id = $1::uuid",
        run_id,
    )
    with pytest.raises(asyncpg.PostgresError, match="append-only"):
        await _execute(
            "UPDATE research_run SET snapshot_hash = 'second' WHERE run_id = $1::uuid", run_id
        )
    assert (await _row(run_id))["snapshot_hash"] == "first"


async def test_trigger_insert_must_be_started(ledger, scope):
    run_id = await _started(ledger, scope)
    row = await _row(run_id)
    with pytest.raises(asyncpg.PostgresError, match="append-only"):
        await _execute(
            "INSERT INTO research_run (run_group, concept_id, kind, mode, spec_path, spec_hash, "
            "spec_blob, code_commit, vintage, status) VALUES ($1, $2, 'evidence', 'real', 'x', "
            "$3, 'x', $4, $5, 'completed')",
            uuid4(),
            row["concept_id"],
            _hash(),
            row["code_commit"],
            row["vintage"],
        )


async def test_trigger_delete_and_truncate_rejected(ledger, scope):
    run_id = await _started(ledger, scope)
    with pytest.raises(asyncpg.PostgresError, match="append-only"):
        await _execute("DELETE FROM research_run WHERE run_id = $1::uuid", run_id)
    # Since migration 515 the research_run_series FK refuses a plain TRUNCATE first; CASCADE
    # reaches the append-only triggers of both tables.
    with pytest.raises(asyncpg.PostgresError, match="foreign key"):
        await _execute("TRUNCATE research_run")
    with pytest.raises(asyncpg.PostgresError, match="append-only"):
        await _execute("TRUNCATE research_run CASCADE")
    assert (await _row(run_id)) is not None


async def test_budget_charge_rules(ledger, scope):
    vintage = _name()
    for final in ("refused", "guard_failed"):
        run_id = await _started(ledger, scope, "book_test", vintage=vintage)
        await ledger.finish_run(run_id, status=final, snapshot_hash=None, evidence={})
    await _started(ledger, scope, "evidence", vintage=vintage)
    assert await ledger.charged_book_tests(vintage) == 0

    await _started(ledger, scope, "book_test", vintage=vintage)  # left started: charged
    for final in ("completed", "failed"):
        run_id = await _started(ledger, scope, "book_test", vintage=vintage)
        await ledger.finish_run(run_id, status=final, snapshot_hash=None, evidence={})
    assert await ledger.charged_book_tests(vintage) == 3
    # E18 (phase 187 plan 06): past M the attempt is recorded, never refused; StepM prices it.
    await _started(ledger, scope, "book_test", vintage=vintage)
    assert await ledger.charged_book_tests(vintage) == 4


async def test_exploration_may_repeat_a_spec_real_may_not(ledger, scope):
    ids, members = scope.identities()
    request = scope.request()
    await ledger.start_runs(request, ids, [members[0]])
    with pytest.raises(LedgerRefusal, match="already run"):
        await ledger.start_runs(request, ids, [members[0]])
    explore = dataclasses.replace(request, mode="exploration")
    first = await ledger.start_runs(explore, ids, [members[0]])
    second = await ledger.start_runs(explore, ids, [members[0]])
    assert first != second
    assert (await _row(first[members[0]]))["mode"] == "exploration"


async def test_an_explored_spec_cannot_take_its_real_run(ledger, scope):
    """A spec searched in exploration is not unlooked: its one real run is refused."""
    ids, members = scope.identities()
    real = scope.request()
    await ledger.start_runs(dataclasses.replace(real, mode="exploration"), ids, [members[0]])
    assert await ledger.has_real_run(real.spec_hash)
    with pytest.raises(LedgerRefusal, match="already run"):
        await ledger.start_runs(real, ids, [members[0]])


async def test_budget_apr_keys_seeded():
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        rows = dict(
            await conn.fetch(
                "SELECT config_key, config_value FROM config_state WHERE config_key = ANY($1)",
                [
                    "alpha.research.vintage_id",
                    "alpha.research.budget_m",
                    "alpha.research.screen_alpha",
                    "infra.research_runner.workers",
                ],
            )
        )
    finally:
        await conn.close()
    assert rows == {
        "alpha.research.vintage_id": "vintage_1",
        "alpha.research.budget_m": "30",
        "alpha.research.screen_alpha": "0.05",
        "infra.research_runner.workers": "8",
    }


async def test_identity_rows_and_edges(ledger, scope):
    ids, members = scope.identities(n_members=2)
    await ledger.start_runs(scope.request(), ids, members)
    await ledger.start_runs(scope.request(), ids, members)  # new spec hash, same identities
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        rows = await conn.fetch(
            "SELECT concept_id, status, enabled, added_phase FROM concept_registry "
            "WHERE domain = ANY(ARRAY['family','member','combiner','construction_rule','book']) "
            "AND name = ANY($1::text[])",
            [i.name for i in ids],
        )
        edges = await conn.fetchval(
            "SELECT count(*) FROM concept_parent WHERE child_concept_id = ANY($1::uuid[])",
            [r["concept_id"] for r in rows],
        )
    finally:
        await conn.close()
    assert len(rows) == 3
    assert {(r["status"], r["enabled"], r["added_phase"]) for r in rows} == {
        ("candidate", False, "183")
    }
    assert edges == 2


async def test_evidence_roundtrip(ledger, scope):
    run_id = await _started(ledger, scope)
    evidence = {
        "estimate": np.float64(0.2),
        "per_period": np.array([0.1, np.nan]),
        "n": np.int64(7),
    }
    await ledger.finish_run(run_id, status="completed", snapshot_hash="h", evidence=evidence)
    stored = (await _row(run_id))["evidence"]
    assert stored == {"estimate": 0.2, "per_period": [0.1, None], "n": 7}
    json.dumps(stored, allow_nan=False)


async def test_finish_run_unserializable_writes_failed(ledger, scope):
    run_id = await _started(ledger, scope)
    with pytest.raises(TypeError):
        await ledger.finish_run(
            run_id, status="completed", snapshot_hash=None, evidence={"x": object()}
        )
    row = await _row(run_id)
    assert row["status"] == "failed"
    assert "error" in row["evidence"]


_SESSIONS = np.array(["2020-01-02", "2020-01-03", "2020-01-06"], dtype="datetime64[D]")
_DECISION = {
    "decision": {
        "t": 2.0,
        "p": 0.04,
        "annualized_sharpe": 0.5,
        "n_sessions": 2,
        "mean_session_pnl": 0.001,
    },
    "turnover_per_session": 1.5,
}


async def _series(run_id: str):
    conn = await connect_with_codecs(_TEST_DB_URL)
    try:
        return await conn.fetchrow(
            "SELECT sessions, d_s FROM research_run_series WHERE run_id = $1::uuid", run_id
        )
    finally:
        await conn.close()


async def test_completed_run_writes_series_and_headline(ledger, scope):
    """Migration 515 / plan 187-02: the series and headline land with the terminal row."""
    ids, members = scope.identities()
    started = await ledger.start_runs(scope.request(), ids, [members[0]])
    run_id = started[members[0]]
    series = AttemptSeries.from_timing(_SESSIONS, np.array([0.1, np.nan, -0.05]))
    await ledger.finish_run(
        run_id, status="completed", snapshot_hash=None, evidence=_DECISION, series=series
    )
    row = await _row(run_id)
    assert (row["decision_t"], row["n_sessions"], row["turnover_per_session"]) == (2.0, 2, 1.5)
    assert (row["span_start"].isoformat(), row["span_end"].isoformat()) == (
        "2020-01-02",
        "2020-01-06",
    )
    stored = await _series(run_id)
    assert [d.isoformat() for d in stored["sessions"]] == ["2020-01-02", "2020-01-06"]
    assert list(stored["d_s"]) == [0.1, -0.05]


async def test_refused_run_writes_no_series(ledger, scope):
    ids, members = scope.identities()
    started = await ledger.start_runs(scope.request(), ids, [members[0]])
    run_id = started[members[0]]
    series = AttemptSeries.from_timing(_SESSIONS, np.array([0.1, 0.2, 0.3]))
    await ledger.finish_run(
        run_id, status="refused", snapshot_hash=None, evidence={"stage": "S3"}, series=series
    )
    assert await _series(run_id) is None
    assert (await _row(run_id))["decision_t"] is None


async def test_a_pod_run_sums_pinned_member_series_through_s6(ledger, scope, tmp_path):
    """Plan 187-10: two completed book tests with series, then a pod pinned to them. The pod's
    stored series is the sum on the common sessions, every headline column is set, and the
    spec-once rule refuses a second real pod run of the same hash."""
    from src.intelligence.research.pod import run_pod, series_sha256
    from src.intelligence.research.runner import BudgetConfig, RunContext, RunRefused
    from tests.unit.research.test_pod_book import A, B, _pod_repo

    vintage = _name()
    scope.vintages.append(vintage)
    pins = [("a", str(uuid4()), series_sha256(A)), ("b", str(uuid4()), series_sha256(B))]
    probe = _pod_repo(tmp_path / "probe", pins)  # the member spec hashes, before the run ids
    run_ids = []
    for book, series in zip(probe.books, (A, B), strict=True):
        name = f"book.{book.model.book}"
        scope.names.append(name)
        request = dataclasses.replace(
            scope.request("book_test", vintage=vintage), spec_hash=book.spec_hash
        )
        started = await ledger.start_runs(request, [Identity(name, "book", "test book")], [name])
        run_id = started[name]
        evidence = {
            "decision": {**_DECISION["decision"], "statistic": "hac_timing_t_e17"},
            "power": {"powered": True},
            "turnover_per_session": 0.5,
        }
        await ledger.finish_run(
            run_id, status="completed", snapshot_hash=None, evidence=evidence, series=series
        )
        run_ids.append(run_id)
    pinned = await ledger.pinned_run(run_ids[0])
    assert series_sha256(pinned.series) == pins[0][2]

    pins = [(x, r, h) for (x, _, h), r in zip(pins, run_ids, strict=True)]
    loaded = _pod_repo(tmp_path / "pod", pins)
    scope.names.append("pod.pod_one")
    ctx = RunContext(root=tmp_path / "pod", budget=BudgetConfig(vintage, 1, 0.05), ledger=ledger)
    result = await run_pod(loaded, ctx, mode="real")
    row = await _row(result["run_id"])
    assert row["kind"] == "pod_book" and row["status"] == "completed"
    headline = ("decision_t", "decision_p", "gross_sharpe", "mean_session_pnl")
    assert all(row[c] is not None for c in (*headline, "turnover_per_session", "n_sessions"))
    stored = await _series(result["run_id"])
    assert [d.isoformat() for d in stored["sessions"]] == ["2024-01-03", "2024-01-05", "2024-01-08"]
    assert list(stored["d_s"]) == [2.5, 2.0, 4.25]
    with pytest.raises(RunRefused, match="already run"):
        await run_pod(loaded, ctx, mode="real")


# Plan 187-11: typed domains, recipe versions, informed_by.


def _recipe(name: str, **over):
    from src.intelligence.research.recipe import RecipeContent

    base = dict(
        concept=name,
        code_pointer="some.module:fn",
        params={"window": 5},
        apr_values={},
        inputs=(),
        universe_selector=None,
        cvr_codes={"research_timeframe": "15m"},
        mechanism="mechanism",
        sources=("docs/x.md",),
    )
    return RecipeContent(**{**base, **over})


async def _recipes(name: str) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        return await conn.fetch(
            "SELECT r.version, r.recipe_hash, r.code_commit, r.author FROM concept_recipe r "
            "JOIN concept_registry c USING (concept_id) WHERE c.name = $1 ORDER BY r.version",
            name,
        )
    finally:
        await conn.close()


async def test_identities_land_in_typed_domains(ledger, scope):
    names = {
        k: _name() for k in ("family", "member", "combiner", "construction_rule", "book", "pod")
    }
    scope.names += list(names.values())
    ids = [Identity(n, k, "typed") for k, n in names.items()]
    await ledger.start_runs(scope.request(), ids, [names["member"]])
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        rows = await conn.fetch(
            "SELECT name, domain, metadata ->> 'kind' AS kind FROM concept_registry "
            "WHERE name = ANY($1::text[])",
            list(names.values()),
        )
    finally:
        await conn.close()
    got = {r["name"]: (r["domain"], r["kind"]) for r in rows}
    assert got[names["pod"]] == ("book", "pod")  # a pod is a book
    assert got[names["book"]] == ("book", "book")
    for kind in ("family", "member", "combiner", "construction_rule"):
        assert got[names[kind]] == (kind, kind)


async def test_first_run_writes_version_1_and_the_run_points_at_its_recipe(ledger, scope):
    ids, members = scope.identities()
    family = ids[0].name
    recipes = {family: _recipe(family), members[0]: _recipe(members[0], params={"window": 1})}
    request = scope.request(recipes=recipes, author="tester")
    run_id = (await ledger.start_runs(request, ids, [members[0]]))[members[0]]
    for name, recipe in recipes.items():
        (row,) = await _recipes(name)
        assert (row["version"], row["recipe_hash"]) == (1, recipe.recipe_hash)
        assert (row["code_commit"], row["author"]) == (request.code_commit, "tester")
    assert (await _row(run_id))["recipe_hash"] == recipes[members[0]].recipe_hash


async def test_a_changed_definition_adds_a_version_for_that_concept_only(ledger, scope):
    ids, members = scope.identities(2)
    family = ids[0].name
    first = {n: _recipe(n) for n in (family, *members)}
    await ledger.start_runs(scope.request(recipes=first), ids, [members[0]])
    changed = {**first, members[0]: _recipe(members[0], params={"window": 6})}
    request = scope.request(recipes=changed, mode="exploration")
    second_commit = _commit()
    request = dataclasses.replace(request, code_commit=second_commit)
    run_id = (await ledger.start_runs(request, ids, [members[0]]))[members[0]]
    assert [r["version"] for r in await _recipes(members[0])] == [1, 2]
    assert [r["version"] for r in await _recipes(members[1])] == [1]
    assert [r["version"] for r in await _recipes(family)] == [1]
    row = await _row(run_id)
    assert row["recipe_hash"] == changed[members[0]].recipe_hash
    # The unchanged member's recipe keeps the commit that first recorded it; the attempt records
    # the code behind it.
    (unchanged,) = await _recipes(members[1])
    assert unchanged["code_commit"] != second_commit and row["code_commit"] == second_commit


async def test_an_existing_idea_row_is_adopted_not_duplicated(ledger, scope):
    name = _name()
    scope.names.append(name)
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        await conn.execute(
            "INSERT INTO concept_registry (domain, name, description, status, enabled, metadata, "
            "added_phase) VALUES ('member', $1, 'an idea', 'candidate', false, '{}'::jsonb, '187')",
            name,
        )
    finally:
        await conn.close()
    request = scope.request(recipes={name: _recipe(name)})
    await ledger.start_runs(request, [Identity(name, "member", "again")], [name])
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        assert (
            await conn.fetchval("SELECT count(*) FROM concept_registry WHERE name = $1", name) == 1
        )
    finally:
        await conn.close()
    assert len(await _recipes(name)) == 1


async def test_an_unregistered_cvr_code_writes_nothing(ledger, scope):
    ids, members = scope.identities()
    bad = {members[0]: _recipe(members[0], cvr_codes={"research_timeframe": "4h"})}
    with pytest.raises(LedgerRefusal, match="4h"):
        await ledger.start_runs(scope.request(recipes=bad), ids, [members[0]])
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        assert not await conn.fetchval(
            "SELECT count(*) FROM concept_registry WHERE name = ANY($1::text[])",
            [i.name for i in ids],
        )
    finally:
        await conn.close()


async def test_informed_by_names_a_terminal_run(ledger, scope):
    run_id = await _started(ledger, scope)
    ids, members = scope.identities()
    with pytest.raises(LedgerRefusal, match="not a terminal"):
        await ledger.start_runs(scope.request(informed_by=run_id), ids, [members[0]])
    await ledger.finish_run(run_id, status="refused", snapshot_hash=None, evidence={})
    informed = (await ledger.start_runs(scope.request(informed_by=run_id), ids, [members[0]]))[
        members[0]
    ]
    assert str((await _row(informed))["informed_by"]) == run_id


# The research stage view (migration 530): one test per branch of the precedence.


async def _stage(name: str) -> str:
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        return await conn.fetchval("SELECT stage FROM concept_research_stage WHERE name = $1", name)
    finally:
        await conn.close()


async def _set_status(name: str, status: str) -> None:
    await _execute("UPDATE concept_registry SET status = $2 WHERE name = $1", name, status)


async def _run_for(ledger, scope, kind: str, status: str | None, **recipe_over) -> str:
    """A concept of `kind` with a recipe and one attempt finished as `status` (None: left
    started); returns the concept name."""
    name = _name()
    scope.names.append(name)
    request = scope.request(recipes={name: _recipe(name, **recipe_over)})
    run_id = (await ledger.start_runs(request, [Identity(name, kind, "stage")], [name]))[name]
    if status is not None:
        await ledger.finish_run(run_id, status=status, snapshot_hash=None, evidence={})
    return name


async def test_stage_idea_specified_registered_tested(ledger, scope):
    idea = _name()
    scope.names.append(idea)
    await _execute(
        "INSERT INTO concept_registry (domain, name, description, status, enabled, metadata, "
        "added_phase) VALUES ('family', $1, 'idea', 'candidate', false, '{}'::jsonb, '187')",
        idea,
    )
    assert await _stage(idea) == "idea"

    # A recipe and no attempt: specified.
    runner, specified = _name(), _name()
    scope.names += [runner, specified]
    request = scope.request(recipes={runner: _recipe(runner), specified: _recipe(specified)})
    ids = [Identity(runner, "member", "r"), Identity(specified, "member", "s")]
    await ledger.start_runs(request, ids, [runner])
    assert await _stage(specified) == "specified"
    assert await _stage(runner) == "registered"  # its attempt is still started

    tested = await _run_for(ledger, scope, "member", "completed")
    assert await _stage(tested) == "tested"


async def test_stage_refused_attempt_then_a_newer_recipe_reopens_it(ledger, scope):
    name = await _run_for(ledger, scope, "member", "refused")
    assert await _stage(name) == "refused"
    other = _name()
    scope.names.append(other)
    request = scope.request(
        recipes={other: _recipe(other), name: _recipe(name, params={"window": 99})}
    )
    ids = [Identity(other, "member", "o"), Identity(name, "member", "again")]
    await ledger.start_runs(request, ids, [other])
    assert await _stage(name) == "specified"


async def test_stage_deprecated_beats_a_tested_attempt(ledger, scope):
    name = await _run_for(ledger, scope, "member", "completed")
    await _set_status(name, "deprecated")
    assert await _stage(name) == "refused"


async def test_stage_a_book_is_frozen_or_confirmed_by_its_status(ledger, scope):
    name = await _run_for(ledger, scope, "book", "completed")
    assert await _stage(name) == "tested"
    await _set_status(name, "shadow_only")
    assert await _stage(name) == "frozen"
    await _set_status(name, "active")
    assert await _stage(name) == "confirmed"
    # Only a book is promoted: a member with the same status stays tested.
    member = await _run_for(ledger, scope, "member", "completed")
    await _set_status(member, "active")
    assert await _stage(member) == "tested"


async def test_stage_legacy_verdicts_alone_are_refused_until_a_recipe_reopens_them(ledger, scope):
    name = _name()
    scope.names.append(name)
    vintage = _name()
    scope.vintages.append(vintage)
    await _execute(
        "INSERT INTO concept_registry (domain, name, description, status, enabled, metadata, "
        "added_phase) VALUES ('family', $1, 'old verdict', 'candidate', false, '{}'::jsonb, '187')",
        name,
    )
    conn = await asyncpg.connect(_TEST_DB_URL)
    try:
        async with conn.transaction():
            await conn.execute("ALTER TABLE research_run DISABLE TRIGGER USER")
            await conn.execute(
                "INSERT INTO research_run (run_group, concept_id, kind, mode, spec_path, spec_hash, "
                "spec_blob, code_commit, vintage, status) SELECT gen_random_uuid(), concept_id, "
                "'legacy_verdict', 'real', 'docs/x.md', $2, 'b', $3, $4, 'completed' "
                "FROM concept_registry WHERE name = $1",
                name,
                _hash(),
                _commit(),
                vintage,
            )
            await conn.execute("ALTER TABLE research_run ENABLE TRIGGER USER")
    finally:
        await conn.close()
    assert await _stage(name) == "refused"
    other = _name()
    scope.names.append(other)
    request = scope.request(recipes={other: _recipe(other), name: _recipe(name)})
    ids = [Identity(other, "member", "o"), Identity(name, "family", "reopened")]
    await ledger.start_runs(request, ids, [other])
    assert await _stage(name) == "specified"
