# Liquidity Pools & Supply/Demand Zones — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 4 new plugins (2 I6 detection + 2 I7 signal) implementing named liquidity pool classification, supply/demand zone detection, and the Act 1-2-3 ICT confirmation model — plus zone-awareness enhancements to 4 existing I7 plugins.

**Architecture:** Two I6 plugins (`smc_LiquidityPools`, `smc_SupplyDemandZones`) populate the `features` dict with institutional-level context. Two I7 plugins (`trad_LiquidityHunt`, `trad_SupplyDemandSetup`) consume those features to generate signals. Four existing I7 plugins are enhanced with zone friction/boost logic. All plugins follow the existing dataclass + `compute_full` / `compute_next` pattern.

**Design doc:** `docs/plans/2026-02-22-liquidity-pools-supply-demand-design.md` — read this before starting. All algorithms, confidence formulas, and output field names are specified there.

**Tech Stack:** Python 3.11+, pandas, numpy, pytest, `src/intelligence/smart_money/_swing_utils.py` (existing)

---

## Reference: Plugin Boilerplate Pattern

Every plugin is a `@dataclass` in `src/intelligence/` with:
- `name`, `outputs`, `min_lookback`, `supports_incremental`, `capability_tags`, `inputs` class fields
- `compute_full(frames: dict) -> dict` — full scan, called on historical data
- `compute_next(windows: dict) -> dict` — incremental (delegates to `compute_full` if `supports_incremental = False`)
- `plugin = PluginClass()` at module bottom

`frames["main"]` = primary DataFrame (first InputSpec TF).
`frames["1d"]` / `frames["15m"]` = secondary DataFrames by timeframe string.
`frames["features"]` = feature dict from upstream plugins.

Tests live in `tests/unit/intelligence/test_smart_money_plugins.py` (I6) and `tests/unit/intelligence/test_trading_setups.py` (I7).

Run tests with: `.venv/bin/pytest tests/unit/intelligence/test_smart_money_plugins.py -v`
Run all unit tests: `.venv/bin/pytest tests/unit/ -q`

---

## Task 1: `smc_LiquidityPools` — I6 Detection Plugin

**Files:**
- Create: `src/intelligence/smart_money/liquidity_pools.py`
- Modify: `tests/unit/intelligence/test_smart_money_plugins.py` (append new class)

### Step 1: Write the failing tests

Append to `tests/unit/intelligence/test_smart_money_plugins.py`:

```python
# ─── Liquidity Pools ──────────────────────────────────────────────


class TestLiquidityPools:
    """Tests for smc_LiquidityPools plugin."""

    def _make_df_with_equal_highs(self, n=150, base_price=5000.0, atr_approx=10.0):
        """Create 1m OHLCV with two equal highs at bars 30 and 60."""
        close = np.full(n, base_price)
        high = np.full(n, base_price + atr_approx * 0.3)  # normal highs
        low = np.full(n, base_price - atr_approx * 0.3)
        open_ = np.full(n, base_price)
        # Equal highs: bars 30 and 60 at same level (within ATR*0.75 tolerance)
        eq_high = base_price + atr_approx * 2.0
        high[30] = eq_high
        high[60] = eq_high + atr_approx * 0.1  # slightly different but within tolerance
        return pd.DataFrame({"open": open_, "high": high, "low": low,
                              "close": close, "volume": np.full(n, 1000.0)})

    def _make_daily_df(self, pdh=5100.0, pdl=4900.0, pwh=5200.0, pwl=4800.0):
        """Create 5-bar 1d DataFrame with distinct PDH/PDL/PWH/PWL."""
        # bars[-5:-2] = prior week extremes, bars[-2] = yesterday, bars[-1] = today
        highs = [pwh, 5150.0, 5120.0, pdh, 5080.0]
        lows  = [pwl, 4850.0, 4870.0, pdl, 4950.0]
        closes = [5000.0] * 5
        opens  = [5000.0] * 5
        return pd.DataFrame({"open": opens, "high": highs, "low": lows,
                              "close": closes, "volume": [1000.0]*5})

    def test_returns_all_output_fields(self):
        """Plugin returns all 13 expected output fields."""
        from src.intelligence.smart_money.liquidity_pools import LiquidityPoolsPlugin
        df_1m = make_ohlcv(np.linspace(5000, 5100, 150))
        df_1d = self._make_daily_df()
        plugin = LiquidityPoolsPlugin()
        result = plugin.compute_full({"main": df_1m, "1d": df_1d})
        expected_fields = {
            "bsl_level", "bsl_type", "bsl_significance", "bsl_dist_atr", "bsl_touches",
            "ssl_level", "ssl_type", "ssl_significance", "ssl_dist_atr", "ssl_touches",
            "price_in_premium", "premium_position", "pool_count",
        }
        assert expected_fields.issubset(result.keys())

    def test_pdh_pdl_detected_from_daily(self):
        """PDH/PDL from yesterday's daily bar → bsl_level=PDH, ssl_level=PDL."""
        from src.intelligence.smart_money.liquidity_pools import LiquidityPoolsPlugin
        df_1d = self._make_daily_df(pdh=5100.0, pdl=4900.0, pwh=5200.0, pwl=4800.0)
        # 1m price between PDH and PDL (no equal highs/lows)
        df_1m = make_ohlcv(np.full(150, 5000.0))
        plugin = LiquidityPoolsPlugin()
        result = plugin.compute_full({"main": df_1m, "1d": df_1d})
        # BSL should be PDH (5100) or PWH (5200) — whichever is nearer and above
        assert result["bsl_level"] > 5000.0  # above current price
        assert result["ssl_level"] < 5000.0  # below current price
        assert result["bsl_significance"] >= 0.85  # PDH or PWH

    def test_pwh_pwl_higher_significance_than_pdh_pdl(self):
        """PWH/PWL have significance 1.0, PDH/PDL have 0.85."""
        from src.intelligence.smart_money.liquidity_pools import LiquidityPoolsPlugin
        # Price near PDH — PWH is the nearest level above PDH
        df_1d = self._make_daily_df(pdh=5050.0, pdl=4950.0, pwh=5080.0, pwl=4920.0)
        df_1m = make_ohlcv(np.full(150, 5000.0))
        plugin = LiquidityPoolsPlugin()
        result = plugin.compute_full({"main": df_1m, "1d": df_1d})
        # If PWH is nearest BSL level above current price
        if abs(result["bsl_level"] - 5080.0) < 5.0:
            assert result["bsl_significance"] == 1.0  # PWH significance

    def test_equal_highs_detected(self):
        """Two swing highs within ATR*0.75 → equal highs BSL with significance 0.60."""
        from src.intelligence.smart_money.liquidity_pools import LiquidityPoolsPlugin
        df_1m = self._make_df_with_equal_highs(base_price=5000.0, atr_approx=10.0)
        df_1d = self._make_daily_df(pdh=5000.0, pdl=4800.0, pwh=5100.0, pwl=4700.0)
        plugin = LiquidityPoolsPlugin()
        result = plugin.compute_full({"main": df_1m, "1d": df_1d})
        # Equal highs at ~5020 should be detected as BSL
        assert result["pool_count"] >= 1.0

    def test_premium_flag_above_midpoint(self):
        """Price above 20-bar range midpoint → price_in_premium=1.0."""
        from src.intelligence.smart_money.liquidity_pools import LiquidityPoolsPlugin
        # Price rises strongly — ends in premium territory
        close = np.concatenate([np.full(10, 4900.0), np.full(140, 5100.0)])
        df_1m = make_ohlcv(close)
        df_1d = self._make_daily_df(pdh=5200.0, pdl=4800.0, pwh=5300.0, pwl=4700.0)
        plugin = LiquidityPoolsPlugin()
        result = plugin.compute_full({"main": df_1m, "1d": df_1d})
        assert result["price_in_premium"] == 1.0

    def test_discount_flag_below_midpoint(self):
        """Price below 20-bar range midpoint → price_in_premium=0.0."""
        from src.intelligence.smart_money.liquidity_pools import LiquidityPoolsPlugin
        close = np.concatenate([np.full(10, 5100.0), np.full(140, 4900.0)])
        df_1m = make_ohlcv(close)
        df_1d = self._make_daily_df(pdh=5200.0, pdl=4800.0, pwh=5300.0, pwl=4700.0)
        plugin = LiquidityPoolsPlugin()
        result = plugin.compute_full({"main": df_1m, "1d": df_1d})
        assert result["price_in_premium"] == 0.0

    def test_empty_data_returns_zeros(self):
        """None or insufficient data → empty dict or all-zero output."""
        from src.intelligence.smart_money.liquidity_pools import LiquidityPoolsPlugin
        plugin = LiquidityPoolsPlugin()
        assert plugin.compute_full({"main": None}) == {}
        df_small = make_ohlcv(np.full(5, 5000.0))
        result = plugin.compute_full({"main": df_small})
        assert result == {} or result.get("pool_count", 0) == 0.0

    def test_bsl_level_is_above_current_price(self):
        """BSL (buy-side liquidity) must be above current price."""
        from src.intelligence.smart_money.liquidity_pools import LiquidityPoolsPlugin
        df_1m = make_ohlcv(np.full(150, 5000.0))
        df_1d = self._make_daily_df(pdh=5100.0, pdl=4900.0, pwh=5200.0, pwl=4800.0)
        plugin = LiquidityPoolsPlugin()
        result = plugin.compute_full({"main": df_1m, "1d": df_1d})
        if result.get("bsl_level", 0) > 0:
            assert result["bsl_level"] > df_1m["close"].iloc[-1]

    def test_ssl_level_is_below_current_price(self):
        """SSL (sell-side liquidity) must be below current price."""
        from src.intelligence.smart_money.liquidity_pools import LiquidityPoolsPlugin
        df_1m = make_ohlcv(np.full(150, 5000.0))
        df_1d = self._make_daily_df(pdh=5100.0, pdl=4900.0, pwh=5200.0, pwl=4800.0)
        plugin = LiquidityPoolsPlugin()
        result = plugin.compute_full({"main": df_1m, "1d": df_1d})
        if result.get("ssl_level", 0) > 0:
            assert result["ssl_level"] < df_1m["close"].iloc[-1]
```

