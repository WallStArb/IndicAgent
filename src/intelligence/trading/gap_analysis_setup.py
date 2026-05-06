"""I7 Gap Analysis setup detection plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr
from .confidence_utils import capture_signal_features, compose_confidence
from .exhaustion_utils import apply_exhaustion_boost
from .plugin_utils import extract_ohlcv, no_signal
from .signal_schema import make_signal_from_frame
from .trade_framer import TradeFrame, TradeTarget


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
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=100),)
    regime_type: str = "any"
    min_gap_atr_mult: float = 0.3
    continuation_atr_mult: float = 1.0
    volume_confirm_ratio: float = 1.5
    stop_atr_fade: float = 1.0
    stop_atr_cont: float = 1.5
    target_atr_cont: float = 2.0
    target_atr_cont2: float = 3.0
    target_atr_fade_ext: float = 0.5
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        result = extract_ohlcv(frames, self.min_lookback)
        if result is None:
            return no_signal()
        open_, high, low, close = result

        features = frames.get("features") or {}
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

        atr = get_atr(features)
        if atr is None:
            return no_signal()

        # Minimum gap gate
        if abs(gap_size) < self.min_gap_atr_mult * atr:
            return no_signal()

        gap_size_atr = abs(gap_size) / atr

        # GAP-02: Volume check
        import numpy as np

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

        # GAP-03: Entry, stop, and targets — all bias-dependent
        if bias == "fade":
            entry_type = "at_limit"
            entry = open_[-1]  # current session open (fade from here toward prior close)
            stop = open_[-1] - direction * self.stop_atr_fade * atr
            targets = [
                round(prior_close, 2),
                round(prior_close + direction * self.target_atr_fade_ext * atr, 2),
            ]
        else:
            entry_type = "at_pullback"
            entry = open_[-1] + (-direction * 0.25 * atr)
            stop = open_[-1] - direction * self.stop_atr_cont * atr
            targets = [
                round(open_[-1] + direction * self.target_atr_cont * atr, 2),
                round(open_[-1] + direction * self.target_atr_cont2 * atr, 2),
            ]

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
        confidence = compose_confidence(base)

        bias_abbr = "cont" if bias == "continuation" else "fade"
        signal_type = f"gap_{bias_abbr}_{'long' if direction == 1 else 'short'}"

        features_snapshot = capture_signal_features(
            features,
            direction,
            "session",
            confidence,
        )
        _risk = abs(float(entry) - float(stop)) or 1e-9
        _t_objs = [
            TradeTarget(
                price=float(t),
                label=f"t{i+1}",
                level_type="atr",
                rr=abs(float(t) - float(entry)) / _risk,
            )
            for i, t in enumerate(targets)
        ]
        _tf = TradeFrame(
            entry=float(entry),
            entry_type=entry_type,
            stop=float(stop),
            stop_type="atr",
            targets=_t_objs,
            rr_t1=_t_objs[0].rr if _t_objs else 0.0,
            rr_t2=_t_objs[1].rr if len(_t_objs) > 1 else 0.0,
            zone_low=float(entry) - 0.2 * atr,
            zone_high=float(entry) + 0.2 * atr,
        )
        signal = make_signal_from_frame(
            _tf,
            symbol="",
            timeframe="",
            timestamp="",
            signal_type=signal_type,
            setup_plugin=self.name,
            direction=direction,
            confidence=confidence,
            regime_context="gap_open",
            confluence_score=0.0,
            supporting_factors=supporting,
            invalidation_conditions=[],
            features_snapshot=features_snapshot,
        )
        signal["bias"] = bias
        signal["gap_size_atr"] = round(gap_size_atr, 4)
        return signal

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = GapAnalysisSetupPlugin()
