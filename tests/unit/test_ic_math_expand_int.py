"""Unit tests for expand_int (todo 009 Part D Item 3).

Int sibling of _expand -- scatters cluster IDs (int-typed, can't use NaN as a fill
value) back into the full n-feature-length position space services/ic_engine.py
uses for its non-degenerate-feature masking. Extracted from two identical inline
4-line scatter loops in ic_engine.py's per-symbol and cross-sectional passes.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.intelligence.statistics.ic_math import expand_int


def test_expand_int_scatters_into_masked_positions() -> None:
    mask = np.array([True, False, True, True, False])
    nd_arr = np.array([10, 20, 30])

    result = expand_int(nd_arr, mask, n=5)

    assert result == [10, None, 20, 30, None]


def test_expand_int_all_masked_out() -> None:
    mask = np.array([False, False, False])
    nd_arr = np.array([], dtype=int)

    result = expand_int(nd_arr, mask, n=3)

    assert result == [None, None, None]


def test_expand_int_all_non_degenerate() -> None:
    mask = np.array([True, True, True])
    nd_arr = np.array([1, 2, 3])

    result = expand_int(nd_arr, mask, n=3)

    assert result == [1, 2, 3]


def test_expand_int_matches_manual_scatter_loop() -> None:
    """Byte-identical to the inline loop it replaces, across a random mask."""
    rng = np.random.default_rng(42)
    n = 50
    mask = rng.random(n) > 0.4
    nd_arr = rng.integers(0, 200, size=int(mask.sum()))

    expected: list[int | None] = [None] * n
    nd_positions = np.where(mask)[0]
    for i, pos in enumerate(nd_positions):
        expected[pos] = int(nd_arr[i])

    assert expand_int(nd_arr, mask, n) == expected
