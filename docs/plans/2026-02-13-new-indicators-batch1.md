# New Indicators Batch 1: ADX/DMI, Keltner Channels, Donchian Channels, ROC/PPO

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 4 new I1 indicator plugins (ADX/DMI, Keltner Channels, Donchian Channels, ROC/PPO) following the established plugin pattern with incremental compute_next() support.

**Architecture:** Each indicator is a standalone `@dataclass` plugin in `src/intelligence/indicators/`, registered via `register_indicator()` in `register_plugins.py`. All 4 support incremental updates. Tests follow the existing pattern in `tests/unit/intelligence/test_plugin_incremental.py`.

**Tech Stack:** Python 3.13, numpy, pandas, dataclasses. Plugin protocol defined in `src/intelligence/plugins.py`.

---

## Plugin Pattern Reference

Every plugin follows this exact structure (see `src/intelligence/indicators/rsi.py` as canonical example):

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import pandas as pd
from ..plugins import InputSpec

@dataclass
class FooPlugin:
    name: str = "Foo"
    outputs: set[str] = frozenset({"foo_14"})
    min_lookback: int = 20
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"category"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        # Full batch computation on frames["main"] DataFrame
        # Must call self._seed_state(frames) before returning
        ...

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> None:
        # Extract state needed for incremental updates
        ...

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        # Incremental single-bar update using self._state
        if not self._state:
            return self.compute_full(windows)
        ...

plugin = FooPlugin()  # Module-level singleton
```

Key conventions:
- `frames["main"]` is always the OHLCV DataFrame with columns: open, high, low, close, volume
- `compute_full()` always calls `self._seed_state()` to prepare incremental state
- `compute_next()` falls back to `compute_full()` if state is empty
- Output keys use format `indicator_param1_param2` (e.g., `adx_14`, `donchian_upper_20`)
- Module ends with `plugin = PluginClass()` singleton

---

### Task 1: ADX/DMI Plugin

ADX (Average Directional Index) with +DI/-DI (Directional Movement Indicators). This is the standard Wilder's trend strength filter.

**Files:**
- Create: `src/intelligence/indicators/adx.py`
- Test: `tests/unit/intelligence/test_plugin_incremental.py` (append new test class)

**Step 1: Write the failing test**

Append to `tests/unit/intelligence/test_plugin_incremental.py`:

```python
class TestADXIncremental:
    def test_compute_next_matches_full(self):
        from src.intelligence.indicators.adx import ADXPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = ADXPlugin()

        plugin.compute_full({"main": df.iloc[:SEED_BARS].copy()})
        for i in range(SEED_BARS, TOTAL_BARS):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = ADXPlugin()
        full_result = fresh.compute_full({"main": df.copy()})

        assert_values_close(result, full_result, "ADX")

    def test_compute_full_outputs(self):
        from src.intelligence.indicators.adx import ADXPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = ADXPlugin()
        result = plugin.compute_full({"main": df})

        assert "adx_14" in result
        assert "plus_di_14" in result
        assert "minus_di_14" in result
        assert 0 <= result["adx_14"] <= 100
        assert 0 <= result["plus_di_14"] <= 100
        assert 0 <= result["minus_di_14"] <= 100

    def test_empty_input(self):
        from src.intelligence.indicators.adx import ADXPlugin

        plugin = ADXPlugin()
        assert plugin.compute_full({"main": None}) == {}
        assert plugin.compute_full({}) == {}

    def test_insufficient_data(self):
        from src.intelligence.indicators.adx import ADXPlugin

        df = generate_synthetic_ohlcv(10)
        plugin = ADXPlugin()
        assert plugin.compute_full({"main": df}) == {}
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/intelligence/test_plugin_incremental.py::TestADXIncremental -v`
Expected: FAIL (ImportError — module doesn't exist yet)

**Step 3: Write the implementation**

Create `src/intelligence/indicators/adx.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ..plugins import InputSpec


