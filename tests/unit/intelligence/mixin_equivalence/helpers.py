"""Helpers for IncrementalMixin equivalence tests.

Provides build_synthetic_frames() for generating deterministic OHLCV data
and assert_output_equivalence() for comparing legacy vs migrated plugin output.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def build_synthetic_frames(n_bars: int = 500, seed: int = 42) -> dict[str, pd.DataFrame]:
    """Build deterministic synthetic OHLCV frames for plugin testing.

    Generates a realistic price series using a geometric random walk with
    controlled spread. Produces a single 'main' DataFrame suitable for
    passing to plugin compute_full() and compute_next() methods.

    Args:
        n_bars: Number of bars to generate. Use 500 for standard plugins,
                2000 for model-state plugins (BOCPD, HMM, GARCH, Kalman).
        seed:   Random seed for reproducibility. Default 42.

    Returns:
        Dict with key "main" -> pd.DataFrame with columns:
        open, high, low, close, volume.
    """
    rng = np.random.default_rng(seed)

    # Geometric random walk for close prices
    close = 5000.0 * np.cumprod(1 + rng.normal(0.0001, 0.005, n_bars))

    # Generate open, high, low from close with realistic spread
    spread = rng.uniform(0.001, 0.003, n_bars)
    open_ = close * (1 + rng.normal(0, 0.001, n_bars))
    high = np.maximum(close * (1 + spread), close)
    low = np.minimum(close * (1 - spread), close)

    # Ensure high/low envelope both open and close
    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))

    # Log-normal volume distribution
    volume = rng.lognormal(10, 0.5, n_bars).astype(float)

    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})
    return {"main": df}


def assert_output_equivalence(
    legacy_plugin: Any,
    migrated_plugin: Any,
    frames: dict[str, pd.DataFrame],
    tolerance: float = 0.001,
    burn_in_bars: int = 0,
) -> None:
    """Assert that legacy and migrated plugin produce equivalent outputs.

    Runs both plugins on the same frames and compares numeric outputs
    within the given relative tolerance. Non-numeric outputs (strings, bools)
    are compared for exact equality.

    Uses compute_full() for both plugins for the equivalence comparison.
    This validates that the migrated IncrementalMixin plugin produces the
    same results as the original implementation.

    Args:
        legacy_plugin:   The original (pre-migration) plugin instance.
        migrated_plugin: The migrated (IncrementalMixin) plugin instance.
        frames:          Frames dict from build_synthetic_frames().
        tolerance:       Relative tolerance for numeric comparisons (0.001 = 0.1%).
        burn_in_bars:    Number of initial bars to skip in comparison (for convergence).

    Raises:
        AssertionError: If any output key differs beyond tolerance.
    """
    legacy_result = legacy_plugin.compute_full(frames)
    migrated_result = migrated_plugin.compute_full(frames)

    # Both must return dicts
    assert isinstance(legacy_result, dict), f"Legacy plugin returned {type(legacy_result)}"
    assert isinstance(migrated_result, dict), f"Migrated plugin returned {type(migrated_result)}"

    # Get comparable keys (exclude _state and _tier_key from migrated)
    legacy_keys = {k for k in legacy_result if not k.startswith("_")}
    migrated_keys = {k for k in migrated_result if not k.startswith("_")}

    assert legacy_keys == migrated_keys, (
        f"Output key mismatch.\n"
        f"  Legacy only: {legacy_keys - migrated_keys}\n"
        f"  Migrated only: {migrated_keys - legacy_keys}"
    )

    for key in legacy_keys:
        l_val = legacy_result[key]
        m_val = migrated_result[key]

        if isinstance(l_val, float) and math.isnan(l_val):
            assert isinstance(m_val, float) and math.isnan(
                m_val
            ), f"Key {key!r}: legacy=NaN, migrated={m_val}"
            continue

        if isinstance(l_val, (int, float)) and isinstance(m_val, (int, float)):
            if l_val == 0 and m_val == 0:
                continue
            rel_diff = abs(l_val - m_val) / max(abs(l_val), abs(m_val), 1e-10)
            assert rel_diff <= tolerance, (
                f"Key {key!r}: legacy={l_val}, migrated={m_val}, "
                f"rel_diff={rel_diff:.6f} > tolerance={tolerance}"
            )
        else:
            assert l_val == m_val, f"Key {key!r}: legacy={l_val!r}, migrated={m_val!r}"
