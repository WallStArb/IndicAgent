"""Pure numeric helpers for cross-timeframe confluence scoring.

No market domain knowledge — independently testable with numeric inputs alone.
"""

from __future__ import annotations

from typing import Any

from ..utils import is_num

# Timeframe weight: higher timeframes carry more authority
_TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}


def _sign(x: float) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def _proximity_decay(price: float, level_top: float, level_bottom: float, atr: float) -> float:
    """1.0 within 1 ATR of zone midpoint; linear decay to 0.0 at 3 ATR; 0.0 beyond."""
    if atr <= 0 or level_top <= 0 or level_bottom <= 0:
        return 0.0
    midpoint = (level_top + level_bottom) / 2.0
    dist_atr = abs(price - midpoint) / atr
    if dist_atr <= 1.0:
        return 1.0
    if dist_atr >= 3.0:
        return 0.0
    return 1.0 - (dist_atr - 1.0) / 2.0


def get_recency_weight(frames: dict[str, Any], tf: str) -> float:
    """Return recency weight for a TF. bars_since=0 → 1.0; stale→→ 0."""
    bars_since = frames.get(f"intel_{tf}_bars_since")
    if not is_num(bars_since) or bars_since < 0:
        return 1.0
    return 1.0 / (bars_since + 1)


def extract_trend_sign(data: dict[str, Any]) -> int:
    """Extract a directional sign from intelligence data.

    Checks multiple keys in priority order:
      trend_direction (SMC BOS/CHoCH: -1/0/+1)
      trend_strength (I3 TrendStructure: float)
      trend_regime (I4 TrendRegime: -1..+1 float)
      momentum_bias (I4 MomentumContext: -1..+1 float)
    """
    for key in ("trend_direction", "trend_strength", "trend_regime", "momentum_bias"):
        v = data.get(key)
        if is_num(v) and v != 0:
            return _sign(v)
    return 0
