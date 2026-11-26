"""The pilot measures the pilot, not its last invocation: a resumed pilot's per-unit time, bytes per row
and stored per spool equal an uninterrupted pilot's (2026-11-26: a resume that computed 9 of 63 units
divided its 9 units' time by all 63 chunks and read about 7x too fast)."""

from __future__ import annotations

import pytest

import services.corpus_rerun as cr
from tests.unit.services.test_corpus_rerun import World, _stage_summary, _through, _world

PER_UNIT = 10.0


def _timed(world: World, passes: list[dict]) -> None:
    """The 1d stage takes PER_UNIT seconds for each unit it computes (loaded or failed), with the
    summary each pass queues; the 1h stage is instant."""
    clock = {"t": 0.0}
    world.runner.deps.monotonic = lambda: clock["t"]
    queue = list(passes)
    default = world.rebuild

    def stage(**kwargs):
        if kwargs["timeframes"] != ["1d"]:
            return default(**kwargs)
        step = queue.pop(0)
        clock["t"] += PER_UNIT * (step["units_loaded"] + step["units_failed"])
        for key in step["scope_batch_keys"][step["units_failed"] :]:
            world.store.provenance[key] = kwargs["run_id"]  # the failed units are the first keys
        return step

    world.runner.deps.run_stage = stage


def _pass(
    loaded: int, failed: int, skipped: int = 0, bpr: float = 1000.0, sps: float = 0.4
) -> dict:
    keys = [f"{i:064x}" for i in range(loaded + failed + skipped)]
    summary = _stage_summary(keys, failed=failed, bpr=bpr, sps=sps)
    return {**summary, "units_loaded": loaded}


def _measured_after(passes: list[dict]) -> dict:
    world = _world()
    _through(world, "pilot")
    _timed(world, passes)
    for _ in passes:
        try:
            world.runner.execute("pilot")
        except cr.StepFailed:
            continue
    return world.store.run.measured


def test_a_resumed_pilot_measures_the_same_time_per_unit_as_an_uninterrupted_one():
    clean = _measured_after([_pass(loaded=5, failed=0)])
    resumed = _measured_after([_pass(loaded=4, failed=1), _pass(loaded=1, failed=0, skipped=4)])
    assert clean["pilot_seconds_1d_chunk"] == PER_UNIT
    assert resumed["pilot_seconds_1d_chunk"] == pytest.approx(PER_UNIT, rel=0.01)
    assert resumed["extrapolated_seconds"] == clean["extrapolated_seconds"]


def test_a_resumed_pilot_keeps_the_largest_bytes_per_row_and_stored_per_spool_it_saw():
    resumed = _measured_after(
        [
            _pass(loaded=4, failed=1, bpr=1315.0, sps=0.50),
            _pass(loaded=1, failed=0, bpr=1175.0, sps=0.44),
        ]
    )
    assert resumed["pilot_bytes_per_row_1d"] == 1315.0
    assert resumed["pilot_stored_per_spool"] == 0.50


def test_the_time_of_a_failed_invocation_is_recorded_before_it_fails():
    world = _world()
    _through(world, "pilot")
    _timed(world, [_pass(loaded=3, failed=2)])
    with pytest.raises(cr.StepFailed, match="units_failed"):
        world.runner.execute("pilot")
    measured = world.store.run.measured
    assert measured["pilot_stage_seconds"] == 5 * PER_UNIT and measured["pilot_units_computed"] == 5


def test_a_pilot_that_computed_no_unit_in_any_invocation_has_nothing_to_time():
    world = _world()
    _through(world, "pilot")
    _timed(world, [_pass(loaded=0, failed=0, skipped=3)])
    with pytest.raises(cr.StepFailed, match="no unit was computed"):
        world.runner.execute("pilot")
