"""Pure tests for the raw cutover window script (plan 191-04): unit selection and the record file."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ops.bars import ops_raw_cutover_window as mod


def _write_unit(directory: Path, name: str, body: str) -> None:
    (directory / name).write_text(body)


@pytest.fixture
def systemd_dir(tmp_path: Path) -> Path:
    _write_unit(
        tmp_path,
        "indicagent-ibkr-history-fetcher.service",
        "[Service]\nExecStart=/x/.venv/bin/python scripts/infrastructure/backfill/"
        "ohlcv_history_fetcher.py\n",
    )
    _write_unit(
        tmp_path,
        "indicagent-ibkr-history-fetcher.timer",
        "[Timer]\nOnBootSec=15min\nUnit=indicagent-ibkr-history-fetcher.service\n",
    )
    _write_unit(
        tmp_path,
        "indicagent-bar-writer.service",
        "[Service]\nExecStart=/x/.venv/bin/python services/bar_writer.py\n",
    )
    _write_unit(
        tmp_path,
        "indicagent-dividend-event-writer@.service",
        "[Service]\nExecStart=/x/.venv/bin/python services/dividend_event_writer.py --sources %i\n",
    )
    _write_unit(
        tmp_path,
        "indicagent-dividend-event-writer-yahoo.timer",
        "[Timer]\nUnit=indicagent-dividend-event-writer@yahoo.service\n",
    )
    _write_unit(
        tmp_path,
        "indicagent-api.service",
        "[Service]\nExecStart=/x/.venv/bin/python -m uvicorn src.api.main:app\n",
    )
    _write_unit(
        tmp_path,
        "indicagent-bar-replay.service",
        "[Service]\nExecStart=/x/.venv/bin/python -m services.bar_replay_provider\n",
    )
    return tmp_path


def test_held_units_selects_modules_and_their_timers(systemd_dir: Path):
    modules = {"ohlcv_history_fetcher", "bar_writer", "dividend_event_writer"}
    held = mod.held_units(systemd_dir, modules)
    assert held == [
        "indicagent-dividend-event-writer-yahoo.timer",
        "indicagent-ibkr-history-fetcher.timer",
        "indicagent-bar-writer.service",
        "indicagent-dividend-event-writer@yahoo.service",
        "indicagent-ibkr-history-fetcher.service",
    ]


def test_held_units_does_not_match_substrings(systemd_dir: Path):
    assert mod.held_units(systemd_dir, {"bar_replay"}) == []
    assert mod.held_units(systemd_dir, {"bar_replay_provider"}) == ["indicagent-bar-replay.service"]


def test_module_set_includes_allow_list_keys_and_readers():
    modules = mod.module_set()
    for reader in mod.READER_MODULES:
        assert reader in modules
    assert "bar_selection" in modules and "bar_writer" in modules
    assert "bar_derivation" in modules and "ohlcv_history_fetcher" in modules


class FakeSystemctl:
    def __init__(self, active: set[str], finish_on_timer_stop: bool = False) -> None:
        self.finish_on_timer_stop = finish_on_timer_stop
        self.active = set(active)
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str) -> str:
        self.calls.append(args)
        verb, *rest = args
        if verb == "is-active":
            return "active" if rest[0] in self.active else "inactive"
        if verb in ("stop",):
            self.active.discard(rest[-1])
            if self.finish_on_timer_stop and rest[-1].endswith(".timer"):
                self.active.discard(rest[-1][: -len(".timer")] + ".service")
        if verb in ("start",):
            self.active.add(rest[-1])
        return ""


def test_open_stops_timers_before_services_and_records(tmp_path: Path):
    record = tmp_path / "w.json"
    ctl = FakeSystemctl({"a.timer", "a.service"}, finish_on_timer_stop=True)
    mod.open_window(
        ["a.timer", "a.service", "b.service"],
        record,
        ctl,
        wait_s=0,
        poll_s=0,
        batch_services={"a.service"},
        sleep=lambda _s: None,
    )
    stops = [c for c in ctl.calls if c[0] == "stop"]
    assert [c[-1] for c in stops] == ["a.timer"]  # the batch service finishes on its own
    data = json.loads(record.read_text())
    assert [u["name"] for u in data["units"]] == ["a.timer", "a.service", "b.service"]
    assert all(u["cleared_by"] is None for u in data["units"])
    assert data["opened_at"].endswith("Z")


def test_open_aborts_when_a_service_does_not_exit(tmp_path: Path):
    record = tmp_path / "w.json"
    ctl = FakeSystemctl({"a.service"})
    with pytest.raises(mod.WindowError, match="a.service"):
        mod.open_window(
            ["a.service"],
            record,
            ctl,
            wait_s=0,
            poll_s=0,
            batch_services={"a.service"},
            sleep=lambda _s: None,
        )
    # the pre-stop active state is persisted before anything is stopped (finding 9)
    assert json.loads(record.read_text())["state"] == "opening"


def test_open_retry_after_abort_keeps_the_recorded_active_state(tmp_path: Path):
    record = tmp_path / "w.json"
    ctl = FakeSystemctl({"a.timer", "a.service"})
    with pytest.raises(mod.WindowError):
        mod.open_window(
            ["a.timer", "a.service"],
            record,
            ctl,
            wait_s=0,
            poll_s=0,
            batch_services={"a.service"},
            sleep=lambda _s: None,
        )
    assert ("stop", "a.timer") in ctl.calls
    ctl.active.discard("a.service")  # the batch run exits; the timer is already stopped
    data = mod.open_window(
        ["a.timer", "a.service"],
        record,
        ctl,
        wait_s=0,
        poll_s=0,
        batch_services={"a.service"},
        sleep=lambda _s: None,
    )
    timer = next(u for u in data["units"] if u["name"] == "a.timer")
    assert timer["active_at_open"] is True and timer["resume_action"] == "start"
    assert data["state"] == "open"
    with pytest.raises(mod.WindowError, match="already open"):
        mod.open_window(["a.timer"], record, ctl, wait_s=0, poll_s=0, batch_services=set())


def _record(path: Path, names: list[str]) -> None:
    path.write_text(
        json.dumps(
            {
                "opened_at": "2026-10-13T00:00:00Z",
                "units": [
                    {"name": n, "cleared_by": None, "evidence": None, "active_at_open": True}
                    for n in names
                ],
            }
        )
    )


def test_clear_requires_evidence_and_known_unit(tmp_path: Path):
    record = tmp_path / "w.json"
    _record(record, ["a.service"])
    with pytest.raises(mod.WindowError, match="evidence"):
        mod.clear_unit(record, "a.service", "191-08", tmp_path / "missing.txt")
    with pytest.raises(mod.WindowError, match="not in the record"):
        mod.clear_unit(record, "zzz.service", "191-08", record)
    mod.clear_unit(record, "a.service", "191-08", record)
    unit = json.loads(record.read_text())["units"][0]
    assert unit["cleared_by"] == "191-08"


def test_resume_refuses_uncleared_then_restarts_and_removes(tmp_path: Path):
    record = tmp_path / "w.json"
    _record(record, ["a.service", "b.service"])
    ctl = FakeSystemctl(set())
    with pytest.raises(mod.WindowError, match="uncleared"):
        mod.resume_unit(record, "a.service", ctl)
    with pytest.raises(mod.WindowError, match="uncleared"):
        mod.resume_all(record, ctl)
    mod.clear_unit(record, "a.service", "191-08", record)
    mod.resume_unit(record, "a.service", ctl)
    assert ("start", "a.service") in ctl.calls
    assert [u["name"] for u in json.loads(record.read_text())["units"]] == ["b.service"]
    with pytest.raises(mod.WindowError, match="uncleared"):
        mod.resume_all(record, ctl)


def test_resume_starts_timers_and_services_that_were_active(tmp_path: Path):
    record = tmp_path / "w.json"
    _record(record, ["a.timer"])
    mod.clear_unit(record, "a.timer", "191-07", record)
    ctl = FakeSystemctl(set())
    mod.resume_all(record, ctl)
    assert ("start", "a.timer") in ctl.calls
    assert json.loads(record.read_text())["units"] == []


FETCHER_TIMER = "indicagent-ibkr-history-fetcher.timer"
FETCHER_SERVICE = "indicagent-ibkr-history-fetcher.service"
DERIVATION = "indicagent-bar-derivation.service"


def _clear(record: Path, *names: str) -> None:
    for name in names:
        mod.clear_unit(record, name, "191-X", record)


def test_dependency_map_matches_the_systemd_units():
    for unit, deps in mod.UNIT_DEPENDENCIES.items():
        assert (mod._SYSTEMD_DIR / unit).exists(), unit
        for dep in deps:
            assert (mod._SYSTEMD_DIR / dep).exists(), dep
    timer_text = (mod._SYSTEMD_DIR / FETCHER_TIMER).read_text()
    assert mod._unit_target(timer_text, FETCHER_TIMER) in mod.UNIT_DEPENDENCIES[FETCHER_TIMER]
    # every module the fetcher service runs that has a unit of its own is a dependency
    for module, unit in mod.MODULE_UNITS.items():
        assert module in mod.FETCHER_RUNS_MODULES
        assert unit in mod.UNIT_DEPENDENCIES[FETCHER_SERVICE]
        assert module in mod._exec_tokens((mod._SYSTEMD_DIR / unit).read_text())
    assert {"bar_derivation", "split_detection", "bar_hold"} <= set(mod.FETCHER_RUNS_MODULES)


def test_timer_resume_refuses_while_its_service_is_uncleared(tmp_path: Path):
    record = tmp_path / "w.json"
    _record(record, [FETCHER_TIMER, FETCHER_SERVICE, DERIVATION])
    _clear(record, FETCHER_TIMER)
    with pytest.raises(mod.WindowError, match=FETCHER_SERVICE):
        mod.resume_unit(record, FETCHER_TIMER, FakeSystemctl(set()), fetcher_plans_done=lambda: [])


def test_timer_resume_refuses_while_a_module_it_runs_is_uncleared(tmp_path: Path):
    record = tmp_path / "w.json"
    _record(record, [FETCHER_TIMER, FETCHER_SERVICE, DERIVATION])
    _clear(record, FETCHER_TIMER, FETCHER_SERVICE)
    ctl = FakeSystemctl(set())
    with pytest.raises(mod.WindowError, match=DERIVATION):
        mod.resume_unit(
            record, FETCHER_TIMER, ctl, fetcher_plans_done=lambda: list(mod.FETCHER_PLANS)
        )
    assert ctl.calls == []


def test_fetcher_stays_held_until_plans_06_08_10_done(tmp_path: Path):
    record = tmp_path / "w.json"
    _record(record, [FETCHER_TIMER, FETCHER_SERVICE, DERIVATION])
    _clear(record, FETCHER_TIMER, FETCHER_SERVICE, DERIVATION)
    ctl = FakeSystemctl(set())
    with pytest.raises(mod.WindowError, match=r"191-08.*191-10"):
        mod.resume_unit(record, FETCHER_TIMER, ctl, fetcher_plans_done=lambda: ["191-06"])
    with pytest.raises(mod.WindowError, match="191-06"):
        mod.resume_all(record, ctl, fetcher_plans_done=lambda: [])
    assert ctl.calls == []
    log = tmp_path / "override.log"
    mod.resume_unit(
        record,
        FETCHER_TIMER,
        ctl,
        fetcher_plans_done=lambda: [],
        override_fetcher_plan_gate=True,
        override_log=log,
    )
    assert ("start", FETCHER_TIMER) in ctl.calls
    assert FETCHER_TIMER in log.read_text() and "override" in log.read_text()
    saved = json.loads(record.read_text())
    assert saved["fetcher_gate_overrides"]


def test_non_fetcher_units_resume_without_the_plan_gate(tmp_path: Path):
    record = tmp_path / "w.json"
    _record(record, [DERIVATION])
    _clear(record, DERIVATION)
    mod.resume_unit(record, DERIVATION, FakeSystemctl(set()), fetcher_plans_done=lambda: [])


def test_fetcher_plans_done_reads_summaries(tmp_path: Path):
    (tmp_path / "191-06-SUMMARY.md").write_text("x")
    (tmp_path / "191-10-SUMMARY.md").write_text("x")
    assert mod.fetcher_plans_done(tmp_path) == ["191-06", "191-10"]
