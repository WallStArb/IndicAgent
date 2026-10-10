"""OHLCVHistoryFetcher (phase 189 plan 04; renamed to the multi-provider name in phase 190):
singleton, dry run, scope, budget, failure paths, outcome writes and run-end stages.

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
from scripts.infrastructure.backfill import ohlcv_history_fetcher as hf
from scripts.infrastructure.backfill._fetcher_lock import LOCK_HELD_MESSAGE, FetcherLock
from scripts.infrastructure.backfill._history_fetch_item import ItemOutcome

_LIVE_DB_DSN = "postgresql://postgres:postgres@localhost:5432/indicagent"
_TODAY = date(2026, 10, 6)

_LANES = fq.LaneConfig(
    reconcile_interval_sessions=1,
    update_overlap_sessions_1d=20,
    update_overlap_days_5m=3,
    gap_fill_interval_days=7,
    parity_names_per_week=10,
    basis_tolerance_bp=10.0,
)
# Never a gap-fill session for any series: gap_fill_due is patched per test where it matters.
_SESSION_DAY = date(2026, 10, 5)

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


def _ranked(
    symbol: str, timeframe: str = "15m", gap_days: int = 0, latest: datetime | None = None
) -> fq.RankedItem:
    row = fq.CoverageRow(symbol, timeframe, None, latest, "ok", 0, None)
    return fq.RankedItem(row, (False,), False, -1, gap_days, 1)


def _ranked_p(symbol: str, timeframe: str = "15m", provider: str = "ibkr") -> fq.RankedItem:
    row = fq.CoverageRow(symbol, timeframe, None, None, "ok", 0, None, None, provider)
    return fq.RankedItem(row, (False,), False, -1, 0, 1)


class _FakeQueue:
    """Hands out its items in order, honoring visited (like PriorityQueue.next)."""

    def __init__(self, items: list[fq.RankedItem], *, repeat_first: bool = False) -> None:
        self.items = items
        self.repeat_first = repeat_first

    async def load(self, pool: Any) -> None:
        return None

    async def next(self, pool: Any, visited: set[tuple[str, ...]]) -> fq.CoverageRow | None:
        if self.repeat_first:
            return self.items[0].row
        for item in self.items:
            if (item.row.provider, item.row.symbol, item.row.timeframe) not in visited:
                return item.row
        return None

    def ranked_snapshot(self) -> list[fq.RankedItem]:
        return list(self.items)

    def held_snapshot(self) -> list[tuple[fq.RankedItem, str]]:
        return []


def _plan(
    items: list[fq.RankedItem],
    *,
    providers: frozenset[str] | None = None,
    plans: dict[str, fq.ProviderPlan] | None = None,
    **queue_kwargs: Any,
) -> hf.RunPlan:
    symbols = {i.row.symbol for i in items}
    return hf.RunPlan(
        config=_CONFIG,
        queue=_FakeQueue(items, **queue_kwargs),
        candidates=hf.Candidates(
            pairs=[(i.row.symbol, i.row.timeframe) for i in items],
            instruments={s: SimpleNamespace(symbol=s) for s in symbols},
        ),
        tf_fetch_config={},
        overlap_sessions=0,
        inter_item_pause_s=0.0,
        lanes=_LANES,
        session_day=_SESSION_DAY,
        providers=(
            frozenset(providers)
            if providers is not None
            else frozenset({i.row.provider for i in items} or {"ibkr"})
        ),
        plans=plans or {},
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
) -> tuple[hf.OHLCVHistoryFetcher, dict[str, Any]]:
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

    async def no_escalation(pool: Any, fetch_run_id: str, lanes: Any) -> dict[str, str]:
        seen.setdefault("judged", []).append(fetch_run_id)
        return {}

    kwargs.setdefault("overlap_judge", no_escalation)
    fetcher = hf.OHLCVHistoryFetcher(
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
    """No APR overlay reads, no ledger writes, no gap-fill session and no overlap reads (the
    1d judge and the 5m waiver come through their seams) in these tests. The overlays are
    patched at the _history_fetch loaders, so the fetcher's real overlay split and each
    registry entry's load_overlays hook still run."""
    for loader in (
        "_load_ibkr_chunk_days_config",
        "_load_ibkr_hist_timeout_config",
        "_load_ibkr_retry_config",
        "_load_ibkr_venue_fallback_config",
        "_load_ibkr_rate_limit_config",
        "_load_ohlcv_insert_batch_size_config",
        "_load_gap_cluster_max_days_config",
    ):
        monkeypatch.setattr(hf._history_fetch, loader, lambda settings: None)
    monkeypatch.setattr(hf, "gap_fill_due", lambda symbol, tf, day, interval: False)
    outcomes: list[tuple[str, str, str, str]] = []
    monkeypatch.setattr(
        hf,
        "record_fetch_outcome",
        lambda cur, symbol, tf, status, fetched_at, *, provider="ibkr": outcomes.append(
            (symbol, tf, status, provider)
        ),
    )
    refreshed: list[list[str]] = []
    monkeypatch.setattr(
        hf, "refresh_1d_bounds", lambda cur, symbols: refreshed.append(sorted(symbols)) or 0
    )
    return SimpleNamespace(outcomes=outcomes, refreshed=refreshed)


