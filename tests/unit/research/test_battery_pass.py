"""Stored E17 battery pass records (todo 635 review): the record check, the code key and the
legacy waiver table."""

import importlib
import re
from pathlib import Path

import pytest

from src.core import code_identity
from src.intelligence.research import battery_pass as bp
from src.intelligence.research.spec import family_spec_hash, load_spec_from_file

ROOT = Path(__file__).resolve().parents[3]
BATTERY = "src.intelligence.research.null_battery_seasonality"
FAMILY_MODULE = "src.intelligence.research.families.seasonality"


def _spec(name="seasonality_h5"):
    return load_spec_from_file(ROOT / f"research/specs/{name}.yaml", root=ROOT).model


def _cells():
    return bp.battery_scenarios(BATTERY)


def _report(cells, rejected=1, sims=1000, arms=("a", "b")):
    return [
        {
            "cell": c["name"],
            "arm": arm,
            "sims": sims,
            "levels": {str(a): {"rejected": rejected, "bound": 999} for a in bp.ALPHAS},
        }
        for c in cells
        for arm in arms
    ]


def _driver(sims=1000, failures=(), cells=None, commit="abc", report=None):
    cells = _cells() if cells is None else cells
    return {
        "schema": bp.SCHEMA,
        "battery": BATTERY,
        "sims_per_cell": sims,
        "scenarios": cells,
        "report": _report(cells) if report is None else report,
        "failures": list(failures),
        "commit": commit,
        "dirty_tracked": [],
    }


def _make(parts=None, spec=None, **over):
    spec = spec or _spec()
    key = bp.battery_code_key(BATTERY, FAMILY_MODULE)
    args = {
        "spec": spec,
        "spec_hashes": ["h"],
        "battery_module": BATTERY,
        "family_module": FAMILY_MODULE,
        "driver_commit": "abc",
        "input_hash_then": bp.battery_input_hash(spec),
        "code_key_then": key,
        "dirty": [],
        "recorded": "2026-11-18",
        **over,
    }
    return bp.make_record(parts if parts is not None else [_driver()], **args)


def _record(spec=None):
    return _make(spec=spec)


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
    cells = _cells()
    assert bp.problems(_driver(), cells) == []
    assert "failure" in bp.problems(_driver(failures=["cell/arm at 0.05: 90 > 67"]), cells)[0]
    assert "below 1000" in bp.problems(_driver(sims=300), cells)[0]
    assert "not run" in bp.problems(_driver(cells=cells[:-1]), cells)[0]
    assert "schema" in bp.problems({**_driver(), "schema": "other"}, cells)[0]


def test_a_shortened_panel_is_another_cell_even_with_the_same_name():
    cells = _cells()
    short = [{**c, "sessions": 300} for c in cells]
    assert "other settings" in bp.problems(_driver(cells=short), cells)[0]


def test_the_result_is_recomputed_from_the_report_not_read_from_the_failure_list():
    cells = _cells()
    over = _report(cells, rejected=90)  # the record's own "bound" of 999 is ignored
    assert "> " in bp.problems(_driver(report=over), cells)[0]
    few = _report(cells, sims=100)
    assert "100 sims" in bp.problems(_driver(report=few), cells)[0]
    # a diagnostic cell may exceed its bound
    diagnostic = {**_driver(report=over), "diagnostic_cells": [c["name"] for c in cells]}
    assert bp.problems(diagnostic, cells) == []


def test_a_battery_run_in_parts_is_merged_and_judged_together():
    cells = _cells()
    part_a, part_b = _driver(cells=cells[:-1]), _driver(cells=cells[-1:])
    record = _make([part_a, part_b])
    assert record["commit"] == "abc" and record["binding"]["family"] == "seasonality"
    with pytest.raises(bp.BatteryPassRefused, match="not run"):
        _make([part_a])
    with pytest.raises(bp.BatteryPassRefused, match="failure"):
        _make([part_a, _driver(cells=cells[-1:], failures=["f"])])


