"""runner.static_gate and the battery pass record (todo 635 review, owner-delegated ruling)."""

from pathlib import Path

import pytest

from src.intelligence.research import battery_pass, runner
from src.intelligence.research.spec import load_spec_from_file

ROOT = Path(__file__).resolve().parents[3]


def _spec(name="seasonality_h5"):
    return load_spec_from_file(ROOT / f"research/specs/{name}.yaml", root=ROOT).model


def test_the_keyword_has_no_default_so_a_caller_cannot_skip_the_check_silently():
    with pytest.raises(TypeError, match="require_pass"):
        runner.static_gate(_spec())


def test_a_synthetic_replay_is_exempt_and_a_real_run_without_a_record_is_refused(monkeypatch):
    monkeypatch.setattr(battery_pass, "load_records", lambda *a, **k: [])
    monkeypatch.setattr(battery_pass, "LEGACY_WAIVERS", {})
    gate = runner.static_gate(_spec(), require_pass=False)
    assert gate.battery.endswith("null_battery_seasonality")
    with pytest.raises(runner.RunRefused, match="no recorded E17 battery pass"):
        runner.static_gate(_spec(), require_pass=True)


def test_a_real_run_with_a_current_record_gets_the_gate(monkeypatch):
    spec = _spec()
    module = runner.family_module(spec)
    names = [s.name for s in __import__(module.NULL_BATTERY, fromlist=["x"]).scenarios()]
    record = battery_pass.make_record(
        [
            {
                "schema": battery_pass.SCHEMA,
                "battery": module.NULL_BATTERY,
                "sims_per_cell": 1000,
                "scenarios": [{"name": n} for n in names],
                "failures": [],
            }
        ],
        binding={
            "family": spec.family,
            "battery_input_hash": battery_pass.battery_input_hash(spec),
            "battery_code_key": battery_pass.battery_code_key(module.NULL_BATTERY, module.__name__),
        },
        scenario_names=names,
    )
    monkeypatch.setattr(battery_pass, "load_records", lambda *a, **k: [record])
    assert runner.static_gate(spec, require_pass=True).battery == module.NULL_BATTERY