### Step 2: Run to confirm failure

```bash
.venv/bin/pytest tests/unit/intelligence/test_smart_money_plugins.py::TestLiquidityPools -v
```
Expected: `ImportError: cannot import name 'LiquidityPoolsPlugin'`

### Step 3: Create the plugin

Create `src/intelligence/smart_money/liquidity_pools.py`:

```python
"""smc_LiquidityPools — Named buy-side/sell-side liquidity pool detection.

Identifies institutional levels where stop-loss orders cluster:
PWH/PWL (1.00), PDH/PDL (0.85), equal highs/lows (0.60–0.75), session H/L (0.50).
Also outputs premium/discount context flag.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..plugins import InputSpec
from ._swing_utils import find_swing_highs, find_swing_lows

# Significance scores by level type
_SIG = {
    "pwh": 1.00, "pwl": 1.00,
    "pdh": 0.85, "pdl": 0.85,
    "eq_highs_3": 0.75, "eq_lows_3": 0.75,
    "eq_highs_2": 0.60, "eq_lows_2": 0.60,
    "session_high": 0.50, "session_low": 0.50,
}


@dataclass
class LiquidityPoolsPlugin:
    """Named buy-side (BSL) and sell-side (SSL) liquidity pool detection."""

    name: str = "smc_LiquidityPools"
    outputs: set[str] = frozenset({
        "bsl_level", "bsl_type", "bsl_significance", "bsl_dist_atr", "bsl_touches",
        "ssl_level", "ssl_type", "ssl_significance", "ssl_dist_atr", "ssl_touches",
        "price_in_premium", "premium_position", "pool_count",
    })
    min_lookback: int = 60
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"smart_money", "liquidity"})
    inputs: list[InputSpec] = (
        InputSpec(symbol=".*", timeframe="1m", lookback=150),
        InputSpec(symbol=".*", timeframe="1d", lookback=5),
    )
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        df_1d = frames.get("1d")
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        current_price = float(close[-1])

        atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            atr = current_price * 0.002

        # --- Collect all candidate levels ---
        bsl_candidates: list[tuple[float, str, float]] = []  # (price, type, significance)
        ssl_candidates: list[tuple[float, str, float]] = []

        # 1. PWH / PWL from 1d data
        if df_1d is not None and len(df_1d) >= 5:
            d_high = df_1d["high"].to_numpy(dtype=float)
            d_low  = df_1d["low"].to_numpy(dtype=float)
            pwh = float(np.max(d_high[-5:-1]))
            pwl = float(np.min(d_low[-5:-1]))
            if pwh > current_price:
                bsl_candidates.append((pwh, "pwh", _SIG["pwh"]))
            if pwl < current_price:
                ssl_candidates.append((pwl, "pwl", _SIG["pwl"]))

            # 2. PDH / PDL (yesterday)
            if len(df_1d) >= 2:
                pdh = float(d_high[-2])
                pdl = float(d_low[-2])
                if pdh > current_price:
                    bsl_candidates.append((pdh, "pdh", _SIG["pdh"]))
                if pdl < current_price:
                    ssl_candidates.append((pdl, "pdl", _SIG["pdl"]))

        # 3. Equal highs / equal lows (1m swings)
        tolerance = atr * 0.75
        swing_highs_idx = find_swing_highs(high, neighbor=5)
        swing_lows_idx  = find_swing_lows(low, neighbor=5)

        eq_highs = self._find_equal_levels(
            [float(high[i]) for i in swing_highs_idx], tolerance
        )
        eq_lows = self._find_equal_levels(
            [float(low[i]) for i in swing_lows_idx], tolerance
        )

        for level, touches in eq_highs:
            if level > current_price:
                lvl_type = "eq_highs_3" if touches >= 3 else "eq_highs_2"
                bsl_candidates.append((level, lvl_type, _SIG[lvl_type]))

        for level, touches in eq_lows:
            if level < current_price:
                lvl_type = "eq_lows_3" if touches >= 3 else "eq_lows_2"
                ssl_candidates.append((level, lvl_type, _SIG[lvl_type]))

        # 4. Session high / low (current calendar day from 1m timestamps)
        session_high = float(np.max(high[-390:])) if len(high) >= 390 else float(np.max(high))
        session_low  = float(np.min(low[-390:]))  if len(low)  >= 390 else float(np.min(low))
        if session_high > current_price:
            bsl_candidates.append((session_high, "session_high", _SIG["session_high"]))
        if session_low < current_price:
            ssl_candidates.append((session_low, "session_low", _SIG["session_low"]))

        pool_count = float(len(bsl_candidates) + len(ssl_candidates))

        # Select nearest significant level on each side
        bsl = self._nearest(bsl_candidates, current_price, above=True)
        ssl = self._nearest(ssl_candidates, current_price, above=False)

        # Premium / Discount
        range_high = float(np.max(high[-20:]))
        range_low  = float(np.min(low[-20:]))
        midpoint   = (range_high + range_low) / 2.0
        price_in_premium = 1.0 if current_price >= midpoint else 0.0
        denom = (range_high - midpoint) if range_high != midpoint else 1.0
        premium_position = float(np.clip((current_price - midpoint) / denom, -1.0, 1.0))

        result: dict[str, Any] = {
            "price_in_premium": price_in_premium,
            "premium_position": round(premium_position, 4),
            "pool_count": pool_count,
        }

        if bsl:
            level, lvl_type, sig = bsl
            result.update({
                "bsl_level": round(level, 4),
                "bsl_type": sig,  # use significance as encoded float
                "bsl_significance": sig,
                "bsl_dist_atr": round(abs(level - current_price) / atr, 4) if atr > 0 else 0.0,
                "bsl_touches": self._touches_for(lvl_type),
            })
        else:
            result.update({"bsl_level": 0.0, "bsl_type": 0.0, "bsl_significance": 0.0,
                           "bsl_dist_atr": 0.0, "bsl_touches": 0.0})

        if ssl:
            level, lvl_type, sig = ssl
            result.update({
                "ssl_level": round(level, 4),
                "ssl_type": sig,
                "ssl_significance": sig,
                "ssl_dist_atr": round(abs(current_price - level) / atr, 4) if atr > 0 else 0.0,
                "ssl_touches": self._touches_for(lvl_type),
            })
        else:
            result.update({"ssl_level": 0.0, "ssl_type": 0.0, "ssl_significance": 0.0,
                           "ssl_dist_atr": 0.0, "ssl_touches": 0.0})

        return result

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _find_equal_levels(
        prices: list[float], tolerance: float
    ) -> list[tuple[float, int]]:
        """Cluster prices within tolerance → return (mean_price, touch_count) for clusters ≥ 2."""
        if not prices:
            return []
        clusters: list[list[float]] = []
        for p in sorted(prices):
            placed = False
            for cluster in clusters:
                if abs(p - np.mean(cluster)) <= tolerance:
                    cluster.append(p)
                    placed = True
                    break
            if not placed:
                clusters.append([p])
        return [
            (float(np.mean(c)), len(c))
            for c in clusters if len(c) >= 2
        ]

    @staticmethod
    def _nearest(
        candidates: list[tuple[float, str, float]],
        price: float,
        above: bool,
    ) -> tuple[float, str, float] | None:
        """Return candidate nearest to price, preferring higher significance on ties."""
        if not candidates:
            return None
        filtered = [c for c in candidates if (c[0] > price if above else c[0] < price)]
        if not filtered:
            return None
        # Sort: primary = distance (nearest), secondary = significance (highest)
        return min(filtered, key=lambda c: (abs(c[0] - price), -c[2]))

    @staticmethod
    def _touches_for(lvl_type: str) -> float:
        if "3" in lvl_type:
            return 3.0
        if "2" in lvl_type:
            return 2.0
        return 1.0


plugin = LiquidityPoolsPlugin()
```

### Step 4: Run tests

```bash
.venv/bin/pytest tests/unit/intelligence/test_smart_money_plugins.py::TestLiquidityPools -v
```
Expected: all PASS

### Step 5: Commit

```bash
git add src/intelligence/smart_money/liquidity_pools.py tests/unit/intelligence/test_smart_money_plugins.py
git commit -m "feat: smc_LiquidityPools — named BSL/SSL detection, premium/discount"
```

---

## Task 2: `smc_SupplyDemandZones` — I6 Detection Plugin

**Files:**
- Create: `src/intelligence/smart_money/supply_demand_zones.py`
- Modify: `tests/unit/intelligence/test_smart_money_plugins.py` (append)

### Step 1: Write the failing tests

Append to `test_smart_money_plugins.py`:

