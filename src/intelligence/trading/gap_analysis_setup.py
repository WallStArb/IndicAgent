"""I7 Gap Analysis setup detection plugin.

Renaissance principles:
- Structural stop hierarchy via frame_trade() (no arbitrary ATR multipliers)
- Zone correction prevents stopped_at_entry outcomes
- Tick-size validation at emission gate
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec
from ..utils.gradient_utils import hmm_regime_weight
from .atr_utils import get_atr_with_floor_from_frames
from .confidence_utils import capture_signal_features, compose_confidence
from .exhaustion_utils import apply_exhaustion_boost
from .plugin_utils import extract_ohlcv, no_signal
from .signal_schema import make_signal_from_frame
from .trade_framer import frame_trade


@dataclass
class GapAnalysisSetupPlugin:
    """Gap analysis setup: fires when a significant gap (open vs prior close) is detected.

    GAP-01: Detects directional gaps using open[-1] vs close[-2].
    GAP-02: Classifies bias as 'continuation' (large gap + high volume) or 'fade'.
    GAP-03: Derives entry, stop, targets and confidence from gap size and ATR.

    Time gate: when I4 SessionContext is present and bars_since_session_start > 30,
    restricts to NY session only (session_ny == 1).
    """

    name: str = "trad_GapAnalysisSetup"
    outputs: frozenset[str] = frozenset(
        {
            "signal_type",
            "direction",
            "bias",
            "gap_size_atr",
            "confidence",
            "entry_type",
            "entry_price",
            "stop_loss",
            "targets",
            "regime_context",
            "supporting_factors",
        }
    )
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "gap"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
    regime_type: str = "any"
    requires_i6_confluence: bool = True
    min_gap_atr_mult: float = 0.3
    continuation_atr_mult: float = 1.0
    volume_confirm_ratio: float = 1.5
    _state: dict = field(default_factory=dict)

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
        df = frames.get("main")

        # Time gate (I4 SessionContext) — only active when feature is present
        bars_since = features.get("bars_since_session_start")
        if bars_since is not None and float(bars_since) > 30:
            session_ny = features.get("session_ny", 1.0)
            if not session_ny:
                return no_signal()

        # GAP-01: Gap detection — close[-2] is prior bar close, open[-1] is current bar open
        prior_close = float(close[-2])

        gap_size = float(open_[-1]) - prior_close
        direction = 1 if gap_size > 0 else (-1 if gap_size < 0 else 0)
        if direction == 0:
            return no_signal()

        symbol = frames.get("symbol", "")
        atr = get_atr_with_floor_from_frames(frames)
        if atr is None:
            return no_signal()

        # Minimum gap gate
        if abs(gap_size) < self.min_gap_atr_mult * atr:
            return no_signal()

        gap_size_atr = abs(gap_size) / atr

        # GAP-02: Volume check
        vol = df["volume"].to_numpy(dtype=float)
        if len(vol) > 21:
            vol_mean = np.mean(vol[-21:-1])
        elif len(vol) > 1:
            vol_mean = np.mean(vol[:-1])
        else:
            vol_mean = 1.0
        vol_ratio = vol[-1] / vol_mean if vol_mean > 0 else 1.0
        high_volume = vol_ratio >= self.volume_confirm_ratio  # 1.5x threshold

        # GAP-02: Bias classification
        if gap_size_atr >= self.continuation_atr_mult and high_volume:
            bias = "continuation"
        else:
            bias = "fade"

        # GAP-03: Entry — bias-dependent
        if bias == "fade":
            # Fade trades AGAINST the gap direction: upward gap → short, downward gap → long.
            # direction here reflects gap direction; fade_direction is the trade direction.
            fade_direction = -direction
            entry_type = "at_limit"
            entry = float(open_[-1])
            direction = fade_direction
        else:
            entry_type = "at_pullback"
            entry = float(open_[-1] + (-direction * 0.25 * atr))

        # GAP-03: Confidence
        base = min(1.0, gap_size_atr / 2.0)
        if high_volume:
            base += 0.15

        # Supporting factors
        supporting: list[str] = []
        if gap_size_atr >= 1.0:
            supporting.append("large_gap")
        if high_volume:
            supporting.append("volume_confirm")
        supporting.append(f"{bias}_bias")

        base, supporting = apply_exhaustion_boost(features, direction, base, supporting)

        # I6 ctf_score contribution (additive)
        ctf_score = float(features.get("ctf_score", 0.0))
        if abs(ctf_score) > 0.3:
            base += 0.15 * min(1.0, abs(ctf_score) / 0.7)
            supporting.append(f"ctf_score={ctf_score:.3f}")

        # HMM regime contribution (additive, centered at 0.5 neutral)
        regime_w = hmm_regime_weight(features, "up" if direction == 1 else "down")
        base += 0.10 * (regime_w - 0.5)

        confidence = compose_confidence(base)

        bias_abbr = "cont" if bias == "continuation" else "fade"
        signal_type = f"gap_{bias_abbr}_{'long' if direction == 1 else 'short'}"

        # Renaissance: Use frame_trade() for structural stop hierarchy
        tf = frame_trade(signal_type, direction, entry, features, atr, regime_type=self.regime_type)
        if not tf.viable:
            return no_signal()

        features_snapshot = capture_signal_features(
            features,
            direction,
            "session",
            confidence,
        )
        signal = make_signal_from_frame(
            tf,
            symbol=symbol,
            timeframe=features.get("timeframe", ""),
            timestamp=features.get("timestamp", ""),
            signal_type=signal_type,
            setup_plugin=self.name,
            direction=direction,
            confidence=confidence,
            regime_context="gap_open",
            supporting_factors=supporting,
            features_snapshot=features_snapshot,
        )
        signal["bias"] = bias
        signal["gap_size_atr"] = round(gap_size_atr, 4)
        return signal

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = GapAnalysisSetupPlugin()
