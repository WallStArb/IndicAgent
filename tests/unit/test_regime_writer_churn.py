"""Unit test: regime writer hmm_churn rolling-instability feature (P2c).

Verifies _compute_hmm_churn() -- the pure function regime_writer._compute_symbol_tf
calls to build the per-bar hmm_churn value appended to update_rows. Tests verify:
  1. A hand-computed label-change sequence matches _compute_hmm_churn's output
     exactly at every bar.
  2. The first (churn_window - 1) bars use the available prefix as the
     denominator (partial window), not NaN.
  3. A perfectly stable regime run yields 0.0 churn everywhere; a strictly
     alternating sequence approaches the maximum churn value once the window is
     fully populated with genuine alternation.
  4. The smallest sequence that clears the occupation gate (length ==
     n_components, one bar per state) produces a well-defined churn array with
     no NaN and no IndexError.

No DB, no GaussianHMM. Pure numpy.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.regime_writer import _compute_hmm_churn


def test_hand_computed_churn_array_matches_exactly():
    """Hand-computed expected array for a known label sequence, churn_window=3.

    labels:  a a b b a a a b
    changes: 0 0 1 0 1 0 0 1   (index 0 has no predecessor -> defined as 0)

    churn[i] = mean(changes[max(0, i-2):i+1])
    i=0: [0]          -> 0/1     = 0.0
    i=1: [0,0]        -> 0/2     = 0.0
    i=2: [0,0,1]      -> 1/3     = 0.3333...
    i=3: [0,1,0]      -> 1/3     = 0.3333...
    i=4: [1,0,1]      -> 2/3     = 0.6667...
    i=5: [0,1,0]      -> 1/3     = 0.3333...
    i=6: [1,0,0]      -> 1/3     = 0.3333...
    i=7: [0,0,1]      -> 1/3     = 0.3333...
    """
    labels = ["a", "a", "b", "b", "a", "a", "a", "b"]
    expected = np.array(
        [0.0, 0.0, 1 / 3, 1 / 3, 2 / 3, 1 / 3, 1 / 3, 1 / 3],
    )
    churn = _compute_hmm_churn(labels, churn_window=3)
    assert churn.shape == (8,)
    np.testing.assert_allclose(churn, expected, atol=1e-9)


def test_partial_window_prefix_uses_bars_available_denominator():
    """First churn_window-1 bars must divide by bars-available, not churn_window.

    churn_window=4, so bars 0/1/2 use denom 1/2/3 respectively (not 4), and
    bar 3 onward uses the full denom=4.
    """
    labels = ["x", "y", "y", "x", "x", "y"]
    # changes: 0 1 0 1 0 1
    churn = _compute_hmm_churn(labels, churn_window=4)
    # i=0: [0] -> 0/1 = 0.0
    assert churn[0] == 0.0
    # i=1: [0,1] -> 1/2 = 0.5
    assert churn[1] == 0.5
    # i=2: [0,1,0] -> 1/3
    assert abs(churn[2] - 1 / 3) < 1e-9
    # i=3: [0,1,0,1] -> full window, denom=4 -> 2/4 = 0.5
    assert churn[3] == 0.5


def test_stable_regime_yields_zero_churn_everywhere():
    """A perfectly stable regime run must yield hmm_churn == 0.0 for every bar."""
    labels = ["ranging"] * 20
    churn = _compute_hmm_churn(labels, churn_window=5)
    assert np.all(churn == 0.0)


def test_alternating_sequence_reaches_maximum_churn_once_window_full():
    """A strictly alternating sequence must reach churn == 1.0 once the rolling
    window no longer includes the very first (no-predecessor) bar."""
    labels = ["a", "b"] * 10  # 20 bars, strictly alternating
    churn_window = 4
    churn = _compute_hmm_churn(labels, churn_window=churn_window)
    # Once i >= churn_window (window excludes index 0's artificial zero-change),
    # every bar in the window is a genuine alternation -> churn == 1.0.
    assert np.all(churn[churn_window:] == 1.0)


def test_smallest_valid_sequence_no_nan_no_index_error():
    """Smallest sequence clearing the occupation gate: length == n_components,
    one bar per state. Must produce a well-defined churn array."""
    n_components = 5
    labels = list(range(n_components))  # one bar per state, all distinct
    churn = _compute_hmm_churn(labels, churn_window=10)  # window > sequence length
    assert churn.shape == (n_components,)
    assert not np.any(np.isnan(churn))
    assert np.all(np.isfinite(churn))


def test_empty_sequence_returns_empty_array_no_error():
    """Empty label sequence must return an empty array without raising."""
    churn = _compute_hmm_churn([], churn_window=10)
    assert churn.shape == (0,)