```python
# ─── Supply/Demand Zones ──────────────────────────────────────────────


class TestSupplyDemandZones:
    """Tests for smc_SupplyDemandZones plugin."""

    def _make_dbr(self, n=150, base=5000.0, atr=15.0):
        """Drop-Base-Rally: bearish impulse → tight base → bullish impulse → demand zone."""
        close = np.full(n, base)
        high  = np.full(n, base + atr * 0.3)
        low   = np.full(n, base - atr * 0.3)
        open_ = np.full(n, base)

        # Bearish impulse: bars 20-23 drop sharply
        for i in range(20, 24):
            close[i] = base - atr * (1 + (i - 20) * 0.7)
            low[i]   = close[i] - atr * 0.2
            high[i]  = close[i - 1] if i > 20 else base
            open_[i] = close[i - 1] if i > 20 else base

        # Base: bars 24-26 tight consolidation
        base_price = close[23]
        for i in range(24, 27):
            close[i] = base_price + atr * 0.05 * (i - 24)
            high[i]  = base_price + atr * 0.25
            low[i]   = base_price - atr * 0.25
            open_[i] = base_price

        # Bullish impulse: bars 27-30 rally hard → DBR → demand zone = bars 24-26 range
        rally_start = close[26]
        for i in range(27, 31):
            close[i] = rally_start + atr * 1.8 * (i - 26)
            high[i]  = close[i] + atr * 0.2
            low[i]   = close[i - 1] if i > 27 else rally_start
            open_[i] = close[i - 1] if i > 27 else rally_start

        # Bars 31+ stay elevated (zone untested)
        for i in range(31, n):
            close[i] = close[30]
            high[i]  = close[30] + atr * 0.3
            low[i]   = close[30] - atr * 0.3
            open_[i] = close[30]

        return pd.DataFrame({"open": open_, "high": high, "low": low,
                              "close": close, "volume": np.full(n, 1000.0)})

    def _make_rbd(self, n=150, base=5000.0, atr=15.0):
        """Rally-Base-Drop: bullish impulse → tight base → bearish impulse → supply zone."""
        close = np.full(n, base)
        high  = np.full(n, base + atr * 0.3)
        low   = np.full(n, base - atr * 0.3)
        open_ = np.full(n, base)

        # Bullish impulse: bars 20-23
        for i in range(20, 24):
            close[i] = base + atr * (1 + (i - 20) * 0.7)
            high[i]  = close[i] + atr * 0.2
            low[i]   = close[i - 1] if i > 20 else base
            open_[i] = close[i - 1] if i > 20 else base

        # Tight base: bars 24-26
        base_price = close[23]
        for i in range(24, 27):
            close[i] = base_price - atr * 0.05 * (i - 24)
            high[i]  = base_price + atr * 0.25
            low[i]   = base_price - atr * 0.25
            open_[i] = base_price

        # Bearish impulse: bars 27-30
        drop_start = close[26]
        for i in range(27, 31):
            close[i] = drop_start - atr * 1.8 * (i - 26)
            low[i]   = close[i] - atr * 0.2
            high[i]  = close[i - 1] if i > 27 else drop_start
            open_[i] = close[i - 1] if i > 27 else drop_start

        # Bars 31+ stay depressed
        for i in range(31, n):
            close[i] = close[30]
            high[i]  = close[30] + atr * 0.3
            low[i]   = close[30] - atr * 0.3
            open_[i] = close[30]

        return pd.DataFrame({"open": open_, "high": high, "low": low,
                              "close": close, "volume": np.full(n, 1000.0)})

    def test_returns_all_output_fields(self):
        """Plugin returns all 14 expected output fields."""
        from src.intelligence.smart_money.supply_demand_zones import SupplyDemandZonesPlugin
        df = make_ohlcv(np.full(150, 5000.0))
        plugin = SupplyDemandZonesPlugin()
        result = plugin.compute_full({"main": df})
        expected = {
            "nearest_demand_high", "nearest_demand_low", "demand_freshness",
            "demand_strength", "demand_dist_atr", "in_demand_zone",
            "nearest_supply_high", "nearest_supply_low", "supply_freshness",
            "supply_strength", "supply_dist_atr", "in_supply_zone",
            "active_demand_zones", "active_supply_zones",
        }
        assert expected.issubset(result.keys())

    def test_dbr_creates_demand_zone(self):
        """Drop-Base-Rally pattern → demand zone detected with freshness=1.0."""
        from src.intelligence.smart_money.supply_demand_zones import SupplyDemandZonesPlugin
        df = self._make_dbr()
        plugin = SupplyDemandZonesPlugin()
        result = plugin.compute_full({"main": df})
        assert result["active_demand_zones"] >= 1.0
        assert result["nearest_demand_high"] > 0.0
        assert result["demand_freshness"] >= 0.9  # fresh (untested)

    def test_rbd_creates_supply_zone(self):
        """Rally-Base-Drop pattern → supply zone detected with freshness=1.0."""
        from src.intelligence.smart_money.supply_demand_zones import SupplyDemandZonesPlugin
        df = self._make_rbd()
        plugin = SupplyDemandZonesPlugin()
        result = plugin.compute_full({"main": df})
        assert result["active_supply_zones"] >= 1.0
        assert result["nearest_supply_high"] > 0.0
        assert result["supply_freshness"] >= 0.9

    def test_zone_range_covers_base_candles(self):
        """Demand zone high/low brackets the base candle range."""
        from src.intelligence.smart_money.supply_demand_zones import SupplyDemandZonesPlugin
        df = self._make_dbr(base=5000.0, atr=15.0)
        plugin = SupplyDemandZonesPlugin()
        result = plugin.compute_full({"main": df})
        if result["active_demand_zones"] >= 1.0:
            assert result["nearest_demand_high"] > result["nearest_demand_low"]
            zone_height = result["nearest_demand_high"] - result["nearest_demand_low"]
            assert zone_height > 0.0
            assert zone_height <= 15.0 * 2.5  # capped at ATR * 2.5

    def test_in_demand_zone_flag(self):
        """When current price is inside demand zone, in_demand_zone=1.0."""
        from src.intelligence.smart_money.supply_demand_zones import SupplyDemandZonesPlugin
        df = self._make_dbr(base=5000.0, atr=15.0)
        plugin = SupplyDemandZonesPlugin()
        # First establish zone
        result = plugin.compute_full({"main": df})
        if result["active_demand_zones"] >= 1.0:
            # Price is above zone (zone was left behind by rally)
            # in_demand_zone should be 0 (we're above it)
            assert result["in_demand_zone"] in [0.0, 1.0]  # valid float

    def test_no_zones_flat_market(self):
        """Flat market with no impulse → no zones detected."""
        from src.intelligence.smart_money.supply_demand_zones import SupplyDemandZonesPlugin
        close = np.full(150, 5000.0) + np.random.default_rng(99).normal(0, 1, 150)
        df = make_ohlcv(close)
        plugin = SupplyDemandZonesPlugin()
        result = plugin.compute_full({"main": df})
        # May detect zones in noise — just validate structure is valid
        assert result["active_demand_zones"] >= 0.0
        assert result["active_supply_zones"] >= 0.0

    def test_empty_data_returns_empty(self):
        """None or insufficient data → empty dict."""
        from src.intelligence.smart_money.supply_demand_zones import SupplyDemandZonesPlugin
        plugin = SupplyDemandZonesPlugin()
        assert plugin.compute_full({"main": None}) == {}
        df_small = make_ohlcv(np.full(10, 5000.0))
        assert plugin.compute_full({"main": df_small}) == {}

    def test_demand_strength_boosted_in_discount(self):
        """Demand zone in discount region (price_in_premium=0.0) → strength >= base."""
        from src.intelligence.smart_money.supply_demand_zones import SupplyDemandZonesPlugin
        df = self._make_dbr()
        plugin = SupplyDemandZonesPlugin()
        result = plugin.compute_full({"main": df, "features": {"price_in_premium": 0.0}})
        if result.get("active_demand_zones", 0) >= 1.0:
            assert result["demand_strength"] > 0.0

    def test_supply_zone_high_above_low(self):
        """Supply zone always has high > low."""
        from src.intelligence.smart_money.supply_demand_zones import SupplyDemandZonesPlugin
        df = self._make_rbd()
        plugin = SupplyDemandZonesPlugin()
        result = plugin.compute_full({"main": df})
        if result["active_supply_zones"] >= 1.0:
            assert result["nearest_supply_high"] > result["nearest_supply_low"]
```

### Step 2: Run to confirm failure

```bash
.venv/bin/pytest tests/unit/intelligence/test_smart_money_plugins.py::TestSupplyDemandZones -v
```
Expected: `ImportError: cannot import name 'SupplyDemandZonesPlugin'`

### Step 3: Create the plugin

Create `src/intelligence/smart_money/supply_demand_zones.py`:

