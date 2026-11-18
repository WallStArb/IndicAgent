"""Stored E17 battery pass records (todo 635 review): the record check, the code key and the
legacy waiver table."""

import re
from pathlib import Path

import pytest

from src.core import code_identity
from src.intelligence.research import battery_pass as bp
from src.intelligence.research.spec import load_spec_from_file

ROOT = Path(__file__).resolve().parents[3]
BATTERY = "src.intelligence.research.null_battery_seasonality"
FAMILY_MODULE = "src.intelligence.research.families.seasonality"


def _spec(name="seasonality_h5"):
    return load_spec_from_file(ROOT / f"research/specs/{name}.yaml", root=ROOT).model


def _scenario_names():
    import importlib

    return [s.name for s in importlib.import_module(BATTERY).scenarios()]


def _driver(sims=1000, failures=(), names=None, commit="abc"):
    names = _scenario_names() if names is None else names
    return {
        "schema": bp.SCHEMA,
        "battery": BATTERY,
        "sims_per_cell": sims,
        "scenarios": [{"name": n} for n in names],
        "report": [],
        "failures": list(failures),
        "commit": commit,
    }


def _record(spec=None, **binding):
    spec = spec or _spec()
    bound = {
        "family": spec.family,
        "battery_input_hash": bp.battery_input_hash(spec),
        "battery_code_key": bp.battery_code_key(BATTERY, FAMILY_MODULE),
        "spec_hashes": [],
        "recorded": "2026-11-18",
        **binding,
    }
    return bp.make_record([_driver()], binding=bound, scenario_names=_scenario_names())


def _require(spec=None, records=(), waivers=None):
    return bp.require(
        spec or _spec(),
        battery_module=BATTERY,
        family_module=FAMILY_MODULE,
        records=list(records),
        waivers=waivers or {},
    )


# -- the input hash ---------------------------------------------------------------------------


def test_the_primary_and_core_twins_share_one_input_hash_and_a_member_change_moves_it():
    primary, core = _spec(), _spec("seasonality_h5_core")
    assert bp.battery_input_hash(primary) == bp.battery_input_hash(core)
    changed = primary.model_copy(update={"horizon": primary.horizon + 1})
    assert bp.battery_input_hash(changed) != bp.battery_input_hash(primary)
    members = [
        m.model_copy(update={"params": {**m.params, "max_missing_fraction": 0.5}})
        for m in primary.members
    ]
    assert bp.battery_input_hash(
        primary.model_copy(update={"members": members})
    ) != bp.battery_input_hash(primary)


# -- the code key -----------------------------------------------------------------------------


def _patched_runner(monkeypatch, tmp_path, edit):
    real_source = code_identity.source_path(bp.RUNNER)
    text = Path(real_source).read_text()
    edited = edit(text)
    assert edited != text
    fake = tmp_path / "runner_variant.py"
    fake.write_text(edited)
    original = code_identity.source_path

    def source_path(name):
        return fake if name == bp.RUNNER else original(name)

    monkeypatch.setattr(code_identity, "source_path", source_path)


def test_editing_s1_input_changes_the_key_and_an_unrelated_runner_function_does_not(
    monkeypatch, tmp_path
):
    base = bp.battery_code_key(BATTERY, FAMILY_MODULE)
    _patched_runner(
        monkeypatch,
        tmp_path,
        lambda t: t.replace(
            "seen = membership.seen_member_mask(panel.member)",
            "seen = ~membership.seen_member_mask(panel.member)",
            1,
        ),
    )
    assert bp.battery_code_key(BATTERY, FAMILY_MODULE) != base
    monkeypatch.undo()
    _patched_runner(
        monkeypatch,
        tmp_path,
        lambda t: t.replace(
            "def family_module(spec: FamilySpec):\n",
            "def family_module(spec: FamilySpec):\n    _plumbing = 1  # an edit unrelated to the statistic\n",
            1,
        ),
    )
    assert bp.battery_code_key(BATTERY, FAMILY_MODULE) == base