def test_the_bind_refuses_parts_from_other_commits_or_batteries_and_a_dirty_tree():
    with pytest.raises(bp.BatteryPassRefused, match="not at the stated driver commit"):
        _make([_driver(commit="other")])
    with pytest.raises(bp.BatteryPassRefused, match="uncommitted"):
        _make(dirty=["src/x.py"])
    with pytest.raises(bp.BatteryPassRefused, match="not "):
        _make([{**_driver(), "battery": "other.battery"}])


def test_the_bind_refuses_when_code_or_inputs_changed_since_the_driver_ran():
    with pytest.raises(bp.BatteryPassRefused, match="code changed"):
        _make(code_key_then="0" * 64)
    with pytest.raises(bp.BatteryPassRefused, match="inputs changed"):
        _make(input_hash_then="0" * 64)


def test_the_bind_refuses_a_spec_the_battery_did_not_simulate():
    with pytest.raises(bp.BatteryPassRefused, match="own inputs differ"):
        _make(spec=_spec("daily_residual_h5"))


# -- the check --------------------------------------------------------------------------------


def test_no_record_is_refused_loudly():
    with pytest.raises(bp.BatteryPassRefused, match="no recorded E17 battery pass"):
        _require()


def test_a_current_record_passes_for_the_primary_and_the_core_twin():
    record = _record()
    assert _require(records=[record]) == "record"
    assert _require(_spec("seasonality_h5_core"), records=[record]) == "record"


def test_a_record_for_other_inputs_or_other_code_is_refused_with_the_reason():
    stale_inputs = _record()
    stale_inputs["binding"]["battery_input_hash"] = "0" * 64
    with pytest.raises(bp.BatteryPassRefused, match="other inputs"):
        _require(records=[stale_inputs])
    stale_code = _record()
    stale_code["binding"]["battery_code_key"] = "0" * 64
    with pytest.raises(bp.BatteryPassRefused, match="other battery code"):
        _require(records=[stale_code])


def test_a_record_that_no_longer_passes_is_refused():
    record = _record()
    record["failures"] = ["cell/arm at 0.05: 90 > 67"]
    with pytest.raises(bp.BatteryPassRefused, match="failure"):
        _require(records=[record])


def test_a_waiver_covers_exactly_its_family_and_spec_hash_not_an_amended_spec():
    spec = _spec()
    key = (spec.family, family_spec_hash(spec))
    assert _require(waivers={key: "ledger E17"}) == "ledger E17"
    with pytest.raises(bp.BatteryPassRefused):
        _require(waivers={(spec.family, "0" * 64): "ledger E17"})
    # the core twin has the same inputs but another spec hash: it needs its own waiver
    with pytest.raises(bp.BatteryPassRefused):
        _require(_spec("seasonality_h5_core"), waivers={key: "ledger E17"})


def test_factor_specs_are_part_of_the_code_key(monkeypatch, tmp_path):
    base = bp.battery_code_key(BATTERY, FAMILY_MODULE)
    _patched_runner(
        monkeypatch,
        tmp_path,
        lambda t: t.replace('"vintage_1": VINTAGE_1', '"vintage_1": VINTAGE_1, "x": VINTAGE_1', 1),
    )
    assert bp.battery_code_key(BATTERY, FAMILY_MODULE) != base


def test_the_key_at_a_past_commit_is_the_key_of_that_code():
    """sources_at reads module sources from git: at HEAD it must equal the working-tree key when the
    tree is clean for the closure files (here: at the commit of HEAD itself)."""
    import subprocess

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if dirty:
        pytest.skip("working tree has uncommitted changes")
    now = bp.battery_code_key(BATTERY, FAMILY_MODULE)
    with bp.sources_at(head, ROOT):
        then = bp.battery_code_key(BATTERY, FAMILY_MODULE)
    assert then == now


# -- the waiver table -------------------------------------------------------------------------


def test_every_waiver_row_cites_a_ledger_entry():
    for (family, input_hash), citation in bp.LEGACY_WAIVERS.items():
        assert re.fullmatch(r"[0-9a-f]{64}", input_hash), family
        assert "E17" in citation and "methodology-change-ledger" in citation, family


