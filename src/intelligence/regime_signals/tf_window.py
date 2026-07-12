"""Shared daily-window -> TF-bar-count conversion for regime signal modules.

Single source of truth for the day->bar mapping consumed by every module in
`src.intelligence.regime_signals`. Ported verbatim from
`services/equity_regime_model.py:84-101` (the pre-existing, bug-fixed implementation)
per RESEARCH.md's Don't Hand-Roll guidance — do not redefine `_BARS_PER_DAY`/`_tf_window`
locally inside any signal module.
"""

from __future__ import annotations

# Trading-session bars per daily bar — used to scale daily window parameters.
# 1d is already in daily bars; 1h: 6.5h/day (NYSE); 15m: 26 bars/day; 5m: 78 bars/day.
_BARS_PER_DAY: dict[str, int] = {
    "1d": 1,
    "1h": 7,  # rounded: 6.5 -> 7 for conservative warmup
    "15m": 26,
    "5m": 78,
}


def _tf_window(daily_window: int, tf: str) -> int:
    """Convert a daily-bar window count to the equivalent bar count for a given TF.

    Examples:
        _tf_window(200, '5m')  -> 200 * 78 = 15600
        _tf_window(252, '1h')  -> 252 * 7  = 1764
        _tf_window(20, '1d')   -> 20
    """
    bars_per_day = _BARS_PER_DAY.get(tf, 1)
    return daily_window * bars_per_day