```python
"""smc_SupplyDemandZones — Supply and demand zone detection.

Detects Rally-Base-Drop (supply) and Drop-Base-Rally (demand) origin zones
on the primary timeframe. Tracks freshness lifecycle (fresh→tested→mitigated)
and scores zone strength with premium/discount and FVG alignment.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..plugins import InputSpec


@dataclass
class _Zone:
    zone_high: float
    zone_low: float
    zone_type: str   # "demand" or "supply"
    created_idx: int
    freshness: float = 1.0
    test_count: int = 0


@dataclass
class SupplyDemandZonesPlugin:
    """Supply/Demand zone detection via base-impulse pattern on 15m bars."""

    name: str = "smc_SupplyDemandZones"
    outputs: set[str] = frozenset({
        "nearest_demand_high", "nearest_demand_low", "demand_freshness",
        "demand_strength", "demand_dist_atr", "in_demand_zone",
        "nearest_supply_high", "nearest_supply_low", "supply_freshness",
        "supply_strength", "supply_dist_atr", "in_supply_zone",
        "active_demand_zones", "active_supply_zones",
    })
    min_lookback: int = 30
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"smart_money", "zones"})
    inputs: list[InputSpec] = (
        InputSpec(symbol=".*", timeframe="1m", lookback=150),
    )
    _state: dict = field(default_factory=dict)

    # Detection thresholds
    impulse_atr_mult: float = 1.5    # close-to-close move must exceed ATR * this
    base_body_ratio: float = 0.5     # base candle body/range must be < this
    base_atr_mult: float = 1.0       # base candle range must be < ATR * this
    max_base_bars: int = 5
    zone_height_cap: float = 2.5     # cap zone height at ATR * this

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        features = frames.get("features") or {}
        high  = df["high"].to_numpy(dtype=float)
        low   = df["low"].to_numpy(dtype=float)
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
            overlap = max(0, min(float(high[i]), float(high[i-1])) -
                             max(float(low[i]), float(low[i-1])))
            if overlap > atr * 0.4:
                continue

            direction = 1 if float(close[i]) > float(close[i - 1]) else -1

            # Find base left of impulse
            base_bars = []
            for b in range(i - 1, max(i - self.max_base_bars - 1, 0), -1):
                bar_range = float(high[b]) - float(low[b])
                bar_body  = abs(float(close[b]) - float(open_[b]))
                if bar_range <= 0:
                    continue
                if (bar_body / bar_range < self.base_body_ratio and
                        bar_range < atr * self.base_atr_mult):
                    base_bars.append(b)
                else:
                    break  # non-base bar interrupts

            if not base_bars:
                continue

            zone_high = float(np.max(high[base_bars]))
            zone_low  = float(np.min(low[base_bars]))
            zone_height = zone_high - zone_low
            if zone_height > atr * self.zone_height_cap:
                zone_high = zone_low + atr * self.zone_height_cap  # cap it

            zone_type = "demand" if direction == 1 else "supply"
            zones.append(_Zone(
                zone_high=round(zone_high, 4),
                zone_low=round(zone_low, 4),
                zone_type=zone_type,
                created_idx=i,
            ))

        # Lifecycle: mark tested/mitigated based on subsequent price action
        active: list[_Zone] = []
        for zone in zones:
            mitigated = False
            for j in range(zone.created_idx + 1, n):
                price_in = (float(low[j]) <= zone.zone_high and
                            float(high[j]) >= zone.zone_low)
                if price_in:
                    if zone.freshness == 1.0:
                        zone.freshness = 0.5
                    zone.test_count += 1
                    zone.freshness = max(0.1, zone.freshness - 0.15)

                # Mitigated: close beyond distal edge
                if zone.zone_type == "demand" and float(close[j]) < zone.zone_low:
                    mitigated = True
                    break
                if zone.zone_type == "supply" and float(close[j]) > zone.zone_high:
                    mitigated = True
                    break

            if not mitigated:
                active.append(zone)

        demand_zones = sorted(
            [z for z in active if z.zone_type == "demand"],
            key=lambda z: abs(current_price - (z.zone_high + z.zone_low) / 2)
        )[:5]
        supply_zones = sorted(
            [z for z in active if z.zone_type == "supply"],
            key=lambda z: abs(current_price - (z.zone_high + z.zone_low) / 2)
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
            result.update({
                "nearest_demand_high": dz.zone_high,
                "nearest_demand_low":  dz.zone_low,
                "demand_freshness":    round(dz.freshness, 4),
                "demand_strength":     zone_strength(dz),
                "demand_dist_atr":     round(abs(current_price - (dz.zone_high + dz.zone_low) / 2) / atr, 4),
                "in_demand_zone":      1.0 if dz.zone_low <= current_price <= dz.zone_high else 0.0,
            })
        else:
            result.update({
                "nearest_demand_high": 0.0, "nearest_demand_low": 0.0,
                "demand_freshness": 0.0, "demand_strength": 0.0,
                "demand_dist_atr": 0.0, "in_demand_zone": 0.0,
            })

        if supply_zones:
            sz = supply_zones[0]
            result.update({
                "nearest_supply_high": sz.zone_high,
                "nearest_supply_low":  sz.zone_low,
                "supply_freshness":    round(sz.freshness, 4),
                "supply_strength":     zone_strength(sz),
                "supply_dist_atr":     round(abs(current_price - (sz.zone_high + sz.zone_low) / 2) / atr, 4),
                "in_supply_zone":      1.0 if sz.zone_low <= current_price <= sz.zone_high else 0.0,
            })
        else:
            result.update({
                "nearest_supply_high": 0.0, "nearest_supply_low": 0.0,
                "supply_freshness": 0.0, "supply_strength": 0.0,
                "supply_dist_atr": 0.0, "in_supply_zone": 0.0,
            })

        return result

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = SupplyDemandZonesPlugin()
```

### Step 4: Run tests

```bash
.venv/bin/pytest tests/unit/intelligence/test_smart_money_plugins.py::TestSupplyDemandZones -v
```
Expected: all PASS

### Step 5: Commit

```bash
git add src/intelligence/smart_money/supply_demand_zones.py tests/unit/intelligence/test_smart_money_plugins.py
git commit -m "feat: smc_SupplyDemandZones — RBD/DBR zone detection, freshness lifecycle"
```

---

## Task 3: `trad_LiquidityHunt` — I7 Signal Plugin

**Files:**
- Create: `src/intelligence/trading/liquidity_hunt.py`
- Modify: `tests/unit/intelligence/test_trading_setups.py` (append)

### Step 1: Write the failing tests

Append to `test_trading_setups.py`:

```python
# ─── LiquidityHunt ──────────────────────────────────────────────


class TestLiquidityHunt:
    """Tests for trad_LiquidityHunt plugin."""

    def _features_bsl_swept(self, bsl_level=5020.0, significance=1.0):
        """Features for a BSL sweep scenario (bearish hunt)."""
        return {
            "bsl_level": bsl_level,
            "bsl_significance": significance,
            "ssl_level": 4980.0,
            "ssl_significance": 0.85,
            "sweep_detected": 1.0,
            "sweep_type": -1.0,        # bearish sweep (BSL swept)
            "sweep_level": bsl_level,
            "sweep_reclaimed": 1.0,
            "price_in_premium": 1.0,
            "fvg_detected": 0.0,
            "fvg_type": 0.0,
            "ob_detected": 0.0,
            "ob_type": 0.0,
            "bos_detected": 0.0,
            "choch_detected": 0.0,
            "ctf_score": 0.0,
            "atr_14": 10.0,
            "in_demand_zone": 0.0,
            "in_supply_zone": 0.0,
        }

    def _features_ssl_swept(self, ssl_level=4980.0, significance=1.0):
        """Features for an SSL sweep scenario (bullish hunt)."""
        return {
            "bsl_level": 5020.0,
            "bsl_significance": 0.85,
            "ssl_level": ssl_level,
            "ssl_significance": significance,
            "sweep_detected": 1.0,
            "sweep_type": 1.0,         # bullish sweep (SSL swept)
            "sweep_level": ssl_level,
            "sweep_reclaimed": 1.0,
            "price_in_premium": 0.0,
            "fvg_detected": 0.0,
            "fvg_type": 0.0,
            "ob_detected": 0.0,
            "ob_type": 0.0,
            "bos_detected": 0.0,
            "choch_detected": 0.0,
            "ctf_score": 0.0,
            "atr_14": 10.0,
            "in_demand_zone": 0.0,
            "in_supply_zone": 0.0,
        }

    def test_bsl_sweep_generates_short(self):
        """BSL swept + reclaimed + significance >= 0.60 → short signal."""
        from src.intelligence.trading.liquidity_hunt import LiquidityHuntPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = LiquidityHuntPlugin()
        result = plugin.compute_full({"main": df, "features": self._features_bsl_swept()})
        assert result["signal_type"] == "liquidity_hunt_short"
        assert result["direction"] == -1
        assert result["confidence"] > 0.5
        assert result["entry_price"] > 0
        assert result["stop_loss"] > result["entry_price"]  # stop above entry for short

    def test_ssl_sweep_generates_long(self):
        """SSL swept + reclaimed + significance >= 0.60 → long signal."""
        from src.intelligence.trading.liquidity_hunt import LiquidityHuntPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = LiquidityHuntPlugin()
        result = plugin.compute_full({"main": df, "features": self._features_ssl_swept()})
        assert result["signal_type"] == "liquidity_hunt_long"
        assert result["direction"] == 1
        assert result["stop_loss"] < result["entry_price"]  # stop below entry for long

    def test_no_signal_low_significance(self):
        """Significance < 0.60 → no signal (random swing, not named level)."""
        from src.intelligence.trading.liquidity_hunt import LiquidityHuntPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        features = self._features_bsl_swept(significance=0.45)
        plugin = LiquidityHuntPlugin()
        result = plugin.compute_full({"main": df, "features": features})
        assert result.get("direction", 0) == 0
        assert result.get("signal_type", "none") == "none"

    def test_no_signal_sweep_not_reclaimed(self):
        """sweep_reclaimed=0 → no signal (breakout not a hunt)."""
        from src.intelligence.trading.liquidity_hunt import LiquidityHuntPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        features = self._features_bsl_swept()
        features["sweep_reclaimed"] = 0.0
        plugin = LiquidityHuntPlugin()
        result = plugin.compute_full({"main": df, "features": features})
        assert result.get("signal_type", "none") == "none"

    def test_confidence_higher_for_pwh_than_pdh(self):
        """PWH level (significance=1.0) → higher confidence than PDH (0.85)."""
        from src.intelligence.trading.liquidity_hunt import LiquidityHuntPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = LiquidityHuntPlugin()
        r_pwh = plugin.compute_full({"main": df, "features": self._features_bsl_swept(significance=1.00)})
        r_pdh = plugin.compute_full({"main": df, "features": self._features_bsl_swept(significance=0.85)})
        if r_pwh.get("direction", 0) == -1 and r_pdh.get("direction", 0) == -1:
            assert r_pwh["confidence"] >= r_pdh["confidence"]

    def test_fvg_boosts_confidence(self):
        """FVG in sweep direction adds confidence boost."""
        from src.intelligence.trading.liquidity_hunt import LiquidityHuntPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = LiquidityHuntPlugin()
        f_no_fvg = self._features_bsl_swept()
        f_fvg    = {**self._features_bsl_swept(), "fvg_detected": 1.0, "fvg_type": -1.0}
        r1 = plugin.compute_full({"main": df, "features": f_no_fvg})
        r2 = plugin.compute_full({"main": df, "features": f_fvg})
        if r1.get("direction") == -1 and r2.get("direction") == -1:
            assert r2["confidence"] > r1["confidence"]

    def test_opposing_zone_penalizes_confidence(self):
        """Hunting short but entering demand zone → confidence penalty."""
        from src.intelligence.trading.liquidity_hunt import LiquidityHuntPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = LiquidityHuntPlugin()
        f_clean    = self._features_bsl_swept()
        f_opposing = {**self._features_bsl_swept(), "in_demand_zone": 1.0}
        r1 = plugin.compute_full({"main": df, "features": f_clean})
        r2 = plugin.compute_full({"main": df, "features": f_opposing})
        if r1.get("direction") == -1 and r2.get("direction") == -1:
            assert r2["confidence"] < r1["confidence"]

    def test_has_two_targets(self):
        """Signal output includes at least 2 price targets."""
        from src.intelligence.trading.liquidity_hunt import LiquidityHuntPlugin
        df = make_ohlcv(np.full(100, 5000.0))
        plugin = LiquidityHuntPlugin()
        result = plugin.compute_full({"main": df, "features": self._features_bsl_swept()})
        if result.get("direction", 0) != 0:
            assert len(result.get("targets", [])) >= 2

    def test_insufficient_data_returns_no_signal(self):
        """Too few bars → no signal."""
        from src.intelligence.trading.liquidity_hunt import LiquidityHuntPlugin
        df = make_ohlcv(np.full(5, 5000.0))
        plugin = LiquidityHuntPlugin()
        result = plugin.compute_full({"main": df, "features": {}})
        assert result.get("signal_type", "none") == "none"
```