def test_committed_records_are_current_passes_for_a_registered_spec():
    """Every record under research/battery_passes/ is current for at least one registered spec of its
    family: a stale record is a failing test, not a silent skip."""
    for record in bp.load_records():
        family = record["binding"]["family"]
        matches = []
        for path in sorted((ROOT / "research/specs").glob("*.yaml")):
            spec = load_spec_from_file(path, root=ROOT).model
            if getattr(spec, "family", None) == family and (
                bp.battery_input_hash(spec) == record["binding"]["battery_input_hash"]
            ):
                matches.append(spec)
        assert matches, f"{family}: no registered spec has the recorded battery inputs"
        module = matches[0].members[0].signal.rsplit(".", 1)[0]
        battery = importlib.import_module(module).NULL_BATTERY
        assert (
            bp.require(matches[0], battery_module=battery, family_module=module, records=[record])
            == "record"
        )


def test_report_coverage_is_required_for_every_gating_cell():
    cells = _cells()
    gating = [c for c in cells if c["name"] not in bp.importlib_diagnostic(BATTERY)]
    missing = [r for r in _report(cells) if r["cell"] != gating[0]["name"]]
    assert "no report rows" in bp.problems(_driver(report=missing), cells)[0]
    dup = _report(cells) + [_report(cells)[0]]
    assert any("duplicate arm" in p for p in bp.problems(_driver(report=dup), cells))
    one_level = _report(cells)
    one_level[0]["levels"] = {"0.05": {"rejected": 0, "bound": 1}}
    assert any("levels" in p for p in bp.problems(_driver(report=one_level), cells))


def test_the_pinned_alphas_and_bound_quantile_are_the_drivers():
    from src.intelligence.research.null_battery import ALPHAS

    assert tuple(ALPHAS) == bp.ALPHAS
    source = (ROOT / "scripts/research/e17_null_battery.py").read_text()
    assert f"_BOUND_QUANTILE = {bp.BOUND_QUANTILE}" in source


def test_a_part_run_from_a_dirty_tree_or_without_recording_it_is_refused():
    with pytest.raises(bp.BatteryPassRefused, match="uncommitted changes or without recording"):
        _make([{**_driver(), "dirty_tracked": [" M src/x.py"]}])
    part = _driver()
    del part["dirty_tracked"]
    with pytest.raises(bp.BatteryPassRefused, match="uncommitted changes or without recording"):
        _make([part])


def test_a_cell_in_two_parts_is_refused():
    with pytest.raises(bp.BatteryPassRefused, match="more than one driver part"):
        _make([_driver(), _driver()])


def test_the_key_covers_what_the_hashed_runner_functions_call():
    closure = code_identity.import_closure(
        [BATTERY, FAMILY_MODULE, *bp.EXTRA_ENTRIES], io_boundary=bp.OPAQUE
    )
    for module in ("membership", "align", "smoothing", "transforms", "factors"):
        assert f"src.intelligence.research.{module}" in closure
    assert "src.intelligence.research.runner" in closure  # named, not hashed
    assert "member_input" in bp.RUNNER_STATISTIC_FUNCTIONS


def test_sources_at_refuses_a_module_outside_the_repository_and_does_not_nest(tmp_path):
    with pytest.raises(bp.BatteryPassRefused, match="outside the repository"):
        with bp.sources_at("HEAD", tmp_path):
            bp.battery_code_key(BATTERY, FAMILY_MODULE)
    assert code_identity.source_path.__name__ == "source_path"  # restored after the error
    with bp.sources_at("HEAD", ROOT):
        with pytest.raises(bp.BatteryPassRefused, match="does not nest"):
            with bp.sources_at("HEAD", ROOT):
                pass


# -- a pre-declared replication: pooled counts (todo 636) ----------------------------------------


def _block(rejected_deepest, commit="abc"):
    cells = _cells()
    report = _report(cells)
    for row in report:
        row["levels"]["0.00167"]["rejected"] = rejected_deepest
    return {**_driver(commit=commit), "report": report}


