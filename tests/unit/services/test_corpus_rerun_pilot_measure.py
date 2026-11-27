"""The pilot measures the pilot, not its last invocation: a resumed pilot's per-unit time, bytes per row
and stored per spool follow the whole pilot (2026-11-26: a resume that loaded 9 of 63 units divided its
9 units' time by all 63 chunks and read about 7x too fast). The divisor is units LOADED; an invocation
that loaded nothing adds no seconds; stage_1d projects over every planned 1d unit, not over chunks.
"""

from __future__ import annotations

import pytest

import services.corpus_rerun as cr
from tests.unit.services.test_corpus_rerun import World, _stage_summary, _through, _world

PER_UNIT = 10.0


def _timed(world: World, passes: list[dict], hourly: list[dict] | None = None) -> None:
    """The 1d stage takes PER_UNIT seconds for each unit it computes (loaded or failed), with the summary
    each pass queues; the 1h stage is instant, with the summary each pass queues (default: one loaded).
    """
    clock = {"t": 0.0}
    world.runner.deps.monotonic = lambda: clock["t"]
    daily_queue, hourly_queue = list(passes), list(hourly or [])

    def stage(**kwargs):
        if kwargs["timeframes"] != ["1d"]:
            if not hourly_queue:
                return world.rebuild(**kwargs)
            step = hourly_queue.pop(0)
            for key in step["scope_batch_keys"]:
                world.store.provenance[key] = kwargs["run_id"]  # the 1h unit is complete either way
            return step
        step = daily_queue.pop(0)
        clock["t"] += PER_UNIT * (step["units_loaded"] + step["units_failed"])
        for key in step["scope_batch_keys"][step["units_failed"] :]:
            world.store.provenance[key] = kwargs["run_id"]  # the failed units are the first keys
        return step

    world.runner.deps.run_stage = stage


def _pass(loaded, failed=0, skipped=0, bpr=1000.0, sps=0.4, out_of_scope=0) -> dict:
    keys = [f"{i:064x}" for i in range(loaded + failed + skipped)]
    summary = _stage_summary(keys, failed=failed, bpr=bpr, sps=sps, out_of_scope=out_of_scope)
    return {**summary, "units_loaded": loaded}


def _measured_after(passes: list[dict], hourly: list[dict] | None = None) -> dict:
    world = _world()
    _through(world, "pilot")
    _timed(world, passes, hourly)
    for _ in passes:
        try:
            world.runner.execute("pilot")
        except cr.StepFailed:
            continue
    return world.store.run.measured


def test_a_pilot_resumed_after_a_kill_measures_the_same_time_per_unit_as_an_uninterrupted_one():
    clean = _measured_after([_pass(loaded=5)])
    # killed after 3 units; the resume adopts them and loads the other 2: no failure, no waste
    resumed = _measured_after([_pass(loaded=3, failed=0, skipped=2), _pass(loaded=2, skipped=3)])
    assert clean["pilot_seconds_1d_unit"] == PER_UNIT
    assert resumed["pilot_seconds_1d_unit"] == pytest.approx(PER_UNIT)
    assert resumed["extrapolated_seconds"] == clean["extrapolated_seconds"]


def test_failed_units_stay_in_the_numerator_so_a_resumed_pilot_reads_slow_never_fast():
    # 4 loaded and 1 failed (5 units of work), then the resume loads the failed one: 6 units of work
    # for 5 loaded units. The recorded 12 s per unit is 20 percent over the true 10: the safe side.
    resumed = _measured_after([_pass(loaded=4, failed=1), _pass(loaded=1, skipped=4)])
    assert resumed["pilot_seconds_1d_unit"] == pytest.approx(12.0)


def test_an_invocation_that_loaded_nothing_adds_no_seconds():
    resumed = _measured_after([_pass(loaded=0, failed=2), _pass(loaded=2, skipped=0)])
    assert resumed["pilot_1d_seconds"] == 2 * PER_UNIT and resumed["pilot_1d_units_loaded"] == 2


