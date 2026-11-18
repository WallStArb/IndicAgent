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
    cells = battery_pass.battery_scenarios(module.NULL_BATTERY)
    driver = {
        "schema": battery_pass.SCHEMA,
        "battery": module.NULL_BATTERY,
        "sims_per_cell": 1000,
        "scenarios": cells,
        "report": [
            {
                "cell": c["name"],
                "arm": "a",
                "sims": 1000,
                "levels": {str(a): {"rejected": 1, "bound": 999} for a in battery_pass.ALPHAS},
            }
            for c in cells
        ],
        "failures": [],
        "commit": "abc",
        "dirty_tracked": [],
    }
    record = battery_pass.make_record(
        [driver],
        spec=spec,
        spec_hashes=[],
        battery_module=module.NULL_BATTERY,
        family_module=module.__name__,
        driver_commit="abc",
        input_hash_then=battery_pass.battery_input_hash(spec),
        code_key_then=battery_pass.battery_code_key(module.NULL_BATTERY, module.__name__),
        dirty=[],
        recorded="2026-11-18",
    )
    monkeypatch.setattr(battery_pass, "load_records", lambda *a, **k: [record])
    assert runner.static_gate(spec, require_pass=True).battery == module.NULL_BATTERY


def test_every_static_gate_call_in_the_runner_passes_the_mode_not_a_constant():
    """A real or exploration run must reach the pass check: run_family and run_book call
    static_gate with require_pass=real (the run's own mode flag). A constant False here would pass
    every other test."""
    import ast

    tree = ast.parse(Path(runner.__file__).read_text())
    calls = {}
    for fn in tree.body:
        if isinstance(fn, ast.AsyncFunctionDef | ast.FunctionDef):
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "static_gate":
                    kw = {k.arg: k.value for k in node.keywords}
                    calls.setdefault(fn.name, []).append(kw.get("require_pass"))
    assert set(calls) == {"run_family", "run_book"}, calls
    for name, values in calls.items():
        assert all(isinstance(v, ast.Name) and v.id == "real" for v in values), name
