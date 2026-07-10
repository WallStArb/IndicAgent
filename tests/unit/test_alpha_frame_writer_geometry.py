"""Unit tests: AlphaFrameWriter.compute_frame_geometry — pure-fn geometry math.

No DB, no Kafka. Direction-correct ATR-only stop/target geometry (long and short).
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.alpha_frame_writer import FrameConfig, compute_frame_geometry


def test_long_geometry():
    stop_price, target_price, r_multiple = compute_frame_geometry(
        "long", entry_price=100.0, atr=2.0, stop_atr_mult=1.5, target_r_multiple=2.0
    )
    assert stop_price == 97.0
    assert target_price == 106.0
    assert r_multiple == 2.0


def test_short_geometry():
    stop_price, target_price, r_multiple = compute_frame_geometry(
        "short", entry_price=100.0, atr=2.0, stop_atr_mult=1.5, target_r_multiple=2.0
    )
    assert stop_price == 103.0
    assert target_price == 94.0
    assert r_multiple == 2.0


def test_long_stop_below_entry_target_above():
    stop_price, target_price, _ = compute_frame_geometry(
        "long", entry_price=50.0, atr=1.0, stop_atr_mult=1.0, target_r_multiple=3.0
    )
    assert stop_price < 50.0
    assert target_price > 50.0


def test_short_stop_above_entry_target_below():
    stop_price, target_price, _ = compute_frame_geometry(
        "short", entry_price=50.0, atr=1.0, stop_atr_mult=1.0, target_r_multiple=3.0
    )
    assert stop_price > 50.0
    assert target_price < 50.0


def test_r_multiple_matches_target_r_multiple_regardless_of_direction():
    _, _, r_long = compute_frame_geometry("long", 100.0, 2.5, 1.2, 1.8)
    _, _, r_short = compute_frame_geometry("short", 100.0, 2.5, 1.2, 1.8)
    assert abs(r_long - 1.8) < 1e-9
    assert abs(r_short - 1.8) < 1e-9


def test_unknown_direction_raises():
    try:
        compute_frame_geometry("sideways", 100.0, 2.0, 1.5, 2.0)
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_zero_atr_raises_value_error_not_zero_division_error():
    """Code-review CR-01: a zero causal ATR (stale/forward-filled bars) must raise a catchable
    ValueError, not an uncaught ZeroDivisionError that would abort the caller's entire scan."""
    try:
        compute_frame_geometry(
            "long", entry_price=100.0, atr=0.0, stop_atr_mult=1.5, target_r_multiple=2.0
        )
        raised = None
    except ValueError as error:
        raised = error
    except ZeroDivisionError:
        raised = None
    assert raised is not None, "expected ValueError, got no exception or ZeroDivisionError"


def test_zero_stop_atr_mult_rejected_eagerly_by_frame_config_not_per_call():
    """Code-review CR-01 + simplify altitude follow-up: stop_atr_mult is a single global APR
    value shared by every frame in a run, so it is validated once, eagerly, in
    FrameConfig.from_apr — not rediscovered by compute_frame_geometry on every call. A zero
    stop_atr_mult never reaches compute_frame_geometry in production because FrameConfig.from_apr
    raises first."""
    try:
        FrameConfig.from_apr({"alpha.frame.stop_atr_mult": "0"})
        raised = False
    except ValueError:
        raised = True
    assert raised

    # compute_frame_geometry itself no longer guards stop_atr_mult (only atr) -- it degrades to
    # a zero-width frame (stop == entry == target) rather than raising, since that path is now
    # unreachable in production via the FrameConfig gate above.
    stop_price, target_price, _ = compute_frame_geometry(
        "short", entry_price=100.0, atr=2.0, stop_atr_mult=0.0, target_r_multiple=2.0
    )
    assert stop_price == 100.0
    assert target_price == 100.0


def test_negative_atr_raises_value_error():
    try:
        compute_frame_geometry(
            "long", entry_price=100.0, atr=-1.0, stop_atr_mult=1.5, target_r_multiple=2.0
        )
        raised = False
    except ValueError:
        raised = True
    assert raised
