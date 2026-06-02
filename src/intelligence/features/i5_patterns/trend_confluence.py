from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.intelligence.plugins import InputSpec
from src.intelligence.utils import clamp, is_num


@dataclass
class TrendConfluencePlugin:
    """Trend-following confluence scoring.

    Aggregates trend signals into a single [-1, +1] score.
    Counterpart to the mean-reversion Confluence plugin.
    """

    name: str = "TrendConfluence"
    outputs: frozenset[str] = frozenset(
        {
            "trend_confluence_score",
            "trend_confluence_n_signals",
            "trend_confluence_agreement",
            "trend_confluence_strength",
        }
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"pattern", "confluence", "trend"})
    inputs: list[InputSpec] = ()  # Consumes upstream feature dicts
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
        }
        if not features:
            return {}

        scores: list[float] = []

        # 1. SMA crossover: sma_20 > sma_50
        sma_cross = features.get("sma_20_gt_50")
        if sma_cross is not None:
            scores.append(1.0 if sma_cross else -1.0)

        # 2. ADX + DI: only score if ADX > 20 (meaningful trend)
        adx = features.get("adx_14")
        plus_di = features.get("plus_di_14")
        minus_di = features.get("minus_di_14")
        if is_num(adx) and is_num(plus_di) and is_num(minus_di) and adx > 20:
            if plus_di > minus_di:
                scores.append(1.0)
            else:
                scores.append(-1.0)

        # 3. Swing pattern: direct pass-through
        swing = features.get("swing_pattern")
        if is_num(swing) and swing != 0:
            scores.append(1.0 if swing > 0 else -1.0)

        # 4. MACD histogram: positive = bullish, negative = bearish
        macd_hist = features.get("macd_histogram_12_26_9") or features.get("macd_12_26_9_hist")
        if is_num(macd_hist):
            scores.append(1.0 if macd_hist > 0 else -1.0)

        # 5. Supertrend direction: direct pass-through
        st_dir = features.get("supertrend_dir")
        if is_num(st_dir) and st_dir != 0:
            scores.append(1.0 if st_dir > 0 else -1.0)

        # 6. Trend regime: direct pass-through (already [-1, +1])
        tr = features.get("trend_regime")
        if is_num(tr) and tr != 0:
            scores.append(clamp(tr))

        if not scores:
            return {}

        avg_score = sum(scores) / len(scores)

        # Agreement: fraction of signals matching majority sign
        if avg_score == 0:
            agreement = 0.0
        else:
            majority_positive = avg_score > 0
            agreement = sum(1 for s in scores if (s > 0) == majority_positive) / len(scores)

        strength = abs(avg_score) * agreement

        return {
            "trend_confluence_score": avg_score,
            "trend_confluence_n_signals": float(len(scores)),
            "trend_confluence_agreement": agreement,
            "trend_confluence_strength": strength,
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = TrendConfluencePlugin()
