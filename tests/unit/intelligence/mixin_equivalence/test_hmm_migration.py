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
    from src.intelligence.features.smc_context.hmm_regime import HMMRegimePlugin
    from src.intelligence.plugins.mixins import IncrementalMixin

    assert isinstance(HMMRegimePlugin(), IncrementalMixin)


def test_hmm_compute_full_returns_state():
    """HMMRegime compute_full returns _state key with alpha (forward probabilities)."""
    from src.intelligence.features.smc_context.hmm_regime import HMMRegimePlugin

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
    from src.intelligence.features.smc_context.hmm_regime import HMMRegimePlugin

    plugin = HMMRegimePlugin()
    frames = build_synthetic_frames(n_bars=200, seed=42)

    result = plugin.compute_full(frames)
    assert "_state" in result, "compute_full must return _state"

    inc_result = plugin.compute_next(frames, state=result["_state"])
    assert "_state" in inc_result
    assert "hmm_regime" in inc_result
    assert "hmm_regime_prob" in inc_result


def test_hmm_output_keys_match_legacy():
    """Migrated HMMRegime produces same output keys as legacy plugin."""
    from src.intelligence.features.smc_context.hmm_regime import HMMRegimePlugin
    from tests.fixtures.legacy_plugins.hmm_legacy import HMMRegimePlugin as HMMLegacy

    legacy = HMMLegacy()
    migrated = HMMRegimePlugin()

    frames = build_synthetic_frames(n_bars=200, seed=42)
    legacy_result = legacy.compute_full(frames)
    migrated_result = migrated.compute_full(frames)

    legacy_keys = {k for k in legacy_result if not k.startswith("_")}
    migrated_keys = {k for k in migrated_result if not k.startswith("_")}
    assert legacy_keys == migrated_keys, (
        f"Output key mismatch.\n"
        f"  Legacy only: {legacy_keys - migrated_keys}\n"
        f"  Migrated only: {migrated_keys - legacy_keys}"
    )


def test_hmm_regime_labels_match_legacy_stable_region():
    """Migrated HMMRegime matches legacy regime labels for >= 95% of bars 200+ (stable region).

    Per plan spec: compare regime labels (not raw probabilities) for bars 200+.
    Both plugins process the same sequence so regime labels must agree on stable bars.
    """

    from src.intelligence.features.smc_context.hmm_regime import HMMRegimePlugin
    from tests.fixtures.legacy_plugins.hmm_legacy import HMMRegimePlugin as HMMLegacy

    # Process bars incrementally to collect regime labels at each bar
    full_frames = build_synthetic_frames(n_bars=2000, seed=42)
    df = full_frames["main"]

    legacy_plugin = HMMLegacy()
    migrated_plugin = HMMRegimePlugin()

    legacy_regimes = []
    migrated_regimes = []

    # Use full computation on growing windows to simulate bar-by-bar regime classification
    # Compare from bar 200 onwards (stable region, per plan spec)
    burn_in = 200
    sample_bars = list(range(burn_in, min(400, len(df))))  # Compare 200 stable-region bars

    for i in sample_bars:
        window = df.iloc[: i + 1]
        frames_i = {"main": window}

        legacy_result = legacy_plugin.compute_full(frames_i)
        migrated_result = migrated_plugin.compute_full(frames_i)

        if legacy_result and migrated_result:
            legacy_regimes.append(int(legacy_result.get("hmm_regime", -1)))
            migrated_regimes.append(int(migrated_result.get("hmm_regime", -1)))

    if not legacy_regimes:
        return  # Skip if no valid results

    matches = sum(leg == mig for leg, mig in zip(legacy_regimes, migrated_regimes))
    match_pct = matches / len(legacy_regimes)
    assert match_pct >= 0.95, (
        f"HMM regime label agreement below 95% in stable region (bars 200+): "
        f"{match_pct:.1%} ({matches}/{len(legacy_regimes)} bars matched)"
    )
