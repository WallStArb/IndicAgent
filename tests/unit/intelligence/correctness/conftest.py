"""Shared fixtures and reference-comparison helper for mathematical correctness tests.

All synthetic fixtures produce valid OHLC (high >= max(open, close),
low <= min(open, close)) and return a pandas DataFrame with columns
[open, high, low, close, volume] indexed by a UTC DatetimeIndex at 1-minute
frequency.

Do NOT add fixtures that hit the live database; correctness tests are
entirely synthetic.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helper: index builder
# ---------------------------------------------------------------------------


def _make_index(n: int, seed_date: str = "2024-01-02") -> pd.DatetimeIndex:
    """Return a UTC DatetimeIndex of *n* 1-minute bars starting at seed_date."""
    return pd.date_range(start=seed_date, periods=n, freq="1min", tz="UTC")


def _clamp_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Enforce OHLC validity: high >= max(open,close), low <= min(open,close)."""
    df = df.copy()
    df["high"] = df[["high", "open", "close"]].max(axis=1)
    df["low"] = df[["low", "open", "close"]].min(axis=1)
    return df


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def synthetic_ohlcv_trending() -> pd.DataFrame:
    """500-bar deterministic upward-trend OHLCV (seed=42, 1-minute UTC bars)."""
    rng = np.random.default_rng(42)
    n = 500
    base = 100.0
    # Gentle upward drift with small noise
    returns = rng.normal(0.0005, 0.002, n)
    close = base * np.exp(np.cumsum(returns))
    spread = close * 0.0015
    noise = rng.normal(0, 0.001, n)
    open_ = close + noise * close
    high = close + spread * (1 + rng.uniform(0, 1, n))
    low = close - spread * (1 + rng.uniform(0, 1, n))
    volume = rng.uniform(5000, 15000, n)

    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=_make_index(n),
    )
    return _clamp_ohlcv(df)


@pytest.fixture(scope="session")
def synthetic_ohlcv_ranging() -> pd.DataFrame:
    """500-bar mean-reverting OHLCV (sine wave + noise, seed=43, 1-minute UTC bars)."""
    rng = np.random.default_rng(43)
    n = 500
    base = 100.0
    # Sine wave oscillation around base price
    t = np.linspace(0, 4 * np.pi, n)
    close = base + 3.0 * np.sin(t) + rng.normal(0, 0.2, n)
    spread = np.abs(close) * 0.0015
    noise = rng.normal(0, 0.001, n)
    open_ = close + noise * close
    high = close + spread * (1 + rng.uniform(0, 1, n))
    low = close - spread * (1 + rng.uniform(0, 1, n))
    volume = rng.uniform(3000, 12000, n)

    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=_make_index(n),
    )
    return _clamp_ohlcv(df)


@pytest.fixture(scope="session")
def synthetic_ohlcv_gap() -> pd.DataFrame:
    """200-bar OHLCV with a 5% gap up at bar index 100 (open[100] != close[99]).

    Tests that indicators handle discontinuous price series without NaN propagation.
    """
    rng = np.random.default_rng(44)
    n = 200
    base = 100.0
    returns = rng.normal(0.0, 0.002, n)
    close = base * np.exp(np.cumsum(returns))
    spread = close * 0.0015
    open_ = np.roll(close, 1)
    open_[0] = close[0] - spread[0]
    # Inject 5% gap up at bar 100
    open_[100] = close[99] * 1.05
    high = np.maximum(open_, close) + spread * rng.uniform(0, 1, n)
    low = np.minimum(open_, close) - spread * rng.uniform(0, 1, n)
    volume = rng.uniform(5000, 15000, n)

    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=_make_index(n),
    )
    return _clamp_ohlcv(df)


@pytest.fixture(scope="session")
def synthetic_ohlcv_zero_volume() -> pd.DataFrame:
    """100-bar OHLCV where the volume column is all zeros.

    Ensures VWAP/OFI plugins handle division-by-zero gracefully.
    """
    rng = np.random.default_rng(45)
    n = 100
    base = 100.0
    returns = rng.normal(0.0, 0.002, n)
    close = base * np.exp(np.cumsum(returns))
    spread = close * 0.0015
    noise = rng.normal(0, 0.001, n)
    open_ = close + noise * close
    high = close + spread * rng.uniform(0.5, 1.5, n)
    low = close - spread * rng.uniform(0.5, 1.5, n)
    volume = np.zeros(n)

    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=_make_index(n),
    )
    return _clamp_ohlcv(df)


@pytest.fixture(scope="session")
def synthetic_ohlcv_single_bar() -> pd.DataFrame:
    """1-row OHLCV DataFrame. Tests boundary: plugins must not crash on min data."""
    df = pd.DataFrame(
        {
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1000.0],
        },
        index=_make_index(1),
    )
    return df