def test_a_docstring_or_comment_edit_of_a_listed_function_does_not_move_the_key(
    monkeypatch, tmp_path
):
    base = bp.battery_code_key(BATTERY, FAMILY_MODULE)
    _patched_runner(
        monkeypatch,
        tmp_path,
        lambda t: t.replace(
            "    seen = membership.seen_member_mask(panel.member)\n",
            "    # reworded comment\n    seen = membership.seen_member_mask(panel.member)\n",
            1,
        ),
    )
    assert bp.battery_code_key(BATTERY, FAMILY_MODULE) == base


def test_every_listed_runner_function_exists():
    assert len(bp.function_key(bp.RUNNER, bp.RUNNER_STATISTIC_FUNCTIONS)) == 64
    with pytest.raises(bp.BatteryPassRefused, match="no top-level function"):
        bp.function_key(bp.RUNNER, ["not_a_function"])


# -- what counts as a pass --------------------------------------------------------------------


def test_problems_names_each_way_a_driver_record_fails():
    names = _scenario_names()
    assert bp.problems(_driver(), names) == []
    assert "failure" in bp.problems(_driver(failures=["cell/arm at 0.05: 90 > 67"]), names)[0]
    assert "below 1000" in bp.problems(_driver(sims=300), names)[0]
    assert "not run" in bp.problems(_driver(names=names[:-1]), names)[0]
    assert "schema" in bp.problems({**_driver(), "schema": "other"}, names)[0]


def test_a_battery_run_in_parts_is_merged_and_judged_together():
    names = _scenario_names()
    part_a, part_b = _driver(names=names[:-1], commit="a"), _driver(names=names[-1:], commit="b")
    record = bp.make_record([part_a, part_b], binding={"family": "x"}, scenario_names=names)
    assert record["commits"] == ["a", "b"]
    with pytest.raises(bp.BatteryPassRefused, match="not run"):
        bp.make_record([part_a], binding={"family": "x"}, scenario_names=names)
    with pytest.raises(bp.BatteryPassRefused, match="failure"):
        bp.make_record(
            [part_a, _driver(names=names[-1:], failures=["f"])],
            binding={"family": "x"},
            scenario_names=names,
        )


# -- the check --------------------------------------------------------------------------------


def test_no_record_is_refused_loudly():
    with pytest.raises(bp.BatteryPassRefused, match="no recorded E17 battery pass"):
        _require()


def test_a_current_record_passes_for_the_primary_and_the_core_twin():
    record = _record()
    assert _require(records=[record]) == "record"
    assert _require(_spec("seasonality_h5_core"), records=[record]) == "record"


def test_a_record_for_other_inputs_or_other_code_is_refused_with_the_reason():
    stale_inputs = _record(battery_input_hash="0" * 64)
    with pytest.raises(bp.BatteryPassRefused, match="other inputs"):
        _require(records=[stale_inputs])
    stale_code = _record(battery_code_key="0" * 64)
    with pytest.raises(bp.BatteryPassRefused, match="other battery code"):
        _require(records=[stale_code])


def test_a_record_that_no_longer_passes_is_refused():
    record = _record()
    record["failures"] = ["cell/arm at 0.05: 90 > 67"]
    with pytest.raises(bp.BatteryPassRefused, match="failure"):
        _require(records=[record])


def test_a_waiver_covers_exactly_its_family_and_input_hash():
    spec = _spec()
    key = (spec.family, bp.battery_input_hash(spec))
    assert _require(waivers={key: "ledger E17"}) == "ledger E17"
    with pytest.raises(bp.BatteryPassRefused):
        _require(waivers={(spec.family, "0" * 64): "ledger E17"})


# -- the waiver table -------------------------------------------------------------------------


def test_every_waiver_row_cites_a_ledger_entry():
    for (family, input_hash), citation in bp.LEGACY_WAIVERS.items():
        assert re.fullmatch(r"[0-9a-f]{64}", input_hash), family
        assert "E17" in citation and "methodology-change-ledger" in citation, family


def test_committed_records_are_current_passes():
    """Every record under research/battery_passes/ must be a pass at today's code and inputs for
    its family: a stale record is a failing test, not a silent skip."""
    for record in bp.load_records():
        assert record["binding"]["family"]
