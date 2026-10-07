"""IbkrHistoryFetcher (phase 189 plan 04): singleton, dry run, scope, budget, failure paths,
outcome writes and run-end stages.

No IBKR connection anywhere: the provider, item fetch, run plan, stage runner and lock come in
through the fetcher's constructor seams. The two singleton tests take a real FetcherLock on a
unique test name against the local PostgreSQL (never FETCHER_LOCK_NAME, T-189-08) and skip
when no database is reachable; every other test is CI-clean.
"""

from __future__ import annotations

import asyncio
import functools
import time
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import psycopg
import pytest

from scripts.infrastructure.backfill import _fetch_queue as fq
from scripts.infrastructure.backfill import ibkr_history_fetcher as hf
from scripts.infrastructure.backfill._fetcher_lock import LOCK_HELD_MESSAGE, FetcherLock
from scripts.infrastructure.backfill._history_fetch_item import ItemOutcome

_LIVE_DB_DSN = "postgresql://postgres:postgres@localhost:5432/indicagent"
_TODAY = date(2026, 10, 6)

_CONFIG = fq.QueueConfig(
    max_consecutive_failures=5,
    max_staleness_days_before_preempt=3,
    priority_tf_order=("15m", "1h"),
    depth_days={"1d": 7300, "1h": 7300, "15m": 7300, "5m": 7300},
    history_request_timeout_s=900.0,
    history_request_retries=2,
    run_budget_minutes=240,
    default_scopes={
        "compute": ("1d", "1h", "15m", "5m"),
        "compute_1d": ("1d",),
        "backfill": ("1h", "15m"),
    },
)


@functools.lru_cache(maxsize=1)
def _db_reachable() -> bool:
    try:
        conn = psycopg.connect(_LIVE_DB_DSN, connect_timeout=3)
    except Exception:
        return False
    conn.close()
    return True


_live = pytest.mark.skipif(not _db_reachable(), reason="local PostgreSQL not reachable")


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _args(*argv: str, **overrides: Any) -> Any:
    args = hf.build_parser().parse_args(list(argv))
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def _ranked(symbol: str, timeframe: str = "15m", gap_days: int = 0) -> fq.RankedItem:
    row = fq.CoverageRow(symbol, timeframe, None, None, "ok", 0, None)
    return fq.RankedItem(row, (False,), False, -1, gap_days, 1)


class _FakeQueue:
    """Hands out its items in order, honoring visited (like PriorityQueue.next)."""

    def __init__(self, items: list[fq.RankedItem], *, repeat_first: bool = False) -> None:
        self.items = items
        self.repeat_first = repeat_first

    async def load(self, pool: Any) -> None:
        return None

    async def next(self, pool: Any, visited: set[tuple[str, str]]) -> fq.CoverageRow | None:
        if self.repeat_first:
            return self.items[0].row
        for item in self.items:
            if (item.row.symbol, item.row.timeframe) not in visited:
                return item.row
        return None

    def ranked_snapshot(self) -> list[fq.RankedItem]:
        return list(self.items)

    def held_snapshot(self) -> list[tuple[fq.RankedItem, str]]:
        return []


def _plan(items: list[fq.RankedItem], **queue_kwargs: Any) -> hf.RunPlan:
    symbols = {i.row.symbol for i in items}
    return hf.RunPlan(
        config=_CONFIG,
        queue=_FakeQueue(items, **queue_kwargs),
        candidates=hf.Candidates(
            pairs=[(i.row.symbol, i.row.timeframe) for i in items],
            instruments={s: SimpleNamespace(symbol=s) for s in symbols},
        ),
        tradier_owned=[],
        tf_fetch_config={},
        overlap_sessions=0,
        inter_item_pause_s=0.0,
    )


class _FakeCursor:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    def execute(self, sql: str, params: Any = None) -> None:
        self.log.append(sql)


class _FakeConn:
    def __init__(self) -> None:
        self.log: list[str] = []

    def transaction(self) -> Any:
        conn = self

        class _Tx:
            def __enter__(self) -> _FakeConn:
                return conn

            def __exit__(self, *exc: Any) -> bool:
                return False

        return _Tx()

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.log)


