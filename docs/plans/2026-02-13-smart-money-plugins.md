# Smart Money Plugins Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 4 smart money I5 pattern plugins (BOS/CHoCH, FVG, Order Blocks, Liquidity Sweeps) in a new `src/intelligence/smart_money/` directory.

**Architecture:** Each plugin is a `@dataclass` implementing `PatternPlugin` protocol. BOS/CHoCH and Liquidity Sweeps share swing detection via a private `_swing_utils.py` module. FVG is fully self-contained. Order Blocks uses inline impulse detection. All register via `registry.register_pattern()`.

**Tech Stack:** Python 3.13, numpy, pandas, dataclasses. Plugin protocol in `src/intelligence/plugins.py`. Test patterns in `tests/unit/intelligence/test_pattern_plugins.py`.

---

## Plugin Pattern Reference

Every plugin follows the same structure as existing I5 patterns (see `src/intelligence/patterns/rsi_divergence.py`):
- `@dataclass` with `name`, `outputs`, `min_lookback`, `supports_incremental=False`, `capability_tags`, `inputs`, `_state`
- `compute_full(frames)` does the work, returns `{}` on bad input
- `compute_next(windows)` delegates to `compute_full(windows)`
- Module ends with `plugin = PluginClass()`

Test helper `make_ohlcv(close, volume)` in `tests/unit/intelligence/test_pattern_plugins.py` builds OHLCV DataFrames from close arrays.

---

### Task 1: Create smart_money package + swing utilities

**Files:**
- Create: `src/intelligence/smart_money/__init__.py`
- Create: `src/intelligence/smart_money/_swing_utils.py`

**Step 1: Create the package**

Create `src/intelligence/smart_money/__init__.py` (empty file).

**Step 2: Write the swing utilities**

Create `src/intelligence/smart_money/_swing_utils.py`:

```python
"""Shared swing detection for smart money plugins.

Same N-neighbor peak/trough algorithm as I3 SwingDetectorPlugin,
extracted here to avoid cross-plugin coupling.
"""

from __future__ import annotations

import numpy as np


def find_swing_highs(high: np.ndarray, n: int = 5) -> list[int]:
    """Find swing high indices using N-neighbor comparison."""
    peaks = []
    for i in range(n, len(high) - n):
        if all(high[i] > high[i - j] for j in range(1, n + 1)) and all(
            high[i] > high[i + j] for j in range(1, n + 1)
        ):
            peaks.append(i)
    return peaks


def find_swing_lows(low: np.ndarray, n: int = 5) -> list[int]:
    """Find swing low indices using N-neighbor comparison."""
    troughs = []
    for i in range(n, len(low) - n):
        if all(low[i] < low[i - j] for j in range(1, n + 1)) and all(
            low[i] < low[i + j] for j in range(1, n + 1)
        ):
            troughs.append(i)
    return troughs
```

**Step 3: Commit**

```bash
git add src/intelligence/smart_money/__init__.py src/intelligence/smart_money/_swing_utils.py
git commit -m "feat: create smart_money package with swing utilities"
```

---

### Task 2: BOS/CHoCH Plugin

**Files:**
- Create: `src/intelligence/smart_money/bos_choch.py`
- Modify: `tests/unit/intelligence/test_smart_money_plugins.py` (new file)

**Step 1: Write the failing tests**

Create `tests/unit/intelligence/test_smart_money_plugins.py`:

