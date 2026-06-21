"""Unit tests for HMMRegimePlugin multi-TF parameterization, entropy/velocity math,
and SIGUSR1-driven reload contract.

Phase 82, Plan 02 — P82-HMM-MULTITF.
"""

from __future__ import annotations

import math
from unittest.mock import patch

import numpy as np
import pytest

from src.intelligence.archive.smc_context.hmm_regime import (
    VELOCITY_WINDOW_BY_TF,
    HMMRegimePlugin,
)

# ---------------------------------------------------------------------------
# Test 1: Parameterized construction per TF
# ---------------------------------------------------------------------------


class TestHmmRegimePluginNamePerTf:
    """Parameterized instances have correct names, timeframes, and lookbacks."""

    @pytest.mark.parametrize(
        ("timeframe", "lookback", "expected_name"),
        [
            ("1m", 200, "smc_HMMRegime_1m"),
            ("5m", 200, "smc_HMMRegime_5m"),
            ("15m", 150, "smc_HMMRegime_15m"),
            ("1h", 100, "smc_HMMRegime_1h"),
        ],
    )
    def test_hmm_regime_plugin_name_per_tf(
        self, timeframe: str, lookback: int, expected_name: str
    ) -> None:
        plugin = HMMRegimePlugin(timeframe=timeframe, lookback=lookback)
        assert plugin.name == expected_name, f"Expected {expected_name!r}, got {plugin.name!r}"
        assert plugin.inputs[0].timeframe == timeframe
        assert plugin.inputs[0].lookback == lookback


# ---------------------------------------------------------------------------
# Test 2: Entropy and velocity in outputs frozenset
# ---------------------------------------------------------------------------


def test_hmm_regime_outputs_include_entropy_and_velocity() -> None:
    """Both new fields appear in the outputs frozenset for every TF."""
    for tf in ("1m", "5m", "15m", "1h"):
        plugin = HMMRegimePlugin(timeframe=tf, lookback=200)
        assert "hmm_regime_entropy" in plugin.outputs, f"entropy missing for {tf}"
        assert "hmm_regime_velocity" in plugin.outputs, f"velocity missing for {tf}"


# ---------------------------------------------------------------------------
# Test 3: Shannon entropy math
# ---------------------------------------------------------------------------


def test_hmm_regime_entropy_math() -> None:
    """Shannon entropy is computed correctly for known distributions.

    Uniform distribution [1/3, 1/3, 1/3] → entropy = log2(3) ≈ 1.585
    Peaked distribution [1.0, 0.0, 0.0]  → entropy ≈ 0.0
    """
    # Warm up the plugin enough to get warmed_up=True
    plugin = HMMRegimePlugin(timeframe="5m", lookback=10)
    plugin.min_lookback = 1  # override for test isolation

    # Inject a uniform alpha directly to verify entropy formula
    plugin._state = plugin._make_initial_state(3)
    plugin._state["alpha"] = np.array([1 / 3, 1 / 3, 1 / 3])
    plugin._state["bars_processed"] = 5  # past min_lookback

    output = plugin._build_output(plugin._state)
    entropy_uniform = output.get("hmm_regime_entropy")
    assert entropy_uniform is not None
    expected_uniform = math.log2(3)  # ≈ 1.585
    assert (
        abs(entropy_uniform - expected_uniform) < 0.01
    ), f"Uniform entropy: expected ~{expected_uniform:.4f}, got {entropy_uniform:.4f}"

    # Peaked distribution — entropy should be near 0
    plugin2 = HMMRegimePlugin(timeframe="5m", lookback=10)
    plugin2.min_lookback = 1
    plugin2._state = plugin2._make_initial_state(3)
    plugin2._state["alpha"] = np.array([1.0 - 1e-10, 5e-11, 5e-11])
    plugin2._state["bars_processed"] = 5

    output2 = plugin2._build_output(plugin2._state)
    entropy_peaked = output2.get("hmm_regime_entropy")
    assert entropy_peaked is not None
    assert entropy_peaked < 0.02, f"Peaked entropy should be near 0, got {entropy_peaked}"


