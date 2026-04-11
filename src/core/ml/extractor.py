"""FeatureExtractor — identical extraction at training time and inference time.

Two entry points, same logic:
  from_event(IntelligenceEvent) → FeatureVector  (real-time path)
  from_row(dict)                → FeatureVector  (training/batch path)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.core.ml.features import FeatureVector

if TYPE_CHECKING:
    from src.intelligence.schemas import IntelligenceEvent


def _safe(obj: Any, attr: str) -> Any:
    """Safely get attribute — returns None if obj is None or attr missing."""
    if obj is None:
        return None
    return getattr(obj, attr, None)


class FeatureExtractor:
    """Extract FeatureVector from IntelligenceEvent (inference) or dict row (training)."""

    def from_event(self, event: IntelligenceEvent) -> FeatureVector:
        """Real-time path: IntelligenceEvent → FeatureVector."""
        i1 = _safe(event, "i1")
        i2 = _safe(event, "i2")
        i3 = _safe(event, "i3")
        i4 = _safe(event, "i4")
        i5 = _safe(event, "i5")
        i6 = _safe(event, "i6")
        i7 = _safe(event, "i7")

        cis = _safe(i7, "cis")

        return FeatureVector(
            ts=event.ts.isoformat() if hasattr(event.ts, "isoformat") else str(event.ts),
            symbol=event.symbol,
            tf=event.tf,
            # i1
            atr=_safe(i1, "atr_14"),
            atr_pct=_safe(i1, "atr_pct"),
            rsi=_safe(i1, "rsi_14"),
            rsi_slope=_safe(i1, "rsi_slope"),
            adx=_safe(i1, "adx"),
            adx_slope=_safe(i1, "adx_slope"),
            macd=_safe(i1, "macd"),
            macd_signal=_safe(i1, "macd_signal"),
            macd_hist=_safe(i1, "macd_hist"),
            bb_pct_b=_safe(i1, "bb_pct_b"),
            bb_width=_safe(i1, "bb_width"),
            ema_9=_safe(i1, "ema_9"),
            ema_21=_safe(i1, "ema_21"),
            ema_50=_safe(i1, "ema_50"),
            ema_200=_safe(i1, "ema_200"),
            ema_9_21_cross=_safe(i1, "ema_9_21_cross"),
            obv_slope=_safe(i1, "obv_slope"),
            volume_ratio=_safe(i1, "volume_ratio"),
            # i2
            pattern_score=_safe(i2, "pattern_score"),
            pattern_type=_safe(i2, "pattern_type"),
            candle_body_pct=_safe(i2, "candle_body_pct"),
            candle_wick_ratio=_safe(i2, "candle_wick_ratio"),
            # i3
            fvg_score=_safe(i3, "fvg_score"),
            ob_score=_safe(i3, "ob_score"),
            liquidity_sweep_score=_safe(i3, "liquidity_sweep_score"),
            choch_score=_safe(i3, "choch_score"),
            order_flow_imbalance=_safe(i3, "order_flow_imbalance"),
            delta_pct=_safe(i3, "delta_pct"),
            # i4
            hmm_regime=_safe(i4, "hmm_regime"),
            hmm_prob=_safe(i4, "hmm_regime_prob"),
            hurst_exponent=_safe(i4, "hurst_exponent"),
            kalman_trend=_safe(i4, "kalman_trend"),
            kalman_slope=_safe(i4, "kalman_slope"),
            vol_percentile=_safe(i4, "vol_percentile"),
            garch_vol_ratio=_safe(i4, "garch_vol_ratio"),
            vwap_distance_atr=_safe(i4, "vwap_distance_atr"),
            poc_distance_atr=_safe(i4, "poc_distance_atr"),
            price_in_value_area=_safe(i4, "price_in_value_area"),
            # i5
            zscore_20=_safe(i5, "zscore_20"),
            zscore_50=_safe(i5, "zscore_50"),
            autocorr_1=_safe(i5, "autocorr_1"),
            autocorr_5=_safe(i5, "autocorr_5"),
            rolling_sharpe_20=_safe(i5, "rolling_sharpe_20"),
            rolling_beta=_safe(i5, "rolling_beta"),
            # i6
            ctf_score=_safe(i6, "ctf_score"),
            ctf_trend_alignment=_safe(i6, "ctf_trend_alignment"),
            ctf_regime_agreement=_safe(i6, "ctf_regime_agreement"),
            ctf_fvg_alignment=_safe(i6, "ctf_fvg_alignment"),
            ctf_ob_alignment=_safe(i6, "ctf_ob_alignment"),
            ctf_timeframes_aligned=_safe(i6, "ctf_timeframes_aligned"),
            ctf_structure_alignment=_safe(i6, "ctf_structure_alignment"),
            # i7
            cis_score=_safe(cis, "score"),
            winner_plugin=None,  # set by caller if needed
            winner_confidence=None,
            winner_direction=None,
            calibrated_confidence=None,
            kalman_smoothed_confidence=None,
            tod_multiplier=None,
        )

    def from_row(self, row: dict[str, Any]) -> FeatureVector:
        """Training/batch path: DB dict row → FeatureVector.

        Column names match intelligence_features JSONB structure flattened.
        """
        return FeatureVector(
            ts=str(row.get("ts", "")),
            symbol=str(row.get("symbol", "")),
            tf=str(row.get("tf", "")),
            atr=row.get("atr"),
            atr_pct=row.get("atr_pct"),
            rsi=row.get("rsi"),
            rsi_slope=row.get("rsi_slope"),
            adx=row.get("adx"),
            adx_slope=row.get("adx_slope"),
            macd=row.get("macd"),
            macd_signal=row.get("macd_signal"),
            macd_hist=row.get("macd_hist"),
            bb_pct_b=row.get("bb_pct_b"),
            bb_width=row.get("bb_width"),
            ema_9=row.get("ema_9"),
            ema_21=row.get("ema_21"),
            ema_50=row.get("ema_50"),
            ema_200=row.get("ema_200"),
            ema_9_21_cross=row.get("ema_9_21_cross"),
            obv_slope=row.get("obv_slope"),
            volume_ratio=row.get("volume_ratio"),
            pattern_score=row.get("pattern_score"),
            pattern_type=row.get("pattern_type"),
            candle_body_pct=row.get("candle_body_pct"),
            candle_wick_ratio=row.get("candle_wick_ratio"),
            fvg_score=row.get("fvg_score"),
            ob_score=row.get("ob_score"),
            liquidity_sweep_score=row.get("liquidity_sweep_score"),
            choch_score=row.get("choch_score"),
            order_flow_imbalance=row.get("order_flow_imbalance"),
            delta_pct=row.get("delta_pct"),
            hmm_regime=row.get("hmm_regime"),
            hmm_prob=row.get("hmm_prob"),
            hurst_exponent=row.get("hurst_exponent"),
            kalman_trend=row.get("kalman_trend"),
            kalman_slope=row.get("kalman_slope"),
            vol_percentile=row.get("vol_percentile"),
            garch_vol_ratio=row.get("garch_vol_ratio"),
            vwap_distance_atr=row.get("vwap_distance_atr"),
            poc_distance_atr=row.get("poc_distance_atr"),
            price_in_value_area=row.get("price_in_value_area"),
            zscore_20=row.get("zscore_20"),
            zscore_50=row.get("zscore_50"),
            autocorr_1=row.get("autocorr_1"),
            autocorr_5=row.get("autocorr_5"),
            rolling_sharpe_20=row.get("rolling_sharpe_20"),
            rolling_beta=row.get("rolling_beta"),
            ctf_score=row.get("ctf_score"),
            ctf_trend_alignment=row.get("ctf_trend_alignment"),
            ctf_regime_agreement=row.get("ctf_regime_agreement"),
            ctf_fvg_alignment=row.get("ctf_fvg_alignment"),
            ctf_ob_alignment=row.get("ctf_ob_alignment"),
            ctf_timeframes_aligned=row.get("ctf_timeframes_aligned"),
            ctf_structure_alignment=row.get("ctf_structure_alignment"),
            cis_score=row.get("cis_score"),
            winner_plugin=row.get("winner_plugin"),
            winner_confidence=row.get("winner_confidence"),
            winner_direction=row.get("winner_direction"),
            calibrated_confidence=row.get("calibrated_confidence"),
            kalman_smoothed_confidence=row.get("kalman_smoothed_confidence"),
            tod_multiplier=row.get("tod_multiplier"),
        )