@pytest.fixture(scope="session")
def synthetic_ohlcv_flat() -> pd.DataFrame:
    """500-bar OHLCV where high=low=close=open=100.0 and volume is constant.

    Used for GARCH long-run variance convergence tests (variance should approach 0).
    """
    n = 500
    price = 100.0
    vol = 10000.0
    df = pd.DataFrame(
        {
            "open": np.full(n, price),
            "high": np.full(n, price),
            "low": np.full(n, price),
            "close": np.full(n, price),
            "volume": np.full(n, vol),
        },
        index=_make_index(n),
    )
    return df


# ---------------------------------------------------------------------------
# Helper functions (importable directly, not fixtures)
# ---------------------------------------------------------------------------


def assert_close_to_reference(
    ours: pd.Series | np.ndarray,
    reference: pd.Series | np.ndarray,
    *,
    atol: float = 1e-6,
    directional_min: float = 0.999,
    warmup_bars: int = 0,
    name: str = "",
) -> None:
    """Assert that *ours* matches *reference* within tolerance.

    Steps:
    1. Convert both inputs to pd.Series.
    2. Align by inner-join on index (or by position if no index).
    3. Drop the first ``warmup_bars`` entries from both series.
    4. Drop any rows where either series is NaN.
    5. Assert max absolute error <= atol.
    6. Compute directional agreement as sign(ours.diff()) == sign(reference.diff()),
       excluding rows where either diff is NaN or zero.
    7. Assert directional agreement >= directional_min.

    Args:
        ours: Production indicator values.
        reference: pandas-ta reference values.
        atol: Maximum allowed absolute error (default 1e-6).
        directional_min: Minimum required directional agreement (default 0.999).
        warmup_bars: Number of leading bars to discard before comparison.
            Handles indicator-specific seeding differences.
        name: Human-readable indicator name included in failure messages.
    """
    # Convert to Series
    if not isinstance(ours, pd.Series):
        ours = pd.Series(np.asarray(ours, dtype=float))
    else:
        ours = ours.astype(float)

    if not isinstance(reference, pd.Series):
        reference = pd.Series(np.asarray(reference, dtype=float))
    else:
        reference = reference.astype(float)

    # Align by index if both have named indices, otherwise by position
    if ours.index.equals(reference.index):
        aligned_ours = ours
        aligned_ref = reference
    elif ours.index.dtype != object and reference.index.dtype != object:
        # Inner join on index
        combined = pd.DataFrame({"o": ours, "r": reference}).dropna(how="all")
        aligned_ours = combined["o"]
        aligned_ref = combined["r"]
    else:
        # Align by position (reset index)
        min_len = min(len(ours), len(reference))
        aligned_ours = ours.iloc[:min_len].reset_index(drop=True)
        aligned_ref = reference.iloc[:min_len].reset_index(drop=True)

    # Apply warmup trim
    if warmup_bars > 0:
        aligned_ours = aligned_ours.iloc[warmup_bars:]
        aligned_ref = aligned_ref.iloc[warmup_bars:]

    # Drop rows where either is NaN
    valid_mask = aligned_ours.notna() & aligned_ref.notna()
    aligned_ours = aligned_ours[valid_mask]
    aligned_ref = aligned_ref[valid_mask]

    assert (
        len(aligned_ours) > 0
    ), f"{name}: no valid (non-NaN) bars remain after warmup_bars={warmup_bars} trim"

    # Absolute error check
    abs_errors = (aligned_ours - aligned_ref).abs()
    max_err = float(abs_errors.max())

    # Directional agreement check
    ours_diff = aligned_ours.diff()
    ref_diff = aligned_ref.diff()
    dir_mask = ours_diff.notna() & ref_diff.notna() & (ours_diff != 0) & (ref_diff != 0)
    if dir_mask.sum() > 0:
        agreement = float((np.sign(ours_diff[dir_mask]) == np.sign(ref_diff[dir_mask])).mean())
    else:
        # No non-zero diffs available; skip directional check
        agreement = 1.0

    # Build diagnostic prefix
    label = f"{name}: " if name else ""

    assert max_err <= atol, (
        f"{label}max_err={max_err:.2e} (atol={atol}), "
        f"directional_agreement={agreement:.4f} (min={directional_min})"
    )
    assert agreement >= directional_min, (
        f"{label}max_err={max_err:.2e} (atol={atol}), "
        f"directional_agreement={agreement:.4f} (min={directional_min})"
    )


def frames_from_ohlcv(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Wrap a DataFrame in the plugin frames protocol dict.

    Plugins receive ``{"main": df}`` where *df* is the OHLCV DataFrame.
    """
    return {"main": df}
