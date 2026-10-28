"""Calendar-anchored ridge refits (design 4.2, plan 187-09 Task 2, R-187-18)."""

import dataclasses
import datetime
import json
from types import SimpleNamespace

import numpy as np
import pytest

from src.intelligence.research import combiner as combiner_mod
from src.intelligence.research import snapshot
from src.intelligence.research.combiner import (
    EqualWeight,
    RidgeSpec,
    anchored_refit_positions,
    exchange_sessions,
    refit_positions,
    walk_forward_ridge,
)
from tests.unit.research.test_combiner_missing_members import _frozen_ridge

BPS = 2
BASE = dict(window_rows=60 * BPS, refit_rows=10 * BPS, penalty=0.5, embargo=3, min_obs=30)
ANCHOR = datetime.date(2014, 1, 2)
SPEC = RidgeSpec(**BASE, refit_anchor=ANCHOR)


def _sessions(n=300, first="2014-01-02"):
    cal = exchange_sessions(np.datetime64(first, "D"), np.datetime64("2016-12-31", "D"))
    return cal[:n]


def _rows(sessions):
    return np.repeat(sessions, BPS)


def _panel(seed=0, n_sessions=300, m=12, k=3):
    rng = np.random.default_rng(seed)
    n = n_sessions * BPS
    stack = rng.normal(size=(n, m, k))
    stack[rng.random((n, m, k)) < 0.1] = np.nan
    target = stack @ np.array([0.3, -0.1, 0.2]) + rng.normal(size=(n, m))
    target[rng.random((n, m)) < 0.1] = np.nan
    return stack, target


def test_exchange_is_the_snapshot_calendar():
    assert combiner_mod._EXCHANGE == snapshot._EXCHANGE


def test_unset_anchor_is_unchanged():
    stack, target = _panel()
    plain = RidgeSpec(**BASE)
    before = _frozen_ridge()
    old = before.walk_forward_ridge(stack, target, before.RidgeSpec(**BASE))
    np.testing.assert_array_equal(
        refit_positions(len(stack), plain),
        before.refit_positions(len(stack), before.RidgeSpec(**BASE)),
    )
    np.testing.assert_array_equal(walk_forward_ridge(stack, target, plain), old)
    with_dates = plain.combine(stack, target, row_session_dates=_rows(_sessions()))
    np.testing.assert_array_equal(with_dates, old)


def test_refits_fall_on_the_anchor_grid():
    sessions = _sessions()
    pos = anchored_refit_positions(_rows(sessions), SPEC)
    # Session index of each refit row, counted from the anchor (the panel's first session).
    idx = pos // BPS
    assert np.all(pos % BPS == 0)  # a refit is the first row of its session
    assert np.all(idx % 10 == 0)
    assert pos[0] >= SPEC.window_rows + SPEC.embargo - 1
    assert pos[0] - 10 * BPS < SPEC.window_rows + SPEC.embargo - 1  # the first full window
    assert idx[-1] + 10 >= len(sessions)


