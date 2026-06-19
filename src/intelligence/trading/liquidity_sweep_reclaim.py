"""I7 Liquidity Sweep Reclaim setup detection plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from ..utils.gradient_utils import linear_ramp
from .atr_utils import get_atr_with_floor_from_frames
from .confidence import compose_confidence
from .plugin_utils import extract_ohlcv, no_signal
from .signal_schema import make_signal_from_frame
from .state_utils import deduplicate_event, onset_guard
from .trade_framer import frame_trade


@dataclass
class LiquiditySweepReclaimPlugin:
    """Highest-conviction SMC setup: fires on the rising edge of sweep_reclaimed.

    Gate ordering:
    1. sweep_detected == 1.0 (sweep existence FIRST)
    2. onset_guard on sweep_reclaimed == 1.0 (rising-edge SECOND — event, not state)
    3. sweep_type != 0.0 (type check THIRD)
    4. close above/below sweep_level (close-above acceptance FOURTH)
    5. OHLCV extraction + ATR + trade frame
    6. deduplicate_event by (sweep_level, sweep_type) (before emission)
    7. Emit signal

    Renaissance principles:
    - Structural stop hierarchy via frame_trade() (no arbitrary ATR multipliers)
    - Zone correction prevents stopped_at_entry outcomes
    - Tick-size validation at emission gate
    - Onset guard fires only on state transition 0->1; flag staying hot is not a trigger
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
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    regime_type: str = "mean_reversion"
    # Phase 126 IC audit: statistically anti-predictive on existing data
    # (IC=-0.011, hit_rate CI upper=0.213, n=78683); redesign required.
    shadow_only: bool = True
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

        symbol = frames.get("__symbol__", "_")
        tf_key = frames.get("__timeframe__", "_")
        state_key = f"{symbol}_{tf_key}"

        # Sweep existence FIRST: sweep must be detected
        sweep_detected = features.get("sweep_detected", 0.0)
        if sweep_detected != 1.0:
            return no_signal()

        # Rising-edge SECOND: fire only on sweep_reclaimed transition 0->1
        # (flag staying hot is not a trigger; onset_guard rearms when flag drops)
        sweep_reclaimed = features.get("sweep_reclaimed", 0.0)
        reclaim_rising_edge = onset_guard(
            self._state, f"{state_key}_reclaim", sweep_reclaimed == 1.0
        )
        if not reclaim_rising_edge:
            return no_signal()

        # Type check THIRD: direction must be known
        sweep_type = features.get("sweep_type", 0.0)
        if sweep_type == 0.0:
            return no_signal()

        sweep_level = features.get("sweep_level", 0.0)

        # Close-above acceptance FOURTH: close must reclaim level with body acceptance
        # (wick-only reclaim is noise — high wick above level but close below is not a reclaim)
        result = extract_ohlcv(frames, self.min_lookback)
        if result is None:
            return no_signal()
        open_, high, low, close = result

        close_val = float(close[-1])
        direction = 1 if sweep_type > 0 else -1
        if direction == 1 and close_val <= sweep_level:
            # Structural specificity: close must reclaim level with body acceptance (wick-only is noise)
            return no_signal()
        if direction == -1 and close_val >= sweep_level:
            # Structural specificity: close must reclaim level with body acceptance (wick-only is noise)
            return no_signal()

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        entry = float(close[-1])
        signal_type = "sweep_reclaim_long" if direction == 1 else "sweep_reclaim_short"
        tf = frame_trade(signal_type, direction, entry, features, atr, regime_type=self.regime_type)
        if not tf.viable:
            return no_signal()

        # Confidence scoring
        cfg = self._config_service
        base_conf = cfg.get_sync("weights.liquidity_sweep.base_conf", 0.40) if cfg else 0.40
        depth_scale = cfg.get_sync("weights.liquidity_sweep.depth_scale", 0.20) if cfg else 0.20
        sweep_depth_atr = float(features.get("sweep_depth_pct", 0.0))
        confidence = base_conf + depth_scale * linear_ramp(sweep_depth_atr, 0.0, 2.0)
        supporting = ["sweep_reclaimed"]

        fvg_type = features.get("fvg_type", 0.0)
        if fvg_type == float(direction):
            confidence += 0.15
            supporting.append("fvg_confirmed")

        ob_type = features.get("ob_type", 0.0)
        if ob_type == float(direction):
            confidence += 0.10
            supporting.append("order_block_confirmed")

        sweep_type_val = features.get("sweep_type", 0.0)
        if sweep_type_val > 0:
            sig = float(features.get("ssl_significance", 0.0))
            if sig >= 0.60:
                confidence += min(0.10, sig * 0.12)
                supporting.append(f"named_ssl_level_{sig:.2f}")
        elif sweep_type_val < 0:
            sig = float(features.get("bsl_significance", 0.0))
            if sig >= 0.60:
                confidence += min(0.10, sig * 0.12)
                supporting.append(f"named_bsl_level_{sig:.2f}")

        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        # Note: additive confidence model; capture key component contributions
        factor_scores = {
            "sweep_depth_score": round(min(1.0, max(0.0, sweep_depth_atr / 2.0)), 4),
            "fvg_confirmed": round(1.0 if fvg_type == float(direction) else 0.0, 4),
            "ob_confirmed": round(1.0 if ob_type == float(direction) else 0.0, 4),
        }

        confidence = compose_confidence(confidence)

        # deduplicate_event by (sweep_level, sweep_type): allows re-arm on re-sweeps of same level
        # after _DEDUP_MIN_BARS active-condition calls; placed immediately before emission
        event_id = (round(float(sweep_level), 4), int(sweep_type))
        if not deduplicate_event(self._state, state_key, event_id):
            return no_signal()

        return make_signal_from_frame(
            tf,
            symbol=frames.get("symbol", ""),
            timeframe=features.get("timeframe", ""),
            timestamp=features.get("timestamp", ""),
            signal_type=signal_type,
            setup_plugin=self.name,
            direction=direction,
            confidence=confidence,
            regime_context="any",
            supporting_factors=supporting,
            factor_scores=factor_scores,
        )

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = LiquiditySweepReclaimPlugin()