def test_the_projection_runs_over_every_planned_1d_unit_not_over_chunks():
    # 2 spans per chunk: 4 units loaded for 2 sample chunks, 6 more out of scope: 10 planned units
    measured = _measured_after([_pass(loaded=4, out_of_scope=6)])
    assert measured["pilot_seconds_1d_unit"] == PER_UNIT
    assert measured["extrapolated_seconds"]["stage_1d"] == 10 * PER_UNIT


def test_a_resumed_pilot_keeps_the_largest_bytes_per_row_and_stored_per_spool_it_saw():
    resumed = _measured_after(
        [
            _pass(loaded=4, failed=1, bpr=1315.0, sps=0.50),
            _pass(loaded=1, skipped=4, bpr=1175.0, sps=0.44),
        ]
    )
    assert resumed["pilot_bytes_per_row_1d"] == 1315.0
    assert resumed["pilot_stored_per_spool"] == 0.50


def test_the_loaded_time_of_a_failed_invocation_is_recorded_before_it_fails():
    world = _world()
    _through(world, "pilot")
    _timed(world, [_pass(loaded=3, failed=2)])
    with pytest.raises(cr.StepFailed, match="units_failed"):
        world.runner.execute("pilot")
    measured = world.store.run.measured
    assert measured["pilot_1d_seconds"] == 5 * PER_UNIT and measured["pilot_1d_units_loaded"] == 3


def test_a_pilot_that_loaded_no_unit_in_any_invocation_has_nothing_to_time():
    world = _world()
    _through(world, "pilot")
    _timed(world, [_pass(loaded=0, skipped=3)])
    with pytest.raises(cr.StepFailed, match="no pilot_1d unit was loaded"):
        world.runner.execute("pilot")


def test_a_resumed_scope_all_pilot_keeps_the_1h_time_of_the_invocation_that_loaded_the_unit():
    # pass 1 loads the 1h unit (100 rows) and fails on a 1d unit; pass 2 finds the 1h unit complete
    key = f"{99:064x}"
    loaded = _stage_summary([key], rows=100)
    skipped = {**_stage_summary([key]), "units_loaded": 0, "rows_loaded": 0}
    measured = _measured_after(
        [_pass(loaded=1, failed=1), _pass(loaded=1, skipped=1)], hourly=[loaded, skipped]
    )
    assert measured["pilot_1h_units_loaded"] == 1 and measured["pilot_1h_rows_loaded"] == 100


def test_a_scope_all_pilot_that_never_loaded_its_1h_unit_refuses_rather_than_report_near_zero():
    key = f"{99:064x}"
    skipped = {**_stage_summary([key]), "units_loaded": 0, "rows_loaded": 0}
    world = _world()
    _through(world, "pilot")
    _timed(world, [_pass(loaded=2)], hourly=[skipped])
    with pytest.raises(cr.StepFailed, match="no pilot_1h unit was loaded"):
        world.runner.execute("pilot")


def test_an_untimed_pilot_reports_its_unit_problems_first_with_the_stage_summary():
    world = _world()
    _through(world, "pilot")
    _timed(world, [_pass(loaded=0, failed=2)])
    with pytest.raises(cr.StepFailed, match="units_failed 2") as refused:
        world.runner.execute("pilot")
    assert "nothing to time" not in str(refused.value)
    assert refused.value.summary["stage_1d_sample"]["units_failed"] == 2


def test_an_untimed_pilot_of_adopted_units_names_the_runs_to_clear():
    world = _world()
    _through(world, "pilot")
    adopted = _pass(loaded=0, skipped=2)
    adopted["adopted"] = [
        {"batch_key": k, "adopted_from_run_id": "older-run"} for k in adopted["scope_batch_keys"]
    ]
    _timed(world, [adopted])
    with pytest.raises(cr.StepFailed, match="adopted from run\\(s\\) older-run"):
        world.runner.execute("pilot")
