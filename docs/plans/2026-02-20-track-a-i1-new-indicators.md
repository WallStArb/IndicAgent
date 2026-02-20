# Track A: New I1 Indicators Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 6 new I1 technical indicator plugins (CMF, Aroon, Historical Volatility, Chandelier Exit, Parabolic SAR, Stochastic RSI) that expand the signal surface for I5 patterns and I7 trading setups.

**Architecture:** Each plugin is a self-contained dataclass in `src/intelligence/indicators/`, following the existing pattern: `compute_full()` for full history replay (seeds incremental state), `compute_next()` for O(1) bar-by-bar updates. All are registered in `register_plugins.py` and auto-appear in `intelligence:SYMBOL:TF` Redis streams.

**Tech Stack:** Python 3.11, numpy, pandas, `collections.deque` for rolling windows. No new dependencies. Test with `.venv/bin/python3 -m pytest`.

---

## Shared Setup

Before Task 1, verify the worktree is on the correct branch:

```bash
git checkout -b feature/i1-new-indicators
```

All test files go in: `tests/unit/intelligence/`
All plugin files go in: `src/intelligence/indicators/`

Shared `_make_ohlcv` helper (copy into each test file — do not DRY across test files):

```python
import numpy as np
import pandas as pd

def _make_ohlcv(n: int = 100, seed: int = 42, trend: str = "flat") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    if trend == "up":
        close = 5000.0 + np.arange(n) * 1.5 + rng.standard_normal(n) * 0.3
    elif trend == "down":
        close = 5200.0 - np.arange(n) * 1.5 + rng.standard_normal(n) * 0.3
    else:
        returns = rng.normal(0.0001, 0.005, n)
        close = 5000.0 * np.cumprod(1 + returns)
    spread = rng.uniform(0.001, 0.003, n)
    high = close * (1 + spread)
    low = close * (1 - spread)
    high = np.maximum(high, close)
    low = np.minimum(low, close)
    return pd.DataFrame({
        "open": close * (1 + rng.normal(0, 0.001, n)),
        "high": high,
        "low": low,
        "close": close,
        "volume": rng.lognormal(10, 0.5, n).astype(float),
    })
```

---

## Task 1: Chaikin Money Flow (`ind_CMF`)

Money flow volume over a rolling window. Simplest of the 6 — pure deque rolling sum, no state machine.

**Files:**
- Create: `src/intelligence/indicators/cmf.py`
- Create: `tests/unit/intelligence/test_cmf.py`

---

### Step 1: Write the failing tests

Create `tests/unit/intelligence/test_cmf.py`:

```python
"""Tests for Chaikin Money Flow indicator plugin."""

import numpy as np
import pandas as pd
import pytest

from src.intelligence.indicators.cmf import CMFPlugin


def _make_ohlcv(n: int = 100, seed: int = 42, trend: str = "flat") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    if trend == "up":
        close = 5000.0 + np.arange(n) * 1.5 + rng.standard_normal(n) * 0.3
    elif trend == "down":
        close = 5200.0 - np.arange(n) * 1.5 + rng.standard_normal(n) * 0.3
    else:
        returns = rng.normal(0.0001, 0.005, n)
        close = 5000.0 * np.cumprod(1 + returns)
    spread = rng.uniform(0.001, 0.003, n)
    high = close * (1 + spread)
    low = close * (1 - spread)
    high = np.maximum(high, close)
    low = np.minimum(low, close)
    return pd.DataFrame({
        "open": close * (1 + rng.normal(0, 0.001, n)),
        "high": high,
        "low": low,
        "close": close,
        "volume": rng.lognormal(10, 0.5, n).astype(float),
    })


class TestCMF:
    def test_output_key_present(self):
        plugin = CMFPlugin()
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert "cmf_20" in result

    def test_value_in_range(self):
        plugin = CMFPlugin()
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert -1.0 <= result["cmf_20"] <= 1.0

    def test_insufficient_data_returns_empty(self):
        plugin = CMFPlugin()
        result = plugin.compute_full({"main": _make_ohlcv(n=5)})
        assert result == {}

    def test_buying_pressure_positive(self):
        """Close near high of every bar → CMF strongly positive."""
        rng = np.random.default_rng(0)
        n = 60
        high = 5001.0 + rng.uniform(0, 1, n)
        low = 4999.0 + rng.uniform(0, 0.1, n)
        close = high - rng.uniform(0.01, 0.05, n)  # close near high
        df = pd.DataFrame({
            "open": close, "high": high, "low": low,
            "close": close, "volume": np.ones(n) * 1000,
        })
        result = CMFPlugin().compute_full({"main": df})
        assert result["cmf_20"] > 0.5

    def test_selling_pressure_negative(self):
        """Close near low of every bar → CMF strongly negative."""
        rng = np.random.default_rng(0)
        n = 60
        high = 5001.0 + rng.uniform(0, 1, n)
        low = 4999.0 + rng.uniform(0, 0.1, n)
        close = low + rng.uniform(0.01, 0.05, n)  # close near low
        df = pd.DataFrame({
            "open": close, "high": high, "low": low,
            "close": close, "volume": np.ones(n) * 1000,
        })
        result = CMFPlugin().compute_full({"main": df})
        assert result["cmf_20"] < -0.5

    def test_zero_range_bars_handled(self):
        """Bars where high == low should not raise (MFM = 0)."""
        df = _make_ohlcv(50)
        df["high"] = df["close"]
        df["low"] = df["close"]
        result = CMFPlugin().compute_full({"main": df})
        assert result["cmf_20"] == 0.0

    def test_incremental_matches_full(self):
        """compute_next fed bar-by-bar should match a fresh compute_full."""
        df = _make_ohlcv(200)

        plugin = CMFPlugin()
        plugin.compute_full({"main": df.iloc[:100].copy()})
        result = None
        for i in range(100, 200):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = CMFPlugin()
        full = fresh.compute_full({"main": df.copy()})

        assert abs(result["cmf_20"] - full["cmf_20"]) < 1e-6
```

### Step 2: Run tests — expect ImportError

```bash
.venv/bin/python3 -m pytest tests/unit/intelligence/test_cmf.py -v
```

Expected: `ImportError: cannot import name 'CMFPlugin'`

### Step 3: Implement `src/intelligence/indicators/cmf.py`

