"""Composite Intelligence Score (CIS) — 6-bucket weighted directional scorer.

CISScorer aggregates 6 intelligence buckets into a single directional score
in [-1.0, +1.0]. Fires when abs(CIS) > 0.35 AND buckets_agreeing >= 3.

At Phase B (bootstrap), weights are fixed from BOOTSTRAP_WEIGHTS (version=0).
Phase C will load learned weights from the cis_weights table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.intelligence.utils import clamp

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BUCKET_NAMES: tuple[str, ...] = (
    "trend",
    "momentum",
    "structure",
    "pattern",
    "institutional",
    "regime",
)

BOOTSTRAP_WEIGHTS: dict[str, float] = {
    "trend": 0.20,
    "momentum": 0.20,
    "structure": 0.15,
    "pattern": 0.05,
    "institutional": 0.25,
    "regime": 0.15,
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class CISResult:
    """Output of a CISScorer.score() call."""

    cis_score: float          # clamp(sum(w*s), -1.0, 1.0)
    direction: int            # -1 (bearish fire), 0 (no fire), +1 (bullish fire)
    bucket_scores: dict[str, float]
    weights_version: int      # 0 = bootstrap; positive = learned from cis_weights table
    buckets_agreeing: int     # count of buckets agreeing with the CIS direction
    # Per-constituent contributions to final CIS score
    # {bucket: {signal_name: actual_contribution_to_cis_score}}
    constituent_contributions: dict[str, dict[str, float]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------


class CISScorer:
    """6-bucket weighted CIS scorer.

    Parameters
    ----------
    weights:
        Optional custom weight dict keyed by BUCKET_NAMES. Defaults to
        BOOTSTRAP_WEIGHTS.
    weights_version:
        Version tag propagated to CISResult. Use 0 for bootstrap.
    """

    CIS_THRESHOLD = 0.35
    AGREE_MIN = 3
    BUCKET_NOISE = 0.1  # minimum |bucket_score| * direction to count as "agreeing"

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        weights_version: int = 0,
    ) -> None:
        self._weights = weights if weights is not None else BOOTSTRAP_WEIGHTS
        self._weights_version = weights_version

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(
        self,
        features: dict[str, Any],
        plugin_outputs: dict[str, dict],
    ) -> CISResult:
        """Compute CIS from feature dict and per-plugin signal outputs.

        Parameters
        ----------
        features:
            Flat dict of intelligence features (all I1-I6 fields merged).
        plugin_outputs:
            Dict of {plugin_name: signal_dict} for active I7 signals. Used to
            extract direction/confidence contributions for new evidence plugins.

        Returns
        -------
        CISResult with cis_score, direction, bucket_scores, weights_version,
        buckets_agreeing.
        """
        bucket_scores: dict[str, float] = {
            "trend": self._trend(features),
            "momentum": self._momentum(features, plugin_outputs),
            "structure": self._structure(features, plugin_outputs),
            "pattern": self._pattern(features, plugin_outputs),
            "institutional": self._institutional(features, plugin_outputs),
            "regime": self._regime(features, plugin_outputs),
        }

        cis_raw = sum(self._weights[b] * bucket_scores[b] for b in BUCKET_NAMES)
        cis_score = clamp(cis_raw)

        # Determine fire direction
        direction = 0
        if abs(cis_score) > self.CIS_THRESHOLD:
            direction = 1 if cis_score > 0 else -1

        # Count agreeing buckets: bucket agrees if it pushes in the same direction
        # as the CIS sign and the contribution exceeds the noise floor.
        # Use the sign of cis_score (not the magnitude) so a bucket score of 0.28
        # with cis_score=0.3 correctly reads as 0.28 * 1.0 = 0.28 > 0.1 = agreeing.
        cis_sign = 1.0 if cis_score >= 0 else -1.0
        agreeing = sum(
            1
            for b in BUCKET_NAMES
            if bucket_scores[b] * cis_sign > self.BUCKET_NOISE
        )

        # Require minimum agreement even if threshold was met
        if agreeing < self.AGREE_MIN:
            direction = 0

        return CISResult(
            cis_score=round(cis_score, 4),
            direction=direction,
            bucket_scores={k: round(v, 4) for k, v in bucket_scores.items()},
            weights_version=self._weights_version,
            buckets_agreeing=agreeing,
            constituent_contributions={b: {} for b in BUCKET_NAMES},  # populated in Task 13
        )

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def _fval(self, features: dict, key: str, default: float = 0.0) -> float:
        """Safe float extraction — returns *default* on missing / non-numeric."""
        v = features.get(key)
        if v is None:
            return default
        if not isinstance(v, (int, float)):
            try:
                return float(v)
            except (TypeError, ValueError):
                return default
        return float(v)

    def _plug(self, plugin_outputs: dict, name: str) -> tuple[int, float]:
        """Extract (direction, confidence) from a plugin signal dict.

        Returns (0, 0.0) if the plugin is not present in *plugin_outputs*.
        """
        sig = plugin_outputs.get(name, {})
        d = sig.get("direction", 0)
        c = sig.get("confidence", 0.0)
        if not isinstance(d, (int, float)):
            d = 0
        if not isinstance(c, (int, float)):
            c = 0.0
        return int(d), float(c)

    # ------------------------------------------------------------------
    # Bucket scoring methods
    # ------------------------------------------------------------------

    def _trend(self, f: dict) -> float:
        """Trend bucket [-1, +1].

        Weights:
          - trend_regime          0.35  (primary directional regime score)
          - kalman_slope sign     0.20  (Kalman filter slope direction)
          - smc_trend_direction   0.25  (SMC trend per I6 SMC)
          - ctf_trend_alignment   0.10  (cross-TF trend alignment)
          - trend_confluence_score 0.10 (I6 confluence)
        """
        slope = self._fval(f, "kalman_slope")
        slope_dir = 1.0 if slope > 0 else (-1.0 if slope < 0 else 0.0)

        score = (
            0.35 * clamp(self._fval(f, "trend_regime"))
            + 0.20 * slope_dir
            + 0.25 * clamp(self._fval(f, "smc_trend_direction"))
            + 0.10 * clamp(self._fval(f, "ctf_trend_alignment"))
            + 0.10 * clamp(self._fval(f, "trend_confluence_score"))
        )
        return clamp(score)

    def _momentum(self, f: dict, po: dict) -> float:
        """Momentum bucket [-1, +1].

        Weights:
          - rsi_14 mapped [0,100]→[-1,+1] around 50   0.30
          - macd_hist_12_26_9 sign                     0.25
          - roc_14 sign                                0.20
          - momentum_bias                              0.15
          - DivergenceStack plugin direction * conf    0.10
        """
        rsi = self._fval(f, "rsi_14", default=50.0)
        rsi_dir = (rsi - 50.0) / 50.0  # maps [0,100] → [-1,+1]

        macd = self._fval(f, "macd_histogram_12_26_9")
        macd_dir = 1.0 if macd > 0 else (-1.0 if macd < 0 else 0.0)

        roc = self._fval(f, "roc_14")
        roc_dir = 1.0 if roc > 0 else (-1.0 if roc < 0 else 0.0)

        d, c = self._plug(po, "trad_DivergenceStack")

        score = (
            0.30 * clamp(rsi_dir)
            + 0.25 * macd_dir
            + 0.20 * roc_dir
            + 0.15 * clamp(self._fval(f, "momentum_bias"))
            + 0.10 * float(d) * float(c)
        )
        return clamp(score)

    def _structure(self, f: dict, po: dict) -> float:
        """Structure bucket [-1, +1].

        Weights:
          - swing_pattern                         0.30
          - bos_detected * bos_direction          0.25
          - choch_detected * choch_direction      0.25
          - CHoCHReversal plugin dir * conf        0.20
        """
        bos = self._fval(f, "bos_detected") * self._fval(f, "bos_direction")
        choch = self._fval(f, "choch_detected") * self._fval(f, "choch_direction")
        d, c = self._plug(po, "trad_CHoCHReversal")

        score = (
            0.30 * clamp(self._fval(f, "swing_pattern"))
            + 0.25 * clamp(bos)
            + 0.25 * clamp(choch)
            + 0.20 * float(d) * float(c)
        )
        return clamp(score)

    def _pattern(self, f: dict, po: dict) -> float:
        """Pattern bucket [-1, +1].

        Weights:
          - dt_db_pattern dir * dt_db_confidence    0.40
          - hs_pattern dir * hs_confidence          0.30
          - tri_breakout_bias * tri_confidence       0.20
          - PatternCompletion plugin dir * conf      0.10

        Note: dt_db_pattern==1 → double top (bearish), ==2 → double bottom (bullish)
              hs_pattern==1,2 → H&S (bearish); hs_pattern==3,4 → IH&S (bullish)
        """
        dt_pattern = self._fval(f, "dt_db_pattern")
        dt_dir = -1.0 if dt_pattern == 1.0 else (1.0 if dt_pattern == 2.0 else 0.0)

        hs = self._fval(f, "hs_pattern")
        hs_dir = -1.0 if hs in (1.0, 2.0) else (1.0 if hs in (3.0, 4.0) else 0.0)

        d, c = self._plug(po, "trad_PatternCompletion")

        score = (
            0.40 * dt_dir * self._fval(f, "dt_db_confidence")
            + 0.30 * hs_dir * self._fval(f, "hs_confidence")
            + 0.20 * self._fval(f, "tri_breakout_bias") * self._fval(f, "tri_confidence")
            + 0.10 * float(d) * float(c)
        )
        return clamp(score)

    def _institutional(self, f: dict, po: dict) -> float:
        """Institutional bucket [-1, +1].

        Weights:
          - ob_type * ob_strength                        0.25
          - fvg_type * (fvg_open_count > 0 ? 1 : 0)     0.15
          - in_demand_zone - in_supply_zone              0.20
          - FVGFill plugin direction * confidence        0.20
          - SupplyDemandSetup plugin direction * conf    0.20
        """
        fvg_active = 1.0 if self._fval(f, "fvg_open_count") > 0 else 0.0
        zone = self._fval(f, "in_demand_zone") - self._fval(f, "in_supply_zone")

        fd, fc = self._plug(po, "trad_FVGFill")
        sd_d, sd_c = self._plug(po, "trad_SupplyDemandSetup")

        score = (
            0.25 * clamp(self._fval(f, "ob_type") * self._fval(f, "ob_strength"))
            + 0.15 * clamp(self._fval(f, "fvg_type") * fvg_active)
            + 0.20 * clamp(zone)
            + 0.20 * float(fd) * float(fc)
            + 0.20 * float(sd_d) * float(sd_c)
        )
        return clamp(score)

    def _regime(self, f: dict, po: dict) -> float:
        """Regime bucket [-1, +1].

        Weights:
          - hmm_prob_trending_up - hmm_prob_trending_down   0.35
          - cp_probability > 0.5 -> 0 (uncertainty)          0.15
          - ctf_regime_agreement                             0.20
          - vol_regime inverted (high vol = bearish for CIS) 0.20
          - RegimeTransition plugin direction * conf          0.10
        """
        hmm_dir = (
            self._fval(f, "hmm_prob_trending_up")
            - self._fval(f, "hmm_prob_trending_down")
        )

        # Changepoint probability > 0.5 signals imminent regime change → uncertain direction (0).
        # When cp <= 0.5 (stable regime), reinforce HMM direction scaled by stability.
        cp = self._fval(f, "cp_probability")
        cp_contribution = 0.0 if cp > 0.5 else clamp(hmm_dir) * (1.0 - cp * 2.0)

        d, c = self._plug(po, "trad_RegimeTransition")

        score = (
            0.35 * clamp(hmm_dir)
            + 0.15 * cp_contribution
            + 0.20 * clamp(self._fval(f, "ctf_regime_agreement"))
            + 0.20 * clamp(self._fval(f, "vol_regime") * -1.0)
            + 0.10 * float(d) * float(c)
        )
        return clamp(score)
