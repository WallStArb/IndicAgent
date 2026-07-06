"""Unit test: regime writer degenerate-model occupation-fraction gate (P2b).

Verifies _check_occupation_gate() -- the pure function regime_writer._compute_symbol_tf
calls after smoothed_states is finalized, before any DB write. Tests verify:
  1. A degenerate fit (one state absorbing >= 1 - min_state_occupation of bars) is
     flagged for skip.
  2. A healthy fit (every state's occupation fraction >= min_state_occupation) is
     NOT flagged -- write proceeds.
  3. Occupation fractions are computed from the smoothed label sequence actually
     written, not from some other summary statistic.
  4. Empty series, single-bar/short series, and non-converged fits are all flagged
     for skip deterministically -- no divide-by-zero, no IndexError -- and use the
     same True/diagnostics-dict marker as the degenerate-occupation path.

No DB, no GaussianHMM. Pure numpy.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.regime_writer import _check_occupation_gate

_MIN_OCCUPATION = 0.05


def test_degenerate_model_is_flagged_for_skip():
    """One state absorbing 96% of bars, with 5 states, must be flagged degenerate.

    n=1000 bars: state 0 gets 960 bars (96%), the other 4 states split the
    remaining 40 bars (1% each) -- each below the 5% floor.
    """
    smoothed_states = np.array([0] * 960 + [1] * 10 + [2] * 10 + [3] * 10 + [4] * 10)
    is_degenerate, info = _check_occupation_gate(
        smoothed_states, n_components=5, min_state_occupation=_MIN_OCCUPATION, converged=True
    )
    assert is_degenerate is True
    assert info["reason"] == "degenerate_occupation"
    assert info["min_fraction"] < _MIN_OCCUPATION


def test_healthy_model_is_not_flagged():
    """Balanced occupation across all 5 states must NOT be flagged -- write proceeds."""
    smoothed_states = np.array([0] * 200 + [1] * 200 + [2] * 200 + [3] * 200 + [4] * 200)
    is_degenerate, info = _check_occupation_gate(
        smoothed_states, n_components=5, min_state_occupation=_MIN_OCCUPATION, converged=True
    )
    assert is_degenerate is False
    assert info["reason"] is None


def test_occupation_fractions_computed_from_smoothed_states():
    """Occupation must reflect the actual smoothed label counts, not a proxy.

    A hand-verified case: 5 states, one state (state 2) exactly at the floor
    boundary (5%) must NOT be flagged (>= floor, not > floor); one bar below
    must be flagged.
    """
    # Exactly at floor: 50/1000 = 0.05 == min_state_occupation -> healthy.
    smoothed_states_at_floor = np.array([0] * 250 + [1] * 250 + [2] * 50 + [3] * 225 + [4] * 225)
    is_degenerate, info = _check_occupation_gate(
        smoothed_states_at_floor,
        n_components=5,
        min_state_occupation=_MIN_OCCUPATION,
        converged=True,
    )
    assert info["occupation"][2] == 0.05
    assert is_degenerate is False

    # One bar below floor: 49/1000 = 0.049 < 0.05 -> degenerate.
    smoothed_states_below_floor = np.array([0] * 250 + [1] * 250 + [2] * 49 + [3] * 226 + [4] * 225)
    is_degenerate2, info2 = _check_occupation_gate(
        smoothed_states_below_floor,
        n_components=5,
        min_state_occupation=_MIN_OCCUPATION,
        converged=True,
    )
    assert is_degenerate2 is True
    assert info2["min_state"] == 2


def test_empty_series_flagged_no_divide_by_zero():
    """An empty smoothed_states array must be flagged for skip without raising."""
    is_degenerate, info = _check_occupation_gate(
        np.array([]), n_components=5, min_state_occupation=_MIN_OCCUPATION, converged=True
    )
    assert is_degenerate is True
    assert info["reason"] == "empty_series"


def test_single_bar_series_flagged_no_index_error():
    """A single-bar (or otherwise too-short) series must be flagged for skip."""
    is_degenerate, info = _check_occupation_gate(
        np.array([0]), n_components=5, min_state_occupation=_MIN_OCCUPATION, converged=True
    )
    assert is_degenerate is True
    assert info["reason"] == "insufficient_obs"


def test_non_converged_fit_flagged_even_if_occupation_balanced():
    """A non-converged fit must be flagged for skip regardless of occupation balance."""
    smoothed_states = np.array([0] * 200 + [1] * 200 + [2] * 200 + [3] * 200 + [4] * 200)
    is_degenerate, info = _check_occupation_gate(
        smoothed_states, n_components=5, min_state_occupation=_MIN_OCCUPATION, converged=False
    )
    assert is_degenerate is True
    assert info["reason"] == "not_converged"


def test_skip_marker_shape_is_uniform_across_all_skip_reasons():
    """All skip paths (empty, short, non-converged, degenerate) return the same
    (bool, dict) shape with a 'reason' key -- the caller handles all uniformly."""
    cases = [
        (np.array([]), 5, True),
        (np.array([0]), 5, True),
        (np.array([0] * 1000), 5, False),
        (np.array([0] * 200 + [1] * 800), 2, True),
    ]
    for smoothed_states, n_components, converged in cases:
        is_degenerate, info = _check_occupation_gate(
            smoothed_states,
            n_components=n_components,
            min_state_occupation=_MIN_OCCUPATION,
            converged=converged,
        )
        assert isinstance(is_degenerate, bool)
        assert isinstance(info, dict)
        assert "reason" in info
