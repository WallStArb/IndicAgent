"""FeatureVector — the single source of truth for ML features.

frozen=True ensures no mutation after construction.
All fields are Optional[float/int/str] — missing values are None (not imputed here).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FeatureVector(BaseModel):
    """Frozen feature vector. One instance per (symbol, tf, bar).

    Fields map directly to intelligence_features JSONB tiers i1-i7.
    Adding a field here is the ONLY place it needs to be added — extractor
    and training query both use this schema.
    """

    model_config = ConfigDict(frozen=True)

    # Identity
    ts: str  # ISO-8601 UTC timestamp
    symbol: str
    tf: str

    # ─── I1: Technical Indicators ───────────────────────────────────────────
    atr: float | None = None  # ATR(14)
    atr_pct: float | None = None  # ATR as % of close
    rsi: float | None = None  # RSI(14)
    rsi_slope: float | None = None  # RSI rate of change
    adx: float | None = None  # ADX(14)
    adx_slope: float | None = None
    macd: float | None = None  # MACD line
    macd_signal: float | None = None
    macd_hist: float | None = None
    bb_pct_b: float | None = None  # Bollinger %B
    bb_width: float | None = None  # Bollinger band width normalized
    ema_9: float | None = None
    ema_21: float | None = None
    ema_50: float | None = None
    ema_200: float | None = None
    ema_9_21_cross: float | None = None  # ema_9 - ema_21 normalized by ATR
    obv_slope: float | None = None
    volume_ratio: float | None = None  # current / 20-bar average

    # ─── I2: Pattern Recognition ────────────────────────────────────────────
    pattern_score: float | None = None
    pattern_type: str | None = None  # e.g. "hammer", "engulfing"
    candle_body_pct: float | None = None
    candle_wick_ratio: float | None = None

    # ─── I3: SMC / Order Flow ───────────────────────────────────────────────
    fvg_score: float | None = None
    ob_score: float | None = None
    liquidity_sweep_score: float | None = None
    choch_score: float | None = None
    order_flow_imbalance: float | None = None
    delta_pct: float | None = None  # buy_delta - sell_delta / total_volume

    # ─── I4: Context Classification ─────────────────────────────────────────
    hmm_regime: int | None = None  # 0=ranging, 1=trending_up, 2=trending_down
    hmm_prob: float | None = None  # HMM state probability
    hurst_exponent: float | None = None
    kalman_trend: float | None = None
    kalman_slope: float | None = None
    vol_percentile: float | None = None  # rolling 252-bar vol percentile
    garch_vol_ratio: float | None = None
    vwap_distance_atr: float | None = None  # (close - vwap) / ATR
    poc_distance_atr: float | None = None  # (close - poc) / ATR
    price_in_value_area: bool | None = None

    # ─── I5: Statistical / ML ───────────────────────────────────────────────
    zscore_20: float | None = None
    zscore_50: float | None = None
    autocorr_1: float | None = None
    autocorr_5: float | None = None
    rolling_sharpe_20: float | None = None
    rolling_beta: float | None = None

    # ─── I6: Cross-Timeframe Confluence ─────────────────────────────────────
    ctf_score: float | None = None
    ctf_trend_alignment: float | None = None
    ctf_regime_agreement: float | None = None
    ctf_fvg_alignment: float | None = None
    ctf_ob_alignment: float | None = None
    ctf_timeframes_aligned: float | None = None
    ctf_structure_alignment: float | None = None

    # ─── I7: Signal Metadata (for context, not direct ML features) ──────────
    cis_score: float | None = None
    winner_plugin: str | None = None
    winner_confidence: float | None = None
    winner_direction: int | None = None  # 1=long, -1=short
    calibrated_confidence: float | None = None
    kalman_smoothed_confidence: float | None = None
    tod_multiplier: float | None = None  # time-of-day multiplier applied
