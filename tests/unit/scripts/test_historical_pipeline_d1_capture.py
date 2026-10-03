"""Wiring tests for D1 capture and the history lease in the historical pipeline
(phase 185 plan 09), all against fakes -- no IBKR, no database.

main() is driven end to end with every external dependency patched at module
attribute level (provider, DB connections, APR loaders, empty-history helpers),
so the tests exercise the real fetch loop: what kwargs reach the provider per
timeframe, where the sink flushes, where the lease checkpoints, and what happens
when a flush fails or the lease times out.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from scripts.infrastructure.backfill import _empty_history as empty_history
from scripts.infrastructure.backfill import (
    infrastructure_run_historical_pipeline as pipeline,
)
from src.core.models import AssetClass
from src.core.resource_lease import LeaseTimeout
from src.providers.base import OHLCVBar

_TEST_RUN_ID = "d1-wiring-test-run-id"


class FakeLease:
    def __init__(self) -> None:
        self.checkpoints = 0
        self.released = False
        self.closed = False
        self.timeout_s: float | None = None

    def acquire(self, timeout_s: float | None) -> None:
        self.timeout_s = timeout_s

    def checkpoint(self) -> bool:
        self.checkpoints += 1
        return False

    def release(self) -> None:
        self.released = True

    def close(self) -> None:
        self.closed = True


class FakeSink:
    instances: list[FakeSink] = []

    def __init__(self, conn, *, caller: str, max_buffer_rows: int = 50_000) -> None:
        self.conn = conn
        self.caller = caller
        self.max_buffer_rows = max_buffer_rows
        self.requests: list[object] = []
        self.observations: list[tuple[object, list]] = []
        self.total_requests = 0
        self.total_observations = 0
        self.flushes = 0
        self.fail_flushes_from: int | None = None
        FakeSink.instances.append(self)

    def on_request(self, record) -> None:
        self.requests.append(record)

    def take_requests(self, request_ids) -> list:
        """Plan 12: the atomic persist helper drains the chunk's requests."""
        wanted = {str(rid) for rid in request_ids}
        taken = [rec for rec in self.requests if str(rec.request_id) in wanted]
        self.requests = [rec for rec in self.requests if str(rec.request_id) not in wanted]
        return taken

    def on_observation(self, record, bars) -> None:
        self.observations.append((record, bars))

    def pending(self) -> int:
        return len(self.requests) + len(self.observations)

    def flush(self) -> tuple[int, int]:
        self.flushes += 1
        if self.fail_flushes_from is not None and self.flushes >= self.fail_flushes_from:
            raise RuntimeError("D1 flush failed")
        n = (len(self.requests), len(self.observations))
        self.total_requests += n[0]
        self.total_observations += n[1]
        self.requests = []
        self.observations = []
        return n


def _bars(symbol: str, tf: str, n: int = 4) -> list[OHLCVBar]:
    return [
        OHLCVBar(
            symbol=symbol,
            timeframe=tf,
            timestamp=datetime(2024, 1, 2 + i, tzinfo=UTC),
            open=100.0 + i,
            high=101.0 + i,
            low=99.0 + i,
            close=100.5 + i,
            volume=1_000 * (i + 1),
            source="ibkr",
        )
        for i in range(n)
    ]


def _record(kwargs: dict, *, route: str = "SMART") -> SimpleNamespace:
    return SimpleNamespace(
        request_id=f"{kwargs['symbol']}-{route}-{kwargs['timeframe']}",
        fetch_run_id=kwargs.get("fetch_run_id"),
        symbol=kwargs["symbol"],
        timeframe=kwargs["timeframe"],
        route=route,
    )