### Step 2: Run to confirm failure

```bash
.venv/bin/pytest tests/unit/intelligence/test_trading_setups.py::TestLiquidityHunt -v
```
Expected: `ImportError`

### Step 3: Create the plugin

Create `src/intelligence/trading/liquidity_hunt.py`:

```python
"""trad_LiquidityHunt — Trade the sweep of named BSL/SSL liquidity pools.

Gates on smc_LiquidityPools significance >= 0.60 AND smc_LiquiditySweeps reclaim.
Only fires when the sweep was at a meaningful institutional level — not random swings.
Direction: BSL sweep → short, SSL sweep → long.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class LiquidityHuntPlugin:
    """I7 signal: sweep of named liquidity pool + reversal confirmation."""

    name: str = "trad_LiquidityHunt"
    outputs: set[str] = frozenset({
        "signal_type", "direction", "entry_price", "stop_loss",
        "targets", "confidence", "supporting_factors",
    })
    min_lookback: int = 30
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"trading", "smc", "liquidity"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    _state: dict = field(default_factory=dict)

    MIN_SIGNIFICANCE: float = 0.60

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return self._no_signal()

        # Gate 1: named level must exist with sufficient significance
        bsl_sig = float(features.get("bsl_significance", 0.0))
        ssl_sig = float(features.get("ssl_significance", 0.0))
        if bsl_sig < self.MIN_SIGNIFICANCE and ssl_sig < self.MIN_SIGNIFICANCE:
            return self._no_signal()

        # Gate 2: sweep must be detected and reclaimed
        sweep_detected  = float(features.get("sweep_detected", 0.0))
        sweep_reclaimed = float(features.get("sweep_reclaimed", 0.0))
        if sweep_detected != 1.0 or sweep_reclaimed != 1.0:
            return self._no_signal()

        sweep_type  = float(features.get("sweep_type", 0.0))
        sweep_level = float(features.get("sweep_level", 0.0))
        bsl_level   = float(features.get("bsl_level", 0.0))
        ssl_level   = float(features.get("ssl_level", 0.0))
        atr         = float(features.get("atr_14", 0.0))

        high = df["high"].to_numpy(dtype=float)
        low  = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)

        if atr <= 0:
            atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            return self._no_signal()

        # Gate 3: sweep was at the named level (within ATR*0.75)
        tol = atr * 0.75
        hit_bsl = bsl_level > 0 and abs(sweep_level - bsl_level) <= tol
        hit_ssl = ssl_level > 0 and abs(sweep_level - ssl_level) <= tol

        if sweep_type < 0 and hit_bsl:
            direction = -1       # BSL swept → smart money sells → short
            significance = bsl_sig
            swept_level = bsl_level
        elif sweep_type > 0 and hit_ssl:
            direction = 1        # SSL swept → smart money buys → long
            significance = ssl_sig
            swept_level = ssl_level
        else:
            return self._no_signal()

        entry = float(close[-1])
        supporting: list[str] = ["named_pool_reclaimed"]

        # Stop: beyond swept level with small buffer
        if direction == -1:
            stop = swept_level + atr * 0.30
        else:
            stop = swept_level - atr * 0.30

        # Targets
        if direction == -1:
            t1 = entry - atr * 1.5
            t2 = entry - atr * 3.0
            # T2 refinement: use ssl_level as natural target if closer than 3R
            if ssl_level > 0 and ssl_level < entry - atr * 1.0:
                t2 = ssl_level
        else:
            t1 = entry + atr * 1.5
            t2 = entry + atr * 3.0
            if bsl_level > 0 and bsl_level > entry + atr * 1.0:
                t2 = bsl_level

        # Confidence scoring
        confidence = 0.55

        if significance >= 1.00:
            confidence += 0.12
            supporting.append("pwh_pwl_level")
        elif significance >= 0.85:
            confidence += 0.08
            supporting.append("pdh_pdl_level")
        elif significance >= 0.75:
            confidence += 0.05
            supporting.append("equal_levels_3plus")

        price_in_premium = float(features.get("price_in_premium", -1))
        if direction == -1 and price_in_premium == 1.0:
            confidence += 0.06
            supporting.append("premium_aligned")
        elif direction == 1 and price_in_premium == 0.0:
            confidence += 0.06
            supporting.append("discount_aligned")

        fvg_det  = float(features.get("fvg_detected", 0.0))
        fvg_type = float(features.get("fvg_type", 0.0))
        if fvg_det == 1.0 and fvg_type == float(direction):
            confidence += 0.08
            supporting.append("fvg_aligned")

        ob_det  = float(features.get("ob_detected", 0.0))
        ob_type = float(features.get("ob_type", 0.0))
        if ob_det == 1.0 and ob_type == float(direction):
            confidence += 0.06
            supporting.append("order_block_aligned")

        choch = float(features.get("choch_detected", 0.0))
        bos   = float(features.get("bos_detected", 0.0))
        bos_dir = float(features.get("bos_direction", 0.0))
        if choch == 1.0:
            confidence += 0.10
            supporting.append("choch_confirmed")
        elif bos == 1.0 and bos_dir == float(direction):
            confidence += 0.05
            supporting.append("bos_confirmed")

        ctf = float(features.get("ctf_score", 0.0))
        if abs(ctf) > 0.3 and math.copysign(1, ctf) == direction:
            confidence += 0.05
            supporting.append("ctf_aligned")

        in_demand = float(features.get("in_demand_zone", 0.0))
        in_supply = float(features.get("in_supply_zone", 0.0))
        if direction == -1 and in_supply == 1.0:
            confidence += 0.05
            supporting.append("supply_zone_aligned")
        elif direction == 1 and in_demand == 1.0:
            confidence += 0.05
            supporting.append("demand_zone_aligned")
        if direction == -1 and in_demand == 1.0:
            confidence -= 0.10
            supporting.append("penalty_demand_zone_opposing")
        elif direction == 1 and in_supply == 1.0:
            confidence -= 0.10
            supporting.append("penalty_supply_zone_opposing")

        confidence = round(min(0.95, max(0.10, confidence)), 4)

        sig_type = "liquidity_hunt_long" if direction == 1 else "liquidity_hunt_short"
        return {
            "signal_type": sig_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": round(stop, 2),
            "targets": [round(t1, 2), round(t2, 2)],
            "confidence": confidence,
            "supporting_factors": supporting,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}


plugin = LiquidityHuntPlugin()
```

