"""corpus_rerun --quiesce and --release against a fake systemd: no real unit is touched."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from services import corpus_rerun_quiesce as q

TIMERS = ("a.timer", "b.timer", "c.timer")


class FakeSystemd:
    """enabled and active state per timer; a service runs for `busy_polls` is-active queries."""

    def __init__(self, enabled=(), active=(), busy_polls=0, live=False):
        self.enabled = set(enabled)
        self.active = set(active)
        self.busy_polls = {q.service_of(t): busy_polls for t in TIMERS}
        self.live = live
        self.calls: list[tuple[str, str]] = []
        self.now = 0.0

    def query(self, verb, unit):
        if verb == "is-enabled":
            return "enabled" if unit in self.enabled else "disabled"
        if unit.endswith(".service"):
            if self.busy_polls.get(unit, 0) > 0:
                self.busy_polls[unit] -= 1
                return "active"
            return "inactive"
        return "active" if unit in self.active else "inactive"

    def change(self, verb, unit):
        self.calls.append((verb, unit))
        {
            "disable": lambda: self.enabled.discard(unit),
            "stop": lambda: self.active.discard(unit),
            "enable": lambda: self.enabled.add(unit),
            "start": lambda: self.active.add(unit),
        }[verb]()

    def deps(self):
        return q.QuiesceDeps(
            query=self.query,
            change=self.change,
            no_live_run=lambda: SimpleNamespace(ok=not self.live, detail="live writer process"),
            sleep=lambda seconds: setattr(self, "now", self.now + seconds),
            monotonic=lambda: self.now,
        )


def _quiesce(world, path, wait=100.0):
    q.quiesce(TIMERS, world.deps(), path, wait_seconds=wait, poll_seconds=1.0)


def test_quiesce_then_release_restores_exactly_the_prior_set(tmp_path):
    path = q.state_path(tmp_path)
    world = FakeSystemd(enabled={"a.timer", "b.timer"}, active={"a.timer", "b.timer"})
    _quiesce(world, path)
    assert world.enabled == set() and world.active == set()
    assert json.loads(path.read_text())["timers"] == {
        "a.timer": {"enabled": True, "active": True},
        "b.timer": {"enabled": True, "active": True},
        "c.timer": {"enabled": False, "active": False},
    }
    assert q.release(world.deps(), path) == ["a.timer", "b.timer"]
    assert world.enabled == {"a.timer", "b.timer"} and world.active == {"a.timer", "b.timer"}
    assert "c.timer" not in world.enabled and not path.exists()


def test_a_second_quiesce_keeps_the_first_record(tmp_path):
    path = q.state_path(tmp_path)
    world = FakeSystemd(enabled={"a.timer"}, active={"a.timer"})
    _quiesce(world, path)
    first = path.read_text()
    _quiesce(world, path)  # everything is already off: the record must not become all-disabled
    assert path.read_text() == first
    q.release(world.deps(), path)
    assert world.enabled == {"a.timer"}


def test_a_timer_enabled_after_the_first_quiesce_joins_the_record(tmp_path):
    path = q.state_path(tmp_path)
    world = FakeSystemd(enabled={"a.timer"})
    _quiesce(world, path)
    world.enabled.add("c.timer")
    _quiesce(world, path)
    assert world.enabled == set()
    assert q.release(world.deps(), path) == ["a.timer", "c.timer"]


def test_release_without_a_record_changes_nothing(tmp_path):
    world = FakeSystemd(enabled={"a.timer"})
    assert q.release(world.deps(), q.state_path(tmp_path)) == []
    assert world.calls == [] and world.enabled == {"a.timer"}


@pytest.mark.parametrize("action", ["quiesce", "release"])
def test_both_refuse_while_a_fingerprinted_run_is_live(tmp_path, action):
    path = q.state_path(tmp_path)
    world = FakeSystemd(enabled={"a.timer"}, live=True)
    with pytest.raises(q.QuiesceError, match="refused: live writer process"):
        _quiesce(world, path) if action == "quiesce" else q.release(world.deps(), path)
    assert world.calls == [] and not path.exists()


def test_quiesce_waits_for_a_running_service_to_finish(tmp_path):
    world = FakeSystemd(enabled={"a.timer"}, active={"a.timer"}, busy_polls=3)
    _quiesce(world, q.state_path(tmp_path))
    assert world.now == 3.0  # three polls of one second until the service settled


def test_a_service_that_never_finishes_fails_loudly_and_keeps_the_record(tmp_path):
    path = q.state_path(tmp_path)
    world = FakeSystemd(enabled={"a.timer"}, active={"a.timer"}, busy_polls=10**6)
    with pytest.raises(q.QuiesceError, match="still running after 5 s"):
        _quiesce(world, path, wait=5.0)
    assert json.loads(path.read_text())["timers"]["a.timer"] == {"enabled": True, "active": True}
    world.busy_polls = {k: 0 for k in world.busy_polls}
    q.release(world.deps(), path)  # the record is the way back
    assert world.enabled == {"a.timer"}


def test_release_fails_loudly_when_a_unit_does_not_come_back(tmp_path):
    path = q.state_path(tmp_path)
    world = FakeSystemd(enabled={"a.timer"})
    _quiesce(world, path)
    world.change = lambda verb, unit: world.calls.append((verb, unit))  # enable does nothing
    with pytest.raises(q.QuiesceError, match="not restored"):
        q.release(world.deps(), path)
    assert path.exists()


def test_a_timer_the_pin_gate_would_refuse_fails_the_quiesce_and_keeps_the_record(tmp_path):
    path = q.state_path(tmp_path)
    world = FakeSystemd(enabled={"a.timer"})
    query = world.query
    world.query = lambda verb, unit: (
        "not-found" if unit == "c.timer" and verb == "is-enabled" else query(verb, unit)
    )
    with pytest.raises(q.QuiesceError, match="pin gate would refuse"):
        _quiesce(world, path)
    assert path.exists()


def test_the_record_is_written_before_the_first_change(tmp_path):
    path = q.state_path(tmp_path)
    world = FakeSystemd(enabled={"a.timer", "b.timer"})
    seen = []

    def failing(verb, unit):
        seen.append(path.exists())
        raise q.QuiesceError("sudo: a password is required")

    world.change = failing
    with pytest.raises(q.QuiesceError):
        _quiesce(world, path)
    assert seen == [True]


def test_the_pin_gate_and_quiesce_share_one_rule():
    assert q.timer_is_quiet("disabled", "inactive") and q.timer_is_quiet("masked", "failed")
    assert not q.timer_is_quiet("enabled", "inactive")
    assert not q.timer_is_quiet("enabled-runtime", "inactive")
    assert not q.timer_is_quiet("not-found", "inactive")
    assert not q.timer_is_quiet("disabled", "active")


def test_the_wait_and_poll_seconds_come_from_seeded_apr_keys():
    from services.corpus_rerun_apr import load_quiesce_apr

    seeded = {
        "infra.corpus_rerun.quiesce.wait_seconds": "3600",
        "infra.corpus_rerun.quiesce.poll_seconds": "5",
    }
    cfg = SimpleNamespace(get_sync=lambda key: seeded.get(key))
    assert load_quiesce_apr(cfg) == load_quiesce_apr(cfg)
    assert load_quiesce_apr(cfg).wait_seconds == 3600.0
    with pytest.raises(KeyError, match="migration 593"):
        load_quiesce_apr(SimpleNamespace(get_sync=lambda key: None))


def test_migration_593_seeds_both_keys_with_their_history():
    from pathlib import Path

    sql = Path("production/migrations/593_corpus_rerun_quiesce_apr.sql").read_text()
    for key in (
        "infra.corpus_rerun.quiesce.wait_seconds",
        "infra.corpus_rerun.quiesce.poll_seconds",
    ):
        assert sql.count(f"'{key}'") == 2  # config_schema and config_state
    assert "'migration_593'" in sql and "INTO config_history" in sql
    assert sql.count("ON CONFLICT (config_key) DO NOTHING") == 2