```python
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class CMFPlugin:
    """Chaikin Money Flow — windowed accumulation/distribution pressure.

    CMF = sum(MFV, period) / sum(volume, period)
    MFV = volume * (2*close - high - low) / (high - low)

    Unlike OBV (cumulative), CMF resets every N bars — better for detecting
    short-term institutional buying/selling pressure.
    """

    name: str = "ind_CMF"
    outputs: set[str] = frozenset({"cmf_20"})
    min_lookback: int = 20
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"volume"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=60),)
    period: int = 20
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.period:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        volume = df["volume"].to_numpy(dtype=float)

        hl_range = high - low
        mfm = np.where(hl_range > 0, (2 * close - high - low) / hl_range, 0.0)
        mfv = mfm * volume

        mfv_win = mfv[-self.period:]
        vol_win = volume[-self.period:]

        vol_sum = float(np.sum(vol_win))
        cmf = float(np.sum(mfv_win)) / vol_sum if vol_sum > 0 else 0.0

        self._state = {
            "mfv_window": deque(mfv_win.tolist(), maxlen=self.period),
            "vol_window": deque(vol_win.tolist(), maxlen=self.period),
        }
        return {"cmf_20": round(cmf, 6)}

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}

        row = df.iloc[-1]
        h, l, c, v = float(row["high"]), float(row["low"]), float(row["close"]), float(row["volume"])
        s = self._state

        hl = h - l
        mfm = (2 * c - h - l) / hl if hl > 0 else 0.0
        s["mfv_window"].append(mfm * v)
        s["vol_window"].append(v)

        vol_sum = sum(s["vol_window"])
        cmf = sum(s["mfv_window"]) / vol_sum if vol_sum > 0 else 0.0
        return {"cmf_20": round(cmf, 6)}


plugin = CMFPlugin()
```

### Step 4: Run tests — expect all green

```bash
.venv/bin/python3 -m pytest tests/unit/intelligence/test_cmf.py -v
```

Expected: 7 tests PASSED

### Step 5: Commit

```bash
git add src/intelligence/indicators/cmf.py tests/unit/intelligence/test_cmf.py
git commit -m "feat: add ind_CMF (Chaikin Money Flow) plugin with incremental support"
```

---

## Task 2: Aroon (`ind_Aroon`)

Measures bars-since-period-high/low. Unique trend-age signal — no other current indicator captures recency of extremes.

**Files:**
- Create: `src/intelligence/indicators/aroon.py`
- Create: `tests/unit/intelligence/test_aroon.py`

---

### Step 1: Write the failing tests

Create `tests/unit/intelligence/test_aroon.py`:

```python
"""Tests for Aroon indicator plugin."""

import numpy as np
import pandas as pd

from src.intelligence.indicators.aroon import AroonPlugin


def _make_ohlcv(n: int = 100, seed: int = 42, trend: str = "flat") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    if trend == "up":
        close = 5000.0 + np.arange(n) * 1.5 + rng.standard_normal(n) * 0.3
    elif trend == "down":
        close = 5200.0 - np.arange(n) * 1.5 + rng.standard_normal(n) * 0.3
    else:
        returns = rng.normal(0.0001, 0.005, n)
        close = 5000.0 * np.cumprod(1 + returns)
    spread = rng.uniform(0.001, 0.003, n)
    high = close * (1 + spread)
    low = close * (1 - spread)
    high = np.maximum(high, close)
    low = np.minimum(low, close)
    return pd.DataFrame({
        "open": close, "high": high, "low": low,
        "close": close,
        "volume": rng.lognormal(10, 0.5, n).astype(float),
    })


class TestAroon:
    def test_all_output_keys_present(self):
        plugin = AroonPlugin()
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert "aroon_up_25" in result
        assert "aroon_down_25" in result
        assert "aroon_osc_25" in result

    def test_values_in_range(self):
        result = AroonPlugin().compute_full({"main": _make_ohlcv()})
        assert 0.0 <= result["aroon_up_25"] <= 100.0
        assert 0.0 <= result["aroon_down_25"] <= 100.0
        assert -100.0 <= result["aroon_osc_25"] <= 100.0

    def test_oscillator_equals_up_minus_down(self):
        result = AroonPlugin().compute_full({"main": _make_ohlcv()})
        assert abs(result["aroon_osc_25"] - (result["aroon_up_25"] - result["aroon_down_25"])) < 1e-6

    def test_high_at_current_bar_gives_100(self):
        """aroon_up should be 100 when highest high is the current bar."""
        df = _make_ohlcv(60)
        df = df.copy()
        df.loc[df.index[-1], "high"] = df["high"].max() * 2.0
        result = AroonPlugin().compute_full({"main": df})
        assert result["aroon_up_25"] == 100.0

    def test_low_at_current_bar_gives_100_down(self):
        """aroon_down should be 100 when lowest low is the current bar."""
        df = _make_ohlcv(60)
        df = df.copy()
        df.loc[df.index[-1], "low"] = df["low"].min() * 0.5
        result = AroonPlugin().compute_full({"main": df})
        assert result["aroon_down_25"] == 100.0

    def test_uptrend_aroon_up_dominates(self):
        """Clear uptrend: aroon_up should exceed aroon_down."""
        result = AroonPlugin().compute_full({"main": _make_ohlcv(150, trend="up")})
        assert result["aroon_osc_25"] > 0

    def test_downtrend_aroon_down_dominates(self):
        """Clear downtrend: aroon_down should exceed aroon_up."""
        result = AroonPlugin().compute_full({"main": _make_ohlcv(150, trend="down")})
        assert result["aroon_osc_25"] < 0

    def test_insufficient_data_returns_empty(self):
        result = AroonPlugin().compute_full({"main": _make_ohlcv(5)})
        assert result == {}

    def test_incremental_matches_full(self):
        df = _make_ohlcv(200)

        plugin = AroonPlugin()
        plugin.compute_full({"main": df.iloc[:100].copy()})
        result = None
        for i in range(100, 200):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = AroonPlugin()
        full = fresh.compute_full({"main": df.copy()})

        assert result["aroon_up_25"] == full["aroon_up_25"]
        assert result["aroon_down_25"] == full["aroon_down_25"]
```

### Step 2: Run tests — expect ImportError

```bash
.venv/bin/python3 -m pytest tests/unit/intelligence/test_aroon.py -v
```

### Step 3: Implement `src/intelligence/indicators/aroon.py`

Key formula: `aroon_up = argmax(high_window) / period * 100` where the window is `(period+1)` bars (index 0 = oldest, index period = current). argmax gives the index of the highest high; dividing by period gives how recently it occurred.

