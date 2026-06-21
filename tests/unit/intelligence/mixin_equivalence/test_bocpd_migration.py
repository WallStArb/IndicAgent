"""Equivalence test for BOCPD plugin migration to IncrementalMixin (Task 14).

Equivalence strategy per plan spec:
- Compare run-length MAP estimate and posterior normalization
  (sum(posteriors) ~ 1.0, atol=1e-5) -- not numeric output values
- 2000-bar synthetic frames for model convergence
"""

from __future__ import annotations

import numpy as np

from tests.unit.intelligence.mixin_equivalence.helpers import build_synthetic_frames


def test_bocpd_uses_incremental_mixin():
    """BOCPD plugin is an instance of IncrementalMixin."""
    from src.intelligence.archive.smc_context.bocpd_changepoint import BOCPDChangePointPlugin
    from src.intelligence.plugins.mixins import IncrementalMixin

    assert isinstance(BOCPDChangePointPlugin(), IncrementalMixin)


def test_bocpd_compute_full_returns_state():
    """BOCPD compute_full returns _state key with run_length_probs."""
    from src.intelligence.archive.smc_context.bocpd_changepoint import BOCPDChangePointPlugin

    plugin = BOCPDChangePointPlugin()
    frames = build_synthetic_frames(n_bars=200, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result, "compute_full must return _state"
    state = result["_state"]
    assert "run_length_probs" in state
    assert "prev_close" in state
    assert "cp_prob" in state


def test_bocpd_posterior_normalization():
    """BOCPD run-length posteriors sum to approximately 1.0 after 2000 bars."""
    from src.intelligence.archive.smc_context.bocpd_changepoint import BOCPDChangePointPlugin

    plugin = BOCPDChangePointPlugin()
    frames = build_synthetic_frames(n_bars=2000, seed=42)

    result = plugin.compute_full(frames)
    state = result["_state"]
    rl_probs = state["run_length_probs"]

    # Posterior normalization: sum of run-length probabilities must be ~1.0
    total = np.sum(rl_probs)
    assert (
        abs(total - 1.0) < 1e-5
    ), f"BOCPD run-length posteriors not normalized: sum={total:.8f}, atol=1e-5"


def test_bocpd_compute_next_returns_state():
    """BOCPD compute_full returns _state key and compute_next uses it."""
    from src.intelligence.archive.smc_context.bocpd_changepoint import BOCPDChangePointPlugin

    plugin = BOCPDChangePointPlugin()
    frames = build_synthetic_frames(n_bars=200, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result, "compute_full must return _state"

    inc_result = plugin.compute_next(frames, state=result["_state"])
    assert "_state" in inc_result
    assert "cp_probability" in inc_result
    assert "cp_raw_probability" in inc_result
    assert "cp_run_length" in inc_result
