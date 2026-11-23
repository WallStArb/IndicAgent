"""Todo 653: panel-source members and the orthogonalization stage (member_sources), and the
proof that adding them left every recorded battery code key and spec hash alone."""

import inspect
import json
from pathlib import Path

import numpy as np
import pytest

from src.intelligence.research import battery_pass, member_sources, runner
from src.intelligence.research.panel import Panel
from src.intelligence.research.spec import (
    MemberSpec,
    family_spec_hash,
    load_spec_from_file,
)

ROOT = Path(__file__).resolve().parents[3]
PASSES = {
    "daily_residual": (
        "src.intelligence.research.null_battery_daily_residual",
        "src.intelligence.research.families.daily_residual",
    ),
    "seasonality": (
        "src.intelligence.research.null_battery_seasonality",
        "src.intelligence.research.families.seasonality",
    ),
}


@pytest.mark.parametrize("family", sorted(PASSES))
def test_recorded_battery_code_keys_are_unchanged(family):
    """The recorded passes still bind: adding panel_source and the stage moved no code key."""
    battery, module = PASSES[family]
    record = sorted((ROOT / "research" / "battery_passes").glob(f"{family}_*.json"))[-1]
    recorded = json.loads(record.read_text())["binding"]["battery_code_key"]
    assert battery_pass.battery_code_key(battery, module) == recorded


@pytest.mark.parametrize("name", ["daily_residual_h5", "daily_residual_h5_core"])
def test_unset_new_member_fields_leave_the_spec_hash_alone(name):
    loaded = load_spec_from_file(ROOT / "research" / "specs" / f"{name}.yaml", ROOT)
    assert family_spec_hash(loaded.model) == loaded.spec_hash


def _spec(orth=True, source="volume"):
    base = load_spec_from_file(ROOT / "research" / "specs" / "daily_residual_h5.yaml", ROOT).model
    first = base.members[0]
    member = MemberSpec(
        name="shock",
        signal=first.signal,
        params={},
        slot_history_sessions=5,
        declared_memory_rows=5,
        panel_source=source,
        orthogonalize={"sum_sessions": 2, "min_names": 6} if orth else None,
    )
    return base.model_copy(update={"members": [first, member]}), member


def _panel(n=40, m=14, seed=0, member_cols=10):
    rng = np.random.default_rng(seed)
    member = np.zeros((n, m), dtype=bool)
    member[:, :member_cols] = True
    return Panel(
        tf="1d",
        symbols=tuple(f"S{i}" for i in range(m)),
        timestamps=np.arange(n).astype("datetime64[D]"),
        bars_per_session=1,
        valid=np.ones(n, dtype=bool),
        open=np.exp(rng.normal(0, 0.01, (n, m))),
        close=np.exp(rng.normal(0, 0.01, (n, m))),
        volume=np.exp(rng.normal(10, 0.5, (n, m))),
        member=member,
    )


def _rank_member(source, *, bars_per_session, coverage_floor):
    """A stand-in member: the trailing 3-row mean of the source (a pure function of rows <= d)."""
    out = np.full(source.shape, np.nan)
    for d in range(2, len(source)):
        out[d] = source[d - 2 : d + 1].mean(axis=0)
    return out


@pytest.fixture
def stand_in(monkeypatch):
    monkeypatch.setattr(member_sources, "resolve_member", lambda signal: _rank_member)


def test_a_panel_member_reads_the_panel_field_and_is_masked(stand_in):
    spec, _ = _spec(orth=False)
    panel = _panel()
    out = member_sources.compute_panel_members(spec, panel, bars_per_session=1)
    assert set(out) == {"shock"}
    assert np.isnan(out["shock"][:, 10:]).all()  # non-members are out
    np.testing.assert_array_equal(
        out["shock"][2:, :10],
        _rank_member(panel.volume, bars_per_session=1, coverage_floor=2)[2:, :10],
    )


def test_stage_residual_is_orthogonal_and_ignores_non_members(stand_in):
    spec, _ = _spec()
    panel = _panel()
    rng = np.random.default_rng(1)
    resid = rng.normal(0, 0.02, panel.close.shape)
    members = member_sources.compute_panel_members(spec, panel, bars_per_session=1)
    base = member_sources.orthogonalize_members(spec, members, resid, bars_per_session=1)
    row = base["shock"][20]
    fin = np.isfinite(row)
    assert fin.sum() == 10
    e = (resid[19] + resid[20])[fin]
    assert abs(row[fin] @ e) < 1e-10 and abs(row[fin] @ np.abs(e)) < 1e-10
    # a non-member's volume and residual can not move any member's residual (bit identical)
    moved_panel = _panel()
    moved_panel.volume[:, 10:] *= 50.0
    moved_resid = resid.copy()
    moved_resid[:, 10:] += 0.5
    moved = member_sources.orthogonalize_members(
        spec,
        member_sources.compute_panel_members(spec, moved_panel, bars_per_session=1),
        moved_resid,
        bars_per_session=1,
    )
    np.testing.assert_array_equal(base["shock"], moved["shock"])


def test_stage_floor_masks_thin_rows_and_passes_other_members_through(stand_in):
    spec, member = _spec()
    thin = spec.model_copy(
        update={
            "members": [
                spec.members[0],
                member.model_copy(
                    update={
                        "orthogonalize": member.orthogonalize.model_copy(update={"min_names": 11})
                    }
                ),
            ]
        }
    )
    panel = _panel()
    resid = np.random.default_rng(2).normal(0, 0.02, panel.close.shape)
    members = member_sources.compute_panel_members(thin, panel, bars_per_session=1)
    out = member_sources.orthogonalize_members(thin, members, resid, bars_per_session=1)
    assert np.isnan(out["shock"]).all()  # 10 members < 11
    plain = {"other": np.ones((3, 3))}
    assert (
        member_sources.orthogonalize_members(
            thin, plain | {"shock": members["shock"]}, resid, bars_per_session=1
        )["other"]
        is plain["other"]
    )