class FakeProvider:
    instances: list[FakeProvider] = []
    last_fetch_failed_chunks = 0

    def __init__(self, **kwargs) -> None:
        self.calls: list[dict] = []
        FakeProvider.instances.append(self)

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> bool:
        return True

    def is_connected(self) -> bool:
        return True

    async def qualify_instrument(self, instrument) -> bool:
        return True

    async def get_head_timestamp(self, symbol: str):
        return (None, "fake head lookup")

    async def fetch_historical_bars(self, **kwargs) -> list[OHLCVBar]:
        self.calls.append(kwargs)
        bars = _bars(kwargs["symbol"], kwargs["timeframe"])
        on_request = kwargs.get("on_request")
        on_observation = kwargs.get("on_observation")
        on_chunk = kwargs.get("on_chunk")
        if on_request is None:
            if on_chunk is not None:
                await on_chunk(bars)
            return bars
        if kwargs["timeframe"] == "1d":
            # SMART answer then a former-venue recovery, two requests, two
            # observation deliveries (the venue-walk shape from plan 03).
            smart = _record(kwargs)
            on_request(smart)
            if on_observation is not None:
                on_observation(smart, bars[:2])
            venue = _record(kwargs, route="NYSE")
            on_request(venue)
            if on_observation is not None:
                on_observation(venue, bars[2:])
        else:
            # Intraday: request records only, never observations (D-02/D-20).
            on_request(_record(kwargs))
        if on_chunk is not None:
            await on_chunk(bars)  # the real walk fires it after the record (todo 462 order)
        return bars


class FakeCursor:
    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, *args, **kwargs) -> None:
        return None

    def fetchall(self) -> list:
        return []


class FakeConn:
    def __init__(self) -> None:
        self.closed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor()

    def close(self) -> None:
        self.closed = True


def _instruments(symbols: list[str]) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            symbol=s, asset_class=AssetClass.EQUITY, session_id="nyse", exchange="NASDAQ"
        )
        for s in symbols
    ]


_NO_OP_LOADERS = (
    "_load_ibkr_chunk_days_config",
    "_load_ibkr_hist_timeout_config",
    "_load_ibkr_retry_config",
    "_load_ibkr_venue_fallback_config",
    "_load_ibkr_rate_limit_config",
    "_load_ohlcv_insert_batch_size_config",
    "_load_gap_cluster_max_days_config",
)


