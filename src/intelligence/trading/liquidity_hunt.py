"""trad_LiquidityHunt — Trade the sweep of named BSL/SSL liquidity pools.

Gates on smc_LiquidityPools significance >= 0.60 AND smc_LiquiditySweeps reclaim.
Only fires when the sweep was at a meaningful institutional level — not random swings.
Direction: BSL sweep → short, SSL sweep → long.

Renaissance principles:
- Structural stop hierarchy via frame_trade() (no arbitrary ATR multipliers)
- Zone correction prevents stopped_at_entry outcomes
- Tick-size validation at emission gate
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import capture_signal_features, compose_confidence
from .plugin_utils import extract_ohlcv, no_signal
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade


@dataclass
class LiquidityHuntPlugin:
    """I7 signal: sweep of named liquidity pool + reversal confirmation."""

    name: str = "trad_LiquidityHunt"
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
    min_lookback: int = 30
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "smc", "liquidity"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    regime_type: str = "trend"
    requires_i6_confluence: bool = True
    _state: dict = field(default_factory=dict)

    MIN_SIGNIFICANCE: float = 0.60

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        result = extract_ohlcv(frames, self.min_lookback)
        if result is None:
            return no_signal()
        open_, high, low, close = result

        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
            **(frames.get("i6") or {}),
        }

        bsl_sig = float(features.get("bsl_significance", 0.0))
        ssl_sig = float(features.get("ssl_significance", 0.0))

        # Gate 1: sweep must be detected and reclaimed
        sweep_detected = float(features.get("sweep_detected", 0.0))
        sweep_reclaimed = float(features.get("sweep_reclaimed", 0.0))
        if sweep_detected != 1.0 or sweep_reclaimed != 1.0:
            return no_signal()

        sweep_type = float(features.get("sweep_type", 0.0))
        sweep_level = float(features.get("sweep_level", 0.0))
        bsl_level = float(features.get("bsl_level", 0.0))
        ssl_level = float(features.get("ssl_level", 0.0))

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        # Gate 3: sweep was at the named level (within ATR*0.75)
        tol = atr * 0.75
        hit_bsl = bsl_level > 0 and abs(sweep_level - bsl_level) <= tol
        hit_ssl = ssl_level > 0 and abs(sweep_level - ssl_level) <= tol

        if sweep_type < 0 and hit_bsl:
            direction = -1  # BSL swept → smart money sells → short
            significance = bsl_sig
            swept_level = bsl_level
        elif sweep_type > 0 and hit_ssl:
            direction = 1  # SSL swept → smart money buys → long
            significance = ssl_sig
            swept_level = ssl_level
        else:
            return no_signal()

        # Gate 3b: swept level must be a named institutional level
        if significance < self.MIN_SIGNIFICANCE:
            return no_signal()

        entry = float(close[-1])
        supporting: list[str] = ["named_pool_reclaimed"]

        # Renaissance: Use frame_trade() for structural stop hierarchy
        sig_type = "liquidity_hunt_long" if direction == 1 else "liquidity_hunt_short"
        tf = frame_trade(sig_type, direction, entry, features, atr, regime_type=self.regime_type)
        if not tf.viable:
            return no_signal()

        # Confidence scoring
        confidence = 0.55

        if significance >= 1.00:
            confidence += 0.12
            supporting.append("pwh_pwl_level")
        elif significance >= 0.85:
            confidence += 0.08
            supporting.append("pdh_pdl_level")
        elif significance >= 0.75:
            confidence += 0.05
            supporting.append("equal_levels_3plus")

        confidence = compose_confidence(confidence)

        return make_signal_from_frame(
            tf,
            symbol=frames.get("symbol", ""),
            timeframe=features.get("timeframe", ""),
            timestamp=features.get("timestamp", ""),
            signal_type=sig_type,
            setup_plugin=self.name,
            direction=direction,
            confidence=confidence,
            regime_context="any",
            supporting_factors=supporting,
            features_snapshot=capture_signal_features(features, direction, "smc", confidence),
        )

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = LiquidityHuntPlugin()
