"""I7 Gap Analysis setup detection plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


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
    outputs: frozenset[str] = frozenset({
        "signal_type", "direction", "bias", "gap_size_atr", "confidence",
        "entry_type", "entry_price", "stop_loss", "targets",
        "regime_context", "supporting_factors",
    })
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "gap"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
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
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return {}

        # Time gate (I4 SessionContext) — only active when feature is present
        bars_since = features.get("bars_since_session_start")
        if bars_since is not None and float(bars_since) > 30:
            session_ny = features.get("session_ny", 1.0)
            if not session_ny:
                return self._no_signal()

        # GAP-01: Gap detection — close[-2] is prior bar close, open[-1] is current bar open
        close = df["close"].to_numpy(dtype=float)
        open_ = df["open"].to_numpy(dtype=float)
        prior_close = float(close[-2])

        gap_size = float(open_[-1]) - prior_close
        direction = 1 if gap_size > 0 else (-1 if gap_size < 0 else 0)
        if direction == 0:
            return self._no_signal()

        # ATR with fallback (established pattern from all I7 plugins)
        atr = float(features.get("atr_14", 0.0))
        if atr <= 0:
            high = df["high"].to_numpy(dtype=float)
            low = df["low"].to_numpy(dtype=float)
            atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            return self._no_signal()

        # Minimum gap gate
        if abs(gap_size) < self.min_gap_atr_mult * atr:
            return self._no_signal()

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
        confidence = round(min(0.95, max(0.05, base)), 4)

        # Supporting factors
        supporting: list[str] = []
        if gap_size_atr >= 1.0:
            supporting.append("large_gap")
        if high_volume:
            supporting.append("volume_confirm")
        supporting.append(f"{bias}_bias")

        bias_abbr = "cont" if bias == "continuation" else "fade"
        signal_type = f"gap_{bias_abbr}_{'long' if direction == 1 else 'short'}"

        return {
            "signal_type": signal_type,
            "direction": direction,
            "bias": bias,
            "gap_size_atr": round(gap_size_atr, 4),
            "confidence": confidence,
            "entry_type": entry_type,
            "entry_price": round(float(entry), 2),
            "stop_loss": round(float(stop), 2),
            "targets": targets,
            "regime_context": "gap_open",
            "supporting_factors": supporting,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}


plugin = GapAnalysisSetupPlugin()
