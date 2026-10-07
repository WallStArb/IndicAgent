"""Plan 185-22 (D-21): ops_split_detect records, re-fetches and re-derives, in that order.

Against a fake connection and injected collaborators; nothing touches IBKR or the database.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date

import pytest

from scripts.ops.bars import ops_split_detect as ops
from services.split_detection import DetectedSplit

_EVIDENCE = ("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222")


def _split(symbol="XYZ", factor=3.0, day=date(2026, 9, 30), unexplained=False, ids=_EVIDENCE):
    return DetectedSplit(symbol, day, factor, ids, unexplained)


class FakeConn:
    def __init__(self, existing=()):
        self.existing = list(existing)  # [(action_id, factor)]
        self.executed: list[tuple[str, tuple]] = []

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql, *args):
        self.executed.append((" ".join(sql.split()), args))

    async def fetch(self, sql, *args):
        return self.existing


def _record(conn, split):
    return asyncio.run(ops.record_split(conn, split))


def test_a_new_split_is_inserted_under_the_writer_role_with_its_evidence():
    conn = FakeConn()
    assert _record(conn, _split()) is True
    role, insert = conn.executed
    assert role[0] == "SET LOCAL ROLE bar_derivation_writer"
    sql, args = insert
    assert "INSERT INTO corporate_action" in sql and "'nightly_overlap'" in sql
    assert args[:4] == ("XYZ", "split", date(2026, 9, 30), 3.0)
    assert args[4] == list(_EVIDENCE) and args[6] is None


def test_a_reverse_split_is_typed_as_one():
    conn = FakeConn()
    _record(conn, _split(factor=0.125))
    assert conn.executed[1][1][1] == "reverse_split"


def test_the_same_factor_is_not_recorded_twice():
    conn = FakeConn(existing=[("aaaa", 3.0)])
    assert _record(conn, _split()) is False
    assert [sql for sql, _ in conn.executed if sql.startswith("INSERT")] == []


def test_a_different_factor_on_the_same_date_supersedes_the_earlier_row():
    conn = FakeConn(existing=[("aaaa", 2.0)])
    assert _record(conn, _split(factor=3.0)) is True
    assert conn.executed[1][1][6] == "aaaa"


def test_a_split_without_evidence_is_refused():
    with pytest.raises(ValueError, match="evidence"):
        _record(FakeConn(), _split(ids=()))


def _process(conn, detected, **calls):
    async def fake_detect(c, **kw):
        return detected

    original = ops.detect_overlap_splits
    ops.detect_overlap_splits = fake_detect
    try:
        return asyncio.run(
            ops.process(
                conn,
                ["run-1"],
                rel_tol=0.002,
                min_run=5,
                ratio_snap_tol=0.01,
                refetch=calls.get("refetch", lambda s: 0),
                derive=calls.get("derive", lambda s: 0),
                report_unexplained=calls.get("report", lambda s: None),
            )
        )
    finally:
        ops.detect_overlap_splits = original


def test_recorded_symbols_are_refetched_then_rederived_in_that_order():
    order: list[tuple[str, list[str]]] = []
    report = _process(
        FakeConn(),
        [_split("BBB"), _split("AAA")],
        refetch=lambda s: order.append(("refetch", s)) or 0,
        derive=lambda s: order.append(("derive", s)) or 0,
    )
    assert order == [("refetch", ["AAA", "BBB"]), ("derive", ["AAA", "BBB"])]
    assert report == {"recorded": ["AAA", "BBB"], "unexplained": [], "returncode": 0}


def test_an_already_recorded_split_is_not_refetched_again():
    order: list = []
    report = _process(
        FakeConn(existing=[("aaaa", 3.0)]),
        [_split()],
        refetch=lambda s: order.append(s) or 0,
    )
    assert order == [] and report["recorded"] == []


def test_unexplained_differences_are_reported_and_never_recorded():
    seen: list[str] = []
    conn = FakeConn()
    report = _process(
        conn, [_split("NOISY", unexplained=True)], report=lambda s: seen.append(s.symbol)
    )
    assert seen == ["NOISY"] and report["unexplained"] == ["NOISY"]
    assert conn.executed == [] and report["recorded"] == []


def test_a_failed_refetch_skips_the_derivation_and_returns_its_code():
    derived: list = []
    report = _process(
        FakeConn(), [_split()], refetch=lambda s: 3, derive=lambda s: derived.append(s) or 0
    )
    assert report["returncode"] == 3 and derived == []


def test_the_refetch_command_asks_the_full_depth_through_the_fetcher_on_the_given_client():
    command = ops.refetch_command(["AAA", "BBB"], years=20, client_id=45)
    assert command[:2] == [sys.executable, str(ops._FETCHER)]
    assert command[1].endswith("scripts/infrastructure/backfill/ibkr_history_fetcher.py")
    assert "--full-scan" in command
    rest = [part for part in command[2:] if part != "--full-scan"]
    pairs = dict(zip(rest[::2], rest[1::2], strict=False))
    assert pairs["--symbols"] == "AAA,BBB" and pairs["--timeframes"] == "1d"
    assert pairs["--dimension"] == "backfill" and pairs["--client-id"] == "45"
    assert pairs["--overlap-sessions"] == str(20 * 260)
    assert not any("lease" in part for part in command)


class _FakeProc:
    def __init__(self, lines: list[str], rc: int) -> None:
        self.stdout = iter(lines)
        self._rc = rc

    def wait(self) -> int:
        return self._rc


def test_a_refetch_refused_by_the_fetcher_lock_is_a_failure_not_a_success():
    """Plan 189-08: the fetcher exits 0 and prints LOCK_HELD_MESSAGE when its lock is held
    (always so when this script runs as the fetcher's own run-end stage). That must read as
    a failed re-fetch, so the derivation is skipped and the split stays quarantined."""
    from scripts.infrastructure.backfill._fetcher_lock import LOCK_HELD_MESSAGE

    refused = ops.run_refetch(["x"], popen=lambda *a, **k: _FakeProc([LOCK_HELD_MESSAGE + "\n"], 0))
    assert refused == ops.LOCK_HELD_EXIT != 0
    assert ops.run_refetch(["x"], popen=lambda *a, **k: _FakeProc(["ok\n"], 0)) == 0
    assert ops.run_refetch(["x"], popen=lambda *a, **k: _FakeProc([], 1)) == 1


def test_the_derive_command_forces_the_daily_stage_for_exactly_those_symbols():
    command = ops._derive_command(["AAA"])
    assert command[-5:] == ["--stage", "daily", "--symbols", "AAA", "--apply"]
