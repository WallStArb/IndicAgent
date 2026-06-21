"""Cross-TF Support/Resistance Confluence Plugin.

Detects support/resistance level alignment between HTF and LTF.
Uses I4 pivot S/R levels to measure price proximity to key levels.

Gradient scoring (per D-06 and CONTEXT.md):
- Uses proximity decay: 1/(distance+1) for soft saturation
- Separates HTF (1h/4h) and LTF (5m/15m) proximity scores
- Confluence = tanh(htf_avg + ltf_avg) for gradient output

Outputs:
    ctf_sr_confluence: float [-1, +1]
        - Positive: Both HTF and LTF near resistance
        - Negative: Both HTF and LTF near support
        - Near 0: No S/R confluence
    ctf_sr_regime: str
        - aligned_both_resistance: HTF+LTF at resistance
        - aligned_both_support: HTF+LTF at support
        - aligned_htf_only: Only HTF at S/R
        - aligned_ltf_only: Only LTF at S/R
        - no_confluence: No S/R proximity
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import tanh
from typing import Any

from src.intelligence.trading.atr_utils import get_atr

from ..plugins import InputSpec


@dataclass
class CrossTFSRConfluencePlugin:
    """Cross-TF support/resistance confluence detector.

    Follows the CrossTimeframeConfluencePlugin pattern: reads cached I4
    context from frames dict and computes HTF-LTF S/R proximity using
    proximity decay scoring (not binary thresholds).

    Per D-06: outputs ctf_sr_confluence [-1, +1] and ctf_sr_regime (categorical)
    Per D-17: gradient scoring via proximity decay, NOT binary step functions
    """

    name: str = "i6_CrossTFSRConfluence"
    outputs: frozenset[str] = frozenset(
        {
            "ctf_sr_confluence",
            "ctf_sr_regime",
        }
    )
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"confluence"})
    inputs: list[InputSpec] = field(default_factory=list)
    _state: dict = field(default_factory=dict)

    # HTF timeframes (1h+) contribute to HTF proximity
    _HTF_TFS: tuple[str, ...] = ("1h", "4h")
    # LTF timeframes (5m/15m) contribute to LTF proximity
    _LTF_TFS: tuple[str, ...] = ("5m", "15m")

    # Proximity window: within this many ATRs of S/R level
    _PROXIMITY_ATR: float = 1.0

    # Regime classification thresholds
    _STRONG_THRESHOLD: float = 0.5
    _WEAK_THRESHOLD: float = 0.2

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        """Compute S/R confluence across timeframes.

        Reads frames["intel_{tf}"] flat dicts (all tiers merged) for each timeframe.
        Uses nearest_resistance/nearest_support (I3) and atr_14 (I1).
        Current bar close comes from frames["features"] (same for all TFs — current bar).

        Args:
            frames: Dict with cached I1-I6 intelligence per TF (keys like "intel_5m").
                    Content is a flat merged dict of all tier outputs for that TF.

        Returns:
            dict with:
                ctf_sr_confluence: float [-1, +1] (tanh-normalized S/R alignment)
                ctf_sr_regime: str (one of 5 categorical labels)
        """
        df = frames.get("main")
        current_close = float(df["close"].iloc[-1]) if df is not None and len(df) else None
        if not isinstance(current_close, (int, float)) or current_close <= 0:
            return {"ctf_sr_confluence": 0.0, "ctf_sr_regime": "no_confluence"}

        close = float(current_close)
        sr_scores: dict[str, float] = {}

        for tf in (*self._HTF_TFS, *self._LTF_TFS):
            intel = frames.get(f"intel_{tf}")
            if not intel:
                continue

            # I3 SupportResistancePlugin fields (nearest_resistance, nearest_support)
            resistance = intel.get("nearest_resistance")
            support = intel.get("nearest_support")

            if not isinstance(resistance, (int, float)) or resistance == 0:
                continue
            if not isinstance(support, (int, float)) or support == 0:
                continue

            atr = get_atr(intel)
            if not atr:
                continue

            # Normalize distances to S/R in ATR units
            dist_to_resistance = (float(resistance) - close) / float(atr)
            dist_to_support = (close - float(support)) / float(atr)

            # Score: positive near resistance (+), negative near support (-)
            # Proximity decay: 1/(distance+1) within _PROXIMITY_ATR window
            if 0 <= dist_to_resistance <= self._PROXIMITY_ATR:
                sr_score = 1.0 / (dist_to_resistance + 1.0)
            elif 0 <= dist_to_support <= self._PROXIMITY_ATR:
                sr_score = -1.0 / (dist_to_support + 1.0)
            else:
                sr_score = 0.0

            sr_scores[tf] = sr_score

        if not sr_scores:
            return {
                "ctf_sr_confluence": 0.0,
                "ctf_sr_regime": "no_confluence",
            }

        # Separate HTF and LTF scores
        htf_scores = [sr_scores[tf] for tf in self._HTF_TFS if tf in sr_scores]
        ltf_scores = [sr_scores[tf] for tf in self._LTF_TFS if tf in sr_scores]

        if not htf_scores or not ltf_scores:
            return {
                "ctf_sr_confluence": 0.0,
                "ctf_sr_regime": "no_confluence",
            }

        htf_avg = sum(htf_scores) / len(htf_scores)
        ltf_avg = sum(ltf_scores) / len(ltf_scores)

        confluence = tanh(htf_avg + ltf_avg)

        # Regime classification — 5 categorical labels
        if htf_avg > self._STRONG_THRESHOLD and ltf_avg > self._STRONG_THRESHOLD:
            regime = "aligned_both_resistance"
        elif htf_avg < -self._STRONG_THRESHOLD and ltf_avg < -self._STRONG_THRESHOLD:
            regime = "aligned_both_support"
        elif abs(htf_avg) > self._STRONG_THRESHOLD and abs(ltf_avg) < self._WEAK_THRESHOLD:
            regime = "aligned_htf_only"
        elif abs(htf_avg) < self._WEAK_THRESHOLD and abs(ltf_avg) > self._STRONG_THRESHOLD:
            regime = "aligned_ltf_only"
        else:
            regime = "no_confluence"

        return {
            "ctf_sr_confluence": round(confluence, 4),
            "ctf_sr_regime": regime,
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = CrossTFSRConfluencePlugin()