class _FakeCtx:
    def __init__(self) -> None:
        self.conn = _FakeConn()
        self.sink = SimpleNamespace(pending=lambda: 0)

    def get_conn(self) -> _FakeConn:
        return self.conn


class _FakeProvider:
    def __init__(self, connects: bool = True, gate: asyncio.Event | None = None) -> None:
        self.connects = connects
        self.gate = gate
        self.disconnected = False

    async def connect(self) -> bool:
        if self.gate is not None:
            await self.gate.wait()
        return self.connects

    async def disconnect(self) -> None:
        self.disconnected = True


class _AlwaysLock:
    def acquire(self) -> bool:
        return True

    def close(self) -> None:
        return None


def _outcome(row: Any, status: str = "ok", **fields: Any) -> ItemOutcome:
    return ItemOutcome(row.symbol, row.timeframe, status, **fields)


def _fetcher(
    tmp_path: Path,
    plan: hf.RunPlan | None = None,
    *,
    args: Any = None,
    fetch_fn: Any = None,
    provider: Any = None,
    stage_rc: int = 0,
    **kwargs: Any,
) -> tuple[hf.IbkrHistoryFetcher, dict[str, Any]]:
    seen: dict[str, Any] = {"providers": 0, "stages": [], "fetched": [], "notify": 0}
    ctx = _FakeCtx()
    seen["ctx"] = ctx

    def provider_factory() -> Any:
        seen["providers"] += 1
        return provider or _FakeProvider()

    async def default_fetch(ctx: Any, instrument: Any, row: Any, **kw: Any) -> ItemOutcome:
        seen["fetched"].append((row.symbol, row.timeframe))
        return _outcome(row)

    async def stage_runner(argv: list[str]) -> int:
        seen["stages"].append(argv)
        return stage_rc

    async def prepare(pool: Any) -> hf.RunPlan:
        seen["prepared"] = True
        assert plan is not None
        return plan

    def notify() -> None:
        seen["notify"] += 1

    kwargs.setdefault("lock_factory", _AlwaysLock)
    fetcher = hf.IbkrHistoryFetcher(
        _LIVE_DB_DSN,
        args or _args(),
        settings=SimpleNamespace(database_url=_LIVE_DB_DSN, ib_host="127.0.0.1", ib_port=7497),
        provider_factory=provider_factory,
        fetch_fn=fetch_fn or default_fetch,
        prepare=prepare,
        context_factory=lambda provider, plan, run_id: ctx,
        stage_runner=stage_runner,
        notify=notify,
        status_file=tmp_path / "status.json",
        **kwargs,
    )
    return fetcher, seen


@pytest.fixture(autouse=True)
def _no_side_effects(monkeypatch):
    """No APR overlay reads and no ledger writes in these tests."""
    monkeypatch.setattr(hf.IbkrHistoryFetcher, "_load_provider_overlays", lambda self: None)
    outcomes: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        hf,
        "record_fetch_outcome",
        lambda cur, symbol, tf, status, fetched_at: outcomes.append((symbol, tf, status)),
    )
    refreshed: list[list[str]] = []
    monkeypatch.setattr(
        hf, "refresh_1d_bounds", lambda cur, symbols: refreshed.append(sorted(symbols)) or 0
    )
    return SimpleNamespace(outcomes=outcomes, refreshed=refreshed)


async def _run(fetcher: hf.IbkrHistoryFetcher) -> tuple[str, BaseException | None]:
    """BaseBatch.run() with the pool and metrics stubbed; returns the emitted status."""
    with (
        patch("src.core.agent.base_batch.create_pool", new_callable=AsyncMock) as pool,
        patch("src.core.agent.base_batch.JOB_COMPLETED_TOTAL") as completed,
        patch("src.core.agent.base_batch.JOB_DURATION_SECONDS"),
        patch("src.core.agent.base_batch.flush_and_shutdown_metrics"),
        patch.object(hf, "OHLCV_COVERAGE_SLA_BREACHED_SERIES"),
    ):
        pool.return_value = MagicMock(close=AsyncMock())
        error: BaseException | None = None
        try:
            await fetcher.run()
        except Exception as exc:  # noqa: BLE001 - the test inspects it
            error = exc
    (_, attrs), _ = completed.add.call_args
    return attrs["status"], error