@dataclass
class ADXPlugin:
    """Average Directional Index with +DI/-DI (Wilder's method).

    ADX measures trend strength (0-100) regardless of direction.
    +DI/-DI measure bullish/bearish directional movement.
    """

    name: str = "ADX"
    outputs: set[str] = frozenset({"adx_14", "plus_di_14", "minus_di_14"})
    min_lookback: int = 30
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"trend"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=200),)
    periods: list[int] = None
    _state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.periods:
            self.periods = [14]
        self.outputs = frozenset(
            {
                key
                for p in self.periods
                for key in (f"adx_{p}", f"plus_di_{p}", f"minus_di_{p}")
            }
        )

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < max(self.periods) * 2 + 1:
            return {}
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        out: dict[str, Any] = {}
        for p in self.periods:
            adx, plus_di, minus_di = self._adx_np(high, low, close, p)
            if adx is not None:
                out[f"adx_{p}"] = adx
                out[f"plus_di_{p}"] = plus_di
                out[f"minus_di_{p}"] = minus_di
        self._seed_state(frames)
        return out

    def _adx_np(
        self, high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int
    ) -> tuple[float | None, float, float]:
        """Compute ADX using Wilder's smoothing."""
        n = len(high)
        if n < period * 2 + 1:
            return None, 0.0, 0.0

        # Directional Movement
        plus_dm = np.zeros(n)
        minus_dm = np.zeros(n)
        tr = np.zeros(n)
        tr[0] = high[0] - low[0]

        for i in range(1, n):
            up_move = high[i] - high[i - 1]
            down_move = low[i - 1] - low[i]
            plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0.0
            minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0.0
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )

        # Wilder's smoothing (EMA with alpha=1/period)
        alpha = 1.0 / period

        # Seed: SMA of first `period` values (starting from index 1)
        smoothed_plus_dm = float(np.mean(plus_dm[1 : period + 1]))
        smoothed_minus_dm = float(np.mean(minus_dm[1 : period + 1]))
        smoothed_tr = float(np.mean(tr[1 : period + 1]))

        dx_values = []
        for i in range(period + 1, n):
            smoothed_plus_dm = (1 - alpha) * smoothed_plus_dm + alpha * plus_dm[i]
            smoothed_minus_dm = (1 - alpha) * smoothed_minus_dm + alpha * minus_dm[i]
            smoothed_tr = (1 - alpha) * smoothed_tr + alpha * tr[i]

            if smoothed_tr == 0:
                plus_di = 0.0
                minus_di = 0.0
            else:
                plus_di = 100.0 * smoothed_plus_dm / smoothed_tr
                minus_di = 100.0 * smoothed_minus_dm / smoothed_tr

            di_sum = plus_di + minus_di
            dx = 100.0 * abs(plus_di - minus_di) / di_sum if di_sum != 0 else 0.0
            dx_values.append(dx)

        if len(dx_values) < period:
            return None, 0.0, 0.0

        # ADX: Wilder's smoothing of DX
        adx = float(np.mean(dx_values[:period]))
        for dx in dx_values[period:]:
            adx = (1 - alpha) * adx + alpha * dx

        # Final +DI/-DI from last smoothed values
        if smoothed_tr == 0:
            final_plus_di = 0.0
            final_minus_di = 0.0
        else:
            final_plus_di = 100.0 * smoothed_plus_dm / smoothed_tr
            final_minus_di = 100.0 * smoothed_minus_dm / smoothed_tr

        return float(adx), float(final_plus_di), float(final_minus_di)

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> None:
        """Extract Wilder's smoothing state for incremental updates."""
        df = frames.get("main")
        if df is None:
            return
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        close = df["close"].to_numpy(dtype=float)
        n = len(high)

        for p in self.periods:
            if n < p * 2 + 1:
                continue
            alpha = 1.0 / p

            # Replay full computation to capture final state
            plus_dm = np.zeros(n)
            minus_dm = np.zeros(n)
            tr = np.zeros(n)
            tr[0] = high[0] - low[0]

            for i in range(1, n):
                up_move = high[i] - high[i - 1]
                down_move = low[i - 1] - low[i]
                plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0.0
                minus_dm[i] = (
                    down_move if (down_move > up_move and down_move > 0) else 0.0
                )
                tr[i] = max(
                    high[i] - low[i],
                    abs(high[i] - close[i - 1]),
                    abs(low[i] - close[i - 1]),
                )

            smoothed_plus_dm = float(np.mean(plus_dm[1 : p + 1]))
            smoothed_minus_dm = float(np.mean(minus_dm[1 : p + 1]))
            smoothed_tr = float(np.mean(tr[1 : p + 1]))

            dx_values = []
            for i in range(p + 1, n):
                smoothed_plus_dm = (1 - alpha) * smoothed_plus_dm + alpha * plus_dm[i]
                smoothed_minus_dm = (
                    (1 - alpha) * smoothed_minus_dm + alpha * minus_dm[i]
                )
                smoothed_tr = (1 - alpha) * smoothed_tr + alpha * tr[i]

                if smoothed_tr == 0:
                    pdi = 0.0
                    mdi = 0.0
                else:
                    pdi = 100.0 * smoothed_plus_dm / smoothed_tr
                    mdi = 100.0 * smoothed_minus_dm / smoothed_tr

                di_sum = pdi + mdi
                dx = 100.0 * abs(pdi - mdi) / di_sum if di_sum != 0 else 0.0
                dx_values.append(dx)

            adx = float(np.mean(dx_values[:p]))
            for dx in dx_values[p:]:
                adx = (1 - alpha) * adx + alpha * dx

            self._state[f"adx_{p}"] = {
                "smoothed_plus_dm": smoothed_plus_dm,
                "smoothed_minus_dm": smoothed_minus_dm,
                "smoothed_tr": smoothed_tr,
                "adx": adx,
                "prev_high": float(high[-1]),
                "prev_low": float(low[-1]),
                "prev_close": float(close[-1]),
            }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        row = df.iloc[-1]
        h = float(row["high"])
        lo = float(row["low"])
        c = float(row["close"])
        out: dict[str, Any] = {}

        for p in self.periods:
            key = f"adx_{p}"
            if key not in self._state:
                continue
            s = self._state[key]
            alpha = 1.0 / p

            # Directional Movement
            up_move = h - s["prev_high"]
            down_move = s["prev_low"] - lo
            pdm = up_move if (up_move > down_move and up_move > 0) else 0.0
            mdm = down_move if (down_move > up_move and down_move > 0) else 0.0
            tr = max(h - lo, abs(h - s["prev_close"]), abs(lo - s["prev_close"]))

            # Wilder's smoothing
            s["smoothed_plus_dm"] = (1 - alpha) * s["smoothed_plus_dm"] + alpha * pdm
            s["smoothed_minus_dm"] = (1 - alpha) * s["smoothed_minus_dm"] + alpha * mdm
            s["smoothed_tr"] = (1 - alpha) * s["smoothed_tr"] + alpha * tr

            if s["smoothed_tr"] == 0:
                plus_di = 0.0
                minus_di = 0.0
            else:
                plus_di = 100.0 * s["smoothed_plus_dm"] / s["smoothed_tr"]
                minus_di = 100.0 * s["smoothed_minus_dm"] / s["smoothed_tr"]

            di_sum = plus_di + minus_di
            dx = 100.0 * abs(plus_di - minus_di) / di_sum if di_sum != 0 else 0.0

            # Smooth ADX
            s["adx"] = (1 - alpha) * s["adx"] + alpha * dx

            s["prev_high"] = h
            s["prev_low"] = lo
            s["prev_close"] = c

            out[f"adx_{p}"] = s["adx"]
            out[f"plus_di_{p}"] = plus_di
            out[f"minus_di_{p}"] = minus_di

        return out


