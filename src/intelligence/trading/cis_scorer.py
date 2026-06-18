"""Composite Intelligence Score (CIS) — 6-bucket weighted directional scorer.

CISScorer aggregates 6 intelligence buckets into a single directional score
in [-1.0, +1.0]. Fires when abs(CIS) > 0.35 AND buckets_agreeing >= 3.

Renaissance principles applied:
- Segment relentlessly: regime thresholds explicitly documented
- Instrument everything: epsilon tolerance for floating-point direction comparisons

At Phase B (bootstrap), weights are fixed from _CONFIG_UNAVAILABLE_FALLBACK (version=0).
Phase C will load learned weights from the cis_weights table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.intelligence.utils import clamp

# Type alias for calibration curves dict (matches calibrator.py type)
type CalibrationCurves = dict[tuple[str, str, str], tuple[np.ndarray, np.ndarray]]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Epsilon tolerance for floating-point comparisons (Renaissance: instrument everything)
EPSILON_TOLERANCE = 1e-9  # Tolerance for direction comparisons (slope, MACD, ROC)

# Regime thresholds (Renaissance: segment relentlessly)
CIS_FIRE_THRESHOLD = 0.35  # abs(CIS) > 0.35 required for signal fire
BUCKET_AGREE_MIN = 3  # Minimum buckets agreeing with CIS direction
BUCKET_NOISE_FLOOR = 0.1  # Minimum |bucket_score| to count as agreeing

_config_service: Any | None = None


def set_config_service(config: Any) -> None:
    """Inject ConfigService for APR-backed CIS gate constants.

    Called by intelligence_pipeline._prewarm_threshold_config() at startup.
    Same pattern as confidence.set_config_service().
    """
    global _config_service
    _config_service = config


BUCKET_NAMES: tuple[str, ...] = (
    "trend",
    "momentum",
    "structure",
    "pattern",
    "institutional",
    "regime",
)

_CONFIG_UNAVAILABLE_FALLBACK: dict[str, float] = {
    "trend": 0.20,
    "momentum": 0.20,
    "structure": 0.15,
    "pattern": 0.05,
    "institutional": 0.25,
    "regime": 0.15,
}
BOOTSTRAP_WEIGHTS = _CONFIG_UNAVAILABLE_FALLBACK  # deprecated: use _CONFIG_UNAVAILABLE_FALLBACK


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class CISResult:
    """Output of a CISScorer.score() call."""

    cis_score: float  # clamp(sum(w*s), -1.0, 1.0)
    direction: int  # -1 (bearish fire), 0 (no fire), +1 (bullish fire)
    bucket_scores: dict[str, float]
    weights_version: int  # 0 = bootstrap; positive = learned from cis_weights table
    buckets_agreeing: int  # count of buckets agreeing with the CIS direction
    # Per-constituent contributions to final CIS score
    # {bucket: {signal_name: actual_contribution_to_cis_score}}
    constituent_contributions: dict[str, dict[str, float]] = field(default_factory=dict)
    # Design B: calibrated CIS score (isotonic applied to Kalman-filtered CIS).
    # None when no calibration curve is available for this (tf, symbol).
    calibrated_cis: float | None = None

    def __post_init__(self) -> None:
        if self.cis_score is None:
            raise TypeError("CISResult.cis_score must be float, got None")
        self.cis_score = float(self.cis_score)


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------


class CISScorer:
    """6-bucket weighted CIS scorer.

    Parameters
    ----------
    weights:
        Optional custom weight dict keyed by BUCKET_NAMES. Defaults to
        _CONFIG_UNAVAILABLE_FALLBACK.
    weights_version:
        Version tag propagated to CISResult. Use 0 for bootstrap.
    """

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        weights_version: int = 0,
    ) -> None:
        self._weights = weights if weights is not None else _CONFIG_UNAVAILABLE_FALLBACK
        self._weights_version = weights_version
        # Pre-compute weights array once — self._weights is immutable after init
        self._weights_array = np.array([self._weights[b] for b in BUCKET_NAMES])
        # Calibration curves for CIS-level calibration (Design B).
        # Set via set_calibration_curves(); empty dict = passthrough.
        self._calibration_curves: CalibrationCurves = {}
        # Per-(tf, symbol) Kalman state for CIS smoothing (Design B: moved from SignalProcessor).
        # Keys: (tf, symbol), values: {"x": float, "P": float, "Q": float, "R": float}
        self._cis_kalman_state: dict[tuple[str, str], dict] = {}

    def update_weights(self, weights: dict[str, float], version: int) -> None:
        """Runtime weight hot-swap. Called from service layer only.

        The GIL protects dict/array assignment — no asyncio.Lock needed.
        Do NOT call this from score() — it is a background refresh concern.

        Parameters
        ----------
        weights:
            New weight dict keyed by BUCKET_NAMES. Must sum to ~1.0.
        version:
            Version number from cis_weights table (positive = learned).
        """
        self._weights = weights
        self._weights_version = version
        self._weights_array = np.array([self._weights[b] for b in BUCKET_NAMES])

    def set_calibration_curves(self, curves: CalibrationCurves) -> None:
        """Update CIS-level calibration curves (Design B).

        Called by orchestrator when cache_snapshot.calibration_curves changes.
        The GIL protects dict assignment — no asyncio.Lock needed.

        Parameters
        ----------
        curves:
            Dict keyed by (plugin_name_or_sentinel, tf, symbol) →
            (breakpoints, values) numpy arrays. Use "_cis_" as plugin_name_or_sentinel
            for CIS-level curves. Empty dict = passthrough.
        """
        self._calibration_curves = curves

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_kalman_state(self) -> dict:
        """Return defensive copy of CIS Kalman state for checkpoint.

        New format: {(tf, symbol): {"x": float, "P": float, "Q": float, "R": float}}
        Legacy (pre-Design-B) format: {str: float} — returned as-is.
        """
        result = {}
        for k, v in self._cis_kalman_state.items():
            result[k] = dict(v) if isinstance(v, dict) else v
        return result

    def restore_kalman_state(self, state: dict) -> None:
        """Restore CIS Kalman state from checkpoint.

        Accepts the new format {(tf, symbol): dict} and gracefully handles
        legacy checkpoint format (arbitrary string keys with non-dict values)
        by storing them as-is for backward compatibility.
        """
        for k, v in state.items():
            if isinstance(v, dict):
                self._cis_kalman_state[k] = dict(v)
            else:
                # Legacy format (pre-Design-B checkpoint): store value as-is.
                # This prevents crashes when restoring old checkpoints.
                self._cis_kalman_state[k] = v

    def score(
        self,
        features: dict[str, Any],
        plugin_outputs: dict[str, dict],
        *,
        tf: str = "*",
        symbol: str = "*",
    ) -> CISResult:
        """Compute CIS from feature dict and per-plugin signal outputs.

        Design B (Phase 112): Applies Kalman smoothing to the raw CIS score and
        then applies CIS-level isotonic calibration (not per-signal calibration).
        The calibrated_cis field on CISResult is stamped by the pipeline as
        calibrated_confidence on the winner signal.

        Parameters
        ----------
        features:
            Flat dict of intelligence features (all I1-I6 fields merged).
        plugin_outputs:
            Dict of {plugin_name: signal_dict} for active I7 signals. Used to
            extract direction/confidence contributions for new evidence plugins.
        tf:
            Current timeframe (e.g. "1m"). Used for Kalman state key and calibration lookup.
        symbol:
            Instrument symbol (e.g. "ES"). Used for Kalman state key and calibration lookup.

        Returns
        -------
        CISResult with cis_score, direction, bucket_scores, weights_version,
        buckets_agreeing, constituent_contributions, calibrated_cis.
        calibrated_cis is None if no calibration curve is available.
        """
        trend_score, trend_contrib = self._trend(features)
        momentum_score, momentum_contrib = self._momentum(features, plugin_outputs)
        structure_score, structure_contrib = self._structure(features, plugin_outputs)
        pattern_score, pattern_contrib = self._pattern(features, plugin_outputs)
        institutional_score, institutional_contrib = self._institutional(features, plugin_outputs)
        regime_score, regime_contrib = self._regime(features, plugin_outputs)

        bucket_scores: dict[str, float] = {
            "trend": trend_score,
            "momentum": momentum_score,
            "structure": structure_score,
            "pattern": pattern_score,
            "institutional": institutional_score,
            "regime": regime_score,
        }
        contributions: dict[str, dict[str, float]] = {
            "trend": trend_contrib,
            "momentum": momentum_contrib,
            "structure": structure_contrib,
            "pattern": pattern_contrib,
            "institutional": institutional_contrib,
            "regime": regime_contrib,
        }

        # Vectorized aggregation: weights_array is pre-computed at init (static),
        # scores_array is per-call. np.dot gives the weighted sum in one pass.
        scores_array = np.array([bucket_scores[b] for b in BUCKET_NAMES])
        cis_raw = float(np.dot(self._weights_array, scores_array))
        cis_score = clamp(cis_raw)

        # Read gate constants from APR at runtime (fallback to module-level defaults).
        fire_threshold = (
            _config_service.get_sync("threshold.cis.fire_threshold", CIS_FIRE_THRESHOLD)
            if _config_service is not None
            else CIS_FIRE_THRESHOLD
        )
        bucket_agree_min = (
            int(_config_service.get_sync("threshold.cis.bucket_agree_min", BUCKET_AGREE_MIN))
            if _config_service is not None
            else BUCKET_AGREE_MIN
        )
        bucket_noise_floor = (
            _config_service.get_sync("threshold.cis.bucket_noise_floor", BUCKET_NOISE_FLOOR)
            if _config_service is not None
            else BUCKET_NOISE_FLOOR
        )

        # Determine fire direction
        direction = 0
        if abs(cis_score) > fire_threshold:
            direction = 1 if cis_score > 0 else -1

        # Count agreeing buckets: bucket agrees if it pushes in the same direction
        # as the CIS sign and the contribution exceeds the noise floor.
        # Use the sign of cis_score (not the magnitude) so a bucket score of 0.28
        # with cis_score=0.3 correctly reads as 0.28 * 1.0 = 0.28 > 0.1 = agreeing.
        cis_sign = 1.0 if cis_score >= 0 else -1.0
        bucket_array = scores_array * cis_sign  # Apply cis_sign to all buckets
        agreeing = int(np.sum(bucket_array > bucket_noise_floor))

        # Require minimum agreement even if threshold was met
        if agreeing < bucket_agree_min:
            direction = 0

        # Design B: Apply Kalman smoothing to raw CIS, then apply CIS-level calibration.
        # The filtered CIS is stored internally in _cis_kalman_state for state persistence.
        filtered_cis = self._apply_cis_kalman(cis_score, tf, symbol)
        calibrated_cis = self._apply_cis_calibration(filtered_cis, tf, symbol)

        return CISResult(
            cis_score=round(cis_score, 4),
            direction=direction,
            bucket_scores={k: round(v, 4) for k, v in bucket_scores.items()},
            weights_version=self._weights_version,
            buckets_agreeing=agreeing,
            constituent_contributions=contributions,
            calibrated_cis=calibrated_cis,
        )

    def _apply_cis_kalman(self, raw_cis: float, tf: str, symbol: str) -> float:
        """Apply per-(tf, symbol) Kalman filter to smooth CIS bar-to-bar noise.

        Design B: Kalman lives in CISScorer so calibration can use the filtered value.
        State keyed by (tf, symbol) to isolate per-instrument Kalman tracks.
        """
        key = (tf, symbol)
        if key not in self._cis_kalman_state:
            R = {"1m": 0.5, "5m": 0.3, "15m": 0.2, "1h": 0.1}.get(tf, 0.3)
            self._cis_kalman_state[key] = {"x": raw_cis, "P": 1.0, "Q": 0.01, "R": R}
        ks = self._cis_kalman_state[key]
        P_pred = ks["P"] + ks["Q"]
        K = P_pred / (P_pred + ks["R"])
        x_new = ks["x"] + K * (raw_cis - ks["x"])
        P_new = (1.0 - K) * P_pred
        ks["x"] = x_new
        ks["P"] = P_new
        return x_new

    def _apply_cis_calibration(self, filtered_cis: float, tf: str, symbol: str) -> float | None:
        """Apply CIS-level isotonic calibration to the Kalman-filtered CIS score.

        Lookup hierarchy: (_cis_, tf, symbol) → (_cis_, tf, *) → None (passthrough).
        Returns None when no calibration curve is available.
        The caller stamps the result on the winner signal as calibrated_confidence.
        """
        if not self._calibration_curves:
            return None
        _key_specific = ("_cis_", tf, symbol)
        _key_global = ("_cis_", tf, "*")
        curve = self._calibration_curves.get(
            _key_specific, self._calibration_curves.get(_key_global)
        )
        if curve is None:
            return None
        breakpoints, values = curve
        calibrated = float(np.interp(filtered_cis, breakpoints, values))
        return round(calibrated, 4)

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

    def _trend(self, f: dict) -> tuple[float, dict[str, float]]:
        """Trend bucket [-1, +1].

        Weights:
          - trend_regime          0.35  (primary directional regime score)
          - kalman_slope sign     0.20  (Kalman filter slope direction)
          - smc_trend_direction   0.25  (SMC trend per I6 SMC)
          - ctf_trend_alignment   0.10  (cross-TF trend alignment)
          - trend_confluence_score 0.10 (I6 confluence)
        """
        slope = self._fval(f, "kalman_slope")
        slope_dir = (
            1.0 if slope > EPSILON_TOLERANCE else (-1.0 if slope < -EPSILON_TOLERANCE else 0.0)
        )

        c_trend_regime = 0.35 * clamp(self._fval(f, "trend_regime"))
        c_kalman_slope = 0.20 * slope_dir
        c_smc_trend = 0.25 * clamp(self._fval(f, "smc_trend_direction"))
        c_ctf_trend = 0.10 * clamp(self._fval(f, "ctf_trend_alignment"))
        c_trend_confluence = 0.10 * clamp(self._fval(f, "trend_confluence_score"))

        score = c_trend_regime + c_kalman_slope + c_smc_trend + c_ctf_trend + c_trend_confluence
        contrib = {
            "trend_regime": c_trend_regime,
            "kalman_slope": c_kalman_slope,
            "smc_trend_direction": c_smc_trend,
            "ctf_trend_alignment": c_ctf_trend,
            "trend_confluence_score": c_trend_confluence,
        }
        return clamp(score), contrib

    def _momentum(self, f: dict, po: dict) -> tuple[float, dict[str, float]]:
        """Momentum bucket [-1, +1].

        Weights:
          - rsi_14 mapped [0,100]→[-1,+1] around 50   0.30
          - macd_histogram_12_26_9 sign                0.25
          - roc_14 sign                                0.20
          - momentum_bias                              0.15
          - DivergenceStack plugin direction * conf    0.10
          - rel_volume sub-term (supplemental, additive) ±0.05
        """
        rsi = self._fval(f, "rsi_14", default=50.0)
        rsi_dir = (rsi - 50.0) / 50.0  # maps [0,100] → [-1,+1]

        macd = self._fval(f, "macd_histogram_12_26_9")
        macd_dir = 1.0 if macd > EPSILON_TOLERANCE else (-1.0 if macd < -EPSILON_TOLERANCE else 0.0)

        roc = self._fval(f, "roc_14")
        roc_dir = 1.0 if roc > EPSILON_TOLERANCE else (-1.0 if roc < -EPSILON_TOLERANCE else 0.0)

        d, c = self._plug(po, "trad_DivergenceStack")

        # QUAL-05: rel_volume sub-term — maps [0,2] → [-0.05, +0.05] via clamp.
        # default=1.0 so missing rel_volume contributes exactly 0.0 (neutral).
        rel_vol = self._fval(f, "rel_volume", default=1.0)
        c_rel_vol = 0.05 * clamp((rel_vol - 1.0) / 1.0)

        c_rsi = 0.30 * clamp(rsi_dir)
        c_macd = 0.25 * macd_dir
        c_roc = 0.20 * roc_dir
        c_momentum_bias = 0.15 * clamp(self._fval(f, "momentum_bias"))
        c_divergence = 0.10 * float(d) * float(c)

        score = c_rsi + c_macd + c_roc + c_momentum_bias + c_divergence + c_rel_vol
        contrib = {
            "rsi_14": float(c_rsi),
            "macd_histogram_12_26_9": float(c_macd),
            "roc_14": float(c_roc),
            "momentum_bias": float(c_momentum_bias),
            "trad_DivergenceStack": float(c_divergence),
            "rel_volume": float(c_rel_vol),
        }
        return clamp(score), contrib

    def _structure(self, f: dict, po: dict) -> tuple[float, dict[str, float]]:
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

        c_swing = 0.30 * clamp(self._fval(f, "swing_pattern"))
        c_bos = 0.25 * clamp(bos)
        c_choch = 0.25 * clamp(choch)
        c_choch_reversal = 0.20 * float(d) * float(c)

        score = c_swing + c_bos + c_choch + c_choch_reversal
        contrib = {
            "swing_pattern": float(c_swing),
            "bos_detected": float(c_bos),
            "choch_detected": float(c_choch),
            "trad_CHoCHReversal": float(c_choch_reversal),
        }
        return clamp(score), contrib

    def _pattern(self, f: dict, po: dict) -> tuple[float, dict[str, float]]:
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

        c_dt = 0.40 * dt_dir * self._fval(f, "dt_db_confidence")
        c_hs = 0.30 * hs_dir * self._fval(f, "hs_confidence")
        c_tri = 0.20 * self._fval(f, "tri_breakout_bias") * self._fval(f, "tri_confidence")
        c_pattern_completion = 0.10 * float(d) * float(c)

        score = c_dt + c_hs + c_tri + c_pattern_completion
        contrib = {
            "dt_db_pattern": float(c_dt),
            "hs_pattern": float(c_hs),
            "tri_breakout_bias": float(c_tri),
            "trad_PatternCompletion": float(c_pattern_completion),
        }
        return clamp(score), contrib

    def _institutional(self, f: dict, po: dict) -> tuple[float, dict[str, float]]:
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

        c_ob = 0.25 * clamp(self._fval(f, "ob_type") * self._fval(f, "ob_strength"))
        c_fvg = 0.15 * clamp(self._fval(f, "fvg_type") * fvg_active)
        c_zone = 0.20 * clamp(zone)
        c_fvg_fill = 0.20 * float(fd) * float(fc)
        c_supply_demand = 0.20 * float(sd_d) * float(sd_c)

        score = c_ob + c_fvg + c_zone + c_fvg_fill + c_supply_demand
        contrib = {
            "ob_type": float(c_ob),
            "fvg_type": float(c_fvg),
            "in_demand_zone": float(c_zone),
            "trad_FVGFill": float(c_fvg_fill),
            "trad_SupplyDemandSetup": float(c_supply_demand),
        }
        return clamp(score), contrib

    def _regime(self, f: dict, po: dict) -> tuple[float, dict[str, float]]:
        """Regime bucket [-1, +1].

        Weights:
          - hmm_prob_trending_up - hmm_prob_trending_down   0.35
          - cp_probability > 0.5 -> 0 (uncertainty)          0.15
          - ctf_regime_agreement                             0.20
          - vol_regime inverted (high vol = bearish for CIS) 0.20
          - RegimeTransition plugin direction * conf          0.10
          - killzone sub-term (supplemental, additive)        ±0.05
        """
        hmm_dir = self._fval(f, "hmm_prob_trending_up") - self._fval(f, "hmm_prob_trending_down")

        # Changepoint probability > 0.5 signals imminent regime change → uncertain direction (0).
        # When cp <= 0.5 (stable regime), reinforce HMM direction scaled by stability.
        cp = self._fval(f, "cp_probability")
        cp_contribution = 0.0 if cp > 0.5 else clamp(hmm_dir) * (1.0 - cp * 2.0)

        d, c = self._plug(po, "trad_RegimeTransition")

        # QUAL-06: killzone sub-term — active London or NY killzone gets slight boost (+0.05);
        # dead session (no killzone active) gets slight suppression (-0.01).
        # Uses max() to handle case where both killzones could be active simultaneously.
        in_kz = max(
            self._fval(f, "in_london_killzone"),
            self._fval(f, "in_ny_killzone"),
        )
        c_killzone = 0.05 * (1.0 if in_kz > 0.5 else -0.2)

        c_hmm = 0.35 * clamp(hmm_dir)
        c_cp = 0.15 * cp_contribution
        c_ctf_regime = 0.20 * clamp(self._fval(f, "ctf_regime_agreement"))
        c_vol_regime = 0.20 * clamp(self._fval(f, "vol_regime") * -1.0)
        c_regime_transition = 0.10 * float(d) * float(c)

        score = c_hmm + c_cp + c_ctf_regime + c_vol_regime + c_regime_transition + c_killzone
        contrib = {
            "hmm_prob_trending_up": float(c_hmm),
            "cp_probability": float(c_cp),
            "ctf_regime_agreement": float(c_ctf_regime),
            "vol_regime": float(c_vol_regime),
            "trad_RegimeTransition": float(c_regime_transition),
            "killzone": float(c_killzone),
        }
        return clamp(score), contrib
