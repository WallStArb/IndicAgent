"""Unit tests: pure-logic helpers in ops_interaction_primitives_pilot.py.

No DB, no Kafka -- these test the stride/lookahead-mapping logic and, as of the
Task 3 v2 fetch-layer rewrite, `_slice_cell()`'s pure in-memory slicing. The
script's DB-facing functions (_load_interaction_features, _load_pooled_cells,
_fetch_tf_dataset, main) are integration-tested manually per the plan's Task 3
Step 3 dry-run, not unit-tested here, matching this codebase's existing convention
of keeping DB-free unit tests DB-free (see ic_math.py's own module docstring).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_project_root / "scripts" / "ops" / "alpha"))

from ops_interaction_primitives_pilot import (
    _LOOKAHEAD_TO_SCALE_CACHE,
    _lookahead_to_scale,
    _scale_stride,
    _slice_cell,
)


def _dataset(symbol_cols: dict[str, dict[str, list]]) -> dict[str, dict[str, np.ndarray]]:
    """Build a `_fetch_tf_dataset()`-shaped in-memory dataset from plain Python
    lists, for pure `_slice_cell()` tests -- mirrors that function's array-building
    tail (regime_label as an object array; `complete_*` as bool; everything else as
    float64 with None -> NaN) without touching a DB."""
    dataset: dict[str, dict[str, np.ndarray]] = {}
    for sym, cols in symbol_cols.items():
        arrays: dict[str, np.ndarray] = {
            "regime_label": np.asarray(cols["regime_label"], dtype=object)
        }
        for key, values in cols.items():
            if key == "regime_label":
                continue
            if key.startswith("complete_"):
                arrays[key] = np.asarray(values, dtype=bool)
            else:
                arrays[key] = np.array(
                    [np.nan if v is None else v for v in values], dtype=np.float64
                )
        dataset[sym] = arrays
    return dataset


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


def test_slice_cell_filters_by_regime_label():
    _LOOKAHEAD_TO_SCALE_CACHE.clear()
    _LOOKAHEAD_TO_SCALE_CACHE[1] = "fast"
    dataset = _dataset(
        {
            "AAA": {
                "regime_label": ["bull", "bear", "bull"],
                "feat": [1.0, 2.0, 3.0],
                "p1": [10.0, 20.0, 30.0],
                "p2": [100.0, 200.0, 300.0],
                "return_fast": [0.1, 0.2, 0.3],
                "complete_fast": [True, True, True],
            }
        }
    )
    try:
        x, controls, y, n = _slice_cell(
            dataset,
            "feat",
            "p1",
            "p2",
            regime_label="bull",
            lookahead_bars=1,
            subsample_min_stride=1,
        )
        assert n == 2
        assert list(x) == [1.0, 3.0]
        assert list(controls[:, 0]) == [10.0, 30.0]
        assert list(controls[:, 1]) == [100.0, 300.0]
        assert list(y) == [0.1, 0.3]
    finally:
        _LOOKAHEAD_TO_SCALE_CACHE.clear()


def test_slice_cell_null_masking_is_independent_per_feature():
    """Two "features" (featA, featB) with non-overlapping NaN patterns share one
    dataset -- slicing one must not be contaminated by the other's NaN positions."""
    _LOOKAHEAD_TO_SCALE_CACHE.clear()
    _LOOKAHEAD_TO_SCALE_CACHE[1] = "fast"
    dataset = _dataset(
        {
            "AAA": {
                "regime_label": ["bull", "bull", "bull", "bull"],
                "featA": [1.0, None, 3.0, 4.0],
                "featB": [10.0, 20.0, None, 40.0],
                "p1": [100.0, 101.0, 102.0, 103.0],
                "p2": [200.0, 201.0, 202.0, 203.0],
                "return_fast": [0.01, 0.02, 0.03, 0.04],
                "complete_fast": [True, True, True, True],
            }
        }
    )
    try:
        x_a, _controls_a, _y_a, n_a = _slice_cell(
            dataset, "featA", "p1", "p2", "bull", lookahead_bars=1, subsample_min_stride=1
        )
        x_b, _controls_b, _y_b, n_b = _slice_cell(
            dataset, "featB", "p1", "p2", "bull", lookahead_bars=1, subsample_min_stride=1
        )
        # featA excludes row 1 (its own NaN); featB has no NaN at row 1 so it must
        # still be present there -- proves featB's mask wasn't polluted by featA's.
        assert n_a == 3
        assert list(x_a) == [1.0, 3.0, 4.0]
        # featB excludes row 2 (its own NaN); featA has no NaN at row 2 so it must
        # still be present there -- proves featA's mask wasn't polluted by featB's.
        assert n_b == 3
        assert list(x_b) == [10.0, 20.0, 40.0]
    finally:
        _LOOKAHEAD_TO_SCALE_CACHE.clear()


