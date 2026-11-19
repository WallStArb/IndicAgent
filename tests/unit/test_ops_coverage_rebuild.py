"""The coverage ledger rebuild wrapper: lock first, writer role, one commit, loud on a held lock."""

from __future__ import annotations

import pytest

from scripts.infrastructure.backfill._fetcher_lock import FetcherLockHeld
from scripts.ops.bars import ops_coverage_rebuild
from scripts.ops.bars.ops_coverage_rebuild import rebuild_ledger

_STALE = ("AAA", "5m", "ibkr", None, None, 10, None)
_FRESH = ("AAA", "5m", "ibkr", None, None, 0, None)


class _Lock:
    def __init__(self, events: list[str], *, held: bool = False) -> None:
        self._events, self._held = events, held

    def hold_or_refuse(self) -> None:
        if self._held:
            raise FetcherLockHeld("held")
        self._events.append("lock")

    def release(self) -> None:
        self._events.append("unlock")


class _Cursor:
    def __init__(self, events: list[str]) -> None:
        self._events, self._reads = events, 0

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str) -> None:
        self._events.append("read" if sql.lstrip().startswith("SELECT") else sql)

    def fetchall(self) -> list[tuple]:
        self._reads += 1
        return [_STALE] if self._reads == 1 else [_FRESH]


class _Conn:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def cursor(self) -> _Cursor:
        return _Cursor(self._events)

    def commit(self) -> None:
        self._events.append("commit")

    def rollback(self) -> None:
        self._events.append("rollback")

    def close(self) -> None:
        self._events.append("close")


def _run(events: list[str], *, apply: bool, held: bool = False, fail: bool = False):
    def rebuild(cur: _Cursor) -> int:
        events.append("rebuild")
        if fail:
            raise RuntimeError("boom")
        return 1

    def connect(dsn: str, **kwargs: object) -> _Conn:
        assert not kwargs, "an autocommit connection would break SET LOCAL ROLE and the rollback"
        return _Conn(events)

    return rebuild_ledger(
        "dsn",
        apply=apply,
        lock_factory=lambda dsn, holder: _Lock(events, held=held),
        connect=connect,
        rebuild=rebuild,
    )


def test_apply_locks_sets_the_writer_role_rebuilds_commits_once_and_unlocks_last():
    events: list[str] = []
    assert _run(events, apply=True) == {"ibkr": 1}
    assert events == [
        "lock",
        "read",
        "SET LOCAL ROLE bar_derivation_writer",
        "rebuild",
        "read",
        "commit",
        "close",
        "unlock",
    ]


def test_a_dry_run_reports_the_drift_and_rolls_back_without_committing():
    events: list[str] = []
    assert _run(events, apply=False) == {"ibkr": 1}
    assert "commit" not in events and events.count("rollback") >= 1


def test_a_held_lock_raises_before_any_connection_and_writes_nothing():
    events: list[str] = []
    with pytest.raises(FetcherLockHeld):
        _run(events, apply=True, held=True)
    assert events == []


def test_a_rebuild_failure_rolls_back_never_commits_and_still_unlocks():
    events: list[str] = []
    with pytest.raises(RuntimeError):
        _run(events, apply=True, fail=True)
    assert "commit" not in events and events[-1] == "unlock" and "rollback" in events


def test_main_exits_1_when_the_fetcher_lock_is_held_and_never_reports_success(monkeypatch):
    def held(dsn: str, *, apply: bool):
        raise FetcherLockHeld("held")

    monkeypatch.setattr(ops_coverage_rebuild, "setup_service_logging", lambda *_: None)
    monkeypatch.setattr(ops_coverage_rebuild, "running_writers", lambda: [])
    monkeypatch.setattr(ops_coverage_rebuild, "rebuild_ledger", held)
    assert ops_coverage_rebuild.main(["--apply"]) == 1


def test_main_refuses_while_a_ledger_writer_runs_without_touching_the_database(monkeypatch):
    def never(dsn: str, *, apply: bool):
        raise AssertionError("rebuild must not start while a writer runs")

    monkeypatch.setattr(ops_coverage_rebuild, "setup_service_logging", lambda *_: None)
    monkeypatch.setattr(
        ops_coverage_rebuild, "running_writers", lambda: ["indicagent-alpaca-nightly.service"]
    )
    monkeypatch.setattr(ops_coverage_rebuild, "rebuild_ledger", never)
    assert ops_coverage_rebuild.main(["--apply"]) == 1