def test_a_later_panel_refits_on_the_same_dates():
    sessions = _sessions()
    late = sessions[37:]
    a = sessions[anchored_refit_positions(_rows(sessions), SPEC) // BPS]
    b = late[anchored_refit_positions(_rows(late), SPEC) // BPS]
    assert b[0] > a[0]
    np.testing.assert_array_equal(a[a >= b[0]], b)
    # Row-0 anchoring, by contrast, puts the later panel's refits on other dates.
    plain = RidgeSpec(**BASE)
    a0 = sessions[refit_positions(len(sessions) * BPS, plain) // BPS]
    b0 = late[refit_positions(len(late) * BPS, plain) // BPS]
    assert not np.isin(b0, a0).all()


def test_predictions_differ_only_where_training_history_differs():
    sessions = _sessions()
    stack, target = _panel()
    off = 37 * BPS
    full = SPEC.combine(stack, target, row_session_dates=_rows(sessions))
    late = SPEC.combine(stack[off:], target[off:], row_session_dates=_rows(sessions[37:]))
    first = anchored_refit_positions(_rows(sessions[37:]), SPEC)[0]
    assert np.isnan(late[:first]).all()
    assert np.isfinite(full[off : off + first]).any()  # the longer panel was already fitted
    # Same training rows on both panels from the later panel's first refit on; the moments are
    # differenced from prefix sums with other origins, so equal up to rounding, not bit for bit.
    np.testing.assert_allclose(late[first:], full[off + first :], rtol=1e-9, atol=1e-12)

    # A target the later panel's training sees changes exactly the blocks whose fold holds it.
    pos = anchored_refit_positions(_rows(sessions[37:]), SPEC)
    r = pos[3] - SPEC.embargo  # the last training row of the fourth fold
    target2 = target[off:].copy()
    assert np.isfinite(target2[r]).any()
    target2[r] = target2[r] + 5.0
    moved = SPEC.combine(stack[off:], target2, row_session_dates=_rows(sessions[37:]))
    ends = np.append(pos[1:], len(moved))
    for p, q in zip(pos, ends, strict=True):
        hi = p - SPEC.embargo + 1
        lo = max(0, hi - SPEC.window_rows)
        # Prefix sums carry the change to every later index, so "same" is up to rounding.
        same = np.allclose(moved[p:q], late[p:q], rtol=1e-9, atol=1e-12, equal_nan=True)
        assert same == (not lo <= r < hi), (p, lo, hi, r)


def test_a_grid_date_missing_from_the_panel_maps_to_the_next_session():
    sessions = _sessions()
    pos = anchored_refit_positions(_rows(sessions), SPEC)
    hole = pos[2] // BPS  # a refit session the panel lacks (no name traded that day)
    holed = np.delete(sessions, hole)
    got = anchored_refit_positions(_rows(holed), SPEC)
    assert len(got) == len(pos)  # no refit is skipped
    assert holed[got[2] // BPS] == sessions[hole + 1]
    others = np.delete(np.arange(len(pos)), 2)
    np.testing.assert_array_equal(holed[got[others] // BPS], sessions[pos[others] // BPS])


def test_an_anchor_on_a_holiday_starts_at_the_next_session():
    sessions = _sessions(first="2014-12-01")
    on_holiday = dataclasses.replace(SPEC, refit_anchor=datetime.date(2014, 12, 25))
    next_day = dataclasses.replace(SPEC, refit_anchor=datetime.date(2014, 12, 26))
    np.testing.assert_array_equal(
        anchored_refit_positions(_rows(sessions), on_holiday),
        anchored_refit_positions(_rows(sessions), next_day),
    )


def test_an_anchor_outside_the_panel_keeps_its_phase():
    sessions = _sessions()
    # Anchors 20 sessions before, and 230 sessions after, the panel's first session: both are
    # whole multiples of the 10-session cadence from it, so the grid is the same.
    cal = exchange_sessions(np.datetime64("2013-01-01", "D"), np.datetime64("2016-12-31", "D"))
    i = int(np.searchsorted(cal, sessions[0]))
    base = anchored_refit_positions(_rows(sessions), SPEC)
    for shift in (-20, 230):
        moved = dataclasses.replace(SPEC, refit_anchor=cal[i + shift].item())
        np.testing.assert_array_equal(anchored_refit_positions(_rows(sessions), moved), base)
    off = dataclasses.replace(SPEC, refit_anchor=cal[i - 3].item())
    assert not np.array_equal(anchored_refit_positions(_rows(sessions), off), base)


def test_combine_without_session_dates_raises_when_anchored():
    stack, target = _panel()
    with pytest.raises(ValueError, match="row_session_dates"):
        SPEC.combine(stack, target)
    with pytest.raises(ValueError, match="row_session_dates"):
        walk_forward_ridge(stack, target, SPEC)


def test_row_session_dates_must_match_the_panel():
    stack, target = _panel()
    rows = _rows(_sessions())
    with pytest.raises(ValueError, match="rows"):
        SPEC.combine(stack, target, row_session_dates=rows[:-2])
    with pytest.raises(ValueError, match="session"):
        anchored_refit_positions(rows[1:-1], SPEC)  # ragged sessions
    with pytest.raises(ValueError, match="sorted"):
        anchored_refit_positions(rows[::-1], SPEC)
    odd = dataclasses.replace(SPEC, refit_rows=21)
    with pytest.raises(ValueError, match="whole number of sessions"):
        anchored_refit_positions(rows, odd)


def test_equal_weight_ignores_session_dates():
    stack, _ = _panel()
    ew = EqualWeight((1.0, -1.0, 1.0))
    np.testing.assert_array_equal(
        ew.combine(stack, None, row_session_dates=_rows(_sessions())), ew.combine(stack, None)
    )


def test_spec_refit_anchor_is_an_optional_ridge_field(tmp_path):
    from tests.unit.research.test_spec import _RIDGE, _book

    plain = _book(tmp_path, _RIDGE)
    line = _RIDGE.replace("min_obs: 10000", 'min_obs: 10000, refit_anchor: "2014-01-02"')
    anchored = _book(tmp_path, line)
    assert anchored.model.combiner.refit_anchor == "2014-01-02"
    assert "refit_anchor" not in json.loads(plain.canonical)["book"]["combiner"]
    assert anchored.spec_hash != plain.spec_hash
    for bad in ('"2014-02-30"', "2014-01-02"):  # not a date; an unquoted YAML date
        with pytest.raises(ValueError):
            _book(
                tmp_path, _RIDGE.replace("min_obs: 10000", f"min_obs: 10000, refit_anchor: {bad}")
            )


def test_spec_refit_anchor_needs_refits(tmp_path):
    from tests.unit.research.test_spec import _book

    with pytest.raises(ValueError, match="refit_anchor"):
        _book(
            tmp_path,
            'combiner: {kind: equal_weight, signs: {fam_one.x: 1}, refit_anchor: "2014-01-02"}',
        )


def test_runner_builds_the_anchored_ridge_and_names_the_feature():
    from src.intelligence.research import runner as runner_mod
    from src.intelligence.research.spec import CombinerSpec

    c = CombinerSpec(
        window_sessions=60, refit_sessions=10, penalty=0.5, min_obs=30, refit_anchor="2014-01-02"
    )
    book = SimpleNamespace(combiner=c)
    ridge = runner_mod._combiner(book, ["f.a"], BPS, 1)
    assert ridge.refit_anchor == ANCHOR
    assert runner_mod._combiner_features(book) == ("refit_anchor",)
    plain = SimpleNamespace(combiner=c.model_copy(update={"refit_anchor": None}))
    assert runner_mod._combiner(plain, ["f.a"], BPS, 1).refit_anchor is None
    assert runner_mod._combiner_features(plain) == ()


def test_book_timing_hands_the_combiner_its_session_dates():
    from src.intelligence.research.book import book_timing

    seen = {}

    class Spy:
        training_rows = 0

        def combine(self, stack, target, *, row_session_dates=None):
            seen["dates"] = row_session_dates
            raise RuntimeError("stop")

    rows = _rows(_sessions(5))
    with pytest.raises(RuntimeError, match="stop"):
        book_timing(
            np.zeros((10, 2, 1)),
            np.zeros((10, 2)),
            np.ones((10, 2)),
            np.ones(10, bool),
            combiner=Spy(),
            rule=None,
            bars_per_session=BPS,
            warmup_sessions=0,
            memory_sessions=1,
            row_session_dates=rows,
        )
    assert seen["dates"] is rows
