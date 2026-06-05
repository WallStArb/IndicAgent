from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.intelligence.plugins import InputSpec
from src.intelligence.trading.atr_utils import get_atr

# Reaction type encoding
_REACTION_NONE = 0.0
_REACTION_REJECT = 1.0
_REACTION_BASE = 2.0
_REACTION_BREAK = 3.0
_REACTION_BREAK_RETEST = 4.0


@dataclass
class KeyLevelReactionPlugin:
    """Classify price behaviour at the nearest key level."""

    name: str = "patt_KeyLevelReaction"
    outputs: frozenset[str] = frozenset(
        {
            "key_level_reaction_type",
            "key_level_confluence_count",
        }
    )
    min_lookback: int = 3
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"pattern"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=10),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i2") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("i5") or {}),
            **(frames.get("smc") or {}),
        }
        _close_feat = features.get("close")
        close = float(_close_feat if _close_feat is not None else df["close"].iloc[-1])
        atr_14 = get_atr(features)
        proximity = atr_14 * 0.5 if atr_14 is not None else 0.0

        # Collect candidate key levels from features
        level_sources = {
            "nearest_support": features.get("nearest_support"),
            "nearest_resistance": features.get("nearest_resistance"),
            "ob_top": features.get("ob_top"),
            "ob_bottom": features.get("ob_bottom"),
            "fvg_top": features.get("fvg_top"),
            "fvg_bottom": features.get("fvg_bottom"),
            "poc_level": features.get("poc_level"),
            "weekly_pivot": features.get("weekly_pivot"),
        }

        levels = [float(v) for v in level_sources.values() if isinstance(v, (int, float)) and v > 0]

        if not levels:
            return {
                "key_level_reaction_type": _REACTION_NONE,
                "key_level_confluence_count": 0.0,
            }

        # Find nearest level
        nearest = min(levels, key=lambda x: abs(x - close))
        dist = abs(close - nearest)

        # Confluence: count levels within ATR/2 of nearest
        if proximity > 0:
            confluence_count = sum(1 for lv in levels if abs(lv - nearest) < proximity)
        else:
            confluence_count = 1

        # Not near any level
        if proximity > 0 and dist > proximity * 2:
            return {
                "key_level_reaction_type": _REACTION_NONE,
                "key_level_confluence_count": float(confluence_count),
            }

        # Classify last 3 bars' behaviour relative to nearest level
        last3_high = df["high"].iloc[-3:].to_numpy(dtype=float)
        last3_low = df["low"].iloc[-3:].to_numpy(dtype=float)
        last3_close = df["close"].iloc[-3:].to_numpy(dtype=float)

        # Did price touch the level in last 3 bars?
        touched = any(last3_low[i] <= nearest <= last3_high[i] for i in range(len(last3_close)))

        if not touched and dist > (proximity if proximity > 0 else abs(nearest) * 0.005):
            reaction = _REACTION_NONE
        else:
            # Reject: touched level, current close moved away (> half ATR from level)
            c_prev = float(last3_close[0]) if len(last3_close) > 0 else close
            c_curr = float(last3_close[-1])
            moving_away = abs(c_curr - nearest) > abs(c_prev - nearest)

            # Break: price closed clearly beyond level
            broke_above = all(c > nearest for c in last3_close[-2:])
            broke_below = all(c < nearest for c in last3_close[-2:])

            if broke_above or broke_below:
                # Check if came back to retest
                tol = proximity if proximity > 0 else abs(nearest) * 0.002
                if touched and abs(close - nearest) < tol:
                    reaction = _REACTION_BREAK_RETEST
                else:
                    reaction = _REACTION_BREAK
            elif touched and moving_away:
                reaction = _REACTION_REJECT
            elif touched:
                reaction = _REACTION_BASE
            else:
                reaction = _REACTION_NONE

        return {
            "key_level_reaction_type": reaction,
            "key_level_confluence_count": float(confluence_count),
        }

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = KeyLevelReactionPlugin()
