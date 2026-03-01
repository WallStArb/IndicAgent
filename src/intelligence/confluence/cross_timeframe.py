from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from ..utils import clamp, is_num

# Timeframe weight: higher timeframes carry more authority
_TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}


def _sign(x: float) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


@dataclass
class CrossTimeframeConfluencePlugin:
    """I6 cross-timeframe confluence scoring.

    Reads cached intelligence from other timeframes (frames["intel_*"])
    and the current timeframe's features to produce a composite
    alignment score across multiple timeframes.
    """

    name: str = "i6_CrossTimeframeConfluence"
    outputs: set[str] = frozenset(
        {
            "ctf_score",
            "ctf_trend_alignment",
            "ctf_structure_alignment",
            "ctf_regime_agreement",
            "ctf_timeframes_aligned",
            "ctf_highest_aligned_tf",
        }
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"confluence"})
    inputs: list[InputSpec] = ()
    _state: dict = field(default_factory=dict)

    # ── Weights for the composite score ──
    W_TREND = 0.4
    W_STRUCTURE = 0.3
    W_REGIME = 0.2
    W_PATTERN = 0.1

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}

        # Collect available cross-TF intelligence dicts
        other_intel: dict[str, dict[str, Any]] = {}
        for key, val in frames.items():
            if key.startswith("intel_") and isinstance(val, dict):
                tf = key[6:]  # "intel_5m" → "5m"
                other_intel[tf] = val

        if not other_intel:
            return {}

        # Current timeframe direction (from I3/I4/SMC outputs in features)
        cur_trend = self._extract_trend_sign(features)

        trend_alignment = self._score_trend_alignment(cur_trend, other_intel)
        structure_alignment = self._score_structure_alignment(features, other_intel)
        regime_agreement = self._score_regime_agreement(features, other_intel)
        pattern_confirmation = self._score_pattern_confirmation(features, other_intel)

        # Weighted composite: positive = bullish confluence, negative = bearish
        raw = (
            self.W_TREND * trend_alignment
            + self.W_STRUCTURE * structure_alignment
            + self.W_REGIME * regime_agreement
            + self.W_PATTERN * pattern_confirmation
        )
        ctf_score = clamp(raw)

        # Count how many other timeframes agree with current direction
        aligned_count = 0
        highest_aligned_minutes = 0.0
        for tf, intel in other_intel.items():
            other_sign = self._extract_trend_sign(intel)
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
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    # ────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_trend_sign(data: dict[str, Any]) -> int:
        """Extract a directional sign from intelligence data.

        Checks multiple keys in priority order:
          trend_direction (SMC BOS/CHoCH: -1/0/+1)
          trend_strength (I3 TrendStructure: float)
          trend_regime (I4 TrendRegime: -1..+1 float)
          momentum_bias (I4 MomentumContext: -1..+1 float)
        """
        for key in ("trend_direction", "trend_strength", "trend_regime", "momentum_bias"):
            v = data.get(key)
            if is_num(v) and v != 0:
                return _sign(v)
        return 0

    def _score_trend_alignment(
        self, cur_trend: int, other_intel: dict[str, dict[str, Any]]
    ) -> float:
        """Fraction of other TFs agreeing with current direction, signed."""
        if cur_trend == 0 or not other_intel:
            return 0.0

        agrees = 0
        total = len(other_intel)
        for intel in other_intel.values():
            other_sign = self._extract_trend_sign(intel)
            if other_sign == cur_trend:
                agrees += 1
            elif other_sign == -cur_trend:
                agrees -= 1
            # other_sign == 0 → neutral, no contribution

        return cur_trend * (agrees / total)

    @staticmethod
    def _score_structure_alignment(
        features: dict[str, Any], other_intel: dict[str, dict[str, Any]]
    ) -> float:
        """Compare swing patterns across timeframes."""
        cur_pattern = features.get("swing_pattern")
        if not is_num(cur_pattern) or cur_pattern == 0:
            return 0.0

        cur_sign = _sign(cur_pattern)
        agrees = 0
        total = 0
        for intel in other_intel.values():
            other_pattern = intel.get("swing_pattern")
            if is_num(other_pattern) and other_pattern != 0:
                total += 1
                if _sign(other_pattern) == cur_sign:
                    agrees += 1

        if total == 0:
            return 0.0
        return cur_sign * (agrees / total)

    @staticmethod
    def _score_regime_agreement(
        features: dict[str, Any], other_intel: dict[str, dict[str, Any]]
    ) -> float:
        """Compare volatility/momentum regime directions."""
        scores: list[float] = []

        # Momentum bias comparison
        cur_mom = features.get("momentum_bias")
        if is_num(cur_mom) and cur_mom != 0:
            cur_sign = _sign(cur_mom)
            agrees = 0
            total = 0
            for intel in other_intel.values():
                other_mom = intel.get("momentum_bias")
                if is_num(other_mom) and other_mom != 0:
                    total += 1
                    if _sign(other_mom) == cur_sign:
                        agrees += 1
            if total > 0:
                scores.append(cur_sign * (agrees / total))

        # Volatility regime comparison (expansion agreement)
        cur_vol_exp = features.get("vol_expansion")
        if is_num(cur_vol_exp):
            same = 0
            total = 0
            for intel in other_intel.values():
                other_exp = intel.get("vol_expansion")
                if is_num(other_exp):
                    total += 1
                    if (cur_vol_exp > 0) == (other_exp > 0):
                        same += 1
            if total > 0:
                # Agreement is unsigned — it amplifies magnitude but not direction
                scores.append(same / total if scores else 0.0)

        if not scores:
            return 0.0
        return sum(scores) / len(scores)

    @staticmethod
    def _score_pattern_confirmation(
        features: dict[str, Any], other_intel: dict[str, dict[str, Any]]
    ) -> float:
        """Check if current TF patterns are confirmed by higher TF context."""
        confirmations: list[float] = []

        # If current TF shows RSI divergence, check if higher TFs agree on direction
        for div_key, sign in [("rsi_div_bullish", 1), ("rsi_div_bearish", -1)]:
            v = features.get(div_key)
            if is_num(v) and v > 0:
                for intel in other_intel.values():
                    other_trend = intel.get("trend_direction") or intel.get("trend_strength")
                    if is_num(other_trend) and _sign(other_trend) == sign:
                        confirmations.append(float(sign))
                        break

        # BOS/CHoCH confirmation from higher TFs
        cur_bos = features.get("bos_direction")
        if is_num(cur_bos) and cur_bos != 0:
            bos_sign = _sign(cur_bos)
            for intel in other_intel.values():
                other_bos = intel.get("bos_direction")
                if is_num(other_bos) and _sign(other_bos) == bos_sign:
                    confirmations.append(float(bos_sign))
                    break

        if not confirmations:
            return 0.0
        return sum(confirmations) / len(confirmations)


plugin = CrossTimeframeConfluencePlugin()
