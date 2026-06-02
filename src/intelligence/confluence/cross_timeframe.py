from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from ..utils import clamp
from .confluence_alignment import (
    score_i2_events,
    score_pattern_confirmation,
    score_regime_agreement,
    score_structure_alignment,
    score_trend_alignment,
)
from .confluence_smc import score_fvg_alignment, score_ob_alignment, score_smc_bos_alignment
from .confluence_weights import (
    _TF_MINUTES,
    _proximity_decay,  # noqa: F401 — re-exported for any existing callers
    _sign,  # noqa: F401 — re-exported for any existing callers
    extract_trend_sign,
    get_recency_weight,
)


@dataclass
class CrossTimeframeConfluencePlugin:
    """I6 cross-timeframe confluence scoring.

    Reads cached intelligence from other timeframes (frames["intel_*"])
    and the current timeframe's features to produce a composite
    alignment score across multiple timeframes.
    """

    name: str = "i6_CrossTimeframeConfluence"
    outputs: frozenset[str] = frozenset(
        {
            "ctf_score",
            "ctf_trend_alignment",
            "ctf_structure_alignment",
            "ctf_regime_agreement",
            "ctf_timeframes_aligned",
            "ctf_highest_aligned_tf",
            "i6_smc_bos_alignment",
            "i6_fvg_tf_alignment",
            "i6_ob_tf_alignment",
            "i6_i2_event_score",
            # Aliases for i6_fvg/ob_tf_alignment using the ctf_* naming convention
            # consistent with all other ctf_* fields consumed by I7 plugins.
            "ctf_fvg_alignment",
            "ctf_ob_alignment",
        }
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"confluence"})
    inputs: list[InputSpec] = ()
    _state: dict = field(default_factory=dict)

    # ── Weights for the composite score ──
    W_TREND = 0.4
    W_STRUCTURE = 0.3
    W_REGIME = 0.2
    W_PATTERN = 0.1
    W_I2 = 0.1  # I2 event signals; total = 1.1 → renormalize by dividing by 1.1

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        # Merge all tier outputs for helper functions that need cross-tier field access
        # This plugin (I6) runs after all prior waves so all tier keys are available
        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
        }
        # Inject close from DataFrame for confluence_smc helpers (proximity decay)
        df = frames.get("main")
        if df is not None and len(df) > 0 and "close" not in features:
            features["close"] = float(df["close"].iloc[-1])
        current_tf = frames.get("timeframe", "")

        # Collect available cross-TF intelligence dicts
        other_intel: dict[str, dict[str, Any]] = {}
        for key, val in frames.items():
            if key.startswith("intel_") and isinstance(val, dict):
                tf = key[6:]  # "intel_5m" → "5m"
                other_intel[tf] = val

        if not other_intel:
            return {}

        # Build recency weights: stale intel contributes less
        weights = {tf: get_recency_weight(frames, tf) for tf in other_intel}

        # Current timeframe direction (from I3/I4/SMC outputs in features)
        cur_trend = extract_trend_sign(features)

        trend_alignment = score_trend_alignment(cur_trend, other_intel, weights)
        structure_alignment = score_structure_alignment(features, other_intel, weights)
        regime_agreement = score_regime_agreement(features, other_intel, weights)
        pattern_confirmation = score_pattern_confirmation(features, other_intel)
        bos_alignment = score_smc_bos_alignment(features, other_intel, weights)
        fvg_score, fvg_tf_contribs = score_fvg_alignment(
            features, other_intel, current_tf, cur_trend
        )
        ob_score, ob_tf_contribs = score_ob_alignment(features, other_intel, current_tf, cur_trend)
        i2_score = score_i2_events(features)

        # Weighted composite: positive = bullish confluence, negative = bearish
        # Weights sum to 1.1 (W_I2 added); divide by 1.1 to normalize to [-1, 1]
        raw = (
            self.W_TREND * trend_alignment
            + self.W_STRUCTURE * structure_alignment
            + self.W_REGIME * regime_agreement
            + self.W_PATTERN * pattern_confirmation
            + self.W_I2 * i2_score
        ) / 1.1
        ctf_score = clamp(raw)

        # Count how many other timeframes agree with current direction
        aligned_count = 0
        highest_aligned_minutes = 0.0
        for tf, intel in other_intel.items():
            other_sign = extract_trend_sign(intel)
            if cur_trend != 0 and other_sign == cur_trend:
                aligned_count += 1
                tf_min = _TF_MINUTES.get(tf, 0)
                if tf_min > highest_aligned_minutes:
                    highest_aligned_minutes = float(tf_min)

        return {
            "ctf_score": round(ctf_score, 4),
            "ctf_trend_alignment": round(trend_alignment, 4),
            "ctf_structure_alignment": round(structure_alignment, 4),
            "ctf_regime_agreement": round(regime_agreement, 4),
            "ctf_timeframes_aligned": float(aligned_count),
            "ctf_highest_aligned_tf": highest_aligned_minutes,
            "i6_smc_bos_alignment": round(bos_alignment, 4),
            "i6_fvg_tf_alignment": fvg_score,
            "i6_ob_tf_alignment": ob_score,
            "i6_i2_event_score": round(i2_score, 4),
            # ctf_fvg/ob_alignment alias i6_fvg/ob_tf_alignment; i6_* keys preserved for
            # backward compatibility with existing consumers of intelligence_features.
            "ctf_fvg_alignment": fvg_score,
            "ctf_ob_alignment": ob_score,
            # Per-TF FVG and OB contributions — Renaissance standard: every score is decomposable
            **{f"i6_fvg_tf_{tf}": v for tf, v in fvg_tf_contribs.items()},
            **{f"i6_ob_tf_{tf}": v for tf, v in ob_tf_contribs.items()},
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = CrossTimeframeConfluencePlugin()