@pytest.fixture
def driven_main(monkeypatch, capsys):
    """Patch every external dependency of pipeline.main(); return a driver."""

    async def _no_sleep(delay):
        return None

    def run(
        argv: list[str],
        *,
        symbols: list[str] | None = None,
        lease: FakeLease | None = None,
        sink: FakeSink | None = None,
        provider_cls=None,
        acquire_raises: Exception | None = None,
        tf_config: dict | None = None,
        daily_stage_rc: int = 0,
    ):
        symbols = symbols or ["AAA", "BBB", "CCC"]
        lease = lease or FakeLease()
        FakeSink.instances = []
        FakeProvider.instances = []
        marked: list[tuple[str, str]] = []
        normalized: list[tuple[str, str]] = []
        stored: list[tuple[str, str, str]] = []  # (symbol, tf, destination)
        atomic_calls: list[dict] = []
        gap_calls: list[tuple[str, str, object]] = []
        d1_gap_calls: list[tuple[str, date, date]] = []
        daily_stage_calls: list[tuple[tuple[str, ...], int]] = []
        mod = pipeline

        def _fake_acquire(settings, args):
            if acquire_raises is not None:
                # Mirrors the real helper: the lease's connection is closed
                # before the timeout propagates.
                lease.close()
                raise acquire_raises
            _fake_acquire.seen = (args.lease_tier, f"historical-pipeline:{args.client_id}")
            return lease

        _fake_acquire.seen = None

        def _sink_factory(conn, *, caller, max_buffer_rows=50_000):
            assert caller == "historical-pipeline"
            if sink is None:
                return FakeSink(conn, caller=caller, max_buffer_rows=max_buffer_rows)
            sink.conn = conn
            sink.caller = caller
            sink.max_buffer_rows = max_buffer_rows
            return sink

        monkeypatch.setattr(sys, "argv", ["pipeline", *argv])
        monkeypatch.setattr(
            mod,
            "Settings",
            lambda: SimpleNamespace(database_url="fake-dsn", ib_host="h", ib_port=7497),
        )
        monkeypatch.setattr(
            mod, "get_active_contracts", lambda settings, dimension="compute": _instruments(symbols)
        )
        monkeypatch.setattr(mod, "_reorder_contracts_by_gap", lambda contracts, s, t: contracts)
        monkeypatch.setattr(
            mod,
            "_load_tf_fetch_config",
            lambda s: tf_config or {"1d": (10, False), "15m": (10, False)},
        )
        for name in _NO_OP_LOADERS:
            monkeypatch.setattr(mod, name, lambda *a, **k: None)
        monkeypatch.setattr(mod, "_load_observation_batch_rows", lambda s: 50_000)
        monkeypatch.setattr(mod, "connect_db", lambda s: FakeConn())
        monkeypatch.setattr(mod, "_acquire_history_lease", _fake_acquire)
        monkeypatch.setattr(mod, "ObservationSink", _sink_factory)
        monkeypatch.setattr(mod, "new_fetch_run_id", lambda: _TEST_RUN_ID)

        def _fake_atomic(conn, *, request_rows, archive_rows, write_archive_rows):
            atomic_calls.append(
                {
                    "requests": list(request_rows),
                    "bars": list(archive_rows),
                    "writer": write_archive_rows,
                }
            )
            return len(request_rows), len(archive_rows)

        monkeypatch.setattr(mod, "persist_chunk_atomically", _fake_atomic)
        monkeypatch.setattr(mod, "IBKRProvider", provider_cls or FakeProvider)
        monkeypatch.setattr(mod, "flush_and_shutdown_metrics", lambda: None)
        monkeypatch.setattr(mod, "JOB_COMPLETED_TOTAL", MagicMock())
        monkeypatch.setattr(
            mod,
            "detect_gaps",
            lambda conn, symbol, tf, start, end, **k: (
                gap_calls.append((symbol, tf, k.get("answered")))
                or [(datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 15, tzinfo=UTC))]
            ),
        )
        record_calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            mod,
            "expected_grid_slots",
            lambda session_id, exchange, tf, start, end: [datetime(2024, 1, 2, tzinfo=UTC)],
        )
        monkeypatch.setattr(
            mod,
            "detect_gaps_1d_from_d1",
            lambda conn, symbol, start, end, sessions, **k: (
                d1_gap_calls.append((symbol, start, end))
                # A fixed end-exclusive date pair, like the real wrapper returns.
                or [(date(2024, 1, 1), date(2024, 1, 15))]
            ),
        )

        def _fake_daily_stage(daily_symbols: list[str]) -> int:
            daily_stage_calls.append((tuple(daily_symbols), daily_stage_rc))
            return daily_stage_rc

        monkeypatch.setattr(mod, "_run_daily_stage", _fake_daily_stage)
        monkeypatch.setattr(
            mod,
            "detect_gaps_from_record",
            lambda conn, symbol, tf, start, end, expected_slots, **k: (
                record_calls.append((symbol, tf))
                # End-exclusive: asks through the last missing slot's own end.
                or [(datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 15, 0, 15, tzinfo=UTC))]
            ),
        )
        monkeypatch.setattr(
            mod, "load_answered_windows", lambda conn, symbol, tf: ("answered", symbol, tf)
        )
        monkeypatch.setattr(mod, "cluster_gap_ranges", lambda gaps, max_gap_days: list(gaps))
        monkeypatch.setattr(
            mod,
            "normalize_bars",
            lambda bars, **k: (normalized.append((k["symbol"], k["timeframe"])), list(bars))[1],
        )
        monkeypatch.setattr(
            mod,
            "store_bars",
            lambda conn, bars, symbol, tf, actual_symbol=None, write_rows=None: (
                stored.append(
                    (symbol, tf, "archive" if write_rows is not None else "market_data_ohlcv")
                )
                or len(bars)
            ),
        )
        monkeypatch.setattr(
            mod,
            "mark_fetch_complete",
            lambda conn, symbol, tf, start_dt: marked.append((symbol, tf)),
        )
        monkeypatch.setattr(empty_history, "load", lambda conn, provider: {})
        monkeypatch.setattr(empty_history, "load_reverify_days", lambda conn: 7)
        monkeypatch.setattr(empty_history, "load_fresh_heads", lambda conn, provider, days: {})
        monkeypatch.setattr(empty_history, "load_first_bars", lambda conn, symbols: {})
        monkeypatch.setattr(empty_history, "record_head", lambda *a, **k: None)
        reconcile_calls: list[tuple] = []
        reconcile_1d_calls: list[tuple] = []
        monkeypatch.setattr(
            empty_history,
            "reconcile",
            lambda conn, symbol, tf, *a, **k: reconcile_calls.append((symbol, tf)),
        )
        monkeypatch.setattr(
            empty_history,
            "reconcile_empty_history",
            lambda conn, tf, provider, symbols=None: reconcile_1d_calls.append(
                (tf, provider, symbols)
            )
            or {"kept": 0, "deleted": 0, "inserted": 0, "extended": 0},
        )

        def _keep_gaps(gaps, empty, started, reverify, interval, chunks):
            return gaps

        monkeypatch.setattr(empty_history, "apply_empty_range", _keep_gaps)
        monkeypatch.setattr(asyncio, "sleep", _no_sleep)

        exit_code = None
        try:
            mod.main()
        except SystemExit as error:
            exit_code = error.code

        return SimpleNamespace(
            lease=lease,
            sink=(
                sink
                if sink is not None
                else (FakeSink.instances[0] if FakeSink.instances else None)
            ),
            provider=FakeProvider.instances[0] if FakeProvider.instances else None,
            acquire_seen=_fake_acquire.seen,
            marked=marked,
            normalized=normalized,
            stored=stored,
            atomic_calls=atomic_calls,
            gap_calls=gap_calls,
            record_calls=record_calls,
            d1_gap_calls=d1_gap_calls,
            daily_stage_calls=daily_stage_calls,
            reconcile_calls=reconcile_calls,
            reconcile_1d_calls=reconcile_1d_calls,
            exit_code=exit_code,
            output=capsys.readouterr().out,
        )

    return run


