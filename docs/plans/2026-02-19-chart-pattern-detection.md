# Chart Pattern Detection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add three I5 chart pattern plugins — `patt_DoubleTB`, `patt_HeadShoulders`, `patt_TriangleWedge` — with two-stage swing filtering, sloped H&S neckline, and convergence-based triangle confidence.

**Architecture:** Each plugin is a standalone `@dataclass` in `src/intelligence/patterns/`. All three use `find_peaks`/`find_troughs` from `src/intelligence/utils.py` followed by a significance filter that removes noise swings (too close in price AND time). `supports_incremental = False` — `compute_next` delegates to `compute_full`. Registered in `src/intelligence/register_plugins.py`.

**Tech Stack:** Python 3.11, numpy, pandas, pytest. No new dependencies.

---

## Context: How Existing Plugins Work

Reference implementations to read before starting:
- `src/intelligence/patterns/rsi_divergence.py` — best structural reference (also uses `find_peaks`, `supports_incremental=False`)
- `src/intelligence/utils.py` — `find_peaks(data, n)` and `find_troughs(data, n)` utilities
- `src/intelligence/register_plugins.py` — where to add imports and `registry.register_pattern(...)` calls

Plugin protocol (from `src/intelligence/plugins.py`):
- `@dataclass` class with `name`, `outputs` (frozenset), `min_lookback`, `supports_incremental`, `capability_tags`, `inputs`
- `compute_full(self, frames: dict[str, Any]) -> dict[str, Any]` — receives `frames["main"]` as a pandas DataFrame
- `compute_next(self, windows: dict[str, Any]) -> dict[str, Any]` — for non-incremental: just calls `compute_full`
- Module-level `plugin = MyPlugin()` singleton
- Return `{}` when data is insufficient. Return default zeros dict when data is sufficient but no pattern found.

Test command: `.venv/bin/python3 -m pytest tests/unit/ -q`

---

## Task 1: Write Failing Tests — patt_DoubleTB

**Files:**
- Create: `tests/unit/test_double_top_bottom.py`

**Step 1: Write the test file**

```python
# tests/unit/test_double_top_bottom.py
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# This import will FAIL until Task 2 creates the plugin — that's expected.
from src.intelligence.patterns.double_top_bottom import DoubleTBPlugin


def _make_frames(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> dict:
    n = len(close)
    return {"main": pd.DataFrame({
        "open": close,
        "high": high,
        "close": close,
        "low": low,
        "volume": np.ones(n) * 1000,
    })}


def _base(n: int = 80) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Flat arrays at 5000. find_peaks finds no peaks (all equal, no strict inequality)."""
    close = np.full(n, 5000.0)
    high = close + 1.0   # 5001 everywhere
    low = close - 1.0    # 4999 everywhere
    return close.copy(), high.copy(), low.copy()


def _inject_peak(high: np.ndarray, bar: int, peak_price: float, shoulder: float = 5010.0) -> None:
    """Place a clean peak at `bar` with 4 lower neighbors on each side."""
    high[bar] = peak_price
    for i in [bar - 2, bar - 1, bar + 1, bar + 2]:
        if 0 <= i < len(high):
            high[i] = shoulder


def _inject_trough(low: np.ndarray, close: np.ndarray, high: np.ndarray,
                   bar: int, trough_price: float, shoulder: float = 4985.0) -> None:
    """Place a clean trough at `bar`."""
    low[bar] = trough_price
    close[bar] = trough_price + 1.0
    high[bar] = trough_price + 2.0
    for i in [bar - 2, bar - 1, bar + 1, bar + 2]:
        if 0 <= i < len(low):
            low[i] = shoulder
            close[i] = shoulder + 1.0
            high[i] = shoulder + 2.0


class TestDoubleTBInsufficientData:
    def test_returns_empty_when_too_few_bars(self):
        plugin = DoubleTBPlugin()
        close, high, low = _base(50)   # min_lookback is 60
        result = plugin.compute_full(_make_frames(high, low, close))
        assert result == {}


class TestDoubleTBForming:
    def test_two_equal_peaks_above_neckline_is_forming(self):
        """Peaks at bars 20 and 55, neckline trough at bar 37, close above neckline → pattern=1."""
        plugin = DoubleTBPlugin()
        n = 80
        close, high, low = _base(n)

        _inject_peak(high, bar=20, peak_price=5015.0)
        _inject_trough(low, close, high, bar=37, trough_price=4980.0)
        _inject_peak(high, bar=55, peak_price=5015.0)  # same price → within 0.3% tolerance

        # Current close ABOVE neckline 4980
        close[-1] = 4992.0
        high[-1] = 4993.0
        low[-1] = 4991.0

        result = plugin.compute_full(_make_frames(high, low, close))
        assert result["dt_db_pattern"] == 1.0, f"Expected forming(1), got {result}"
        assert result["dt_db_neckline"] == pytest.approx(4980.0, abs=0.5)
        assert 0.0 <= result["dt_db_confidence"] <= 1.0


class TestDoubleTBConfirmed:
    def test_close_below_neckline_confirms_double_top(self):
        """Same setup but close BELOW neckline → pattern=2."""
        plugin = DoubleTBPlugin()
        n = 80
        close, high, low = _base(n)

        _inject_peak(high, bar=20, peak_price=5015.0)
        _inject_trough(low, close, high, bar=37, trough_price=4980.0)
        _inject_peak(high, bar=55, peak_price=5015.0)

        # Close BELOW neckline 4980
        close[-1] = 4970.0
        high[-1] = 4972.0
        low[-1] = 4969.0

        result = plugin.compute_full(_make_frames(high, low, close))
        assert result["dt_db_pattern"] == 2.0
        target = result["dt_db_target"]
        # Measured move: neckline - (peak - neckline) = 4980 - (5015 - 4980) = 4945
        assert target == pytest.approx(4945.0, abs=2.0)


class TestDoubleBottom:
    def test_two_equal_troughs_detected_as_double_bottom(self):
        """Two troughs at same price, neckline peak between them → pattern 3 or 4."""
        plugin = DoubleTBPlugin()
        n = 80
        close, high, low = _base(n)

        # Trough 1 at bar 20
        _inject_trough(low, close, high, bar=20, trough_price=4985.0)
        # Neckline peak at bar 37
        _inject_peak(high, bar=37, peak_price=5010.0)
        # Trough 2 at bar 55 (same price)
        _inject_trough(low, close, high, bar=55, trough_price=4985.0)

        result = plugin.compute_full(_make_frames(high, low, close))
        assert result["dt_db_pattern"] in (3.0, 4.0), f"Expected 3 or 4, got {result}"
        assert result["dt_db_neckline"] == pytest.approx(5010.0, abs=1.0)


class TestNoPattern:
    def test_flat_data_returns_zero_pattern(self):
        """Flat data → find_peaks finds nothing → pattern=0."""
        plugin = DoubleTBPlugin()
        close, high, low = _base(80)
        result = plugin.compute_full(_make_frames(high, low, close))
        # Returns default zeros dict (not empty — data is sufficient)
        assert result.get("dt_db_pattern", 0.0) == 0.0
```

