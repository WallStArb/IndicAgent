"""Reference-validation tests for VWAPPlugin against pandas-ta.

Tolerance contract:
- VWAP is a session-anchored cumulative calculation. Agreement is machine-epsilon
  within a single session: atol=1e-4 with warmup_bars=0.
- pandas-ta vwap() requires a DatetimeIndex and resets at day boundaries. We test
  on a single-session 390-bar fixture to eliminate session boundary ambiguity.
- No EWM seeding: pure cumulative sum, so agreement is immediate.

Sign convention: VWAP is positive (price-weighted), output in the same units as price.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pandas_ta = pytest.importorskip("pandas_ta")

from src.intelligence.features.i1_indicators.vwap import VWAPPlugin
from tests.unit.intelligence.correctness.conftest import (
    assert_close_to_reference,
    frames_from_ohlcv,
)


def _make_single_session_ohlcv(n: int = 390, seed: int = 42) -> pd.DataFrame:
    """Create a single 390-bar (1-minute) trading session fixture.

    Uses UTC timestamps starting at 2024-01-02 09:30:00 Eastern (14:30 UTC).
    No session boundary within the 390 bars.
    """
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.02, n))
    high = close + rng.uniform(0, 0.1, n)
    low = close - rng.uniform(0, 0.1, n)
    volume = rng.uniform(1000, 5000, n)
    idx = pd.date_range(start="2024-01-02 14:30:00", periods=n, freq="1min", tz="UTC")
    df = pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )
    df["high"] = df[["high", "close"]].max(axis=1)
    df["low"] = df[["low", "close"]].min(axis=1)
    return df


class TestVWAPReference:
    """Validate VWAPPlugin output against pandas-ta vwap() reference.

    Tests use a single-session (390-bar) fixture to avoid session boundary semantics.
    Both implementations compute cumulative TP*Volume / cumulative Volume.
    Agreement is machine-epsilon (warmup_bars=0, atol=1e-4 for floating-point safety).
    """

    def _collect_vwap_series(self, df: pd.DataFrame) -> pd.Series:
        """Drive VWAPPlugin.compute_full and return vwap series."""
        plugin = VWAPPlugin()
        values: dict = {}
        for i in range(1, len(df) + 1):
            window = df.iloc[:i]
            result = plugin.compute_full(frames_from_ohlcv(window))
            if "vwap" in result:
                values[df.index[i - 1]] = result["vwap"]
        return pd.Series(values, name="vwap")

    def test_vwap_matches_pandas_ta_on_single_session(self) -> None:
        """VWAP matches pandas-ta on 390-bar single-session trending data.

        Session-scoped fixture avoids ambiguity at day boundaries. Both implementations
        compute cumulative TP*V / cumulative V from bar 0. Agreement is machine-epsilon.
        warmup_bars=0 — VWAP has no recursive seeding, valid from bar 1.
        """
        df = _make_single_session_ohlcv(n=390, seed=42)
        ours = self._collect_vwap_series(df)

        reference = pd.Series(
            pandas_ta.vwap(df["high"], df["low"], df["close"], df["volume"]).values,
            index=df.index,
            name="vwap_ref",
        )

        assert_close_to_reference(
            ours,
            reference,
            atol=1e-4,
            directional_min=0.999,
            warmup_bars=0,
            name="vwap",
        )

    def test_vwap_matches_pandas_ta_on_single_session_ranging(self) -> None:
        """VWAP matches pandas-ta on 390-bar single-session ranging data."""
        df = _make_single_session_ohlcv(n=390, seed=43)
        ours = self._collect_vwap_series(df)

        reference = pd.Series(
            pandas_ta.vwap(df["high"], df["low"], df["close"], df["volume"]).values,
            index=df.index,
            name="vwap_ref",
        )

        assert_close_to_reference(
            ours,
            reference,
            atol=1e-4,
            directional_min=0.999,
            warmup_bars=0,
            name="vwap",
        )

    def test_vwap_positive_price(self) -> None:
        """VWAP must be positive (price-weighted average, same units as price)."""
        df = _make_single_session_ohlcv(n=100, seed=42)
        ours = self._collect_vwap_series(df)
        valid = ours.dropna()
        assert (valid > 0).all(), f"VWAP must be positive; min={float(valid.min()):.4f}"