```python
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class AroonPlugin:
    """Aroon indicator — measures bars since the period high/low.

    aroon_up  = argmax(highs over period+1 bars) / period * 100
    aroon_down = argmin(lows over period+1 bars) / period * 100
    aroon_osc  = aroon_up - aroon_down  (range: -100 to +100)

    Value of 100 means the high/low was the current bar.
    Value of 0 means the high/low was exactly period bars ago.
    """

    name: str = "ind_Aroon"
    outputs: set[str] = frozenset({"aroon_up_25", "aroon_down_25", "aroon_osc_25"})
    min_lookback: int = 27
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"trend"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    period: int = 25
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.period + 1:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)

        # Window of (period+1) bars: oldest at index 0, current at index period
        h_win = high[-(self.period + 1):]
        l_win = low[-(self.period + 1):]

        aroon_up = float(np.argmax(h_win)) / self.period * 100.0
        aroon_down = float(np.argmin(l_win)) / self.period * 100.0

        self._state = {
            "high_window": deque(h_win.tolist(), maxlen=self.period + 1),
            "low_window": deque(l_win.tolist(), maxlen=self.period + 1),
        }

        return {
            "aroon_up_25": round(aroon_up, 2),
            "aroon_down_25": round(aroon_down, 2),
            "aroon_osc_25": round(aroon_up - aroon_down, 2),
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}

        row = df.iloc[-1]
        s = self._state
        s["high_window"].append(float(row["high"]))
        s["low_window"].append(float(row["low"]))

        if len(s["high_window"]) < self.period + 1:
            return {}

        hw = list(s["high_window"])
        lw = list(s["low_window"])

        aroon_up = float(np.argmax(hw)) / self.period * 100.0
        aroon_down = float(np.argmin(lw)) / self.period * 100.0

        return {
            "aroon_up_25": round(aroon_up, 2),
            "aroon_down_25": round(aroon_down, 2),
            "aroon_osc_25": round(aroon_up - aroon_down, 2),
        }


plugin = AroonPlugin()
```

### Step 4: Run tests — expect all green

```bash
.venv/bin/python3 -m pytest tests/unit/intelligence/test_aroon.py -v
```

Expected: 9 tests PASSED

### Step 5: Commit

```bash
git add src/intelligence/indicators/aroon.py tests/unit/intelligence/test_aroon.py
git commit -m "feat: add ind_Aroon plugin (trend age indicator) with incremental support"
```

---

## Task 3: Historical Volatility (`ind_HistoricalVolatility`)

Realized annualized volatility from log returns. Critical for VIX futures traders comparing realized to implied vol.

**Files:**
- Create: `src/intelligence/indicators/historical_volatility.py`
- Create: `tests/unit/intelligence/test_historical_volatility.py`

---

### Step 1: Write the failing tests

Create `tests/unit/intelligence/test_historical_volatility.py`:

```python
"""Tests for Historical Volatility indicator plugin."""

import numpy as np
import pandas as pd

from src.intelligence.indicators.historical_volatility import HistoricalVolatilityPlugin


def _make_ohlcv(n: int = 100, seed: int = 42, vol: float = 0.005) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0001, vol, n)
    close = 5000.0 * np.cumprod(1 + returns)
    spread = rng.uniform(0.001, 0.002, n)
    high = close * (1 + spread)
    low = close * (1 - spread)
    return pd.DataFrame({
        "open": close, "high": high, "low": low,
        "close": close,
        "volume": rng.lognormal(10, 0.5, n).astype(float),
    })


class TestHistoricalVolatility:
    def test_output_keys_present(self):
        result = HistoricalVolatilityPlugin().compute_full({"main": _make_ohlcv()})
        assert "hv_20" in result
        assert "hv_ratio_20" in result

    def test_hv_positive(self):
        result = HistoricalVolatilityPlugin().compute_full({"main": _make_ohlcv()})
        assert result["hv_20"] > 0.0

    def test_hv_annualized_scale(self):
        """For 0.5% per-bar vol, annualized HV should be in reasonable range (> 5% annual)."""
        result = HistoricalVolatilityPlugin().compute_full({"main": _make_ohlcv(vol=0.005)})
        assert result["hv_20"] > 0.05  # at least 5% annualized

    def test_insufficient_data_returns_empty(self):
        result = HistoricalVolatilityPlugin().compute_full({"main": _make_ohlcv(n=10)})
        assert result == {}

    def test_higher_vol_gives_higher_hv(self):
        low_result = HistoricalVolatilityPlugin().compute_full({"main": _make_ohlcv(vol=0.001)})
        high_result = HistoricalVolatilityPlugin().compute_full({"main": _make_ohlcv(vol=0.02)})
        assert high_result["hv_20"] > low_result["hv_20"]

    def test_ratio_near_one_for_stable_vol(self):
        """With constant volatility throughout, ratio should be close to 1.0."""
        result = HistoricalVolatilityPlugin().compute_full({"main": _make_ohlcv(n=200, vol=0.005)})
        assert 0.5 < result["hv_ratio_20"] < 2.0

    def test_ratio_elevated_after_vol_spike(self):
        """Vol spike at end of series → ratio > 1.0."""
        rng = np.random.default_rng(0)
        low_ret = rng.normal(0, 0.001, 60)
        high_ret = rng.normal(0, 0.02, 20)   # 20x vol spike
        returns = np.concatenate([low_ret, high_ret])
        close = 5000.0 * np.cumprod(1 + returns)
        df = pd.DataFrame({
            "open": close, "high": close * 1.001, "low": close * 0.999,
            "close": close, "volume": np.ones(len(returns)) * 1000,
        })
        result = HistoricalVolatilityPlugin().compute_full({"main": df})
        assert result["hv_ratio_20"] > 1.5

    def test_incremental_matches_full(self):
        df = _make_ohlcv(200)

        plugin = HistoricalVolatilityPlugin()
        plugin.compute_full({"main": df.iloc[:100].copy()})
        result = None
        for i in range(100, 200):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = HistoricalVolatilityPlugin()
        full = fresh.compute_full({"main": df.copy()})

        assert abs(result["hv_20"] - full["hv_20"]) / full["hv_20"] < 0.005  # 0.5% tolerance
        assert abs(result["hv_ratio_20"] - full["hv_ratio_20"]) < 0.05
```

