"""The 1d-first corpus rerun (scope `1d`, runbook "The 1d-first run"): no span, no intraday step,
unit or timeframe anywhere in the chain. Same fakes as test_corpus_rerun.py."""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

import services.corpus_rerun as cr
from services.corpus_rerun_budget import RowCounts
from tests.unit.services.test_corpus_rerun import (
    APR,
    CHUNKS,
    RUN,
    SPANS,
    World,
    _counts,
    _ic_units,
    _jan1,
    _result,
    _run,
    _specs,
    _through,
    _world,
)

CHAIN_1D = [
    "data_gate", "pin_gate", "pilot", "stage_1d",
    "feature_complete", "ic_measure", "d19_bound", "canary",
]  # fmt: skip


def _counts_1d() -> list[list[Any]]:
    return [row for row in _counts() if row[0] == "1d"]


def _world_1d(**state_overrides) -> World:
    run = _run(spans=(), measured={"row_counts": _counts_1d(), "data_gate_scope": "1d"})
    world = _world(run, **state_overrides)
    world.state["gate"] = _result()
    return world


def _through_1d(world: World, name: str, **gate_summary) -> None:
    for step in world.runner.steps:
        if step.name == name:
            return
        done = {"scope": "1d", **gate_summary} if step.name == "data_gate" else {}
        world.store.steps[step.name] = cr.StepRow("completed", done)


def _only_1d_outcomes(world: World) -> None:
    world.state["report"]["outcomes"] = [
        o for o in world.state["report"]["outcomes"] if "1h" not in o["unit_key"]
    ]


def test_a_1d_chain_has_no_span_step_and_the_all_chain_is_unchanged():
    steps = cr.build_steps((), "1d")
    assert [s.name for s in steps] == CHAIN_1D
    assert all(s.kind != cr.SPAN for s in steps)
    assert steps[0].upstream is None and all(b.upstream == a.name for a, b in zip(steps, steps[1:]))
    assert [s.name for s in cr.build_steps(SPANS, "all")][4:6] == ["s1.1h", "s1.15m"]
    assert [s.name for s in _world_1d().runner.steps] == CHAIN_1D
    assert [s.name for s in _world().runner.steps] == [s.name for s in cr.build_steps(SPANS, "all")]


def test_a_1d_run_cannot_carry_spans_and_an_unknown_scope_has_no_chain():
    with pytest.raises(ValueError, match="no spans"):
        cr.build_steps(SPANS, "1d")
    for scope in ("both", "", None):
        with pytest.raises(ValueError, match="scope"):
            cr.build_steps(SPANS, scope)  # type: ignore[arg-type]
    with pytest.raises(cr.StepRefused, match="valid scope"):
        _world(_run(measured={"row_counts": _counts()}))


def test_a_1d_run_has_no_span_step_to_execute():
    with pytest.raises(cr.StepRefused, match="unknown step"):
        _world_1d().runner.execute("s1.1h")


def test_a_1d_run_refuses_any_stage_that_is_not_1d_only():
    world = _world_1d()
    for kwargs in ({"timeframes": ["1h"]}, {"timeframes": ["1d", "5m"]}, {}):
        with pytest.raises(cr.StepRefused, match="1d only"):
            world.runner._stage(**kwargs)
    assert world.rebuild.calls == []


def test_the_1d_pilot_runs_chunk_0_of_1d_only_with_every_gate_on_1d():
    world = _world_1d(member_months={"AAA": (12, False)})
    _through_1d(world, "pilot")
    summary = world.runner.execute("pilot")
    (daily,) = world.rebuild.calls
    assert daily["timeframes"] == ["1d"] and daily["chunk_indices"] == [0]
    assert "span" not in daily
    argvs = [argv for argv, _ in world.commands]
    screen = next(a for a in argvs if "ops_feature_column_screen.py" in a[1])
    assert "--null-gate" in screen and screen[screen.index("--tf") + 1] == "1d"
    assert screen.count("--tf") == 1 and not any("1h" in a for argv in argvs for a in argv)
    gate = next(a for a in argvs if "ops_pilot_compute_gate.py" in a[1])
    assert gate[gate.index("--units") + 1 :] == ["AAA:1d", "BBB:1d"]
    assert set(summary["gates"]) == {"G1-G3", "G4-G5", "G6-objects"}
    measured = world.store.run.measured
    assert "pilot_bytes_per_row_intraday" not in measured
    assert "pilot_seconds_1h_unit" not in measured
    assert measured["pilot_bytes_per_row_1d"] == 1379.0
    assert set(measured["extrapolated_seconds"]) == {"stage_1d"}
    assert set(measured["pilot_compression"]) == {"1d"}
    assert measured["compression_ratio_measured"] == 5.0
    assert "s1_1h_unit" not in summary
    assert [p["step"] for p in summary["reprojection"]] == ["stage_1d"]


