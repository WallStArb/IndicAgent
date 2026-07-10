"""Unit tests: determine_exit (direction-aware FRAME-02/03 state machine) and
compute_frame_pnl_r.

Review H3 (the single most important fix in Phase 142B Plan 02): determine_exit MUST be
direction-aware. A long-only implementation would close every direction='short' frame as an
instant false stop-out, silently corrupting ~half the corpus. The SHORT cases below are
MANDATORY -- this is exactly the test matrix the prior (long-only) plan lacked.
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.counterfactual_tracker import Bar, compute_frame_pnl_r, determine_exit

# ---------------------------------------------------------------------------
# determine_exit -- LONG
# ---------------------------------------------------------------------------


def test_long_stop_only():
    bars = [Bar(open=100, high=101, low=94, close=95)]
    result = determine_exit(
        "long", bars, stop_price=95, target_price=110, hold_max_bars=10, ic_ci_lower=None
    )
    assert result.status == "closed_stop"
    assert result.bars == 1
    assert result.exit_price == 95  # min(open=100, stop=95)


def test_long_target_only():
    bars = [Bar(open=100, high=111, low=99, close=105)]
    result = determine_exit(
        "long", bars, stop_price=95, target_price=110, hold_max_bars=10, ic_ci_lower=None
    )
    assert result.status == "closed_target"
    assert result.bars == 1
    assert result.exit_price == 110


def test_long_both_hit_same_bar_stop_wins():
    bars = [Bar(open=100, high=111, low=94, close=100)]
    result = determine_exit(
        "long", bars, stop_price=95, target_price=110, hold_max_bars=10, ic_ci_lower=None
    )
    assert result.status == "closed_stop"


def test_long_gap_through_stop_fills_at_worse_of_open_and_stop():
    # Bar opens BELOW the stop (gap down through it) -- fill at the worse (lower) price.
    bars = [Bar(open=90, high=92, low=85, close=88)]
    result = determine_exit(
        "long", bars, stop_price=95, target_price=110, hold_max_bars=10, ic_ci_lower=None
    )
    assert result.status == "closed_stop"
    assert result.exit_price == 90  # min(open=90, stop=95)


def test_long_max_hold_reached():
    bars = [
        Bar(open=100, high=102, low=99, close=101),
        Bar(open=101, high=103, low=100, close=102),
        Bar(open=102, high=104, low=101, close=103),
    ]
    result = determine_exit(
        "long", bars, stop_price=95, target_price=110, hold_max_bars=3, ic_ci_lower=None
    )
    assert result.status == "closed_max_hold"
    assert result.bars == 3
    assert result.exit_price == 103  # last bar close


def test_long_ic_decay_only_after_no_per_bar_exit_and_negative_ci_lower():
    bars = [Bar(open=100, high=102, low=99, close=101)]
    result = determine_exit(
        "long", bars, stop_price=95, target_price=110, hold_max_bars=10, ic_ci_lower=-0.05
    )
    assert result.status == "closed_ic_decay"
    assert result.exit_price == 101  # last observed close


def test_long_still_open_returns_none():
    bars = [Bar(open=100, high=102, low=99, close=101)]
    result = determine_exit(
        "long", bars, stop_price=95, target_price=110, hold_max_bars=10, ic_ci_lower=None
    )
    assert result is None


def test_empty_bars_returns_none():
    result = determine_exit(
        "long", [], stop_price=95, target_price=110, hold_max_bars=10, ic_ci_lower=-0.5
    )
    assert result is None


def test_ic_ci_lower_none_never_triggers_decay():
    bars = [Bar(open=100, high=102, low=99, close=101)]
    result = determine_exit(
        "long", bars, stop_price=95, target_price=110, hold_max_bars=10, ic_ci_lower=None
    )
    assert result is None


def test_ic_ci_lower_nonnegative_never_triggers_decay():
    bars = [Bar(open=100, high=102, low=99, close=101)]
    result = determine_exit(
        "long", bars, stop_price=95, target_price=110, hold_max_bars=10, ic_ci_lower=0.02
    )
    assert result is None


# ---------------------------------------------------------------------------
# determine_exit -- SHORT (review H3, MANDATORY -- the prior plan's missing case)
# ---------------------------------------------------------------------------


def test_short_stop_hit_stop_above_entry():
    # Short: entry=100, stop=105 (ABOVE entry), target=90 (BELOW entry).
    # bar.high >= stop_price closes closed_stop; the same bar's low being below entry
    # must NOT falsely close via any other path (priority ordering: stop checked first).
    bars = [Bar(open=101, high=106, low=80, close=104)]
    result = determine_exit(
        "short", bars, stop_price=105, target_price=90, hold_max_bars=10, ic_ci_lower=None
    )
    assert result.status == "closed_stop"
    assert result.bars == 1
    assert result.exit_price == 105  # max(open=101, stop=105)


def test_short_target_hit_target_below_entry():
    bars = [Bar(open=99, high=101, low=89, close=91)]
    result = determine_exit(
        "short", bars, stop_price=105, target_price=90, hold_max_bars=10, ic_ci_lower=None
    )
    assert result.status == "closed_target"
    assert result.bars == 1
    assert result.exit_price == 90


def test_short_both_hit_same_bar_stop_wins():
    bars = [Bar(open=101, high=106, low=85, close=100)]
    result = determine_exit(
        "short", bars, stop_price=105, target_price=90, hold_max_bars=10, ic_ci_lower=None
    )
    assert result.status == "closed_stop"


def test_short_gap_through_stop_fills_at_worse_of_open_and_stop():
    # Bar opens ABOVE the stop (gap up through it) -- fill at the worse (higher) price.
    bars = [Bar(open=110, high=112, low=108, close=109)]
    result = determine_exit(
        "short", bars, stop_price=105, target_price=90, hold_max_bars=10, ic_ci_lower=None
    )
    assert result.status == "closed_stop"
    assert result.exit_price == 110  # max(open=110, stop=105)


def test_short_max_hold_reached():
    bars = [
        Bar(open=100, high=101, low=98, close=99),
        Bar(open=99, high=100, low=97, close=98),
        Bar(open=98, high=99, low=96, close=97),
    ]
    result = determine_exit(
        "short", bars, stop_price=105, target_price=90, hold_max_bars=3, ic_ci_lower=None
    )
    assert result.status == "closed_max_hold"
    assert result.bars == 3
    assert result.exit_price == 97


def test_short_ic_decay_only_after_no_per_bar_exit_and_negative_ci_lower():
    bars = [Bar(open=100, high=101, low=98, close=99)]
    result = determine_exit(
        "short", bars, stop_price=105, target_price=90, hold_max_bars=10, ic_ci_lower=-0.1
    )
    assert result.status == "closed_ic_decay"
    assert result.exit_price == 99


def test_short_still_open_returns_none():
    bars = [Bar(open=100, high=101, low=98, close=99)]
    result = determine_exit(
        "short", bars, stop_price=105, target_price=90, hold_max_bars=10, ic_ci_lower=None
    )
    assert result is None


def test_determine_exit_unknown_direction_raises():
    import pytest

    with pytest.raises(ValueError):
        determine_exit("sideways", [Bar(1, 1, 1, 1)], 1, 1, 1, None)


# ---------------------------------------------------------------------------
# compute_frame_pnl_r -- direction-aware sign
# ---------------------------------------------------------------------------


def test_compute_frame_pnl_r_long_stop_is_negative_one_r():
    pnl = compute_frame_pnl_r("long", entry_price=100, stop_price=95, exit_price=95)
    assert pnl == -1.0


def test_compute_frame_pnl_r_long_target_is_positive_two_r():
    pnl = compute_frame_pnl_r("long", entry_price=100, stop_price=95, exit_price=110)
    assert pnl == 2.0


def test_compute_frame_pnl_r_short_stop_is_negative_one_r():
    pnl = compute_frame_pnl_r("short", entry_price=100, stop_price=105, exit_price=105)
    assert pnl == -1.0


def test_compute_frame_pnl_r_short_target_is_positive_two_r():
    pnl = compute_frame_pnl_r("short", entry_price=100, stop_price=105, exit_price=90)
    assert pnl == 2.0


def test_compute_frame_pnl_r_unknown_direction_raises():
    import pytest

    with pytest.raises(ValueError):
        compute_frame_pnl_r("sideways", 100, 95, 95)
