"""I7 Liquidity Sweep Reclaim setup detection plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr
from .confidence_utils import capture_signal_features, compose_confidence
from .exhaustion_utils import apply_exhaustion_boost
from .plugin_utils import extract_ohlcv, no_signal


@dataclass
class LiquiditySweepReclaimPlugin:
    """Highest-conviction SMC setup: fires when a liquidity sweep is reclaimed.

    Gate: sweep_detected == 1.0 AND sweep_reclaimed == 1.0.
    Optional confidence boosts from FVG, order block, and cross-timeframe confluence.
    """

    name: str = "trad_LiquiditySweepReclaim"
    outputs: frozenset[str] = frozenset(
        {
            "signal_type",
            "direction",
            "entry_price",
            "stop_loss",
            "targets",
            "confidence",
            "supporting_factors",
        }
    )
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "smc", "sweep"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=100),)
    regime_type: str = "mean_reversion"
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        result = extract_ohlcv(frames, self.min_lookback)
        if result is None:
            return no_signal()
        open_, high, low, close = result

        features = frames.get("features") or {}

        sweep_detected = features.get("sweep_detected", 0.0)
        sweep_reclaimed = features.get("sweep_reclaimed", 0.0)

        if sweep_detected != 1.0 or sweep_reclaimed != 1.0:
            return no_signal()

        sweep_type = features.get("sweep_type", 0.0)
        sweep_level = features.get("sweep_level", 0.0)

        if sweep_type == 0.0:
            return no_signal()

        direction = 1 if sweep_type > 0 else -1

        atr = get_atr(features)
        if atr is None:
            return no_signal()

        entry = float(close[-1])

        # Stop loss
        if direction == 1:
            stop = sweep_level - atr * 0.5
        else:
            stop = sweep_level + atr * 0.5

        # Targets
        if direction == 1:
            t1 = entry + atr * 1.5
            t2 = entry + atr * 3.0
        else:
            t1 = entry - atr * 1.5
            t2 = entry - atr * 3.0
        targets = [round(t1, 2), round(t2, 2)]

        # Confidence scoring
        confidence = 0.55
        supporting = ["sweep_reclaimed"]

        fvg_type = features.get("fvg_type", 0.0)
        if fvg_type == float(direction):
            confidence += 0.15
            supporting.append("fvg_confirmed")

        ob_type = features.get("ob_type", 0.0)
        if ob_type == float(direction):
            confidence += 0.10
            supporting.append("order_block_confirmed")

        ctf_score = features.get("ctf_score", 0.0)
        if abs(ctf_score) > 0.3:
            # Renaissance principle: weight by magnitude, not binary gate
            # Stronger CTF alignment = larger boost (0.0 to 0.10 range)
            ctf_boost = 0.05 * min(2.0, abs(ctf_score) / 0.5)
            confidence += ctf_boost
            if ctf_boost > 0.04:
                supporting.append("strong_cross_timeframe_aligned")
            else:
                supporting.append("cross_timeframe_aligned")

        # Named pool significance boost
        sweep_type_val = features.get("sweep_type", 0.0)
        if sweep_type_val > 0:  # bullish sweep (SSL swept)
            sig = float(features.get("ssl_significance", 0.0))
            if sig >= 0.60:
                confidence += min(0.10, sig * 0.12)
                supporting.append(f"named_ssl_level_{sig:.2f}")
        elif sweep_type_val < 0:  # bearish sweep (BSL swept)
            sig = float(features.get("bsl_significance", 0.0))
            if sig >= 0.60:
                confidence += min(0.10, sig * 0.12)
                supporting.append(f"named_bsl_level_{sig:.2f}")

        confidence, supporting = apply_exhaustion_boost(features, direction, confidence, supporting)
        confidence = compose_confidence(confidence)

        signal_type = "sweep_reclaim_long" if direction == 1 else "sweep_reclaim_short"

        signal = {
            "signal_type": signal_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": round(stop, 2),
            "targets": targets,
            "confidence": confidence,
            "supporting_factors": supporting,
        }
        signal["_shadow"] = capture_signal_features(
            features, direction, "smc", signal["confidence"],
        )
        return signal

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = LiquiditySweepReclaimPlugin()
