from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class SupportResistancePlugin:
    """Detect dynamic S/R levels from pivot clustering with strength scoring."""

    name: str = "struct_SupportResistance"
    outputs: set[str] = frozenset(
        {
            "nearest_resistance",
            "nearest_support",
            "resistance_strength",
            "support_strength",
            "resistance_dist_pct",
            "support_dist_pct",
            "sr_level_count",
            "resistance_age_bars",
            "support_age_bars",
        }
    )
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"structure"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=120),)
    window: int = 10
    cluster_pct: float = 0.005
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        current_price = float(close[-1])
        n_bars = len(df)

        # Detect pivot highs and lows — track (price, bar_index) tuples
        pivot_highs: list[tuple[float, int]] = []
        pivot_lows: list[tuple[float, int]] = []
        w = self.window

        for i in range(w, len(high) - w):
            if high[i] == np.max(high[i - w : i + w + 1]):
                pivot_highs.append((float(high[i]), i))
            if low[i] == np.min(low[i - w : i + w + 1]):
                pivot_lows.append((float(low[i]), i))

        # Cluster nearby levels
        resistance_clusters = self._cluster_levels(pivot_highs, current_price)
        support_clusters = self._cluster_levels(pivot_lows, current_price)

        # Find nearest resistance (above price) and support (below price)
        resistances_above = [r for r in resistance_clusters if r["level"] > current_price]
        supports_below = [s for s in support_clusters if s["level"] < current_price]

        if resistances_above:
            nearest_r = min(resistances_above, key=lambda x: x["level"] - current_price)
        else:
            nearest_r = {"level": current_price * 1.02, "strength": 0, "latest_idx": 0}

        if supports_below:
            nearest_s = max(supports_below, key=lambda x: x["level"])
        else:
            nearest_s = {"level": current_price * 0.98, "strength": 0, "latest_idx": 0}

        r_dist = (nearest_r["level"] - current_price) / current_price * 100
        s_dist = (current_price - nearest_s["level"]) / current_price * 100

        # Age: bars since most recent pivot touch in nearest cluster
        r_idx = nearest_r["latest_idx"]
        s_idx = nearest_s["latest_idx"]
        r_age = float(n_bars - 1 - r_idx) if r_idx > 0 else float(n_bars)
        s_age = float(n_bars - 1 - s_idx) if s_idx > 0 else float(n_bars)

        return {
            "nearest_resistance": nearest_r["level"],
            "nearest_support": nearest_s["level"],
            "resistance_strength": float(nearest_r["strength"]),
            "support_strength": float(nearest_s["strength"]),
            "resistance_dist_pct": r_dist,
            "support_dist_pct": s_dist,
            "sr_level_count": float(len(resistance_clusters) + len(support_clusters)),
            "resistance_age_bars": r_age,
            "support_age_bars": s_age,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    def _cluster_levels(
        self, pivots: list[tuple[float, int]], current_price: float,
    ) -> list[dict[str, Any]]:
        """Cluster nearby price levels; return level, strength, and latest bar index."""
        if not pivots:
            return []

        sorted_pivots = sorted(pivots, key=lambda p: p[0])
        clusters: list[dict[str, Any]] = []
        current_cluster: list[tuple[float, int]] = [sorted_pivots[0]]

        for price, idx in sorted_pivots[1:]:
            if abs(price - current_cluster[-1][0]) <= current_price * self.cluster_pct:
                current_cluster.append((price, idx))
            else:
                clusters.append(self._finalize_cluster(current_cluster))
                current_cluster = [(price, idx)]

        if current_cluster:
            clusters.append(self._finalize_cluster(current_cluster))

        return clusters

    @staticmethod
    def _finalize_cluster(members: list[tuple[float, int]]) -> dict[str, Any]:
        avg_level = sum(p for p, _ in members) / len(members)
        latest_idx = max(idx for _, idx in members)
        return {"level": avg_level, "strength": len(members), "latest_idx": latest_idx}


plugin = SupportResistancePlugin()
