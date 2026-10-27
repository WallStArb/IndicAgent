"""The daily residual family's members' universe (prereg 2026-10-27 section 2, B1)."""

import asyncio
import datetime
import hashlib

import pytest

from src.intelligence.research import snapshot

CUTOFF = datetime.datetime(2026, 9, 13, tzinfo=datetime.UTC)


class _Pool:
    def __init__(self, seen, names):
        self.seen, self.names, self.calls = seen, names, []

    async def fetch(self, sql, *args):
        self.calls.append(args)
        rows = self.seen if "created_at < $1" in sql else self.names
        return [{"symbol": s} for s in rows]

    async def close(self):
        pass


def _run(monkeypatch, pool, seen_hash):
    async def fake(dsn):
        return pool

    monkeypatch.setattr(snapshot, "read_only_pool", fake)
    monkeypatch.setattr(snapshot, "DAILY_SEEN_BEFORE_CUTOFF_SHA256", seen_hash)
    return asyncio.run(snapshot.daily_unseen_symbols("postgresql://unused"))


def _sha(names):
    return hashlib.sha256("\n".join(names).encode()).hexdigest()


def test_returns_the_unseen_names_on_the_utc_cutoff(monkeypatch):
    pool = _Pool(["OLD1", "OLD2"], ["A", "B"])
    assert _run(monkeypatch, pool, _sha(["OLD1", "OLD2"])) == ["A", "B"]
    assert pool.calls == [(CUTOFF,), (CUTOFF, list(snapshot.DAILY_SEEN_SLEEVE))]


def test_refuses_when_the_seen_set_no_longer_reproduces(monkeypatch):
    with pytest.raises(ValueError, match="not the pinned set"):
        _run(monkeypatch, _Pool(["OLD1"], ["A"]), _sha(["OLD1", "OLD2"]))


def test_the_seen_sleeve_matches_the_tsmom_harness():
    from scripts.research.determinism.config import HarnessConfig

    assert set(snapshot.DAILY_SEEN_SLEEVE) == set(HarnessConfig().sleeve)