### Step 2: Run tests — expect ImportError

```bash
.venv/bin/python3 -m pytest tests/unit/intelligence/test_historical_volatility.py -v
```

### Step 3: Implement `src/intelligence/indicators/historical_volatility.py`

Annualization: 390 1-minute bars/day × 252 trading days/year. `hv_ratio_20` is the ratio of current HV to the rolling mean of the last `period` HV values — a vol-of-vol signal.

```python
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec

# 390 1m bars/day × 252 trading days/year
_ANNUALIZATION = math.sqrt(390 * 252)


@dataclass
class HistoricalVolatilityPlugin:
    """Realized (historical) volatility: annualized std of log returns.

    hv_20      = std(log_returns, 20 bars) * sqrt(390 * 252)
    hv_ratio_20 = hv_20 / rolling_mean(hv_20, 20 bars)
                  > 1.0 → vol elevated vs recent baseline
                  < 1.0 → vol compressed vs recent baseline
    """

    name: str = "ind_HistoricalVolatility"
    outputs: set[str] = frozenset({"hv_20", "hv_ratio_20"})
    min_lookback: int = 22
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"volatility"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    period: int = 20
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.period + 1:
            return {}

        close = df["close"].to_numpy(dtype=float)
        log_returns = np.log(close[1:] / close[:-1])

        if len(log_returns) < self.period:
            return {}

        # Rolling HV values
        hv_values = [
            float(np.std(log_returns[i - self.period + 1: i + 1], ddof=1) * _ANNUALIZATION)
            for i in range(self.period - 1, len(log_returns))
        ]

        hv_20 = hv_values[-1]
        recent = hv_values[-self.period:]
        hv_mean = float(np.mean(recent))
        hv_ratio = hv_20 / hv_mean if hv_mean > 1e-10 else 1.0

        self._state = {
            "prev_close": float(close[-1]),
            "log_return_window": deque(log_returns[-self.period:].tolist(), maxlen=self.period),
            "hv_window": deque(hv_values[-self.period:], maxlen=self.period),
        }

        return {"hv_20": round(hv_20, 6), "hv_ratio_20": round(hv_ratio, 4)}

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}

        curr = float(df["close"].iloc[-1])
        s = self._state

        s["log_return_window"].append(math.log(curr / s["prev_close"]))
        s["prev_close"] = curr

        if len(s["log_return_window"]) < self.period:
            return {}

        hv_20 = float(np.std(list(s["log_return_window"]), ddof=1) * _ANNUALIZATION)
        s["hv_window"].append(hv_20)

        hv_mean = float(np.mean(list(s["hv_window"])))
        hv_ratio = hv_20 / hv_mean if hv_mean > 1e-10 else 1.0

        return {"hv_20": round(hv_20, 6), "hv_ratio_20": round(hv_ratio, 4)}


plugin = HistoricalVolatilityPlugin()
```

### Step 4: Run tests — expect all green

```bash
.venv/bin/python3 -m pytest tests/unit/intelligence/test_historical_volatility.py -v
```

Expected: 8 tests PASSED

### Step 5: Commit

```bash
git add src/intelligence/indicators/historical_volatility.py tests/unit/intelligence/test_historical_volatility.py
git commit -m "feat: add ind_HistoricalVolatility plugin (realized vol + ratio) with incremental support"
```

---

## Task 4: Chandelier Exit (`ind_ChandelierExit`)

ATR-based adaptive trailing stops. Long stop = highest_high(22) − 3×ATR(22). Provides calibrated stop levels that I7 setups can reference directly.

**Files:**
- Create: `src/intelligence/indicators/chandelier.py`
- Create: `tests/unit/intelligence/test_chandelier.py`

---

### Step 1: Write the failing tests

Create `tests/unit/intelligence/test_chandelier.py`:

```python
"""Tests for Chandelier Exit indicator plugin."""

import numpy as np
import pandas as pd

from src.intelligence.indicators.chandelier import ChandelierPlugin


def _make_ohlcv(n: int = 100, seed: int = 42, trend: str = "flat") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    if trend == "up":
        close = 5000.0 + np.arange(n) * 1.5 + rng.standard_normal(n) * 0.3
    elif trend == "down":
        close = 5200.0 - np.arange(n) * 1.5 + rng.standard_normal(n) * 0.3
    else:
        returns = rng.normal(0.0001, 0.005, n)
        close = 5000.0 * np.cumprod(1 + returns)
    spread = rng.uniform(0.001, 0.003, n)
    high = close * (1 + spread)
    low = close * (1 - spread)
    high = np.maximum(high, close)
    low = np.minimum(low, close)
    return pd.DataFrame({
        "open": close, "high": high, "low": low,
        "close": close,
        "volume": rng.lognormal(10, 0.5, n).astype(float),
    })


class TestChandelier:
    def test_output_keys_present(self):
        result = ChandelierPlugin().compute_full({"main": _make_ohlcv()})
        assert "chandelier_long_22" in result
        assert "chandelier_short_22" in result

    def test_long_stop_below_highest_high(self):
        """Long stop must always be below the highest high in the window."""
        df = _make_ohlcv(100)
        result = ChandelierPlugin().compute_full({"main": df})
        highest = df["high"].iloc[-22:].max()
        assert result["chandelier_long_22"] < highest

    def test_short_stop_above_lowest_low(self):
        """Short stop must always be above the lowest low in the window."""
        df = _make_ohlcv(100)
        result = ChandelierPlugin().compute_full({"main": df})
        lowest = df["low"].iloc[-22:].min()
        assert result["chandelier_short_22"] > lowest

    def test_short_stop_above_long_stop(self):
        """Short stop (ceiling) should be above long stop (floor)."""
        result = ChandelierPlugin().compute_full({"main": _make_ohlcv()})
        assert result["chandelier_short_22"] > result["chandelier_long_22"]

    def test_positive_values(self):
        result = ChandelierPlugin().compute_full({"main": _make_ohlcv()})
        assert result["chandelier_long_22"] > 0
        assert result["chandelier_short_22"] > 0

    def test_insufficient_data_returns_empty(self):
        result = ChandelierPlugin().compute_full({"main": _make_ohlcv(n=10)})
        assert result == {}

    def test_custom_period_and_multiplier(self):
        plugin = ChandelierPlugin(period=14, multiplier=2.0)
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert "chandelier_long_22" in result  # name stays 22 by convention

    def test_incremental_matches_full(self):
        df = _make_ohlcv(200)

        plugin = ChandelierPlugin()
        plugin.compute_full({"main": df.iloc[:100].copy()})
        result = None
        for i in range(100, 200):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = ChandelierPlugin()
        full = fresh.compute_full({"main": df.copy()})

        for key in ("chandelier_long_22", "chandelier_short_22"):
            rel_diff = abs(result[key] - full[key]) / abs(full[key])
            assert rel_diff < 0.005, f"{key}: {rel_diff:.4%} drift"
```