_BASE_ARGS = ["--symbols", "AAA,BBB,CCC", "--timeframes", "1d,15m", "--client-id", "47"]


def test_capture_and_checkpoint_wiring(driven_main):
    result = driven_main(_BASE_ARGS)
    assert result.exit_code is None  # success path: main returns without sys.exit

    # One lease checkpoint per completed (symbol, tf) unit: 3 symbols x 2 tfs.
    assert result.lease.checkpoints == 6
    assert result.lease.released and result.lease.closed

    # Lease acquired as the process that talks to IBKR, tier bulk by default.
    assert result.acquire_seen == ("bulk", "historical-pipeline:47")

    # Provider kwargs: requests recorded for every tf, observations only for 1d.
    calls = result.provider.calls
    assert len(calls) == 6
    for call in calls:
        assert call["on_request"] is not None
        assert call["fetch_run_id"] == _TEST_RUN_ID
        if call["timeframe"] == "1d":
            assert call["on_observation"] is not None
        else:
            assert call.get("on_observation") is None

    # Sink saw both requests and both observation deliveries per 1d fetch, plus
    # one request per intraday fetch, and flushed once per symbol. The intraday
    # requests are taken out of the buffer by the atomic persist (below), so the
    # flush carries only the 1d pair per symbol.
    assert result.sink.total_requests == 6  # 3 symbols x 2 (SMART/venue, 1d)
    assert result.sink.total_observations == 6  # 3 symbols x 2 observation deliveries
    assert result.sink.flushes == 3

    # Plan 12: one atomic request-and-bars commit per intraday fetch, with the
    # chunk's answer rows and its bars together, written by the archive's writer.
    assert len(result.atomic_calls) == 3
    for call in result.atomic_calls:
        assert len(call["requests"]) == 1
        assert len(call["bars"]) == 4
        assert call["bars"][0][1] in ("AAA", "BBB", "CCC")
        assert call["bars"][0][2] == "15m"
        assert call["writer"] is pipeline._insert_archive_rows

    # fetch_run_id printed at start; every (symbol, tf) marked complete.
    assert _TEST_RUN_ID in result.output
    assert sorted(result.marked) == [
        ("AAA", "15m"),
        ("AAA", "1d"),
        ("BBB", "15m"),
        ("BBB", "1d"),
        ("CCC", "15m"),
        ("CCC", "1d"),
    ]


def test_15m_is_archive_bound_and_1d_is_d1_only(driven_main):
    """Plan 12 + plan 185-18 task 1b: 15m is a raw observation stored into the
    archive (no fill, coverage from the record planner); 1d writes nothing to
    market_data_ohlcv -- its answers go to D1 and the daily derivation stage
    owns the grid rows."""
    result = driven_main(_BASE_ARGS)
    # No normalize anywhere: 15m is real-bars-only, 1d never reaches the store path.
    assert result.normalized == []
    # 15m plans from the record wrapper; 1d plans from the D1 wrapper.
    assert sorted(result.record_calls) == [(symbol, "15m") for symbol in ("AAA", "BBB", "CCC")]
    assert sorted(call[0] for call in result.d1_gap_calls) == ["AAA", "BBB", "CCC"]
    # The legacy grid-difference planner is not called at 1d anymore.
    assert all(tf != "1d" for _symbol, tf, _windows in result.gap_calls)
    destinations = {(symbol, tf): dest for symbol, tf, dest in result.stored}
    for symbol in ("AAA", "BBB", "CCC"):
        assert destinations[(symbol, "15m")] == "archive"
        assert (symbol, "1d") not in destinations


