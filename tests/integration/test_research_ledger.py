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
                    "WHERE domain = 'construction' AND name = ANY($1::text[])",
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
            "WHERE domain = 'construction' AND name = ANY($1::text[])",
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
