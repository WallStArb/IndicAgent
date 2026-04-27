"""Cross-TF Order Flow Alignment Plugin.

Detects order flow (OFI/CVD) alignment across timeframes.
Uses I1 OFI and CVD to measure buying/selling pressure agreement.

Gradient scoring (per D-06 and CONTEXT.md):
- Uses np.tanh() for soft saturation (NOT binary step functions)
- OFI and CVD combined as order flow score per TF
- Alignment = tanh(avg_of * 2.0) for sharpened gradient

Outputs:
    ctf_orderflow_alignment: float [-1, +1]
        - Positive: All TFs showing buying pressure
        - Negative: All TFs showing selling pressure
        - Near 0: Mixed order flow
    ctf_orderflow_regime: str
        - aligned_bull: All TFs bullish OFI/CVD (all > +0.3)
        - aligned_bear: All TFs bearish OFI/CVD (all < -0.3)
        - mostly_bull: Majority bullish
        - mostly_bear: Majority bearish
        - divergent: Mixed bullish/bearish across TFs
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class CrossTFOrderFlowAlignmentPlugin:
    """Cross-TF order flow alignment detector.

    Follows the CrossTimeframeConfluencePlugin pattern: reads cached I1
    features from frames dict and computes OFI/CVD alignment across TFs using
    np.tanh() gradient scoring (not binary step functions).

    Per D-06: outputs ctf_orderflow_alignment [-1, +1] and ctf_orderflow_regime (categorical)
    Per CONTEXT.md: combines OFI + CVD for robust order flow direction detection
    NOTE: "missing_data" regime is returned only when NO order flow data is available.
    """

    name: str = "i6_CrossTFOrderFlowAlignment"
    outputs: frozenset[str] = frozenset(
        {
            "ctf_orderflow_alignment",
            "ctf_orderflow_regime",
        }
    )
    min_lookback: int = 10
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"confluence"})
    inputs: list[InputSpec] = field(default_factory=list)
    _state: dict = field(default_factory=dict)

    # All timeframes to check order flow alignment across
    _ALL_TFS: tuple[str, ...] = ("5m", "15m", "1h", "4h")

    # Normalization constants for OFI and CVD (typical magnitudes)
    _OFI_NORM: float = 1000.0   # Typical OFI magnitude per bar
    _CVD_NORM: float = 5000.0   # Typical CVD magnitude per bar

    # Majority thresholds for regime classification
    _STRONG_THRESHOLD: float = 0.3

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        """Compute order flow alignment across timeframes.

        Reads frames["intel_i1"] (I1 features: ofi, cvd) per timeframe.
        Normalizes via tanh, averages HTF+LTF, then computes alignment score.

        Args:
            frames: Dict with cached I1-I5 intelligence per TF.
                    Expected keys: "intel_i1" (maps tf->dict with ofi, cvd fields)

        Returns:
            dict with:
                ctf_orderflow_alignment: float [-1, +1] (tanh-normalized alignment)
                ctf_orderflow_regime: str (one of 5 categorical labels)
        """
        i1_events = frames.get("intel_i1", {})

        of_scores: dict[str, float] = {}

        for tf in self._ALL_TFS:
            if tf not in i1_events:
                continue

            i1_tf = i1_events[tf]
            if not isinstance(i1_tf, dict):
                continue

            ofi = i1_tf.get("ofi")
            cvd = i1_tf.get("cvd")

            # Need at least one valid order flow indicator
            if not isinstance(ofi, (int, float)) and not isinstance(cvd, (int, float)):
                continue

            # Normalize OFI: positive = buying pressure, negative = selling
            # Use tanh(ofi / norm) for gradient score
            ofi_score = 0.0
            if isinstance(ofi, (int, float)):
                ofi_score = float(np.tanh(float(ofi) / self._OFI_NORM))

            # Normalize CVD: positive = net buying, negative = net selling
            cvd_score = 0.0
            if isinstance(cvd, (int, float)):
                cvd_score = float(np.tanh(float(cvd) / self._CVD_NORM))

            # Weighted combination: equal weight OFI and CVD
            if isinstance(ofi, (int, float)) and isinstance(cvd, (int, float)):
                of_score = (ofi_score + cvd_score) / 2.0
            elif isinstance(ofi, (int, float)):
                of_score = ofi_score
            else:
                of_score = cvd_score

            of_scores[tf] = of_score

        if not of_scores:
            return {
                "ctf_orderflow_alignment": 0.0,
                "ctf_orderflow_regime": "missing_data",
            }

        # Average order flow score across all available TFs
        avg_of = float(np.mean(list(of_scores.values())))

        # Alignment: how strongly do TFs agree on direction?
        # Multiply by 2.0 to sharpen gradient (D-17: continuous gradient)
        alignment = float(np.tanh(avg_of * 2.0))

        # Regime classification — 5 categorical labels
        t = self._STRONG_THRESHOLD
        if all(v > t for v in of_scores.values()):
            regime = "aligned_bull"
        elif all(v < -t for v in of_scores.values()):
            regime = "aligned_bear"
        elif avg_of > t:
            regime = "mostly_bull"
        elif avg_of < -t:
            regime = "mostly_bear"
        else:
            regime = "divergent"

        return {
            "ctf_orderflow_alignment": round(alignment, 4),
            "ctf_orderflow_regime": regime,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = CrossTFOrderFlowAlignmentPlugin()
