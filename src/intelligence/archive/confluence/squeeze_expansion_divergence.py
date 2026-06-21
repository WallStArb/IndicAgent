"""Squeeze/Expansion Divergence Plugin.

Detects volatility squeeze/expansion divergence between HTF and LTF.
Uses I4 ATR and shannon_entropy to classify volatility regimes.

Gradient scoring (per D-06 and CONTEXT.md):
- Uses np.tanh() for soft saturation (NOT binary step functions)
- ATR and shannon_entropy combined as volatility score per TF
- Divergence = HTF_vol - LTF_vol, normalized via tanh

Outputs:
    ctf_volatility_divergence: float [-1, +1]
        - Positive: HTF expanding, LTF squeezing (coiling into expansion)
        - Negative: HTF squeezing, LTF expanding (exhaustion signal)
        - Near 0: Both TFs in same volatility regime
    ctf_volatility_regime: str
        - both_squeezing: Low volatility on both TFs
        - both_expanding: High volatility on both TFs
        - squeeze_htf_expand_ltf: HTF squeeze, LTF expansion (exhaustion)
        - squeeze_ltf_expand_htf: LTF squeeze, HTF expansion (coiling)
        - mixed: Unclear volatility regime
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import tanh
from typing import Any

from src.intelligence.trading.atr_utils import get_atr

from ..plugins import InputSpec


@dataclass
class SqueezeExpansionDivergencePlugin:
    """Squeeze/expansion volatility divergence detector.

    Follows the CrossTimeframeConfluencePlugin pattern: reads cached I4
    context from frames dict and computes HTF-LTF volatility divergence using
    np.tanh() gradient scoring (not binary step functions).

    Per D-06: outputs ctf_volatility_divergence [-1, +1] and ctf_volatility_regime (categorical)
    Per CONTEXT.md: combines ATR + shannon_entropy for robust volatility classification
    """

    name: str = "i6_SqueezeExpansionDivergence"
    outputs: frozenset[str] = frozenset(
        {
            "ctf_volatility_divergence",
            "ctf_volatility_regime",
        }
    )
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"confluence"})
    inputs: list[InputSpec] = field(default_factory=list)
    _state: dict = field(default_factory=dict)

    # HTF timeframes (1h+) contribute to HTF volatility
    _HTF_TFS: tuple[str, ...] = ("1h", "4h")
    # LTF timeframes (5m/15m) contribute to LTF volatility
    _LTF_TFS: tuple[str, ...] = ("5m", "15m")

    # Regime classification threshold — scores above/below indicate expansion/squeeze
    _VOL_THRESHOLD: float = 0.3

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        """Compute volatility squeeze/expansion divergence.

        Reads frames["intel_{tf}"] flat dicts (all tiers merged) for each timeframe.
        Uses atr_14 (I1) and shannon_entropy (I4) fields.

        Low ATR + low entropy = squeeze (-1), high ATR + high entropy = expansion (+1)
        The normalization uses tanh with typical market parameters:
        - ATR ref: 0.02 (2% typical; scale with tanh(atr/ref - 1))
        - Entropy ref: 0.7 nats (typical mixed market; scale with tanh(entropy/ref - 1))

        Args:
            frames: Dict with cached I1-I6 intelligence per TF (keys like "intel_5m").
                    Content is a flat merged dict of all tier outputs for that TF.

        Returns:
            dict with:
                ctf_volatility_divergence: float [-1, +1] (tanh-normalized HTF-LTF divergence)
                ctf_volatility_regime: str (one of 5 categorical labels)
        """
        vol_scores: dict[str, float] = {}

        for tf in (*self._HTF_TFS, *self._LTF_TFS):
            intel = frames.get(f"intel_{tf}")
            if not intel:
                continue

            atr = get_atr(intel)
            entropy = intel.get("shannon_entropy")

            atr_valid = atr is not None
            entropy_valid = isinstance(entropy, (int, float)) and float(entropy) > 0
            if not atr_valid and not entropy_valid:
                continue

            # ATR ref 0.02 (2% typical daily range): below = squeeze, above = expansion
            atr_score = tanh(float(atr) / 0.02 - 1.0) if atr_valid else 0.0
            # Entropy ref 0.7 nats (typical mixed market): below = low-entropy squeeze
            entropy_score = tanh(float(entropy) / 0.7 - 1.0) if entropy_valid else 0.0

            if atr_valid and entropy_valid:
                vol_score = (atr_score + entropy_score) / 2.0
            elif atr_valid:
                vol_score = atr_score
            else:
                vol_score = entropy_score

            vol_scores[tf] = vol_score

        if not vol_scores:
            return {
                "ctf_volatility_divergence": 0.0,
                "ctf_volatility_regime": "mixed",
            }

        # Separate HTF and LTF scores
        htf_scores = [vol_scores[tf] for tf in self._HTF_TFS if tf in vol_scores]
        ltf_scores = [vol_scores[tf] for tf in self._LTF_TFS if tf in vol_scores]

        if not htf_scores or not ltf_scores:
            return {
                "ctf_volatility_divergence": 0.0,
                "ctf_volatility_regime": "mixed",
            }

        htf_avg = sum(htf_scores) / len(htf_scores)
        ltf_avg = sum(ltf_scores) / len(ltf_scores)

        # Positive: HTF expanding, LTF squeezing (coiling). Negative: HTF squeezing, LTF expanding (exhaustion).
        divergence = tanh(htf_avg - ltf_avg)

        # Regime classification — 5 categorical labels
        t = self._VOL_THRESHOLD
        if htf_avg < -t and ltf_avg < -t:
            regime = "both_squeezing"
        elif htf_avg > t and ltf_avg > t:
            regime = "both_expanding"
        elif htf_avg < -t and ltf_avg > t:
            regime = "squeeze_htf_expand_ltf"
        elif htf_avg > t and ltf_avg < -t:
            regime = "squeeze_ltf_expand_htf"
        else:
            regime = "mixed"

        return {
            "ctf_volatility_divergence": round(divergence, 4),
            "ctf_volatility_regime": regime,
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = SqueezeExpansionDivergencePlugin()