plugin = ADXPlugin()
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/intelligence/test_plugin_incremental.py::TestADXIncremental -v`
Expected: 4 PASS

**Step 5: Commit**

```bash
git add src/intelligence/indicators/adx.py tests/unit/intelligence/test_plugin_incremental.py
git commit -m "feat: add ADX/DMI indicator plugin with incremental support"
```

---

### Task 2: Keltner Channels Plugin

Extract standalone Keltner Channels from the Bollinger Squeeze's internal KC computation. KC = EMA(close, period) ± multiplier × ATR(period).

**Files:**
- Create: `src/intelligence/indicators/keltner.py`
- Test: `tests/unit/intelligence/test_plugin_incremental.py` (append new test class)

**Step 1: Write the failing test**

Append to `tests/unit/intelligence/test_plugin_incremental.py`:

```python
class TestKeltnerIncremental:
    def test_compute_next_matches_full(self):
        from src.intelligence.indicators.keltner import KeltnerChannelsPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = KeltnerChannelsPlugin()

        plugin.compute_full({"main": df.iloc[:SEED_BARS].copy()})
        for i in range(SEED_BARS, TOTAL_BARS):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = KeltnerChannelsPlugin()
        full_result = fresh.compute_full({"main": df.copy()})

        assert_values_close(result, full_result, "Keltner")

    def test_compute_full_outputs(self):
        from src.intelligence.indicators.keltner import KeltnerChannelsPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = KeltnerChannelsPlugin()
        result = plugin.compute_full({"main": df})

        assert "kc_upper_20" in result
        assert "kc_mid_20" in result
        assert "kc_lower_20" in result
        # Upper > mid > lower always
        assert result["kc_upper_20"] > result["kc_mid_20"]
        assert result["kc_mid_20"] > result["kc_lower_20"]

    def test_empty_input(self):
        from src.intelligence.indicators.keltner import KeltnerChannelsPlugin

        plugin = KeltnerChannelsPlugin()
        assert plugin.compute_full({"main": None}) == {}
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/intelligence/test_plugin_incremental.py::TestKeltnerIncremental -v`
Expected: FAIL (ImportError)

**Step 3: Write the implementation**

Create `src/intelligence/indicators/keltner.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..plugins import InputSpec