def test_1d_fetch_captures_to_d1_and_persists_no_chunk(driven_main):
    """The 1d fetch passes no on_chunk (nothing persists bars outside D1) while
    15m keeps its atomic chunk persist; observations still flow to the sink."""
    result = driven_main(_BASE_ARGS)
    on_chunk_by_tf: dict[str, object] = {
        c["timeframe"]: c.get("on_chunk") for c in result.provider.calls if c["symbol"] == "AAA"
    }
    assert callable(on_chunk_by_tf["15m"])
    assert on_chunk_by_tf["1d"] is None
    # Only the 15m fetches produced an atomic persist call; 1d produced none.
    assert [call["bars"][0][2] for call in result.atomic_calls] == ["15m"] * 3
    # D1 still saw the 1d pair of requests and observation deliveries per symbol.
    assert result.sink.total_observations == 6


def test_daily_stage_runs_for_touched_symbols_on_the_clean_path(driven_main):
    """A run that fetched 1d chains the derivation's daily stage for exactly the
    symbols whose 1d windows were asked, then marks 1d fetch-complete (the
    EXISTS guard needs the rows the stage just wrote)."""
    result = driven_main(_BASE_ARGS)
    assert result.exit_code is None
    assert result.daily_stage_calls == [(("AAA", "BBB", "CCC"), 0)]
    assert sorted(result.marked) == [
        ("AAA", "15m"),
        ("AAA", "1d"),
        ("BBB", "15m"),
        ("BBB", "1d"),
        ("CCC", "15m"),
        ("CCC", "1d"),
    ]


def test_daily_stage_failure_fails_the_run_loudly(driven_main):
    result = driven_main(_BASE_ARGS, daily_stage_rc=1)
    assert result.exit_code == 1
    assert "daily derivation" in result.output.lower()
    # 1d is not marked fetch-complete: no derived rows were written.
    assert all(tf != "1d" for _symbol, tf in result.marked)


def test_store_bars_refuses_1d():
    """store_bars is the fence behind the D1-only path: a forgotten 1d caller
    fails loudly instead of silently writing a non-canonical grid row."""
    with pytest.raises(RuntimeError, match="1d"):
        pipeline.store_bars(MagicMock(), _bars("SPY", "1d"), "SPY", "1d")


def test_real_bars_only_now_covers_1d():
    """1d joins the real-bars-only set (no synthetic fill at any timeframe the
    pipeline fetches except 4h); its store path is refused outright."""
    assert pipeline.real_bars_only_for("1d") is True
    assert pipeline.real_bars_only_for("4h") is False


def test_5m_chunks_persist_atomically_into_the_grid(driven_main):
    """Plan 185-18: 5m joins the archive timeframes on the atomic
    request-and-bars persist, with the pipeline's own market_data_ohlcv insert
    as the destination writer, and no synthetic fill anywhere on its path."""
    result = driven_main(
        ["--symbols", "AAA", "--timeframes", "5m", "--client-id", "47"],
        tf_config={"5m": (10, False)},
    )
    assert result.exit_code is None
    assert sorted(result.record_calls) == [("AAA", "5m")]
    assert len(result.atomic_calls) == 1
    call = result.atomic_calls[0]
    assert call["writer"] is pipeline._insert_market_data_rows
    assert call["bars"][0][1] == "AAA"
    assert call["bars"][0][2] == "5m"
    assert len(call["bars"][0]) == 9  # the grid row shape (no base column)
    assert len(call["requests"]) == 1  # the chunk's answer committed with its bars
    assert result.marked == [("AAA", "5m")]
    # No fill: normalize_bars is never called at 5m.
    assert result.normalized == []


