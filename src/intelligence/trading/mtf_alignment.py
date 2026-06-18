"""I7 Multi-Timeframe Alignment setup detection plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr_with_floor_from_frames
from .confidence import compose_confidence
from .exhaustion_utils import apply_exhaustion_guard
from .plugin_utils import extract_ohlcv, no_signal, signal_type_for_direction
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade


@dataclass
class MTFAlignmentPlugin:
    """MTF Alignment setup: fires when I6 cross-timeframe confluence score
    exceeds threshold and multiple timeframes agree.

    Gate: abs(ctf_score) > 0.7 AND ctf_timeframes_aligned >= 2.
    Wider stops and larger targets since multi-TF moves tend to extend.

    ECL EXEMPTION (Phase 123): CTF score is this plugin's INTRINSIC detection signal,
    not extrinsic context. MTFAlignment exists to measure CTF confluence — removing
    the CTF gate would eliminate the plugin's core purpose. Do NOT apply the standard
    Phase 123 ECL annotation pattern here; ctf_score is a first-class confidence factor,
    not an annotation field.
    """

    name: str = "trad_MTFAlignment"
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
    capability_tags: frozenset[str] = frozenset({"trading", "multi_timeframe"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    regime_type: str = "trend"
    ctf_score_threshold: float = 0.7
    min_timeframes_aligned: int = 2
    _state: dict = field(default_factory=dict)
    _config_service: Any = field(default=None, compare=False, repr=False)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        cfg = self._config_service
        ctf_score_min = (
            cfg.get_sync("threshold.mtf_alignment.ctf_score_min", self.ctf_score_threshold)
            if cfg
            else self.ctf_score_threshold
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

        ctf_score = features.get("ctf_score", 0.0)
        ctf_timeframes_aligned = features.get("ctf_timeframes_aligned", 0.0)

        # Gate: score must exceed threshold AND multiple timeframes must agree
        if abs(ctf_score) <= ctf_score_min:
            return no_signal()
        if ctf_timeframes_aligned < self.min_timeframes_aligned:
            return no_signal()

        direction = 1 if ctf_score > 0 else -1

        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        price = float(close[-1])
        entry = price

        signal_type = signal_type_for_direction("mtf_alignment", direction)
        tf = frame_trade(signal_type, direction, entry, features, atr, regime_type=self.regime_type)
        if not tf.viable:
            return no_signal()

        # Wave B: factor audit trail — pre-composite [0,1] scores (Phase 123)
        factor_scores = {
            "ctf_score_raw": round(min(1.0, abs(float(ctf_score))), 4),
            "ctf_timeframes_aligned_score": round(min(1.0, float(ctf_timeframes_aligned) / 4.0), 4),
        }

        # Confidence directly from abs(ctf_score)
        raw_conf = abs(ctf_score)
        supporting = [f"{int(ctf_timeframes_aligned)}_timeframes_aligned"]

        highest_tf = features.get("ctf_highest_aligned_tf", None)
        if highest_tf is not None:
            supporting.append(f"highest_tf_{int(highest_tf)}m")

        ctf_trend = features.get("ctf_trend_alignment", 0.0)
        if abs(ctf_trend) >= 0.5:
            supporting.append("trend_alignment_strong")

        ctf_structure = features.get("ctf_structure_alignment", 0.0)
        if abs(ctf_structure) >= 0.5:
            supporting.append("structure_alignment_strong")

        ctf_regime = features.get("ctf_regime_agreement", 0.0)
        if ctf_regime >= 0.5:
            supporting.append("regime_agreement_strong")

        raw_conf, supporting = apply_exhaustion_guard(features, raw_conf, supporting)
        confidence = compose_confidence(raw_conf)

        regime_ctx = "bullish" if direction == 1 else "bearish"

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


plugin = MTFAlignmentPlugin()
