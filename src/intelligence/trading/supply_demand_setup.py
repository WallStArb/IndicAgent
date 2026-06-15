"""trad_SupplyDemandSetup — Trade institutional supply/demand zone retests.

Fires when price enters a fresh/tested S/D zone and shows rejection.
Highest confidence when the full ICT Act 1-2-3 model is confirmed:
  sweep (Act 1) → FVG displacement (Act 2) → zone retest (Act 3).

Renaissance principles:
- Structural stop hierarchy via frame_trade() (no arbitrary ATR multipliers)
- Zone correction prevents stopped_at_entry outcomes
- Tick-size validation at emission gate
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from ..utils.gradient_utils import linear_ramp
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import capture_signal_features, compose_confidence, get_min_ctf_score
from .plugin_utils import extract_ohlcv, no_signal
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade


@dataclass
class SupplyDemandSetupPlugin:
    """I7 signal: price enters institutional S/D zone + rejection confirmation."""

    name: str = "trad_SupplyDemandSetup"
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
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "zones", "smc"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=50),)
    regime_type: str = "any"
    requires_i6_confluence: bool = True
    # Phase 126 IC audit: statistically anti-predictive on existing data
    # (IC=-0.020, hit_rate CI upper=0.175, n=8433); redesign required.
    shadow_only: bool = True
    _state: dict = field(default_factory=dict)
    _config_service: Any = field(default=None, compare=False, repr=False)

    MIN_FRESHNESS: float = 0.40

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

        in_demand = float(features.get("in_demand_zone", 0.0))
        in_supply = float(features.get("in_supply_zone", 0.0))

        # Gate 1: must be inside a zone
        if in_demand != 1.0 and in_supply != 1.0:
            return no_signal()

        # Gate 2: not both (ambiguous)
        if in_demand == 1.0 and in_supply == 1.0:
            return no_signal()

        if in_demand == 1.0:
            direction = 1
            freshness = float(features.get("demand_freshness", 0.0))
            strength = float(features.get("demand_strength", 0.0))
            zone_high = float(features.get("nearest_demand_high", 0.0))
            zone_low = float(features.get("nearest_demand_low", 0.0))
        else:
            direction = -1
            freshness = float(features.get("supply_freshness", 0.0))
            strength = float(features.get("supply_strength", 0.0))
            zone_high = float(features.get("nearest_supply_high", 0.0))
            zone_low = float(features.get("nearest_supply_low", 0.0))

        # Gate 3: freshness threshold
        if freshness < self.MIN_FRESHNESS:
            return no_signal()

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        entry = float(close[-1])
        supporting: list[str] = [f"{'demand' if direction == 1 else 'supply'}_zone_entry"]

        # Confidence scoring — continuous base from freshness (replaces 3-step tiers)
        cfg = self._config_service
        base_conf = cfg.get_sync("weights.supply_demand.base_conf", 0.35) if cfg else 0.35
        freshness_scale = (
            cfg.get_sync("weights.supply_demand.freshness_scale", 0.23) if cfg else 0.23
        )
        confidence = base_conf + freshness_scale * linear_ramp(freshness, 0.40, 1.0)

        # Zone strength adjustment
        confidence += (strength - 0.5) * 0.20

        # Premium/discount alignment
        pip = float(features.get("price_in_premium", -1))
        if direction == 1 and pip == 0.0:
            confidence += 0.08
            supporting.append("discount_zone_aligned")
        elif direction == -1 and pip == 1.0:
            confidence += 0.08
            supporting.append("premium_zone_aligned")
        elif direction == 1 and pip == 1.0:
            confidence -= 0.06
        elif direction == -1 and pip == 0.0:
            confidence -= 0.06

        # *** ACT 1-2-3 MODEL ***
        sweep_det = float(features.get("sweep_detected", 0.0))
        sweep_recl = float(features.get("sweep_reclaimed", 0.0))
        sweep_type = float(features.get("sweep_type", 0.0))
        fvg_type = float(features.get("fvg_type", 0.0))

        act1 = sweep_det == 1.0 and sweep_recl == 1.0
        act1_dir = (direction == 1 and sweep_type == 1.0) or (
            direction == -1 and sweep_type == -1.0
        )
        act2 = fvg_type == float(direction)

        if act1 and act1_dir:
            if act2:
                confidence += 0.14
                supporting.append("act_1_2_3_confirmed")
            else:
                confidence += 0.07
                supporting.append("act_1_confirmed")

        if act2 and not act1:
            confidence += 0.09
            supporting.append("fvg_displacement")

        # Order block fully contained within zone
        ob_type = float(features.get("ob_type", 0.0))
        ob_top = float(features.get("ob_top", 0.0))
        ob_bottom = float(features.get("ob_bottom", 0.0))
        if (
            ob_type == float(direction)
            and ob_top > 0
            and ob_bottom >= zone_low
            and ob_top <= zone_high
        ):
            confidence += 0.08
            supporting.append("ob_zone_overlap")

        choch = float(features.get("choch_detected", 0.0))
        bos = float(features.get("bos_detected", 0.0))
        bos_dir = float(features.get("bos_direction", 0.0))
        if choch == 1.0:
            confidence += 0.09
            supporting.append("choch_confirmed")
        elif bos == 1.0 and bos_dir == float(direction):
            confidence += 0.05
            supporting.append("bos_confirmed")

        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        # Note: supply_demand uses additive confidence model; capture component contributions
        factor_scores = {
            "freshness_score": round(float(freshness), 4),
            "strength_score": round(float(strength), 4),
            "act123_confirmed": round(1.0 if (act1 and act1_dir and act2) else 0.0, 4),
            "zone_alignment_score": round(
                (
                    1.0
                    if (
                        "discount_zone_aligned" in supporting
                        or "premium_zone_aligned" in supporting
                    )
                    else 0.0
                ),
                4,
            ),
        }

        confidence = compose_confidence(confidence)

        # ECL annotations: ctf_score + zone_friction_score as context (Phase 123)
        _ctf_raw = features.get("ctf_score")
        ctf_score: float | None = float(_ctf_raw) if _ctf_raw is not None else None
        ctf_confirmed: bool | None = (
            (abs(ctf_score) >= get_min_ctf_score()) if ctf_score is not None else None
        )
        _zf_raw = features.get("zone_friction_score")
        zone_friction_score: float | None = float(_zf_raw) if _zf_raw is not None else None

        sig_type = "supply_demand_long" if direction == 1 else "supply_demand_short"

        # Renaissance: Use frame_trade() for structural stop hierarchy
        tf = frame_trade(sig_type, direction, entry, features, atr, regime_type=self.regime_type)
        if not tf.viable:
            return no_signal()

        ctx = capture_signal_features(features, direction, "smc", confidence)
        return make_signal_from_frame(
            tf,
            symbol="",
            timeframe="",
            timestamp="",
            signal_type=sig_type,
            setup_plugin=self.name,
            direction=direction,
            confidence=confidence,
            regime_context="",
            supporting_factors=supporting,
            features_snapshot=ctx,
            context_features=ctx,
            ctf_score=ctf_score,
            ctf_confirmed=ctf_confirmed,
            zone_friction_score=zone_friction_score,
            factor_scores=factor_scores,
        )

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = SupplyDemandSetupPlugin()