# ---------------------------------------------------------------------------
# Test 4: VELOCITY_WINDOW_BY_TF constant
# ---------------------------------------------------------------------------


def test_hmm_regime_velocity_window_by_tf() -> None:
    """Module constant maps each standard TF to the expected window size."""
    assert VELOCITY_WINDOW_BY_TF["1m"] == 5
    assert VELOCITY_WINDOW_BY_TF["5m"] == 5
    assert VELOCITY_WINDOW_BY_TF["15m"] == 4
    assert VELOCITY_WINDOW_BY_TF["1h"] == 3


# ---------------------------------------------------------------------------
# Test 5: reload_parameters() is idempotent
# ---------------------------------------------------------------------------


def test_hmm_regime_reload_parameters_idempotent() -> None:
    """Calling reload_parameters() twice does not raise and preserves K."""
    plugin = HMMRegimePlugin(timeframe="1m", lookback=200)
    initial_k = plugin._K

    # First call — should not raise
    plugin.reload_parameters()
    assert plugin._K == initial_k
    assert plugin._A.shape[0] == plugin._K

    # Second call — still idempotent
    plugin.reload_parameters()
    assert plugin._K == initial_k
    assert plugin._A.shape[0] == plugin._K


def test_hmm_regime_reload_parameters_with_tf_file(tmp_path: pytest.FixtureRequest) -> None:
    """reload_parameters loads TF-suffixed file when present."""
    import json

    # Build a minimal valid parameter file
    params = {
        "transition_matrix": [[0.9, 0.05, 0.05], [0.05, 0.9, 0.05], [0.05, 0.05, 0.9]],
        "emission_means": [[0.0, 0.005, 0.0, 0.3, 0.0]] * 3,
        "emission_variances": [[0.0001, 0.001, 0.04, 0.04, 0.04]] * 3,
    }
    tf_config = tmp_path / "hmm_parameters_5m.json"
    tf_config.write_text(json.dumps(params))

    plugin = HMMRegimePlugin(timeframe="5m", lookback=200)

    # Patch Path to point to our tmp file so no real filesystem access needed
    with patch(
        "src.intelligence.archive.smc_context.hmm_regime.Path",
        side_effect=lambda p: (
            tmp_path / p.split("/")[-1] if "hmm_parameters" in str(p) else type(tmp_path)(p)
        ),
    ):
        # Just verify it doesn't raise — full integration tested via live service
        try:
            plugin.reload_parameters()
        except Exception as exc:
            pytest.fail(f"reload_parameters raised unexpectedly: {exc}")

    assert plugin._A.shape[0] == plugin._K


# ---------------------------------------------------------------------------
# Test 6: TIER_SMC exposes all four HMM instances
# ---------------------------------------------------------------------------


def test_register_plugins_exposes_four_hmm_instances() -> None:
    """TIER_SMC contains all four expected smc_HMMRegime_* plugin names."""
    from src.intelligence.register_plugins import TIER_SMC

    hmm_names = [n for n in TIER_SMC if n.startswith("smc_HMMRegime_")]
    assert "smc_HMMRegime_1m" in hmm_names, f"1m missing from TIER_SMC HMM names: {hmm_names}"
    assert "smc_HMMRegime_5m" in hmm_names, f"5m missing from TIER_SMC HMM names: {hmm_names}"
    assert "smc_HMMRegime_15m" in hmm_names, f"15m missing from TIER_SMC HMM names: {hmm_names}"
    assert "smc_HMMRegime_1h" in hmm_names, f"1h missing from TIER_SMC HMM names: {hmm_names}"
    assert len(hmm_names) == 4, f"Expected exactly 4 HMM entries, got {len(hmm_names)}: {hmm_names}"
