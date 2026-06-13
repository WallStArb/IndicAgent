"""trad_PatternCompletion — Chart pattern completion evidence-contributor.

Gates on any I5 pattern confidence > threshold.
Checks dt_db (double top/bottom), hs (head and shoulders), then triangle.
Takes highest-confidence pattern if multiple fire.
Evidence contributor for CIS bucket scorer — Phase B input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..plugins import InputSpec
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import capture_signal_features, clamp01, compose_confidence
from .plugin_utils import extract_ohlcv, no_signal
from .signal_schema import make_signal_from_frame
from .state_utils import deduplicate_event
from .trade_framer import frame_trade

if TYPE_CHECKING:
    pass

_CONFIDENCE_MIN_DEFAULT: float = 0.70


@dataclass
class PatternCompletionPlugin:
    """I7 evidence contributor: fires when a high-confidence chart pattern completes.

    Gate: any pattern confidence > confidence_min
    Priority: dt_db first, then hs, then triangle (take highest-confidence)
    Confidence: 4-factor intrinsic composite

    deduplicate_event: fires once per unique (pattern_name, direction, structural_anchor).
    The structural anchor (neckline / apex_bars) changes when a new formation appears,
    distinguishing genuinely new pattern instances from persistent lookback echoes.
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
    requires_i6_confluence: bool = True
    shadow_only: bool = True
    confidence_threshold: float = _CONFIDENCE_MIN_DEFAULT  # alias for backward-compat
    _state: dict = field(default_factory=dict)
    _config_service: Any = field(default=None, compare=False, repr=False)

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

        candidates: list[tuple[float, int, str]] = []  # (confidence, direction, signal_name)

        dt_db_confidence = float(features.get("dt_db_confidence", 0.0))
        dt_db_pattern = int(features.get("dt_db_pattern", 0))
        if dt_db_confidence > confidence_min and dt_db_pattern in (1, 2):
            direction = -1 if dt_db_pattern == 1 else 1
            pattern_name = "double_top" if dt_db_pattern == 1 else "double_bottom"
            candidates.append((dt_db_confidence, direction, pattern_name))

        hs_confidence = float(features.get("hs_confidence", 0.0))
        hs_pattern = int(features.get("hs_pattern", 0))
        if hs_confidence > confidence_min and hs_pattern in (1, 2):
            direction = -1 if hs_pattern == 1 else 1
            pattern_name = "hs_top" if hs_pattern == 1 else "hs_bottom"
            candidates.append((hs_confidence, direction, pattern_name))

        tri_confidence = float(features.get("tri_confidence", 0.0))
        tri_breakout_bias = int(features.get("tri_breakout_bias", 0))
        if tri_confidence > confidence_min and tri_breakout_bias != 0:
            direction = int(tri_breakout_bias)
            candidates.append((tri_confidence, direction, "triangle"))

        if not candidates:
            return no_signal()

        best_confidence, direction, pattern_name = max(candidates, key=lambda x: x[0])

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        entry = float(close[-1])
        suffix = "long" if direction == 1 else "short"
        signal_type = f"pattern_{pattern_name}_{suffix}"
        tf = frame_trade(signal_type, direction, entry, features, atr, regime_type=self.regime_type)
        if not tf.viable:
            return no_signal()

        n_candidates = len(candidates)
        pattern_score = clamp01(best_confidence)
        strength_score = clamp01(
            (best_confidence - confidence_min) / max(1e-9, 1.0 - confidence_min)
        )
        convergence_score = clamp01(n_candidates / 3.0)
        if n_candidates > 1:
            direction_purity = 1.0 if all(d == direction for _, d, _ in candidates) else 0.4
        else:
            direction_purity = 0.7

        raw_conf = (
            0.45 * pattern_score
            + 0.25 * strength_score
            + 0.20 * convergence_score
            + 0.10 * direction_purity
        )
        confidence = compose_confidence(raw_conf)

        # deduplicate_event: distinguish pattern instances by structural anchor.
        # neckline/apex_bars changes when a genuinely new pattern forms — same pattern
        # type reappearing at a different structural level fires normally.
        symbol = frames.get("__symbol__", "_")
        tf_key = frames.get("__timeframe__", "_")
        state_key = f"{symbol}_{tf_key}"
        if pattern_name in ("double_top", "double_bottom"):
            anchor: Any = round(float(features.get("dt_db_neckline", 0.0)), 4)
        elif pattern_name in ("hs_top", "hs_bottom"):
            anchor = round(float(features.get("hs_neckline", 0.0)), 4)
        else:
            anchor = int(features.get("tri_apex_bars", 0))
        event_id = (pattern_name, direction, anchor)
        if not deduplicate_event(self._state, state_key, event_id):
            return no_signal()

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
            features_snapshot=capture_signal_features(features, direction, "smc", confidence),
        )
        signal["pattern_name"] = pattern_name
        signal["pattern_raw_confidence"] = round(best_confidence, 4)
        signal["pattern_count"] = n_candidates
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = PatternCompletionPlugin()