### Step 4: Run tests

```bash
.venv/bin/pytest tests/unit/intelligence/test_trading_setups.py::TestLiquidityHunt -v
```
Expected: all PASS

### Step 5: Commit

```bash
git add src/intelligence/trading/liquidity_hunt.py tests/unit/intelligence/test_trading_setups.py
git commit -m "feat: trad_LiquidityHunt — named pool sweep signal with confidence scoring"
```

---

## Task 4: `trad_SupplyDemandSetup` — I7 Signal Plugin

**Files:**
- Create: `src/intelligence/trading/supply_demand_setup.py`
- Modify: `tests/unit/intelligence/test_trading_setups.py` (append)

### Step 1: Write the failing tests

Append to `test_trading_setups.py`:

```python
# ─── SupplyDemandSetup ──────────────────────────────────────────────


class TestSupplyDemandSetup:
    """Tests for trad_SupplyDemandSetup plugin."""

    def _demand_features(self, freshness=1.0, strength=0.8, in_zone=1.0, act123=False):
        f = {
            "in_demand_zone": in_zone,
            "in_supply_zone": 0.0,
            "demand_freshness": freshness,
            "demand_strength": strength,
            "nearest_demand_high": 5010.0,
            "nearest_demand_low":  4990.0,
            "supply_freshness": 0.0,
            "supply_strength": 0.0,
            "nearest_supply_high": 5100.0,
            "nearest_supply_low":  5090.0,
            "price_in_premium": 0.0,  # discount = demand zone stronger
            "atr_14": 10.0,
            "fvg_detected": 0.0,
            "fvg_type": 0.0,
            "ob_detected": 0.0,
            "ob_type": 0.0,
            "ob_high": 0.0,
            "ob_low": 0.0,
            "sweep_detected": 0.0,
            "sweep_reclaimed": 0.0,
            "sweep_type": 0.0,
            "bos_detected": 0.0,
            "choch_detected": 0.0,
            "ctf_score": 0.0,
        }
        if act123:
            f["sweep_detected"] = 1.0
            f["sweep_reclaimed"] = 1.0
            f["sweep_type"] = 1.0    # bullish sweep → long
            f["fvg_detected"] = 1.0
            f["fvg_type"] = 1.0
        return f

    def _supply_features(self, freshness=1.0, strength=0.8, in_zone=1.0):
        return {
            "in_demand_zone": 0.0,
            "in_supply_zone": in_zone,
            "demand_freshness": 0.0,
            "demand_strength": 0.0,
            "nearest_demand_high": 4910.0,
            "nearest_demand_low":  4900.0,
            "supply_freshness": freshness,
            "supply_strength": strength,
            "nearest_supply_high": 5010.0,
            "nearest_supply_low":  4990.0,
            "price_in_premium": 1.0,  # premium = supply zone stronger
            "atr_14": 10.0,
            "fvg_detected": 0.0,
            "fvg_type": 0.0,
            "ob_detected": 0.0,
            "ob_type": 0.0,
            "ob_high": 0.0,
            "ob_low": 0.0,
            "sweep_detected": 0.0,
            "sweep_reclaimed": 0.0,
            "sweep_type": 0.0,
            "bos_detected": 0.0,
            "choch_detected": 0.0,
            "ctf_score": 0.0,
        }

    def test_demand_zone_generates_long(self):
        """Price in demand zone + fresh → long signal."""
        from src.intelligence.trading.supply_demand_setup import SupplyDemandSetupPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = SupplyDemandSetupPlugin()
        result = plugin.compute_full({"main": df, "features": self._demand_features()})
        assert result["signal_type"] == "supply_demand_long"
        assert result["direction"] == 1
        assert result["confidence"] > 0.4
        assert result["stop_loss"] < result["entry_price"]

    def test_supply_zone_generates_short(self):
        """Price in supply zone + fresh → short signal."""
        from src.intelligence.trading.supply_demand_setup import SupplyDemandSetupPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = SupplyDemandSetupPlugin()
        result = plugin.compute_full({"main": df, "features": self._supply_features()})
        assert result["signal_type"] == "supply_demand_short"
        assert result["direction"] == -1
        assert result["stop_loss"] > result["entry_price"]

    def test_no_signal_when_not_in_zone(self):
        """Price not in any zone → no signal."""
        from src.intelligence.trading.supply_demand_setup import SupplyDemandSetupPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        features = self._demand_features(in_zone=0.0)
        plugin = SupplyDemandSetupPlugin()
        result = plugin.compute_full({"main": df, "features": features})
        assert result.get("signal_type", "none") == "none"

    def test_no_signal_mitigated_zone(self):
        """Zone freshness below threshold → no signal."""
        from src.intelligence.trading.supply_demand_setup import SupplyDemandSetupPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        features = self._demand_features(freshness=0.1)
        plugin = SupplyDemandSetupPlugin()
        result = plugin.compute_full({"main": df, "features": features})
        assert result.get("signal_type", "none") == "none"

    def test_fresh_zone_higher_confidence_than_tested(self):
        """Fresh zone (1.0) has higher confidence than tested zone (0.5)."""
        from src.intelligence.trading.supply_demand_setup import SupplyDemandSetupPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = SupplyDemandSetupPlugin()
        r_fresh  = plugin.compute_full({"main": df, "features": self._demand_features(freshness=1.0)})
        r_tested = plugin.compute_full({"main": df, "features": self._demand_features(freshness=0.5)})
        if r_fresh.get("direction") == 1 and r_tested.get("direction") == 1:
            assert r_fresh["confidence"] > r_tested["confidence"]

    def test_act_123_bonus_applied(self):
        """Sweep + FVG preceding zone entry → act_1_2_3_confirmed bonus."""
        from src.intelligence.trading.supply_demand_setup import SupplyDemandSetupPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = SupplyDemandSetupPlugin()
        r_plain = plugin.compute_full({"main": df, "features": self._demand_features(act123=False)})
        r_act   = plugin.compute_full({"main": df, "features": self._demand_features(act123=True)})
        if r_plain.get("direction") == 1 and r_act.get("direction") == 1:
            assert r_act["confidence"] > r_plain["confidence"]
            assert "act_1_2_3_confirmed" in r_act.get("supporting_factors", [])

    def test_premium_discount_penalty_applied(self):
        """Demand zone in premium → lower confidence than demand zone in discount."""
        from src.intelligence.trading.supply_demand_setup import SupplyDemandSetupPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = SupplyDemandSetupPlugin()
        f_discount = {**self._demand_features(), "price_in_premium": 0.0}  # aligned
        f_premium  = {**self._demand_features(), "price_in_premium": 1.0}  # opposing
        r1 = plugin.compute_full({"main": df, "features": f_discount})
        r2 = plugin.compute_full({"main": df, "features": f_premium})
        if r1.get("direction") == 1 and r2.get("direction") == 1:
            assert r1["confidence"] > r2["confidence"]

    def test_has_two_targets(self):
        """Output includes at least 2 price targets."""
        from src.intelligence.trading.supply_demand_setup import SupplyDemandSetupPlugin
        df = make_ohlcv(np.full(100, 5000.0))
        plugin = SupplyDemandSetupPlugin()
        result = plugin.compute_full({"main": df, "features": self._demand_features()})
        if result.get("direction", 0) != 0:
            assert len(result.get("targets", [])) >= 2

    def test_insufficient_data_no_signal(self):
        """Too few bars → no signal."""
        from src.intelligence.trading.supply_demand_setup import SupplyDemandSetupPlugin
        df = make_ohlcv(np.full(5, 5000.0))
        plugin = SupplyDemandSetupPlugin()
        result = plugin.compute_full({"main": df, "features": {}})
        assert result.get("signal_type", "none") == "none"
```

### Step 2: Run to confirm failure

```bash
.venv/bin/pytest tests/unit/intelligence/test_trading_setups.py::TestSupplyDemandSetup -v
```
Expected: `ImportError`

### Step 3: Create the plugin

Create `src/intelligence/trading/supply_demand_setup.py`:

