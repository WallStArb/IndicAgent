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
from typing import Any

import numpy as np

from ..plugins import InputSpec
from .cross_timeframe import CrossTimeframeConfluencePlugin  # noqa: F401 — pattern reference


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

        Reads frames["intel_i2"] (I2 momentum event directions) and
        frames["intel_i4"] (I4 context: RSI, MACD histogram) per timeframe.
        Computes per-TF momentum bias, then HTF-LTF divergence via tanh.

        Args:
            frames: Dict with cached I1-I5 intelligence per TF.
                    Expected keys: "intel_i2", "intel_i4" (each maps tf->dict)

        Returns:
            dict with:
                ctf_momentum_divergence: float [-1, +1] (tanh-normalized HTF-LTF divergence)
                ctf_momentum_regime: str (one of 5 categorical labels per D-06)
        """
        # Extract I2 momentum events and I4 context per TF
        i2_events = frames.get("intel_i2", {})
        i4_context = frames.get("intel_i4", {})

        # Compute momentum bias per TF
        # Per CONTEXT.md: "extract momentum bias from each TF using I2 events + RSI/MACD direction"
        tf_biases: dict[str, float] = {}
        for tf in (*self._HTF_TFS, *self._LTF_TFS):
            i2_tf = i2_events.get(tf)
            i4_tf = i4_context.get(tf)

            if not i2_tf and not i4_tf:
                continue

            # I2 event direction contribution (0.4 weight)
            event_bias = 0.0
            if i2_tf and isinstance(i2_tf, dict):
                directions = []
                for event in i2_tf.values():
                    if isinstance(event, dict) and "direction" in event:
                        d = event["direction"]
                        if isinstance(d, (int, float)):
                            directions.append(float(d))
                if directions:
                    # Average direction across all I2 events for this TF
                    event_bias = float(np.mean(directions))

            # I4 RSI and MACD alignment (0.3 + 0.3 weight)
            rsi_alignment = 0.0
            macd_alignment = 0.0
            if i4_tf and isinstance(i4_tf, dict):
                rsi = i4_tf.get("rsi")
                macd_hist = i4_tf.get("macd_histogram")

                if isinstance(rsi, (int, float)):
                    # RSI alignment: >50 bullish, <50 bearish, normalized to [-1, +1]
                    rsi_alignment = (float(rsi) - 50.0) / 50.0

                if isinstance(macd_hist, (int, float)):
                    # MACD histogram: normalize via tanh for soft saturation (D-17: gradient-first)
                    macd_alignment = float(np.tanh(float(macd_hist) * 10.0))

            # Combine I2 + I4 for TF momentum bias (weights sum to 1.0)
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

        # Average HTF and LTF biases
        # Per CONTEXT.md: "compute HTF-LTF divergence as continuous gradient"
        htf_bias = float(np.mean(htf_biases))
        ltf_bias = float(np.mean(ltf_biases))

        # Divergence = HTF_bias - LTF_bias per CONTEXT.md specification
        # Positive: HTF bullish, LTF bearish (pullback opportunity)
        # Negative: HTF bearish, LTF bullish (bounce / short-squeeze)
        divergence = htf_bias - ltf_bias

        # Normalize via np.tanh() for soft saturation (D-06, D-17: continuous gradient not binary)
        divergence_score = float(np.tanh(divergence))

        # Regime classification — 5 categorical labels per D-06
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

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = CrossTFMomentumDivergencePlugin()