# ---------------------------------------------------------------------------
# Singleton (CD-14), live lock
# ---------------------------------------------------------------------------


@_live
async def test_lock_held_elsewhere_exits_lock_held_without_touching_ibkr(tmp_path, capsys):
    name = f"test_ibkr_fetcher_{uuid.uuid4().hex[:8]}"
    holder = FetcherLock(_LIVE_DB_DSN, "test-holder", name=name)
    assert holder.acquire()
    try:
        fetcher, seen = _fetcher(tmp_path, _plan([_ranked("AAA")]), lock_factory=None)
        fetcher._lock_name = name
        status, error = await _run(fetcher)
    finally:
        holder.close()
    assert error is None
    assert status == "lock_held"
    assert LOCK_HELD_MESSAGE in capsys.readouterr().out
    assert seen["providers"] == 0
    assert "prepared" not in seen
    assert not (tmp_path / "status.json").exists()


@_live
async def test_two_concurrent_runs_exactly_one_reaches_the_provider(tmp_path):
    name = f"test_ibkr_fetcher_{uuid.uuid4().hex[:8]}"
    gate = asyncio.Event()
    calls = {"providers": 0}

    def provider_factory() -> Any:
        calls["providers"] += 1
        return _FakeProvider(gate=gate)

    fetchers = []
    for i in range(2):
        fetcher, _ = _fetcher(tmp_path / str(i), _plan([]), lock_factory=None)
        fetcher._lock_name = name
        fetcher._provider_factory = provider_factory
        fetchers.append(fetcher)

    finished: dict[int, tuple[str, float]] = {}
    started = time.monotonic()

    async def go(i: int) -> None:
        status, error = await _run(fetchers[i])
        assert error is None
        finished[i] = (status, time.monotonic() - started)
        gate.set()  # whichever finishes first releases the holder's blocked connect

    await asyncio.wait_for(asyncio.gather(go(0), go(1)), timeout=30)
    assert calls["providers"] == 1
    statuses = sorted(status for status, _ in finished.values())
    assert statuses == ["lock_held", "success"]
    held_elapsed = next(t for status, t in finished.values() if status == "lock_held")
    assert held_elapsed < 2.0


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


class _RecordingSyncConn:
    """psycopg-shaped: answers load_queue_config and the APR read, records every statement."""

    def __init__(self, log: list[str]) -> None:
        self.log = log

    def cursor(self) -> Any:
        conn = self

        class _Cur:
            def __enter__(self) -> _Cur:
                return self

            def __exit__(self, *exc: Any) -> bool:
                return False

            def execute(self, sql: str, params: Any = None) -> None:
                conn.log.append(sql)
                self.rows = [
                    ("infra.backfill.default_scopes", '{"compute": ["1d", "15m"]}'),
                    ("infra.bar_derivation.overlap_sessions", "20"),
                    ("infra.ibkr.inter_item_pause_s", "2.0"),
                ]

            def fetchall(self) -> list[tuple[str, str]]:
                return self.rows

        return _Cur()

    def close(self) -> None:
        return None


class _RecordingPool:
    def __init__(self, log: list[str]) -> None:
        self.log = log

    def acquire(self) -> Any:
        log = self.log

        class _Conn:
            async def fetch(self, sql: str, *params: Any) -> list[dict[str, Any]]:
                log.append(sql)
                if "FROM config_state" in sql:
                    return [
                        {
                            "config_key": "infra.backfill.empty_history_reverify_days",
                            "config_value": "90",
                        },
                        {
                            "config_key": "infra.ibkr.no_data_confirmation_chunks",
                            "config_value": "2",
                        },
                    ]
                if "FROM ohlcv_coverage" in sql:
                    return [
                        {
                            "symbol": "AAA",
                            "timeframe": "15m",
                            "earliest_timestamp": datetime(2010, 1, 4, tzinfo=UTC),
                            "latest_timestamp": datetime(2026, 9, 1, tzinfo=UTC),
                            "last_fetch_status": "ok",
                            "consecutive_failures": 0,
                            "last_fetched_at": datetime(2026, 9, 1, tzinfo=UTC),
                        }
                    ]
                return []

            async def fetchrow(self, sql: str, *params: Any) -> dict[str, Any]:
                log.append(sql)
                return {"tradier_owned": params[0] == "TRD"}

        class _Acquire:
            async def __aenter__(self) -> _Conn:
                return _Conn()

            async def __aexit__(self, *exc: Any) -> bool:
                return False

        return _Acquire()


