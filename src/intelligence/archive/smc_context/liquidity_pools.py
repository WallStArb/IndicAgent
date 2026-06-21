"""smc_LiquidityPools — Named buy-side/sell-side liquidity pool detection.

Identifies institutional levels where stop-loss orders cluster:
PWH/PWL (1.00), PDH/PDL (0.85), equal highs/lows (0.60–0.75), session H/L (0.50).
Also outputs premium/discount context flag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.intelligence.plugins import InputSpec

from .swing_utils import find_swing_highs, find_swing_lows

# Significance scores by level type
_SIG = {
    "pwh": 1.00,
    "pwl": 1.00,
    "pdh": 0.85,
    "pdl": 0.85,
    "eq_highs_3": 0.75,
    "eq_lows_3": 0.75,
    "eq_highs_2": 0.60,
    "eq_lows_2": 0.60,
    "session_high": 0.50,
    "session_low": 0.50,
}


@dataclass
class LiquidityPoolsPlugin:
    """Named buy-side (BSL) and sell-side (SSL) liquidity pool detection."""

    name: str = "smc_LiquidityPools"
    outputs: frozenset[str] = frozenset(
        {
            "bsl_level",
            "bsl_type",
            "bsl_significance",
            "bsl_dist_atr",
            "bsl_touches",
            "ssl_level",
            "ssl_type",
            "ssl_significance",
            "ssl_dist_atr",
            "ssl_touches",
            "price_in_premium",
            "premium_position",
            "pool_count",
        }
    )
    min_lookback: int = 60
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"smart_money", "liquidity"})
    inputs: list[InputSpec] = (
        InputSpec(symbol=".*", lookback=150),
        InputSpec(symbol=".*", timeframe="1d", lookback=5),
    )
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        df_1d = frames.get("1d")
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        current_price = float(close[-1])

        atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            atr = current_price * 0.002

        # --- Collect all candidate levels ---
        bsl_candidates: list[tuple[float, str, float]] = []  # (price, type, significance)
        ssl_candidates: list[tuple[float, str, float]] = []

        # 1. PWH / PWL from 1d data
        if df_1d is not None and len(df_1d) >= 5:
            d_high = df_1d["high"].to_numpy(dtype=float)
            d_low = df_1d["low"].to_numpy(dtype=float)
            pwh = float(np.max(d_high[-5:-1]))
            pwl = float(np.min(d_low[-5:-1]))
            if pwh > current_price:
                bsl_candidates.append((pwh, "pwh", _SIG["pwh"]))
            if pwl < current_price:
                ssl_candidates.append((pwl, "pwl", _SIG["pwl"]))

            # 2. PDH / PDL (yesterday)
            if len(df_1d) >= 2:
                pdh = float(d_high[-2])
                pdl = float(d_low[-2])
                if pdh > current_price:
                    bsl_candidates.append((pdh, "pdh", _SIG["pdh"]))
                if pdl < current_price:
                    ssl_candidates.append((pdl, "pdl", _SIG["pdl"]))

        # 3. Equal highs / equal lows (1m swings)
        tolerance = atr * 0.75
        swing_highs_idx = find_swing_highs(high, n=5)
        swing_lows_idx = find_swing_lows(low, n=5)

        eq_highs = self._find_equal_levels([float(high[i]) for i in swing_highs_idx], tolerance)
        eq_lows = self._find_equal_levels([float(low[i]) for i in swing_lows_idx], tolerance)

        for level, touches in eq_highs:
            if level > current_price:
                lvl_type = "eq_highs_3" if touches >= 3 else "eq_highs_2"
                bsl_candidates.append((level, lvl_type, _SIG[lvl_type]))

        for level, touches in eq_lows:
            if level < current_price:
                lvl_type = "eq_lows_3" if touches >= 3 else "eq_lows_2"
                ssl_candidates.append((level, lvl_type, _SIG[lvl_type]))

        # 4. Session high / low (current calendar day from 1m timestamps)
        session_high = float(np.max(high[-390:])) if len(high) >= 390 else float(np.max(high))
        session_low = float(np.min(low[-390:])) if len(low) >= 390 else float(np.min(low))
        if session_high > current_price:
            bsl_candidates.append((session_high, "session_high", _SIG["session_high"]))
        if session_low < current_price:
            ssl_candidates.append((session_low, "session_low", _SIG["session_low"]))

        pool_count = float(len(bsl_candidates) + len(ssl_candidates))

        # Select nearest significant level on each side
        bsl = self._nearest(bsl_candidates, current_price, above=True)
        ssl = self._nearest(ssl_candidates, current_price, above=False)

        # Premium / Discount — use full available bar range to capture recent swing
        range_high = float(np.max(high))
        range_low = float(np.min(low))
        midpoint = (range_high + range_low) / 2.0
        price_in_premium = 1.0 if current_price >= midpoint else 0.0
        denom = (range_high - midpoint) if range_high != midpoint else 1.0
        premium_position = float(np.clip((current_price - midpoint) / denom, -1.0, 1.0))

        result: dict[str, Any] = {
            "price_in_premium": price_in_premium,
            "premium_position": round(premium_position, 4),
            "pool_count": pool_count,
        }

        if bsl:
            level, lvl_type, sig = bsl
            result.update(
                {
                    "bsl_level": round(level, 4),
                    "bsl_type": sig,  # use significance as encoded float
                    "bsl_significance": sig,
                    "bsl_dist_atr": round(abs(level - current_price) / atr, 4) if atr > 0 else 0.0,
                    "bsl_touches": self._touches_for(lvl_type),
                }
            )
        else:
            result.update(
                {
                    "bsl_level": 0.0,
                    "bsl_type": 0.0,
                    "bsl_significance": 0.0,
                    "bsl_dist_atr": 0.0,
                    "bsl_touches": 0.0,
                }
            )

        if ssl:
            level, lvl_type, sig = ssl
            result.update(
                {
                    "ssl_level": round(level, 4),
                    "ssl_type": sig,
                    "ssl_significance": sig,
                    "ssl_dist_atr": round(abs(current_price - level) / atr, 4) if atr > 0 else 0.0,
                    "ssl_touches": self._touches_for(lvl_type),
                }
            )
        else:
            result.update(
                {
                    "ssl_level": 0.0,
                    "ssl_type": 0.0,
                    "ssl_significance": 0.0,
                    "ssl_dist_atr": 0.0,
                    "ssl_touches": 0.0,
                }
            )

        return result

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _find_equal_levels(prices: list[float], tolerance: float) -> list[tuple[float, int]]:
        """Cluster prices within tolerance → return (mean_price, touch_count) for clusters ≥ 2.

        Optimized from O(N²) to O(N) using single-pass clustering.
        """
        if not prices:
            return []
        if not prices:
            return []

        # Sort prices first - O(N log N)
        sorted_prices = sorted(prices)

        # Single-pass clustering - O(N)
        clusters: list[list[float]] = []
        for p in sorted_prices:
            # Only check the last cluster (if any) since prices are sorted
            if clusters and abs(p - np.mean(clusters[-1])) <= tolerance:
                clusters[-1].append(p)
            else:
                clusters.append([p])

        return [(float(np.mean(c)), len(c)) for c in clusters if len(c) >= 2]

    @staticmethod
    def _nearest(
        candidates: list[tuple[float, str, float]],
        price: float,
        above: bool,
    ) -> tuple[float, str, float] | None:
        """Return candidate nearest to price, preferring higher significance on ties."""
        if not candidates:
            return None
        filtered = [c for c in candidates if (c[0] > price if above else c[0] < price)]
        if not filtered:
            return None
        # Sort: primary = significance (highest), secondary = distance (nearest)
        return min(filtered, key=lambda c: (-c[2], abs(c[0] - price)))

    @staticmethod
    def _touches_for(lvl_type: str) -> float:
        if "3" in lvl_type:
            return 3.0
        if "2" in lvl_type:
            return 2.0
        return 1.0


plugin = LiquidityPoolsPlugin()
