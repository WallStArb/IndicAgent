from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from ..utils import clamp, is_num

# Timeframe weight: higher timeframes carry more authority
_TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}

# I2 event keys that indicate bullish momentum (+0.1 each)
_I2_BULLISH_EVENTS = frozenset(
    {
        "macd_cross_bullish",
        "rsi_crossed_30_up",
        "rsi_extreme_reversal",
        "stoch_cross_bullish",
        "stoch_oversold_reversal",
        "adx_trend_confirmed",
        "di_cross_bullish",
        "stoch_both_oversold",
    }
)

# I2 event keys that indicate bearish momentum (-0.1 each)
_I2_BEARISH_EVENTS = frozenset(
    {
        "macd_cross_bearish",
        "rsi_crossed_70_down",
        "stoch_cross_bearish",
        "stoch_overbought_reversal",
        "di_cross_bearish",
        "stoch_both_overbought",
    }
)


def _sign(x: float) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def _proximity_decay(price: float, level_top: float, level_bottom: float, atr: float) -> float:
    """1.0 within 1 ATR of zone midpoint; linear decay to 0.0 at 3 ATR; 0.0 beyond."""
    if atr <= 0 or level_top <= 0 or level_bottom <= 0:
        return 0.0
    midpoint = (level_top + level_bottom) / 2.0
    dist_atr = abs(price - midpoint) / atr
    if dist_atr <= 1.0:
        return 1.0
    if dist_atr >= 3.0:
        return 0.0
    return 1.0 - (dist_atr - 1.0) / 2.0


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
        features = frames.get("features") or {}
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
        weights = {tf: self._get_recency_weight(frames, tf) for tf in other_intel}

        # Current timeframe direction (from I3/I4/SMC outputs in features)
        cur_trend = self._extract_trend_sign(features)

        trend_alignment = self._score_trend_alignment(cur_trend, other_intel, weights)
        structure_alignment = self._score_structure_alignment(features, other_intel, weights)
        regime_agreement = self._score_regime_agreement(features, other_intel, weights)
        pattern_confirmation = self._score_pattern_confirmation(features, other_intel)
        bos_alignment = self._score_smc_bos_alignment(features, other_intel, weights)
        fvg_score, fvg_tf_contribs = self._score_fvg_alignment(features, other_intel, current_tf)
        ob_score, ob_tf_contribs = self._score_ob_alignment(features, other_intel, current_tf)
        i2_score = self._score_i2_events(features)

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
            "i6_smc_bos_alignment": round(bos_alignment, 4),
            "i6_fvg_tf_alignment": fvg_score,
            "i6_ob_tf_alignment": ob_score,
            "i6_i2_event_score": round(i2_score, 4),
            # Per-TF FVG and OB contributions — Renaissance standard: every score is decomposable
            **{f"i6_fvg_tf_{tf}": v for tf, v in fvg_tf_contribs.items()},
            **{f"i6_ob_tf_{tf}": v for tf, v in ob_tf_contribs.items()},
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    # ────────────────────────────────────────────────────────────

    @staticmethod
    def _get_recency_weight(frames: dict[str, Any], tf: str) -> float:
        """Return recency weight for a TF. bars_since=0 → 1.0; stale→→ 0."""
        bars_since = frames.get(f"intel_{tf}_bars_since")
        if not is_num(bars_since) or bars_since < 0:
            return 1.0
        return 1.0 / (bars_since + 1)

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
        self,
        cur_trend: int,
        other_intel: dict[str, dict[str, Any]],
        weights: dict[str, float],
    ) -> float:
        """Recency-weighted fraction of other TFs agreeing with current direction."""
        if cur_trend == 0 or not other_intel:
            return 0.0

        total_weight = 0.0
        weighted_sum = 0.0
        for tf, intel in other_intel.items():
            w = weights.get(tf, 1.0)
            other_sign = self._extract_trend_sign(intel)
            total_weight += w
            if other_sign == cur_trend:
                weighted_sum += w
            elif other_sign == -cur_trend:
                weighted_sum -= w
            # other_sign == 0 → neutral, no contribution

        if total_weight == 0.0:
            return 0.0
        return cur_trend * (weighted_sum / total_weight)

    @staticmethod
    def _score_structure_alignment(
        features: dict[str, Any],
        other_intel: dict[str, dict[str, Any]],
        weights: dict[str, float],
    ) -> float:
        """Recency-weighted swing pattern agreement across timeframes."""
        cur_pattern = features.get("swing_pattern")
        if not is_num(cur_pattern) or cur_pattern == 0:
            return 0.0

        cur_sign = _sign(cur_pattern)
        total_weight = 0.0
        weighted_sum = 0.0
        for tf, intel in other_intel.items():
            other_pattern = intel.get("swing_pattern")
            if is_num(other_pattern) and other_pattern != 0:
                w = weights.get(tf, 1.0)
                total_weight += w
                if _sign(other_pattern) == cur_sign:
                    weighted_sum += w

        if total_weight == 0.0:
            return 0.0
        return cur_sign * (weighted_sum / total_weight)

    @staticmethod
    def _score_regime_agreement(
        features: dict[str, Any],
        other_intel: dict[str, dict[str, Any]],
        weights: dict[str, float],
    ) -> float:
        """Recency-weighted volatility/momentum regime agreement."""
        scores: list[float] = []

        # Momentum bias comparison
        cur_mom = features.get("momentum_bias")
        if is_num(cur_mom) and cur_mom != 0:
            cur_sign = _sign(cur_mom)
            total_weight = 0.0
            weighted_sum = 0.0
            for tf, intel in other_intel.items():
                other_mom = intel.get("momentum_bias")
                if is_num(other_mom) and other_mom != 0:
                    w = weights.get(tf, 1.0)
                    total_weight += w
                    if _sign(other_mom) == cur_sign:
                        weighted_sum += w
            if total_weight > 0.0:
                scores.append(cur_sign * (weighted_sum / total_weight))

        # Volatility regime comparison (expansion agreement)
        cur_vol_exp = features.get("vol_expansion")
        if is_num(cur_vol_exp):
            total_weight = 0.0
            weighted_sum = 0.0
            for tf, intel in other_intel.items():
                other_exp = intel.get("vol_expansion")
                if is_num(other_exp):
                    w = weights.get(tf, 1.0)
                    total_weight += w
                    if (cur_vol_exp > 0) == (other_exp > 0):
                        weighted_sum += w
            if total_weight > 0.0 and scores:
                # Agreement is unsigned — only valid when a directional baseline exists
                scores.append(weighted_sum / total_weight)

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

    def _score_smc_bos_alignment(
        self,
        features: dict[str, Any],
        other_intel: dict[str, dict[str, Any]],
        weights: dict[str, float],
    ) -> float:
        """BOS direction on current TF vs higher TF trend direction (recency-weighted)."""
        cur_bos = features.get("bos_direction")
        if not is_num(cur_bos) or cur_bos == 0:
            return 0.0

        bos_sign = _sign(cur_bos)
        total_weight = 0.0
        weighted_sum = 0.0
        for tf, intel in other_intel.items():
            other_sign = self._extract_trend_sign(intel)
            if other_sign != 0:
                w = weights.get(tf, 1.0)
                total_weight += w
                if other_sign == bos_sign:
                    weighted_sum += w
                else:
                    weighted_sum -= w

        if total_weight == 0.0:
            return 0.0
        return clamp(bos_sign * (weighted_sum / total_weight))

    def _score_fvg_alignment(
        self,
        features: dict[str, Any],
        other_intel: dict[str, dict[str, Any]],
        current_tf: str,
    ) -> tuple[float, dict[str, float]]:
        """Direction-weighted FVG proximity score across higher TFs.

        Only higher TFs are used (lower TFs are too ephemeral).
        TF authority weight = _TF_MINUTES value, normalized across contributing TFs.
        Returns (aggregate_score, per_tf_contributions) for full auditability.
        """
        cur_price = features.get("close") or 0.0
        atr = features.get("atr_14") or 0.0
        cur_trend = self._extract_trend_sign(features)
        if cur_trend == 0 or atr <= 0:
            return 0.0, {}

        cur_tf_min = _TF_MINUTES.get(current_tf, 0)
        total_weight = 0.0
        weighted_sum = 0.0
        contributions: dict[str, float] = {}

        for tf, intel in other_intel.items():
            tf_min = _TF_MINUTES.get(tf, 0)
            if tf_min <= cur_tf_min:
                continue  # Only higher TFs
            fvg_type = intel.get("fvg_type") or 0.0
            fvg_top = intel.get("fvg_top") or 0.0
            fvg_bottom = intel.get("fvg_bottom") or 0.0
            if not is_num(fvg_type) or fvg_type == 0.0 or fvg_top <= 0 or fvg_bottom <= 0:
                continue
            direction_match = 1.0 if int(fvg_type) == cur_trend else -1.0
            decay = _proximity_decay(cur_price, fvg_top, fvg_bottom, atr)
            if decay <= 0:
                continue
            w = float(tf_min)
            total_weight += w
            contrib = direction_match * decay
            weighted_sum += w * contrib
            contributions[tf] = round(contrib, 4)

        if total_weight == 0.0:
            return 0.0, {}
        return round(clamp(weighted_sum / total_weight), 4), contributions

    def _score_ob_alignment(
        self,
        features: dict[str, Any],
        other_intel: dict[str, dict[str, Any]],
        current_tf: str,
    ) -> tuple[float, dict[str, float]]:
        """Direction-weighted Order Block proximity score across higher TFs.

        OBs are already filtered to unmitigated-only by order_blocks.py.
        Same formula as FVG — Phase 46 calibration may diverge weights if data supports it.
        Returns (aggregate_score, per_tf_contributions) for full auditability.
        """
        cur_price = features.get("close") or 0.0
        atr = features.get("atr_14") or 0.0
        cur_trend = self._extract_trend_sign(features)
        if cur_trend == 0 or atr <= 0:
            return 0.0, {}

        cur_tf_min = _TF_MINUTES.get(current_tf, 0)
        total_weight = 0.0
        weighted_sum = 0.0
        contributions: dict[str, float] = {}

        for tf, intel in other_intel.items():
            tf_min = _TF_MINUTES.get(tf, 0)
            if tf_min <= cur_tf_min:
                continue  # Only higher TFs
            ob_type = intel.get("ob_type") or 0.0
            ob_top = intel.get("ob_top") or 0.0
            ob_bottom = intel.get("ob_bottom") or 0.0
            if not is_num(ob_type) or ob_type == 0.0 or ob_top <= 0 or ob_bottom <= 0:
                continue
            direction_match = 1.0 if int(ob_type) == cur_trend else -1.0
            decay = _proximity_decay(cur_price, ob_top, ob_bottom, atr)
            if decay <= 0:
                continue
            w = float(tf_min)
            total_weight += w
            contrib = direction_match * decay
            weighted_sum += w * contrib
            contributions[tf] = round(contrib, 4)

        if total_weight == 0.0:
            return 0.0, {}
        return round(clamp(weighted_sum / total_weight), 4), contributions

    @staticmethod
    def _score_i2_events(features: dict[str, Any]) -> float:
        """Score I2 composite event signals on the current bar.

        Bullish events add +0.1, bearish events subtract 0.1.
        macd_negative_support_test adds +0.15 (bullish reversal confirmation).
        Result clamped to [-1.0, 1.0].
        """
        score = 0.0
        for key in _I2_BULLISH_EVENTS:
            v = features.get(key)
            if is_num(v) and v > 0:
                score += 0.1
        for key in _I2_BEARISH_EVENTS:
            v = features.get(key)
            if is_num(v) and v > 0:
                score -= 0.1
        v_neg = features.get("macd_negative_support_test")
        if is_num(v_neg) and v_neg > 0:
            score += 0.15
        return clamp(score)


plugin = CrossTimeframeConfluencePlugin()