async def test_dry_run_takes_no_lock_opens_no_provider_and_writes_nothing(tmp_path, monkeypatch):
    log: list[str] = []
    out = tmp_path / "dry.tsv"
    monkeypatch.setattr(
        hf._history_fetch,
        "_load_tf_fetch_config",
        lambda settings: {"1d": (7300, False), "15m": (7300, False)},
    )

    def no_lock() -> Any:
        raise AssertionError("dry run must not construct the lock")

    def no_provider() -> Any:
        raise AssertionError("dry run must not construct the provider")

    fetcher = hf.IbkrHistoryFetcher(
        _LIVE_DB_DSN,
        _args("--dry-run", "--dry-run-out", str(out)),
        settings=SimpleNamespace(database_url=_LIVE_DB_DSN),
        provider_factory=no_provider,
        lock_factory=no_lock,
        connect=lambda: _RecordingSyncConn(log),
        contracts_for=lambda dim: [SimpleNamespace(symbol="AAA"), SimpleNamespace(symbol="TRD")],
        status_file=tmp_path / "status.json",
    )
    with (
        patch("src.core.agent.base_batch.create_pool", new_callable=AsyncMock) as pool,
        patch("src.core.agent.base_batch.JOB_COMPLETED_TOTAL") as completed,
        patch("src.core.agent.base_batch.JOB_DURATION_SECONDS"),
        patch("src.core.agent.base_batch.flush_and_shutdown_metrics"),
    ):
        pool.return_value = _RecordingPool(log)
        pool.return_value.close = AsyncMock()
        await fetcher.run()
    (_, attrs), _ = completed.add.call_args
    assert attrs["status"] == "dry_run"
    assert log, "the dry run reads"
    assert all(sql.lstrip().upper().startswith(("SELECT", "/*")) for sql in log), log
    assert not any(word in sql.upper() for sql in log for word in ("INSERT", "UPDATE ", "DELETE"))
    lines = out.read_text().splitlines()
    assert lines[0].split("\t") == list(hf._TSV_COLUMNS)
    rows = [line.split("\t") for line in lines[1:]]
    assert {(r[1], r[2], r[13]) for r in rows} == {
        ("AAA", "15m", ""),
        ("AAA", "1d", ""),
        ("TRD", "15m", ""),
        ("TRD", "1d", "tradier_owned"),
    }
    assert not (tmp_path / "status.json").exists()


@pytest.mark.parametrize(
    ("argv", "named", "overlap"),
    [
        ((), False, 20),
        (("--symbols", "AAA"), True, 20),
        (("--symbols", "AAA", "--overlap-sessions", "5200"), True, 5200),
    ],
)
async def test_named_symbols_bypass_the_current_hold_and_overlap_overrides_apr(
    monkeypatch, argv, named, overlap
):
    """Plan 189-08: a caller that names series (ops_split_detect's re-fetch, ops_head_rerun)
    gets them asked even when current; --overlap-sessions overrides the APR overlap, so the
    split re-fetch re-asks the history D1 already holds. The timer run names none and keeps
    the current hold and the APR overlap."""
    log: list[str] = []
    monkeypatch.setattr(
        hf._history_fetch,
        "_load_tf_fetch_config",
        lambda settings: {"1d": (7300, False), "15m": (7300, False)},
    )
    fetcher = hf.IbkrHistoryFetcher(
        _LIVE_DB_DSN,
        _args(*argv),
        settings=SimpleNamespace(database_url=_LIVE_DB_DSN),
        connect=lambda: _RecordingSyncConn(log),
        contracts_for=lambda dim: [SimpleNamespace(symbol="AAA"), SimpleNamespace(symbol="TRD")],
    )
    plan = await fetcher.prepare(_RecordingPool(log))
    assert (plan.queue.current_after is None) is named
    assert plan.overlap_sessions == overlap