@dataclass
class KeltnerChannelsPlugin:
    """Keltner Channels: EMA ± multiplier × ATR.

    Measures volatility-adjusted price channels. When Bollinger Bands
    contract inside Keltner Channels, a "squeeze" is forming.
    """

    name: str = "KeltnerChannels"
    outputs: set[str] = frozenset({"kc_upper_20", "kc_mid_20", "kc_lower_20"})
    min_lookback: int = 25
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"volatility"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    period: int = 20
    atr_period: int = 20
    multiplier: float = 1.5
    _state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.outputs = frozenset(
            {
                f"kc_upper_{self.period}",
                f"kc_mid_{self.period}",
                f"kc_lower_{self.period}",
            }
        )

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < max(self.period, self.atr_period) + 1:
            return {}
        close = df["close"]
        high = df["high"]
        low = df["low"]

        # EMA of close
        ema = close.ewm(span=self.period, adjust=False, min_periods=self.period).mean()

        # ATR via Wilder's smoothing
        prev_close = close.shift(1)
        tr = pd.concat(
            [
                (high - low).abs(),
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.ewm(alpha=1 / self.atr_period, adjust=False, min_periods=self.atr_period).mean()

        mid = float(ema.iloc[-1])
        atr_val = float(atr.iloc[-1])
        out = {
            f"kc_upper_{self.period}": mid + self.multiplier * atr_val,
            f"kc_mid_{self.period}": mid,
            f"kc_lower_{self.period}": mid - self.multiplier * atr_val,
        }
        self._seed_state(frames)
        return out

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> None:
        df = frames.get("main")
        if df is None:
            return
        close = df["close"]
        high = df["high"]
        low = df["low"]

        ema = close.ewm(span=self.period, adjust=False, min_periods=self.period).mean()

        prev_close = close.shift(1)
        tr = pd.concat(
            [
                (high - low).abs(),
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.ewm(alpha=1 / self.atr_period, adjust=False, min_periods=self.atr_period).mean()

        self._state = {
            "ema": float(ema.iloc[-1]),
            "atr": float(atr.iloc[-1]),
            "prev_close": float(close.iloc[-1]),
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        row = df.iloc[-1]
        h = float(row["high"])
        lo = float(row["low"])
        c = float(row["close"])

        s = self._state
        # Update EMA
        alpha_ema = 2.0 / (self.period + 1)
        s["ema"] = alpha_ema * c + (1 - alpha_ema) * s["ema"]

        # Update ATR (Wilder's)
        alpha_atr = 1.0 / self.atr_period
        tr = max(h - lo, abs(h - s["prev_close"]), abs(lo - s["prev_close"]))
        s["atr"] = (1 - alpha_atr) * s["atr"] + alpha_atr * tr
        s["prev_close"] = c

        mid = s["ema"]
        return {
            f"kc_upper_{self.period}": mid + self.multiplier * s["atr"],
            f"kc_mid_{self.period}": mid,
            f"kc_lower_{self.period}": mid - self.multiplier * s["atr"],
        }


plugin = KeltnerChannelsPlugin()
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/intelligence/test_plugin_incremental.py::TestKeltnerIncremental -v`
Expected: 3 PASS

**Step 5: Commit**

```bash
git add src/intelligence/indicators/keltner.py tests/unit/intelligence/test_plugin_incremental.py
git commit -m "feat: add Keltner Channels indicator plugin with incremental support"
```

---

### Task 3: Donchian Channels Plugin

Donchian Channels = N-period highest high / lowest low. The basis of Richard Dennis's turtle trading system.

**Files:**
- Create: `src/intelligence/indicators/donchian.py`
- Test: `tests/unit/intelligence/test_plugin_incremental.py` (append new test class)

**Step 1: Write the failing test**

Append to `tests/unit/intelligence/test_plugin_incremental.py`:

```python
class TestDonchianIncremental:
    def test_compute_next_matches_full(self):
        from src.intelligence.indicators.donchian import DonchianChannelsPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = DonchianChannelsPlugin()

        plugin.compute_full({"main": df.iloc[:SEED_BARS].copy()})
        for i in range(SEED_BARS, TOTAL_BARS):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = DonchianChannelsPlugin()
        full_result = fresh.compute_full({"main": df.copy()})

        assert_values_close(result, full_result, "Donchian")

    def test_compute_full_outputs(self):
        from src.intelligence.indicators.donchian import DonchianChannelsPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = DonchianChannelsPlugin()
        result = plugin.compute_full({"main": df})

        assert "donchian_upper_20" in result
        assert "donchian_mid_20" in result
        assert "donchian_lower_20" in result
        assert result["donchian_upper_20"] >= result["donchian_mid_20"]
        assert result["donchian_mid_20"] >= result["donchian_lower_20"]

    def test_empty_input(self):
        from src.intelligence.indicators.donchian import DonchianChannelsPlugin

        plugin = DonchianChannelsPlugin()
        assert plugin.compute_full({"main": None}) == {}
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/intelligence/test_plugin_incremental.py::TestDonchianIncremental -v`
Expected: FAIL (ImportError)

**Step 3: Write the implementation**

Create `src/intelligence/indicators/donchian.py`:

```python
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..plugins import InputSpec


@dataclass
class DonchianChannelsPlugin:
    """Donchian Channels: N-period highest high / lowest low.

    Breakout indicator used in turtle trading systems.
    Upper = max(high, N), Lower = min(low, N), Mid = average.
    """

    name: str = "DonchianChannels"
    outputs: set[str] = frozenset(
        {"donchian_upper_20", "donchian_mid_20", "donchian_lower_20"}
    )
    min_lookback: int = 22
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"volatility"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    period: int = 20
    _state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.outputs = frozenset(
            {
                f"donchian_upper_{self.period}",
                f"donchian_mid_{self.period}",
                f"donchian_lower_{self.period}",
            }
        )

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.period:
            return {}
        high = df["high"]
        low = df["low"]

        upper = float(high.iloc[-self.period :].max())
        lower = float(low.iloc[-self.period :].min())
        mid = (upper + lower) / 2.0

        self._seed_state(frames)
        return {
            f"donchian_upper_{self.period}": upper,
            f"donchian_mid_{self.period}": mid,
            f"donchian_lower_{self.period}": lower,
        }

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> None:
        df = frames.get("main")
        if df is None:
            return
        highs = df["high"].iloc[-self.period :].tolist()
        lows = df["low"].iloc[-self.period :].tolist()
        self._state = {
            "high_window": deque(highs, maxlen=self.period),
            "low_window": deque(lows, maxlen=self.period),
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        row = df.iloc[-1]
        h = float(row["high"])
        lo = float(row["low"])

        s = self._state
        s["high_window"].append(h)
        s["low_window"].append(lo)

        upper = max(s["high_window"])
        lower = min(s["low_window"])
        mid = (upper + lower) / 2.0

        return {
            f"donchian_upper_{self.period}": upper,
            f"donchian_mid_{self.period}": mid,
            f"donchian_lower_{self.period}": lower,
        }


plugin = DonchianChannelsPlugin()
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/intelligence/test_plugin_incremental.py::TestDonchianIncremental -v`
Expected: 3 PASS

**Step 5: Commit**

```bash
git add src/intelligence/indicators/donchian.py tests/unit/intelligence/test_plugin_incremental.py
git commit -m "feat: add Donchian Channels indicator plugin with incremental support"
```

---

### Task 4: ROC/PPO Plugin

Rate of Change (ROC) and Percentage Price Oscillator (PPO) in one plugin. Both are normalized momentum measures.

**Files:**
- Create: `src/intelligence/indicators/roc_ppo.py`
- Test: `tests/unit/intelligence/test_plugin_incremental.py` (append new test class)

**Step 1: Write the failing test**

Append to `tests/unit/intelligence/test_plugin_incremental.py`:

```python
class TestROCPPOIncremental:
    def test_compute_next_matches_full(self):
        from src.intelligence.indicators.roc_ppo import ROCPPOPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = ROCPPOPlugin()

        plugin.compute_full({"main": df.iloc[:SEED_BARS].copy()})
        for i in range(SEED_BARS, TOTAL_BARS):
            result = plugin.compute_next({"main": df.iloc[: i + 1].copy()})

        fresh = ROCPPOPlugin()
        full_result = fresh.compute_full({"main": df.copy()})

        assert_values_close(result, full_result, "ROC_PPO")

    def test_compute_full_outputs(self):
        from src.intelligence.indicators.roc_ppo import ROCPPOPlugin

        df = generate_synthetic_ohlcv(TOTAL_BARS)
        plugin = ROCPPOPlugin()
        result = plugin.compute_full({"main": df})

        assert "roc_14" in result
        assert "ppo_12_26" in result
        assert "ppo_signal_12_26" in result
        # ROC can be positive or negative
        assert isinstance(result["roc_14"], float)
        # PPO is percentage-based
        assert isinstance(result["ppo_12_26"], float)

    def test_empty_input(self):
        from src.intelligence.indicators.roc_ppo import ROCPPOPlugin

        plugin = ROCPPOPlugin()
        assert plugin.compute_full({"main": None}) == {}
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/intelligence/test_plugin_incremental.py::TestROCPPOIncremental -v`
Expected: FAIL (ImportError)

**Step 3: Write the implementation**

Create `src/intelligence/indicators/roc_ppo.py`:

```python
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..plugins import InputSpec


@dataclass
class ROCPPOPlugin:
    """Rate of Change (ROC) and Percentage Price Oscillator (PPO).

    ROC: ((close - close_n) / close_n) * 100  (simple % change over N periods)
    PPO: ((EMA_fast - EMA_slow) / EMA_slow) * 100  (normalized MACD)

    PPO is MACD expressed as a percentage, enabling cross-instrument comparison.
    """

    name: str = "ROC_PPO"
    outputs: set[str] = frozenset({"roc_14", "ppo_12_26", "ppo_signal_12_26"})
    min_lookback: int = 30
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"momentum"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=200),)
    roc_period: int = 14
    ppo_fast: int = 12
    ppo_slow: int = 26
    ppo_signal: int = 9
    _state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.outputs = frozenset(
            {
                f"roc_{self.roc_period}",
                f"ppo_{self.ppo_fast}_{self.ppo_slow}",
                f"ppo_signal_{self.ppo_fast}_{self.ppo_slow}",
            }
        )

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.ppo_slow + self.ppo_signal + 1:
            return {}
        close = df["close"]
        out: dict[str, Any] = {}

        # ROC
        if len(close) > self.roc_period:
            current = float(close.iloc[-1])
            past = float(close.iloc[-1 - self.roc_period])
            out[f"roc_{self.roc_period}"] = (
                100.0 * (current - past) / past if past != 0 else 0.0
            )

        # PPO = (EMA_fast - EMA_slow) / EMA_slow * 100
        ema_fast = close.ewm(span=self.ppo_fast, adjust=False, min_periods=self.ppo_fast).mean()
        ema_slow = close.ewm(span=self.ppo_slow, adjust=False, min_periods=self.ppo_slow).mean()
        ppo_line = (ema_fast - ema_slow) / ema_slow * 100
        ppo_sig = ppo_line.ewm(span=self.ppo_signal, adjust=False, min_periods=self.ppo_signal).mean()

        out[f"ppo_{self.ppo_fast}_{self.ppo_slow}"] = float(ppo_line.iloc[-1])
        out[f"ppo_signal_{self.ppo_fast}_{self.ppo_slow}"] = float(ppo_sig.iloc[-1])

        self._seed_state(frames)
        return out

    def _seed_state(self, frames: dict[str, pd.DataFrame]) -> None:
        df = frames.get("main")
        if df is None:
            return
        close = df["close"]

        # ROC state: keep a deque of recent closes for lookback
        recent = close.iloc[-self.roc_period - 1 :].tolist()
        roc_window = deque(recent, maxlen=self.roc_period + 1)

        # PPO state: EMA values
        ema_fast = close.ewm(span=self.ppo_fast, adjust=False, min_periods=self.ppo_fast).mean()
        ema_slow = close.ewm(span=self.ppo_slow, adjust=False, min_periods=self.ppo_slow).mean()
        ppo_line = (ema_fast - ema_slow) / ema_slow * 100
        ppo_sig = ppo_line.ewm(span=self.ppo_signal, adjust=False, min_periods=self.ppo_signal).mean()

        self._state = {
            "roc_window": roc_window,
            "ema_fast": float(ema_fast.iloc[-1]),
            "ema_slow": float(ema_slow.iloc[-1]),
            "ppo_signal_ema": float(ppo_sig.iloc[-1]),
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)
        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}
        c = float(df["close"].iloc[-1])
        s = self._state
        out: dict[str, Any] = {}

        # ROC: % change from N bars ago
        s["roc_window"].append(c)
        if len(s["roc_window"]) == self.roc_period + 1:
            past = s["roc_window"][0]
            out[f"roc_{self.roc_period}"] = (
                100.0 * (c - past) / past if past != 0 else 0.0
            )

        # PPO: update EMAs
        alpha_fast = 2.0 / (self.ppo_fast + 1)
        alpha_slow = 2.0 / (self.ppo_slow + 1)
        s["ema_fast"] = alpha_fast * c + (1 - alpha_fast) * s["ema_fast"]
        s["ema_slow"] = alpha_slow * c + (1 - alpha_slow) * s["ema_slow"]

        ppo_val = (
            100.0 * (s["ema_fast"] - s["ema_slow"]) / s["ema_slow"]
            if s["ema_slow"] != 0
            else 0.0
        )

        alpha_sig = 2.0 / (self.ppo_signal + 1)
        s["ppo_signal_ema"] = alpha_sig * ppo_val + (1 - alpha_sig) * s["ppo_signal_ema"]

        out[f"ppo_{self.ppo_fast}_{self.ppo_slow}"] = ppo_val
        out[f"ppo_signal_{self.ppo_fast}_{self.ppo_slow}"] = s["ppo_signal_ema"]

        return out


plugin = ROCPPOPlugin()
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/intelligence/test_plugin_incremental.py::TestROCPPOIncremental -v`
Expected: 3 PASS

**Step 5: Commit**

```bash
git add src/intelligence/indicators/roc_ppo.py tests/unit/intelligence/test_plugin_incremental.py
git commit -m "feat: add ROC/PPO indicator plugin with incremental support"
```

---

### Task 5: Register All 4 New Plugins

**Files:**
- Modify: `src/intelligence/register_plugins.py`

**Step 1: Update register_plugins.py**

Add imports and registrations for all 4 new plugins:

```python
# Add these imports after the existing indicator imports:
from .indicators.adx import plugin as adx_plugin
from .indicators.donchian import plugin as donchian_plugin
from .indicators.keltner import plugin as keltner_plugin
from .indicators.roc_ppo import plugin as roc_ppo_plugin
```

Add these registrations inside `register_all_plugins()` after the existing `register_indicator()` calls:

```python
    registry.register_indicator(adx_plugin)
    registry.register_indicator(keltner_plugin)
    registry.register_indicator(donchian_plugin)
    registry.register_indicator(roc_ppo_plugin)
```

**Step 2: Verify registration**

Run: `python -c "from src.intelligence.register_plugins import register_all_plugins; from src.intelligence.plugins import registry; register_all_plugins(); print(f'Indicators: {len(registry.indicators)}, Patterns: {len(registry.patterns)}, Total: {len(registry.indicators) + len(registry.patterns)}')" `
Expected: `Indicators: 16, Patterns: 10, Total: 26`

**Step 3: Run full test suite**

Run: `python -m pytest tests/unit/ -v`
Expected: All tests pass (110 existing + 13 new = ~123 tests)

**Step 4: Lint check**

Run: `.venv/bin/ruff check src/intelligence/indicators/adx.py src/intelligence/indicators/keltner.py src/intelligence/indicators/donchian.py src/intelligence/indicators/roc_ppo.py src/intelligence/register_plugins.py`
Expected: 0 errors

**Step 5: Commit**

```bash
git add src/intelligence/register_plugins.py
git commit -m "feat: register ADX, Keltner, Donchian, ROC/PPO plugins (26 total)"
```