@pytest.mark.parametrize(
    "state, match",
    [
        ({"returncodes": {"ops_feature_column_screen.py": 1}}, "G1-G3"),
        ({"returncodes": {"ops_pilot_compute_gate.py": 1}}, "G4-G5"),
    ],
)
def test_a_red_1d_gate_fails_the_1d_pilot(state, match):
    world = _world_1d(**state)
    _through_1d(world, "pilot")
    with pytest.raises(cr.StepFailed, match=match):
        world.runner.execute("pilot")
    with pytest.raises(cr.StepRefused, match="pilot is failed"):
        world.runner.execute("stage_1d")


def test_a_red_object_gate_fails_the_1d_pilot():
    world = _world_1d()
    _through_1d(world, "pilot")
    original = world.rebuild.__call__

    def bad_stats(**kwargs):
        summary = original(**kwargs)
        world.store.stats[summary["scope_batch_keys"][0]] = (
            "1d",
            {"swing_high_dist_atr": {"present": 1000, "nan_present": 950}},
        )
        return summary

    world.runner.deps.run_stage = bad_stats
    with pytest.raises(cr.StepFailed, match="G6-objects"):
        world.runner.execute("pilot")


def test_the_1d_pilot_fails_before_stage_1d_when_the_measured_1d_bytes_overflow():
    world = _world_1d()
    _through_1d(world, "pilot")
    original = world.rebuild.__call__

    def heavy(**kwargs):
        summary = original(**kwargs)
        summary["bytes_per_row_max"] = 2e10
        return summary

    world.runner.deps.run_stage = heavy
    with pytest.raises(cr.StepFailed, match="overflow the run's stage_1d peak.*no spans"):
        world.runner.execute("pilot")


def test_the_1d_pilot_is_allowed_on_a_1d_verdict_and_an_all_pilot_is_not():
    world = _world_1d()
    _through_1d(world, "pilot")
    world.runner.execute("pilot")  # the verdict is scope 1d
    allrun = _world()
    _through(allrun, "pilot")
    allrun.store.steps["data_gate"] = cr.StepRow("completed", {"scope": "1d"})
    with pytest.raises(cr.StepRefused, match="intraday"):
        allrun.runner.execute("pilot")


def test_the_pilot_records_the_proven_start_disclosure():
    world = _world_1d(member_months={"RSX": (10, False), "BFX": (5, True), "AAA": (100, True)})
    _through_1d(world, "pilot", names_member_before_proven_start=["RSX", "BFX", "NOROW"])
    summary = world.runner.execute("pilot")
    assert summary["proven_start_disclosure"] == {
        "names": 2,
        "names_in_5m_tier": 1,
        "member_months": 15,
        "member_months_total": 115,
    }


def test_the_all_pilot_records_it_too_and_keeps_its_1h_unit():
    world = _world(member_months={"RSX": (10, False)})
    _through(world, "pilot")
    world.store.steps["data_gate"] = cr.StepRow(
        "completed", {"scope": "all", "names_member_before_proven_start": ["RSX"]}
    )
    summary = world.runner.execute("pilot")
    assert summary["proven_start_disclosure"]["member_months"] == 10
    assert [c["timeframes"] for c in world.rebuild.calls] == [["1d"], ["1h"]]


def _intraday_flags(world: World, names: tuple[str, ...]) -> list[bool]:
    seen: list[bool] = []
    original = world.runner.deps.preconditions
    world.runner.deps.preconditions = lambda intraday, disk: (
        seen.append(intraday) or original(intraday, disk)
    )
    for name in names:
        world.runner.pin_checks(world.runner.by_name[name])
    return seen


def test_the_1d_disk_gate_skips_the_intraday_preconditions_and_the_all_gate_keeps_them():
    assert _intraday_flags(_world_1d(), ("pilot", "stage_1d")) == [False, False]
    assert _intraday_flags(_world(), ("pilot", "stage_1d", "s1.1h")) == [True, False, True]


def test_the_1d_feature_complete_plans_and_screens_1d_only():
    world = _world_1d(planned=(_specs("k1"), set()))
    _through_1d(world, "feature_complete")
    world.store.provenance["k1"] = RUN
    healthy = {"swing_high_dist_atr": {"present": 100, "nan_present": 1}}
    world.store.stats["k1"] = ("1d", healthy)  # a 1d run's units are 1d units
    summary = world.runner.execute("feature_complete")
    assert world.state["planned_tfs"] == [["1d"]]
    assert set(summary["column_screen"]) == {"1d"}
    screens = [argv for argv, _ in world.commands if "ops_feature_column_screen.py" in argv[1]]
    assert len(screens) == 1 and screens[0][screens[0].index("--tf") + 1] == "1d"
    assert set(summary["object_share"]["shares"]) <= {"1d"}


def test_the_all_feature_complete_plans_the_full_scope():
    world = _world(planned=(_specs("k1"), set()))
    _through(world, "feature_complete")
    world.store.provenance["k1"] = RUN
    world.runner.execute("feature_complete")
    assert world.state["planned_tfs"] == [None]  # the full scope, as before the 1d run existed