def test_negative_overlap_sessions_is_rejected():
    assert hf.validate_args(_args("--overlap-sessions", "-1")) is not None
    assert hf.validate_args(_args("--overlap-sessions", "0")) is None


# ---------------------------------------------------------------------------
# Scope resolution
# ---------------------------------------------------------------------------


def test_default_scope_union_is_deduplicated_and_has_no_1m():
    universe = {
        "compute": ["AAA", "BBB"],
        "compute_1d": ["AAA", "BBB", "CCC"],
        "backfill": ["AAA", "BBB", "CCC", "DDD"],
    }
    scopes = hf.resolve_scopes(_args(), _CONFIG.default_scopes)
    assert [dim for dim, _ in scopes] == ["compute", "compute_1d", "backfill"]
    candidates = hf.build_candidates(
        scopes,
        lambda dim: [SimpleNamespace(symbol=s) for s in universe[dim]],
        fetchable_timeframes={"1d", "1h", "15m", "5m", "1m"},
    )
    pairs = candidates.pairs
    assert len(pairs) == len(set(pairs))
    assert not any(tf == "1m" for _, tf in pairs)
    expected = (
        {(s, tf) for s in universe["compute"] for tf in ("1d", "1h", "15m", "5m")}
        | {(s, "1d") for s in universe["compute_1d"]}
        | {(s, tf) for s in universe["backfill"] for tf in ("1h", "15m")}
    )
    assert set(pairs) == expected
    # CCC is compute_1d and backfill only: never 5m.
    assert ("CCC", "5m") not in pairs


def test_explicit_scope_flags_resolve_one_scope_and_keep_the_timeframes_rule():
    assert hf.resolve_scopes(_args("--dimension", "compute"), _CONFIG.default_scopes) == [
        ("compute", ("1d", "1h", "15m", "5m"))
    ]
    assert hf.resolve_scopes(_args("--timeframes", "1h"), _CONFIG.default_scopes) == [
        ("compute", ("1h",))
    ]
    assert hf.validate_args(_args("--dimension", "backfill")) is not None
    assert hf.validate_args(_args("--dimension", "compute_1d", "--timeframes", "1d")) is None
    with pytest.raises(ValueError):
        hf.resolve_scopes(_args("--dimension", "live"), _CONFIG.default_scopes)


def test_symbols_narrow_by_contract_or_base_and_unknown_timeframes_are_reported():
    candidates = hf.build_candidates(
        [("compute", ("15m", "4x"))],
        lambda dim: [SimpleNamespace(symbol=s) for s in ("AAA", "ESZ6", "BBB")],
        symbols=["AAA", "ES"],
        fetchable_timeframes={"15m"},
    )
    assert candidates.pairs == [("AAA", "15m"), ("ESZ6", "15m")]
    assert candidates.unknown_timeframes == ["4x"]


def test_reset_target_parses_symbol_and_optional_timeframe():
    assert hf.parse_reset_target("AAPL") == ("AAPL", None)
    assert hf.parse_reset_target("AAPL:15m") == ("AAPL", "15m")
    with pytest.raises(ValueError):
        hf.parse_reset_target(":15m")


