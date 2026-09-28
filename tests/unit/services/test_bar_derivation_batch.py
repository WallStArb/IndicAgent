"""Tests for services/bar_derivation_batch.py (phase 185 plan 04, task 3).

Fakes only, no DB: the helpers' contract is the SQL shape (one short
transaction per write, SET LOCAL ROLE bar_derivation_writer first), the
close_batch status guard, and current_code_commit's dirty suffix.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager

from services import bar_derivation_batch as bdb


class FakeAsyncConn:
    """asyncpg-shaped fake recording every statement in order."""

    def __init__(self, fetchval_result="batch-uuid-1"):
        self.statements: list[tuple] = []
        self._fetchval_result = fetchval_result

    class _Txn:
        def __init__(self, outer):
            self.outer = outer

        async def __aenter__(self):
            self.outer.statements.append(("<begin>",))

        async def __aexit__(self, *exc):
            self.outer.statements.append(("<commit>",))

    def transaction(self):
        return self._Txn(self)

    async def execute(self, sql, *args):
        self.statements.append((sql, args))

    async def fetchval(self, sql, *args):
        self.statements.append((sql, args))
        return self._fetchval_result


class FakeSyncConn:
    """psycopg-shaped fake recording every statement in order."""

    def __init__(self, fetchone_result=("batch-uuid-2",)):
        self.statements: list[tuple] = []
        self._fetchone_result = fetchone_result

    @contextmanager
    def transaction(self):
        self.statements.append(("<begin>",))
        yield
        self.statements.append(("<commit>",))

    def execute(self, sql, params=()):
        self.statements.append((sql, tuple(params)))
        return self  # .fetchone below

    def fetchone(self):
        return self._fetchone_result


def _first_sql(conn) -> str:
    return conn.statements[1][0]  # index 0 is <begin>


def test_open_batch_returns_uuid_under_writer_role() -> None:
    conn = FakeAsyncConn()
    batch_id = asyncio.run(
        bdb.open_batch(
            conn,
            stage="scrub",
            rule_version="v1",
            apr_snapshot={"threshold.bar_scrub.jump_sigma": 8.0},
            n_symbols=50,
        )
    )
    assert batch_id == "batch-uuid-1"
    assert _first_sql(conn) == "SET LOCAL ROLE bar_derivation_writer"
    insert = conn.statements[2]
    assert "INSERT INTO bar_derivation_batch" in insert[0]
    assert "gen_random_uuid()" in insert[0]
    assert "'running'" in insert[0]
    assert insert[1][0] == "scrub" and insert[1][1] == "v1"


def test_open_batch_embeds_current_code_commit() -> None:
    conn = FakeAsyncConn()
    asyncio.run(
        bdb.open_batch(conn, stage="legacy", rule_version="legacy", apr_snapshot={}, n_symbols=None)
    )
    assert conn.statements[2][1][2] == bdb.current_code_commit()


def test_close_batch_completed_and_failed_update_row() -> None:
    for status in ("completed", "failed"):
        conn = FakeAsyncConn()
        asyncio.run(bdb.close_batch(conn, "batch-uuid-1", status=status))
        assert _first_sql(conn) == "SET LOCAL ROLE bar_derivation_writer"
        update = conn.statements[2]
        assert "UPDATE bar_derivation_batch" in update[0]
        assert "finished_at" in update[0]
        assert update[1][1] == status


def test_close_batch_unknown_status_raises_before_sql() -> None:
    conn = FakeAsyncConn()
    try:
        asyncio.run(bdb.close_batch(conn, "batch-uuid-1", status="cancelled"))
    except ValueError as error:
        assert "cancelled" in str(error)
    else:
        raise AssertionError("expected ValueError")
    assert conn.statements == []  # guard fires before any statement


def test_sync_twins_same_contract() -> None:
    conn = FakeSyncConn()
    batch_id = bdb.open_batch_sync(
        conn, stage="grid", rule_version="v2", apr_snapshot={}, n_symbols=None
    )
    assert batch_id == "batch-uuid-2"
    assert _first_sql(conn) == "SET LOCAL ROLE bar_derivation_writer"
    for status in ("completed", "failed"):
        conn2 = FakeSyncConn()
        bdb.close_batch_sync(conn2, "batch-uuid-2", status=status)
        assert _first_sql(conn2) == "SET LOCAL ROLE bar_derivation_writer"
        assert "UPDATE bar_derivation_batch" in conn2.statements[2][0]


def _fake_git(monkeypatch, head: str, porcelain: str) -> None:
    class Result:
        def __init__(self, out: str):
            self.stdout = out

    def fake_run(args, **kwargs):
        assert args[0] == "git"
        if args[1] == "rev-parse":
            return Result(head + "\n")
        if args[1] == "status":
            return Result(porcelain)
        raise AssertionError(f"unexpected git call {args}")

    monkeypatch.setattr(bdb.subprocess, "run", fake_run)


def test_current_code_commit_clean_tree(monkeypatch) -> None:
    _fake_git(monkeypatch, "abc1234", "")
    assert bdb.current_code_commit() == "abc1234"


def test_current_code_commit_dirty_only_on_tracked_changes(monkeypatch) -> None:
    _fake_git(monkeypatch, "abc1234", " M services/foo.py\n?? scratch.txt\n")
    assert bdb.current_code_commit() == "abc1234-dirty"


def test_current_code_commit_untracked_alone_is_clean(monkeypatch) -> None:
    _fake_git(monkeypatch, "abc1234", "?? scratch.txt\n")
    assert bdb.current_code_commit() == "abc1234"
