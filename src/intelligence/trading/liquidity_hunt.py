"""trad_LiquidityHunt — Trade the sweep of named BSL/SSL liquidity pools.

Gates on smc_LiquidityPools significance >= 0.60 AND smc_LiquiditySweeps reclaim.
Only fires when the sweep was at a meaningful institutional level — not random swings.
Direction: BSL sweep → short, SSL sweep → long.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr
from .confidence_utils import capture_signal_features, compose_confidence
from .exhaustion_utils import apply_exhaustion_boost
from .plugin_utils import extract_ohlcv, no_signal


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
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=100),)
    regime_type: str = "trend"
    _state: dict = field(default_factory=dict)

    MIN_SIGNIFICANCE: float = 0.60

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        result = extract_ohlcv(frames, self.min_lookback)
        if result is None:
            return no_signal()
        open_, high, low, close = result

        features = frames.get("features") or {}

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

        atr = get_atr(features)
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

        # Stop: beyond swept level with small buffer
        if direction == -1:
            stop = swept_level + atr * 0.30
        else:
            stop = swept_level - atr * 0.30

        # Targets
        if direction == -1:
            t1 = entry - atr * 1.5
            t2 = entry - atr * 3.0
            # T2 refinement: use ssl_level as natural target if closer than 3R
            if ssl_level > 0 and ssl_level < entry - atr * 1.0:
                t2 = ssl_level
        else:
            t1 = entry + atr * 1.5
            t2 = entry + atr * 3.0
            if bsl_level > 0 and bsl_level > entry + atr * 1.0:
                t2 = bsl_level

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

        price_in_premium = float(features.get("price_in_premium", -1))
        if direction == -1 and price_in_premium == 1.0:
            confidence += 0.06
            supporting.append("premium_aligned")
        elif direction == 1 and price_in_premium == 0.0:
            confidence += 0.06
            supporting.append("discount_aligned")

        # fvg_type/ob_type are explicitly reset to 0.0 by their plugins when inactive,
        # so matching direction (±1) is sufficient — no separate detection flag needed.
        fvg_type = float(features.get("fvg_type", 0.0))
        if fvg_type == float(direction):
            confidence += 0.08
            supporting.append("fvg_aligned")

        ob_type = float(features.get("ob_type", 0.0))
        if ob_type == float(direction):
            confidence += 0.06
            supporting.append("order_block_aligned")

        choch = float(features.get("choch_detected", 0.0))
        bos = float(features.get("bos_detected", 0.0))
        bos_dir = float(features.get("bos_direction", 0.0))
        if choch == 1.0:
            confidence += 0.10
            supporting.append("choch_confirmed")
        elif bos == 1.0 and bos_dir == float(direction):
            confidence += 0.05
            supporting.append("bos_confirmed")

        ctf = float(features.get("ctf_score", 0.0))
        if abs(ctf) > 0.3 and math.copysign(1, ctf) == direction:
            confidence += 0.05
            supporting.append("ctf_aligned")

        in_demand = float(features.get("in_demand_zone", 0.0))
        in_supply = float(features.get("in_supply_zone", 0.0))
        if direction == -1 and in_supply == 1.0:
            confidence += 0.05
            supporting.append("supply_zone_aligned")
        elif direction == 1 and in_demand == 1.0:
            confidence += 0.05
            supporting.append("demand_zone_aligned")
        if direction == -1 and in_demand == 1.0:
            confidence -= 0.10
            supporting.append("penalty_demand_zone_opposing")
        elif direction == 1 and in_supply == 1.0:
            confidence -= 0.10
            supporting.append("penalty_supply_zone_opposing")

        confidence, supporting = apply_exhaustion_boost(features, direction, confidence, supporting)
        confidence = compose_confidence(confidence)

        sig_type = "liquidity_hunt_long" if direction == 1 else "liquidity_hunt_short"
        signal = {
            "signal_type": sig_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": round(stop, 2),
            "targets": [round(t1, 2), round(t2, 2)],
            "confidence": confidence,
            "supporting_factors": supporting,
        }
        signal["_shadow"] = capture_signal_features(
            features, direction, "smc", signal["confidence"],
        )
        return signal

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = LiquidityHuntPlugin()
