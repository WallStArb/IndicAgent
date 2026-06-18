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
from ..utils.gradient_utils import hmm_trending_weight
from .atr_utils import get_atr_with_floor_from_frames
from .confidence import (
    clamp01,
    compose_confidence,
    get_min_regime_weight,
    rel_volume_score,
)
from .plugin_utils import no_signal
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade


@dataclass
class LiquidityHuntPlugin:
    """I7 signal: sweep of named liquidity pool + reversal confirmation."""

    name: str = "trad_LiquidityHunt"
    shadow_only: bool = True
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
    _state: dict = field(default_factory=dict)

    MIN_SIGNIFICANCE: float = 0.60
    _config_service: Any = field(default=None, compare=False, repr=False)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        cfg = self._config_service
        significance_min = (
            cfg.get_sync("threshold.liquidity_hunt.significance_min", self.MIN_SIGNIFICANCE)
            if cfg
            else self.MIN_SIGNIFICANCE
        )

        df = frames.get("main")
        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
            **(frames.get("i6") or {}),
        }

        if df is None or len(df) < self.min_lookback:
            return no_signal()

        # ── Dual gate (before OHLCV access) ─────────────────────────────────
        # Gate 1: trend regime gate (LiquidityHunt is regime_type="trend")
        # Use the direction-specific form: block only if BOTH up AND down are below threshold
        if hmm_trending_weight(features) < get_min_regime_weight():
            return no_signal()

        bsl_sig = float(features.get("bsl_significance", 0.0))
        ssl_sig = float(features.get("ssl_significance", 0.0))

        # Gate 3: sweep must be detected and reclaimed
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

        # Gate 4: sweep was at the named level (within ATR*0.75)
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

        # Gate 5: swept level must be a named institutional level
        if significance < significance_min:
            return no_signal()

        # ── OHLCV access (after all gates) ───────────────────────────────────
        entry = float(df["close"].iloc[-1])
        supporting: list[str] = ["named_pool_reclaimed"]

        # Renaissance: Use frame_trade() for structural stop hierarchy
        sig_type = "liquidity_hunt_long" if direction == 1 else "liquidity_hunt_short"
        tf = frame_trade(sig_type, direction, entry, features, atr, regime_type=self.regime_type)
        if not tf.viable:
            return no_signal()

        # ── 4-factor intrinsic confidence composite ───────────────────────────
        # hunt_significance: how significant the swept institutional level is
        hunt_significance = clamp01((significance - significance_min) / (1.0 - significance_min))

        # rejection_reclaim_strength: how far price reclaimed through the swept level
        sweep_distance = abs(entry - swept_level)
        rejection_reclaim_strength = clamp01(sweep_distance / max(1e-9, atr))

        # volume_context: rel_volume confirmation
        volume_context = rel_volume_score(features)

        # structure_quality: significant level type bonus
        if significance >= 1.00:
            structure_quality = 1.0
            supporting.append("pwh_pwl_level")
        elif significance >= 0.85:
            structure_quality = 0.75
            supporting.append("pdh_pdl_level")
        elif significance >= 0.75:
            structure_quality = 0.55
            supporting.append("equal_levels_3plus")
        else:
            structure_quality = 0.35

        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "hunt_significance": round(hunt_significance, 4),
            "rejection_reclaim_strength": round(rejection_reclaim_strength, 4),
            "volume_context": round(volume_context, 4),
            "structure_quality": round(structure_quality, 4),
        }

        # Weights sum to 1.0
        raw_conf = (
            0.35 * hunt_significance
            + 0.30 * rejection_reclaim_strength
            + 0.20 * volume_context
            + 0.15 * structure_quality
        )
        confidence = compose_confidence(raw_conf)

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
            factor_scores=factor_scores,
        )

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = LiquidityHuntPlugin()