def test_a_block_that_fails_alone_passes_when_the_pooled_counts_hold_and_both_blocks_are_kept():
    first, second = _block(6), _block(1)  # 6 > 5 alone at n=1000; pooled 7 <= 8 at n=2000
    with pytest.raises(bp.BatteryPassRefused, match="> 5"):
        _make([first])
    record = _make([first], replication_blocks=[[second]], seed_bases=[0, 1_000_000])
    assert record["sims_per_cell"] == 2000
    assert [b["seed_base"] for b in record["blocks"]] == [0, 1_000_000]
    assert record["blocks"][0]["report"][0]["levels"]["0.00167"]["rejected"] == 6
    pooled = record["report"][0]
    assert pooled["sims"] == 2000 and pooled["levels"]["0.00167"]["rejected"] == 7
    assert _require(records=[record]) == "record"


def test_the_pooled_run_fails_when_the_pooled_counts_exceed_the_pooled_bound():
    with pytest.raises(bp.BatteryPassRefused, match="9 > 8"):
        _make([_block(6)], replication_blocks=[[_block(3)]], seed_bases=[0, 1_000_000])


def test_a_replication_needs_non_overlapping_seed_ranges_the_same_cells_and_settings():
    for bases in ([0, 0], [0, 1], [0, 50_000]):
        with pytest.raises(bp.BatteryPassRefused, match="overlap"):
            _make([_block(1)], replication_blocks=[[_block(2)]], seed_bases=bases)
    with pytest.raises(bp.BatteryPassRefused, match="one seed base per block"):
        _make([_block(1)], replication_blocks=[[_block(2)]], seed_bases=[0])
    partial = {**_block(1), "scenarios": _cells()[:-1], "report": _report(_cells()[:-1])}
    with pytest.raises(bp.BatteryPassRefused, match="same cells"):
        _make([_block(1)], replication_blocks=[[partial]], seed_bases=[0, 1_000_000])
    short = {**_block(1), "scenarios": [{**c, "sessions": 300} for c in _cells()]}
    with pytest.raises(bp.BatteryPassRefused, match="other settings"):
        _make([_block(1)], replication_blocks=[[short]], seed_bases=[0, 1_000_000])


def test_a_replayed_block_and_a_block_with_other_arms_or_a_wrong_claimed_seed_are_refused():
    first = _block(1)
    with pytest.raises(bp.BatteryPassRefused, match="replayed"):
        _make([first], replication_blocks=[[first]], seed_bases=[0, 1_000_000])
    fewer_arms = {**_block(2), "report": _report(_cells(), arms=("a",))}
    with pytest.raises(bp.BatteryPassRefused, match="different \\(cell, arm\\) sets"):
        _make([_block(1)], replication_blocks=[[fewer_arms]], seed_bases=[0, 1_000_000])
    claimed = {**_block(2), "seed_base": 7}
    with pytest.raises(bp.BatteryPassRefused, match="not the claimed"):
        _make([_block(1)], replication_blocks=[[claimed]], seed_bases=[0, 1_000_000])
    no_levels = _block(2)
    del no_levels["report"][0]["levels"]["0.05"]
    with pytest.raises(bp.BatteryPassRefused, match="block 2: .*levels"):
        _make([_block(1)], replication_blocks=[[no_levels]], seed_bases=[0, 1_000_000])


def test_a_family_with_a_declared_replication_binds_only_pooled_over_its_declared_seeds(
    monkeypatch,
):
    monkeypatch.setattr(bp, "DECLARED_REPLICATIONS", {"seasonality": (0, 1_000_000)})
    with pytest.raises(bp.BatteryPassRefused, match="pre-declared replication"):
        _make([_block(1)])  # a single block, even a clean one
    with pytest.raises(bp.BatteryPassRefused, match="pre-declared replication"):
        _make([_block(1)], replication_blocks=[[_block(2)]], seed_bases=[0, 2_000_000])
    with pytest.raises(bp.BatteryPassRefused, match="must record its seed base"):
        _make([_block(1)], replication_blocks=[[_block(2)]], seed_bases=[0, 1_000_000])
    first, second = {**_block(1), "seed_base": 0}, {**_block(2), "seed_base": 1_000_000}
    record = _make([first], replication_blocks=[[second]], seed_bases=[0, 1_000_000])
    assert record["blocks"][1]["seed_base_recorded"] is True
    assert record["sims_per_cell"] == 2000 and record["seed_bases"] == [0, 1_000_000]