async def _run(fetcher: hf.OHLCVHistoryFetcher) -> tuple[str, BaseException | None]:
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
    """psycopg-shaped: answers load_queue_config, load_lane_config and the APR read, records
    every statement."""

    def __init__(self, log: list[str], parity: int = 10, scopes: str | None = None) -> None:
        self.log = log
        self.parity = parity
        self.scopes = scopes or '{"compute": ["1d", "15m"]}'

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
                    ("infra.backfill.default_scopes", conn.scopes),
                    ("infra.ibkr.inter_item_pause_s", "2.0"),
                    # the planner-input APR keys (190-03): load_queue_config raises without them
                    ("infra.ibkr.history_request_timeout", "900"),
                    ("infra.ibkr.history_request_retries", "2"),
                    ("infra.ibkr.rate_limit_window_sec", "600.0"),
                    ("infra.ibkr.no_data_confirmation_chunks", "2"),
                    ("infra.backfill.ibkr_1d_reconcile_interval_days", "1"),
                    ("infra.backfill.update_overlap_sessions_1d", "20"),
                    ("infra.backfill.update_overlap_days_5m", "3"),
                    ("infra.backfill.gap_fill_interval_days", "7"),
                    ("infra.backfill.grid_parity_sample_names_per_week", str(conn.parity)),
                    ("threshold.bar_integrity.fallback_basis_tolerance_bp", "10"),
                ]

            def fetchall(self) -> list[tuple[str, str]]:
                return self.rows

        return _Cur()

    def close(self) -> None:
        return None