### Step 2: Run tests — expect ImportError

```bash
.venv/bin/python3 -m pytest tests/unit/intelligence/test_chandelier.py -v
```

### Step 3: Implement `src/intelligence/indicators/chandelier.py`

Note: the plugin outputs use "22" in the key name regardless of the `period` param (convention matching the design doc). ATR is computed with Wilder's smoothing inline — do not read from upstream `atr_14` since Chandelier uses period 22.

```python
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class ChandelierPlugin:
    """Chandelier Exit — ATR-based adaptive trailing stop levels.

    Long stop  = highest_high(period) - multiplier * ATR(period)
    Short stop = lowest_low(period)   + multiplier * ATR(period)

    Provides adaptive stop/target levels calibrated to recent volatility.
    Uses period=22, multiplier=3.0 by default (Wilder's recommendation).
    """

    name: str = "ind_ChandelierExit"
    outputs: set[str] = frozenset({"chandelier_long_22", "chandelier_short_22"})
    min_lookback: int = 25
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"volatility"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    period: int = 22
    multiplier: float = 3.0
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.period + 1:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)

        atr = self._compute_atr(high, low, close, self.period)
        highest_high = float(np.max(high[-self.period:]))
        lowest_low = float(np.min(low[-self.period:]))

        self._state = {
            "atr": atr,
            "prev_close": float(close[-1]),
            "high_window": deque(high[-self.period:].tolist(), maxlen=self.period),
            "low_window": deque(low[-self.period:].tolist(), maxlen=self.period),
        }

        return {
            "chandelier_long_22": round(highest_high - self.multiplier * atr, 6),
            "chandelier_short_22": round(lowest_low + self.multiplier * atr, 6),
        }

    def _compute_atr(self, high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> float:
        """Wilder's ATR: SMA seed then Wilder smoothing (alpha = 1/period)."""
        n = len(high)
        tr = np.empty(n)
        tr[0] = high[0] - low[0]
        for i in range(1, n):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
        atr = float(np.mean(tr[1: period + 1]))
        alpha = 1.0 / period
        for i in range(period + 1, n):
            atr = (1 - alpha) * atr + alpha * float(tr[i])
        return atr

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}

        row = df.iloc[-1]
        h = float(row["high"])
        l = float(row["low"])
        c = float(row["close"])
        s = self._state

        tr = max(h - l, abs(h - s["prev_close"]), abs(l - s["prev_close"]))
        alpha = 1.0 / self.period
        s["atr"] = (1 - alpha) * s["atr"] + alpha * tr
        s["prev_close"] = c
        s["high_window"].append(h)
        s["low_window"].append(l)

        highest_high = max(s["high_window"])
        lowest_low = min(s["low_window"])

        return {
            "chandelier_long_22": round(highest_high - self.multiplier * s["atr"], 6),
            "chandelier_short_22": round(lowest_low + self.multiplier * s["atr"], 6),
        }


plugin = ChandelierPlugin()
```

### Step 4: Run tests — expect all green

```bash
.venv/bin/python3 -m pytest tests/unit/intelligence/test_chandelier.py -v
```

Expected: 8 tests PASSED

### Step 5: Commit

```bash
git add src/intelligence/indicators/chandelier.py tests/unit/intelligence/test_chandelier.py
git commit -m "feat: add ind_ChandelierExit plugin (ATR-based trailing stops) with incremental support"
```

---

## Task 5: Parabolic SAR (`ind_ParabolicSAR`)

Most stateful of the 6. SAR flips sides when price crosses it, resetting the acceleration factor. Read the algorithm comments carefully.

**Files:**
- Create: `src/intelligence/indicators/parabolic_sar.py`
- Create: `tests/unit/intelligence/test_parabolic_sar.py`

---

### Step 1: Write the failing tests

Create `tests/unit/intelligence/test_parabolic_sar.py`:

```python
"""Tests for Parabolic SAR indicator plugin."""

import numpy as np
import pandas as pd

from src.intelligence.indicators.parabolic_sar import PSARPlugin


def _make_ohlcv(n: int = 100, seed: int = 42, trend: str = "flat") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    if trend == "up":
        close = 5000.0 + np.arange(n) * 1.5 + rng.standard_normal(n) * 0.3
    elif trend == "down":
        close = 5200.0 - np.arange(n) * 1.5 + rng.standard_normal(n) * 0.3
    else:
        returns = rng.normal(0.0001, 0.005, n)
        close = 5000.0 * np.cumprod(1 + returns)
    spread = rng.uniform(0.003, 0.006, n)
    high = close * (1 + spread)
    low = close * (1 - spread)
    high = np.maximum(high, close)
    low = np.minimum(low, close)
    return pd.DataFrame({
        "open": close, "high": high, "low": low,
        "close": close,
        "volume": rng.lognormal(10, 0.5, n).astype(float),
    })


class TestPSAR:
    def test_output_keys_present(self):
        result = PSARPlugin().compute_full({"main": _make_ohlcv()})
        assert "psar_value" in result
        assert "psar_direction" in result

    def test_direction_is_valid(self):
        result = PSARPlugin().compute_full({"main": _make_ohlcv()})
        assert result["psar_direction"] in (1.0, -1.0)

    def test_psar_value_positive(self):
        result = PSARPlugin().compute_full({"main": _make_ohlcv()})
        assert result["psar_value"] > 0

    def test_uptrend_bullish_direction(self):
        """Strong uptrend → PSAR should be bullish (1.0) and below price."""
        df = _make_ohlcv(200, trend="up")
        result = PSARPlugin().compute_full({"main": df})
        assert result["psar_direction"] == 1.0
        assert result["psar_value"] < float(df["close"].iloc[-1])

    def test_downtrend_bearish_direction(self):
        """Strong downtrend → PSAR should be bearish (-1.0) and above price."""
        df = _make_ohlcv(200, trend="down")
        result = PSARPlugin().compute_full({"main": df})
        assert result["psar_direction"] == -1.0
        assert result["psar_value"] > float(df["close"].iloc[-1])

    def test_insufficient_data_returns_empty(self):
        result = PSARPlugin().compute_full({"main": _make_ohlcv(n=5)})
        assert result == {}

    def test_incremental_matches_full(self):
        """compute_next bar-by-bar should match fresh compute_full."""
        df = _make_ohlcv(200)

        plugin = PSARPlugin()
        plugin.compute_full({"main": df.iloc[:100].copy()})
        result = None
        for i in range(100, 200):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = PSARPlugin()
        full = fresh.compute_full({"main": df.copy()})

        assert result["psar_direction"] == full["psar_direction"]
        assert abs(result["psar_value"] - full["psar_value"]) / abs(full["psar_value"]) < 0.005

    def test_custom_af_params(self):
        plugin = PSARPlugin(af_step=0.01, af_max=0.10)
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert "psar_value" in result
```

