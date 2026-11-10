"""Level seams (admission step 4): known splits on an unadjusted tape, judged by level."""

from __future__ import annotations

import math

import numpy as np
import pytest

from src.intelligence.bars.corporate_actions import SplitRatioRule
from src.intelligence.bars.level_seams import (
    RecordedFactor,
    SeamParams,
    classify_step,
    find_level_steps,
    incumbent_reading,
    junction_levels,
    simplest_split_ratio,
    tape_reading,
)

RULE = SplitRatioRule(max_numerator=50, max_denominator=4, rel_tol=0.002)
PARAMS = SeamParams(
    junction_cut=0.2,
    transient_tol=0.1,
    level_sessions=10,
    explain_sessions=5,
    halt_gap=5,
    max_halt_gap=60,
    thin_volume=1000.0,
    rel_tol=0.3,
    ratio_rule=RULE,
)


def _tape(before: float, after: float, n: int = 60, at: int = 30, seed: int = 0):
    """An unadjusted daily tape: a 1 percent random walk at `before`, then at `after` from `at`
    (the split's first new-scale session); share volume scales inversely with price."""
    rng = np.random.default_rng(seed)
    walk = np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    level = np.where(np.arange(n) < at, before, after)
    close = level * walk
    volume = 1e6 * before / level
    return np.arange(n, dtype=np.int64) + 1000, close, volume


@pytest.mark.parametrize(
    "case, before, after, factor",
    [
        ("NVDA 2024-06-07 10:1", 1210.0, 121.0, 10.0),
        ("AAPL 2020-08-31 4:1", 500.0, 125.0, 4.0),
        ("AAPL 2014-06-09 7:1", 645.0, 92.14, 7.0),
        ("a 1-for-10 reverse split", 1.2, 12.0, 0.1),
    ],
)
def test_a_known_split_steps_once_and_its_record_explains_it(case, before, after, factor):
    sessions, close, volume = _tape(before, after)
    steps, printed = find_level_steps(sessions, close, volume, PARAMS)
    assert printed == 0 and len(steps) == 1, case
    step = steps[0]
    assert step.session == 1030 and step.prev_session == 1029
    assert step.level_step == pytest.approx(-math.log(factor), abs=0.05)
    record = RecordedFactor(1030, factor, "massive", "E1")
    verdict = classify_step(step, [record], [], PARAMS)
    assert (verdict.seam_class, verdict.explained_by) == ("explained", ("E1",))
    # Unrecorded, it is the candidate missing split at its ratio, share volume agreeing.
    missing = classify_step(step, [], [], PARAMS)
    assert missing.seam_class == "unexplained"
    assert missing.implied_ratio == pytest.approx(factor)
    assert missing.volume_agrees is True
    # The vendor's own tape witnesses the recorded split.
    reading, level = tape_reading(sessions, close, 1030, factor, (0, 1 << 30), PARAMS)
    assert reading == "tape_step" and level == pytest.approx(-math.log(factor), abs=0.05)


def test_a_record_at_the_wrong_ratio_does_not_explain_and_is_named():
    sessions, close, volume = _tape(500.0, 125.0)
    (step,), _ = find_level_steps(sessions, close, volume, PARAMS)
    verdict = classify_step(step, [RecordedFactor(1030, 2.0, "massive", "E2")], [], PARAMS)
    assert verdict.seam_class == "unexplained"
    assert verdict.nearby_unexplaining == ("E2",)
    assert "does not explain" in verdict.reason


def test_a_split_recorded_by_two_sources_is_not_multiplied_twice():
    sessions, close, volume = _tape(500.0, 125.0)
    (step,), _ = find_level_steps(sessions, close, volume, PARAMS)
    both = [
        RecordedFactor(1030, 4.0, "corporate_action", "ours"),
        RecordedFactor(1031, 4.0, "massive", "theirs"),
    ]
    assert classify_step(step, both, [], PARAMS).seam_class == "explained"


def test_a_one_bar_print_is_no_seam():
    sessions, close, volume = _tape(50.0, 50.0)
    close = close.copy()
    close[30] *= 2.0
    steps, printed = find_level_steps(sessions, close, volume, PARAMS)
    assert (steps, printed) == ([], 2)


def test_a_short_excursion_is_never_a_finding():
    # The 592 rule: each side is a span bounded by the neighbouring junctions, so a three-session
    # excursion is two steps whose inner side holds three observations: thin, never a split.
    sessions, close, volume = _tape(50.0, 50.0)
    close = close.copy()
    close[30:33] *= 1.6
    steps, _ = find_level_steps(sessions, close, volume, PARAMS)
    assert [(s.session, s.n_after) for s in steps] == [(1030, 3), (1033, 10)]
    assert {classify_step(s, [], [], PARAMS).seam_class for s in steps} == {"thin_halted"}


