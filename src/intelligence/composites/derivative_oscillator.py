from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec, PatternPlugin
from .common import crossover_detect, is_num

# EMA smoothing constants (Constance Brown formula)
ALPHA_EMA5: float = 2 / (5 + 1)  # = 1/3
ALPHA_EMA3: float = 2 / (3 + 1)  # = 1/2


@dataclass
class DerivativeOscillatorPlugin(PatternPlugin):
    """Derivative Oscillator (Constance Brown) — triple-smoothed RSI derivative.

    Formula:
        ema5   = EMA(5, RSI-14)     alpha = 2/6
        ema3   = EMA(3, ema5)       alpha = 2/4
        signal = SMA(9, ema3)
        deriv_osc = ema3 - signal

    Leads MACD by ~1-2 bars. Output gate: returns {} until sma9 buffer has 9
    values (~18 bars from first valid RSI). State update always runs when RSI
    is valid — warmup is separated from output gate.
    """

    name: str = "cmp_DerivativeOscillator"
    outputs: frozenset[str] = frozenset({
        "deriv_osc",
        "deriv_osc_signal",
        "deriv_osc_cross_bullish",
        "deriv_osc_cross_bearish",
    })
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"momentum", "oscillator"})
    inputs: tuple[InputSpec, ...] = ()
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        rsi = features.get("rsi_14")
        if not is_num(rsi):
            return {}

        state = self._state

        # --- EMA5 update (always runs when RSI valid) ---
        ema5 = state.get("ema5")
        if ema5 is None:
            ema5 = rsi  # seed on first bar
        else:
            ema5 = ALPHA_EMA5 * rsi + (1 - ALPHA_EMA5) * ema5
        state["ema5"] = ema5

        # --- EMA3 update (always runs) ---
        prev_ema3 = state.get("ema3")  # save before update for cross detection
        if prev_ema3 is None:
            ema3 = ema5  # seed with first ema5 value
        else:
            ema3 = ALPHA_EMA3 * ema5 + (1 - ALPHA_EMA3) * prev_ema3
        state["ema3"] = ema3

        # --- SMA9 buffer update (always runs) ---
        sma9_buf = state.get("sma9_buf")
        if sma9_buf is None:
            sma9_buf = deque(maxlen=9)
            state["sma9_buf"] = sma9_buf
        sma9_buf.append(ema3)

        # --- Output gate: wait until SMA9 buffer is full ---
        if len(sma9_buf) < 9:
            return {}

        signal_line = sum(sma9_buf) / len(sma9_buf)
        deriv_osc = ema3 - signal_line

        # --- Cross detection ---
        prev_signal = state.get("prev_signal")
        bullish, bearish = crossover_detect(prev_ema3, ema3, prev_signal, signal_line)

        # Store signal line for next bar's cross detection
        state["prev_signal"] = signal_line

        return {
            "deriv_osc": deriv_osc,
            "deriv_osc_signal": signal_line,
            "deriv_osc_cross_bullish": bullish,
            "deriv_osc_cross_bearish": bearish,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = DerivativeOscillatorPlugin()
