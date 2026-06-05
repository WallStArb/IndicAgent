from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from src.intelligence.plugins import InputSpec
from src.intelligence.trading.atr_utils import get_atr
from src.intelligence.trading.trade_framer import (
    MAX_STOP_ATR_MULTIPLIER_BY_TF,
    MAX_STOP_ATR_MULTIPLIER_DEFAULT,
)
from src.intelligence.trading.zone_engine import (
    ZoneCandidate,
    collect_sr_candidates,
    find_best_level,
)

EPSILON = 1e-9


@dataclass
class SRConsensusPlugin:
    name: str = "ctx_SRConsensus"
    outputs: frozenset[str] = frozenset(
        {
            "sr_nearest_support",
            "sr_nearest_resistance",
            "sr_support_confluence_score",
            "sr_resistance_confluence_score",
            "sr_support_dist_atr",
            "sr_resistance_dist_atr",
        }
    )
    min_lookback: int = 5
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"context"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=5),)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}
        features = {
            **(frames.get("i1") or {}),
            **(frames.get("i3") or {}),
            **(frames.get("i4") or {}),
            **(frames.get("smc") or {}),
        }
        current_price = float(df["close"].iloc[-1])
        features["timeframe"] = frames.get("timeframe", "")
        atr = get_atr(features)
        if not atr:
            return {}
        max_dist = atr * MAX_STOP_ATR_MULTIPLIER_BY_TF.get(
            features["timeframe"], MAX_STOP_ATR_MULTIPLIER_DEFAULT
        )

        def _build_cands(direction: int) -> list[ZoneCandidate]:
            return sorted(
                collect_sr_candidates(features, direction, current_price, atr, max_dist)
                + _round_candidates(current_price, atr, max_dist, direction),
                key=lambda c: c.price,
            )

        s_best = find_best_level(_build_cands(-1), atr, current_price)
        r_best = find_best_level(_build_cands(1), atr, current_price)
        return {
            "sr_nearest_support": s_best.price if s_best else None,
            "sr_nearest_resistance": r_best.price if r_best else None,
            "sr_support_confluence_score": s_best.strength if s_best else 0.0,
            "sr_resistance_confluence_score": r_best.strength if r_best else 0.0,
            "sr_support_dist_atr": abs(current_price - s_best.price) / atr if s_best else None,
            "sr_resistance_dist_atr": abs(r_best.price - current_price) / atr if r_best else None,
        }

    def compute_next(self, windows, *, state=None):
        return self.compute_full(windows)


def _round_candidates(price, atr, max_dist, direction):
    if price <= EPSILON:
        return []
    mag = 10 ** math.floor(math.log10(price))
    lo, hi = (price - max_dist, price) if direction == -1 else (price, price + max_dist)
    seen: set[float] = set()
    res = []
    for g, s in [(mag, 0.8), (mag / 10, 0.6), (mag / 20, 0.4)]:
        for lvl in (math.floor(price / g) * g, math.ceil(price / g) * g):
            if lvl > EPSILON and lo < lvl < hi and lvl not in seen:
                seen.add(lvl)
                res.append(ZoneCandidate(lvl, f"round_{g:.0f}", s, "round", "round_number"))
    return res


plugin = SRConsensusPlugin()
