"""Unit tests: pure-logic helpers in ops_interaction_primitives_pilot.py.

No DB, no Kafka -- these test the stride/lookahead-mapping logic only. The script's
DB-facing functions (_load_interaction_features, _load_pooled_cells,
_fetch_cell_arrays, main) are integration-tested manually per the plan's Task 3
Step 3 dry-run, not unit-tested here, matching this codebase's existing convention
of keeping DB-free unit tests DB-free (see ic_math.py's own module docstring).
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_project_root / "scripts" / "ops" / "alpha"))

from ops_interaction_primitives_pilot import (
    _LOOKAHEAD_TO_SCALE_CACHE,
    _lookahead_to_scale,
    _scale_stride,
)


def test_scale_stride_uses_floor_when_lookahead_below_min():
    assert _scale_stride(lookahead_bars=1, subsample_min_stride=5) == 5


def test_scale_stride_uses_lookahead_when_above_min():
    assert _scale_stride(lookahead_bars=60, subsample_min_stride=5) == 60


def test_lookahead_to_scale_raises_before_init():
    _LOOKAHEAD_TO_SCALE_CACHE.clear()
    try:
        _lookahead_to_scale(999)
        raise AssertionError("expected KeyError for unmapped lookahead_bars")
    except KeyError:
        pass


def test_lookahead_to_scale_resolves_after_populated():
    _LOOKAHEAD_TO_SCALE_CACHE.clear()
    _LOOKAHEAD_TO_SCALE_CACHE[1] = "fast"
    _LOOKAHEAD_TO_SCALE_CACHE[60] = "extended"
    assert _lookahead_to_scale(1) == "fast"
    assert _lookahead_to_scale(60) == "extended"
    _LOOKAHEAD_TO_SCALE_CACHE.clear()
