"""`corpus_rerun --check`: every refusal a launch would meet, read-only and all at once (the 2026-11-26
pilot restarts: a held-verdicts change after --new-run moved the pinned APR hash, and stored units of an
older pilot made the COPY fail on the primary key after minutes of compute)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import services.corpus_rerun as cr
import services.corpus_rerun_check as chk
from tests.unit.services.test_corpus_rerun import OTHER, RUN, _counts, _run, _world

START, END = datetime(2003, 1, 1, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC)


def _unit(key: str, *symbols: str, tf: str = "1d", start=START, end=END) -> chk.UnitSpan:
    return chk.UnitSpan(key, tf, start, end, tuple(symbols))


def _stored(key: str, *symbols: str, status: str = "completed", run: str | None = OTHER, **kwargs):
    return chk.StoredUnit(_unit(key, *symbols, **kwargs), run, status, 100)


def _spec(unit: chk.UnitSpan) -> SimpleNamespace:
    return SimpleNamespace(
        batch_key=unit.batch_key,
        tf=unit.tf,
        range_start=unit.range_start,
        range_end=unit.range_end,
        symbols=unit.symbols,
    )


def test_a_stored_unit_over_shared_symbols_with_another_batch_key_blocks():
    blockers = chk.find_blockers([_unit("new", "AAA", "BBB")], [_stored("old", "BBB", "CCC")])
    assert [(b.stored.unit.batch_key, b.blocks) for b in blockers] == [("old", ("new",))]


def test_the_same_batch_key_is_adopted_not_a_blocker():
    assert chk.find_blockers([_unit("k", "AAA")], [_stored("k", "AAA")]) == []


@pytest.mark.parametrize(
    "stored",
    [
        _stored("old", "ZZZ"),  # no shared symbol
        _stored("old", "AAA", tf="1h"),  # another timeframe
        _stored(
            "old", "AAA", start=END, end=datetime(2027, 1, 1, tzinfo=UTC)
        ),  # half-open ranges touch
        _stored("old", "AAA", status="superseded"),  # no longer holds rows
        _stored("old", "AAA", status="failed"),  # a failed COPY rolled back
    ],
)
def test_a_stored_unit_that_holds_no_rows_in_the_way_does_not_block(stored):
    assert chk.find_blockers([_unit("new", "AAA")], [stored]) == []


def test_a_started_unit_blocks_like_a_completed_one():
    assert chk.find_blockers([_unit("new", "AAA")], [_stored("old", "AAA", status="started")])


def test_apr_diff_names_every_moved_added_and_removed_key():
    diff = chk.apr_diff({"a": 1, "b": [1], "c": 3}, {"a": 1, "b": [1, 2], "d": 4})
    assert diff == ["b: [1] -> [1, 2]", "c: 3 -> None", "d: None -> 4"]


def test_apr_diff_is_empty_when_nothing_moved():
    assert chk.apr_diff({"a": 1}, {"a": 1}) == []


def test_render_reports_every_failure_at_once_and_says_the_launch_is_refused():
    checks = [
        {"name": "head", "ok": True, "detail": "fine"},
        {"name": "apr_hash", "ok": False, "detail": "moved"},
    ]
    blocker = chk.find_blockers([_unit("new", "AAA")], [_stored("old", "AAA")])
    lines, ok = chk.render(checks, ["held: 1 -> 2"], blocker)
    text = "\n".join(lines)
    assert not ok
    assert "FAIL apr_hash: moved" in text and "held: 1 -> 2" in text and "old" in text
    assert lines[-1] == "check: a launch would be refused"


def test_render_passes_a_clean_state():
    lines, ok = chk.render([{"name": "head", "ok": True, "detail": "fine"}], [], [])
    assert ok and lines[-1] == "check: would launch"


def _checked(world):
    return world.runner.check_report("pilot")


def test_check_report_lists_a_failed_pin_check_a_moved_key_and_a_blocker_together():
    run = _run(
        spans=(),
        measured={"apr_values": {"held": 1}, "data_gate_scope": "1d", "row_counts": _counts()},
    )
    unit = _unit("new", "AAA")
    world = _world(
        run,
        head="f" * 40,
        apr_values={"held": 2},
        planned=([_spec(unit)], set()),
        stored=[_stored("old", "AAA")],
    )
    lines, ok = _checked(world)
    text = "\n".join(lines)
    assert not ok
    assert "FAIL head:" in text and "held: 1 -> 2" in text and "old" in text


def test_check_report_is_clean_when_nothing_refuses():
    run = _run(
        spans=(),
        measured={"apr_values": {"held": 1}, "data_gate_scope": "1d", "row_counts": _counts()},
    )
    world = _world(run, apr_values={"held": 1}, planned=([_spec(_unit("new", "AAA"))], set()))
    lines, ok = _checked(world)
    assert ok, lines


def test_check_report_notes_a_run_that_recorded_no_pinned_values():
    world = _world(
        _run(spans=(), measured={"data_gate_scope": "1d", "row_counts": _counts()}),
        planned=([], set()),
    )
    lines, _ = _checked(world)
    assert any("recorded no pinned APR values" in line for line in lines)


def test_check_report_writes_nothing():
    world = _world(
        _run(spans=(), measured={"data_gate_scope": "1d", "row_counts": _counts()}),
        planned=([], set()),
    )
    _checked(world)
    assert world.store.steps == {} and world.commands == []


def test_the_check_flag_needs_a_run_and_refuses_through():
    with pytest.raises(SystemExit):
        cr._parse_args(["--new-run", "--check", "--data-gate-scope", "1d"])
    with pytest.raises(SystemExit):
        cr._parse_args(["--run-id", RUN, "--check", "--through", "pilot"])
    args = cr._parse_args(["--run-id", RUN, "--check"])
    assert args.check and args.step is None
