"""AccelerationRegime I2 composite plugin.

Sign-votes across four acceleration measures to classify momentum regime.
"peak" and "trough" are single-bar inflection events, not multi-bar states.

Outputs:
    accel_regime:    "building" | "peak" | "trough" | "waning" | "neutral"
    accel_score:     float in [-1.0, 1.0] — signed agreement strength
    accel_agreement: float in [0.0, 1.0] — directional consensus (max votes / total)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..utils.common import is_num


@dataclass
class AccelerationRegimePlugin:
    name: str = "cmp_AccelerationRegime"
    outputs: frozenset = field(
        default_factory=lambda: frozenset(
            {
                "accel_regime",
                "accel_score",
                "accel_agreement",
            }
        )
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset = field(default_factory=lambda: frozenset({"momentum", "regime"}))
    inputs: tuple = ()  # reads from frames["features"] only
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}

        rsi_curvature = features.get("rsi_curvature")
        macd_hist_slope = features.get("macd_hist_slope")
        price_accel = features.get("price_accel")
        hma_accel = features.get("hma_accel")

        # Sign-vote each input: +1 positive, -1 negative, 0 unavailable/zero
        def _vote(x: Any) -> int:
            if is_num(x) and x > 0:
                return 1
            if is_num(x) and x < 0:
                return -1
            return 0

        votes = [_vote(rsi_curvature), _vote(macd_hist_slope), _vote(price_accel), _vote(hma_accel)]
        n_votes = 4  # always 4 inputs — zero is a valid abstention

        raw_sum = sum(votes)
        accel_score = round(raw_sum / n_votes, 4)

        # Agreement = max(pos_votes, neg_votes) / total
        # e.g. 4/4→1.0, 3/4→0.75, 2/4→0.5, 1/4→0.25, 0/0→0.0
        pos_count = sum(1 for v in votes if v > 0)
        neg_count = sum(1 for v in votes if v < 0)
        accel_agreement = round(max(pos_count, neg_count) / n_votes, 4)

        # Regime — inflection events (peak/trough) take priority over
        # directional states (building/waning) since they mark the turning bar.
        prev_accel_score = self._state.get("prev_accel_score", 0.0)

        if prev_accel_score > 0.3 and accel_score <= 0.3:
            regime = "peak"
        elif prev_accel_score < -0.3 and accel_score >= -0.3:
            regime = "trough"
        elif accel_score > 0.5:
            regime = "building"
        elif accel_score < -0.3:
            regime = "waning"
        else:
            regime = "neutral"

        # Write state AFTER regime determination
        self._state["prev_accel_score"] = accel_score

        return {
            "accel_regime": regime,
            "accel_score": accel_score,
            "accel_agreement": accel_agreement,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = AccelerationRegimePlugin()
