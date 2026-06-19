"""I7 Mean Reversion setup detection plugin.

DUAL-GATE DIAGNOSIS (Phase 126):
SQL probe on 2,222,468 bars (30-day window):
  Gate A (|trend_regime| < 0.4): 120,648 bars pass (5.4%)
  Gate B (|kalman_price_position| >= 1.0): 276,144 bars pass (12.4%)
  Both gates: 114 bars (0.0051%) -- mutual exclusion confirmed

Root cause: kalman_price_position is near-zero in ranging regimes (p50 = 2.57e-13 when Gate A
passes). In a ranging regime, price oscillates around Kalman fair value, so displacement is
inherently low. The two gates select for contradictory market states.

Relaxing Gate B to 0.1 yields 1,012 qualifying bars (0.046%) -- still below the 0.01% threshold
required to generate >100 fires/30-day window (would need ~2x volume to get 10 signals/session).

Disposition: shadow_only=True. Parked for redesign. Recommended replacement gate: use hmm_regime=0
(ranging, not |trend_regime| < 0.4) as the primary regime gate, then standard RSI/divergence
detection without a kalman displacement requirement. See APR key:
  threshold.mean_reversion.trend_regime_max = 0.2  (created in migration 133)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr_with_floor_from_frames
from .confidence import (
    _validate_weights_sum,
    compose_confidence,
)
from .exhaustion_utils import apply_exhaustion_boost
from .plugin_utils import extract_ohlcv, no_signal, signal_type_for_direction
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade


@dataclass
class MeanReversionPlugin:
    """Mean-reversion setup: fires when regime = ranging + price at RSI extreme or divergence.

    Gates on |trend_regime| < 0.4 (must NOT be trending).
    Long when RSI < 35 or bullish divergence present.
    Short when RSI > 65 or bearish divergence present.
    Targets Bollinger middle band and nearest S/R levels.
    """

    name: str = "trad_MeanReversion"
    shadow_only: bool = True  # dual-gate mutual exclusion diagnosed; see module docstring
    outputs: frozenset[str] = frozenset(
        {
            "signal_type",
            "direction",
            "entry_price",
            "stop_loss",
            "targets",
            "confidence",
            "regime_context",
            "supporting_factors",
        }
    )
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "mean_reversion"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    regime_type: str = "mean_reversion"
    regime_threshold: float = 0.4
    _state: dict = field(default_factory=dict)
    _config_service: Any = field(default=None, compare=False, repr=False)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
            **(frames.get("i6") or {}),
        }
        features["timeframe"] = frames.get("timeframe") or frames.get("__timeframe__", "")

        # OPTIMIZATION (Phase 48): Check regime gate BEFORE expensive OHLCV extraction
        # TODO: Apply this pattern to remaining 34/36 I7 plugins (2/36 optimized: trend_following, mean_reversion)  # noqa: E501
        # Pattern: Check cheap regime gates (dict lookups) before expensive extract_ohlcv() (numpy conversion)  # noqa: E501
        # Estimated benefit: Skip ~144 numpy conversions per bar (80% early exit rate)
        # Remaining plugins to optimize: All other I7 plugins except trend_following.py and this file  # noqa: E501
        cfg = self._config_service
        # APR key: threshold.mean_reversion.trend_regime_max (migration 133)
        # Relaxed from 0.4 to 0.2 — but diagnosis shows kalman_price_position gate still mutually
        # exclusive in ranging (see module docstring). Plugin parked shadow_only=True.
        trend_regime_max = (
            cfg.get_sync("threshold.mean_reversion.trend_regime_max", 0.2) if cfg else 0.2
        )
        trend_regime = features.get("trend_regime", 0.0)
        if abs(trend_regime) >= trend_regime_max:
            return no_signal()

        # Regime gate passed - now extract OHLCV (expensive numpy conversion)
        result = extract_ohlcv(frames, self.min_lookback)
        if result is None:
            return no_signal()
        open_, high, low, close = result

        # ── Gate: price must be displaced from Kalman fair value ──
        kalman_pos = features.get("kalman_price_position")
        if kalman_pos is not None and abs(float(kalman_pos)) < 1.0:
            return no_signal()

        # ── Read features ──
        rsi = features.get("rsi_14", 50.0)
        rsi_div_bull = features.get("rsi_div_bullish", 0.0)
        rsi_div_bear = features.get("rsi_div_bearish", 0.0)
        vol_regime = features.get("vol_regime", 0.5)
        sr_support = features.get("sr_nearest_support", None)
        sr_resistance = features.get("sr_nearest_resistance", None)

        price = float(close[-1])

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        # ── Direction detection ──
        long_rsi = rsi < 35
        long_div = rsi_div_bull > 0.3
        short_rsi = rsi > 65
        short_div = rsi_div_bear > 0.3

        if long_rsi or long_div:
            direction = 1
        elif short_rsi or short_div:
            direction = -1
        else:
            return no_signal()

        entry = price
        signal_type = signal_type_for_direction("reversion", direction)

        tf = frame_trade(signal_type, direction, entry, features, atr, regime_type=self.regime_type)
        if not tf.viable:
            return no_signal()

        # ── Confidence scoring ──
        # RSI extremeness (0.3 weight)
        if direction == 1:
            rsi_extreme = min(1.0, max(0.0, (35.0 - rsi) / 35.0)) if rsi < 35 else 0.0
        else:
            rsi_extreme = min(1.0, max(0.0, (rsi - 65.0) / 35.0)) if rsi > 65 else 0.0

        # Divergence (0.3 weight)
        div_score = min(1.0, rsi_div_bull if direction == 1 else rsi_div_bear)

        # Vol regime stability (0.2 weight) — closer to 0.5 = more stable ranging
        vol_stability = 1.0 - min(1.0, abs(vol_regime - 0.5) * 2.0)

        # S/R proximity (0.2 weight)
        if direction == 1 and sr_support is not None and sr_support > 0:
            sr_prox = max(0.0, 1.0 - abs(price - sr_support) / (atr * 3.0))
        elif direction == -1 and sr_resistance is not None and sr_resistance > 0:
            sr_prox = max(0.0, 1.0 - abs(price - sr_resistance) / (atr * 3.0))
        else:
            sr_prox = 0.0

        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "rsi_extreme_score": round(rsi_extreme, 4),
            "div_score": round(div_score, 4),
            "vol_stability": round(vol_stability, 4),
            "sr_prox": round(sr_prox, 4),
        }

        w_rsi = cfg.get_sync("weights.mean_reversion.rsi_extreme", 0.30) if cfg else 0.30
        w_div = cfg.get_sync("weights.mean_reversion.div_score", 0.30) if cfg else 0.30
        w_vol = cfg.get_sync("weights.mean_reversion.vol_stability", 0.20) if cfg else 0.20
        w_sr = cfg.get_sync("weights.mean_reversion.sr_proximity", 0.20) if cfg else 0.20
        _validate_weights_sum(
            {
                "rsi_extreme": w_rsi,
                "div_score": w_div,
                "vol_stability": w_vol,
                "sr_proximity": w_sr,
            },
            "trad_MeanReversion",
        )
        raw_conf = w_rsi * rsi_extreme + w_div * div_score + w_vol * vol_stability + w_sr * sr_prox

        # ── Supporting factors ──
        supporting = []
        if long_rsi or short_rsi:
            supporting.append("rsi_extreme")
        if long_div or short_div:
            supporting.append("rsi_divergence")
        if sr_prox > 0.3:
            supporting.append("near_sr_level")
        if vol_stability > 0.5:
            supporting.append("stable_vol_regime")

        raw_conf, supporting = apply_exhaustion_boost(features, direction, raw_conf, supporting)
        confidence = compose_confidence(raw_conf)

        regime_ctx = "ranging"

        signal = make_signal_from_frame(
            tf,
            symbol=frames.get("symbol", ""),
            timeframe=features.get("timeframe", ""),
            timestamp=features.get("timestamp", ""),
            signal_type=signal_type,
            setup_plugin=self.name,
            direction=direction,
            confidence=confidence,
            regime_context=regime_ctx,
            supporting_factors=supporting,
            factor_scores=factor_scores,
        )
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = MeanReversionPlugin()
