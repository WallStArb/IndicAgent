"""System-wide confidence contract for I7 trading plugins.

Per D-12/D-13/D-14: All I7 plugins route their final confidence value through
compose_confidence(). Zero inline min()/max() clamping in plugin bodies.

The contract: ceiling only — [0.0, CONF_CEIL].
Rounding: 4 decimal places for consistent ML feature representation.
The publication floor (0.12) is enforced exclusively by apply_quality_gate().

capture_signal_features() captures I4 macro context + I6 ctf_* scores + exhaustion state into
signal["features_snapshot"] for ML training — zero confidence modification.
Shadow dict has 30 keys: 2 metadata (profile, existing_confidence) + 8 I6 CTF base+momentum
(ctf_score, ctf_trend_alignment, ctf_structure_alignment, ctf_regime_agreement,
ctf_fvg_alignment, ctf_ob_alignment, ctf_momentum_divergence, ctf_momentum_regime) +
8 I6 CTF extended (ctf_sr_confluence, ctf_sr_regime, ctf_hmm_regime_agreement,
ctf_hmm_regime_label, ctf_volatility_divergence, ctf_volatility_regime,
ctf_orderflow_alignment, ctf_orderflow_regime) + 9 I4 macro context (vix_level, vix_z,
eq_spread_z, eq_pairs_confirming, ftq_score, ftq_regime, yield_curve_slope,
yield_curve_regime, corr_z) + 3 exhaustion fields.
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


def get_min_regime_weight() -> float:
    if _config_service is not None:
        return _config_service.get_sync("threshold.global.min_regime_weight", MIN_REGIME_WEIGHT)
    return MIN_REGIME_WEIGHT


def get_min_ctf_score() -> float:
    if _config_service is not None:
        return _config_service.get_sync("threshold.global.min_ctf_score", MIN_CTF_SCORE)
    return MIN_CTF_SCORE


def _validate_weights_sum(weights: dict[str, float], plugin: str, tol: float = 1e-6) -> None:
    """Validate that confidence weights sum to 1.0 within floating-point tolerance.

    Raises ValueError (not AssertionError — asserts disabled by -O) if the
    invariant is violated. Called at prewarm/init time so bad DB seeds or
    bad operator writes fail fast at daemon startup, before any signal fires.

    Args:
        weights: Dict of weight name to value (e.g. {'roc': 0.40, 'vol': 0.35, ...}).
        plugin:  Human-readable plugin name for error messages.
        tol:     Floating-point tolerance. Default 1e-6 handles float repr of 0.40+0.35+0.25.
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
    return round(clamp(raw, 0.0, CONF_CEIL), 4)


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