### Step 2: Run tests — expect ImportError

```bash
.venv/bin/python3 -m pytest tests/unit/intelligence/test_parabolic_sar.py -v
```

### Step 3: Implement `src/intelligence/indicators/parabolic_sar.py`

Algorithm notes:
- **Long (bull) mode**: SAR accelerates upward from below price. Flip to short when low < SAR. SAR must always be ≤ min of previous 2 lows (prevents SAR jumping above price on initialization).
- **Short (bear) mode**: SAR accelerates downward from above price. Flip to long when high > SAR. SAR must always be ≥ max of previous 2 highs.
- AF starts at `af_step` (0.02), increments by `af_step` each time EP is broken, capped at `af_max` (0.20). AF resets on every flip.

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class PSARPlugin:
    """Parabolic SAR — trailing stop and reversal system.

    psar_value     : current SAR price level
    psar_direction : +1.0 (bull, SAR below price) / -1.0 (bear, SAR above price)

    A flip from +1 to -1 or vice versa signals a potential trend reversal.
    """

    name: str = "ind_ParabolicSAR"
    outputs: set[str] = frozenset({"psar_value", "psar_direction"})
    min_lookback: int = 10
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"trend"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=50),)
    af_step: float = 0.02
    af_max: float = 0.20
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        n = len(high)

        # Initialize from first 5 bars
        init = min(5, n // 2)
        if high[init - 1] >= high[0]:
            direction = 1.0
            ep = float(np.max(high[:init]))
            sar = float(np.min(low[:init]))
        else:
            direction = -1.0
            ep = float(np.min(low[:init]))
            sar = float(np.max(high[:init]))

        af = self.af_step
        prev_prev_h = float(high[max(0, init - 2)])
        prev_prev_l = float(low[max(0, init - 2)])
        prev_h = float(high[init - 1])
        prev_l = float(low[init - 1])

        for i in range(init, n):
            curr_h = float(high[i])
            curr_l = float(low[i])

            if direction == 1.0:
                new_sar = sar + af * (ep - sar)
                new_sar = min(new_sar, prev_l, prev_prev_l)
                if curr_l < new_sar:
                    direction = -1.0
                    new_sar = ep
                    ep = curr_l
                    af = self.af_step
                else:
                    if curr_h > ep:
                        ep = curr_h
                        af = min(af + self.af_step, self.af_max)
            else:
                new_sar = sar + af * (ep - sar)
                new_sar = max(new_sar, prev_h, prev_prev_h)
                if curr_h > new_sar:
                    direction = 1.0
                    new_sar = ep
                    ep = curr_h
                    af = self.af_step
                else:
                    if curr_l < ep:
                        ep = curr_l
                        af = min(af + self.af_step, self.af_max)

            prev_prev_h = prev_h
            prev_prev_l = prev_l
            prev_h = curr_h
            prev_l = curr_l
            sar = new_sar

        self._state = {
            "sar": sar, "ep": ep, "af": af, "direction": direction,
            "prev_high": prev_h, "prev_low": prev_l,
            "prev_prev_high": prev_prev_h, "prev_prev_low": prev_prev_l,
        }
        return {"psar_value": sar, "psar_direction": direction}

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}

        row = df.iloc[-1]
        curr_h = float(row["high"])
        curr_l = float(row["low"])
        s = self._state

        if s["direction"] == 1.0:
            new_sar = s["sar"] + s["af"] * (s["ep"] - s["sar"])
            new_sar = min(new_sar, s["prev_low"], s["prev_prev_low"])
            if curr_l < new_sar:
                s["direction"] = -1.0
                new_sar = s["ep"]
                s["ep"] = curr_l
                s["af"] = self.af_step
            else:
                if curr_h > s["ep"]:
                    s["ep"] = curr_h
                    s["af"] = min(s["af"] + self.af_step, self.af_max)
        else:
            new_sar = s["sar"] + s["af"] * (s["ep"] - s["sar"])
            new_sar = max(new_sar, s["prev_high"], s["prev_prev_high"])
            if curr_h > new_sar:
                s["direction"] = 1.0
                new_sar = s["ep"]
                s["ep"] = curr_h
                s["af"] = self.af_step
            else:
                if curr_l < s["ep"]:
                    s["ep"] = curr_l
                    s["af"] = min(s["af"] + self.af_step, self.af_max)

        s["prev_prev_high"] = s["prev_high"]
        s["prev_prev_low"] = s["prev_low"]
        s["prev_high"] = curr_h
        s["prev_low"] = curr_l
        s["sar"] = new_sar

        return {"psar_value": new_sar, "psar_direction": s["direction"]}


plugin = PSARPlugin()
```

### Step 4: Run tests — expect all green

```bash
.venv/bin/python3 -m pytest tests/unit/intelligence/test_parabolic_sar.py -v
```

Expected: 8 tests PASSED

### Step 5: Commit

```bash
git add src/intelligence/indicators/parabolic_sar.py tests/unit/intelligence/test_parabolic_sar.py
git commit -m "feat: add ind_ParabolicSAR plugin with incremental flip-state tracking"
```

---

## Task 6: Stochastic RSI (`ind_StochRSI`)

RSI of RSI with Stochastic normalization. State = Wilder's RSI smoothing state + rolling deque of 14 RSI values + rolling deque of 3 K values for D-line.

**Files:**
- Create: `src/intelligence/indicators/stochastic_rsi.py`
- Create: `tests/unit/intelligence/test_stochastic_rsi.py`

---

### Step 1: Write the failing tests

Create `tests/unit/intelligence/test_stochastic_rsi.py`:

```python
"""Tests for Stochastic RSI indicator plugin."""