class _RecordingPool:
    def __init__(
        self,
        log: list[str],
        eligible: tuple[str, ...] = (),
        coverage_provider: str = "ibkr",
    ) -> None:
        self.log = log
        self.eligible = eligible
        self.coverage_provider = coverage_provider

    def acquire(self) -> Any:
        log = self.log
        eligible = self.eligible
        coverage_provider = self.coverage_provider

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
                if "ohlcv_intraday_raw_archive" in sql:
                    return [{"symbol": s} for s in eligible]
                if "FROM ohlcv_coverage" in sql:
                    return [
                        {
                            "symbol": "AAA",
                            "timeframe": "15m",
                            "provider": coverage_provider,
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

    fetcher = hf.OHLCVHistoryFetcher(
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
    col = hf._TSV_COLUMNS.index
    held = col("held_reason")
    lane = col("lane")
    assert {(r[col("symbol")], r[col("timeframe")], r[held]) for r in rows} == {
        ("AAA", "15m", ""),
        ("AAA", "1d", ""),
        ("TRD", "15m", ""),
        ("TRD", "1d", ""),
    }
    # The provider column sits immediately after symbol and today every row is the ibkr
    # plane (phase 190 plan 04; the parity gate is column-aware, owned by 190-06).
    assert col("provider") == col("symbol") + 1
    assert {r[col("provider")] for r in rows} == {"ibkr"}
    assert "tradier_owned" not in out.read_text()
    # AAA 15m holds a ledger row (update lane); the rest were never fetched (backfill).
    assert [(r[col("symbol")], r[col("timeframe")]) for r in rows if r[lane] == "update"] == [
        ("AAA", "15m")
    ]
    assert {r[lane] for r in rows} == {"update", "backfill"}
    assert not any("tradier" in sql.lower() for sql in log)
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
    fetcher = hf.OHLCVHistoryFetcher(
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


def test_completed_session_closes_end_at_the_latest_close_at_or_before_now():
    # Monday 2026-10-05 15:00 UTC is mid-session: the latest close is Friday's.
    closes = hf.completed_session_closes(datetime(2026, 10, 5, 15, 0, tzinfo=UTC))
    assert closes[-1] == datetime(2026, 10, 2, 20, 0, tzinfo=UTC)
    after = hf.completed_session_closes(datetime(2026, 10, 5, 21, 0, tzinfo=UTC), 30)
    assert after[-1] == datetime(2026, 10, 5, 20, 0, tzinfo=UTC)
    assert len(after) >= 30 and after == sorted(after)


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
    assert _no_side_effects.outcomes == [("AAA", "15m", "ok", "ibkr")]


async def test_gateway_unreachable_at_startup_fails_before_any_item(tmp_path):
    fetcher, seen = _fetcher(
        tmp_path, _plan([_ranked("AAA")]), provider=_FakeProvider(connects=False)
    )
    status, error = await _run(fetcher)
    assert status == "failure"
    assert isinstance(error, RuntimeError)
    # The ibkr entry keeps the parsed wording, composed from its connect label.
    assert str(error) == "IBKR gateway unreachable at startup"
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
    assert _no_side_effects.outcomes == [("AAA", "15m", "ok", "ibkr")]


async def test_one_outcome_write_per_item_with_its_status(tmp_path, _no_side_effects):
    statuses = {"AAA": "ok", "BBB": "no_data", "CCC": "error"}

    async def fetch(ctx: Any, instrument: Any, row: Any, **kw: Any) -> ItemOutcome:
        return _outcome(row, statuses[row.symbol])

    items = [_ranked(s) for s in statuses]
    fetcher, seen = _fetcher(tmp_path, _plan(items), fetch_fn=fetch)
    status, error = await _run(fetcher)
    assert error is None
    assert status == "partial"
    assert _no_side_effects.outcomes == [(s, "15m", st, "ibkr") for s, st in statuses.items()]
    # Every outcome write ran under the ledger writer role.
    assert seen["ctx"].conn.log.count("SET LOCAL ROLE bar_derivation_writer") == 3
    assert fetcher.summary["n_error"] == 1
    assert '"status": "partial"' in (tmp_path / "status.json").read_text()


async def test_the_update_lane_span_and_watchdog_tick_reach_the_item_fetch(tmp_path):
    received: dict[str, Any] = {}

    async def fetch(ctx: Any, instrument: Any, row: Any, **kw: Any) -> ItemOutcome:
        received.update(kw)
        kw["on_tick"]()
        return _outcome(row)

    covered = _ranked("AAA", "5m", gap_days=42, latest=datetime(2026, 10, 5, 19, 55, tzinfo=UTC))
    fetcher, seen = _fetcher(tmp_path, _plan([covered]), fetch_fn=fetch)
    await _run(fetcher)
    assert "gap_days" not in received  # a short start waits for the gap-fill lane
    assert received["full_scan"] is False
    assert received["overlap_days"] == 3
    assert received["refetch"] is False
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
    # Split detection runs in-process under the run's lock (todo 507): no subprocess.
    assert seen["judged"] == [fetcher.summary["fetch_run_id"]]
    (daily,) = seen["stages"]
    assert not any("ops_split_detect" in arg for arg in daily)
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


async def test_no_derive_skips_the_daily_stage_and_the_ledger_refresh(tmp_path, _no_side_effects):
    """189-10 Task 1b: --no-derive leaves 1d answers in D1 only, so the caller can gate a
    d2-v2 dry run before any apply. The fetch and its ledger outcomes are unchanged."""

    async def fetch(ctx: Any, instrument: Any, row: Any, **kw: Any) -> ItemOutcome:
        return _outcome(row, n_bars=5, derive_1d_since=datetime(2006, 10, 2, tzinfo=UTC))

    items = [_ranked("BBB", "1d"), _ranked("AAA", "1d")]
    fetcher, seen = _fetcher(tmp_path, _plan(items), args=_args("--no-derive"), fetch_fn=fetch)
    status, error = await _run(fetcher)
    assert error is None
    assert status == "success"
    assert seen["stages"] == []
    assert _no_side_effects.refreshed == []
    assert sorted(o[0] for o in _no_side_effects.outcomes) == ["AAA", "BBB"]


def test_no_derive_defaults_off():
    assert _args().no_derive is False


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


# ---------------------------------------------------------------------------
# Plan 189-10 Task 1 (amended): the parity sample, the two lanes, the in-process escalation
# ---------------------------------------------------------------------------


async def _prepared(monkeypatch, *, parity: int, eligible: tuple[str, ...], argv=()) -> Any:
    log: list[str] = []
    monkeypatch.setattr(
        hf._history_fetch,
        "_load_tf_fetch_config",
        lambda settings: {tf: (7300, False) for tf in ("1d", "5m", "15m", "1h")},
    )
    fetcher = hf.OHLCVHistoryFetcher(
        _LIVE_DB_DSN,
        _args(*argv),
        settings=SimpleNamespace(database_url=_LIVE_DB_DSN),
        connect=lambda: _RecordingSyncConn(
            log, parity=parity, scopes='{"compute_1d": ["1d", "5m"]}'
        ),
        contracts_for=lambda dim: [SimpleNamespace(symbol=s) for s in ("AAA", "BBB", "CCC", "DDD")],
    )
    return await fetcher.prepare(_RecordingPool(log, eligible=eligible))


async def test_with_the_parity_count_at_zero_no_15m_or_1h_item_is_queued(monkeypatch):
    plan = await _prepared(monkeypatch, parity=0, eligible=("AAA", "BBB", "CCC"))
    assert {tf for _, tf in plan.candidates.pairs} == {"1d", "5m"}
    assert plan.parity == ()


async def test_the_parity_sample_adds_15m_and_1h_for_sampled_eligible_names_only(monkeypatch):
    plan = await _prepared(monkeypatch, parity=2, eligible=("AAA", "BBB", "CCC"))
    sampled = sorted({s for s, _ in plan.parity})
    assert len(sampled) == 2 and set(sampled) <= {"AAA", "BBB", "CCC"}
    assert set(plan.parity) == {(s, tf) for s in sampled for tf in ("15m", "1h")}
    assert set(plan.parity) <= set(plan.candidates.pairs)
    # Held once asked this ISO week; the archive is their destination (the item routes 15m/1h).
    week_start = fq.parity_week_start(datetime.now(UTC).date())
    assert all(plan.queue.current_after_by_series[p] == week_start for p in plan.parity)
    assert {"15m", "1h"} <= set(hf._history_fetch._ARCHIVE_TFS)
    lane = hf._TSV_COLUMNS.index("lane")
    sym = hf._TSV_COLUMNS.index("symbol")
    tf = hf._TSV_COLUMNS.index("timeframe")
    lanes = {(r[sym], r[tf]): r[lane] for r in hf.dry_run_rows(plan)}
    assert {key for key, value in lanes.items() if value == "parity"} == set(plan.parity)


async def test_an_explicit_run_gets_no_parity_sample(monkeypatch):
    plan = await _prepared(
        monkeypatch, parity=10, eligible=("AAA",), argv=("--symbols", "AAA", "--timeframes", "5m")
    )
    assert plan.parity == ()


async def test_the_gap_fill_session_plans_the_full_depth_and_parity_items_never_do(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(hf, "gap_fill_due", lambda symbol, tf, day, interval: symbol == "GAP")
    received: dict[tuple[str, str], dict[str, Any]] = {}

    async def fetch(ctx: Any, instrument: Any, row: Any, **kw: Any) -> ItemOutcome:
        received[(row.symbol, row.timeframe)] = kw
        return _outcome(row)

    latest = datetime(2026, 10, 5, 19, 55, tzinfo=UTC)
    items = [
        _ranked("GAP", "5m", latest=latest),
        _ranked("UPD", "5m", latest=latest),
        _ranked("GAP", "15m", latest=latest),
    ]
    plan = _plan(items)
    plan.parity = (("GAP", "15m"),)
    fetcher, _ = _fetcher(tmp_path, plan, fetch_fn=fetch)
    await _run(fetcher)
    assert (received[("GAP", "5m")]["full_scan"], received[("GAP", "5m")]["overlap_days"]) == (
        True,
        0,
    )
    assert (received[("UPD", "5m")]["full_scan"], received[("UPD", "5m")]["overlap_days"]) == (
        False,
        3,
    )
    assert (received[("GAP", "15m")]["full_scan"], received[("GAP", "15m")]["overlap_days"]) == (
        False,
        0,
    )
    assert fetcher.summary["lanes"] == {"gap_fill": 1, "update": 1, "parity": 1}


async def test_a_split_is_recorded_then_re_fetched_in_process_then_derived(tmp_path):
    """Todo 507: record, re-fetch, derive, in that order, inside this run and under its lock;
    no ops_split_detect subprocess and no lock refusal (the old exit 3)."""
    events: list[tuple[str, ...]] = []
    since = datetime(2006, 10, 2, tzinfo=UTC)

    async def fetch(ctx: Any, instrument: Any, row: Any, **kw: Any) -> ItemOutcome:
        events.append(("fetch", row.symbol, row.timeframe, str(kw["refetch"])))
        return _outcome(row, n_bars=5, derive_1d_since=since)

    async def judge(pool: Any, fetch_run_id: str, lanes: Any) -> dict[str, str]:
        events.append(("record", "AAA"))
        return {"AAA": "split_recorded"}

    async def stage_runner(argv: list[str]) -> int:
        events.append(("stage", argv[argv.index("--stage") + 1]))
        return 0

    lock = _CountingLock(True)
    fetcher, seen = _fetcher(
        tmp_path,
        _plan([_ranked("AAA", "1d"), _ranked("BBB", "1d")]),
        fetch_fn=fetch,
        overlap_judge=judge,
        lock_factory=lambda: lock,
    )
    fetcher._run_stage = stage_runner
    status, error = await _run(fetcher)
    assert error is None and status == "success"
    assert events == [
        ("fetch", "AAA", "1d", "False"),
        ("fetch", "BBB", "1d", "False"),
        ("record", "AAA"),
        ("fetch", "AAA", "1d", "True"),
        ("stage", "daily"),
    ]
    assert lock.closed
    assert fetcher.summary["escalated"] == {"AAA/1d": "split_recorded"}
    assert fetcher.summary["stages"]["escalation"] == 0


def _pairs(ratio: float, n: int = 30) -> tuple[tuple[float, float], ...]:
    return tuple(((100.0 + i) * ratio, 100.0 + i) for i in range(n))


@pytest.mark.parametrize(("ratio", "escalates"), [(2.0, True), (1.0, False)])
async def test_a_5m_overlap_breach_escalates_to_a_waived_full_depth_refetch(
    tmp_path, ratio, escalates
):
    calls: list[tuple[str, dict[str, Any]]] = []

    async def fetch(ctx: Any, instrument: Any, row: Any, **kw: Any) -> ItemOutcome:
        calls.append((row.symbol, kw))
        pairs = () if kw["refetch"] else _pairs(ratio)
        return _outcome(row, n_bars=30, n_grid_source_rows=30, overlap_pairs=pairs)

    async def waiver(pool: Any, symbol: str, timeframe: str, before: datetime) -> bool:
        return True

    fetcher, seen = _fetcher(tmp_path, _plan([_ranked("AAA", "5m")]), fetch_fn=fetch, waiver=waiver)
    status, error = await _run(fetcher)
    assert error is None and status == "success"
    refetches = [kw for _, kw in calls if kw["refetch"]]
    if escalates:
        assert len(refetches) == 1
        assert refetches[0]["full_scan"] is True and refetches[0]["waived"] is True
        assert fetcher.summary["escalated"] == {"AAA/5m": "ratio_outside_tolerance"}
    else:
        assert refetches == []
        assert fetcher.summary["escalated"] == {}


async def test_an_unwaived_5m_breach_is_reported_not_refetched_and_the_run_is_partial(tmp_path):
    """Without a recorded corporate action the ingress contract would refuse the full-depth
    rewrite, so the escalation records the finding instead of spending about 49 requests."""
    calls: list[dict[str, Any]] = []
    reported: list[tuple[str, str]] = []

    async def fetch(ctx: Any, instrument: Any, row: Any, **kw: Any) -> ItemOutcome:
        calls.append(kw)
        return _outcome(row, n_bars=30, n_grid_source_rows=30, overlap_pairs=_pairs(2.0))

    async def waiver(pool: Any, symbol: str, timeframe: str, before: datetime) -> bool:
        return False

    fetcher, _ = _fetcher(
        tmp_path,
        _plan([_ranked("AAA", "5m")]),
        fetch_fn=fetch,
        waiver=waiver,
        report_overlap=lambda symbol, tf, verdict: reported.append((symbol, tf)),
    )
    status, error = await _run(fetcher)
    assert error is None and status == "partial"
    assert [kw["refetch"] for kw in calls] == [False]
    assert reported == [("AAA", "5m")]
    assert fetcher.summary["stages"]["escalation"] == 1


async def test_a_failed_overlap_judgment_is_partial_and_still_derives(tmp_path):
    async def fetch(ctx: Any, instrument: Any, row: Any, **kw: Any) -> ItemOutcome:
        return _outcome(row, n_bars=5, derive_1d_since=datetime(2006, 10, 2, tzinfo=UTC))

    async def judge(pool: Any, fetch_run_id: str, lanes: Any) -> dict[str, str]:
        raise ValueError("AAA: overlap pairs are unusable")

    fetcher, seen = _fetcher(
        tmp_path, _plan([_ranked("AAA", "1d")]), fetch_fn=fetch, overlap_judge=judge
    )
    status, error = await _run(fetcher)
    assert error is None and status == "partial"
    (daily,) = seen["stages"]
    assert daily[-5:] == ["--stage", "daily", "--symbols", "AAA", "--apply"]
    assert fetcher.summary["stages"]["escalation"] == 1


async def test_a_new_unclassified_rescale_makes_the_run_partial_and_is_still_refetched(tmp_path):
    """Plan 185-51 (todo 515): the 1d judge held a name whose rescale is no split ratio. The
    run is partial (a new integrity fact), the name's history is re-asked so D1 holds the
    vendor's restated answer, and the daily stage still runs: bar_derivation skips the held
    name itself, so no rewrite is applied."""
    calls: list[tuple[str, bool]] = []

    async def fetch(ctx: Any, instrument: Any, row: Any, **kw: Any) -> ItemOutcome:
        calls.append((row.symbol, kw["refetch"]))
        return _outcome(row, n_bars=5, derive_1d_since=datetime(2006, 10, 2, tzinfo=UTC))

    async def judge(pool: Any, fetch_run_id: str, lanes: Any) -> dict[str, str]:
        return {"CTVA": "unclassified_rescale"}

    fetcher, seen = _fetcher(
        tmp_path, _plan([_ranked("CTVA", "1d")]), fetch_fn=fetch, overlap_judge=judge
    )
    status, error = await _run(fetcher)
    assert error is None and status == "partial"
    assert calls == [("CTVA", False), ("CTVA", True)]
    assert fetcher.summary["escalated"] == {"CTVA/1d": "unclassified_rescale"}
    assert fetcher.summary["stages"]["escalation"] == 1
    (daily,) = seen["stages"]
    assert daily[-5:] == ["--stage", "daily", "--symbols", "CTVA", "--apply"]


def test_the_1d_judge_reads_the_split_rule_keys_and_acts_through_ops_split_detect():
    import inspect

    source = inspect.getsource(hf.OHLCVHistoryFetcher._judge_daily_overlap)
    assert "SPLIT_RULE_KEYS" in source and "split_rule_from_apr" in source
    assert "act_on_detections" in source and "record_split" not in source


def test_the_5m_waiver_never_counts_a_void_row():
    assert "action_type <> 'void'" in hf._WAIVER_SQL


# ---------------------------------------------------------------------------
# Provider registry dispatch (phase 190 plan 04): the loop is vendor-blind
# ---------------------------------------------------------------------------


class _FakeLeaf:
    def __init__(self, name: str, connects: bool = True) -> None:
        self.name = name
        self.connects = connects
        self.connect_calls = 0
        self.disconnect_calls = 0

    async def connect(self) -> bool:
        self.connect_calls += 1
        return self.connects

    async def disconnect(self) -> None:
        self.disconnect_calls += 1


class _FakeEntry:
    """A registry entry duck type: leaf_factory + fetch hook + overlay loader."""

    def __init__(self, name: str, leaf: _FakeLeaf, *, raises: bool = False) -> None:
        self.name = name
        self.leaf = leaf
        self.raises = raises
        self.connect_failure_label = name
        self.fetch_calls: list[tuple[Any, ...]] = []
        self.overlays = 0

    def leaf_factory(self, settings: Any, args: Any) -> Any:
        return self.leaf

    async def fetch(self, ctx: Any, leaf: Any, instrument: Any, row: Any, **kw: Any) -> ItemOutcome:
        self.fetch_calls.append((row.provider, row.symbol, row.timeframe, kw.get("plan")))
        if self.raises:
            raise RuntimeError(f"{self.name} entry fetch exploded")
        return ItemOutcome(row.symbol, row.timeframe, "ok")

    def load_overlays(self, settings: Any) -> None:
        self.overlays += 1


async def test_two_provider_registry_dispatches_each_item_to_its_own_entry(tmp_path):
    leaf_a, leaf_b = _FakeLeaf("provA"), _FakeLeaf("provB")
    entry_a, entry_b = _FakeEntry("provA", leaf_a), _FakeEntry("provB", leaf_b)
    items = [_ranked_p("A1", provider="provA"), _ranked_p("B1", provider="provB")]
    fetcher, _ = _fetcher(tmp_path, _plan(items), registry={"provA": entry_a, "provB": entry_b})
    status, error = await _run(fetcher)
    assert error is None and status == "success"
    assert [(p, s, tf) for p, s, tf, _ in entry_a.fetch_calls] == [("provA", "A1", "15m")]
    assert [(p, s, tf) for p, s, tf, _ in entry_b.fetch_calls] == [("provB", "B1", "15m")]


async def test_only_providers_in_the_plan_get_connected(tmp_path):
    leaf_a, leaf_ghost = _FakeLeaf("provA"), _FakeLeaf("ghost")
    entry_a, entry_ghost = _FakeEntry("provA", leaf_a), _FakeEntry("ghost", leaf_ghost)
    plan = _plan([_ranked_p("A1", provider="provA")], providers={"provA"})
    fetcher, _ = _fetcher(tmp_path, plan, registry={"provA": entry_a, "ghost": entry_ghost})
    status, error = await _run(fetcher)
    assert error is None and status == "success"
    assert leaf_a.connect_calls == 1
    assert leaf_ghost.connect_calls == 0 and entry_ghost.fetch_calls == []


async def test_dispatch_passes_the_provider_plan_to_the_entry_fetch(tmp_path):
    plan_a = fq.ProviderPlan(
        name="provA",
        request_timeout_s=5.5,
        request_retries=3,
        rate_limit_window_s=1.0,
        confirmation_chunks=2,
        inter_item_pause_s=0.0,
    )
    entry_a = _FakeEntry("provA", _FakeLeaf("provA"))
    run_plan = _plan([_ranked_p("A1", provider="provA")], plans={"provA": plan_a})
    fetcher, _ = _fetcher(tmp_path, run_plan, registry={"provA": entry_a})
    status, error = await _run(fetcher)
    assert error is None and status == "success"
    assert entry_a.fetch_calls[0][3] is plan_a


async def test_a_raising_entry_fetch_becomes_an_error_outcome_with_no_ibkr_fallback(
    tmp_path, _no_side_effects
):
    ghost = _FakeEntry("ghost", _FakeLeaf("ghost"), raises=True)
    fetched: list[str] = []

    async def fetch(ctx: Any, instrument: Any, row: Any, **kw: Any) -> ItemOutcome:
        fetched.append(row.symbol)
        return _outcome(row)

    items = [_ranked_p("G1", provider="ghost"), _ranked_p("A1")]
    fetcher, _ = _fetcher(
        tmp_path, _plan(items), fetch_fn=fetch, registry={**hf._PROVIDER_REGISTRY, "ghost": ghost}
    )
    status, error = await _run(fetcher)
    assert error is None
    assert status == "partial"
    assert fetched == ["A1"]  # the ibkr path ran only its own item, never the ghost's
    assert ("G1", "15m", "error", "ghost") in _no_side_effects.outcomes
    assert ("A1", "15m", "ok", "ibkr") in _no_side_effects.outcomes


def test_the_ibkr_registry_entry_holds_the_concrete_leaf_construction():
    entry = hf._PROVIDER_REGISTRY["ibkr"]
    leaf = entry.leaf_factory(
        SimpleNamespace(ib_host="127.0.0.9", ib_port=7498), _args("--client-id", "77")
    )
    assert type(leaf).__name__ == "IBKRProvider"
    assert leaf._host == "127.0.0.9" and leaf._port == 7498 and leaf._client_id == 77


async def test_the_ibkr_entry_fetch_wraps_the_injected_fetch_path(tmp_path):
    ibkr_plan = fq.ProviderPlan(
        name="ibkr",
        request_timeout_s=900.0,
        request_retries=2,
        rate_limit_window_s=600.0,
        confirmation_chunks=2,
        inter_item_pause_s=0.0,
    )
    received: dict[str, Any] = {}

    async def fetch(ctx: Any, instrument: Any, row: Any, **kw: Any) -> ItemOutcome:
        received.update(ctx=ctx, **kw)
        return _outcome(row)

    run_plan = _plan([_ranked("AAA")], plans={"ibkr": ibkr_plan})
    fetcher, seen = _fetcher(tmp_path, run_plan, fetch_fn=fetch)
    status, error = await _run(fetcher)
    assert error is None and status == "success"
    assert received["provider_plan"] is ibkr_plan
    assert received["ctx"].plan is ibkr_plan  # the hook carries the plan in the context
    assert received["config"] is run_plan.config
    assert received["full_scan"] is False and received["refetch"] is False


async def test_unknown_provider_fails_fast_at_prepare(monkeypatch):
    """A plan that could dispatch an unregistered provider is refused in prepare, never
    mid-loop (the guard runs on the loaded queue, so a held row fails the run too)."""
    log: list[str] = []
    monkeypatch.setattr(
        hf._history_fetch,
        "_load_tf_fetch_config",
        lambda settings: {"1d": (7300, False), "15m": (7300, False)},
    )

    def ghost_ranked(self: Any) -> list[fq.RankedItem]:
        row = fq.CoverageRow("AAA", "15m", None, None, "ok", 0, None, None, "ghost")
        return [fq.RankedItem(row, (False,), False, -1, 0, 1)]

    monkeypatch.setattr(fq.PriorityQueue, "ranked_snapshot", ghost_ranked)
    fetcher = hf.OHLCVHistoryFetcher(
        _LIVE_DB_DSN,
        _args(),
        settings=SimpleNamespace(database_url=_LIVE_DB_DSN),
        connect=lambda: _RecordingSyncConn(log),
        contracts_for=lambda dim: [SimpleNamespace(symbol="AAA")],
    )
    with pytest.raises(RuntimeError, match="ghost"):
        await fetcher.prepare(_RecordingPool(log))


async def test_a_foreign_connect_failure_names_the_provider(tmp_path):
    leaf = _FakeLeaf("provX", connects=False)
    entry = _FakeEntry("provX", leaf)
    fetcher, _ = _fetcher(
        tmp_path, _plan([_ranked_p("A1", provider="provX")]), registry={"provX": entry}
    )
    status, error = await _run(fetcher)
    assert status == "failure"
    assert str(error) == "provX unreachable at startup"


async def test_each_connected_provider_loads_its_own_overlays(tmp_path):
    entry_a = _FakeEntry("provA", _FakeLeaf("provA"))
    entry_b = _FakeEntry("provB", _FakeLeaf("provB"))
    entry_idle = _FakeEntry("idle", _FakeLeaf("idle"))
    fetcher, _ = _fetcher(
        tmp_path,
        _plan([_ranked_p("A1", provider="provA")], providers={"provA", "provB"}),
        registry={"provA": entry_a, "provB": entry_b, "idle": entry_idle},
    )
    status, error = await _run(fetcher)
    assert error is None and status == "success"
    assert entry_a.overlays == 1 and entry_b.overlays == 1 and entry_idle.overlays == 0


async def test_gateway_lost_records_provider_symbol_and_timeframe(tmp_path):
    lost = _FakeEntry("provA", _FakeLeaf("provA"))

    async def fetch(ctx: Any, leaf: Any, instrument: Any, row: Any, **kw: Any) -> ItemOutcome:
        lost.fetch_calls.append(row.symbol)
        return ItemOutcome(
            row.symbol, row.timeframe, "error", provider=row.provider, gateway_lost=True
        )

    lost.fetch = fetch  # type: ignore[method-assign]
    items = [_ranked_p("A1", provider="provA"), _ranked_p("B1", provider="provA")]
    fetcher, _ = _fetcher(tmp_path, _plan(items), registry={"provA": lost})
    status, error = await _run(fetcher)
    assert status == "failure"
    assert isinstance(error, RuntimeError)
    assert lost.fetch_calls == ["A1"]
    assert fetcher.summary["gateway_lost"] == "provA/A1/15m"


def test_unknown_providers_lists_ranked_and_held_ghosts():
    ghost_row = fq.CoverageRow("G1", "15m", None, None, "ok", 0, None, None, "ghost")
    held_row = fq.CoverageRow("H1", "1d", None, None, "ok", 0, None, None, "wraith")
    ibkr_row = fq.CoverageRow("A1", "5m", None, None, "ok", 0, None, None, "ibkr")
    queue = SimpleNamespace(
        ranked_snapshot=lambda: [fq.RankedItem(ghost_row, (), False, -1, 0, 1)],
        held_snapshot=lambda: [(fq.RankedItem(held_row, (), False, -1, 0, 1), "current")],
    )
    assert hf._unknown_providers(queue, ["ibkr"]) == ["ghost", "wraith"]
    queue.ranked_snapshot = lambda: [fq.RankedItem(ibkr_row, (), False, -1, 0, 1)]  # type: ignore[method-assign]
    queue.held_snapshot = lambda: []  # type: ignore[method-assign]
    assert hf._unknown_providers(queue, ["ibkr"]) == []
