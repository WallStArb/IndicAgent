from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.intelligence.plugins import InputSpec
from src.intelligence.trading.atr_utils import get_atr
from src.intelligence.utils import find_peaks, find_troughs

_LOOKBACK_BY_TF: dict[str, int] = {
    "1m": 60,
    "5m": 60,
    "15m": 80,
    "1h": 120,
    "4h": 120,
    "1d": 60,
}


@dataclass
class SupportResistancePlugin:
    """Detect dynamic S/R levels from pivot clustering with strength scoring."""

    name: str = "struct_SupportResistance"
    outputs: frozenset[str] = frozenset(
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
    capability_tags: frozenset[str] = frozenset({"structure"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=120),)
    window: int = 10
    cluster_atr_mult: float = 0.5
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        tf = frames.get("timeframe", "")
        lookback = _LOOKBACK_BY_TF.get(tf, 120)
        df = df.iloc[-lookback:]

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        current_price = float(close[-1])
        n_bars = len(df)

        atr_14 = get_atr(frames.get("i1") or {})
        volume = df["volume"].to_numpy(dtype=float) if "volume" in df.columns else None
        mean_volume = float(volume.mean()) if volume is not None and volume.size else 0.0

        w = self.window
        peak_indices = find_peaks(high, n=w)
        trough_indices = find_troughs(low, n=w)

        pivot_highs = [(float(high[i]), i) for i in peak_indices]
        pivot_lows = [(float(low[i]), i) for i in trough_indices]

        resistance_clusters = self._cluster_levels(
            pivot_highs, current_price, atr_14, volume, mean_volume
        )
        support_clusters = self._cluster_levels(
            pivot_lows, current_price, atr_14, volume, mean_volume
        )

        resistances_above = [r for r in resistance_clusters if r["level"] > current_price]
        supports_below = [s for s in support_clusters if s["level"] < current_price]

        nearest_r = (
            min(resistances_above, key=lambda x: x["level"] - current_price)
            if resistances_above
            else None
        )
        nearest_s = max(supports_below, key=lambda x: x["level"]) if supports_below else None

        result: dict[str, Any] = {}
        result["sr_level_count"] = float(len(resistance_clusters) + len(support_clusters))
        if nearest_r is not None:
            r_dist = (nearest_r["level"] - current_price) / current_price * 100
            r_age = float(n_bars - 1 - nearest_r["latest_idx"])
            result["nearest_resistance"] = nearest_r["level"]
            result["resistance_strength"] = float(nearest_r["strength"])
            result["resistance_dist_pct"] = r_dist
            result["resistance_age_bars"] = r_age
        if nearest_s is not None:
            s_dist = (current_price - nearest_s["level"]) / current_price * 100
            s_age = float(n_bars - 1 - nearest_s["latest_idx"])
            result["nearest_support"] = nearest_s["level"]
            result["support_strength"] = float(nearest_s["strength"])
            result["support_dist_pct"] = s_dist
            result["support_age_bars"] = s_age
        return result

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)

    def _cluster_levels(
        self,
        pivots: list[tuple[float, int]],
        current_price: float,
        atr_14: float | None,
        volume: Any,
        mean_volume: float,
    ) -> list[dict[str, Any]]:
        """Cluster nearby price levels; return level, strength, and latest bar index."""
        if not pivots:
            return []

        cluster_radius = (atr_14 * self.cluster_atr_mult) if atr_14 else (current_price * 0.005)

        sorted_pivots = sorted(pivots, key=lambda p: p[0])
        clusters: list[dict[str, Any]] = []
        current_cluster: list[tuple[float, int]] = [sorted_pivots[0]]

        for price, idx in sorted_pivots[1:]:
            if abs(price - current_cluster[-1][0]) <= cluster_radius:
                current_cluster.append((price, idx))
            else:
                clusters.append(self._finalize_cluster(current_cluster, volume, mean_volume))
                current_cluster = [(price, idx)]

        if current_cluster:
            clusters.append(self._finalize_cluster(current_cluster, volume, mean_volume))

        return clusters

    @staticmethod
    def _finalize_cluster(
        members: list[tuple[float, int]],
        volume: Any,
        mean_volume: float,
    ) -> dict[str, Any]:
        avg_level = sum(p for p, _ in members) / len(members)
        latest_idx = max(idx for _, idx in members)
        vol_sum = sum(
            (
                min(2.0, (float(volume[idx]) / mean_volume if mean_volume > 0 else 1.0))
                if volume is not None
                else 1.0
            )
            for _, idx in members
        )
        strength = len(members) * (vol_sum / len(members))
        return {"level": avg_level, "strength": strength, "latest_idx": latest_idx}


plugin = SupportResistancePlugin()