import numpy as np
import pandas as pd

from src.intelligence.indicators.stochastic_rsi import StochRSIPlugin


def _make_ohlcv(n: int = 100, seed: int = 42, trend: str = "flat") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    if trend == "up":
        close = 5000.0 + np.arange(n) * 1.5 + rng.standard_normal(n) * 0.3
    elif trend == "down":
        close = 5200.0 - np.arange(n) * 1.5 + rng.standard_normal(n) * 0.3
    else:
        returns = rng.normal(0.0001, 0.005, n)
        close = 5000.0 * np.cumprod(1 + returns)
    spread = rng.uniform(0.001, 0.003, n)
    high = close * (1 + spread)
    low = close * (1 - spread)
    high = np.maximum(high, close)
    low = np.minimum(low, close)
    return pd.DataFrame({
        "open": close, "high": high, "low": low,
        "close": close,
        "volume": rng.lognormal(10, 0.5, n).astype(float),
    })


class TestStochRSI:
    def test_output_keys_present(self):
        result = StochRSIPlugin().compute_full({"main": _make_ohlcv()})
        assert "stoch_rsi_k_14" in result
        assert "stoch_rsi_d_14" in result

    def test_k_in_range(self):
        result = StochRSIPlugin().compute_full({"main": _make_ohlcv()})
        assert 0.0 <= result["stoch_rsi_k_14"] <= 100.0

    def test_d_in_range(self):
        result = StochRSIPlugin().compute_full({"main": _make_ohlcv()})
        assert 0.0 <= result["stoch_rsi_d_14"] <= 100.0

    def test_insufficient_data_returns_empty(self):
        result = StochRSIPlugin().compute_full({"main": _make_ohlcv(n=20)})
        assert result == {}

    def test_overbought_strong_uptrend(self):
        """Strong uptrend → StochRSI K should be > 50 (RSI elevated, near top of its range)."""
        df = _make_ohlcv(150, trend="up")
        result = StochRSIPlugin().compute_full({"main": df})
        assert result["stoch_rsi_k_14"] > 50.0

    def test_oversold_strong_downtrend(self):
        """Strong downtrend → StochRSI K should be < 50."""
        df = _make_ohlcv(150, trend="down")
        result = StochRSIPlugin().compute_full({"main": df})
        assert result["stoch_rsi_k_14"] < 50.0

    def test_flat_rsi_gives_midpoint(self):
        """When RSI is constant (high == low == close on every bar), K should be 50."""
        n = 80
        close = np.ones(n) * 5000.0
        df = pd.DataFrame({
            "open": close, "high": close, "low": close,
            "close": close, "volume": np.ones(n) * 1000,
        })
        result = StochRSIPlugin().compute_full({"main": df})
        # With no price changes, RSI = 50 constantly → StochRSI = 50
        assert result["stoch_rsi_k_14"] == 50.0

    def test_incremental_matches_full(self):
        df = _make_ohlcv(200)

        plugin = StochRSIPlugin()
        plugin.compute_full({"main": df.iloc[:100].copy()})
        result = None
        for i in range(100, 200):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = StochRSIPlugin()
        full = fresh.compute_full({"main": df.copy()})

        assert abs(result["stoch_rsi_k_14"] - full["stoch_rsi_k_14"]) < 0.5
        assert abs(result["stoch_rsi_d_14"] - full["stoch_rsi_d_14"]) < 0.5
```

### Step 2: Run tests — expect ImportError

```bash
.venv/bin/python3 -m pytest tests/unit/intelligence/test_stochastic_rsi.py -v
```

### Step 3: Implement `src/intelligence/indicators/stochastic_rsi.py`

```python
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class StochRSIPlugin:
    """Stochastic RSI — applies Stochastic normalization to RSI values.

    K = (RSI - min(RSI_window)) / (max(RSI_window) - min(RSI_window)) * 100
    D = SMA(K, d_period)

    Catches extreme overbought/oversold that plain RSI misses — RSI can sit
    at 60 for hours while StochRSI signals the local extreme.
    K < 20 = oversold extreme; K > 80 = overbought extreme.
    """

    name: str = "ind_StochRSI"
    outputs: set[str] = frozenset({"stoch_rsi_k_14", "stoch_rsi_d_14"})
    min_lookback: int = 35
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"momentum"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    period: int = 14
    d_period: int = 3
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.period * 2 + self.d_period:
            return {}

        close = df["close"].to_numpy(dtype=float)
        rsi_series = self._rsi_series(close, self.period)

        if len(rsi_series) < self.period + self.d_period - 1:
            return {}

        # Apply Stochastic to RSI series
        k_values = []
        for i in range(self.period - 1, len(rsi_series)):
            window = rsi_series[i - self.period + 1: i + 1]
            lo, hi = float(np.min(window)), float(np.max(window))
            k_values.append((rsi_series[i] - lo) / (hi - lo) * 100.0 if hi > lo else 50.0)

        if len(k_values) < self.d_period:
            return {}

        k = k_values[-1]
        d = float(np.mean(k_values[-self.d_period:]))

        # Seed incremental state
        deltas = np.diff(close)
        avg_g = float(deltas[:self.period].clip(min=0).sum() / self.period)
        avg_l = float(-deltas[:self.period].clip(max=0).sum() / self.period)
        for delta in deltas[self.period:]:
            avg_g = (avg_g * (self.period - 1) + max(delta, 0.0)) / self.period
            avg_l = (avg_l * (self.period - 1) + max(-delta, 0.0)) / self.period

        self._state = {
            "avg_gain": avg_g,
            "avg_loss": avg_l,
            "prev_close": float(close[-1]),
            "rsi_window": deque(rsi_series[-self.period:].tolist(), maxlen=self.period),
            "k_window": deque(k_values[-self.d_period:], maxlen=self.d_period),
        }
        return {"stoch_rsi_k_14": round(k, 4), "stoch_rsi_d_14": round(d, 4)}

    def _rsi_series(self, close: np.ndarray, period: int) -> np.ndarray:
        """Return RSI values starting from index `period` (length = len(close) - period - 1)."""
        deltas = np.diff(close)
        if len(deltas) < period:
            return np.array([])
        avg_g = float(deltas[:period].clip(min=0).sum() / period)
        avg_l = float(-deltas[:period].clip(max=0).sum() / period)
        values = []
        for delta in deltas[period:]:
            avg_g = (avg_g * (period - 1) + max(float(delta), 0.0)) / period
            avg_l = (avg_l * (period - 1) + max(-float(delta), 0.0)) / period
            values.append(100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l))
        return np.array(values)

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}

        curr = float(df["close"].iloc[-1])
        s = self._state

        delta = curr - s["prev_close"]
        s["avg_gain"] = (s["avg_gain"] * (self.period - 1) + max(delta, 0.0)) / self.period
        s["avg_loss"] = (s["avg_loss"] * (self.period - 1) + max(-delta, 0.0)) / self.period
        s["prev_close"] = curr

        rsi = 100.0 if s["avg_loss"] == 0 else 100.0 - 100.0 / (1.0 + s["avg_gain"] / s["avg_loss"])
        s["rsi_window"].append(rsi)

        if len(s["rsi_window"]) < self.period:
            return {}

        lo, hi = min(s["rsi_window"]), max(s["rsi_window"])
        k = (rsi - lo) / (hi - lo) * 100.0 if hi > lo else 50.0
        s["k_window"].append(k)

        if len(s["k_window"]) < self.d_period:
            return {}

        d = sum(s["k_window"]) / len(s["k_window"])
        return {"stoch_rsi_k_14": round(k, 4), "stoch_rsi_d_14": round(d, 4)}


