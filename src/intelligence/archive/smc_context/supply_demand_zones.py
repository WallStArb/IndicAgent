"""smc_SupplyDemandZones — Supply and demand zone detection.

Detects Rally-Base-Drop (supply) and Drop-Base-Rally (demand) origin zones
on the primary timeframe. Tracks freshness lifecycle (fresh→tested→mitigated)
and scores zone strength with premium/discount and FVG alignment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.intelligence.plugins import InputSpec
from src.intelligence.utils.gradient_utils import freshness_decay


@dataclass
class _Zone:
    zone_high: float
    zone_low: float
    zone_type: str  # "demand" or "supply"
    created_idx: int
    freshness: float = 1.0
    test_count: int = 0


@dataclass
class SupplyDemandZonesPlugin:
    """Supply/Demand zone detection via base-impulse pattern on 15m bars."""

    name: str = "smc_SupplyDemandZones"
    outputs: frozenset[str] = frozenset(
        {
            "nearest_demand_high",
            "nearest_demand_low",
            "demand_freshness",
            "demand_strength",
            "demand_dist_atr",
            "in_demand_zone",
            "nearest_supply_high",
            "nearest_supply_low",
            "supply_freshness",
            "supply_strength",
            "supply_dist_atr",
            "in_supply_zone",
            "active_demand_zones",
            "active_supply_zones",
            "zone_friction_score",  # Phase 126-06: formalized in SMCContext schema
        }
    )
    min_lookback: int = 30
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"smart_money", "zones"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=150),)
    _state: dict = field(default_factory=dict)

    # Detection thresholds
    impulse_atr_mult: float = 1.5  # close-to-close move must exceed ATR * this
    base_body_ratio: float = 0.5  # base candle body/range must be < this
    base_atr_mult: float = 1.0  # base candle range must be < ATR * this
    max_base_bars: int = 5
    zone_height_cap: float = 2.5  # cap zone height at ATR * this

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
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        open_ = df["open"].to_numpy(dtype=float)
        n = len(df)

        atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            atr = float(np.std(close[-20:])) or 1.0
        current_price = float(close[-1])

        # Scan for zone origins
        zones: list[_Zone] = []
        for i in range(self.max_base_bars + 2, n - 1):
            # Detect impulse at bar i
            cc_move = abs(float(close[i]) - float(close[i - 1]))
            if cc_move < atr * self.impulse_atr_mult:
                continue
            # Overlap check: high of bars must not heavily overlap
            overlap = max(
                0, min(float(high[i]), float(high[i - 1])) - max(float(low[i]), float(low[i - 1]))
            )
            if overlap > atr * 0.4:
                continue

            direction = 1 if float(close[i]) > float(close[i - 1]) else -1

            # Find base left of impulse
            base_bars = []
            for b in range(i - 1, max(i - self.max_base_bars - 1, 0), -1):
                bar_range = float(high[b]) - float(low[b])
                bar_body = abs(float(close[b]) - float(open_[b]))
                if bar_range <= 0:
                    continue
                if (
                    bar_body / bar_range < self.base_body_ratio
                    and bar_range < atr * self.base_atr_mult
                ):
                    base_bars.append(b)
                else:
                    break  # non-base bar interrupts

            if not base_bars:
                continue

            zone_high = float(np.max(high[base_bars]))
            zone_low = float(np.min(low[base_bars]))
            zone_height = zone_high - zone_low
            if zone_height > atr * self.zone_height_cap:
                zone_high = zone_low + atr * self.zone_height_cap  # cap it

            zone_type = "demand" if direction == 1 else "supply"
            zones.append(
                _Zone(
                    zone_high=round(zone_high, 4),
                    zone_low=round(zone_low, 4),
                    zone_type=zone_type,
                    created_idx=i,
                )
            )

        # Lifecycle: mark tested/mitigated based on subsequent price action
        # Optimized: vectorized operations instead of nested loops
        active: list[_Zone] = []
        for zone in zones:
            mitigated = False

            # Vectorized check for price entering zone
            if zone.created_idx + 1 < n:
                price_in_zone = (low[zone.created_idx + 1 :] <= zone.zone_high) & (
                    high[zone.created_idx + 1 :] >= zone.zone_low
                )

                if np.any(price_in_zone):
                    zone.test_count += int(np.sum(price_in_zone))
                    zone.freshness = round(freshness_decay(zone.test_count, k=0.5), 4)

                    # Check if mitigated (close beyond distal edge)
                    if zone.zone_type == "demand":
                        mitigated = np.any(close[zone.created_idx + 1 :] < zone.zone_low)
                    elif zone.zone_type == "supply":
                        mitigated = np.any(close[zone.created_idx + 1 :] > zone.zone_high)

            if not mitigated:
                active.append(zone)

        demand_zones = sorted(
            [z for z in active if z.zone_type == "demand"],
            key=lambda z: abs(current_price - (z.zone_high + z.zone_low) / 2),
        )[:5]
        supply_zones = sorted(
            [z for z in active if z.zone_type == "supply"],
            key=lambda z: abs(current_price - (z.zone_high + z.zone_low) / 2),
        )[:5]

        price_in_premium = features.get("price_in_premium", 0.0)
        fvg_midpoint = features.get("fvg_midpoint", 0.0)

        def zone_strength(z: _Zone) -> float:
            s = z.freshness
            if z.zone_type == "demand" and price_in_premium == 0.0:
                s = min(1.0, s * 1.20)
            elif z.zone_type == "supply" and price_in_premium == 1.0:
                s = min(1.0, s * 1.20)
            if fvg_midpoint and z.zone_low <= fvg_midpoint <= z.zone_high:
                s = min(1.0, s * 1.15)
            age = n - z.created_idx
            age_penalty = max(0.70, 1.0 - (age / 200) * 0.30)
            return round(min(1.0, s * age_penalty), 4)

        result: dict[str, Any] = {
            "active_demand_zones": float(len(demand_zones)),
            "active_supply_zones": float(len(supply_zones)),
        }

        if demand_zones:
            dz = demand_zones[0]
            result.update(
                {
                    "nearest_demand_high": dz.zone_high,
                    "nearest_demand_low": dz.zone_low,
                    "demand_freshness": round(dz.freshness, 4),
                    "demand_strength": zone_strength(dz),
                    "demand_dist_atr": round(
                        abs(current_price - (dz.zone_high + dz.zone_low) / 2) / atr, 4
                    ),
                    "in_demand_zone": 1.0 if dz.zone_low <= current_price <= dz.zone_high else 0.0,
                }
            )
        else:
            result.update(
                {
                    "nearest_demand_high": 0.0,
                    "nearest_demand_low": 0.0,
                    "demand_freshness": 0.0,
                    "demand_strength": 0.0,
                    "demand_dist_atr": 0.0,
                    "in_demand_zone": 0.0,
                }
            )

        if supply_zones:
            sz = supply_zones[0]
            result.update(
                {
                    "nearest_supply_high": sz.zone_high,
                    "nearest_supply_low": sz.zone_low,
                    "supply_freshness": round(sz.freshness, 4),
                    "supply_strength": zone_strength(sz),
                    "supply_dist_atr": round(
                        abs(current_price - (sz.zone_high + sz.zone_low) / 2) / atr, 4
                    ),
                    "in_supply_zone": 1.0 if sz.zone_low <= current_price <= sz.zone_high else 0.0,
                }
            )
        else:
            result.update(
                {
                    "nearest_supply_high": 0.0,
                    "nearest_supply_low": 0.0,
                    "supply_freshness": 0.0,
                    "supply_strength": 0.0,
                    "supply_dist_atr": 0.0,
                    "in_supply_zone": 0.0,
                }
            )

        # zone_friction_score: Phase 126-06 formalization. Captures proximity × quality of the
        # nearest active zone. Formula: freshness * strength * (1 / (1 + dist_atr)).
        # High score = zone is close, fresh, and strong (high friction on price movement).
        # None only when no zones are detected at all (genuine cold-start).
        # 0.0 = zone detected but zero freshness or strength (genuine neutral).
        # Choose the zone with higher friction (max of demand vs supply).
        zf_demand: float | None = None
        zf_supply: float | None = None
        if demand_zones:
            _d_freshness = float(result.get("demand_freshness", 0.0))
            _d_strength = float(result.get("demand_strength", 0.0))
            _d_dist = float(result.get("demand_dist_atr", 0.0))
            zf_demand = round(_d_freshness * _d_strength * (1.0 / (1.0 + _d_dist)), 4)
        if supply_zones:
            _s_freshness = float(result.get("supply_freshness", 0.0))
            _s_strength = float(result.get("supply_strength", 0.0))
            _s_dist = float(result.get("supply_dist_atr", 0.0))
            zf_supply = round(_s_freshness * _s_strength * (1.0 / (1.0 + _s_dist)), 4)

        if zf_demand is not None and zf_supply is not None:
            result["zone_friction_score"] = max(zf_demand, zf_supply)
        elif zf_demand is not None:
            result["zone_friction_score"] = zf_demand
        elif zf_supply is not None:
            result["zone_friction_score"] = zf_supply
        # else: no zones, zone_friction_score absent (None in flat_features via schema default)

        return result

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = SupplyDemandZonesPlugin()
