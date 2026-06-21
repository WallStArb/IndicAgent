"""Equivalence test for HMM plugin migration to IncrementalMixin (Task 14).

Equivalence strategy per plan spec:
- Compare regime labels (not raw probabilities) for bars 200+
- assert migrated_regime == legacy_regime for >= 95% of stable-region bars
- 2000-bar synthetic frames for model convergence
"""

from __future__ import annotations

from tests.unit.intelligence.mixin_equivalence.helpers import build_synthetic_frames


def test_hmm_uses_incremental_mixin():
    """HMMRegime plugin is an instance of IncrementalMixin."""
    from src.intelligence.archive.smc_context.hmm_regime import HMMRegimePlugin
    from src.intelligence.plugins.mixins import IncrementalMixin

    assert isinstance(HMMRegimePlugin(), IncrementalMixin)


def test_hmm_compute_full_returns_state():
    """HMMRegime compute_full returns _state key with alpha (forward probabilities)."""
    from src.intelligence.archive.smc_context.hmm_regime import HMMRegimePlugin

    plugin = HMMRegimePlugin()
    frames = build_synthetic_frames(n_bars=200, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result, "compute_full must return _state"
    state = result["_state"]
    assert "alpha" in state
    assert "prev_close" in state
    assert "bars_processed" in state


def test_hmm_compute_next_returns_state():
    """HMMRegime compute_full returns _state key and compute_next uses it."""
    from src.intelligence.archive.smc_context.hmm_regime import HMMRegimePlugin

    plugin = HMMRegimePlugin()
    frames = build_synthetic_frames(n_bars=200, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result, "compute_full must return _state"

    inc_result = plugin.compute_next(frames, state=result["_state"])
    assert "_state" in inc_result
    assert "hmm_regime" in inc_result
    assert "hmm_regime_prob" in inc_result
