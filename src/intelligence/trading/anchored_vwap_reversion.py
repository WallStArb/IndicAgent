"""trad_AnchoredVWAPReversion — I7 mean-reversion setup consuming I4 AnchoredVWAP fields.

Fires when price has deviated significantly from session VWAP in a ranging,
mean-reverting regime. Uses statistical sigma thresholds, HMM regime gating,
and Hurst exponent quality filtering.

Renaissance principles:
- Segment relentlessly: fires only in ranging regime (hmm_regime=0)
- Earn the right through proof: sigma threshold (|σ| > 1.5) + hurst < 0.55 required
- Instrument everything: sigma magnitude, velocity, hurst quality all logged
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from ..plugins import InputSpec
from ..utils import guard_intraday_only
from .trade_framer import frame_trade


@dataclass
class AnchoredVWAPReversionPlugin:
    """Mean-reversion setup: fires when session_vwap_deviation_sigma > ±1.5 in a ranging regime.

    Gates:
    - |session_vwap_deviation_sigma| >= 1.5 (price significantly displaced from VWAP)
    - hmm_regime == 0 (ranging — NOT trending)
    - hurst_exponent < 0.55 (sub-random walk confirms mean-reversion tendency)

    Direction:
    - sigma > 0 (price above VWAP) → short (reversion down)
    - sigma < 0 (price below VWAP) → long (reversion up)

    Targets: T1 = session_vwap, T2 = opposite VWAP band
    """

    name: str = "trad_AnchoredVWAPReversion"
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
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "mean_reversion"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=120),)
    regime_type: str = "mean_reversion"

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        if not guard_intraday_only(frames):
            return self._no_signal()

        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return self._no_signal()

        # ── Gate: required I4 VWAP fields ────────────────────────────────────
        sigma = features.get("session_vwap_deviation_sigma")
        hmm = features.get("hmm_regime")
        hurst = features.get("hurst_exponent")

        if sigma is None or hmm is None or hurst is None:
            return self._no_signal()

        sigma = float(sigma)
        hmm = int(hmm)
        hurst = float(hurst)

        # ── Gate: sigma threshold ─────────────────────────────────────────────
        if abs(sigma) < 1.5:
            return self._no_signal()

        # ── Gate: must be ranging (hmm_regime == 0) ───────────────────────────
        if hmm != 0:
            return self._no_signal()

        # ── Gate: hurst must confirm mean-reversion tendency ─────────────────
        if hurst >= 0.55:
            return self._no_signal()

        # ── Direction ─────────────────────────────────────────────────────────
        # Short when price above VWAP (sigma > 0), long when below (sigma < 0)
        direction = -1 if sigma > 0 else 1

        # ── ATR ───────────────────────────────────────────────────────────────
        atr = float(features.get("atr_14", 0.0))
        if atr <= 0:
            high = df["high"].to_numpy(dtype=float)
            low = df["low"].to_numpy(dtype=float)
            atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            return self._no_signal()

        # ── Entry (current close) ─────────────────────────────────────────────
        close = df["close"].to_numpy(dtype=float)
        entry = float(close[-1])

        # ── Trade frame for stop/targets ──────────────────────────────────────
        setup_type = "vwap_reversion_short" if direction == -1 else "vwap_reversion_long"
        frame = frame_trade(
            setup_type=setup_type,
            direction=direction,
            entry=entry,
            features=features,
            atr=atr,
        )
        if not frame.viable:
            return self._no_signal()

        # ── Override targets with VWAP levels ────────────────────────────────
        session_vwap = float(features.get("session_vwap", 0.0))
        avwap_upper = float(features.get("avwap_upper_band", 0.0))
        avwap_lower = float(features.get("avwap_lower_band", 0.0))

        targets: list[float] = []
        if session_vwap > 0:
            targets.append(round(session_vwap, 2))
        else:
            targets.append(round(frame.targets[0].price if frame.targets else 0.0, 2))

        # T2: opposite VWAP band (short → lower band target, long → upper band target)
        if direction == -1 and avwap_lower > 0:
            targets.append(round(avwap_lower, 2))
        elif direction == 1 and avwap_upper > 0:
            targets.append(round(avwap_upper, 2))
        elif len(frame.targets) > 1:
            targets.append(round(frame.targets[1].price, 2))

        # ── Confidence scoring ────────────────────────────────────────────────
        # sigma_magnitude: 0.3 weight — how far beyond threshold
        sigma_magnitude = min(1.0, (abs(sigma) - 1.5) / 1.5)

        # velocity: 0.25 weight — moving TOWARD vwap (opposite direction to sigma)
        velocity = float(features.get("session_vwap_deviation_velocity", 0.0))
        # For short (sigma>0, direction=-1): velocity should be negative (sigma shrinking)
        # For long (sigma<0, direction=1): velocity should be positive (sigma recovering)
        if direction == -1:
            velocity_ok = velocity < 0
        else:
            velocity_ok = velocity > 0
        velocity_score = 0.7 if velocity_ok else 0.3

        # hurst_quality: 0.25 weight — how far below 0.55 threshold
        hurst_mr_quality = float(features.get("hurst_mr_quality", 1.0 - hurst))
        hurst_quality = min(1.0, max(0.0, hurst_mr_quality))

        # vol_stability: 0.2 weight — vol_regime near 0.5 = stable
        vol_regime = float(features.get("vol_regime", 0.5))
        vol_stability = 1.0 - abs(vol_regime - 0.5) * 2.0

        raw_conf = (
            0.30 * sigma_magnitude
            + 0.25 * velocity_score
            + 0.25 * hurst_quality
            + 0.20 * vol_stability
        )
        confidence = round(min(1.0, max(0.0, raw_conf)), 4)

        # ── Supporting factors ────────────────────────────────────────────────
        supporting: list[str] = [
            f"session_vwap_deviation_sigma={sigma:.3f}",
            f"session_vwap_deviation_velocity={velocity:.4f}",
            f"hurst_exponent={hurst:.3f}",
        ]
        if velocity_ok:
            supporting.append("velocity_toward_vwap")
        if sigma_magnitude > 0.5:
            supporting.append("sigma_extreme")

        regime_ctx = "ranging"

        return {
            "signal_type": setup_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": round(frame.stop, 2),
            "targets": targets,
            "confidence": confidence,
            "regime_context": regime_ctx,
            "supporting_factors": supporting,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}


plugin = AnchoredVWAPReversionPlugin()
