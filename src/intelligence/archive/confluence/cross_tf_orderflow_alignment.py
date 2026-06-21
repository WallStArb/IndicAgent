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
from math import tanh
from typing import Any

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
    _OFI_NORM: float = 1000.0  # Typical OFI magnitude per bar
    _CVD_NORM: float = 5000.0  # Typical CVD magnitude per bar

    # Majority thresholds for regime classification
    _STRONG_THRESHOLD: float = 0.3

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        """Compute order flow alignment across timeframes.

        Reads frames["intel_{tf}"] flat dicts (all tiers merged) for each timeframe.
        Uses ofi_ewma_5 (I1 OFI plugin) and cvd (I1 CVD plugin) fields.

        Args:
            frames: Dict with cached I1-I6 intelligence per TF (keys like "intel_5m").
                    Content is a flat merged dict of all tier outputs for that TF.

        Returns:
            dict with:
                ctf_orderflow_alignment: float [-1, +1] (tanh-normalized alignment)
                ctf_orderflow_regime: str (one of 5 categorical labels)
        """
        of_scores: dict[str, float] = {}

        for tf in self._ALL_TFS:
            intel = frames.get(f"intel_{tf}")
            if not intel:
                continue

            ofi = intel.get("ofi_ewma_5")
            cvd = intel.get("cvd")

            ofi_valid = isinstance(ofi, (int, float))
            cvd_valid = isinstance(cvd, (int, float))
            if not ofi_valid and not cvd_valid:
                continue

            ofi_score = tanh(float(ofi) / self._OFI_NORM) if ofi_valid else 0.0
            cvd_score = tanh(float(cvd) / self._CVD_NORM) if cvd_valid else 0.0

            if ofi_valid and cvd_valid:
                of_score = (ofi_score + cvd_score) / 2.0
            elif ofi_valid:
                of_score = ofi_score
            else:
                of_score = cvd_score

            of_scores[tf] = of_score

        if not of_scores:
            return {
                "ctf_orderflow_alignment": 0.0,
                "ctf_orderflow_regime": "missing_data",
            }

        avg_of = sum(of_scores.values()) / len(of_scores)
        alignment = tanh(avg_of * 2.0)

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

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = CrossTFOrderFlowAlignmentPlugin()
