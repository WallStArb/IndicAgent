from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from ..utils import find_peaks, find_troughs


@dataclass
class SwingDetectorPlugin:
    """Detect swing highs/lows and classify HH/HL/LH/LL trend geometry."""

    name: str = "struct_SwingDetector"
    outputs: frozenset[str] = frozenset(
        {
            "swing_high",
            "swing_low",
            "swing_high_idx",
            "swing_low_idx",
            "swing_pattern",
            "swing_high_type",
            "swing_low_type",
            "swing_high_age_bars",
            "swing_low_age_bars",
        }
    )
    min_lookback: int = 60
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"structure"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=120),)
    neighbor: int = 5
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        n_bars = len(df)

        swing_highs = find_peaks(high, self.neighbor)
        swing_lows = find_troughs(low, self.neighbor)

        # Most recent swing values
        sh_price = float(high[swing_highs[-1]]) if swing_highs else 0.0
        sl_price = float(low[swing_lows[-1]]) if swing_lows else 0.0
        sh_idx = float(swing_highs[-1]) if swing_highs else 0.0
        sl_idx = float(swing_lows[-1]) if swing_lows else 0.0

        # Age: how many bars ago the most recent swing occurred
        sh_age = float(n_bars - 1 - swing_highs[-1]) if swing_highs else float(n_bars)
        sl_age = float(n_bars - 1 - swing_lows[-1]) if swing_lows else float(n_bars)

        # Classify swing high type: HH (+1) or LH (-1)
        high_type = 0.0
        if len(swing_highs) >= 2:
            prev_sh = high[swing_highs[-2]]
            curr_sh = high[swing_highs[-1]]
            high_type = 1.0 if curr_sh > prev_sh else -1.0

        # Classify swing low type: HL (+1) or LL (-1)
        low_type = 0.0
        if len(swing_lows) >= 2:
            prev_sl = low[swing_lows[-2]]
            curr_sl = low[swing_lows[-1]]
            low_type = 1.0 if curr_sl > prev_sl else -1.0

        # Combined pattern: HH+HL = uptrend, LH+LL = downtrend
        if high_type == 1.0 and low_type == 1.0:
            pattern = 1.0
        elif high_type == -1.0 and low_type == -1.0:
            pattern = -1.0
        else:
            pattern = 0.0

        return {
            "swing_high": sh_price,
            "swing_low": sl_price,
            "swing_high_idx": sh_idx,
            "swing_low_idx": sl_idx,
            "swing_pattern": pattern,
            "swing_high_type": high_type,
            "swing_low_type": low_type,
            "swing_high_age_bars": sh_age,
            "swing_low_age_bars": sl_age,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = SwingDetectorPlugin()