def test_last_session_close_is_the_latest_close_at_or_before_now():
    # Monday 2026-10-05 15:00 UTC is mid-session: the latest close is Friday's.
    close = hf.last_session_close(datetime(2026, 10, 5, 15, 0, tzinfo=UTC))
    assert close == datetime(2026, 10, 2, 20, 0, tzinfo=UTC)
    after = hf.last_session_close(datetime(2026, 10, 5, 21, 0, tzinfo=UTC))
    assert after == datetime(2026, 10, 5, 20, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Loop: budget, visited, failures, outcomes
# ---------------------------------------------------------------------------


async def test_budget_stops_taking_new_items(tmp_path):
    async def slow_fetch(ctx: Any, instrument: Any, row: Any, **kw: Any) -> ItemOutcome:
        seen["fetched"].append(row.symbol)
        await asyncio.sleep(0.1)
        return _outcome(row)

    items = [_ranked(s) for s in ("A1", "A2", "A3", "A4", "A5")]
    fetcher, seen = _fetcher(
        tmp_path, _plan(items), args=_args("--budget-minutes", "0.001"), fetch_fn=slow_fetch
    )
    status, error = await _run(fetcher)
    assert error is None
    assert status == "success"
    assert len(seen["fetched"]) <= 1
    assert fetcher.summary["budget_exhausted"] is True


async def test_a_repeated_item_is_processed_once(tmp_path, _no_side_effects):
    fetcher, seen = _fetcher(tmp_path, _plan([_ranked("AAA")], repeat_first=True))
    status, error = await _run(fetcher)
    assert error is None
    assert seen["fetched"] == [("AAA", "15m")]
    assert _no_side_effects.outcomes == [("AAA", "15m", "ok")]


async def test_gateway_unreachable_at_startup_fails_before_any_item(tmp_path):
    fetcher, seen = _fetcher(
        tmp_path, _plan([_ranked("AAA")]), provider=_FakeProvider(connects=False)
    )
    status, error = await _run(fetcher)
    assert status == "failure"
    assert isinstance(error, RuntimeError)
    assert "unreachable" in str(error)
    assert seen["fetched"] == []
    assert '"status": "failed"' in (tmp_path / "status.json").read_text()


async def test_gateway_lost_mid_run_stops_and_does_not_charge_the_item(tmp_path, _no_side_effects):
    async def fetch(ctx: Any, instrument: Any, row: Any, **kw: Any) -> ItemOutcome:
        seen["fetched"].append(row.symbol)
        if row.symbol == "BBB":
            return _outcome(row, "error", gateway_lost=True)
        return _outcome(row)

    items = [_ranked(s) for s in ("AAA", "BBB", "CCC")]
    fetcher, seen = _fetcher(tmp_path, _plan(items), fetch_fn=fetch)
    status, error = await _run(fetcher)
    assert status == "failure"
    assert isinstance(error, RuntimeError)
    assert seen["fetched"] == ["AAA", "BBB"]
    assert _no_side_effects.outcomes == [("AAA", "15m", "ok")]


async def test_one_outcome_write_per_item_with_its_status(tmp_path, _no_side_effects):
    statuses = {"AAA": "ok", "BBB": "no_data", "CCC": "error"}

    async def fetch(ctx: Any, instrument: Any, row: Any, **kw: Any) -> ItemOutcome:
        return _outcome(row, statuses[row.symbol])

    items = [_ranked(s) for s in statuses]
    fetcher, seen = _fetcher(tmp_path, _plan(items), fetch_fn=fetch)
    status, error = await _run(fetcher)
    assert error is None
    assert status == "partial"
    assert _no_side_effects.outcomes == [(s, "15m", st) for s, st in statuses.items()]
    # Every outcome write ran under the ledger writer role.
    assert seen["ctx"].conn.log.count("SET LOCAL ROLE bar_derivation_writer") == 3
    assert fetcher.summary["n_error"] == 1
    assert '"status": "partial"' in (tmp_path / "status.json").read_text()


async def test_gap_days_and_watchdog_tick_reach_the_item_fetch(tmp_path):
    received: dict[str, Any] = {}

    async def fetch(ctx: Any, instrument: Any, row: Any, **kw: Any) -> ItemOutcome:
        received.update(kw)
        kw["on_tick"]()
        return _outcome(row)

    fetcher, seen = _fetcher(tmp_path, _plan([_ranked("AAA", gap_days=42)]), fetch_fn=fetch)
    await _run(fetcher)
    assert received["gap_days"] == 42
    assert received["full_scan"] is False
    assert seen["notify"] >= 2  # the tick, plus the post-item ping


# ---------------------------------------------------------------------------
# Run-end stages: grid promotion, daily stage
# ---------------------------------------------------------------------------


def _grid_calls(seen: dict[str, Any]) -> list[list[str]]:
    return [argv for argv in seen["stages"] if "grid" in argv]


async def test_grid_promoted_when_5m_rows_landed_and_failure_is_partial(tmp_path):
    async def fetch(ctx: Any, instrument: Any, row: Any, **kw: Any) -> ItemOutcome:
        return _outcome(row, n_bars=10, n_grid_source_rows=10)

    fetcher, seen = _fetcher(tmp_path, _plan([_ranked("AAA", "5m")]), fetch_fn=fetch, stage_rc=1)
    status, error = await _run(fetcher)
    assert error is None
    grid = _grid_calls(seen)
    assert len(grid) == 1
    assert grid[0][-4:] == ["--stage", "grid", "--changed-only", "--apply"]
    assert status == "partial"


async def test_grid_not_promoted_without_5m_rows(tmp_path):
    fetcher, seen = _fetcher(tmp_path, _plan([_ranked("AAA", "15m")]))
    status, error = await _run(fetcher)
    assert error is None
    assert _grid_calls(seen) == []
    assert status == "success"


async def test_1d_items_run_split_detection_daily_stage_then_refresh_the_ledger(
    tmp_path, _no_side_effects
):
    since = datetime(2006, 10, 2, tzinfo=UTC)

    async def fetch(ctx: Any, instrument: Any, row: Any, **kw: Any) -> ItemOutcome:
        return _outcome(row, n_bars=5, derive_1d_since=since)

    items = [_ranked("BBB", "1d"), _ranked("AAA", "1d")]
    fetcher, seen = _fetcher(tmp_path, _plan(items), fetch_fn=fetch)
    status, error = await _run(fetcher)
    assert error is None
    assert status == "success"
    split, daily = seen["stages"]
    assert "ops_split_detect.py" in split[1] and "--fetch-run-id" in split
    assert daily[-5:] == ["--stage", "daily", "--symbols", "AAA,BBB", "--apply"]
    assert _no_side_effects.refreshed == [["AAA", "BBB"]]


async def test_failed_daily_stage_skips_the_ledger_refresh_and_is_partial(
    tmp_path, _no_side_effects
):
    async def fetch(ctx: Any, instrument: Any, row: Any, **kw: Any) -> ItemOutcome:
        return _outcome(row, n_bars=5, derive_1d_since=datetime(2006, 10, 2, tzinfo=UTC))

    fetcher, seen = _fetcher(tmp_path, _plan([_ranked("AAA", "1d")]), fetch_fn=fetch, stage_rc=1)
    status, error = await _run(fetcher)
    assert status == "partial"
    assert _no_side_effects.refreshed == []


def test_the_fetcher_writes_no_backfill_status():
    """Plan 189-08: the fetch path stops writing backfill_status (promotion reads
    bar_integrity verdicts since plan 185-41); the run-end 1d step only refreshes the
    ledger bounds."""
    source = Path(hf.__file__).read_text()
    assert "mark_fetch_complete" not in source
    assert "INSERT INTO backfill_status" not in source


# ---------------------------------------------------------------------------
# --rebuild-coverage (189-06: the ledger rebuild before the first real run)
# ---------------------------------------------------------------------------


class _CountingLock:
    def __init__(self, grant: bool) -> None:
        self.grant = grant
        self.closed = False

    def acquire(self) -> bool:
        return self.grant

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("granted", [True, False])
async def test_rebuild_coverage_runs_under_the_lock_without_ibkr(tmp_path, monkeypatch, granted):
    calls: list[Any] = []
    monkeypatch.setattr(
        hf, "rebuild_from_stored_state", lambda cur, symbols=None: calls.append(symbols) or 7
    )
    lock = _CountingLock(granted)
    conn = _FakeConn()
    conn.close = lambda: None  # type: ignore[attr-defined]
    fetcher, seen = _fetcher(
        tmp_path,
        _plan([_ranked("AAA")]),
        args=_args("--rebuild-coverage"),
        lock_factory=lambda: lock,
        connect=lambda: conn,
    )
    status, error = await _run(fetcher)
    assert error is None
    assert seen["providers"] == 0 and "prepared" not in seen
    assert not (tmp_path / "status.json").exists()
    if granted:
        assert status == "success"
        assert calls == [None]  # every series
        assert conn.log == ["SET LOCAL ROLE bar_derivation_writer"]
        assert lock.closed
    else:
        assert status == "lock_held"
        assert calls == []
