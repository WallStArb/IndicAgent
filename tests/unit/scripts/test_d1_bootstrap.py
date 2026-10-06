"""Unit tests for the D1 bootstrap (scripts/ops/bars/ops_d1_bootstrap.py), fakes only."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts.infrastructure.backfill._fetcher_lock import LOCK_HELD_MESSAGE
from scripts.ops.bars import ops_d1_bootstrap as mod
from services.ohlcv_observation_writer import _observation_rows, _request_row

_NOW = datetime(2026, 9, 30, tzinfo=UTC)
_RUN = "11111111-1111-1111-1111-111111111111"


def _rows():
    return [
        (datetime(2020, 1, 2, tzinfo=UTC), 10.0, 11.0, 9.0, 10.5, 1000),
        (datetime(2020, 1, 3, tzinfo=UTC), 10.5, 12.0, 10.0, 11.0, 2000),
    ]


def test_legacy_records_map_to_request_and_observation_rows() -> None:
    request, bars = mod.legacy_records("AAA", _rows(), fetch_run_id=_RUN, now=_NOW)
    assert request.route == "LEGACY_IMPORT"
    assert request.outcome == "legacy_import"
    assert request.what_to_show == "TRADES"
    assert request.n_bars == 2
    assert request.window_start == _rows()[0][0]
    assert request.window_end == _rows()[1][0]
    req_row = _request_row(request, caller="d1-bootstrap", source="ibkr")
    assert req_row[5] == "LEGACY_IMPORT" and req_row[11] == "legacy_import"
    assert req_row[16] == "d1-bootstrap"
    obs = _observation_rows(request, bars, source="ibkr", fetched_at=_NOW)
    assert [row[3].isoformat() for row in obs] == ["2020-01-02", "2020-01-03"]
    assert obs[0][5] == 11.0 and obs[0][8] == 1000
    assert obs[0][10] == "LEGACY_IMPORT" and obs[0][11] == "TRADES"


def test_legacy_records_refuse_empty_symbol() -> None:
    with pytest.raises(ValueError):
        mod.legacy_records("AAA", [], fetch_run_id=_RUN, now=_NOW)


def test_order_puts_mrna_and_alms_first() -> None:
    assert mod.order_symbols(["ZZZ", "AAPL", "ALMS", "MRNA"]) == ["MRNA", "ALMS", "AAPL", "ZZZ"]


def test_resume_refetches_a_symbol_missing_either_series() -> None:
    outcomes = {
        "BOTH": {"TRADES": ["bars"], "ADJUSTED_LAST": ["no_data"]},
        "ONLY_TRADES": {"TRADES": ["bars"]},
        "FAILED_ADJ": {"TRADES": ["bars"], "ADJUSTED_LAST": ["failed", "timeout"]},
        "RETRIED": {"TRADES": ["bars"], "ADJUSTED_LAST": ["failed", "bars"]},
    }
    done = mod.symbols_done(outcomes)
    assert done == {"BOTH", "RETRIED"}
    todo = mod.pending_symbols(["BOTH", "ONLY_TRADES", "FAILED_ADJ", "RETRIED", "MRNA"], done)
    assert todo == ["MRNA", "FAILED_ADJ", "ONLY_TRADES"]


# --- fresh-fetch on the shared fetcher lock (phase 189 plan 05, CD-09) -----------


class _FakeDbConn:
    def __enter__(self) -> _FakeDbConn:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _FakeLock:
    instances: list[_FakeLock] = []

    def __init__(self, dsn: str, holder: str, granted: bool, events: list[str]) -> None:
        self.dsn = dsn
        self.holder = holder
        self._granted = granted
        self._events = events
        self.closed = False
        _FakeLock.instances.append(self)

    def acquire(self) -> bool:
        self._events.append("lock.acquire")
        return self._granted

    def close(self) -> None:
        self._events.append("lock.close")
        self.closed = True


class _FakeProvider:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def connect(self) -> bool:
        self._events.append("provider.connect")
        return False

    async def disconnect(self) -> None:
        self._events.append("provider.disconnect")


def _wire_fresh_fetch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, granted: bool
) -> list[str]:
    events: list[str] = []
    _FakeLock.instances = []
    settings = SimpleNamespace(database_url="postgresql://fake/db", ib_host="h", ib_port=1)
    monkeypatch.setattr(mod, "Settings", lambda: settings)
    monkeypatch.setattr(mod, "psycopg", SimpleNamespace(connect=lambda *a, **k: _FakeDbConn()))
    monkeypatch.setattr(mod, "_load_apr", lambda conn: {})
    monkeypatch.setattr(mod, "preflight", lambda **kwargs: None)
    monkeypatch.setattr(mod, "_eligible_instruments", lambda s: {"AAA": object()})
    monkeypatch.setattr(mod, "apply_hist_rate_limit_config", lambda cfg: None)
    monkeypatch.setattr(mod, "_PROGRESS_DIR", tmp_path)
    monkeypatch.setattr(
        mod,
        "FetcherLock",
        lambda dsn, holder: _FakeLock(dsn, holder, granted, events),
    )
    monkeypatch.setattr(mod, "AsyncObservationSink", lambda **kwargs: SimpleNamespace())

    def _provider(**kwargs: Any) -> _FakeProvider:
        events.append("provider.init")
        return _FakeProvider(events)

    monkeypatch.setattr(mod, "IBKRProvider", _provider)
    return events


def _fresh_args() -> argparse.Namespace:
    return argparse.Namespace(resume_run=None, symbols=None, max_consecutive_failures=5)


def test_fresh_fetch_refuses_fast_when_the_fetcher_lock_is_held(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    events = _wire_fresh_fetch(monkeypatch, tmp_path, granted=False)
    exit_code = asyncio.run(mod._fresh_fetch(_fresh_args()))
    out = capsys.readouterr().out
    assert exit_code == mod._INTERRUPTED_EXIT
    assert LOCK_HELD_MESSAGE in out
    assert "rerun with --resume-run" in out
    assert "provider.init" not in events
    assert events == ["lock.acquire"]
    assert _FakeLock.instances[0].holder == "d1-bootstrap:47"
    assert _FakeLock.instances[0].dsn == "postgresql://fake/db"


def test_fresh_fetch_takes_the_lock_before_connecting_and_closes_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events = _wire_fresh_fetch(monkeypatch, tmp_path, granted=True)
    exit_code = asyncio.run(mod._fresh_fetch(_fresh_args()))
    assert exit_code == mod._INTERRUPTED_EXIT  # the fake gateway refuses the connection
    assert events == [
        "lock.acquire",
        "provider.init",
        "provider.connect",
        "provider.disconnect",
        "lock.close",
    ]
