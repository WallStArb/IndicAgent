"""Plan 185-20 (D-19): intraday venue recovery refuses until every lock opens.

recovery_refusals is the gate; recovery_targets reads recorded venue answers; recover
composes fetch, store and the grid re-derivation. All against fakes: nothing here
touches IBKR or a database.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

from scripts.infrastructure.backfill import _fetcher_lock
from scripts.ops.bars import _campaign
from scripts.ops.bars import ops_intraday_venue_recovery as rec
from src import providers
from src.config import settings as settings_module

_STATE = json.dumps(
    {"table": "provenance_batch", "target_tables": ["feature_vectors_v2", "feature_vectors"]}
)
_OPEN = {
    "infra.bar_derivation.venue_bars_intraday": "true",
    "infra.bar_derivation.intraday_recovery_unlocked": "true",
    "infra.bar_derivation.rebuild_state_table": _STATE,
}


def _dt(y, m, d):
    return datetime(y, m, d, tzinfo=UTC)


class FakeConn:
    def __init__(self, *, incomplete=0, rows=()):
        self.incomplete = incomplete
        self.rows = list(rows)
        self.queries: list[tuple[str, tuple]] = []
        self._last: list = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query, params=()):
        text = query if isinstance(query, str) else query.as_string(None)
        self.queries.append((text, params))
        self._last = [(self.incomplete,)] if "count(*)" in text else list(self.rows)

    def fetchone(self):
        return self._last[0]

    def fetchall(self):
        return self._last


def test_every_lock_open_allows_recovery():
    assert rec.recovery_refusals(FakeConn(), _OPEN, []) == []


def test_each_failing_lock_names_its_reason():
    refusals = rec.recovery_refusals(FakeConn(), {}, [])
    joined = " | ".join(refusals)
    assert len(refusals) == 3
    assert "5m verdict" in joined and "rebuild has not completed" in joined
    assert "rebuild_state_table is empty" in joined


def test_incomplete_rebuild_units_refuse_and_the_count_is_reported():
    conn = FakeConn(incomplete=7)
    (reason,) = rec.recovery_refusals(conn, _OPEN, [])
    assert "7 rebuild unit(s)" in reason and "live or resumable" in reason
    query, params = conn.queries[0]
    assert "provenance_batch" in query and "status <> 'completed'" in query
    assert params == (["feature_vectors_v2", "feature_vectors"],)


def test_a_malformed_state_table_value_refuses_without_querying():
    conn = FakeConn()
    apr = {**_OPEN, "infra.bar_derivation.rebuild_state_table": "not json"}
    (reason,) = rec.recovery_refusals(conn, apr, [])
    assert "malformed" in reason and conn.queries == []


def test_a_state_table_name_that_is_not_an_identifier_refuses():
    conn = FakeConn()
    bad = json.dumps({"table": "x; drop table y", "target_tables": ["feature_vectors"]})
    (reason,) = rec.recovery_refusals(
        conn, {**_OPEN, "infra.bar_derivation.rebuild_state_table": bad}, []
    )
    assert "invalid table" in reason and conn.queries == []


def test_a_running_ic_engine_or_rebuild_process_refuses():
    args = [
        "/home/bg/dev/indicagent/.venv/bin/python -u scripts/research/ic_engine_run.py --backfill",
        "python services/backfill_feature_factory.py --stage rebuild",
        "python something_unrelated.py",
    ]
    reasons = rec.recovery_refusals(FakeConn(), _OPEN, args)
    assert any("ic_engine process" in r for r in reasons)
    assert any("backfill_feature_factory process" in r for r in reasons)
    assert any("rebuild process" in r for r in reasons)
    assert not any("unrelated" in r for r in reasons)


def test_targets_pick_the_deepest_venue_per_name_from_recorded_answers():
    rows = [
        ("AAA", "NYSE", _dt(2010, 1, 1), _dt(2010, 3, 1), 100),
        ("AAA", "NYSE", _dt(2010, 3, 1), _dt(2010, 6, 1), 150),
        ("AAA", "ARCA", _dt(2010, 1, 1), _dt(2010, 6, 1), 90),
        ("BBB", "BATS", _dt(2012, 1, 1), _dt(2012, 2, 1), 40),
    ]
    conn = FakeConn(rows=rows)
    targets = rec.recovery_targets(conn)
    assert targets == [
        rec.RecoveryTarget("AAA", "NYSE", _dt(2010, 1, 1), _dt(2010, 6, 1)),
        rec.RecoveryTarget("BBB", "BATS", _dt(2012, 1, 1), _dt(2012, 2, 1)),
    ]
    query, params = conn.queries[0]
    assert "caller <> %s" in query and params == ("5m", "venue-study")


def test_recover_stores_what_it_fetched_then_rederives_the_grid_for_those_names():
    targets = [
        rec.RecoveryTarget("AAA", "NYSE", _dt(2010, 1, 1), _dt(2010, 6, 1)),
        rec.RecoveryTarget("BBB", "BATS", _dt(2012, 1, 1), _dt(2012, 2, 1)),
    ]
    stored: list[tuple[str, int]] = []
    grid_calls: list[list[str]] = []

    async def fetch(target):
        return [{"timestamp": _dt(2010, 1, 4), "source": "ibkr_venue"}] * (
            3 if target.symbol == "AAA" else 0
        )

    def store(symbol, bars):
        stored.append((symbol, len(bars)))
        return len(bars)

    def grid(names):
        grid_calls.append(names)
        return 0

    report = asyncio.run(rec.recover(targets, fetch=fetch, store=store, run_grid_stage=grid))
    assert stored == [("AAA", 3)]
    assert grid_calls == [["AAA"]]
    assert report == {"stored": {"AAA": 3}, "grid_returncode": 0}


def test_recover_runs_no_grid_stage_when_nothing_was_fetched():
    async def fetch(target):
        return []

    calls: list = []
    report = asyncio.run(
        rec.recover(
            [rec.RecoveryTarget("AAA", "NYSE", _dt(2010, 1, 1), _dt(2010, 6, 1))],
            fetch=fetch,
            store=lambda s, b: 0,
            run_grid_stage=lambda names: calls.append(names) or 0,
        )
    )
    assert calls == [] and report["stored"] == {}


# --- the shared fetcher lock (phase 189 plan 05, CD-09) --------------------------


class _FakeLock:
    def __init__(self, granted, events):
        self._granted = granted
        self._events = events

    def acquire(self):
        self._events.append("lock.acquire")
        return self._granted

    def close(self):
        self._events.append("lock.close")


class _FakeProvider:
    def __init__(self, events):
        self._events = events

    async def connect(self):
        self._events.append("provider.connect")
        return False

    async def disconnect(self):
        self._events.append("provider.disconnect")


def _wire_apply(monkeypatch, *, granted):
    events: list[str] = []
    holders: list[str] = []

    def _lock(dsn, holder):
        holders.append(holder)
        return _FakeLock(granted, events)

    def _provider(**kwargs):
        events.append("provider.init")
        return _FakeProvider(events)

    monkeypatch.setattr(_fetcher_lock, "FetcherLock", _lock)
    monkeypatch.setattr(providers, "IBKRProvider", _provider)
    monkeypatch.setattr(_campaign, "preflight", lambda **kwargs: None)
    monkeypatch.setattr(settings_module, "get_active_contracts", lambda *a, **k: [])
    return events, holders


def _settings():
    return SimpleNamespace(database_url="postgresql://fake/db", ib_host="h", ib_port=1)


def test_apply_refuses_fast_when_the_fetcher_lock_is_held(monkeypatch, capsys):
    events, holders = _wire_apply(monkeypatch, granted=False)
    exit_code = asyncio.run(rec._apply(_settings(), FakeConn(), _OPEN, []))
    assert exit_code == 1
    assert _fetcher_lock.LOCK_HELD_MESSAGE in capsys.readouterr().out
    assert events == ["lock.acquire"]
    assert holders == ["intraday-venue-recovery:49"]


def test_apply_takes_the_lock_before_connecting_and_closes_it(monkeypatch):
    events, _ = _wire_apply(monkeypatch, granted=True)
    assert asyncio.run(rec._apply(_settings(), FakeConn(), _OPEN, [])) == 2
    assert events == [
        "lock.acquire",
        "provider.init",
        "provider.connect",
        "provider.disconnect",
        "lock.close",
    ]