**Step 2: Run test to verify it FAILS (ImportError)**

```bash
.venv/bin/python3 -m pytest tests/unit/test_double_top_bottom.py -v
```

Expected: `ImportError: cannot import name 'DoubleTBPlugin' from 'src.intelligence.patterns.double_top_bottom'` (file doesn't exist yet).

**Step 3: Commit the test file**

```bash
git add tests/unit/test_double_top_bottom.py
git commit -m "test: add failing tests for patt_DoubleTB"
```

---

## Task 2: Implement patt_DoubleTB

**Files:**
- Create: `src/intelligence/patterns/double_top_bottom.py`

**Step 1: Write the implementation**

```python
# src/intelligence/patterns/double_top_bottom.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec
from ..utils import find_peaks, find_troughs


@dataclass
class DoubleTBPlugin:
    name: str = "patt_DoubleTB"
    outputs: set[str] = frozenset({
        "dt_db_pattern",
        "dt_db_neckline",
        "dt_db_target",
        "dt_db_confidence",
    })
    min_lookback: int = 60
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"pattern", "chart"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=120),)
    neighbor: int = 5
    amplitude_thr: float = 0.002
    min_swing_bars: int = 8
    peak_tolerance: float = 0.003
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        close = df["close"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)

        default = {
            "dt_db_pattern": 0.0, "dt_db_neckline": 0.0,
            "dt_db_target": 0.0, "dt_db_confidence": 0.0,
        }

        raw_peaks = find_peaks(high, self.neighbor)
        raw_troughs = find_troughs(low, self.neighbor)
        peaks = self._filter_swings(raw_peaks, high, self.amplitude_thr, self.min_swing_bars, keep_max=True)
        troughs = self._filter_swings(raw_troughs, low, self.amplitude_thr, self.min_swing_bars, keep_max=False)

        current_close = float(close[-1])

        # --- Double Top ---
        if len(peaks) >= 2:
            p1_idx, p2_idx = peaks[-2], peaks[-1]
            p1_price, p2_price = float(high[p1_idx]), float(high[p2_idx])
            peak_avg = (p1_price + p2_price) / 2.0

            if abs(p1_price - p2_price) / peak_avg <= self.peak_tolerance:
                neck_candidates = [t for t in troughs if p1_idx < t < p2_idx]
                if neck_candidates:
                    neck_idx = min(neck_candidates, key=lambda i: low[i])
                    neckline = float(low[neck_idx])
                    pattern = 2.0 if current_close < neckline else 1.0

                    price_sym = 1.0 - abs(p1_price - p2_price) / peak_avg / self.peak_tolerance
                    total_span = p2_idx - p1_idx
                    if total_span > 0:
                        left_span = neck_idx - p1_idx
                        time_sym = 1.0 - abs(left_span / total_span - 0.5) * 2.0
                    else:
                        time_sym = 0.5
                    confidence = round(max(0.0, min(1.0, (price_sym + time_sym) / 2.0)), 4)

                    return {
                        "dt_db_pattern": pattern,
                        "dt_db_neckline": round(neckline, 4),
                        "dt_db_target": round(neckline - (peak_avg - neckline), 4),
                        "dt_db_confidence": confidence,
                    }

        # --- Double Bottom ---
        if len(troughs) >= 2:
            t1_idx, t2_idx = troughs[-2], troughs[-1]
            t1_price, t2_price = float(low[t1_idx]), float(low[t2_idx])
            trough_avg = (t1_price + t2_price) / 2.0

            if abs(t1_price - t2_price) / trough_avg <= self.peak_tolerance:
                neck_candidates = [p for p in peaks if t1_idx < p < t2_idx]
                if neck_candidates:
                    neck_idx = max(neck_candidates, key=lambda i: high[i])
                    neckline = float(high[neck_idx])
                    pattern = 4.0 if current_close > neckline else 3.0

                    price_sym = 1.0 - abs(t1_price - t2_price) / trough_avg / self.peak_tolerance
                    total_span = t2_idx - t1_idx
                    if total_span > 0:
                        left_span = neck_idx - t1_idx
                        time_sym = 1.0 - abs(left_span / total_span - 0.5) * 2.0
                    else:
                        time_sym = 0.5
                    confidence = round(max(0.0, min(1.0, (price_sym + time_sym) / 2.0)), 4)

                    return {
                        "dt_db_pattern": pattern,
                        "dt_db_neckline": round(neckline, 4),
                        "dt_db_target": round(neckline + (neckline - trough_avg), 4),
                        "dt_db_confidence": confidence,
                    }

        return default

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _filter_swings(
        indices: list[int],
        prices: np.ndarray,
        amplitude_thr: float = 0.002,
        min_bars: int = 8,
        keep_max: bool = True,
    ) -> list[int]:
        """Two-stage significance filter: removes noise swings that are too close
        in both price and time. Retains the more extreme swing when merging."""
        if not indices:
            return []
        filtered = [indices[0]]
        for idx in indices[1:]:
            prev_idx = filtered[-1]
            bar_gap = idx - prev_idx
            ref = prices[prev_idx]
            price_diff = abs(prices[idx] - ref) / ref if ref != 0 else 1.0
            if bar_gap >= min_bars or price_diff >= amplitude_thr:
                filtered.append(idx)
            else:
                if keep_max and prices[idx] > prices[prev_idx]:
                    filtered[-1] = idx
                elif not keep_max and prices[idx] < prices[prev_idx]:
                    filtered[-1] = idx
        return filtered


plugin = DoubleTBPlugin()
```

**Step 2: Run tests**

```bash
.venv/bin/python3 -m pytest tests/unit/test_double_top_bottom.py -v
```

Expected: 5 tests PASS.

**Step 3: Commit**

```bash
git add src/intelligence/patterns/double_top_bottom.py
git commit -m "feat: add patt_DoubleTB — double top/bottom pattern plugin with two-stage swing filter"
```

---

## Task 3: Write Failing Tests — patt_HeadShoulders

**Files:**
- Create: `tests/unit/test_head_shoulders.py`

**Step 1: Write the test file**

```python
# tests/unit/test_head_shoulders.py
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.intelligence.patterns.head_shoulders import HeadShouldersPlugin


def _make_frames(high, low, close):
    n = len(close)
    return {"main": pd.DataFrame({
        "open": close, "high": high, "close": close,
        "low": low, "volume": np.ones(n) * 1000,
    })}


def _base(n: int = 100):
    close = np.full(n, 5000.0)
    high = close + 1.0
    low = close - 1.0
    return close.copy(), high.copy(), low.copy()


def _inject_peak(high, bar, peak_price, shoulder=5010.0):
    high[bar] = peak_price
    for i in [bar - 2, bar - 1, bar + 1, bar + 2]:
        if 0 <= i < len(high):
            high[i] = shoulder


def _inject_trough(low, close, high, bar, trough_price, shoulder=4990.0):
    low[bar] = trough_price
    close[bar] = trough_price + 1.0
    high[bar] = trough_price + 2.0
    for i in [bar - 2, bar - 1, bar + 1, bar + 2]:
        if 0 <= i < len(low):
            low[i] = shoulder
            close[i] = shoulder + 1.0
            high[i] = shoulder + 2.0


def _build_hs_data(n=100, confirmed=False):
    """
    Structure:
      Left shoulder peak: bar 15, high=5015
      Left trough:        bar 28, low=4985   ← neckline point 1
      Head peak:          bar 45, high=5190  (> ls * 1.03 = 5165)
      Right trough:       bar 60, low=4987   ← neckline point 2
      Right shoulder:     bar 75, high=5016  (within 5% of 5015)
      Final bar 99: above or below sloped neckline
    """
    close, high, low = _base(n)

    _inject_peak(high, bar=15, peak_price=5015.0)
    _inject_trough(low, close, high, bar=28, trough_price=4985.0)
    _inject_peak(high, bar=45, peak_price=5190.0, shoulder=5160.0)
    _inject_trough(low, close, high, bar=60, trough_price=4987.0)
    _inject_peak(high, bar=75, peak_price=5016.0)

    # Sloped neckline: from (28, 4985) to (60, 4987)
    # slope = (4987 - 4985) / (60 - 28) = 0.0625 per bar
    # neckline at bar 99 = 4985 + 0.0625 * (99 - 28) = 4985 + 4.44 = 4989.44
    if confirmed:
        close[-1] = 4983.0   # well below 4989.44
        low[-1] = 4982.0
        high[-1] = 4984.0
    else:
        close[-1] = 4995.0   # above neckline
        low[-1] = 4994.0
        high[-1] = 4996.0

    return close, high, low


class TestHSInsufficientData:
    def test_returns_empty_when_too_few_bars(self):
        plugin = HeadShouldersPlugin()
        close, high, low = _base(70)  # min_lookback is 80
        result = plugin.compute_full(_make_frames(high, low, close))
        assert result == {}


class TestHSForming:
    def test_valid_hs_above_neckline_is_forming(self):
        plugin = HeadShouldersPlugin()
        close, high, low = _build_hs_data(confirmed=False)
        result = plugin.compute_full(_make_frames(high, low, close))
        assert result["hs_pattern"] == 1.0, f"Expected hs_forming(1), got {result}"
        assert 0.0 <= result["hs_confidence"] <= 1.0
        # Neckline at bar 99 ≈ 4989.44
        assert result["hs_neckline"] == pytest.approx(4989.44, abs=1.0)


class TestHSConfirmed:
    def test_close_below_sloped_neckline_confirms(self):
        plugin = HeadShouldersPlugin()
        close, high, low = _build_hs_data(confirmed=True)
        result = plugin.compute_full(_make_frames(high, low, close))
        assert result["hs_pattern"] == 2.0, f"Expected hs_confirmed(2), got {result}"
        # neckline_distance should be positive (close below neckline)
        assert result["hs_neckline_distance"] > 0.0

    def test_target_is_below_neckline(self):
        plugin = HeadShouldersPlugin()
        close, high, low = _build_hs_data(confirmed=True)
        result = plugin.compute_full(_make_frames(high, low, close))
        if result["hs_pattern"] == 2.0:
            # Target should be well below the neckline (measured move down)
            assert result["hs_target"] < result["hs_neckline"]


class TestInverseHS:
    def test_inverse_hs_detected(self):
        """Mirror: three troughs with lowest in middle → ihs_forming (3) or ihs_confirmed (4)."""
        plugin = HeadShouldersPlugin()
        n = 100
        close, high, low = _base(n)

        # Left shoulder trough at bar 15 (low=4985)
        _inject_trough(low, close, high, bar=15, trough_price=4985.0)
        # Left peak (neckline point 1) at bar 28
        _inject_peak(high, bar=28, peak_price=5015.0)
        # Head trough at bar 45 (must be < 4985 * (1 - 0.03) = 4815.55 → use 4810)
        _inject_trough(low, close, high, bar=45, trough_price=4810.0, shoulder=4850.0)
        # Right peak (neckline point 2) at bar 60
        _inject_peak(high, bar=60, peak_price=5016.0)
        # Right shoulder trough at bar 75 (≈ left shoulder, within 5%)
        _inject_trough(low, close, high, bar=75, trough_price=4986.0)

        result = plugin.compute_full(_make_frames(high, low, close))
        assert result["hs_pattern"] in (3.0, 4.0), f"Expected IHS, got {result}"


class TestNoPattern:
    def test_flat_data_returns_zero_pattern(self):
        plugin = HeadShouldersPlugin()
        close, high, low = _base(100)
        result = plugin.compute_full(_make_frames(high, low, close))
        assert result.get("hs_pattern", 0.0) == 0.0
```

**Step 2: Run test to verify it FAILS (ImportError)**

```bash
.venv/bin/python3 -m pytest tests/unit/test_head_shoulders.py -v
```

Expected: `ImportError` — file doesn't exist yet.

**Step 3: Commit**

```bash
git add tests/unit/test_head_shoulders.py
git commit -m "test: add failing tests for patt_HeadShoulders"
```

---

## Task 4: Implement patt_HeadShoulders

**Files:**
- Create: `src/intelligence/patterns/head_shoulders.py`

**Step 1: Write the implementation**

```python
# src/intelligence/patterns/head_shoulders.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec
from ..utils import find_peaks, find_troughs


@dataclass
class HeadShouldersPlugin:
    name: str = "patt_HeadShoulders"
    outputs: set[str] = frozenset({
        "hs_pattern",
        "hs_neckline",
        "hs_target",
        "hs_confidence",
        "hs_neckline_distance",
    })
    min_lookback: int = 80
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"pattern", "chart"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=120),)
    neighbor: int = 5
    amplitude_thr: float = 0.002
    min_swing_bars: int = 8
    shoulder_sym_pct: float = 0.05
    head_extend_pct: float = 0.03
    atr_period: int = 14
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        close = df["close"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)

        default = {
            "hs_pattern": 0.0, "hs_neckline": 0.0, "hs_target": 0.0,
            "hs_confidence": 0.0, "hs_neckline_distance": 0.0,
        }

        raw_peaks = find_peaks(high, self.neighbor)
        raw_troughs = find_troughs(low, self.neighbor)
        peaks = self._filter_swings(raw_peaks, high, self.amplitude_thr, self.min_swing_bars, keep_max=True)
        troughs = self._filter_swings(raw_troughs, low, self.amplitude_thr, self.min_swing_bars, keep_max=False)

        atr = self._compute_atr(high, low, close, self.atr_period)
        current_close = float(close[-1])
        current_bar = len(close) - 1

        # --- Regular H&S (bearish reversal) ---
        if len(peaks) >= 3:
            ls_idx, h_idx, rs_idx = peaks[-3], peaks[-2], peaks[-1]
            ls_p = float(high[ls_idx])
            h_p = float(high[h_idx])
            rs_p = float(high[rs_idx])

            head_extends = (
                h_p > ls_p * (1.0 + self.head_extend_pct)
                and h_p > rs_p * (1.0 + self.head_extend_pct)
            )
            shoulders_sym = abs(ls_p - rs_p) / max(ls_p, rs_p) <= self.shoulder_sym_pct

            if head_extends and shoulders_sym:
                lt_candidates = [t for t in troughs if ls_idx < t < h_idx]
                rt_candidates = [t for t in troughs if h_idx < t < rs_idx]

                if lt_candidates and rt_candidates:
                    lt_idx = min(lt_candidates, key=lambda i: low[i])
                    rt_idx = min(rt_candidates, key=lambda i: low[i])
                    lt_p = float(low[lt_idx])
                    rt_p = float(low[rt_idx])

                    # Sloped neckline through the two troughs
                    neckline_slope = (rt_p - lt_p) / (rt_idx - lt_idx) if rt_idx != lt_idx else 0.0
                    neckline_at_bar = lt_p + neckline_slope * (current_bar - lt_idx)
                    neckline_at_head = lt_p + neckline_slope * (h_idx - lt_idx)

                    pattern = 2.0 if current_close < neckline_at_bar else 1.0
                    sym_score = 1.0 - abs(ls_p - rs_p) / max(ls_p, rs_p) / self.shoulder_sym_pct
                    confidence = round(max(0.0, min(1.0, sym_score)), 4)
                    target = round(neckline_at_head - (h_p - neckline_at_head), 4)
                    neckline_distance = round(
                        (neckline_at_bar - current_close) / atr if atr > 0 else 0.0, 4
                    )

                    return {
                        "hs_pattern": pattern,
                        "hs_neckline": round(neckline_at_bar, 4),
                        "hs_target": target,
                        "hs_confidence": confidence,
                        "hs_neckline_distance": neckline_distance,
                    }

        # --- Inverse H&S (bullish reversal) ---
        if len(troughs) >= 3:
            ls_idx, h_idx, rs_idx = troughs[-3], troughs[-2], troughs[-1]
            ls_p = float(low[ls_idx])
            h_p = float(low[h_idx])
            rs_p = float(low[rs_idx])

            head_extends = (
                h_p < ls_p * (1.0 - self.head_extend_pct)
                and h_p < rs_p * (1.0 - self.head_extend_pct)
            )
            shoulders_sym = abs(ls_p - rs_p) / max(ls_p, rs_p) <= self.shoulder_sym_pct

            if head_extends and shoulders_sym:
                lt_candidates = [p for p in peaks if ls_idx < p < h_idx]
                rt_candidates = [p for p in peaks if h_idx < p < rs_idx]

                if lt_candidates and rt_candidates:
                    lt_idx = max(lt_candidates, key=lambda i: high[i])
                    rt_idx = max(rt_candidates, key=lambda i: high[i])
                    lt_p = float(high[lt_idx])
                    rt_p = float(high[rt_idx])

                    neckline_slope = (rt_p - lt_p) / (rt_idx - lt_idx) if rt_idx != lt_idx else 0.0
                    neckline_at_bar = lt_p + neckline_slope * (current_bar - lt_idx)
                    neckline_at_head = lt_p + neckline_slope * (h_idx - lt_idx)

                    pattern = 4.0 if current_close > neckline_at_bar else 3.0
                    sym_score = 1.0 - abs(ls_p - rs_p) / max(ls_p, rs_p) / self.shoulder_sym_pct
                    confidence = round(max(0.0, min(1.0, sym_score)), 4)
                    target = round(neckline_at_head + (neckline_at_head - h_p), 4)
                    neckline_distance = round(
                        (current_close - neckline_at_bar) / atr if atr > 0 else 0.0, 4
                    )

                    return {
                        "hs_pattern": pattern,
                        "hs_neckline": round(neckline_at_bar, 4),
                        "hs_target": target,
                        "hs_confidence": confidence,
                        "hs_neckline_distance": neckline_distance,
                    }

        return default

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _filter_swings(
        indices: list[int],
        prices: np.ndarray,
        amplitude_thr: float = 0.002,
        min_bars: int = 8,
        keep_max: bool = True,
    ) -> list[int]:
        if not indices:
            return []
        filtered = [indices[0]]
        for idx in indices[1:]:
            prev_idx = filtered[-1]
            bar_gap = idx - prev_idx
            ref = prices[prev_idx]
            price_diff = abs(prices[idx] - ref) / ref if ref != 0 else 1.0
            if bar_gap >= min_bars or price_diff >= amplitude_thr:
                filtered.append(idx)
            else:
                if keep_max and prices[idx] > prices[prev_idx]:
                    filtered[-1] = idx
                elif not keep_max and prices[idx] < prices[prev_idx]:
                    filtered[-1] = idx
        return filtered

    @staticmethod
    def _compute_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> float:
        n = min(period, len(close) - 1)
        if n < 1:
            return 1.0
        trs = []
        start = max(1, len(close) - n)
        for i in range(start, len(close)):
            tr = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
            trs.append(tr)
        return sum(trs) / len(trs) if trs else 1.0


plugin = HeadShouldersPlugin()
```

**Step 2: Run tests**

```bash
.venv/bin/python3 -m pytest tests/unit/test_head_shoulders.py -v
```

Expected: 5 tests PASS.

**Step 3: Commit**

```bash
git add src/intelligence/patterns/head_shoulders.py
git commit -m "feat: add patt_HeadShoulders — sloped neckline, ATR-normalized breakout distance"
```

---

## Task 5: Write Failing Tests — patt_TriangleWedge

**Files:**
- Create: `tests/unit/test_triangle_wedge.py`

**Step 1: Write the test file**

```python
# tests/unit/test_triangle_wedge.py
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.intelligence.patterns.triangle_wedge import TriangleWedgePlugin


def _make_frames(high, low, close):
    n = len(close)
    return {"main": pd.DataFrame({
        "open": close, "high": high, "close": close,
        "low": low, "volume": np.ones(n) * 1000,
    })}


def _base(n: int = 80):
    close = np.full(n, 5000.0)
    high = close + 1.0
    low = close - 1.0
    return close.copy(), high.copy(), low.copy()


def _inject_peak(high, bar, peak_price, shoulder_price=None):
    high[bar] = peak_price
    sp = shoulder_price if shoulder_price is not None else peak_price - 5.0
    for i in [bar - 2, bar - 1, bar + 1, bar + 2]:
        if 0 <= i < len(high):
            high[i] = sp


def _inject_trough(low, bar, trough_price, shoulder_price=None):
    low[bar] = trough_price
    sp = shoulder_price if shoulder_price is not None else trough_price + 5.0
    for i in [bar - 2, bar - 1, bar + 1, bar + 2]:
        if 0 <= i < len(low):
            low[i] = sp


def _build_ascending_triangle(n=80):
    """
    Ascending triangle: flat top (all peaks ≈ 5020), rising bottom trough sequence.
    Peak bars: 12, 27, 42, 57  — all high=5020 (slope ≈ 0)
    Trough bars: 19, 34, 49, 64 — lows: 4980, 4984, 4988, 4992 (rising)
    """
    close, high, low = _base(n)

    peak_bars = [12, 27, 42, 57]
    for b in peak_bars:
        _inject_peak(high, b, peak_price=5020.0, shoulder_price=5014.0)

    trough_prices = [4980.0, 4984.0, 4988.0, 4992.0]
    trough_bars = [19, 34, 49, 64]
    for b, lp in zip(trough_bars, trough_prices):
        _inject_trough(low, b, trough_price=lp, shoulder_price=lp + 4.0)

    return close, high, low


def _build_descending_triangle(n=80):
    """
    Descending triangle: falling top, flat bottom.
    Peak bars: 12, 27, 42, 57  — highs: 5040, 5034, 5028, 5022 (falling)
    Trough bars: 19, 34, 49, 64 — all low=4980 (slope ≈ 0)
    """
    close, high, low = _base(n)

    peak_prices = [5040.0, 5034.0, 5028.0, 5022.0]
    peak_bars = [12, 27, 42, 57]
    for b, hp in zip(peak_bars, peak_prices):
        _inject_peak(high, b, peak_price=hp, shoulder_price=hp - 5.0)

    trough_bars = [19, 34, 49, 64]
    for b in trough_bars:
        _inject_trough(low, b, trough_price=4980.0, shoulder_price=4985.0)

    return close, high, low


def _build_rising_wedge(n=80):
    """
    Rising wedge: both trendlines slope up, lower line steeper.
    Peaks: 12→5020, 27→5025, 42→5030, 57→5035  (slope +1/bar)
    Troughs: 19→5000, 34→5008, 49→5016, 64→5024  (slope +8/15 ≈ steeper relative to channel)
    """
    close, high, low = _base(n)

    peak_prices = [5020.0, 5025.0, 5030.0, 5035.0]
    peak_bars = [12, 27, 42, 57]
    for b, hp in zip(peak_bars, peak_prices):
        _inject_peak(high, b, peak_price=hp, shoulder_price=hp - 4.0)

    trough_prices = [5000.0, 5008.0, 5016.0, 5024.0]
    trough_bars = [19, 34, 49, 64]
    for b, lp in zip(trough_bars, trough_prices):
        _inject_trough(low, b, trough_price=lp, shoulder_price=lp + 4.0)

    return close, high, low


class TestTriangleWedgeInsufficientData:
    def test_returns_empty_when_too_few_bars(self):
        plugin = TriangleWedgePlugin()
        close, high, low = _base(50)  # min_lookback is 60
        result = plugin.compute_full(_make_frames(high, low, close))
        assert result == {}


class TestAscendingTriangle:
    def test_ascending_triangle_detected(self):
        plugin = TriangleWedgePlugin()
        close, high, low = _build_ascending_triangle()
        result = plugin.compute_full(_make_frames(high, low, close))
        assert result["tri_pattern"] == 1.0, f"Expected ascending(1), got {result}"
        assert result["tri_breakout_bias"] == 1.0
        assert 0.0 <= result["tri_confidence"] <= 1.0

    def test_ascending_triangle_upper_slope_near_zero(self):
        plugin = TriangleWedgePlugin()
        close, high, low = _build_ascending_triangle()
        result = plugin.compute_full(_make_frames(high, low, close))
        if result.get("tri_pattern") == 1.0:
            assert abs(result["tri_upper_slope"]) <= plugin.slope_tolerance * 50


class TestDescendingTriangle:
    def test_descending_triangle_detected(self):
        plugin = TriangleWedgePlugin()
        close, high, low = _build_descending_triangle()
        result = plugin.compute_full(_make_frames(high, low, close))
        assert result["tri_pattern"] == 2.0, f"Expected descending(2), got {result}"
        assert result["tri_breakout_bias"] == -1.0


class TestRisingWedge:
    def test_rising_wedge_detected(self):
        plugin = TriangleWedgePlugin()
        close, high, low = _build_rising_wedge()
        result = plugin.compute_full(_make_frames(high, low, close))
        assert result["tri_pattern"] == 4.0, f"Expected rising_wedge(4), got {result}"
        assert result["tri_breakout_bias"] == -1.0


class TestConfidence:
    def test_confidence_always_in_valid_range(self):
        plugin = TriangleWedgePlugin()
        for builder in [_build_ascending_triangle, _build_descending_triangle, _build_rising_wedge]:
            close, high, low = builder()
            result = plugin.compute_full(_make_frames(high, low, close))
            assert 0.0 <= result.get("tri_confidence", 0.0) <= 1.0
```

**Step 2: Run test to verify it FAILS (ImportError)**

```bash
.venv/bin/python3 -m pytest tests/unit/test_triangle_wedge.py -v
```

Expected: `ImportError` — file doesn't exist yet.

**Step 3: Commit**

```bash
git add tests/unit/test_triangle_wedge.py
git commit -m "test: add failing tests for patt_TriangleWedge"
```

---

## Task 6: Implement patt_TriangleWedge

**Files:**
- Create: `src/intelligence/patterns/triangle_wedge.py`

**Step 1: Write the implementation**

```python
# src/intelligence/patterns/triangle_wedge.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec
from ..utils import find_peaks, find_troughs


@dataclass
class TriangleWedgePlugin:
    name: str = "patt_TriangleWedge"
    outputs: set[str] = frozenset({
        "tri_pattern",
        "tri_upper_slope",
        "tri_lower_slope",
        "tri_apex_bars",
        "tri_breakout_bias",
        "tri_confidence",
    })
    min_lookback: int = 60
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"pattern", "chart"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=120),)
    neighbor: int = 5
    amplitude_thr: float = 0.002
    min_swing_bars: int = 8
    slope_tolerance: float = 0.0001
    min_swing_points: int = 2
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)

        default = {
            "tri_pattern": 0.0, "tri_upper_slope": 0.0, "tri_lower_slope": 0.0,
            "tri_apex_bars": 0.0, "tri_breakout_bias": 0.0, "tri_confidence": 0.0,
        }

        raw_peaks = find_peaks(high, self.neighbor)
        raw_troughs = find_troughs(low, self.neighbor)
        peaks = self._filter_swings(raw_peaks, high, self.amplitude_thr, self.min_swing_bars, keep_max=True)
        troughs = self._filter_swings(raw_troughs, low, self.amplitude_thr, self.min_swing_bars, keep_max=False)

        if len(peaks) < self.min_swing_points or len(troughs) < self.min_swing_points:
            return default

        # Linear regression on upper trendline (peaks) and lower trendline (troughs)
        px = np.array(peaks, dtype=float)
        py = np.array([float(high[i]) for i in peaks], dtype=float)
        slope_h, intercept_h, r2_upper = self._linreg(px, py)

        tx = np.array(troughs, dtype=float)
        ty = np.array([float(low[i]) for i in troughs], dtype=float)
        slope_l, intercept_l, r2_lower = self._linreg(tx, ty)

        tol = self.slope_tolerance
        pattern = 0.0
        bias = 0.0

        if abs(slope_h) <= tol and slope_l > tol:
            pattern, bias = 1.0, 1.0    # ascending triangle → bullish
        elif slope_h < -tol and abs(slope_l) <= tol:
            pattern, bias = 2.0, -1.0   # descending triangle → bearish
        elif slope_h < -tol and slope_l > tol:
            pattern, bias = 3.0, 0.0    # symmetrical triangle → continuation
        elif slope_h > tol and slope_l > tol and slope_l > slope_h:
            pattern, bias = 4.0, -1.0   # rising wedge → bearish
        elif slope_h < -tol and slope_l < -tol and slope_h < slope_l:
            pattern, bias = 5.0, 1.0    # falling wedge → bullish

        if pattern == 0.0:
            return default

        # Apex: bar where upper and lower trendlines converge
        apex_bars = 0.0
        denom = slope_h - slope_l
        if abs(denom) > 1e-10:
            apex_bar = (intercept_l - intercept_h) / denom
            bars_to_apex = apex_bar - float(len(high) - 1)
            apex_bars = round(max(0.0, bars_to_apex), 1)

        # Convergence ratio: how much the channel has tightened
        first_bar = float(min(peaks[0], troughs[0]))
        last_bar = float(len(high) - 1)
        initial_width = (slope_h * first_bar + intercept_h) - (slope_l * first_bar + intercept_l)
        current_width = (slope_h * last_bar + intercept_h) - (slope_l * last_bar + intercept_l)

        convergence = 0.0
        if initial_width > 1e-6:
            convergence = max(0.0, min(1.0, 1.0 - current_width / initial_width))

        r2_combined = (r2_upper * r2_lower) ** 0.5
        confidence = round(convergence * r2_combined, 4)

        return {
            "tri_pattern": pattern,
            "tri_upper_slope": round(slope_h, 6),
            "tri_lower_slope": round(slope_l, 6),
            "tri_apex_bars": apex_bars,
            "tri_breakout_bias": bias,
            "tri_confidence": confidence,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _filter_swings(
        indices: list[int],
        prices: np.ndarray,
        amplitude_thr: float = 0.002,
        min_bars: int = 8,
        keep_max: bool = True,
    ) -> list[int]:
        if not indices:
            return []
        filtered = [indices[0]]
        for idx in indices[1:]:
            prev_idx = filtered[-1]
            bar_gap = idx - prev_idx
            ref = prices[prev_idx]
            price_diff = abs(prices[idx] - ref) / ref if ref != 0 else 1.0
            if bar_gap >= min_bars or price_diff >= amplitude_thr:
                filtered.append(idx)
            else:
                if keep_max and prices[idx] > prices[prev_idx]:
                    filtered[-1] = idx
                elif not keep_max and prices[idx] < prices[prev_idx]:
                    filtered[-1] = idx
        return filtered

    @staticmethod
    def _linreg(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
        """Returns (slope, intercept, r2). Requires len >= 2."""
        n = len(x)
        if n < 2:
            return 0.0, float(y[0]) if n == 1 else 0.0, 0.0
        x_mean, y_mean = x.mean(), y.mean()
        ss_xy = float(((x - x_mean) * (y - y_mean)).sum())
        ss_xx = float(((x - x_mean) ** 2).sum())
        if ss_xx < 1e-10:
            return 0.0, y_mean, 1.0
        slope = ss_xy / ss_xx
        intercept = y_mean - slope * x_mean
        y_pred = slope * x + intercept
        ss_res = float(((y - y_pred) ** 2).sum())
        ss_tot = float(((y - y_mean) ** 2).sum())
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-10 else 1.0
        return slope, intercept, max(0.0, min(1.0, r2))


plugin = TriangleWedgePlugin()
```

**Step 2: Run tests**

```bash
.venv/bin/python3 -m pytest tests/unit/test_triangle_wedge.py -v
```

Expected: 6 tests PASS.

**Step 3: Commit**

```bash
git add src/intelligence/patterns/triangle_wedge.py
git commit -m "feat: add patt_TriangleWedge — convergence ratio + R² confidence, 5 pattern types"
```

---

## Task 7: Register All Three Plugins

**Files:**
- Modify: `src/intelligence/register_plugins.py`

**Step 1: Add imports** (after the existing `.patterns.*` imports, before `.plugins import registry`):

```python
from .patterns.double_top_bottom import plugin as double_tb_plugin
from .patterns.head_shoulders import plugin as head_shoulders_plugin
from .patterns.triangle_wedge import plugin as triangle_wedge_plugin
```

**Step 2: Add registrations** (inside `register_all_plugins()`, after existing pattern registrations, before the `# I7 Trading Setups` comment):

```python
    # I5 Chart Patterns
    registry.register_pattern(double_tb_plugin)
    registry.register_pattern(head_shoulders_plugin)
    registry.register_pattern(triangle_wedge_plugin)
```

**Step 3: Run the full test suite**

```bash
.venv/bin/python3 -m pytest tests/unit/ -q
```

Expected: All prior 366 tests pass PLUS the 15 new tests = **381 total, 0 failures**.

**Step 4: Run lint**

```bash
.venv/bin/ruff check src/intelligence/patterns/double_top_bottom.py src/intelligence/patterns/head_shoulders.py src/intelligence/patterns/triangle_wedge.py --fix
```

Expected: No errors.

**Step 5: Commit**

```bash
git add src/intelligence/register_plugins.py
git commit -m "feat: register patt_DoubleTB, patt_HeadShoulders, patt_TriangleWedge (45 plugins, 381 tests)"
```

---

## Task 8: Update Docs and CLAUDE.md

**Files:**
- Modify: `docs/for-ai-assistants/CLAUDE.md` (update plugin count from 42 → 45, test count 366 → 381)
- Commit plan doc: `docs/plans/2026-02-19-chart-pattern-detection.md`

**Step 1: Update CLAUDE.md header line**

Find and replace:
```
Status: I1-I8 pipeline complete — 42 plugins + ...366 tests
```
With:
```
Status: I1-I8 pipeline complete — 45 plugins + ...381 tests
```

Also update the version to `4.6.0` and date to `2026-02-19`.

**Step 2: Commit everything**

```bash
git add docs/for-ai-assistants/CLAUDE.md docs/plans/2026-02-19-chart-pattern-detection.md
git commit -m "docs: update CLAUDE.md v4.6.0 — chart pattern plugins added (45 plugins, 381 tests)"
```

---

## Completion Checklist

- [ ] `tests/unit/test_double_top_bottom.py` — 5 tests passing
- [ ] `src/intelligence/patterns/double_top_bottom.py` — DoubleTBPlugin, `patt_DoubleTB`
- [ ] `tests/unit/test_head_shoulders.py` — 5 tests passing
- [ ] `src/intelligence/patterns/head_shoulders.py` — HeadShouldersPlugin, `patt_HeadShoulders`
- [ ] `tests/unit/test_triangle_wedge.py` — 6 tests passing
- [ ] `src/intelligence/patterns/triangle_wedge.py` — TriangleWedgePlugin, `patt_TriangleWedge`
- [ ] `src/intelligence/register_plugins.py` — 3 new `register_pattern(...)` calls
- [ ] Full suite: 381 tests, 0 failures
- [ ] Lint: 0 ruff errors
- [ ] CLAUDE.md updated to v4.6.0

## Gotchas

- `find_peaks` operates on `high` array; `find_troughs` on `low` array — not on `close`
- `_filter_swings` is duplicated in all 3 plugins (not a shared import) — keeps plugins self-contained per project convention
- ATR in HeadShoulders is computed inline, does not read from I1 ATR plugin output
- Return `{}` for insufficient data; return zeros-default-dict for sufficient data with no pattern found
- All numeric outputs use `round(..., 4)`
- `inputs` tuple needs the trailing comma: `inputs: list[InputSpec] = (InputSpec(...),)` ← don't miss the comma
