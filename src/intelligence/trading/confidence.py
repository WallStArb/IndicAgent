"""System-wide confidence contract for I7 trading plugins.

Per D-12/D-13/D-14: All I7 plugins route their final confidence value through
compose_confidence(). Zero inline min()/max() clamping in plugin bodies.

The contract: ceiling only — [0.0, CONF_CEIL].
Rounding: 4 decimal places for consistent ML feature representation.
The publication floor (0.12) is enforced exclusively by apply_quality_gate().

ConfluenceWeightProfile holds placeholder weights (all 0.0) for each plugin family.
Phase 49 fills non-zero values once XGBoost/logistic training produces learned weights.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.intelligence.utils.core import clamp

CONF_CEIL: float = 0.95
"""Maximum allowed confidence for any I7 signal."""

MIN_REGIME_WEIGHT: float = 0.30
"""Minimum HMM regime weight for the dual gate across all I7 plugins."""

MIN_CTF_SCORE: float = 0.25
"""Minimum absolute I6 CTF score for the dual gate across all I7 plugins."""

_config_service: Any | None = None


def set_config_service(config: Any) -> None:
    global _config_service
    _config_service = config


def _cfg(key: str, default: float) -> float:
    return _config_service.get_sync(key, default) if _config_service is not None else default


def get_min_regime_weight() -> float:
    return _cfg("threshold.global.min_regime_weight", MIN_REGIME_WEIGHT)


def get_min_ctf_score() -> float:
    return _cfg("threshold.global.min_ctf_score", MIN_CTF_SCORE)


def get_conf_ceil() -> float:
    return _cfg("threshold.global.conf_ceil", CONF_CEIL)


def _validate_weights_sum(weights: dict[str, float], plugin: str, tol: float = 1e-6) -> None:
    """Validate that confidence weights sum to 1.0 within floating-point tolerance.

    Raises ValueError (not AssertionError — asserts disabled by -O) if the
    invariant is violated. Called at prewarm/init time so bad DB seeds or
    bad operator writes fail fast at daemon startup, before any signal fires.

    Args:
        weights: Dict of weight name to value (e.g. {'roc': 0.40, 'vol': 0.35, ...}).
        plugin:  Human-readable plugin name for error messages.
        tol:     Floating-point tolerance. Default 1e-6 handles float repr of 0.40+0.35+0.25.
        tol:     Floating-point tolerance (default 1e-6 handles 0.40+0.35+0.25).
    """
    total = sum(weights.values())
    if abs(total - 1.0) > tol:
        raise ValueError(f"{plugin} weights sum to {total:.6f}, expected 1.0")


def clamp01(x: float) -> float:
    """Clamp x to [0.0, 1.0]. Use for per-factor scoring before weighted sums."""
    return clamp(x, 0.0, 1.0)


def _nullable_float(features: dict, key: str) -> float | None:
    """Null-preserving float extraction: None = key absent or null, 0.0 = genuine neutral.

    Never use `or 0.0` or `, 0.0` fallback for extrinsic CTF/exhaustion fields —
    that conflates cold-start (no data) with a genuine neutral reading (ML training bias).
    """
    _raw = features.get(key)
    if _raw is None:
        return None
    return float(_raw)


def rel_volume_score(features: dict[str, Any], fallback: float = 0.3) -> float:
    """Normalize rel_volume into a [0, 1] confidence factor.

    Maps rel_volume=1.0 → 0.0 (no expansion), rel_volume=2.5 → 1.0 (strong expansion).
    Returns fallback when rel_volume is absent.
    """
    rel_vol = features.get("rel_volume")
    if rel_vol is None:
        return fallback
    return clamp01((float(rel_vol) - 1.0) / 1.5)


def compose_confidence(raw: float) -> float:
    """Clamp raw confidence to the system ceiling [0.0, CONF_CEIL].

    All I7 plugins must route through this function before emitting a signal.
    This enforces the system-wide ceiling at a single point.

    The publication floor (min_confidence=0.12) is applied by apply_quality_gate()
    after isotonic calibration — not here. Enforcing a floor at construction time
    would corrupt pre_quality_confidence in ML training data.

    Args:
        raw: Raw confidence value (any float, including out-of-range).

    Returns:
        Float in [0.0, CONF_CEIL] rounded to 4 decimal places.
    """
    return round(clamp(raw, 0.0, get_conf_ceil()), 4)


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