def test_a_reused_ticker_is_identity_suspect_never_a_missing_split():
    # The old company's last session, months of silence, then a new company at another level.
    sessions, close, volume = _tape(40.0, 7.5)
    sessions = sessions.copy()
    sessions[30:] += 200
    (step,), _ = find_level_steps(sessions, close, volume, PARAMS)
    assert step.gap == 200
    verdict = classify_step(step, [], [], PARAMS)
    assert verdict.seam_class == "identity_suspect"
    # A recorded change of hands at the junction says the same with no gap at all.
    sessions, close, volume = _tape(40.0, 7.5)
    (step,), _ = find_level_steps(sessions, close, volume, PARAMS)
    verdict = classify_step(step, [], [1030], PARAMS)
    assert (verdict.seam_class, verdict.reason) == (
        "identity_suspect",
        "identity break at session 1030",
    )


def test_a_halt_and_a_thin_tape_are_not_findings():
    sessions, close, volume = _tape(40.0, 20.0)
    sessions = sessions.copy()
    sessions[30:] += 10
    (step,), _ = find_level_steps(sessions, close, volume, PARAMS)
    assert classify_step(step, [], [], PARAMS).seam_class == "thin_halted"
    sessions, close, volume = _tape(40.0, 20.0)
    (step,), _ = find_level_steps(sessions, close, volume / 1e4, PARAMS)
    assert classify_step(step, [], [], PARAMS).seam_class == "thin_halted"


def test_the_simplest_readable_ratio_wins_not_the_nearest():
    # ln 2 = 0.6931: 2 is the simplest ratio the step reads as, though 49/25 or 2.01 lie nearer.
    assert simplest_split_ratio(-0.70, RULE, 0.3) == (2.0, pytest.approx(-0.007, abs=1e-3))
    # The smaller term first, then the nearest: a 4:1 is 4, though the tolerance admits 3.
    assert simplest_split_ratio(-math.log(4), RULE, 0.3)[0] == 4.0
    assert simplest_split_ratio(math.log(10), RULE, 0.3)[0] == 0.1
    assert simplest_split_ratio(-0.01, RULE, 0.3) is None


def test_the_incumbent_separates_a_real_move_from_a_split():
    # Both vendors move: a real move. The adjusted incumbent flat while the tape halves: a split.
    assert incumbent_reading(-0.69, -0.66, RULE, 0.3, 0.1) == ("incumbent_moves", None)
    assert incumbent_reading(-0.69, 0.01, RULE, 0.3, 0.1) == ("incumbent_flat", 2.0)
    assert incumbent_reading(-0.69, -0.54, RULE, 0.3, 0.1) == ("incumbent_other", None)


def test_tape_reading_flat_conflict_and_absent():
    sessions, close, volume = _tape(50.0, 50.0)
    assert tape_reading(sessions, close, 1030, 2.0, (0, 1 << 30), PARAMS)[0] == "tape_flat"
    sessions, close, volume = _tape(50.0, 30.0)
    assert tape_reading(sessions, close, 1030, 4.0, (0, 1 << 30), PARAMS)[0] == "tape_conflict"
    assert tape_reading(sessions, close, 5000, 2.0, (0, 1 << 30), PARAMS) == ("no_tape", None)
    # A neighbouring recorded split bounds the medians: a side left empty is no tape.
    assert tape_reading(sessions, close, 1030, 2.0, (1030, 1 << 30), PARAMS)[0] == "no_tape"


def test_junction_levels_and_input_validation():
    s = np.array([1, 2, 3, 4])
    v = np.array([0.0, 0.0, 1.0, 1.0])
    assert junction_levels(s, v, 3, 10) == (0.0, 1.0)
    assert junction_levels(s, v, 1, 10) is None
    with pytest.raises(ValueError, match="strictly increasing"):
        find_level_steps(np.array([1, 1]), np.array([1.0, 2.0]), np.array([1.0, 1.0]), PARAMS)
    with pytest.raises(ValueError, match="positive"):
        find_level_steps(np.array([1, 2]), np.array([1.0, 0.0]), np.array([1.0, 1.0]), PARAMS)


def test_a_dropped_transient_never_truncates_a_real_steps_side():
    # A spike that decays without a second junction (so no one-bar print) four sessions before a
    # 2:1 split: its level comes back, it is dropped, and the split is measured on full sides.
    sessions, close, volume = _tape(100.0, 50.0, n=80, at=40)
    close = close.copy()
    close[36] *= 1.25
    close[37] *= 1.12
    steps, _ = find_level_steps(sessions, close, volume, PARAMS)
    (split,) = [s for s in steps if s.session == 1040]
    assert split.n_before == 10 and split.n_after == 10
    assert classify_step(split, [], [], PARAMS).seam_class == "unexplained"