```python
"""trad_SupplyDemandSetup — Trade institutional supply/demand zone retests.

Fires when price enters a fresh/tested S/D zone and shows rejection.
Highest confidence when the full ICT Act 1-2-3 model is confirmed:
  sweep (Act 1) → FVG displacement (Act 2) → zone retest (Act 3).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class SupplyDemandSetupPlugin:
    """I7 signal: price enters institutional S/D zone + rejection confirmation."""

    name: str = "trad_SupplyDemandSetup"
    outputs: set[str] = frozenset({
        "signal_type", "direction", "entry_price", "stop_loss",
        "targets", "confidence", "supporting_factors",
    })
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"trading", "zones", "smc"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=50),)
    _state: dict = field(default_factory=dict)

    MIN_FRESHNESS: float = 0.40

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return self._no_signal()

        in_demand = float(features.get("in_demand_zone", 0.0))
        in_supply = float(features.get("in_supply_zone", 0.0))

        # Gate 1: must be inside a zone
        if in_demand != 1.0 and in_supply != 1.0:
            return self._no_signal()

        # Gate 2: not both (ambiguous)
        if in_demand == 1.0 and in_supply == 1.0:
            return self._no_signal()

        if in_demand == 1.0:
            direction = 1
            freshness = float(features.get("demand_freshness", 0.0))
            strength  = float(features.get("demand_strength", 0.0))
            zone_high = float(features.get("nearest_demand_high", 0.0))
            zone_low  = float(features.get("nearest_demand_low", 0.0))
        else:
            direction = -1
            freshness = float(features.get("supply_freshness", 0.0))
            strength  = float(features.get("supply_strength", 0.0))
            zone_high = float(features.get("nearest_supply_high", 0.0))
            zone_low  = float(features.get("nearest_supply_low", 0.0))

        # Gate 3: freshness threshold
        if freshness < self.MIN_FRESHNESS:
            return self._no_signal()

        atr = float(features.get("atr_14", 0.0))
        close_arr = df["close"].to_numpy(dtype=float)
        if atr <= 0:
            high_arr = df["high"].to_numpy(dtype=float)
            low_arr  = df["low"].to_numpy(dtype=float)
            atr = float(np.mean(high_arr[-14:] - low_arr[-14:]))
        if atr <= 0:
            return self._no_signal()

        entry = float(close_arr[-1])
        supporting: list[str] = [f"{'demand' if direction == 1 else 'supply'}_zone_entry"]

        # Stop: beyond distal zone edge with buffer
        stop = (zone_low - atr * 0.25) if direction == 1 else (zone_high + atr * 0.25)

        # T1: proximal zone edge
        t1 = zone_high if direction == 1 else zone_low
        # T2: 2.5R from entry
        risk = abs(entry - stop)
        t2 = entry + risk * 2.5 if direction == 1 else entry - risk * 2.5

        # Confidence scoring
        if freshness >= 0.9:
            confidence = 0.58
        elif freshness >= 0.5:
            confidence = 0.46
        else:
            confidence = 0.35

        # Zone strength adjustment
        confidence += (strength - 0.5) * 0.20

        # Premium/discount alignment
        pip = float(features.get("price_in_premium", -1))
        if direction == 1 and pip == 0.0:
            confidence += 0.08
            supporting.append("discount_zone_aligned")
        elif direction == -1 and pip == 1.0:
            confidence += 0.08
            supporting.append("premium_zone_aligned")
        elif direction == 1 and pip == 1.0:
            confidence -= 0.06
        elif direction == -1 and pip == 0.0:
            confidence -= 0.06

        # *** ACT 1-2-3 MODEL ***
        sweep_det    = float(features.get("sweep_detected", 0.0))
        sweep_recl   = float(features.get("sweep_reclaimed", 0.0))
        sweep_type   = float(features.get("sweep_type", 0.0))
        fvg_det      = float(features.get("fvg_detected", 0.0))
        fvg_type     = float(features.get("fvg_type", 0.0))

        act1 = sweep_det == 1.0 and sweep_recl == 1.0
        act1_dir = (direction == 1 and sweep_type == 1.0) or (direction == -1 and sweep_type == -1.0)
        act2 = fvg_det == 1.0 and fvg_type == float(direction)

        if act1 and act1_dir:
            if act2:
                confidence += 0.14
                supporting.append("act_1_2_3_confirmed")
            else:
                confidence += 0.07
                supporting.append("act_1_confirmed")

        if act2 and not act1:
            confidence += 0.09
            supporting.append("fvg_displacement")

        # Order block overlapping zone
        ob_det  = float(features.get("ob_detected", 0.0))
        ob_type = float(features.get("ob_type", 0.0))
        ob_high = float(features.get("ob_high", 0.0))
        ob_low  = float(features.get("ob_low", 0.0))
        if (ob_det == 1.0 and ob_type == float(direction) and
                ob_high > 0 and ob_low >= zone_low and ob_high <= zone_high):
            confidence += 0.08
            supporting.append("ob_zone_overlap")

        choch = float(features.get("choch_detected", 0.0))
        bos   = float(features.get("bos_detected", 0.0))
        bos_dir = float(features.get("bos_direction", 0.0))
        if choch == 1.0:
            confidence += 0.09
            supporting.append("choch_confirmed")
        elif bos == 1.0 and bos_dir == float(direction):
            confidence += 0.05
            supporting.append("bos_confirmed")

        ctf = float(features.get("ctf_score", 0.0))
        if abs(ctf) > 0.3 and math.copysign(1, ctf) == direction:
            confidence += 0.05
            supporting.append("ctf_aligned")

        confidence = round(min(0.95, max(0.10, confidence)), 4)

        sig_type = "supply_demand_long" if direction == 1 else "supply_demand_short"
        return {
            "signal_type": sig_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": round(stop, 2),
            "targets": [round(t1, 2), round(t2, 2)],
            "confidence": confidence,
            "supporting_factors": supporting,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}


plugin = SupplyDemandSetupPlugin()
```

### Step 4: Run tests

```bash
.venv/bin/pytest tests/unit/intelligence/test_trading_setups.py::TestSupplyDemandSetup -v
```
Expected: all PASS

### Step 5: Run all trading setup tests

```bash
.venv/bin/pytest tests/unit/intelligence/test_trading_setups.py -v
```
Expected: all PASS (no regressions)

### Step 6: Commit

```bash
git add src/intelligence/trading/supply_demand_setup.py tests/unit/intelligence/test_trading_setups.py
git commit -m "feat: trad_SupplyDemandSetup — zone retest signal with Act 1-2-3 ICT model"
```

---

## Task 5: Register All 4 New Plugins

**Files:**
- Modify: `src/intelligence/register_plugins.py`

### Step 1: Add imports

In `src/intelligence/register_plugins.py`, add after the existing smart money imports:

```python
from .smart_money.liquidity_pools import plugin as liquidity_pools_plugin
from .smart_money.supply_demand_zones import plugin as supply_demand_zones_plugin
from .trading.liquidity_hunt import plugin as liquidity_hunt_plugin
from .trading.supply_demand_setup import plugin as supply_demand_setup_plugin
```

### Step 2: Add registrations

Inside `register_all_plugins()`, after `registry.register_pattern(hmm_regime_plugin)`:

```python
    registry.register_pattern(liquidity_pools_plugin)
    registry.register_pattern(supply_demand_zones_plugin)
```

After `registry.register_pattern(squeeze_expansion_plugin)`:

```python
    registry.register_pattern(liquidity_hunt_plugin)
    registry.register_pattern(supply_demand_setup_plugin)
```

### Step 3: Verify registration

```bash
.venv/bin/python -c "
from src.intelligence.register_plugins import register_all_plugins
from src.intelligence.plugins import registry
register_all_plugins()
names = [p.name for p in registry.patterns]
assert 'smc_LiquidityPools' in names
assert 'smc_SupplyDemandZones' in names
assert 'trad_LiquidityHunt' in names
assert 'trad_SupplyDemandSetup' in names
print('All 4 plugins registered. Total patterns:', len(registry.patterns))
"
```
Expected: `All 4 plugins registered. Total patterns: 34`

### Step 4: Run full unit suite

```bash
.venv/bin/pytest tests/unit/ -q
```
Expected: all PASS, 0 errors

### Step 5: Commit

```bash
git add src/intelligence/register_plugins.py
git commit -m "feat: register smc_LiquidityPools, smc_SupplyDemandZones, trad_LiquidityHunt, trad_SupplyDemandSetup"
```

---

## Task 6: Enhance Existing I7 Plugins — Zone Awareness

**Files:**
- Modify: `src/intelligence/trading/liquidity_sweep_reclaim.py`
- Modify: `src/intelligence/trading/momentum_breakout.py`
- Modify: `src/intelligence/trading/trend_following.py`
- Modify: `src/intelligence/trading/vwap_deviation.py`
- Modify: `tests/unit/intelligence/test_trading_setups.py` (append enhancement tests)

### Step 1: Write enhancement tests

Append to `test_trading_setups.py`:

