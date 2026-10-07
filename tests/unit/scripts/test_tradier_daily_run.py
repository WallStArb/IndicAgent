"""The Tradier loader's run (plan 185-38): raw only, then the chained daily stage.

Fakes only (todo 494): no test appends to the live D1, writes a bar, or opens a database
connection. A fake asyncpg connection records every statement; the Tradier client, the APR read,
and the daily-stage subprocess are replaced on the module.

Contract: each load lands D1 (changes only) and writes one ohlcv_load row with destination d1;
no market_data_ohlcv, lineage, revision or digest statement is issued in any path; a gated
answer lands nothing; a split writes its corporate_action row in the load row's transaction;
after the loop the daily stage runs once over exactly the names whose D1 changed (or that
carried a split) and its failure fails the run.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

import scripts.infrastructure.backfill.infrastructure_run_tradier_daily as loader
from src.providers.tradier import DailyBar

_APR = {
    "infra.tradier.min_session_ratio": "0.95",
    "infra.tradier.first_date_tolerance_days": "7",
    "infra.tradier.history_start": "2024-01-01",
    "infra.tradier.concurrency": "2",
    "infra.tradier.request_timeout_s": "30",
    "infra.tradier.nightly_enabled": "true",
    "threshold.bar_integrity.max_revision_ratio": "0.02",
    "threshold.seam.rel_tol": "0.002",
    "threshold.seam.min_run": "5",
    "threshold.seam.ratio_snap_tol": "0.01",
}


def _weekday_bars(n: int, start: datetime = datetime(2024, 1, 1, tzinfo=UTC)) -> list[DailyBar]:
    bars, day = [], start
    while len(bars) < n:
        if day.weekday() < 5:
            bars.append(DailyBar(day, 10.0, 11.0, 9.0, 10.5, 100))
        day += timedelta(days=1)
    return bars


class FakeConn:
    def __init__(self, observed: dict[str, list[DailyBar]]) -> None:
        self.observed = observed
        self.calls: list[tuple[str, str, tuple]] = []
        self.copies: list[tuple[str, list]] = []
        self._depth = 0

    class _Txn:
        def __init__(self, outer: FakeConn) -> None:
            self.outer = outer

        async def __aenter__(self) -> None:
            self.outer._depth += 1
            self.outer.calls.append(("begin", "", ()))

        async def __aexit__(self, *exc: object) -> bool:
            self.outer._depth -= 1
            self.outer.calls.append(("rollback" if exc[0] else "commit", "", ()))
            return False

    def transaction(self) -> FakeConn._Txn:
        return self._Txn(self)

    def is_in_transaction(self) -> bool:
        return self._depth > 0

    async def fetch(self, sql: str, *args: Any) -> list[dict]:
        self.calls.append(("fetch", sql, args))
        if "DISTINCT ON (o.bar_date)" in sql:
            return [
                {
                    "bar_date": b.timestamp.date(),
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                }
                for b in self.observed.get(str(args[0]), [])
            ]
        raise AssertionError(f"unexpected fetch: {sql}")

    async def execute(self, sql: str, *args: Any) -> str:
        self.calls.append(("execute", sql, args))
        return "INSERT 0 1"

    async def executemany(self, sql: str, args_seq: Any) -> None:
        self.calls.append(("executemany", sql, tuple(tuple(a) for a in args_seq)))

    async def copy_records_to_table(self, table: str, *, records: Any, columns: Any) -> None:
        self.copies.append((table, list(records)))

    async def close(self) -> None:
        return None

    def loads(self) -> list[tuple]:
        return [a for _k, sql, a in self.calls if "INSERT INTO ohlcv_load" in sql]


class _Client:
    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _install(monkeypatch, conn: FakeConn, answers, *, stage_code: int = 0) -> dict[str, list]:
    seen: dict[str, list] = {"stage": []}

    async def connect(_url: str) -> FakeConn:
        return conn

    async def apr(_conn: Any, _patterns: Any) -> dict[str, str]:
        return dict(_APR)

    async def fetch_history(_client: Any, symbol: str, _start: date, _end: date) -> Any:
        return answers[symbol]

    def stage(symbols: list[str]) -> int:
        seen["stage"].append(symbols)
        return stage_code

    monkeypatch.setattr(loader.asyncpg, "connect", connect)
    monkeypatch.setattr(loader, "load_apr_dict_async", apr)
    monkeypatch.setattr(
        loader,
        "get_settings",
        lambda: type(
            "S",
            (),
            {
                "database_url": "postgresql://unused",
                "tradier_base_url": "https://unused",
                "tradier_api_token": "unused",
            },
        )(),
    )
    monkeypatch.setattr(loader, "make_client", lambda *a: _Client())
    monkeypatch.setattr(loader, "fetch_daily_history", fetch_history)
    monkeypatch.setattr(loader, "run_daily_stage", stage)
    return seen


def _three_names():
    bars = _weekday_bars(300)
    moved = list(bars)
    moved[5] = replace(bars[5], close=10.75)
    moved.append(DailyBar(bars[-1].timestamp + timedelta(days=3), 10.0, 11.0, 9.0, 10.5, 100))
    noisy = [replace(b, close=b.close + 0.01) if i % 10 == 0 else b for i, b in enumerate(bars)]
    conn = FakeConn({"SAME": bars, "MOVED": bars, "NOISY": bars})
    return conn, {"SAME": bars, "MOVED": moved, "NOISY": noisy}


def _load_field(row: tuple, name: str) -> Any:
    columns = (
        "load_id symbol source requested_start requested_end outcome n_bars n_new n_changed "
        "first_bar last_bar detail caller destination"
    ).split()
    return row[columns.index(name)]


def test_raw_only_run_lands_changes_records_d1_loads_and_chains_the_changed_names(monkeypatch):
    conn, answers = _three_names()
    seen = _install(monkeypatch, conn, answers)
    code = asyncio.run(loader.run(["SAME", "MOVED", "NOISY"], False, False))
    assert code == loader.EXIT_REFUSED  # NOISY is gated: a finding
    loads = {_load_field(r, "symbol"): r for r in conn.loads()}
    assert {s: _load_field(r, "outcome") for s, r in loads.items()} == {
        "SAME": "loaded",
        "MOVED": "loaded",
        "NOISY": "gated",
    }
    assert {_load_field(r, "destination") for r in loads.values()} == {"d1"}
    assert (_load_field(loads["SAME"], "n_new"), _load_field(loads["SAME"], "n_changed")) == (0, 0)
    assert (_load_field(loads["MOVED"], "n_new"), _load_field(loads["MOVED"], "n_changed")) == (
        1,
        1,
    )
    # D1: every request recorded, observations only for MOVED's two bars (NOISY gated).
    requests = [r for t, rows in conn.copies if t == "ohlcv_request" for r in rows]
    observations = [r for t, rows in conn.copies if t == "ohlcv_observation" for r in rows]
    assert len(requests) == 3 and len(observations) == 2
    # The daily stage runs once over exactly the changed names.
    assert seen["stage"] == [["MOVED"]]


def test_no_canonical_lineage_revision_or_digest_statement_in_any_path(monkeypatch):
    conn, answers = _three_names()
    _install(monkeypatch, conn, answers)
    asyncio.run(loader.run(["SAME", "MOVED", "NOISY"], False, False))
    for _kind, sql, _args in conn.calls:
        assert not re.search(
            r"market_data_ohlcv\b(?!_tradeable)|canonical_bar_lineage|ohlcv_revision|"
            r"bar_content_digest",
            sql,
        ), sql


def test_a_split_refetch_records_corporate_action_in_the_load_transaction_and_chains(monkeypatch):
    bars = _weekday_bars(301)
    old = [
        replace(b, open=b.open * 2, high=b.high * 2, low=b.low * 2, close=b.close * 2)
        for b in bars[:300]
    ]
    conn = FakeConn({"SPLIT": old})
    seen = _install(monkeypatch, conn, {"SPLIT": bars})
    assert asyncio.run(loader.run(["SPLIT"], False, False)) == 0
    kinds = [(k, sql) for k, sql, _ in conn.calls if k in ("begin", "commit", "execute")]
    load_i = next(i for i, (_k, sql) in enumerate(kinds) if "INSERT INTO ohlcv_load" in sql)
    role_i = next(i for i, (_k, sql) in enumerate(kinds) if "SET LOCAL ROLE" in sql and i > load_i)
    split_i = next(i for i, (_k, sql) in enumerate(kinds) if "INSERT INTO corporate_action" in sql)
    commit_i = next(i for i, (k, _s) in enumerate(kinds) if k == "commit" and i > load_i)
    assert load_i < role_i < split_i < commit_i
    assert seen["stage"] == [["SPLIT"]]


def test_a_short_history_answer_lands_and_records_loaded(monkeypatch):
    bars = _weekday_bars(300)
    sparse = bars[:100] + bars[200:]
    conn = FakeConn({})
    seen = _install(monkeypatch, conn, {"SHORT": sparse})
    assert asyncio.run(loader.run(["SHORT"], False, False)) == 0
    (row,) = conn.loads()
    assert _load_field(row, "outcome") == "loaded"
    assert _load_field(row, "detail").startswith("short_history")
    assert seen["stage"] == [["SHORT"]]


def test_a_failed_daily_stage_fails_the_run(monkeypatch):
    conn, answers = _three_names()
    _install(monkeypatch, conn, answers, stage_code=1)
    assert asyncio.run(loader.run(["MOVED"], False, False)) == 1


def test_nothing_changed_runs_no_daily_stage(monkeypatch):
    conn, answers = _three_names()
    seen = _install(monkeypatch, conn, answers)
    assert asyncio.run(loader.run(["SAME"], False, False)) == 0
    assert seen["stage"] == []


def test_a_failed_fetch_records_failed_and_is_not_chained(monkeypatch):
    conn = FakeConn({})
    seen = _install(monkeypatch, conn, {})

    async def failing(_client, symbol, _s, _e):
        raise loader.TradierError("timeout")

    monkeypatch.setattr(loader, "fetch_daily_history", failing)
    assert asyncio.run(loader.run(["DOWN"], False, False)) == loader.EXIT_REFUSED
    (row,) = conn.loads()
    assert _load_field(row, "outcome") == "failed"
    assert seen["stage"] == []


def test_dry_run_writes_nothing(monkeypatch):
    conn, answers = _three_names()
    seen = _install(monkeypatch, conn, answers)
    asyncio.run(loader.run(["SAME", "MOVED"], False, True))
    assert [c for c in conn.calls if c[0] in ("execute", "executemany")] == []
    assert conn.copies == [] and seen["stage"] == []


def test_daily_stage_subprocess_is_the_single_writer_with_apply():
    assert loader.DAILY_STAGE_ARGS == ("-m", "services.bar_derivation", "--stage", "daily")
    import inspect

    source = inspect.getsource(loader.run_daily_stage)
    assert '"--apply"' in source and '"--symbols"' in source


def test_the_loader_writes_no_backfill_status():
    """Plan 189-08 retired the fetch_complete writer: promotion reads bar_integrity
    verdicts since plan 185-41, so an accepted load no longer marks backfill_status."""
    import inspect

    source = inspect.getsource(loader)
    assert "mark_fetch_complete" not in source and "mark_loaded_fetch_complete" not in source
    assert "INSERT INTO backfill_status" not in source


def test_raw_only_flag_and_lineage_symbols_are_gone():
    for name in ("TRADIER_LINEAGE_UPSERT_SQL", "LineageGapError", "_scrub_and_digest"):
        assert not hasattr(loader, name), name
    with pytest.raises(SystemExit):
        import sys

        argv = sys.argv
        sys.argv = ["loader", "--raw-only"]
        try:
            loader.main()
        finally:
            sys.argv = argv