def test_15m_always_asks_through_the_last_slot_end(driven_main):
    # The fake record-planned gap is (2024-01-01, 2024-01-15 00:15) at 15m:
    # end-exclusive, so the request runs through the last missing slot's own end
    # and the slot's bar can actually be asked for.
    default = driven_main(_BASE_ARGS)
    ends = {c["timeframe"]: c["end"] for c in default.provider.calls if c["symbol"] == "AAA"}
    assert ends["15m"] == datetime(2024, 1, 15, 0, 15, tzinfo=UTC)  # through the slot's own end
    # The D1 plan is end-exclusive too: its window ends at the last missing
    # session's own day end and is asked for as-is.
    assert ends["1d"] == datetime(2024, 1, 15, tzinfo=UTC)


def test_priority_tier_flag_reaches_the_lease(driven_main):
    result = driven_main([*_BASE_ARGS, "--lease-tier", "priority"])
    assert result.acquire_seen == ("priority", "historical-pipeline:47")


def test_flush_failure_fails_the_symbol_loudly(driven_main):
    sink = FakeSink(conn=None, caller="historical-pipeline")
    sink.fail_flushes_from = 1
    result = driven_main(_BASE_ARGS, sink=sink)
    # The symbol fails, the run refuses to declare complete, exit code 1.
    assert result.exit_code == 1
    assert "D1 flush failed" in result.output
    assert "FETCH ERROR" in result.output


def test_lease_timeout_exits_with_the_lease_code(driven_main):
    result = driven_main(_BASE_ARGS, acquire_raises=LeaseTimeout("waited too long"))
    assert result.exit_code == pipeline.EXIT_LEASE_TIMEOUT
    assert result.exit_code == 3
    assert "lease" in result.output.lower()
    # No fetch attempted without the lease.
    assert result.provider is None
    assert result.lease.released is False and result.lease.closed is True


class TestCaptureKwargs:
    def test_1d_gets_requests_and_observations(self):
        sink = FakeSink(conn=None, caller="historical-pipeline")
        kwargs = pipeline._capture_kwargs("1d", sink, _TEST_RUN_ID)
        assert kwargs["on_request"] == sink.on_request
        assert kwargs["on_observation"] == sink.on_observation
        assert kwargs["fetch_run_id"] == _TEST_RUN_ID

    def test_intraday_gets_requests_only(self):
        sink = FakeSink(conn=None, caller="historical-pipeline")
        kwargs = pipeline._capture_kwargs("5m", sink, _TEST_RUN_ID)
        assert kwargs["on_request"] == sink.on_request
        assert "on_observation" not in kwargs


class TestLeaseWaitSeconds:
    def _args(self, tier: str, wait: float | None) -> SimpleNamespace:
        return SimpleNamespace(lease_tier=tier, lease_wait_minutes=wait)

    def test_bulk_default_is_unbounded(self, monkeypatch):
        monkeypatch.setattr(pipeline, "_load_lease_apr_minutes", lambda s: 240.0)
        assert pipeline._lease_wait_seconds(None, self._args("bulk", None)) is None

    def test_priority_defaults_to_apr_minutes(self, monkeypatch):
        monkeypatch.setattr(pipeline, "_load_lease_apr_minutes", lambda s: 240.0)
        assert pipeline._lease_wait_seconds(None, self._args("priority", None)) == 240.0 * 60

    def test_explicit_flag_wins(self, monkeypatch):
        monkeypatch.setattr(pipeline, "_load_lease_apr_minutes", lambda s: 240.0)
        assert pipeline._lease_wait_seconds(None, self._args("bulk", 5.0)) == 300.0
        assert pipeline._lease_wait_seconds(None, self._args("priority", 5.0)) == 300.0


def test_1d_empty_history_is_reconciled_from_d1_after_the_flush_not_from_the_walk(driven_main):
    """Plan 185-19 (D-20, D4 a derived fact): the in-memory walk never writes a 1d
    ohlcv_empty_history row; each symbol's oldest 1d window triggers a reconcile from the
    recorded answers once D1 holds them."""
    result = driven_main(_BASE_ARGS)
    assert result.exit_code is None
    assert [tf for _symbol, tf in result.reconcile_calls if tf == "1d"] == []
    assert sorted(result.reconcile_1d_calls) == [
        ("1d", "ibkr", ["AAA"]),
        ("1d", "ibkr", ["BBB"]),
        ("1d", "ibkr", ["CCC"]),
    ]