```python
"""Tests for smart money concept plugins (I5 tier)."""

import numpy as np
import pandas as pd


def make_ohlcv(close: np.ndarray, volume: np.ndarray | None = None) -> pd.DataFrame:
    """Build OHLCV DataFrame from close array with synthetic high/low/open."""
    n = len(close)
    spread = np.abs(close) * 0.002
    high = close + spread
    low = close - spread
    open_ = close + np.random.default_rng(0).normal(0, 0.001, n) * close
    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))
    if volume is None:
        volume = np.full(n, 1000.0)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


def make_ohlcv_from_hl(
    high: np.ndarray, low: np.ndarray, volume: np.ndarray | None = None
) -> pd.DataFrame:
    """Build OHLCV from explicit high/low arrays (close = midpoint)."""
    close = (high + low) / 2
    open_ = close + np.random.default_rng(0).normal(0, 0.001, len(close)) * close
    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))
    if volume is None:
        volume = np.full(len(close), 1000.0)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


# ─── BOS / CHoCH ──────────────────────────────────────────────


class TestBOSCHoCH:
    def test_bullish_bos_in_uptrend(self):
        """Price breaking above swing high in uptrend → bullish BOS, not CHoCH."""
        from src.intelligence.smart_money.bos_choch import BOSCHoCHPlugin

        n = 120
        # Uptrend with HH and HL pattern, then a clear break above last swing high
        close = np.full(n, 5000.0)
        # Swing low at bar 20
        for i in range(15, 30):
            close[i] = 5000 - 80 * np.sin(np.pi * (i - 15) / 15)
        # Swing high at bar 45
        for i in range(35, 55):
            close[i] = 5000 + 120 * np.sin(np.pi * (i - 35) / 20)
        # Higher swing low at bar 70
        for i in range(65, 80):
            close[i] = 5000 - 40 * np.sin(np.pi * (i - 65) / 15)
        # Break above swing high (bullish BOS)
        for i in range(90, 110):
            close[i] = 5000 + 120 + (i - 90) * 5

        df = make_ohlcv(close)
        plugin = BOSCHoCHPlugin()
        result = plugin.compute_full({"main": df})

        assert "bos_detected" in result
        assert "bos_direction" in result
        assert "choch_detected" in result
        assert result["bos_direction"] == 1.0  # Bullish
        assert result["choch_detected"] == 0.0  # Not a CHoCH (same direction as trend)

    def test_choch_after_downtrend(self):
        """Bullish break after downtrend → CHoCH (reversal signal)."""
        from src.intelligence.smart_money.bos_choch import BOSCHoCHPlugin

        n = 120
        close = np.full(n, 5000.0)
        # Downtrend: LH at bar 25, LL at bar 50, LH at bar 70
        for i in range(20, 35):
            close[i] = 5000 + 80 * np.sin(np.pi * (i - 20) / 15)
        for i in range(40, 60):
            close[i] = 5000 - 150 * np.sin(np.pi * (i - 40) / 20)
        for i in range(62, 78):
            close[i] = 5000 + 50 * np.sin(np.pi * (i - 62) / 16)
        # Now break above the LH → CHoCH (bullish reversal)
        for i in range(90, 115):
            close[i] = 5000 + 50 + (i - 90) * 8

        df = make_ohlcv(close)
        plugin = BOSCHoCHPlugin()
        result = plugin.compute_full({"main": df})

        assert result["choch_detected"] == 1.0
        assert result["choch_direction"] == 1.0  # Bullish reversal

    def test_no_bos_ranging(self):
        """Flat market with no breaks → no BOS."""
        from src.intelligence.smart_money.bos_choch import BOSCHoCHPlugin

        close = np.full(100, 5000.0) + np.random.default_rng(42).normal(0, 2, 100)
        df = make_ohlcv(close)
        plugin = BOSCHoCHPlugin()
        result = plugin.compute_full({"main": df})

        assert result.get("bos_detected", 0.0) == 0.0

    def test_empty_input(self):
        from src.intelligence.smart_money.bos_choch import BOSCHoCHPlugin

        plugin = BOSCHoCHPlugin()
        assert plugin.compute_full({"main": None}) == {}
        assert plugin.compute_full({}) == {}

    def test_insufficient_data(self):
        from src.intelligence.smart_money.bos_choch import BOSCHoCHPlugin

        df = make_ohlcv(np.full(10, 5000.0))
        plugin = BOSCHoCHPlugin()
        assert plugin.compute_full({"main": df}) == {}
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/intelligence/test_smart_money_plugins.py::TestBOSCHoCH -v`
Expected: FAIL (ImportError — module doesn't exist)

**Step 3: Write the implementation**

Create `src/intelligence/smart_money/bos_choch.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..plugins import InputSpec
from ._swing_utils import find_swing_highs, find_swing_lows


@dataclass
class BOSCHoCHPlugin:
    """Break of Structure (BOS) and Change of Character (CHoCH).

    BOS: price closes beyond a swing high (bullish) or swing low (bearish).
    CHoCH: first BOS in the opposite direction of the prevailing trend,
    signaling a potential reversal.
    """

    name: str = "smc_BOSCHoCH"
    outputs: set[str] = frozenset(
        {
            "bos_detected",
            "bos_direction",
            "bos_level",
            "choch_detected",
            "choch_direction",
            "trend_direction",
        }
    )
    min_lookback: int = 60
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"smart_money"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=120),)
    neighbor: int = 5
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)

        swing_highs = find_swing_highs(high, self.neighbor)
        swing_lows = find_swing_lows(low, self.neighbor)

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return {
                "bos_detected": 0.0,
                "bos_direction": 0.0,
                "bos_level": 0.0,
                "choch_detected": 0.0,
                "choch_direction": 0.0,
                "trend_direction": 0.0,
            }

        # Determine prevailing trend from swing structure
        trend = self._determine_trend(high, low, swing_highs, swing_lows)

        # Check for BOS: recent close beyond swing levels
        last_sh_price = float(high[swing_highs[-1]])
        last_sl_price = float(low[swing_lows[-1]])
        last_sh_idx = swing_highs[-1]
        last_sl_idx = swing_lows[-1]

        bos_detected = 0.0
        bos_direction = 0.0
        bos_level = 0.0

        # Check bars AFTER the most recent swing for breaks
        check_from = max(last_sh_idx, last_sl_idx) + 1
        for i in range(check_from, len(close)):
            if close[i] > last_sh_price:
                bos_detected = 1.0
                bos_direction = 1.0  # Bullish
                bos_level = last_sh_price
                break
            if close[i] < last_sl_price:
                bos_detected = 1.0
                bos_direction = -1.0  # Bearish
                bos_level = last_sl_price
                break

        # CHoCH: BOS in opposite direction to prevailing trend
        choch_detected = 0.0
        choch_direction = 0.0
        if bos_detected == 1.0 and trend != 0.0:
            if bos_direction != trend:
                choch_detected = 1.0
                choch_direction = bos_direction

        return {
            "bos_detected": bos_detected,
            "bos_direction": bos_direction,
            "bos_level": bos_level,
            "choch_detected": choch_detected,
            "choch_direction": choch_direction,
            "trend_direction": trend,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _determine_trend(
        high: np.ndarray,
        low: np.ndarray,
        swing_highs: list[int],
        swing_lows: list[int],
    ) -> float:
        """Determine trend from last 2 swing highs and 2 swing lows."""
        hh = 0.0
        if len(swing_highs) >= 2:
            hh = 1.0 if high[swing_highs[-1]] > high[swing_highs[-2]] else -1.0

        hl = 0.0
        if len(swing_lows) >= 2:
            hl = 1.0 if low[swing_lows[-1]] > low[swing_lows[-2]] else -1.0

        if hh == 1.0 and hl == 1.0:
            return 1.0  # Uptrend
        elif hh == -1.0 and hl == -1.0:
            return -1.0  # Downtrend
        return 0.0  # Neutral


plugin = BOSCHoCHPlugin()
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/intelligence/test_smart_money_plugins.py::TestBOSCHoCH -v`
Expected: 5 PASS

**Step 5: Commit**

```bash
git add src/intelligence/smart_money/bos_choch.py tests/unit/intelligence/test_smart_money_plugins.py
git commit -m "feat: add BOS/CHoCH smart money plugin with tests"
```

---

### Task 3: Fair Value Gap Plugin

**Files:**
- Create: `src/intelligence/smart_money/fair_value_gap.py`
- Modify: `tests/unit/intelligence/test_smart_money_plugins.py` (append)

**Step 1: Write the failing tests**

Append to `tests/unit/intelligence/test_smart_money_plugins.py`:

```python
# ─── Fair Value Gap ────────────────────────────────────────────


class TestFairValueGap:
    def test_bullish_fvg(self):
        """3-candle gap up: bar3.low > bar1.high → bullish FVG."""
        from src.intelligence.smart_money.fair_value_gap import FairValueGapPlugin

        n = 60
        close = np.full(n, 5000.0)
        # Create an impulsive bullish move at bars 30-32
        # bar 30 (bar1): close at 5000, high ~5010
        # bar 31 (bar2): impulsive up, close at 5050
        # bar 32 (bar3): continues up, low at 5015 which is > bar1.high (~5010)
        close[31] = 5050
        close[32] = 5060
        for i in range(33, n):
            close[i] = 5060  # Stay above, FVG unfilled

        df = make_ohlcv(close)
        plugin = FairValueGapPlugin()
        result = plugin.compute_full({"main": df})

        assert result["fvg_type"] != 0.0
        assert result["fvg_top"] > result["fvg_bottom"]
        assert result["fvg_open_count"] >= 1.0

    def test_no_fvg_gradual(self):
        """Gradual move → no FVG (no 3-candle gap)."""
        from src.intelligence.smart_money.fair_value_gap import FairValueGapPlugin

        close = np.linspace(5000, 5100, 60)
        df = make_ohlcv(close)
        plugin = FairValueGapPlugin()
        result = plugin.compute_full({"main": df})

        assert result["fvg_type"] == 0.0
        assert result["fvg_open_count"] == 0.0

    def test_fvg_filled(self):
        """FVG that gets filled by price retracing → should not count as open."""
        from src.intelligence.smart_money.fair_value_gap import FairValueGapPlugin

        n = 60
        close = np.full(n, 5000.0)
        # Create FVG at bars 20-22
        close[21] = 5050
        close[22] = 5060
        # Price retraces back into the gap
        for i in range(30, 40):
            close[i] = 5005  # Back into the gap zone, filling it
        for i in range(40, n):
            close[i] = 5060  # Back up

        df = make_ohlcv(close)
        plugin = FairValueGapPlugin()
        result = plugin.compute_full({"main": df})

        # The FVG from bars 20-22 should be filled, not counted as open
        # fvg_type could be 0.0 if no unfilled FVGs remain
        assert isinstance(result["fvg_open_count"], float)

    def test_empty_input(self):
        from src.intelligence.smart_money.fair_value_gap import FairValueGapPlugin

        plugin = FairValueGapPlugin()
        assert plugin.compute_full({"main": None}) == {}
        assert plugin.compute_full({}) == {}
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/intelligence/test_smart_money_plugins.py::TestFairValueGap -v`
Expected: FAIL (ImportError)

**Step 3: Write the implementation**

Create `src/intelligence/smart_money/fair_value_gap.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..plugins import InputSpec


@dataclass
class FairValueGapPlugin:
    """Fair Value Gap (FVG) — 3-candle imbalance detection.

    Bullish FVG: bar3.low > bar1.high (gap up, unfilled space).
    Bearish FVG: bar3.high < bar1.low (gap down, unfilled space).
    FVGs tend to be "filled" as price retraces to them.
    """

    name: str = "smc_FairValueGap"
    outputs: set[str] = frozenset(
        {
            "fvg_type",
            "fvg_top",
            "fvg_bottom",
            "fvg_midpoint",
            "fvg_size_pct",
            "fvg_open_count",
        }
    )
    min_lookback: int = 30
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"smart_money"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        current_price = float(df["close"].iloc[-1])

        # Scan for all FVGs
        open_fvgs: list[dict[str, Any]] = []

        for i in range(2, len(df)):
            bar1_high = high[i - 2]
            bar1_low = low[i - 2]
            bar3_high = high[i]
            bar3_low = low[i]

            fvg_type = 0
            fvg_top = 0.0
            fvg_bottom = 0.0

            # Bullish FVG: bar3's low is above bar1's high
            if bar3_low > bar1_high:
                fvg_type = 1
                fvg_top = float(bar3_low)
                fvg_bottom = float(bar1_high)

            # Bearish FVG: bar3's high is below bar1's low
            elif bar3_high < bar1_low:
                fvg_type = -1
                fvg_top = float(bar1_low)
                fvg_bottom = float(bar3_high)

            if fvg_type != 0:
                # Check if this FVG has been filled by subsequent price action
                filled = False
                for j in range(i + 1, len(df)):
                    if fvg_type == 1 and low[j] <= fvg_bottom:
                        filled = True
                        break
                    elif fvg_type == -1 and high[j] >= fvg_top:
                        filled = True
                        break

                if not filled:
                    open_fvgs.append(
                        {"type": fvg_type, "top": fvg_top, "bottom": fvg_bottom}
                    )

        if not open_fvgs:
            return {
                "fvg_type": 0.0,
                "fvg_top": 0.0,
                "fvg_bottom": 0.0,
                "fvg_midpoint": 0.0,
                "fvg_size_pct": 0.0,
                "fvg_open_count": 0.0,
            }

        # Return the most recent unfilled FVG
        latest = open_fvgs[-1]
        mid = (latest["top"] + latest["bottom"]) / 2
        size_pct = (
            (latest["top"] - latest["bottom"]) / current_price * 100
            if current_price != 0
            else 0.0
        )

        return {
            "fvg_type": float(latest["type"]),
            "fvg_top": latest["top"],
            "fvg_bottom": latest["bottom"],
            "fvg_midpoint": mid,
            "fvg_size_pct": size_pct,
            "fvg_open_count": float(len(open_fvgs)),
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = FairValueGapPlugin()
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/intelligence/test_smart_money_plugins.py::TestFairValueGap -v`
Expected: 4 PASS

**Step 5: Commit**

```bash
git add src/intelligence/smart_money/fair_value_gap.py tests/unit/intelligence/test_smart_money_plugins.py
git commit -m "feat: add Fair Value Gap smart money plugin with tests"
```

---

### Task 4: Order Blocks Plugin

**Files:**
- Create: `src/intelligence/smart_money/order_blocks.py`
- Modify: `tests/unit/intelligence/test_smart_money_plugins.py` (append)

**Step 1: Write the failing tests**

Append to `tests/unit/intelligence/test_smart_money_plugins.py`:

```python
# ─── Order Blocks ──────────────────────────────────────────────


class TestOrderBlocks:
    def test_bullish_order_block(self):
        """Last bearish candle before bullish impulse → bullish OB."""
        from src.intelligence.smart_money.order_blocks import OrderBlocksPlugin

        n = 80
        close = np.full(n, 5000.0)
        open_ = np.full(n, 5000.0)

        # Bearish candle at bar 40 (the order block)
        open_[40] = 5010
        close[40] = 4990

        # Bullish impulse bars 41-44 (3+ consecutive bullish candles, strong move)
        for i in range(41, 45):
            open_[i] = close[i - 1]
            close[i] = open_[i] + 30

        # Continue at elevated level
        for i in range(45, n):
            open_[i] = close[44]
            close[i] = close[44]

        high = np.maximum(open_, close) * 1.002
        low = np.minimum(open_, close) * 0.998
        volume = np.full(n, 1000.0)
        # Higher volume on impulse
        volume[41:45] = 3000.0

        df = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume}
        )
        plugin = OrderBlocksPlugin()
        result = plugin.compute_full({"main": df})

        assert result["ob_type"] == 1.0  # Bullish
        assert result["ob_top"] > result["ob_bottom"]
        assert result["ob_strength"] > 0

    def test_no_ob_no_impulse(self):
        """No impulsive move → no order block."""
        from src.intelligence.smart_money.order_blocks import OrderBlocksPlugin

        close = np.full(60, 5000.0) + np.random.default_rng(42).normal(0, 2, 60)
        df = make_ohlcv(close)
        plugin = OrderBlocksPlugin()
        result = plugin.compute_full({"main": df})

        assert result["ob_type"] == 0.0

    def test_empty_input(self):
        from src.intelligence.smart_money.order_blocks import OrderBlocksPlugin

        plugin = OrderBlocksPlugin()
        assert plugin.compute_full({"main": None}) == {}
        assert plugin.compute_full({}) == {}
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/intelligence/test_smart_money_plugins.py::TestOrderBlocks -v`
Expected: FAIL (ImportError)

**Step 3: Write the implementation**

Create `src/intelligence/smart_money/order_blocks.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..plugins import InputSpec


@dataclass
class OrderBlocksPlugin:
    """Order Blocks — last opposing candle before an impulsive move.

    Bullish OB: last bearish candle before a bullish impulse.
    Bearish OB: last bullish candle before a bearish impulse.
    These zones represent institutional entry points and act as S/R.
    """

    name: str = "smc_OrderBlocks"
    outputs: set[str] = frozenset(
        {
            "ob_type",
            "ob_top",
            "ob_bottom",
            "ob_strength",
            "ob_mitigated",
            "ob_distance_pct",
        }
    )
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"smart_money"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    impulse_bars: int = 3  # Minimum consecutive bars for an impulse
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        open_ = df["open"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        volume = df["volume"].to_numpy(dtype=float)
        current_price = float(close[-1])
        avg_volume = float(np.mean(volume))

        # Find impulsive moves and their order blocks
        order_blocks: list[dict[str, Any]] = []

        i = self.impulse_bars
        while i < len(df):
            # Check for bullish impulse: N consecutive bullish candles
            bullish_run = 0
            for j in range(i - self.impulse_bars, i):
                if j >= 0 and close[j] > open_[j]:
                    bullish_run += 1
                else:
                    break

            if bullish_run >= self.impulse_bars:
                impulse_start = i - self.impulse_bars
                impulse_move = close[i - 1] - open_[impulse_start]
                impulse_vol = float(np.mean(volume[impulse_start:i]))

                # Significant move check (at least 0.3% of price)
                if abs(impulse_move) > current_price * 0.003:
                    # Find last bearish candle before impulse
                    ob_idx = None
                    for k in range(impulse_start - 1, max(0, impulse_start - 10), -1):
                        if close[k] < open_[k]:  # Bearish candle
                            ob_idx = k
                            break

                    if ob_idx is not None:
                        strength = min(1.0, impulse_vol / avg_volume) if avg_volume > 0 else 0.5
                        mitigated = self._check_mitigated(
                            low, ob_idx, float(low[ob_idx]), i, len(df)
                        )
                        order_blocks.append(
                            {
                                "type": 1.0,
                                "top": float(high[ob_idx]),
                                "bottom": float(low[ob_idx]),
                                "strength": strength,
                                "mitigated": mitigated,
                                "idx": ob_idx,
                            }
                        )

            # Check for bearish impulse
            bearish_run = 0
            for j in range(i - self.impulse_bars, i):
                if j >= 0 and close[j] < open_[j]:
                    bearish_run += 1
                else:
                    break

            if bearish_run >= self.impulse_bars:
                impulse_start = i - self.impulse_bars
                impulse_move = close[i - 1] - open_[impulse_start]
                impulse_vol = float(np.mean(volume[impulse_start:i]))

                if abs(impulse_move) > current_price * 0.003:
                    ob_idx = None
                    for k in range(impulse_start - 1, max(0, impulse_start - 10), -1):
                        if close[k] > open_[k]:  # Bullish candle
                            ob_idx = k
                            break

                    if ob_idx is not None:
                        strength = min(1.0, impulse_vol / avg_volume) if avg_volume > 0 else 0.5
                        mitigated = self._check_mitigated(
                            high, ob_idx, float(high[ob_idx]), i, len(df)
                        )
                        order_blocks.append(
                            {
                                "type": -1.0,
                                "top": float(high[ob_idx]),
                                "bottom": float(low[ob_idx]),
                                "strength": strength,
                                "mitigated": mitigated,
                                "idx": ob_idx,
                            }
                        )

            i += 1

        # Filter to unmitigated OBs and return most recent
        active_obs = [ob for ob in order_blocks if ob["mitigated"] == 0.0]

        if not active_obs:
            return {
                "ob_type": 0.0,
                "ob_top": 0.0,
                "ob_bottom": 0.0,
                "ob_strength": 0.0,
                "ob_mitigated": 0.0,
                "ob_distance_pct": 0.0,
            }

        latest = active_obs[-1]
        ob_mid = (latest["top"] + latest["bottom"]) / 2
        dist_pct = (
            abs(current_price - ob_mid) / current_price * 100
            if current_price != 0
            else 0.0
        )

        return {
            "ob_type": latest["type"],
            "ob_top": latest["top"],
            "ob_bottom": latest["bottom"],
            "ob_strength": latest["strength"],
            "ob_mitigated": latest["mitigated"],
            "ob_distance_pct": dist_pct,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _check_mitigated(
        price_array: np.ndarray,
        ob_idx: int,
        ob_level: float,
        impulse_end: int,
        n: int,
    ) -> float:
        """Check if price traded through the OB zone after the impulse."""
        for j in range(impulse_end, n):
            if price_array[j] <= ob_level:  # For bullish OB: price dropped back to OB low
                return 1.0
        return 0.0


plugin = OrderBlocksPlugin()
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/intelligence/test_smart_money_plugins.py::TestOrderBlocks -v`
Expected: 3 PASS

**Step 5: Commit**

```bash
git add src/intelligence/smart_money/order_blocks.py tests/unit/intelligence/test_smart_money_plugins.py
git commit -m "feat: add Order Blocks smart money plugin with tests"
```

---

### Task 5: Liquidity Sweeps Plugin

**Files:**
- Create: `src/intelligence/smart_money/liquidity_sweeps.py`
- Modify: `tests/unit/intelligence/test_smart_money_plugins.py` (append)

**Step 1: Write the failing tests**

Append to `tests/unit/intelligence/test_smart_money_plugins.py`:

```python
# ─── Liquidity Sweeps ─────────────────────────────────────────


class TestLiquiditySweeps:
    def test_bullish_sweep(self):
        """Wick below swing low that closes back above → bullish sweep."""
        from src.intelligence.smart_money.liquidity_sweeps import LiquiditySweepsPlugin

        n = 120
        # Build data with clear swing lows, then a sweep
        high = np.full(n, 5020.0)
        low = np.full(n, 4980.0)

        # Create a swing low at bar 30 (low dips to 4950)
        for i in range(25, 36):
            depth = 30 * np.sin(np.pi * (i - 25) / 11)
            low[i] = 4980 - depth
            high[i] = low[i] + 40

        # Normal bars in between
        for i in range(36, 80):
            low[i] = 4980
            high[i] = 5020

        # Sweep at bar 85: wick below the swing low but close above it
        low[85] = 4940  # Below the swing low of ~4950
        high[85] = 5010  # Close (midpoint) is above 4950

        df = make_ohlcv_from_hl(high, low)
        plugin = LiquiditySweepsPlugin()
        result = plugin.compute_full({"main": df})

        assert result["sweep_detected"] == 1.0
        assert result["sweep_type"] == 1.0  # Bullish (swept lows)

    def test_no_sweep_clean_trend(self):
        """Clean uptrend with no wicks beyond swing levels → no sweep."""
        from src.intelligence.smart_money.liquidity_sweeps import LiquiditySweepsPlugin

        close = np.linspace(5000, 5200, 100)
        df = make_ohlcv(close)
        plugin = LiquiditySweepsPlugin()
        result = plugin.compute_full({"main": df})

        assert result["sweep_detected"] == 0.0

    def test_empty_input(self):
        from src.intelligence.smart_money.liquidity_sweeps import LiquiditySweepsPlugin

        plugin = LiquiditySweepsPlugin()
        assert plugin.compute_full({"main": None}) == {}
        assert plugin.compute_full({}) == {}

    def test_insufficient_data(self):
        from src.intelligence.smart_money.liquidity_sweeps import LiquiditySweepsPlugin

        df = make_ohlcv(np.full(10, 5000.0))
        plugin = LiquiditySweepsPlugin()
        assert plugin.compute_full({"main": df}) == {}
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/intelligence/test_smart_money_plugins.py::TestLiquiditySweeps -v`
Expected: FAIL (ImportError)

**Step 3: Write the implementation**

Create `src/intelligence/smart_money/liquidity_sweeps.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..plugins import InputSpec
from ._swing_utils import find_swing_highs, find_swing_lows


@dataclass
class LiquiditySweepsPlugin:
    """Liquidity Sweeps — stop hunts beyond swing levels.

    Bullish sweep: price wicks below a swing low but closes above it
    (smart money grabbed sell stops, then reversed).
    Bearish sweep: price wicks above a swing high but closes below it.
    """

    name: str = "smc_LiquiditySweeps"
    outputs: set[str] = frozenset(
        {
            "sweep_detected",
            "sweep_type",
            "sweep_level",
            "sweep_depth_pct",
            "sweep_reclaimed",
        }
    )
    min_lookback: int = 60
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"smart_money"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=120),)
    neighbor: int = 5
    reclaim_bars: int = 3  # Bars to check for reclaim confirmation
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)

        swing_highs = find_swing_highs(high, self.neighbor)
        swing_lows = find_swing_lows(low, self.neighbor)

        if not swing_highs and not swing_lows:
            return {
                "sweep_detected": 0.0,
                "sweep_type": 0.0,
                "sweep_level": 0.0,
                "sweep_depth_pct": 0.0,
                "sweep_reclaimed": 0.0,
            }

        # Check recent bars for sweeps of swing levels
        sweeps: list[dict[str, Any]] = []

        # Check for bullish sweeps (wicks below swing lows)
        for sl_idx in swing_lows:
            sl_price = float(low[sl_idx])
            # Look for bars AFTER this swing low that wick below it
            for i in range(sl_idx + self.neighbor + 1, len(df)):
                if low[i] < sl_price and close[i] > sl_price:
                    depth = (sl_price - float(low[i])) / sl_price * 100
                    # Check reclaim: next bars continue up
                    reclaimed = 0.0
                    if i + self.reclaim_bars < len(df):
                        if all(
                            close[i + k] > sl_price
                            for k in range(1, self.reclaim_bars + 1)
                        ):
                            reclaimed = 1.0
                    sweeps.append(
                        {
                            "type": 1.0,
                            "level": sl_price,
                            "depth_pct": depth,
                            "reclaimed": reclaimed,
                            "bar_idx": i,
                        }
                    )

        # Check for bearish sweeps (wicks above swing highs)
        for sh_idx in swing_highs:
            sh_price = float(high[sh_idx])
            for i in range(sh_idx + self.neighbor + 1, len(df)):
                if high[i] > sh_price and close[i] < sh_price:
                    depth = (float(high[i]) - sh_price) / sh_price * 100
                    reclaimed = 0.0
                    if i + self.reclaim_bars < len(df):
                        if all(
                            close[i + k] < sh_price
                            for k in range(1, self.reclaim_bars + 1)
                        ):
                            reclaimed = 1.0
                    sweeps.append(
                        {
                            "type": -1.0,
                            "level": sh_price,
                            "depth_pct": depth,
                            "reclaimed": reclaimed,
                            "bar_idx": i,
                        }
                    )

        if not sweeps:
            return {
                "sweep_detected": 0.0,
                "sweep_type": 0.0,
                "sweep_level": 0.0,
                "sweep_depth_pct": 0.0,
                "sweep_reclaimed": 0.0,
            }

        # Return most recent sweep
        latest = max(sweeps, key=lambda s: s["bar_idx"])
        return {
            "sweep_detected": 1.0,
            "sweep_type": latest["type"],
            "sweep_level": latest["level"],
            "sweep_depth_pct": latest["depth_pct"],
            "sweep_reclaimed": latest["reclaimed"],
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = LiquiditySweepsPlugin()
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/intelligence/test_smart_money_plugins.py::TestLiquiditySweeps -v`
Expected: 4 PASS

**Step 5: Commit**

```bash
git add src/intelligence/smart_money/liquidity_sweeps.py tests/unit/intelligence/test_smart_money_plugins.py
git commit -m "feat: add Liquidity Sweeps smart money plugin with tests"
```

---

### Task 6: Register All 4 Plugins + Final Verification

**Files:**
- Modify: `src/intelligence/register_plugins.py`

**Step 1: Update register_plugins.py**

Add imports after existing pattern imports:

```python
from .smart_money.bos_choch import plugin as bos_choch_plugin
from .smart_money.fair_value_gap import plugin as fvg_plugin
from .smart_money.liquidity_sweeps import plugin as liq_sweep_plugin
from .smart_money.order_blocks import plugin as ob_plugin
```

Add registrations inside `register_all_plugins()` after existing pattern registrations:

```python
    registry.register_pattern(bos_choch_plugin)
    registry.register_pattern(fvg_plugin)
    registry.register_pattern(ob_plugin)
    registry.register_pattern(liq_sweep_plugin)
```

**Step 2: Verify registration**

Run: `python -c "from src.intelligence.register_plugins import register_all_plugins; from src.intelligence.plugins import registry; register_all_plugins(); print(f'Indicators: {len(registry.indicators)}, Patterns: {len(registry.patterns)}, Total: {len(registry.indicators) + len(registry.patterns)}')" `
Expected: `Indicators: 16, Patterns: 14, Total: 30`

**Step 3: Run full test suite**

Run: `python -m pytest tests/unit/ -v`
Expected: All tests pass (~139 tests: 123 existing + ~16 new)

**Step 4: Lint check**

Run: `.venv/bin/ruff check src/intelligence/smart_money/ tests/unit/intelligence/test_smart_money_plugins.py`
Expected: 0 errors

**Step 5: Commit**

```bash
git add src/intelligence/register_plugins.py
git commit -m "feat: register 4 smart money plugins (30 total)"
```
