from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.intelligence.plugins import InputSpec
from src.intelligence.utils import clamp, is_num


@dataclass
class ConfluencePlugin:
    """Mean-reversion confluence scoring (RSI<30=bullish, >70=bearish)."""

    name: str = "Confluence"
    outputs: frozenset[str] = frozenset(
        {
            "confluence_score",
            "confluence_n_signals",
            "confluence_agreement",
            "meanrev_confluence_score",
            "meanrev_confluence_n_signals",
            "meanrev_confluence_agreement",
        }
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"pattern", "confluence"})
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

        # RSI scoring: <30 bullish (+1), >70 bearish (-1), linear between
        rsi = features.get("rsi_14")
        if is_num(rsi):
            if rsi < 30:
                scores.append(1.0)
            elif rsi > 70:
                scores.append(-1.0)
            else:
                # Linear: 30→+1, 50→0, 70→-1
                scores.append(1.0 - (rsi - 30) / 20.0)

        # MACD histogram scoring: positive → bullish, negative → bearish
        macd_hist = features.get("macd_histogram_12_26_9")
        if is_num(macd_hist):
            scores.append(clamp(macd_hist / max(abs(macd_hist), 1e-10)))

        # Stochastic %K scoring: <20 bullish, >80 bearish, linear between
        stoch_k = features.get("stoch_k_14_3")
        if is_num(stoch_k):
            if stoch_k < 20:
                scores.append(1.0)
            elif stoch_k > 80:
                scores.append(-1.0)
            else:
                scores.append(1.0 - (stoch_k - 20) / 30.0)

        # CCI scoring: < -100 bullish, > 100 bearish, linear between
        cci = features.get("cci_14")
        if is_num(cci):
            if cci < -100:
                scores.append(1.0)
            elif cci > 100:
                scores.append(-1.0)
            else:
                scores.append(-cci / 100.0)

        if not scores:
            return {}

        avg_score = sum(scores) / len(scores)
        # Agreement: fraction of signals with the same sign as the average
        if avg_score == 0:
            agreement = 0.0
        else:
            sign = 1 if avg_score > 0 else -1
            agreement = sum(1 for s in scores if (s > 0) == (sign > 0)) / len(scores)

        return {
            # Semantic keys — I6 should consume these
            "meanrev_confluence_score": avg_score,
            "meanrev_confluence_n_signals": float(len(scores)),
            "meanrev_confluence_agreement": agreement,
            # Legacy keys for backward compatibility
            "confluence_score": avg_score,
            "confluence_n_signals": float(len(scores)),
            "confluence_agreement": agreement,
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = ConfluencePlugin()