def test_the_daily_residual_declaration_is_two_fresh_disjoint_blocks_bound_only_in_that_order(
    monkeypatch,
):
    declared = bp.DECLARED_REPLICATIONS["daily_residual"]
    assert declared == (5_000_000, 6_000_000)
    used = (0, 1_000_000, 2_000_000, 3_000_000, 4_000_000, 9_000_000, 77_000_000)
    daily = bp.battery_scenarios("src.intelligence.research.null_battery_daily_residual")
    span = bp.SEED_STRIDE * (len(daily) - 1) + 2_000  # the driver draws base + stride * cell + sim
    ranges = [(b, b + span) for b in (*used, *declared)]
    ranges.sort()
    assert all(a[1] <= b[0] for a, b in zip(ranges, ranges[1:], strict=False))
    monkeypatch.setattr(bp, "DECLARED_REPLICATIONS", {"seasonality": declared})
    blocks = (
        [{**_block(1), "seed_base": declared[0]}],
        [[{**_block(2), "seed_base": declared[1]}]],
    )
    for bad in (
        [declared[0]],
        [declared[1], declared[0]],
        [declared[0], 3_000_000],
        [*declared, 7_000_000],
    ):
        with pytest.raises(bp.BatteryPassRefused, match="pre-declared replication"):
            _make(blocks[0], replication_blocks=list(blocks[1]), seed_bases=bad)
    with pytest.raises(bp.BatteryPassRefused, match="pre-declared replication"):
        _make(blocks[0])  # one block alone, even a clean one
    record = _make(blocks[0], replication_blocks=list(blocks[1]), seed_bases=list(declared))
    assert record["seed_bases"] == list(declared) and record["sims_per_cell"] == 2000


def test_a_declared_single_block_must_prove_its_seed_base(monkeypatch):
    monkeypatch.setattr(bp, "DECLARED_REPLICATIONS", {"seasonality": (2_000_000,)})
    with pytest.raises(bp.BatteryPassRefused, match="must record its seed base"):
        _make([_block(1)], seed_bases=[2_000_000])
    old_block = {**_block(1), "seed_base": 0}  # an earlier run cannot stand in for the fresh one
    with pytest.raises(bp.BatteryPassRefused, match="not the claimed 2000000"):
        _make([old_block], seed_bases=[2_000_000])
    record = _make([{**_block(1), "seed_base": 2_000_000}], seed_bases=[2_000_000])
    assert record["seed_bases"] == [2_000_000]


def test_a_new_spec_validator_or_field_does_not_stale_the_key_but_resolving_members_does(
    monkeypatch, tmp_path
):
    base = bp.battery_code_key(BATTERY, FAMILY_MODULE)
    spec_path = Path(code_identity.source_path(bp.SPEC))
    original = code_identity.source_path

    def variant(edit):
        fake = tmp_path / "spec_variant.py"
        fake.write_text(edit(spec_path.read_text()))
        monkeypatch.setattr(
            code_identity, "source_path", lambda n: fake if n == bp.SPEC else original(n)
        )

    variant(
        lambda t: t.replace(
            "class TotalReturnSpec(BaseModel):",
            "UNRELATED = 1\n\n\nclass TotalReturnSpec(BaseModel):",
            1,
        )
    )
    assert bp.battery_code_key(BATTERY, FAMILY_MODULE) == base
    monkeypatch.undo()
    variant(
        lambda t: t.replace("_check_member_path(dotted)\n    module, _, attr", "module, _, attr", 1)
    )
    assert bp.battery_code_key(BATTERY, FAMILY_MODULE) != base