def test_the_1d_ic_measure_runs_and_expects_1d_pairs_only():
    world = _world_1d()
    _through_1d(world, "ic_measure")
    _ic_units(world, RUN)
    _only_1d_outcomes(world)  # the run's report holds no 1h unit
    world.store.lookaheads = {"1h": {1: 9, 6: 9}, "1d": {1: 9}}  # 1h rows are not this run's
    summary = world.runner.execute("ic_measure")
    argv, _ = world.commands[-1]
    assert argv[argv.index("--tf") :] == ["--tf", "1d"]
    assert summary["pooled_lookaheads"] == {"1d": [1]}


def test_the_1d_ic_measure_fails_on_a_missing_1d_lookahead():
    world = _world_1d()
    _through_1d(world, "ic_measure")
    _ic_units(world, RUN)
    world.store.lookaheads = {"1h": {1: 9}}
    with pytest.raises(cr.StepFailed, match="1d: no POOLED rows at lookaheads"):
        world.runner.execute("ic_measure")


def test_the_all_ic_measure_command_has_no_tf_restriction():
    world = _world()
    _through(world, "ic_measure")
    _ic_units(world, RUN)
    world.runner.execute("ic_measure")
    assert "--tf" not in world.commands[-1][0]


def test_the_1d_d19_bound_and_canary_restrict_to_1d_and_the_all_ones_do_not():
    world = _world_1d()
    _through_1d(world, "d19_bound")
    world.runner.execute("d19_bound")
    assert world.store.reaching_tfs == ["1d"]
    world.runner.execute("canary")
    assert world.commands[-1][0][-4:] == ["--run-id", RUN, "--tf", "1d"]
    allrun = _world()
    _through(allrun, "d19_bound")
    allrun.runner.execute("d19_bound")
    assert allrun.store.reaching_tfs is None
    allrun.runner.execute("canary")
    assert "--tf" not in allrun.commands[-1][0]


def test_every_step_of_a_1d_run_reaches_no_intraday_stage_unit_or_command():
    world = _world_1d(planned=(_specs("k1"), set()), member_months={"AAA": (1, False)})
    world.store.provenance["k1"] = RUN
    _ic_units(world, RUN)
    _only_1d_outcomes(world)
    world.store.lookaheads = {"1d": {1: 9}}
    world.runner.through("canary")
    assert {tuple(c["timeframes"]) for c in world.rebuild.calls} == {("1d",)}
    assert all("span" not in c for c in world.rebuild.calls)
    words = {a for argv, _ in world.commands for a in argv}
    assert not {"5m", "15m", "1h"} & words and not any(
        w.endswith((":5m", ":15m", ":1h")) for w in words
    )
    assert set(world.store.steps) == {s.name for s in world.runner.steps}


def test_plan_daily_only_plans_no_span_and_refuses_an_overflowing_peak():
    from services.corpus_rerun_budget import SpanPlanRefused, plan_daily_only

    probe = _world_1d()
    counts, inputs = probe.runner._counts(), probe.runner._inputs()
    plan = plan_daily_only(counts, inputs)
    assert plan.spans == [] and [p.step for p in plan.peaks] == ["stage_1d"]
    with pytest.raises(SpanPlanRefused, match="stage_1d peak"):
        plan_daily_only(counts, dataclasses.replace(inputs, free_bytes_at_launch=1000))


def test_plan_run_at_scope_1d_counts_1d_only_and_plans_no_span(monkeypatch):
    from services import backfill_feature_factory as factory

    seen: dict[str, Any] = {}
    ctx = SimpleNamespace(
        chunks=CHUNKS, starts={}, intraday=frozenset(), all_timeframes=["5m", "15m", "1h", "1d"]
    )
    monkeypatch.setattr(factory, "_stage_context", lambda *a: ctx)
    monkeypatch.setattr(factory, "database_free_bytes", lambda cfg: 700 * 10**9)
    monkeypatch.setattr(factory, "max_wal_bytes", lambda conn: 16 * 10**9)
    monkeypatch.setattr(cr, "load_config_service_sync", lambda conn: object())
    monkeypatch.setattr(cr, "load_corpus_rerun_apr", lambda cfg: APR)
    monkeypatch.setattr(cr, "chunk_interval", lambda conn: timedelta(days=360))

    def counts(conn, chunks, starts, horizon, tfs, intraday):
        seen["tfs"] = list(tfs)
        return RowCounts({("1d", 0, date(2020, 1, 1)): 100})

    def stored(conn, settings, horizon, chunks, intraday, planned=None, timeframes=None):
        seen["stored_tfs"] = timeframes
        return cr.Adoption(RowCounts({}), {})

    monkeypatch.setattr(cr, "fetch_row_counts", counts)
    monkeypatch.setattr(cr, "stored_row_counts", stored)
    plan = cr.plan_run(object(), object(), _jan1(2026), "1d")
    assert plan.spans == [] and seen == {"tfs": ["1d"], "stored_tfs": ["1d"]}
    assert [p.step for p in plan.peaks] == ["stage_1d"]
    with pytest.raises(ValueError, match="scope"):
        cr.plan_run(object(), object(), _jan1(2026), "both")
