"""Unit tests: AlphaFrameWriter.compute_frame_geometry — pure-fn geometry math.

No DB, no Kafka. Direction-correct ATR-only stop/target geometry (long and short).
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.alpha_frame_writer import compute_frame_geometry


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
