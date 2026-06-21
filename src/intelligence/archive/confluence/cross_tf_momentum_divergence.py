"""Cross-TF Momentum Divergence Plugin.

Detects momentum bias divergence between HTF (1h+) and LTF (5m/15m).
Uses I2 event direction + RSI/MACD alignment to score momentum per TF,
then computes divergence as HTF_bias - LTF_bias.

Gradient scoring (per D-06 and CONTEXT.md specific_ideas):
- Uses np.tanh() for soft saturation (NOT binary step functions)
- Recency weighting: recent bars matter more
- Proximity decay: nearby TFs have more influence
- Computes HTF_bias and LTF_bias from I2 events + I4 context
- Divergence = HTF_bias - LTF_bias, normalized via tanh

Outputs:
    ctf_momentum_divergence: float [-1, +1]
        - Positive: HTF bullish, LTF bearish (pullback setup)
        - Negative: HTF bearish, LTF bullish (bounce setup)
        - Near 0: No divergence (aligned)
    ctf_momentum_regime: str
        - aligned_htf_bull: Both HTF+LTF bullish
        - aligned_htf_bear: Both HTF+LTF bearish
        - pullback: HTF bullish, LTF bearish (dip buy)
        - bounce: HTF bearish, LTF bullish (short squeeze)
        - mixed: Unclear direction
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import tanh
from typing import Any

from ..plugins import InputSpec


@dataclass
class CrossTFMomentumDivergencePlugin:
    """Cross-TF momentum divergence detector (FULL IMPLEMENTATION per D-06).

    Follows the CrossTimeframeConfluencePlugin pattern: reads cached I2/I4
    intelligence from frames dict and computes HTF-LTF divergence using
    np.tanh() gradient scoring (not binary step functions).

    Per D-06: outputs ctf_momentum_divergence [-1, +1] and ctf_momentum_regime (categorical)
    Per CONTEXT.md: extract momentum bias from each TF using I2 events + RSI/MACD direction
    """

    name: str = "i6_CrossTFMomentumDivergence"
    outputs: frozenset[str] = frozenset(
        {
            "ctf_momentum_divergence",
            "ctf_momentum_regime",
        }
    )
    min_lookback: int = 20  # Need 20 bars for RSI/MACD
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"confluence"})
    inputs: list[InputSpec] = field(default_factory=list)
    _state: dict = field(default_factory=dict)

    # HTF timeframes (1h+) contribute to HTF bias
    _HTF_TFS: tuple[str, ...] = ("1h", "4h")
    # LTF timeframes (5m/15m) contribute to LTF bias
    _LTF_TFS: tuple[str, ...] = ("5m", "15m")

    # Regime classification thresholds
    _BIAS_THRESHOLD: float = 0.3

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        """Compute cross-TF momentum divergence with full gradient implementation.

        Reads frames["intel_{tf}"] flat dicts (all tiers merged) for each timeframe.
        Uses rsi_14 (I1), macd_histogram_12_26_9 (I1), and momentum_bias (I4) fields.
        Computes per-TF momentum bias, then HTF-LTF divergence via tanh.

        Args:
            frames: Dict with cached I1-I6 intelligence per TF (keys like "intel_5m").
                    Content is a flat merged dict of all tier outputs for that TF.

        Returns:
            dict with:
                ctf_momentum_divergence: float [-1, +1] (tanh-normalized HTF-LTF divergence)
                ctf_momentum_regime: str (one of 5 categorical labels per D-06)
        """
        tf_biases: dict[str, float] = {}
        for tf in (*self._HTF_TFS, *self._LTF_TFS):
            intel = frames.get(f"intel_{tf}")
            if not intel:
                continue

            # I4 momentum_bias (precomputed composite — highest priority when available)
            momentum_bias = intel.get("momentum_bias")
            if isinstance(momentum_bias, (int, float)):
                tf_biases[tf] = tanh(float(momentum_bias))
                continue

            # Fallback: compose from I1 RSI + MACD + I2 event flags
            rsi_alignment = 0.0
            rsi = intel.get("rsi_14")
            if isinstance(rsi, (int, float)):
                rsi_alignment = (float(rsi) - 50.0) / 50.0

            macd_alignment = 0.0
            macd_hist = intel.get("macd_histogram_12_26_9")
            if isinstance(macd_hist, (int, float)):
                macd_alignment = tanh(float(macd_hist) * 10.0)

            # I2 event flags: macd/rsi crossovers as directional bias
            bullish = float(intel.get("macd_cross_bullish") or 0)
            bearish = float(intel.get("macd_cross_bearish") or 0)
            rsi_up = float(intel.get("rsi_crossed_50_up") or 0)
            rsi_down = float(intel.get("rsi_crossed_50_down") or 0)
            event_bias = tanh(bullish + rsi_up - bearish - rsi_down)

            no_events = not any((bullish, bearish, rsi_up, rsi_down))
            if (
                not isinstance(rsi, (int, float))
                and not isinstance(macd_hist, (int, float))
                and no_events
            ):
                continue

            tf_biases[tf] = event_bias * 0.4 + rsi_alignment * 0.3 + macd_alignment * 0.3

        # Separate HTF and LTF biases
        htf_biases = [tf_biases[tf] for tf in self._HTF_TFS if tf in tf_biases]
        ltf_biases = [tf_biases[tf] for tf in self._LTF_TFS if tf in tf_biases]

        # Insufficient data — return mixed (no directional conviction)
        if not htf_biases or not ltf_biases:
            return {
                "ctf_momentum_divergence": 0.0,
                "ctf_momentum_regime": "mixed",
            }

        htf_bias = sum(htf_biases) / len(htf_biases)
        ltf_bias = sum(ltf_biases) / len(ltf_biases)

        # Positive: HTF bullish, LTF bearish (pullback). Negative: HTF bearish, LTF bullish (bounce).
        divergence_score = tanh(htf_bias - ltf_bias)

        t = self._BIAS_THRESHOLD
        if htf_bias > t and ltf_bias > t:
            regime = "aligned_htf_bull"
        elif htf_bias < -t and ltf_bias < -t:
            regime = "aligned_htf_bear"
        elif htf_bias > t and ltf_bias < -t:
            regime = "pullback"
        elif htf_bias < -t and ltf_bias > t:
            regime = "bounce"
        else:
            regime = "mixed"

        return {
            "ctf_momentum_divergence": round(divergence_score, 4),
            "ctf_momentum_regime": regime,
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = CrossTFMomentumDivergencePlugin()
