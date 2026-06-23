"""Unit test: regime writer canonical label mapping.

Verifies that _build_label_map() assigns canonical text labels correctly
using known synthetic HMM state means. Tests verify:
  1. State with highest mean log-return gets "trending_up"
  2. State with lowest mean log-return gets "trending_down"
  3. Remaining states get "ranging"
  4. All output labels are canonical text strings, NOT integer strings like '0'/'1'/'2'
  5. Label map covers all K states

All tests use synthetic np.ndarray means -- no GaussianHMM instance required,
confirming _build_label_map() accepts plain np.ndarray as its first argument.

No DB, no Kafka. Pure numpy.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.regime_writer import (
    _LABEL_RANGING,
    _LABEL_TRENDING_DOWN,
    _LABEL_TRENDING_UP,
    _build_label_map,
)

# Canonical set -- the only allowed values
_CANONICAL_LABELS = {_LABEL_TRENDING_UP, _LABEL_TRENDING_DOWN, _LABEL_RANGING}


def _make_means_3state(ret_0: float, ret_1: float, ret_2: float) -> np.ndarray:
    """Build a (3, 2) means array with specified log-return dim values."""
    # means[:, 0] = log-return dimension (used for sorting)
    # means[:, 1] = realized_vol dimension (ignored by label mapping)
    return np.array(
        [
            [ret_0, 0.01],
            [ret_1, 0.02],
            [ret_2, 0.015],
        ]
    )


# ---------------------------------------------------------------------------
# Tests: known means -> correct label assignment
# ---------------------------------------------------------------------------


def test_label_map_assigns_trending_up_to_highest_mean():
    """State with highest mean log-return must get trending_up."""
    # State 0: -0.5, State 1: +0.5, State 2: 0.0
    # trending_up -> State 1 (highest)
    means = _make_means_3state(-0.5, 0.5, 0.0)
    label_map = _build_label_map(means)

    assert (
        label_map[1] == _LABEL_TRENDING_UP
    ), f"State 1 (mean=0.5) should be trending_up, got '{label_map[1]}'"


def test_label_map_assigns_trending_down_to_lowest_mean():
    """State with lowest mean log-return must get trending_down."""
    # State 0: -0.5 -> trending_down
    means = _make_means_3state(-0.5, 0.5, 0.0)
    label_map = _build_label_map(means)

    assert (
        label_map[0] == _LABEL_TRENDING_DOWN
    ), f"State 0 (mean=-0.5) should be trending_down, got '{label_map[0]}'"


def test_label_map_assigns_ranging_to_middle_mean():
    """State with middle mean log-return must get ranging."""
    # State 2: 0.0 -> ranging
    means = _make_means_3state(-0.5, 0.5, 0.0)
    label_map = _build_label_map(means)

    assert (
        label_map[2] == _LABEL_RANGING
    ), f"State 2 (mean=0.0) should be ranging, got '{label_map[2]}'"


def test_label_map_all_three_labels_present():
    """All three canonical labels must appear exactly once in the 3-state map."""
    means = _make_means_3state(-0.5, 0.5, 0.0)
    label_map = _build_label_map(means)

    label_values = set(label_map.values())
    assert (
        label_values == _CANONICAL_LABELS
    ), f"Expected labels {_CANONICAL_LABELS}, got {label_values}"


def test_label_map_covers_all_states():
    """label_map must have an entry for every state 0..K-1."""
    means = _make_means_3state(-0.5, 0.5, 0.0)
    label_map = _build_label_map(means)

    assert set(label_map.keys()) == {
        0,
        1,
        2,
    }, f"Expected keys {{0, 1, 2}}, got {set(label_map.keys())}"


def test_label_map_no_integer_string_labels():
    """No output label may be an integer string like '0', '1', or '2'.

    This is the key regression guard: old code that returned str(state_index)
    instead of canonical text would pass label_map.get(k) but write garbage
    regime labels to the DB, silently breaking all downstream IC regime-conditional
    analysis.
    """
    means = _make_means_3state(-0.5, 0.5, 0.0)
    label_map = _build_label_map(means)

    integer_string_labels = {str(i) for i in range(100)}
    for state, label in label_map.items():
        assert label not in integer_string_labels, (
            f"State {state} has integer-string label '{label}' -- "
            "should be one of {trending_up, trending_down, ranging}"
        )


def test_label_map_with_different_state_ordering():
    """Label assignment must be correct regardless of which state index has the highest mean."""
    # State 0: +0.8 (trending_up), State 1: +0.1 (ranging), State 2: -0.3 (trending_down)
    means = _make_means_3state(0.8, 0.1, -0.3)
    label_map = _build_label_map(means)

    assert label_map[0] == _LABEL_TRENDING_UP
    assert label_map[2] == _LABEL_TRENDING_DOWN
    assert label_map[1] == _LABEL_RANGING


def test_label_map_canonical_label_strings():
    """Canonical label constants must be exact expected strings."""
    assert _LABEL_TRENDING_UP == "trending_up"
    assert _LABEL_TRENDING_DOWN == "trending_down"
    assert _LABEL_RANGING == "ranging"


def test_label_map_accepts_numpy_array_not_hmm_model():
    """_build_label_map must accept np.ndarray shape (K, n_features) directly.

    This confirms the function signature is means: np.ndarray (not model: GaussianHMM).
    The unit test does NOT need a fitted HMM -- just a plain numpy array.
    """
    means = np.array(
        [
            [-0.5, 0.01],
            [0.5, 0.02],
            [0.0, 0.015],
        ]
    )
    # Must not raise AttributeError or TypeError
    label_map = _build_label_map(means)
    assert len(label_map) == 3


def test_label_map_four_components_has_two_ranging():
    """With 4 components, exactly 2 states should get 'ranging'."""
    # State 0: -0.4, State 1: -0.1, State 2: +0.1, State 3: +0.4
    means_4 = np.array(
        [
            [-0.4, 0.01],
            [-0.1, 0.01],
            [+0.1, 0.01],
            [+0.4, 0.01],
        ]
    )
    label_map = _build_label_map(means_4)

    ranging_count = sum(1 for v in label_map.values() if v == _LABEL_RANGING)
    assert (
        ranging_count == 2
    ), f"Expected 2 ranging states for 4-component HMM, got {ranging_count}: {label_map}"
    assert sum(1 for v in label_map.values() if v == _LABEL_TRENDING_UP) == 1
    assert sum(1 for v in label_map.values() if v == _LABEL_TRENDING_DOWN) == 1
