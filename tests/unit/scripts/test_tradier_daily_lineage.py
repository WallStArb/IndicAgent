"""The Tradier daily loader's write path (plan 185-27, VERIFICATION gaps 1 and 2).

Fakes only (todo 494): no test appends to the live D1, writes a bar, or opens a database
connection. A fake asyncpg connection records every statement; the Tradier client, the APR read,
the batch helpers, the scrub, the digest writer and the pool factory are replaced on the module.

Contract: _record_load upserts only new and changed bars, then under bar_derivation_writer
writes tradier-v1 lineage in the same transaction and aborts it when a stored Tradier bar has no
equal observation; a write run is one tradier batch that scrubs the names it changed and digests
every loaded name after the fetch loop; D1 lands only new or changed bars while the request row
keeps the full answer count; --dry-run writes nothing.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

import scripts.infrastructure.backfill.infrastructure_run_tradier_daily as loader
from scripts.infrastructure.backfill.infrastructure_run_tradier_daily import (
    TRADIER_LINEAGE_UPSERT_SQL,
    LoadParams,
    plan_symbol_load,
)
from src.intelligence.bars.sources import TRADIER_RULE_VERSION
from src.providers.tradier import DailyBar

_PARAMS = LoadParams(
    min_session_ratio=0.95,
    first_date_tolerance_days=7,
    max_changed_bar_ratio=0.02,
    rebase=False,
    split_rel_tol=0.002,
    split_min_run=5,
    ratio_snap_tol=0.01,
)
_BATCH_ID = "33333333-3333-3333-3333-333333333333"
_APR = {
    "infra.tradier.min_session_ratio": "0.95",
    "infra.tradier.first_date_tolerance_days": "7",
    "infra.tradier.max_changed_bar_ratio": "0.02",
    "infra.tradier.history_start": "2024-01-01",
    "infra.tradier.concurrency": "2",
    "infra.tradier.request_timeout_s": "30",
    "infra.tradier.nightly_enabled": "true",
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


def _stored(bar: DailyBar, close: float | None = None) -> tuple:
    return (
        bar.open,
        bar.high,
        bar.low,
        bar.close if close is None else close,
        bar.volume,
        "tradier",
    )


class FakeConn:
    """asyncpg.Connection-shaped recorder with configurable read answers."""

    def __init__(
        self,
        *,
        stored: dict[str, list[DailyBar]] | None = None,
        observed: dict[str, list[DailyBar]] | None = None,
        unmatched: dict[str, list[date]] | None = None,
        lineage_rowcount: int = 0,
    ) -> None:
        self.stored = stored or {}
        self.observed = observed or {}
        self.unmatched = unmatched or {}
        self.lineage_rowcount = lineage_rowcount
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
        symbol = str(args[0]) if args else ""
        if "tradier_lineage_unmatched" in sql:
            return [{"bar_date": d} for d in self.unmatched.get(symbol, [])]
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
                for b in self.observed.get(symbol, [])
            ]
        if "FROM market_data_ohlcv" in sql:
            return [
                {
                    "timestamp": b.timestamp,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                    "source": "tradier",
                }
                for b in self.stored.get(symbol, [])
            ]
        raise AssertionError(f"unexpected fetch: {sql}")

    async def execute(self, sql: str, *args: Any) -> str:
        self.calls.append(("execute", sql, args))
        if sql is TRADIER_LINEAGE_UPSERT_SQL:
            return f"INSERT 0 {self.lineage_rowcount}"
        return "INSERT 0 1"

    async def executemany(self, sql: str, args_seq: Any) -> None:
        self.calls.append(("executemany", sql, tuple(tuple(a) for a in args_seq)))

    async def copy_records_to_table(self, table: str, *, records: Any, columns: Any) -> None:
        self.copies.append((table, list(records)))

    async def close(self) -> None:
        return None

    def writes(self) -> list[tuple[str, str, tuple]]:
        return [c for c in self.calls if c[0] in ("execute", "executemany")]

    def upsert_rows(self) -> list[tuple]:
        return [
            row
            for kind, sql, rows in self.calls
            if kind == "executemany" and "INSERT INTO market_data_ohlcv" in sql
            for row in rows
        ]


# --- _record_load ------------------------------------------------------------------------


def _record(conn: FakeConn, plan: Any, n_fetched: int = 0) -> int:
    return asyncio.run(
        loader._record_load(
            conn,
            "TEST",
            date(2024, 1, 1),
            date(2024, 12, 31),
            plan,
            n_fetched,
            request_id="req-1",
            batch_id=_BATCH_ID,
        )
    )


def test_identical_refetch_issues_no_upsert_row():
    bars = _weekday_bars(300)
    plan = plan_symbol_load(bars, {b.timestamp: _stored(b) for b in bars}, _PARAMS)
    conn = FakeConn()
    _record(conn, plan, len(bars))
    assert conn.upsert_rows() == []


def test_one_changed_and_one_new_bar_upsert_exactly_those_two():
    bars = _weekday_bars(300)
    existing = {b.timestamp: _stored(b) for b in bars[:299]}
    existing[bars[5].timestamp] = _stored(bars[5], close=99.0)
    plan = plan_symbol_load(bars, existing, _PARAMS)
    conn = FakeConn()
    _record(conn, plan, len(bars))
    rows = conn.upsert_rows()
    assert [r[0] for r in rows] == [bars[5].timestamp, bars[299].timestamp]
    assert all(r[1] == "TEST" and r[-1] == "tradier" for r in rows)


def test_lineage_runs_in_the_bar_transaction_under_the_writer_role_after_load_and_revision():
    bars = _weekday_bars(300)
    existing = {b.timestamp: _stored(b) for b in bars}
    existing[bars[5].timestamp] = _stored(bars[5], close=99.0)
    plan = plan_symbol_load(bars, existing, _PARAMS)
    conn = FakeConn(lineage_rowcount=300)
    assert _record(conn, plan, len(bars)) == 300
    seq = [
        (kind, sql.strip().split("\n")[0][:40])
        for kind, sql, _ in conn.calls
        if kind in ("begin", "commit", "rollback", "execute", "executemany")
    ]
    kinds = [k for k, _ in seq]
    assert kinds[0] == "begin" and kinds[-1] == "commit" and kinds.count("begin") == 1
    statements = [sql for kind, sql, _ in conn.calls if kind in ("execute", "executemany")]
    i_load = next(i for i, s in enumerate(statements) if "INSERT INTO ohlcv_load" in s)
    i_rev = next(i for i, s in enumerate(statements) if "INSERT INTO ohlcv_revision" in s)
    i_role = statements.index("SET LOCAL ROLE bar_derivation_writer")
    i_lineage = statements.index(TRADIER_LINEAGE_UPSERT_SQL)
    assert i_load < i_role and i_rev < i_role < i_lineage
    lineage_args = next(a for k, s, a in conn.calls if s is TRADIER_LINEAGE_UPSERT_SQL)
    assert lineage_args == ("TEST", _BATCH_ID)


def test_unmatched_stored_bar_rolls_the_load_back():
    bars = _weekday_bars(300)
    plan = plan_symbol_load(bars, {}, _PARAMS)
    conn = FakeConn(unmatched={"TEST": [date(2024, 1, 2)]})
    with pytest.raises(loader.LineageGapError, match="2024-01-02"):
        _record(conn, plan, len(bars))
    assert conn.calls[-1][0] == "rollback"


def test_failed_load_writes_no_lineage():
    conn = FakeConn()
    _record(conn, loader.LoadPlan("failed", "boom"))
    assert TRADIER_LINEAGE_UPSERT_SQL not in [sql for _, sql, _ in conn.calls]


def test_lineage_sql_matches_the_latest_equal_non_test_tradier_observation():
    sql = TRADIER_LINEAGE_UPSERT_SQL
    assert "INSERT INTO canonical_bar_lineage" in sql
    assert f"'{TRADIER_RULE_VERSION}'" in sql
    assert "m.source = 'tradier'" in sql and "o.route = 'TRADIER'" in sql
    assert "q.caller NOT LIKE 'test-%'" in sql
    assert 'ORDER BY s."timestamp", o.fetched_at DESC' in sql
    assert repr(loader._VALUE_TOLERANCE) in sql
    assert "o.volume = s.volume" in sql
    # Only rows whose rule or provenance changed are rewritten.
    assert "IS DISTINCT FROM EXCLUDED.rule_version" in sql
    assert "IS DISTINCT FROM EXCLUDED.request_ids" in sql
    assert "$2::uuid" in sql and "$3" not in sql
    # The unmatched count uses the same match predicate.
    assert loader._LINEAGE_MATCH_SQL in sql
    assert loader._LINEAGE_MATCH_SQL in loader._TRADIER_LINEAGE_UNMATCHED_SQL


# --- run() -------------------------------------------------------------------------------


class _Client:
    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _Pool:
    closed = False

    async def close(self) -> None:
        _Pool.closed = True


def _install(
    monkeypatch: pytest.MonkeyPatch,
    conn: FakeConn,
    answers: dict[str, list[DailyBar]],
    *,
    scrub_error: Exception | None = None,
) -> dict[str, list]:
    seen: dict[str, list] = {
        "open": [],
        "close": [],
        "scrub": [],
        "digest": [],
        "pool": [],
        "marked": [],
    }

    async def connect(_url: str) -> FakeConn:
        return conn

    async def apr(_conn: Any, _patterns: Any) -> dict[str, str]:
        return dict(_APR)

    async def fetch_history(_client: Any, symbol: str, _start: date, _end: date) -> list:
        return answers[symbol]

    async def open_batch(_conn: Any, **kwargs: Any) -> str:
        seen["open"].append(kwargs)
        return _BATCH_ID

    async def close_batch(_conn: Any, batch_id: str, **kwargs: Any) -> None:
        seen["close"].append((batch_id, kwargs))

    async def create_pool(url: str, pool_name: str = "default", **kwargs: Any) -> _Pool:
        seen["pool"].append(pool_name)
        return _Pool()

    async def scrub(pool: Any, **kwargs: Any) -> dict[str, int]:
        seen["scrub"].append(kwargs)
        if scrub_error is not None:
            raise scrub_error
        return {"volume_spike": 1}

    async def digests(_conn: Any, **kwargs: Any) -> int:
        seen["digest"].append(kwargs)
        return 2

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
    monkeypatch.setattr(loader, "open_batch", open_batch)
    monkeypatch.setattr(loader, "close_batch", close_batch)
    monkeypatch.setattr(loader, "create_pool", create_pool)
    monkeypatch.setattr(loader, "scrub_symbols", scrub)
    monkeypatch.setattr(loader, "write_1d_digests", digests)
    monkeypatch.setattr(
        loader,
        "mark_loaded_fetch_complete",
        lambda url, symbols, since: seen["marked"].append((url, symbols, since)),
    )
    return seen


def _two_names() -> tuple[FakeConn, dict[str, list[DailyBar]], list[DailyBar]]:
    bars = _weekday_bars(300)
    # SAME: stored and observed equal to the answer. MOVED: one changed bar, one new bar.
    moved = list(bars)
    moved[5] = replace(bars[5], close=10.75)
    moved.append(DailyBar(bars[-1].timestamp + timedelta(days=3), 10.0, 11.0, 9.0, 10.5, 100))
    conn = FakeConn(
        stored={"SAME": bars, "MOVED": bars},
        observed={"SAME": bars, "MOVED": bars},
    )
    return conn, {"SAME": bars, "MOVED": moved}, moved


def test_write_run_is_one_tradier_batch_scrubbing_changed_names_and_digesting_all(monkeypatch):
    conn, answers, moved = _two_names()
    seen = _install(monkeypatch, conn, answers)
    code = asyncio.run(loader.run(["SAME", "MOVED"], False, False, False))
    assert code == 0
    (opened,) = seen["open"]
    assert opened["stage"] == "tradier" and opened["rule_version"] == TRADIER_RULE_VERSION
    assert set(opened["apr_snapshot"]) == {k for k in _APR if k.startswith("infra.tradier.")}
    # Scrub only the name whose bars changed (no lineage change in the fake), after the loop.
    (scrub,) = seen["scrub"]
    assert scrub["symbols"] == ["MOVED"] and scrub["tf"] == "1d" and scrub["write"] is True
    assert scrub["batch_id"] == _BATCH_ID and scrub["rules"] is None
    assert scrub["start"] is None and scrub["end"] is None
    # Digests for every loaded name at tradier-v1.
    assert sorted(d["symbol"] for d in seen["digest"]) == ["MOVED", "SAME"]
    assert all(d["rule_version"] == TRADIER_RULE_VERSION for d in seen["digest"])
    assert all(d["batch_id"] == _BATCH_ID for d in seen["digest"])
    ((batch_id, closed),) = seen["close"]
    assert batch_id == _BATCH_ID and closed["status"] == "completed"
    # D1: each request keeps the full answer count; observations are the new or changed bars.
    requests = [r for table, rows in conn.copies if table == "ohlcv_request" for r in rows]
    observations = [r for table, rows in conn.copies if table == "ohlcv_observation" for r in rows]
    assert len(requests) == 2
    assert sorted(len(answers[s]) for s in ("SAME", "MOVED")) == sorted(
        r[_n_bars_index()] for r in requests
    )
    assert len(observations) == 2  # MOVED's changed bar and its new bar; SAME lands none
    # The canonical upsert carries MOVED's two bars only.
    assert sorted(r[0] for r in conn.upsert_rows()) == [moved[5].timestamp, moved[-1].timestamp]


def _n_bars_index() -> int:
    from services.ohlcv_observation_writer import _REQUEST_COLUMNS

    return list(_REQUEST_COLUMNS).index("n_bars")


def test_lineage_change_alone_puts_a_name_in_the_scrub(monkeypatch):
    conn, answers, _ = _two_names()
    conn.lineage_rowcount = 300
    seen = _install(monkeypatch, conn, answers)
    assert asyncio.run(loader.run(["SAME", "MOVED"], False, False, False)) == 0
    assert sorted(seen["scrub"][0]["symbols"]) == ["MOVED", "SAME"]


def test_scrub_failure_fails_the_batch_and_exits_1(monkeypatch):
    conn, answers, _ = _two_names()
    seen = _install(monkeypatch, conn, answers, scrub_error=RuntimeError("scrub down"))
    assert asyncio.run(loader.run(["SAME", "MOVED"], False, False, False)) == 1
    assert seen["close"][0][1]["status"] == "failed"


def test_unmatched_lineage_records_the_load_failed_and_moves_on(monkeypatch):
    conn, answers, _ = _two_names()
    conn.unmatched = {"MOVED": [date(2024, 1, 2)]}
    seen = _install(monkeypatch, conn, answers)
    assert asyncio.run(loader.run(["SAME", "MOVED"], False, False, False)) == loader.EXIT_REFUSED
    load_rows = [a for kind, sql, a in conn.calls if "INSERT INTO ohlcv_load" in sql]
    moved_outcomes = [a[5] for a in load_rows if a[1] == "MOVED"]
    assert moved_outcomes == ["loaded", "failed"]  # the first rolled back, the second recorded
    assert [d["symbol"] for d in seen["digest"]] == ["SAME"]


def test_dry_run_writes_nothing(monkeypatch):
    conn, answers, _ = _two_names()
    seen = _install(monkeypatch, conn, answers)
    assert asyncio.run(loader.run(["SAME", "MOVED"], False, False, True)) == 0
    assert conn.writes() == [] and conn.copies == []
    assert seen["open"] == [] and seen["scrub"] == [] and seen["digest"] == []


def test_raw_only_lands_every_bar_and_opens_no_batch(monkeypatch):
    conn, answers, _ = _two_names()
    seen = _install(monkeypatch, conn, answers)
    assert asyncio.run(loader.run(["SAME"], False, True, False)) == 0
    observations = [r for table, rows in conn.copies if table == "ohlcv_observation" for r in rows]
    assert len(observations) == len(answers["SAME"])
    assert seen["open"] == [] and conn.upsert_rows() == []


def test_accepted_loads_mark_1d_fetch_complete_after_the_loop(monkeypatch):
    conn, answers, _ = _two_names()
    seen = _install(monkeypatch, conn, answers)
    assert asyncio.run(loader.run(["SAME", "MOVED"], False, False, False)) == 0
    # One call for every accepted load, from the requested start (infra.tradier.history_start).
    assert seen["marked"] == [("postgresql://unused", ["MOVED", "SAME"], date(2024, 1, 1))]
    assert seen["close"][0][1]["detail"]["n_fetch_complete_marked"] == 2


def test_a_failed_load_is_not_marked_fetch_complete(monkeypatch):
    conn, answers, _ = _two_names()
    conn.unmatched = {"MOVED": [date(2024, 1, 2)]}
    seen = _install(monkeypatch, conn, answers)
    asyncio.run(loader.run(["SAME", "MOVED"], False, False, False))
    assert [symbols for _url, symbols, _since in seen["marked"]] == [["SAME"]]


def test_dry_run_and_raw_only_mark_nothing(monkeypatch):
    conn, answers, _ = _two_names()
    seen = _install(monkeypatch, conn, answers)
    asyncio.run(loader.run(["SAME", "MOVED"], False, False, True))
    asyncio.run(loader.run(["SAME"], False, True, False))
    assert seen["marked"] == []


def test_fetch_complete_failure_fails_the_batch_and_exits_1(monkeypatch):
    conn, answers, _ = _two_names()
    seen = _install(monkeypatch, conn, answers)

    def boom(*_args: Any) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(loader, "mark_loaded_fetch_complete", boom)
    assert asyncio.run(loader.run(["SAME", "MOVED"], False, False, False)) == 1
    assert seen["close"][0][1]["status"] == "failed"


def test_mark_loaded_fetch_complete_goes_through_the_one_writer(monkeypatch):
    """No restated SQL: each name goes to mark_fetch_complete on one psycopg connection."""
    calls: list[tuple] = []

    class _Pg:
        def __enter__(self) -> _Pg:
            return self

        def __exit__(self, *_exc: Any) -> None:
            calls.append(("exit",))

    monkeypatch.setattr(
        loader.psycopg, "connect", lambda url: calls.append(("connect", url)) or _Pg()
    )
    monkeypatch.setattr(
        loader, "mark_fetch_complete", lambda conn, *args: calls.append(("mark", *args))
    )
    loader.mark_loaded_fetch_complete("postgresql://x", ["AAA", "BBB"], date(2000, 1, 1))
    since = datetime(2000, 1, 1, tzinfo=UTC)
    assert calls == [
        ("connect", "postgresql://x"),
        ("mark", "AAA", "1d", since),
        ("mark", "BBB", "1d", since),
        ("exit",),
    ]


def test_the_loader_uses_the_pipeline_writer_itself():
    from scripts.infrastructure.backfill import infrastructure_run_historical_pipeline as pipeline

    assert loader.mark_fetch_complete is pipeline.mark_fetch_complete