def test_stage_needs_the_daily_clock(stand_in):
    spec, _ = _spec()
    with pytest.raises(ValueError, match="1d book clock"):
        member_sources.orthogonalize_members(
            spec, {"shock": np.zeros((4, 4))}, np.zeros((4, 4)), bars_per_session=2
        )


def test_the_runner_and_any_battery_share_one_stage_function(stand_in, monkeypatch):
    """compute_family_members reaches the stage and the panel members only through
    member_sources attributes: a battery that imports the same two functions certifies them."""
    calls = []
    real = member_sources.orthogonalize_members

    def spy(*args, **kwargs):
        calls.append(args[0].family)
        return real(*args, **kwargs)

    monkeypatch.setattr(member_sources, "orthogonalize_members", spy)
    spec, _ = _spec()
    panel = _panel()
    resid = np.zeros(panel.close.shape)
    members = runner.compute_family_members(spec, resid, bars_per_session=1, panel=panel)
    assert calls == [spec.family]
    assert list(members) == [m.name for m in spec.members]
    assert runner.member_sources is member_sources
    for fn in (runner.run_family, runner.run_book):
        src = inspect.getsource(fn)
        assert "compute_family_members(" in src and "compute_members(" not in src


def test_a_spec_without_panel_members_is_compute_members(monkeypatch):
    spec = load_spec_from_file(ROOT / "research" / "specs" / "daily_residual_h5.yaml", ROOT).model
    sentinel = {"x": np.zeros(1)}
    monkeypatch.setattr(runner, "compute_members", lambda *a, **k: sentinel)
    assert runner.compute_family_members(spec, np.zeros((2, 2)), bars_per_session=1) is sentinel


def test_close_needs_total_return_and_orthogonalize_needs_a_panel_source():
    spec, member = _spec(orth=False, source="close")
    assert spec.panel.total_return is not None  # the daily spec declares it: valid
    spec_type = type(spec)
    bare = spec.model_dump() | {"panel": spec.panel.model_dump() | {"total_return": None}}
    with pytest.raises(ValueError, match="total_return"):
        spec_type.model_validate(bare)
    with pytest.raises(ValueError, match="orthogonalize needs"):
        MemberSpec(
            **{
                **member.model_dump(),
                "panel_source": None,
                "orthogonalize": {"sum_sessions": 1, "min_names": 4},
            }
        )
    with pytest.raises(ValueError, match="excludes input"):
        MemberSpec(**{**member.model_dump(), "smoothing_half_life": 5})


def test_input_hash_sees_the_source_and_the_stage_and_only_when_set():
    spec, member = _spec()
    base = battery_pass.battery_input_hash(spec)

    def with_member(**change):
        changed = member.model_copy(update=change)
        return battery_pass.battery_input_hash(
            spec.model_copy(update={"members": [spec.members[0], changed]})
        )

    o = member.orthogonalize
    assert with_member(orthogonalize=o.model_copy(update={"sum_sessions": 1})) != base
    assert with_member(orthogonalize=o.model_copy(update={"min_names": 7})) != base
    assert with_member(orthogonalize=None) != base
    assert with_member(panel_source="close") != base
    daily = load_spec_from_file(ROOT / "research" / "specs" / "daily_residual_h5.yaml", ROOT).model
    (record,) = (ROOT / "research" / "battery_passes").glob("daily_residual_*.json")
    assert battery_pass.battery_input_hash(daily) in record.read_text()


def test_stage_memory_and_clock_are_refused_at_load():
    spec, member = _spec()
    with pytest.raises(ValueError, match="exceeds slot_history_sessions"):
        MemberSpec(
            **{
                **member.model_dump(),
                "slot_history_sessions": 3,
                "orthogonalize": {"sum_sessions": 10, "min_names": 6},
            }
        )
    five_minute = spec.model_dump() | {"panel": spec.panel.model_dump() | {"tf": "5m"}}
    with pytest.raises(ValueError, match="1d book clock"):
        type(spec).model_validate(five_minute)


def test_check_spec_declared_memory_rule_for_panel_members():
    from src.intelligence.research import runner
    from src.intelligence.research.runner import RunRefused

    spec, member = _spec(orth=False)
    runner._check_spec(spec.model_copy(update={"members": [spec.members[0], member]}))
    bad = member.model_copy(update={"declared_memory_rows": 99})
    with pytest.raises(RunRefused, match="declared_memory_rows 99"):
        runner._check_spec(spec.model_copy(update={"members": [spec.members[0], bad]}))
    spec_o, member_o = _spec()  # orthogonalized: slot history plus S1's reach, not the bare window
    with pytest.raises(RunRefused, match="declared_memory_rows 5"):
        runner._check_spec(spec_o)


def test_member_recipe_params_see_the_source_and_the_stage():
    import dataclasses
    import json

    from src.intelligence.research import recipe

    spec, member = _spec()
    loaded = load_spec_from_file(ROOT / "research" / "specs" / "daily_residual_h5.yaml", ROOT)
    plain = member.model_copy(update={"orthogonalize": None})
    other = member.model_copy(update={"panel_source": "close"})
    keys = {
        json.dumps(
            recipe.family_recipes(
                dataclasses.replace(
                    loaded, model=spec.model_copy(update={"members": [spec.members[0], m]})
                )
            )[f"member.{spec.family}.shock"].hashed(),
            sort_keys=True,
            default=str,
        )
        for m in (member, plain, other)
    }
    assert len(keys) == 3
