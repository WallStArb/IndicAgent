"""trad_PatternCompletion — Chart pattern completion evidence-contributor.

Fires on structural completion: neckline break (DT/DB/HS) or triangle apex breach.
Confidence is context (pattern quality), NOT the trigger.
Pattern instance is consumed after firing — never re-fires same instance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..plugins import InputSpec
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import clamp01, compose_confidence
from .plugin_utils import extract_ohlcv, no_signal
from .signal_schema import make_signal_from_frame
from .state_utils import deduplicate_event
from .trade_framer import frame_trade

if TYPE_CHECKING:
    pass

_CONFIDENCE_MIN_DEFAULT: float = 0.70


@dataclass
class PatternInstanceState:
    """State for a single pattern instance (identified by structural anchor).

    fired_bars > 0 means this instance has been consumed — no re-fire.
    """

    pattern_name: str
    direction: int
    structural_anchor: float | int  # neckline for DT/DB/HS, apex_bars for triangle
    fired_bars: int = 0  # Bars since fire; >0 = consumed


@dataclass
class PatternCompletionPlugin:
    """I7 evidence contributor: fires when a chart pattern structurally completes.

    Structural trigger: neckline break (DT/DB/HS) or apex-bound breach (triangle).
    Confidence filter: pattern quality score (context only, not the trigger).
    Instance consumption: each (pattern_name, direction, anchor) fires at most once.

    deduplicate_event is kept as a secondary guard. The primary guard is
    instance.fired_bars > 0, which is permanent (no re-arm after min_bars).
    """

    name: str = "trad_PatternCompletion"
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
    capability_tags: frozenset[str] = frozenset({"trading", "pattern", "structure"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=50),)
    regime_type: str = "trend"
    shadow_only: bool = True
    confidence_threshold: float = _CONFIDENCE_MIN_DEFAULT  # alias for backward-compat
    _state: dict = field(default_factory=dict)
    _instances: dict[str, PatternInstanceState] = field(default_factory=dict)
    _config_service: Any = field(default=None, compare=False, repr=False)

    def _get_instance_state(self, instance_id: str) -> PatternInstanceState:
        """Factory for lazy init of instance state."""
        if instance_id not in self._instances:
            self._instances[instance_id] = PatternInstanceState(
                pattern_name="", direction=0, structural_anchor=0
            )
        return self._instances[instance_id]

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        cfg = self._config_service
        confidence_min = (
            cfg.get_sync("threshold.pattern_completion.confidence_min", _CONFIDENCE_MIN_DEFAULT)
            if cfg
            else _CONFIDENCE_MIN_DEFAULT
        )

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

        symbol = frames.get("__symbol__", "_")
        tf_key = frames.get("__timeframe__", "_")
        state_key = f"{symbol}_{tf_key}"
        current_close = float(close[-1])

        # --- PATTERN EXISTENCE FIRST ---
        # Identify which patterns are active (I5 pattern codes non-zero)
        dt_db_pattern = int(features.get("dt_db_pattern", 0))
        hs_pattern = int(features.get("hs_pattern", 0))
        tri_breakout_bias = int(features.get("tri_breakout_bias", 0))

        if dt_db_pattern not in (1, 2) and hs_pattern not in (1, 2) and tri_breakout_bias == 0:
            return no_signal()

        # --- STRUCTURAL COMPLETION SECOND ---
        # Check each pattern type for structural completion (neckline break / apex breach).
        # A candidate requires BOTH pattern existence AND structural completion.
        candidates: list[tuple[float, int, str, float | int]] = []
        # (confidence, direction, pattern_name, structural_anchor)

        if dt_db_pattern in (1, 2):
            dt_db_neckline = features.get("dt_db_neckline")
            dt_db_confidence = float(features.get("dt_db_confidence", 0.0))
            if dt_db_neckline is not None:
                neckline = float(dt_db_neckline)
                if dt_db_pattern == 1:
                    # Double top: bearish structural completion = close breaks below neckline
                    structurally_complete = current_close < neckline
                    direction = -1
                    pattern_name = "double_top"
                else:
                    # Double bottom: bullish structural completion = close breaks above neckline
                    structurally_complete = current_close > neckline
                    direction = 1
                    pattern_name = "double_bottom"
                anchor: float | int = round(neckline, 4)
                if structurally_complete:
                    candidates.append((dt_db_confidence, direction, pattern_name, anchor))

        if hs_pattern in (1, 2):
            hs_neckline = features.get("hs_neckline")
            hs_confidence = float(features.get("hs_confidence", 0.0))
            if hs_neckline is not None:
                neckline = float(hs_neckline)
                if hs_pattern == 1:
                    # Head and shoulders top: bearish = close breaks below neckline
                    structurally_complete = current_close < neckline
                    direction = -1
                    pattern_name = "hs_top"
                else:
                    # Inverse head and shoulders: bullish = close breaks above neckline
                    structurally_complete = current_close > neckline
                    direction = 1
                    pattern_name = "hs_bottom"
                anchor = round(neckline, 4)
                if structurally_complete:
                    candidates.append((hs_confidence, direction, pattern_name, anchor))

        if tri_breakout_bias != 0:
            tri_apex_bars = features.get("tri_apex_bars")
            tri_confidence = float(features.get("tri_confidence", 0.0))
            if tri_apex_bars is not None:
                apex_bars = int(tri_apex_bars)
                direction = int(tri_breakout_bias)
                # Triangle structural completion: close breaks consolidation bounds.
                # Use recent high/low over apex_bars window as consolidation bounds.
                lookback = max(2, min(apex_bars, len(close) - 1))
                consolidation_high = float(high[-lookback - 1 : -1].max())
                consolidation_low = float(low[-lookback - 1 : -1].min())
                if direction == 1:
                    structurally_complete = current_close > consolidation_high
                else:
                    structurally_complete = current_close < consolidation_low
                anchor = apex_bars
                if structurally_complete:
                    candidates.append((tri_confidence, direction, "triangle", anchor))

        if not candidates:
            # No structural completion — pattern(s) exist but have not triggered yet
            return no_signal()

        best_confidence, direction, pattern_name, best_anchor = max(candidates, key=lambda x: x[0])

        # --- CONFIDENCE CONTEXT FILTER THIRD ---
        # Confidence is pattern quality (context), not the trigger.
        # A low-confidence pattern completing structurally is still a signal — but
        # we filter out very weak patterns (e.g., noise at the edge of detection).
        if best_confidence <= confidence_min:
            return no_signal()

        # --- INSTANCE CONSUMPTION FOURTH ---
        # Each (symbol, tf, pattern_name, anchor) fires at most once.
        # Instance consumed: this pattern structure fires at most once.
        instance_id = f"{symbol}_{tf_key}_{pattern_name}_{best_anchor}"
        instance = self._get_instance_state(instance_id)
        if instance.fired_bars > 0:
            return no_signal()

        # Secondary dedup guard via deduplicate_event (handles edge cases where
        # instance_id could collide across very different patterns at same level).
        event_id = (pattern_name, direction, best_anchor)
        if not deduplicate_event(self._state, state_key, event_id):
            return no_signal()

        # --- OHLCV AND TRADE FRAME FIFTH ---
        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        entry = current_close
        suffix = "long" if direction == 1 else "short"
        signal_type = f"pattern_{pattern_name}_{suffix}"
        tf = frame_trade(signal_type, direction, entry, features, atr, regime_type=self.regime_type)
        if not tf.viable:
            return no_signal()

        # --- EMIT AND MARK CONSUMED SIXTH ---
        # Mark instance as consumed: this pattern structure fires at most once.
        instance.pattern_name = pattern_name
        instance.direction = direction
        instance.structural_anchor = best_anchor
        instance.fired_bars = 1

        n_candidates = len(candidates)
        pattern_score = clamp01(best_confidence)
        strength_score = clamp01(
            (best_confidence - confidence_min) / max(1e-9, 1.0 - confidence_min)
        )
        convergence_score = clamp01(n_candidates / 3.0)
        if n_candidates > 1:
            direction_purity = 1.0 if all(d == direction for _, d, _, _ in candidates) else 0.4
        else:
            direction_purity = 0.7

        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "pattern_score": round(pattern_score, 4),
            "strength_score": round(strength_score, 4),
            "convergence_score": round(convergence_score, 4),
        }

        raw_conf = (
            0.45 * pattern_score
            + 0.25 * strength_score
            + 0.20 * convergence_score
            + 0.10 * direction_purity
        )
        confidence = compose_confidence(raw_conf)

        regime_ctx = "bullish" if direction == 1 else "bearish"
        supporting = [pattern_name]
        if n_candidates > 1:
            supporting.append("multiple_patterns")

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
        signal["pattern_name"] = pattern_name
        signal["pattern_raw_confidence"] = round(best_confidence, 4)
        signal["pattern_count"] = n_candidates
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = PatternCompletionPlugin()