def test_slice_cell_excludes_incomplete_rows():
    _LOOKAHEAD_TO_SCALE_CACHE.clear()
    _LOOKAHEAD_TO_SCALE_CACHE[1] = "fast"
    dataset = _dataset(
        {
            "AAA": {
                "regime_label": ["bull", "bull", "bull"],
                "feat": [1.0, 2.0, 3.0],
                "p1": [10.0, 20.0, 30.0],
                "p2": [100.0, 200.0, 300.0],
                "return_fast": [0.1, 0.2, 0.3],
                "complete_fast": [True, False, True],
            }
        }
    )
    try:
        x, _controls, _y, n = _slice_cell(
            dataset, "feat", "p1", "p2", "bull", lookahead_bars=1, subsample_min_stride=1
        )
        assert n == 2
        assert list(x) == [1.0, 3.0]
    finally:
        _LOOKAHEAD_TO_SCALE_CACHE.clear()


def test_slice_cell_stride_applies_to_post_filter_index_not_raw_rows():
    """Stride must apply to the ordered, already-filtered row-position sequence
    (matching the OLD design, which received an already-SQL-filtered row list per
    symbol) -- not to the raw unfiltered row sequence, which would select different
    (wrong) rows whenever any row fails the regime/NULL/completeness filter."""
    _LOOKAHEAD_TO_SCALE_CACHE.clear()
    _LOOKAHEAD_TO_SCALE_CACHE[1] = "fast"
    n_rows = 10
    regimes = ["bull", "bear", "bull", "bull", "bear", "bull", "bull", "bull", "bear", "bull"]
    dataset = _dataset(
        {
            "AAA": {
                "regime_label": regimes,
                "feat": [float(i) for i in range(n_rows)],
                "p1": [float(i) * 10 for i in range(n_rows)],
                "p2": [float(i) * 100 for i in range(n_rows)],
                "return_fast": [float(i) / 10 for i in range(n_rows)],
                "complete_fast": [True] * n_rows,
            }
        }
    )
    try:
        # Reference (old-design) computation: filter first, in order, then stride.
        filtered_idx = [i for i, r in enumerate(regimes) if r == "bull"]
        stride = 3
        expected_idx = filtered_idx[::stride]
        assert expected_idx == [0, 5, 9]  # sanity-check the hand-derived expectation

        x, _controls, _y, n = _slice_cell(
            dataset,
            "feat",
            "p1",
            "p2",
            regime_label="bull",
            lookahead_bars=1,
            subsample_min_stride=stride,
        )
        assert n == len(expected_idx)
        assert list(x) == [float(i) for i in expected_idx]
    finally:
        _LOOKAHEAD_TO_SCALE_CACHE.clear()


def test_slice_cell_pools_across_symbols():
    _LOOKAHEAD_TO_SCALE_CACHE.clear()
    _LOOKAHEAD_TO_SCALE_CACHE[1] = "fast"
    dataset = _dataset(
        {
            "AAA": {
                "regime_label": ["bull", "bull"],
                "feat": [1.0, 2.0],
                "p1": [10.0, 20.0],
                "p2": [100.0, 200.0],
                "return_fast": [0.1, 0.2],
                "complete_fast": [True, True],
            },
            "BBB": {
                "regime_label": ["bull"],
                "feat": [3.0],
                "p1": [30.0],
                "p2": [300.0],
                "return_fast": [0.3],
                "complete_fast": [True],
            },
        }
    )
    try:
        x, controls, y, n = _slice_cell(
            dataset, "feat", "p1", "p2", "bull", lookahead_bars=1, subsample_min_stride=1
        )
        assert n == 3
        assert list(x) == [1.0, 2.0, 3.0]
        assert list(controls[:, 0]) == [10.0, 20.0, 30.0]
        assert list(y) == [0.1, 0.2, 0.3]
    finally:
        _LOOKAHEAD_TO_SCALE_CACHE.clear()


def test_slice_cell_returns_empty_sentinel_when_no_rows_match():
    _LOOKAHEAD_TO_SCALE_CACHE.clear()
    _LOOKAHEAD_TO_SCALE_CACHE[1] = "fast"
    dataset = _dataset(
        {
            "AAA": {
                "regime_label": ["bear", "bear"],
                "feat": [1.0, 2.0],
                "p1": [10.0, 20.0],
                "p2": [100.0, 200.0],
                "return_fast": [0.1, 0.2],
                "complete_fast": [True, True],
            }
        }
    )
    try:
        x, controls, y, n = _slice_cell(
            dataset, "feat", "p1", "p2", "bull", lookahead_bars=1, subsample_min_stride=1
        )
        assert n == 0
        assert x.size == 0
        assert controls.size == 0
        assert y.size == 0
    finally:
        _LOOKAHEAD_TO_SCALE_CACHE.clear()
