"""`PostgresLedger.record_sweep_block` (E21, ledger 2026-11-24i): one transaction per block, a
refusal before any write, the feature-domain lookup, completed or failed by the series. The
SQL itself runs against the database in tests/integration/test_research_ledger.py."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import numpy as np
import pytest

from src.intelligence.research import ledger as ledger_module
from src.intelligence.research.ledger import (
    AttemptSeries,
    LedgerRefusal,
    PostgresLedger,
    RunRequest,
)


class _Transaction:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        self.conn.transactions += 1

    async def __aexit__(self, *exc):
        self.conn.committed = exc[0] is None
        return False


class FakeConn:
    def __init__(self, prior=False, known=("f1", "f2")):
        self.prior, self.known = prior, set(known)
        self.transactions, self.committed, self.closed = 0, None, False
        self.inserted: list = []
        self.updates: list = []
        self.series: list = []
        self.lookups: list = []

    def transaction(self):
        return _Transaction(self)

    async def fetchval(self, sql, *args):
        if sql.startswith("SELECT EXISTS"):
            return self.prior
        if "FROM concept_registry" in sql:
            self.lookups.append((tuple(args[0]), args[1]))
            return uuid4() if args[1] in self.known else None
        if sql.startswith("INSERT INTO research_run"):
            self.inserted.append(args)
            return uuid4()
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        if sql.startswith("SELECT pg_advisory"):
            return "SELECT 1"
        if sql.startswith("UPDATE research_run"):
            self.updates.append((args[1], args))  # status
            return "UPDATE 1"
        if sql.startswith("INSERT INTO research_run_series"):
            self.series.append(args)
            return "INSERT 0 1"
        raise AssertionError(sql)

    async def close(self):
        self.closed = True


def _request(**overrides):
    base = dict(
        kind="evidence",
        spec_path="research/sweeps/x.yaml",
        spec_hash="a" * 64,
        spec_blob="b",
        code_commit="0" * 40,
        vintage="test",
    )
    return RunRequest(**{**base, **overrides})


def _series(n=5):
    return AttemptSeries(
        sessions=np.array([f"2020-01-0{i + 1}" for i in range(n)], dtype="datetime64[D]"),
        values=np.linspace(-0.01, 0.02, n),
    )


@pytest.fixture
def conn(monkeypatch):
    fake = FakeConn()

    async def connect(_dsn):
        return fake

    monkeypatch.setattr(ledger_module, "connect_with_codecs", connect)
    return fake


def _record(request, cells):
    return asyncio.run(PostgresLedger("dsn").record_sweep_block(request, cells))


def test_one_transaction_one_row_per_cell_completed_or_failed(conn):
    ids = _record(
        _request(), {"f1": (_series(), {"cell": {"feature": "f1"}}), "f2": (None, {"cell": {}})}
    )
    assert set(ids) == {"f1", "f2"}
    assert conn.transactions == 1 and conn.committed and conn.closed
    assert [u[0] for u in conn.updates] == ["completed", "failed"]
    assert len(conn.series) == 1  # only the completed cell stores a series
    assert all(domains == ("feature",) for domains, _ in conn.lookups)


def test_prior_run_of_the_spec_refuses_before_any_write(conn):
    conn.prior = True
    with pytest.raises(LedgerRefusal, match="spec already run"):
        _record(_request(), {"f1": (_series(), {})})
    assert not conn.inserted and not conn.updates and not conn.committed


def test_unknown_feature_aborts_the_whole_block(conn):
    with pytest.raises(LedgerRefusal, match="unknown feature identity: nope"):
        _record(_request(), {"f1": (_series(), {}), "nope": (_series(), {})})
    assert conn.committed is False  # the transaction context saw the exception: rolled back


@pytest.mark.parametrize("override", [{"kind": "book_test"}, {"mode": "exploration"}])
def test_only_real_evidence_runs_are_sweep_blocks(conn, override):
    with pytest.raises(ValueError, match="real-mode evidence"):
        _record(_request(**override), {"f1": (_series(), {})})
    assert conn.transactions == 0


def test_empty_block_and_unserializable_payload_refuse_before_connecting(conn):
    with pytest.raises(ValueError, match="at least one cell"):
        _record(_request(), {})
    with pytest.raises(TypeError):
        _record(_request(), {"f1": (_series(), {"x": object()})})
    assert conn.transactions == 0