plugin = StochRSIPlugin()
```

### Step 4: Run tests — expect all green

```bash
.venv/bin/python3 -m pytest tests/unit/intelligence/test_stochastic_rsi.py -v
```

Expected: 8 tests PASSED

### Step 5: Commit

```bash
git add src/intelligence/indicators/stochastic_rsi.py tests/unit/intelligence/test_stochastic_rsi.py
git commit -m "feat: add ind_StochRSI plugin (Stochastic RSI with D-line) with incremental support"
```

---

## Task 7: Register, Verify, Update Docs

**Files:**
- Modify: `src/intelligence/register_plugins.py`
- Modify: `docs/for-ai-assistants/CLAUDE.md` (plugin count: 45 → 51)
- Modify: `docs/plans/future-indicators-backlog.md` (mark Track A complete)

---

### Step 1: Add imports and registration to `register_plugins.py`

In `src/intelligence/register_plugins.py`, add after line 16 (`from .indicators.macd import plugin as macd_plugin`):

```python
from .indicators.aroon import plugin as aroon_plugin
from .indicators.chandelier import plugin as chandelier_plugin
from .indicators.cmf import plugin as cmf_plugin
from .indicators.historical_volatility import plugin as hv_plugin
from .indicators.parabolic_sar import plugin as psar_plugin
from .indicators.stochastic_rsi import plugin as stoch_rsi_plugin
```

In the `register_all_plugins()` function, add after `registry.register_indicator(roc_ppo_plugin)` (line 68):

```python
    registry.register_indicator(aroon_plugin)
    registry.register_indicator(chandelier_plugin)
    registry.register_indicator(cmf_plugin)
    registry.register_indicator(hv_plugin)
    registry.register_indicator(psar_plugin)
    registry.register_indicator(stoch_rsi_plugin)
```

### Step 2: Run full test suite

```bash
.venv/bin/python3 -m pytest tests/unit/ --ignore=tests/integration -q
```

Expected: all existing 383 tests + 47 new tests = ~430 tests PASSED, 0 failures.

If any failures: read the error message carefully. Do NOT retry — investigate root cause.

### Step 3: Run the plugin registry sanity check

```bash
.venv/bin/python3 -c "
from src.intelligence.register_plugins import register_all_plugins
from src.intelligence.plugins import registry
register_all_plugins()
total = len(registry.indicators) + len(registry.patterns)
print(f'Indicators: {len(registry.indicators)}')
print(f'Patterns: {len(registry.patterns)}')
print(f'Total: {total}')
assert total == 51, f'Expected 51, got {total}'
print('OK')
"
```

Expected output:
```
Indicators: 23
Patterns: 28
Total: 51
OK
```

### Step 4: Update CLAUDE.md plugin count

In `docs/for-ai-assistants/CLAUDE.md`, find and update:

```
### I1 Technical Indicators (17 plugins)
```
→
```
### I1 Technical Indicators (23 plugins)
```

Also update the plugin list under I1 to add:
```
- **Trend:** SMA/EMA, MACD, ADX/DMI, Parabolic SAR, Aroon
- **Momentum:** RSI, Stochastic, Williams %R, CCI, ROC/PPO, Stochastic RSI
- **Volatility:** Bollinger Bands, ATR, Keltner Channels, Donchian Channels, Chandelier Exit, Historical Volatility
- **Volume:** OBV, MFI, VWAP, CMF
```

Update the Status line and Plugin System count from 45 to 51.

### Step 5: Mark Track A complete in backlog

In `docs/plans/future-indicators-backlog.md`, update the Track A row:

```markdown
### Track A: New I1 Indicators — ✅ COMPLETED (v4.7.0)
```

### Step 6: Commit and finish

```bash
git add src/intelligence/register_plugins.py \
        docs/for-ai-assistants/CLAUDE.md \
        docs/plans/future-indicators-backlog.md
git commit -m "feat: register 6 new I1 plugins, update docs (45 → 51 plugins total)"
```

Then invoke the `superpowers:finishing-a-development-branch` skill to merge.

---

## Quick Reference

| Plugin | File | Test File | Outputs |
|---|---|---|---|
| `ind_CMF` | `indicators/cmf.py` | `test_cmf.py` | `cmf_20` |
| `ind_Aroon` | `indicators/aroon.py` | `test_aroon.py` | `aroon_up_25`, `aroon_down_25`, `aroon_osc_25` |
| `ind_HistoricalVolatility` | `indicators/historical_volatility.py` | `test_historical_volatility.py` | `hv_20`, `hv_ratio_20` |
| `ind_ChandelierExit` | `indicators/chandelier.py` | `test_chandelier.py` | `chandelier_long_22`, `chandelier_short_22` |
| `ind_ParabolicSAR` | `indicators/parabolic_sar.py` | `test_parabolic_sar.py` | `psar_value`, `psar_direction` |
| `ind_StochRSI` | `indicators/stochastic_rsi.py` | `test_stochastic_rsi.py` | `stoch_rsi_k_14`, `stoch_rsi_d_14` |