def capture_signal_features(
    features: dict[str, Any],
    direction: int,
    profile_name: str,
    existing_confidence: float,
) -> dict[str, Any]:
    """Capture signal features snapshot for shadow logging.

    Returns a standardized dict stored as signal["features_snapshot"] in i7 JSONB.
    Zero confidence modification — pure data capture for Phase 49 ML training.
    All I7 plugins emit the same shadow structure regardless of family.

    Args:
        features:            frames["features"] dict from I7 plugin compute_full().
        direction:           +1 long, -1 short (reserved for future directional capture).
        profile_name:        Family name — one of FAMILY_PROFILES keys.
        existing_confidence: The plugin's current confidence value (unchanged by this call).

    Returns:
        Shadow dict with 30 keys: 9 I4 macro context + 16 I6 CTF (8 base+momentum, 8 extended)
        + 3 exhaustion fields + 2 metadata.
    """
    shadow: dict[str, Any] = {
        "profile": profile_name,
        "existing_confidence": round(existing_confidence, 4),
        # Null-preserving extraction: None = field absent (cold-start), 0.0 = genuine neutral.
        # Never use `or 0.0` fallbacks here — conflates cold-start with neutral (ML bias).
        "ctf_score": _nullable_float(features, "ctf_score"),
        "ctf_trend_alignment": _nullable_float(features, "ctf_trend_alignment"),
        "ctf_structure_alignment": _nullable_float(features, "ctf_structure_alignment"),
        "ctf_regime_agreement": _nullable_float(features, "ctf_regime_agreement"),
        "ctf_fvg_alignment": _nullable_float(features, "ctf_fvg_alignment"),
        "ctf_ob_alignment": _nullable_float(features, "ctf_ob_alignment"),
        # I4 macro context (Phase 46.1): VIX regime + EQ_INDEX sector rotation.
        # Per D-06: None means data unavailable — never substitute 0.0 (valid z-score value).
        "vix_level": _nullable_float(features, "vix_level"),
        "vix_z": _nullable_float(features, "vix_z"),
        "eq_spread_z": _nullable_float(features, "eq_spread_z"),
        "eq_pairs_confirming": _nullable_float(features, "eq_pairs_confirming"),
        # I4 macro regime context (Phase 121 Wave 2 / D-10 MacroContextPlugin):
        # flight-to-quality, yield curve, stock-bond corr.
        # Per D-06: None means data unavailable — never substitute 0.0.
        "ftq_score": _nullable_float(features, "ftq_score"),
        "ftq_regime": features.get("ftq_regime"),  # str | None — not a float field
        "yield_curve_slope": _nullable_float(features, "yield_curve_slope"),
        "yield_curve_regime": features.get("yield_curve_regime"),  # str | None — not a float field
        "corr_z": _nullable_float(features, "corr_z"),
    }
    # Cross-TF momentum divergence fields (Plan 64-01, D-13, D-14)
    # Captured as-is: divergence is float | None, regime is str | None
    ctf_mom_div = features.get("ctf_momentum_divergence")
    shadow["ctf_momentum_divergence"] = (
        float(ctf_mom_div) if isinstance(ctf_mom_div, (int, float)) else None
    )
    shadow["ctf_momentum_regime"] = features.get("ctf_momentum_regime")  # str | None

    # Cross-TF S/R confluence (Plan 64-02, D-13, D-14)
    ctf_sr = features.get("ctf_sr_confluence")
    shadow["ctf_sr_confluence"] = float(ctf_sr) if isinstance(ctf_sr, (int, float)) else None
    shadow["ctf_sr_regime"] = features.get("ctf_sr_regime")  # str | None

    # Cross-TF HMM regime agreement (Plan 64-02, D-13, D-14)
    ctf_hmm = features.get("ctf_hmm_regime_agreement")
    shadow["ctf_hmm_regime_agreement"] = (
        float(ctf_hmm) if isinstance(ctf_hmm, (int, float)) else None
    )
    shadow["ctf_hmm_regime_label"] = features.get("ctf_hmm_regime_label")  # str | None

    # Cross-TF volatility divergence (Plan 64-02, D-13, D-14)
    ctf_vol = features.get("ctf_volatility_divergence")
    shadow["ctf_volatility_divergence"] = (
        float(ctf_vol) if isinstance(ctf_vol, (int, float)) else None
    )
    shadow["ctf_volatility_regime"] = features.get("ctf_volatility_regime")  # str | None

    # Cross-TF order flow alignment (Plan 64-02, D-13, D-14)
    ctf_ofa = features.get("ctf_orderflow_alignment")
    shadow["ctf_orderflow_alignment"] = (
        float(ctf_ofa) if isinstance(ctf_ofa, (int, float)) else None
    )
    shadow["ctf_orderflow_regime"] = features.get("ctf_orderflow_regime")  # str | None

    # Exhaustion fields — omit for plugins that ARE the exhaustion detector (D-09)
    # Null-preserving: None = absent (cold-start), 0.0 = genuine neutral
    if profile_name != "exempt_exhaustion":
        shadow["exhaustion_score"] = _nullable_float(features, "exhaustion_score")
        shadow["exhaustion_side"] = features.get("exhaustion_side")
        _exh_bars_raw = features.get("exhaustion_bars")
        shadow["exhaustion_bars"] = float(_exh_bars_raw) if _exh_bars_raw is not None else None
    else:
        shadow["exhaustion_score"] = None
        shadow["exhaustion_side"] = None
        shadow["exhaustion_bars"] = None
    return shadow
