"""Unit tests for the D3 venue study script (phase 185 plan 13, D-17).

Pure pieces only: name selection, the pre-registration refusals, the
per-timeframe verdict write and the fetcher-lock refusal. No IBKR, no database
(the verdict writer and the run take recording fakes).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts.infrastructure.backfill._fetcher_lock import LOCK_HELD_MESSAGE, FetcherLockHeld
from scripts.ops.bars import ops_venue_study as study
from src.intelligence.bars.venue_study import VenueStudyResult

_PREREG = json.loads(
    (Path(__file__).parents[3] / "config" / "bars" / "venue_study_preregistration.json").read_text()
)


def _primary_map(n_per_venue: int = 30) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for venue in ("NYSE", "NASDAQ", "ARCA", "AMEX"):
        for i in range(n_per_venue):
            mapping[f"{venue[:2]}{i:02d}"] = venue
    return mapping


def test_selection_is_deterministic_and_respects_quota() -> None:
    primary = _primary_map()
    first = study.select_names(primary, _PREREG)
    second = study.select_names(dict(reversed(list(primary.items()))), _PREREG)
    assert first == second
    quota = _PREREG["selection"]["per_venue_names"]
    assert set(first) == {"NYSE", "ISLAND", "ARCA"}
    assert all(len(names) == quota for names in first.values())
    # AMEX is not a listing venue of the study; NASDAQ is normalized to ISLAND.
    assert all(not name.startswith("AM") for names in first.values() for name in names)
    assert all(name.startswith("NA") for name in first["ISLAND"])


def test_selection_order_is_seeded_sha256() -> None:
    ordered = study.order_candidates(["AAA", "BBB", "CCC", "DDD"], 185017)
    assert sorted(ordered) == ["AAA", "BBB", "CCC", "DDD"]
    assert ordered == study.order_candidates(["DDD", "CCC", "BBB", "AAA"], 185017)
    assert ordered != study.order_candidates(["AAA", "BBB", "CCC", "DDD"], 1)


def test_quotas_full_reports_unfilled_venues() -> None:
    primary = {"A": "NYSE", "B": "NASDAQ"}
    assert not study.quotas_full(primary, _PREREG)
    assert study.quotas_full(_primary_map(), _PREREG)


def test_eligibility_date_comes_from_the_preregistration_text() -> None:
    assert study.max_first_bar_date(_PREREG).isoformat() == "2006-11-01"


def test_refuses_when_preregistration_commit_is_after_first_request() -> None:
    now = datetime(2026, 9, 30, tzinfo=UTC)
    committed = datetime(2026, 9, 28, tzinfo=UTC)
    study.check_preregistration(committed, None, now)
    study.check_preregistration(committed, committed + timedelta(hours=1), now)
    with pytest.raises(study.PreregistrationRefused):
        study.check_preregistration(committed, committed - timedelta(hours=1), now)


def test_refuses_when_commit_is_in_the_future() -> None:
    now = datetime(2026, 9, 30, tzinfo=UTC)
    with pytest.raises(study.PreregistrationRefused):
        study.check_preregistration(now + timedelta(minutes=1), None, now)


def test_missing_preregistration_file_refuses(tmp_path: Path) -> None:
    with pytest.raises(study.PreregistrationRefused):
        study.load_preregistration(tmp_path / "absent.json")


def _result(timeframe: str, passed: bool) -> VenueStudyResult:
    return VenueStudyResult(
        timeframe=timeframe,
        names=(),
        n_names_by_venue={"NYSE": 12},
        criterion_a_pass=passed,
        criterion_b_pass=passed,
        passed=passed,
        reasons=(),
    )


class _Cursor:
    def __init__(self, log: list[tuple[str, tuple[Any, ...]]]) -> None:
        self._log = log

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self._log.append((" ".join(sql.split()), params))

    def fetchone(self) -> tuple[int]:
        return (3,)


class _Conn:
    def __init__(self) -> None:
        self.log: list[tuple[str, tuple[Any, ...]]] = []

    def cursor(self) -> _Cursor:
        return _Cursor(self.log)

    def transaction(self) -> _Cursor:
        return _Cursor(self.log)


def test_pass_1d_fail_5m_sets_only_the_1d_switch_true() -> None:
    results = {"1d": True, "5m": False}
    assert study.switch_values(results) == {
        "infra.bar_derivation.venue_bars_1d": True,
        "infra.bar_derivation.venue_bars_intraday": False,
    }
    conn = _Conn()
    study.apply_verdict(conn, results, "abc123")
    updates = [p for sql, p in conn.log if sql.startswith("UPDATE config_state")]
    history = [p for sql, p in conn.log if sql.startswith("INSERT INTO config_history")]
    assert sorted((p[2], p[0]) for p in updates) == [
        ("infra.bar_derivation.venue_bars_1d", "true"),
        ("infra.bar_derivation.venue_bars_intraday", "false"),
    ]
    assert len(history) == 2
    for params in history:
        assert "venue_study_185" in params
        assert any("abc123" in str(p) for p in params)


# --- the shared fetcher lock (phase 189 plan 05, CD-09) --------------------------


class _RunConn:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def close(self) -> None:
        self._events.append("conn.close")


class _FakeLock:
    def __init__(self, holder: str, granted: bool, events: list[str]) -> None:
        self.holder = holder
        self._granted = granted
        self._events = events

    def hold_or_refuse(self) -> None:
        self._events.append("lock.acquire")
        if not self._granted:
            raise FetcherLockHeld(LOCK_HELD_MESSAGE)

    def close(self) -> None:
        self._events.append("lock.close")


class _FakeProvider:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def connect(self) -> bool:
        self._events.append("provider.connect")
        return False

    async def disconnect(self) -> None:
        self._events.append("provider.disconnect")


def _wire_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, granted: bool
) -> tuple[list[str], list[_FakeLock]]:
    events: list[str] = []
    locks: list[_FakeLock] = []
    prereg_path = tmp_path / "prereg.json"
    prereg_path.write_text(json.dumps(_PREREG))
    settings = SimpleNamespace(database_url="postgresql://fake/db", ib_host="h", ib_port=1)
    monkeypatch.setattr(study, "Settings", lambda: settings)
    monkeypatch.setattr(study, "_PREREG_PATH", prereg_path)
    monkeypatch.setattr(study, "_VERDICT_PATH", tmp_path / "verdict.json")
    monkeypatch.setattr(study, "_ARTIFACT_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(study, "git_commit_time", lambda path: datetime(2026, 9, 1, tzinfo=UTC))
    monkeypatch.setattr(study, "psycopg", SimpleNamespace(connect=lambda *a, **k: _RunConn(events)))
    monkeypatch.setattr(study, "_load_apr", lambda conn: {})
    monkeypatch.setattr(study, "preflight", lambda **kwargs: None)
    monkeypatch.setattr(study, "_first_study_request", lambda conn: None)
    monkeypatch.setattr(study, "check_preregistration", lambda *args: None)
    monkeypatch.setattr(study, "_eligible_symbols", lambda conn, cutoff: set())
    monkeypatch.setattr(study, "get_active_contracts", lambda *a, **k: [])

    def _lock(dsn: str, holder: str) -> _FakeLock:
        assert dsn == "postgresql://fake/db"
        locks.append(_FakeLock(holder, granted, events))
        return locks[-1]

    monkeypatch.setattr(study, "FetcherLock", _lock)
    monkeypatch.setattr(
        study, "ObservationSink", lambda *a, **k: SimpleNamespace(flush=lambda: None)
    )

    def _provider(**kwargs: Any) -> _FakeProvider:
        events.append("provider.init")
        return _FakeProvider(events)

    monkeypatch.setattr(study, "IBKRProvider", _provider)
    return events, locks


def _run_args() -> argparse.Namespace:
    return argparse.Namespace(apply_only=False, allow_rerun=False, apply_verdict=False)


def test_run_refuses_fast_when_the_fetcher_lock_is_held(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events, locks = _wire_run(monkeypatch, tmp_path, granted=False)
    with pytest.raises(FetcherLockHeld, match=LOCK_HELD_MESSAGE):
        asyncio.run(study._run(_run_args()))
    assert "provider.init" not in events
    assert events == ["lock.acquire", "conn.close"]
    assert locks[0].holder == "venue-study:48"


def test_run_takes_the_lock_before_connecting_and_closes_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events, _ = _wire_run(monkeypatch, tmp_path, granted=True)
    assert asyncio.run(study._run(_run_args())) == 2  # the fake gateway refuses
    assert events == [
        "lock.acquire",
        "provider.init",
        "provider.connect",
        "provider.disconnect",
        "lock.close",
        "conn.close",
    ]
