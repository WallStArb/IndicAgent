"""Cross-TF Regime Agreement Plugin.

Detects HMM regime agreement across timeframes.
Uses I4 hmm_regime to classify trending vs ranging agreement.

Gradient scoring (per D-06 and CONTEXT.md):
- Uses np.tanh() for soft saturation (NOT binary step functions)
- Trending regimes (hmm_regime 1/2) score +1, ranging (0) score -1
- Agreement = tanh(avg_regime * 2.0) for sharpened gradient

Outputs:
    ctf_hmm_regime_agreement: float [-1, +1]
        - Positive: All timeframes trending
        - Negative: All timeframes ranging
        - Near 0: Mixed regimes
    ctf_hmm_regime_label: str
        - all_trending: All TFs in trending regime (hmm_regime 1 or 2)
        - all_ranging: All TFs in ranging regime (hmm_regime 0)
        - mostly_trending: Majority trending
        - mostly_ranging: Majority ranging
        - mixed: Split decision
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import tanh
from typing import Any

from ..plugins import InputSpec


@dataclass
class CrossTFRegimeAgreementPlugin:
    """Cross-TF HMM regime agreement detector.

    Follows the CrossTimeframeConfluencePlugin pattern: reads cached I4
    context from frames dict and computes regime agreement across TFs using
    np.tanh() gradient scoring (not binary step functions).

    Per D-06: outputs ctf_hmm_regime_agreement [-1, +1] and ctf_hmm_regime_label (categorical)
    NOTE: Named ctf_hmm_regime_* to avoid conflict with existing ctf_regime_agreement
    float field (CrossTimeframeConfluencePlugin) in I6Confluence schema.
    """

    name: str = "i6_CrossTFRegimeAgreement"
    outputs: frozenset[str] = frozenset(
        {
            "ctf_hmm_regime_agreement",
            "ctf_hmm_regime_label",
        }
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"confluence"})
    inputs: list[InputSpec] = field(default_factory=list)
    _state: dict = field(default_factory=dict)

    # All timeframes to check regime agreement across
    _ALL_TFS: tuple[str, ...] = ("5m", "15m", "1h", "4h")

    # Majority thresholds for regime classification
    _MAJORITY_THRESHOLD: float = 0.3

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        """Compute HMM regime agreement across timeframes.

        Reads frames["intel_{tf}"] flat dicts (all tiers merged) for each timeframe.
        Uses hmm_regime from SMCContext (0=ranging, 1=trending-up, 2=trending-down).

        Args:
            frames: Dict with cached I1-I6 intelligence per TF (keys like "intel_5m").
                    Content is a flat merged dict of all tier outputs for that TF.

        Returns:
            dict with:
                ctf_hmm_regime_agreement: float [-1, +1] (tanh-normalized regime agreement)
                ctf_hmm_regime_label: str (one of 5 categorical labels)
        """
        regime_scores: dict[str, float] = {}

        for tf in self._ALL_TFS:
            intel = frames.get(f"intel_{tf}")
            if not intel:
                continue

            hmm_regime = intel.get("hmm_regime")  # SMCContext field (smc tier)
            if not isinstance(hmm_regime, (int, float)):
                continue

            # Trending (1 or 2) = +1.0, ranging (0) = -1.0
            if hmm_regime in (1, 2):
                regime_scores[tf] = 1.0
            elif hmm_regime == 0:
                regime_scores[tf] = -1.0
            else:
                regime_scores[tf] = 0.0

        if not regime_scores:
            return {
                "ctf_hmm_regime_agreement": 0.0,
                "ctf_hmm_regime_label": "mixed",
            }

        avg_regime = sum(regime_scores.values()) / len(regime_scores)
        agreement = tanh(avg_regime * 2.0)

        # Regime classification — 5 categorical labels
        if all(v > 0 for v in regime_scores.values()):
            label = "all_trending"
        elif all(v < 0 for v in regime_scores.values()):
            label = "all_ranging"
        elif avg_regime > self._MAJORITY_THRESHOLD:
            label = "mostly_trending"
        elif avg_regime < -self._MAJORITY_THRESHOLD:
            label = "mostly_ranging"
        else:
            label = "mixed"

        return {
            "ctf_hmm_regime_agreement": round(agreement, 4),
            "ctf_hmm_regime_label": label,
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = CrossTFRegimeAgreementPlugin()