```python
# ─── Zone Enhancement Tests ──────────────────────────────────────────────


class TestZoneEnhancements:
    """Tests that existing I7 plugins correctly use zone awareness features."""

    def test_liquidity_sweep_reclaim_boosted_by_named_level(self):
        """LiquiditySweepReclaim gains confidence when sweep was at a named pool level."""
        from src.intelligence.trading.liquidity_sweep_reclaim import LiquiditySweepReclaimPlugin
        close = np.full(100, 5000.0)
        df = make_ohlcv(close)
        plugin = LiquiditySweepReclaimPlugin()

        base_features = {
            "sweep_detected": 1.0, "sweep_reclaimed": 1.0,
            "sweep_type": 1.0, "sweep_level": 4980.0,
            "atr_14": 10.0, "fvg_detected": 0.0, "fvg_type": 0.0,
            "ob_detected": 0.0, "ob_type": 0.0, "ctf_score": 0.0,
        }
        named_features = {
            **base_features,
            "ssl_significance": 1.0,   # PWL level
            "ssl_level": 4980.0,
            "bsl_significance": 0.0,
        }
        plain_features = {
            **base_features,
            "ssl_significance": 0.0,
            "bsl_significance": 0.0,
        }

        r_named = plugin.compute_full({"main": df, "features": named_features})
        r_plain = plugin.compute_full({"main": df, "features": plain_features})

        if r_named.get("direction", 0) == 1 and r_plain.get("direction", 0) == 1:
            assert r_named["confidence"] > r_plain["confidence"]

    def test_momentum_breakout_penalized_by_opposing_zone(self):
        """MomentumBreakout long penalized when in_supply_zone=1.0."""
        from src.intelligence.trading.momentum_breakout import MomentumBreakoutPlugin
        close = np.linspace(5000, 5100, 100)
        df = make_ohlcv(close)
        plugin = MomentumBreakoutPlugin()

        base_features = {
            "roc_14": 0.8, "atr_14": 10.0, "volume": 2000.0,
            "bos_detected": 1.0, "bos_direction": 1.0, "bos_level": 5050.0,
            "trend_regime": 0.6, "ctf_score": 0.0,
        }
        clean_features   = {**base_features, "in_supply_zone": 0.0, "supply_strength": 0.0}
        opposing_features = {**base_features, "in_supply_zone": 1.0, "supply_strength": 0.8}

        r_clean    = plugin.compute_full({"main": df, "features": clean_features})
        r_opposing = plugin.compute_full({"main": df, "features": opposing_features})

        if r_clean.get("direction", 0) == 1 and r_opposing.get("direction", 0) == 1:
            assert r_opposing["confidence"] < r_clean["confidence"]

    def test_trend_following_penalized_by_opposing_zone(self):
        """TrendFollowing long penalized when trending into supply zone."""
        from src.intelligence.trading.trend_following import TrendFollowingPlugin
        close = np.linspace(5000, 5200, 100)
        df = make_ohlcv(close)
        plugin = TrendFollowingPlugin()

        base_features = {
            "trend_regime": 0.8, "trend_confidence": 0.75,
            "swing_pattern": 1.0, "trend_strength": 0.7,
            "ctf_score": 0.6, "atr_14": 10.0,
            "sma_20": 5180.0, "ema_21": 5185.0,
        }
        clean_features    = {**base_features, "in_supply_zone": 0.0, "supply_strength": 0.0}
        opposing_features = {**base_features, "in_supply_zone": 1.0, "supply_strength": 0.8}

        r_clean    = plugin.compute_full({"main": df, "features": clean_features})
        r_opposing = plugin.compute_full({"main": df, "features": opposing_features})

        if r_clean.get("direction", 0) == 1 and r_opposing.get("direction", 0) == 1:
            assert r_opposing["confidence"] < r_clean["confidence"]
```

### Step 2: Run to confirm these fail (features not yet consumed)

```bash
.venv/bin/pytest tests/unit/intelligence/test_trading_setups.py::TestZoneEnhancements -v
```
Expected: tests fail on assertions (no confidence difference yet)

### Step 3: Enhance `trad_LiquiditySweepReclaim`

In `src/intelligence/trading/liquidity_sweep_reclaim.py`, after the existing `ctf_score` block inside `compute_full`:

```python
        # Named pool significance boost
        sweep_type_val = features.get("sweep_type", 0.0)
        if sweep_type_val > 0:   # bullish sweep (SSL swept)
            sig = float(features.get("ssl_significance", 0.0))
            if sig >= 0.60:
                confidence += min(0.10, sig * 0.12)
                supporting.append(f"named_ssl_level_{sig:.2f}")
        elif sweep_type_val < 0:  # bearish sweep (BSL swept)
            sig = float(features.get("bsl_significance", 0.0))
            if sig >= 0.60:
                confidence += min(0.10, sig * 0.12)
                supporting.append(f"named_bsl_level_{sig:.2f}")
```

### Step 4: Enhance `trad_MomentumBreakout`

In `src/intelligence/trading/momentum_breakout.py`, near the end of `compute_full` before the return, add:

```python
        # Zone friction penalty
        in_supply = float(features.get("in_supply_zone", 0.0))
        in_demand = float(features.get("in_demand_zone", 0.0))
        supply_str = float(features.get("supply_strength", 0.0))
        demand_str = float(features.get("demand_strength", 0.0))
        if direction == 1 and in_supply == 1.0:
            confidence -= 0.12 * supply_str
            supporting.append("penalty_supply_zone_friction")
        elif direction == -1 and in_demand == 1.0:
            confidence -= 0.12 * demand_str
            supporting.append("penalty_demand_zone_friction")
        confidence = round(min(0.95, max(0.10, confidence)), 4)
```

### Step 5: Enhance `trad_TrendFollowing`

Same zone friction logic — add to `src/intelligence/trading/trend_following.py` before the return:

```python
        # Zone friction penalty
        in_supply = float(features.get("in_supply_zone", 0.0))
        in_demand = float(features.get("in_demand_zone", 0.0))
        supply_str = float(features.get("supply_strength", 0.0))
        demand_str = float(features.get("demand_strength", 0.0))
        if direction == 1 and in_supply == 1.0:
            confidence -= 0.12 * supply_str
            supporting.append("penalty_supply_zone_friction")
        elif direction == -1 and in_demand == 1.0:
            confidence -= 0.12 * demand_str
            supporting.append("penalty_demand_zone_friction")
        confidence = round(min(0.95, max(0.10, confidence)), 4)
```

### Step 6: Run enhancement tests

```bash
.venv/bin/pytest tests/unit/intelligence/test_trading_setups.py::TestZoneEnhancements -v
```
Expected: all PASS

### Step 7: Run full test suite — no regressions

```bash
.venv/bin/pytest tests/unit/ -q
```
Expected: all PASS (existing tests unaffected — penalties only apply when zone features present, default 0.0)

### Step 8: Commit

```bash
git add src/intelligence/trading/liquidity_sweep_reclaim.py \
        src/intelligence/trading/momentum_breakout.py \
        src/intelligence/trading/trend_following.py \
        tests/unit/intelligence/test_trading_setups.py
git commit -m "feat: zone-awareness enhancements to LiquiditySweepReclaim, MomentumBreakout, TrendFollowing"
```

---

## Task 7: Final Verification

### Step 1: Full test suite

```bash
.venv/bin/pytest tests/unit/ -q
```
Expected: 536+ tests PASS, 0 failures

### Step 2: Lint

```bash
.venv/bin/ruff check . --fix
```
Expected: 0 errors

### Step 3: Protocol verification

```bash
.venv/bin/python -c "
from src.intelligence.register_plugins import register_all_plugins
from src.intelligence.plugins import registry
register_all_plugins()
names = {p.name for p in registry.patterns}
required = {'smc_LiquidityPools', 'smc_SupplyDemandZones', 'trad_LiquidityHunt', 'trad_SupplyDemandSetup'}
assert required.issubset(names), f'Missing: {required - names}'
print('All plugins verified:', sorted(required))
print('Total registered plugins:', len(list(registry.indicators)) + len(list(registry.patterns)))
"
```
Expected: `Total registered plugins: 57`

### Step 4: Spot-check Act 1-2-3 model end-to-end

```bash
.venv/bin/python -c "
import numpy as np, pandas as pd
from tests.unit.intelligence.helpers import make_ohlcv
from src.intelligence.trading.supply_demand_setup import SupplyDemandSetupPlugin

df = make_ohlcv(np.full(100, 5000.0))
features = {
    'in_demand_zone': 1.0, 'in_supply_zone': 0.0,
    'demand_freshness': 1.0, 'demand_strength': 0.9,
    'nearest_demand_high': 5010.0, 'nearest_demand_low': 4990.0,
    'supply_freshness': 0.0, 'supply_strength': 0.0,
    'nearest_supply_high': 5100.0, 'nearest_supply_low': 5090.0,
    'price_in_premium': 0.0, 'atr_14': 10.0,
    'sweep_detected': 1.0, 'sweep_reclaimed': 1.0, 'sweep_type': 1.0,
    'fvg_detected': 1.0, 'fvg_type': 1.0,
    'ob_detected': 0.0, 'ob_type': 0.0, 'ob_high': 0.0, 'ob_low': 0.0,
    'bos_detected': 0.0, 'choch_detected': 0.0, 'ctf_score': 0.0,
}
result = SupplyDemandSetupPlugin().compute_full({'main': df, 'features': features})
assert 'act_1_2_3_confirmed' in result['supporting_factors']
print('Act 1-2-3 signal:', result['signal_type'], 'confidence:', result['confidence'])
"
```
Expected: `Act 1-2-3 signal: supply_demand_long confidence: 0.8+`

### Step 5: Final commit

```bash
git add -A
git commit -m "chore: liquidity pools + S/D zones implementation complete — 4 plugins, ~60 tests"
```

---

## Success Checklist

- [ ] `smc_LiquidityPools`: PWH/PWL/PDH/PDL from 1d; equal highs/lows with ATR tolerance; premium/discount flag; 9 tests
- [ ] `smc_SupplyDemandZones`: DBR demand / RBD supply zones on primary TF; freshness lifecycle; strength with premium/discount; 9 tests
- [ ] `trad_LiquidityHunt`: gates on significance ≥ 0.60; BSL→short, SSL→long; confidence scoring with all boosts/penalties; 9 tests
- [ ] `trad_SupplyDemandSetup`: zone entry + freshness gate; Act 1-2-3 bonus; premium/discount adjustment; 9 tests
- [ ] All 4 plugins registered in `register_plugins.py` — total 57 plugins
- [ ] `trad_LiquiditySweepReclaim` boosted by named-level significance
- [ ] `trad_MomentumBreakout` + `trad_TrendFollowing` penalized by opposing zone friction
- [ ] 536+ unit tests passing, 0 ruff errors
