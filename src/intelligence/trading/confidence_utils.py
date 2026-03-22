"""System-wide confidence contract for I7 trading plugins.

Per D-12/D-13/D-14: All I7 plugins route their final confidence value through
compose_confidence(). Zero inline min()/max() clamping in plugin bodies.

The contract: [CONF_FLOOR, CONF_CEIL] = [0.10, 0.95].
Rounding: 4 decimal places for consistent ML feature representation.

capture_confluence_features() captures I6 ctf_* scores and exhaustion state into
signal["_shadow"] for ML training — zero confidence modification.
ConfluenceWeightProfile holds placeholder weights (all 0.0) for each plugin family.
Phase 49 fills non-zero values once XGBoost/logistic training produces learned weights.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CONF_FLOOR: float = 0.10
"""Minimum allowed confidence for any I7 signal."""

CONF_CEIL: float = 0.95
"""Maximum allowed confidence for any I7 signal."""


def compose_confidence(raw: float) -> float:
    """Clamp raw confidence to the system contract [CONF_FLOOR, CONF_CEIL].

    All I7 plugins must route through this function before emitting a signal.
    This eliminates inline clamping patterns (min(0.95, max(0.10, x))) and
    ensures the system-wide contract is enforced at a single point.

    Args:
        raw: Raw confidence value (any float, including out-of-range).

    Returns:
        Float in [CONF_FLOOR, CONF_CEIL] rounded to 4 decimal places.
    """
    return round(max(CONF_FLOOR, min(CONF_CEIL, raw)), 4)


@dataclass(frozen=True)
class ConfluenceWeightProfile:
    """Weight profile for confluence/exhaustion features — Phase 49 fills non-zero values.

    All weights are 0.0 placeholders in Phase 45. Phase 49 replaces these with
    per-plugin-family learned weights from XGBoost/logistic training on
    intelligence_features + signal_ledger.

    Each I7 plugin declares its family name, which selects the appropriate profile
    from FAMILY_PROFILES. The profile name is also captured in the shadow dict for
    Phase 49 slicing.
    """

    name: str
    w_ctf_score: float = 0.0
    w_ctf_trend_alignment: float = 0.0
    w_ctf_structure_alignment: float = 0.0
    w_ctf_regime_agreement: float = 0.0
    w_ctf_fvg_alignment: float = 0.0
    w_ctf_ob_alignment: float = 0.0
    w_exhaustion: float = 0.0


FAMILY_PROFILES: dict[str, ConfluenceWeightProfile] = {
    "trend": ConfluenceWeightProfile(name="trend"),
    "mean_reversion": ConfluenceWeightProfile(name="mean_reversion"),
    "smc": ConfluenceWeightProfile(name="smc"),
    "microstructure": ConfluenceWeightProfile(name="microstructure"),
    "session": ConfluenceWeightProfile(name="session"),
    "exempt_exhaustion": ConfluenceWeightProfile(name="exempt_exhaustion"),
}
"""Six plugin families for Phase 49 weight learning.

Family assignments (D-08):
- "trend"          → TrendFollowing, MTFAlignment, MomentumBreakout, SqueezeExpansion,
                     VCP, SecondLegContinuation, RegimeTransition
- "mean_reversion" → MeanReversion, VWAPDeviation, VWAPReclaim, AnchoredVWAPReversion,
                     POCRejection, HVNRejection
- "smc"            → FVGFill, CHoCHReversal, SupplyDemandSetup, LiquiditySweepReclaim,
                     LiquidityHunt, PatternCompletion, LVNBreakout
- "microstructure" → OFIContinuation, OFIDivergence, OFISpike, CVDDivergence, CVDSpike,
                     DivergenceStack, DualDivergence, CrossAssetDivergence
- "session"        → SessionExtremesSetup, FailedBreakout, ORB15, ORB30, PrevDayLevelTest,
                     GapAnalysisSetup, CandlestickPatternSetup
- "exempt_exhaustion" → DeltaExhaustion (IS the exhaustion detector — omit exhaustion fields)
"""


def capture_confluence_features(
    features: dict[str, Any],
    direction: int,
    profile_name: str,
    existing_confidence: float,
) -> dict[str, Any]:
    """Capture confluence + exhaustion feature snapshot for shadow logging.

    Returns a standardized dict stored as signal["_shadow"] in i7 JSONB.
    No confidence modification — pure data capture for Phase 49 ML.

    Zero confidence modification — pure data capture for Phase 49 ML training.
    All I7 plugins emit the same shadow structure regardless of family.

    Args:
        features:            frames["features"] dict from I7 plugin compute_full().
        direction:           +1 long, -1 short (reserved for future directional capture).
        profile_name:        Family name — one of FAMILY_PROFILES keys.
        existing_confidence: The plugin's current confidence value (unchanged by this call).

    Returns:
        Shadow dict with 11 keys matching D-07 schema.
    """
    shadow: dict[str, Any] = {
        "profile": profile_name,
        "existing_confidence": round(existing_confidence, 4),
        "ctf_score": float(features.get("ctf_score", 0.0)),
        "ctf_trend_alignment": float(features.get("ctf_trend_alignment", 0.0)),
        "ctf_structure_alignment": float(features.get("ctf_structure_alignment", 0.0)),
        "ctf_regime_agreement": float(features.get("ctf_regime_agreement", 0.0)),
        "ctf_fvg_alignment": float(features.get("ctf_fvg_alignment", 0.0)),
        "ctf_ob_alignment": float(features.get("ctf_ob_alignment", 0.0)),
    }
    # Exhaustion fields — omit for plugins that ARE the exhaustion detector (D-09)
    if profile_name != "exempt_exhaustion":
        shadow["exhaustion_score"] = float(features.get("exhaustion_score", 0.0))
        shadow["exhaustion_side"] = features.get("exhaustion_side", "none")
        shadow["exhaustion_bars"] = float(features.get("exhaustion_bars", 0.0))
    else:
        shadow["exhaustion_score"] = None
        shadow["exhaustion_side"] = None
        shadow["exhaustion_bars"] = None
    return shadow
