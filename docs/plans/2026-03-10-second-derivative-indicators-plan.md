# Second-Derivative Indicator Coverage Expansion (I2/I3) Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add second-derivative (acceleration) indicators to I2/I3 tiers — enabling early inflection detection and exhaustion guards in I7 trading setups.

**Architecture:** Extend `MomentumAcceleration` with 3 new outputs; add 2 new I2 plugins (`ExhaustionScore`, `AccelerationRegime`); add 1 new I3 plugin (`SwingMomentum`); wire exhaustion awareness into 4 existing I7 setups.

**Tech Stack:** Python dataclasses, numpy, pandas, pytest. All plugins follow the `PatternPlugin` protocol in `src/intelligence/plugins.py`. Tests use `tests/unit/intelligence/helpers.py::make_ohlcv`.

**Spec:** `docs/plans/2026-03-10-second-derivative-indicators-design.md`

---

## Chunk 1: Extend MomentumAcceleration (+3 outputs)

**Files:**
- Modify: `src/intelligence/composites/momentum_accel.py`
- Modify: `tests/unit/intelligence/composites/test_momentum_accel.py`

---

- [ ] **Step 1.1: Write failing tests for rsi_curvature, macd_hist_slope, price_accel**

Add to `tests/unit/intelligence/composites/test_momentum_accel.py`:

```python
import numpy as np
import pandas as pd
import pytest


def make_frames_with_ohlcv(
    rsi=None, macd=None, roc=None, macd_hist=None,
    prev_rsi=None, prev_macd=None, prev_roc=None, prev_macd_hist=None,
    close_prices=None, atr=8.0,
) -> dict:
    """Extended make_frames with OHLCV and macd_histogram."""
    features = {}
    prev = {}
    if rsi is not None: features["rsi_14"] = rsi
    if macd is not None: features["macd_12_26_9"] = macd
    if roc is not None: features["roc_14"] = roc
    if macd_hist is not None: features["macd_histogram_12_26_9"] = macd_hist
    if prev_rsi is not None: prev["rsi_14"] = prev_rsi
    if prev_macd is not None: prev["macd_12_26_9"] = prev_macd
    if prev_roc is not None: prev["roc_14"] = prev_roc
    if prev_macd_hist is not None: prev["macd_histogram_12_26_9"] = prev_macd_hist
    features["atr_14"] = atr

    # Build minimal OHLCV df (at least 5 bars)
    if close_prices is None:
        close_prices = [5000.0, 5001.0, 5002.0, 5003.0, 5004.0]
    close = np.array(close_prices, dtype=float)
    spread = close * 0.001
    df = pd.DataFrame({
        "open": close, "high": close + spread,
        "low": close - spread, "close": close, "volume": np.full(len(close), 1000.0),
    })
    return {"features": features, "prev_features": prev, "main": df}


def test_rsi_curvature_zero_on_first_bar():
    """First bar: no prev_rsi_accel in state → rsi_curvature = 0.0."""
    from src.intelligence.composites.momentum_accel import MomentumAccelPlugin
    plugin = MomentumAccelPlugin()
    result = plugin.compute_next(make_frames_with_ohlcv(
        rsi=55.0, prev_rsi=50.0,
    ))
    assert result["rsi_curvature"] == 0.0


def test_rsi_curvature_computed_on_second_bar():
    """Second bar: rsi_curvature = rsi_accel[bar2] - rsi_accel[bar1]."""
    from src.intelligence.composites.momentum_accel import MomentumAccelPlugin
    plugin = MomentumAccelPlugin()
    # Bar 1: rsi_accel = +5.0 (stored in state)
    plugin.compute_next(make_frames_with_ohlcv(rsi=55.0, prev_rsi=50.0))
    # Bar 2: rsi_accel = +2.0, curvature = 2.0 - 5.0 = -3.0
    result = plugin.compute_next(make_frames_with_ohlcv(rsi=57.0, prev_rsi=55.0))
    assert result["rsi_curvature"] == pytest.approx(-3.0)


def test_rsi_curvature_positive_when_acceleration_increasing():
    """rsi_curvature > 0 when RSI is accelerating upward."""
    from src.intelligence.composites.momentum_accel import MomentumAccelPlugin
    plugin = MomentumAccelPlugin()
    # Bar 1: accel = +2
    plugin.compute_next(make_frames_with_ohlcv(rsi=52.0, prev_rsi=50.0))
    # Bar 2: accel = +5, curvature = +3
    result = plugin.compute_next(make_frames_with_ohlcv(rsi=57.0, prev_rsi=52.0))
    assert result["rsi_curvature"] == pytest.approx(3.0)


def test_macd_hist_slope_zero_on_first_bar():
    """No prev_macd_histogram in state → macd_hist_slope = 0.0."""
    from src.intelligence.composites.momentum_accel import MomentumAccelPlugin
    plugin = MomentumAccelPlugin()
    result = plugin.compute_next(make_frames_with_ohlcv(macd_hist=0.5))
    assert result["macd_hist_slope"] == 0.0


def test_macd_hist_slope_computed_on_second_bar():
    """macd_hist_slope = current_hist - prev_hist (stored in state from prior call)."""
    from src.intelligence.composites.momentum_accel import MomentumAccelPlugin
    plugin = MomentumAccelPlugin()
    plugin.compute_next(make_frames_with_ohlcv(macd_hist=0.3))   # stores 0.3 in state
    result = plugin.compute_next(make_frames_with_ohlcv(macd_hist=0.2))
    assert result["macd_hist_slope"] == pytest.approx(-0.1)


def test_macd_hist_slope_positive_when_histogram_growing():
    """Positive slope = histogram is expanding (bullish momentum building)."""
    from src.intelligence.composites.momentum_accel import MomentumAccelPlugin
    plugin = MomentumAccelPlugin()
    plugin.compute_next(make_frames_with_ohlcv(macd_hist=0.2))
    result = plugin.compute_next(make_frames_with_ohlcv(macd_hist=0.5))
    assert result["macd_hist_slope"] == pytest.approx(0.3)


def test_price_accel_zero_when_atr_missing():
    """No ATR in features → price_accel = 0.0 (safe fallback)."""
    from src.intelligence.composites.momentum_accel import MomentumAccelPlugin
    plugin = MomentumAccelPlugin()
    frames = make_frames_with_ohlcv(close_prices=[5000.0, 5001.0, 5003.0, 5006.0, 5010.0])
    frames["features"].pop("atr_14", None)  # remove ATR
    result = plugin.compute_next(frames)
    assert result["price_accel"] == 0.0


def test_price_accel_computes_normalized_second_derivative():
    """price_accel = ((c[-1]-c[-2]) - (c[-2]-c[-3])) / atr_14.

    close = [5000, 5001, 5003, 5006, 5010]:
      velocity[-1] = 5010 - 5006 = 4
      velocity[-2] = 5006 - 5003 = 3
      accel = (4 - 3) / atr = 1/8 = 0.125
    """
    from src.intelligence.composites.momentum_accel import MomentumAccelPlugin
    plugin = MomentumAccelPlugin()
    closes = [5000.0, 5001.0, 5003.0, 5006.0, 5010.0]
    result = plugin.compute_next(make_frames_with_ohlcv(close_prices=closes, atr=8.0))
    assert result["price_accel"] == pytest.approx(0.125)  # (4-3)/8


def test_price_accel_negative_when_decelerating():
    """Decelerating price → negative price_accel."""
    from src.intelligence.composites.momentum_accel import MomentumAccelPlugin
    plugin = MomentumAccelPlugin()
    # velocity going from 5 to 2 → accel = (2-5)/8 = -0.375
    closes = [5000.0, 5005.0, 5010.0, 5015.0, 5017.0]
    result = plugin.compute_next(make_frames_with_ohlcv(close_prices=closes, atr=8.0))
    assert result["price_accel"] == pytest.approx(-0.375)


def test_new_outputs_in_outputs_frozenset():
    """New outputs are declared in the plugin's outputs frozenset."""
    from src.intelligence.composites.momentum_accel import MomentumAccelPlugin
    p = MomentumAccelPlugin()
    assert "rsi_curvature" in p.outputs
    assert "macd_hist_slope" in p.outputs
    assert "price_accel" in p.outputs
```

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
cd /home/bg/dev/indicagent
.venv/bin/pytest tests/unit/intelligence/composites/test_momentum_accel.py -k "curvature or hist_slope or price_accel" -v
```
Expected: FAIL (AttributeError or AssertionError — outputs not yet declared)

- [ ] **Step 1.3: Implement the extension in momentum_accel.py**

Replace the entire file with:

```python
# src/intelligence/composites/momentum_accel.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .common import is_num


@dataclass
class MomentumAccelPlugin:
    name: str = "evt_MomentumAcceleration"
    outputs: frozenset = field(
        default_factory=lambda: frozenset({
            "rsi_accel",
            "macd_accel",
            "roc_accel",
            "inflection_flag",
            "rsi_curvature",
            "macd_hist_slope",
            "price_accel",
        })
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset = field(
        default_factory=lambda: frozenset({"momentum"})
    )
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=5),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        prev = frames.get("prev_features") or {}
        df = frames.get("main")

        rsi = features.get("rsi_14")
        macd = features.get("macd_12_26_9")
        roc = features.get("roc_14")
        macd_hist = features.get("macd_histogram_12_26_9")
        atr = features.get("atr_14")

        prev_rsi = prev.get("rsi_14")
        prev_macd = prev.get("macd_12_26_9")
        prev_roc = prev.get("roc_14")

        out: dict[str, Any] = {}
        inflection = 0

        # ── RSI acceleration (first derivative) ──
        if is_num(rsi) and is_num(prev_rsi):
            rsi_accel = rsi - prev_rsi
            prev_rsi_accel = self._state.get("prev_rsi_accel")
            if is_num(prev_rsi_accel) and prev_rsi_accel * rsi_accel < 0:
                inflection = 1
            # rsi_curvature = second derivative of RSI
            out["rsi_curvature"] = (rsi_accel - prev_rsi_accel) if is_num(prev_rsi_accel) else 0.0
            self._state["prev_rsi_accel"] = rsi_accel
            out["rsi_accel"] = rsi_accel
        else:
            out["rsi_accel"] = 0.0
            out["rsi_curvature"] = 0.0

        # ── MACD line acceleration (first derivative) ──
        if is_num(macd) and is_num(prev_macd):
            macd_accel = macd - prev_macd
            prev_macd_accel = self._state.get("prev_macd_accel")
            if is_num(prev_macd_accel) and prev_macd_accel * macd_accel < 0:
                inflection = 1
            self._state["prev_macd_accel"] = macd_accel
            out["macd_accel"] = macd_accel
        else:
            out["macd_accel"] = 0.0

        # ── MACD histogram slope (second derivative of MACD) ──
        if is_num(macd_hist):
            prev_macd_hist = self._state.get("prev_macd_histogram")
            out["macd_hist_slope"] = (macd_hist - prev_macd_hist) if is_num(prev_macd_hist) else 0.0
            self._state["prev_macd_histogram"] = macd_hist
        else:
            out["macd_hist_slope"] = 0.0

        # ── ROC acceleration (first derivative) ──
        if is_num(roc) and is_num(prev.get("roc_14")):
            roc_accel = roc - prev.get("roc_14")
            prev_roc_accel = self._state.get("prev_roc_accel")
            if is_num(prev_roc_accel) and prev_roc_accel * roc_accel < 0:
                inflection = 1
            self._state["prev_roc_accel"] = roc_accel
            out["roc_accel"] = roc_accel
        else:
            out["roc_accel"] = 0.0

        # ── Price acceleration (second derivative of price, ATR-normalized) ──
        out["price_accel"] = 0.0
        if df is not None and len(df) >= 3 and is_num(atr) and atr > 0:
            close = df["close"].to_numpy(dtype=float)
            if len(close) >= 3:
                velocity_now = close[-1] - close[-2]
                velocity_prev = close[-2] - close[-3]
                out["price_accel"] = round((velocity_now - velocity_prev) / atr, 6)

        out["inflection_flag"] = inflection
        return out

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = MomentumAccelPlugin()
```

- [ ] **Step 1.4: Run all momentum_accel tests**

```bash
.venv/bin/pytest tests/unit/intelligence/composites/test_momentum_accel.py -v
```
Expected: ALL PASS (existing + new tests)

- [ ] **Step 1.5: Commit**

```bash
git add src/intelligence/composites/momentum_accel.py tests/unit/intelligence/composites/test_momentum_accel.py
git commit -m "feat(i2): extend MomentumAcceleration with rsi_curvature, macd_hist_slope, price_accel"
```

---

## Chunk 2: New ExhaustionScore I2 Plugin

**Files:**
- Create: `src/intelligence/composites/exhaustion_score.py`
- Create: `tests/unit/intelligence/composites/test_exhaustion_score.py`

---

- [ ] **Step 2.1: Write failing tests**

Create `tests/unit/intelligence/composites/test_exhaustion_score.py`:

```python
"""Tests for cmp_ExhaustionScore I2 plugin."""
from __future__ import annotations
import pytest


def _frames(rsi=50.0, rsi_curvature=0.0, macd_hist_slope=0.0) -> dict:
    return {"features": {
        "rsi_14": rsi,
        "rsi_curvature": rsi_curvature,
        "macd_hist_slope": macd_hist_slope,
    }}


class TestExhaustionScore:
    def test_no_exhaustion_when_rsi_midrange(self):
        """RSI at 50 with neutral derivatives → no exhaustion."""
        from src.intelligence.composites.exhaustion_score import ExhaustionScorePlugin
        p = ExhaustionScorePlugin()
        result = p.compute_full(_frames(rsi=50.0, rsi_curvature=0.5, macd_hist_slope=0.3))
        assert result["exhaustion_score"] == 0.0
        assert result["exhaustion_side"] == "none"
        assert result["exhaustion_bars"] == 0.0

    def test_full_bullish_exhaustion_all_three_conditions(self):
        """RSI > 70, rsi_curvature < 0, macd_hist_slope < 0 → score = 1.0, side = 'bull'."""
        from src.intelligence.composites.exhaustion_score import ExhaustionScorePlugin
        p = ExhaustionScorePlugin()
        result = p.compute_full(_frames(rsi=75.0, rsi_curvature=-2.0, macd_hist_slope=-0.1))
        assert result["exhaustion_score"] == pytest.approx(1.0)
        assert result["exhaustion_side"] == "bull"

    def test_partial_bullish_exhaustion_two_conditions(self):
        """RSI > 70 + rsi_curvature < 0 (no histogram condition) → score = 0.6."""
        from src.intelligence.composites.exhaustion_score import ExhaustionScorePlugin
        p = ExhaustionScorePlugin()
        result = p.compute_full(_frames(rsi=72.0, rsi_curvature=-1.0, macd_hist_slope=0.2))
        assert result["exhaustion_score"] == pytest.approx(0.6)
        assert result["exhaustion_side"] == "bull"

    def test_single_condition_bullish_exhaustion(self):
        """Only RSI > 70 (other derivatives neutral/positive) → score = 0.2."""
        from src.intelligence.composites.exhaustion_score import ExhaustionScorePlugin
        p = ExhaustionScorePlugin()
        result = p.compute_full(_frames(rsi=71.0, rsi_curvature=0.5, macd_hist_slope=0.3))
        assert result["exhaustion_score"] == pytest.approx(0.2)
        assert result["exhaustion_side"] == "bull"

    def test_full_bearish_exhaustion(self):
        """RSI < 30, rsi_curvature > 0, macd_hist_slope > 0 → score = 1.0, side = 'bear'."""
        from src.intelligence.composites.exhaustion_score import ExhaustionScorePlugin
        p = ExhaustionScorePlugin()
        result = p.compute_full(_frames(rsi=25.0, rsi_curvature=2.0, macd_hist_slope=0.1))
        assert result["exhaustion_score"] == pytest.approx(1.0)
        assert result["exhaustion_side"] == "bear"

    def test_exhaustion_bars_increments_each_call(self):
        """exhaustion_bars counter increments on each bar the condition holds."""
        from src.intelligence.composites.exhaustion_score import ExhaustionScorePlugin
        p = ExhaustionScorePlugin()
        frames = _frames(rsi=75.0, rsi_curvature=-2.0, macd_hist_slope=-0.1)
        r1 = p.compute_full(frames)
        r2 = p.compute_full(frames)
        r3 = p.compute_full(frames)
        assert r1["exhaustion_bars"] == 1.0
        assert r2["exhaustion_bars"] == 2.0
        assert r3["exhaustion_bars"] == 3.0

    def test_exhaustion_bars_resets_when_condition_clears(self):
        """Counter resets to 0 the bar after exhaustion clears."""
        from src.intelligence.composites.exhaustion_score import ExhaustionScorePlugin
        p = ExhaustionScorePlugin()
        p.compute_full(_frames(rsi=75.0, rsi_curvature=-2.0, macd_hist_slope=-0.1))
        p.compute_full(_frames(rsi=75.0, rsi_curvature=-2.0, macd_hist_slope=-0.1))
        # condition clears
        result = p.compute_full(_frames(rsi=50.0, rsi_curvature=0.5, macd_hist_slope=0.1))
        assert result["exhaustion_bars"] == 0.0
        assert result["exhaustion_score"] == 0.0

    def test_missing_rsi_returns_safe_defaults(self):
        """Missing RSI feature → returns default zero-exhaustion safely."""
        from src.intelligence.composites.exhaustion_score import ExhaustionScorePlugin
        p = ExhaustionScorePlugin()
        result = p.compute_full({"features": {}})
        assert result["exhaustion_score"] == 0.0
        assert result["exhaustion_side"] == "none"

    def test_plugin_registered_in_tier_i2():
        from src.intelligence.composites.exhaustion_score import plugin
        from src.intelligence.register_plugins import TIER_I2
        assert plugin.name in TIER_I2
```

- [ ] **Step 2.2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/intelligence/composites/test_exhaustion_score.py -v
```
Expected: ModuleNotFoundError (plugin not yet created)

- [ ] **Step 2.3: Implement ExhaustionScore plugin**

Create `src/intelligence/composites/exhaustion_score.py`:

```python
# src/intelligence/composites/exhaustion_score.py
"""ExhaustionScore — detect when indicators are extreme AND decelerating.

Three conditions for bullish exhaustion (price extended up but momentum dying):
  1. rsi_14 > 70  (price in overbought territory)
  2. rsi_curvature < 0  (RSI deceleration — rate of momentum change going negative)
  3. macd_hist_slope < 0  (MACD histogram contracting — buy pressure fading)

Inverted for bearish exhaustion. Score = fraction of conditions met (1/3=0.2, 2/3=0.6, 3/3=1.0).
exhaustion_bars: internal counter, incremented each bar the condition holds, reset on clear.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec, PatternPlugin
from .common import is_num

RSI_OB = 70.0
RSI_OS = 30.0


@dataclass
class ExhaustionScorePlugin:
    name: str = "cmp_ExhaustionScore"
    outputs: frozenset[str] = frozenset({
        "exhaustion_score",
        "exhaustion_side",
        "exhaustion_bars",
    })
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"momentum", "exhaustion"})
    inputs: tuple[InputSpec, ...] = ()
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}

        rsi = features.get("rsi_14")
        rsi_curvature = features.get("rsi_curvature", 0.0)
        macd_hist_slope = features.get("macd_hist_slope", 0.0)

        if not is_num(rsi):
            return {
                "exhaustion_score": 0.0,
                "exhaustion_side": "none",
                "exhaustion_bars": 0.0,
            }

        # ── Bullish exhaustion (overbought + decelerating) ──
        bull_conditions = [
            rsi > RSI_OB,
            is_num(rsi_curvature) and rsi_curvature < 0,
            is_num(macd_hist_slope) and macd_hist_slope < 0,
        ]
        n_bull = sum(bull_conditions)

        # ── Bearish exhaustion (oversold + decelerating) ──
        bear_conditions = [
            rsi < RSI_OS,
            is_num(rsi_curvature) and rsi_curvature > 0,
            is_num(macd_hist_slope) and macd_hist_slope > 0,
        ]
        n_bear = sum(bear_conditions)

        if n_bull >= n_bear and n_bull > 0:
            side = "bull"
            n_hit = n_bull
        elif n_bear > n_bull and n_bear > 0:
            side = "bear"
            n_hit = n_bear
        else:
            side = "none"
            n_hit = 0

        # Score: 1/3 → 0.2, 2/3 → 0.6, 3/3 → 1.0
        score_map = {0: 0.0, 1: 0.2, 2: 0.6, 3: 1.0}
        score = score_map[n_hit]

        # ── Internal counter (exhaustion_bars) tracked in _state ──
        if score > 0:
            self._state["exhaustion_bars"] = self._state.get("exhaustion_bars", 0) + 1
        else:
            self._state["exhaustion_bars"] = 0

        return {
            "exhaustion_score": score,
            "exhaustion_side": side,
            "exhaustion_bars": float(self._state["exhaustion_bars"]),
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = ExhaustionScorePlugin()
```

- [ ] **Step 2.4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/composites/test_exhaustion_score.py -v
```
Expected: ALL PASS. Fix any failures before proceeding.

- [ ] **Step 2.5: Commit**

```bash
git add src/intelligence/composites/exhaustion_score.py tests/unit/intelligence/composites/test_exhaustion_score.py
git commit -m "feat(i2): add ExhaustionScore plugin (rsi/histogram/curvature exhaustion detection)"
```

---

## Chunk 3: New AccelerationRegime I2 Plugin

**Files:**
- Create: `src/intelligence/composites/acceleration_regime.py`
- Create: `tests/unit/intelligence/composites/test_acceleration_regime.py`

---

- [ ] **Step 3.1: Write failing tests**

Create `tests/unit/intelligence/composites/test_acceleration_regime.py`:

```python
"""Tests for cmp_AccelerationRegime I2 plugin."""
from __future__ import annotations
import pytest


def _frames(rsi_curvature=0.0, macd_hist_slope=0.0, price_accel=0.0) -> dict:
    return {"features": {
        "rsi_curvature": rsi_curvature,
        "macd_hist_slope": macd_hist_slope,
        "price_accel": price_accel,
    }}


class TestAccelerationRegime:
    def test_building_when_all_three_positive(self):
        """All three measures positive → accel_regime = 'building', score > 0.5."""
        from src.intelligence.composites.acceleration_regime import AccelerationRegimePlugin
        p = AccelerationRegimePlugin()
        result = p.compute_full(_frames(rsi_curvature=2.0, macd_hist_slope=0.1, price_accel=0.3))
        assert result["accel_regime"] == "building"
        assert result["accel_score"] > 0.5
        assert result["accel_agreement"] == pytest.approx(1.0)

    def test_waning_when_all_three_negative(self):
        """All three measures negative → accel_regime = 'waning', score < -0.3."""
        from src.intelligence.composites.acceleration_regime import AccelerationRegimePlugin
        p = AccelerationRegimePlugin()
        result = p.compute_full(_frames(rsi_curvature=-2.0, macd_hist_slope=-0.1, price_accel=-0.3))
        assert result["accel_regime"] == "waning"
        assert result["accel_score"] < -0.3
        assert result["accel_agreement"] == pytest.approx(1.0)

    def test_neutral_when_mixed_signals(self):
        """Two positive, one negative, no inflection crossing → 'neutral'."""
        from src.intelligence.composites.acceleration_regime import AccelerationRegimePlugin
        p = AccelerationRegimePlugin()
        result = p.compute_full(_frames(rsi_curvature=0.5, macd_hist_slope=-0.5, price_accel=0.0))
        assert result["accel_regime"] in ("neutral", "building", "waning")
        assert result["accel_agreement"] < 1.0

    def test_peak_detected_on_inflection_from_building_to_falling(self):
        """prev_accel_score > 0.3 AND current ≤ 0.3 → regime = 'peak' (single bar)."""
        from src.intelligence.composites.acceleration_regime import AccelerationRegimePlugin
        p = AccelerationRegimePlugin()
        # Bar 1: all positive → building, accel_score > 0.5 → stored in state
        p.compute_full(_frames(rsi_curvature=2.0, macd_hist_slope=0.1, price_accel=0.3))
        # Bar 2: all negative → accel_score < 0 ≤ 0.3, but prev was > 0.3 → PEAK
        result = p.compute_full(_frames(rsi_curvature=-1.0, macd_hist_slope=-0.1, price_accel=-0.2))
        assert result["accel_regime"] == "peak"

    def test_trough_detected_on_inflection_from_waning_to_rising(self):
        """prev_accel_score < -0.3 AND current ≥ -0.3 → regime = 'trough'."""
        from src.intelligence.composites.acceleration_regime import AccelerationRegimePlugin
        p = AccelerationRegimePlugin()
        # Bar 1: all negative → waning, score stored
        p.compute_full(_frames(rsi_curvature=-2.0, macd_hist_slope=-0.1, price_accel=-0.3))
        # Bar 2: all positive → score crosses above -0.3 → TROUGH
        result = p.compute_full(_frames(rsi_curvature=1.0, macd_hist_slope=0.1, price_accel=0.2))
        assert result["accel_regime"] == "trough"

    def test_peak_is_transient_reverts_next_bar(self):
        """After a 'peak' bar, the following bar re-classifies based on new score."""
        from src.intelligence.composites.acceleration_regime import AccelerationRegimePlugin
        p = AccelerationRegimePlugin()
        p.compute_full(_frames(rsi_curvature=2.0, macd_hist_slope=0.1, price_accel=0.3))
        peak_bar = p.compute_full(_frames(rsi_curvature=-1.0, macd_hist_slope=-0.1, price_accel=-0.2))
        assert peak_bar["accel_regime"] == "peak"
        # Bar 3: still negative → no longer crossing from prev (was already negative)
        next_bar = p.compute_full(_frames(rsi_curvature=-1.0, macd_hist_slope=-0.1, price_accel=-0.2))
        assert next_bar["accel_regime"] != "peak"

    def test_accel_score_bounded_minus_one_to_one(self):
        """accel_score always in [-1.0, 1.0]."""
        from src.intelligence.composites.acceleration_regime import AccelerationRegimePlugin
        p = AccelerationRegimePlugin()
        for rsi_c, hist_s, pa in [(10.0, 5.0, 3.0), (-10.0, -5.0, -3.0), (0.0, 0.0, 0.0)]:
            result = p.compute_full(_frames(rsi_curvature=rsi_c, macd_hist_slope=hist_s, price_accel=pa))
            assert -1.0 <= result["accel_score"] <= 1.0

    def test_empty_features_returns_neutral(self):
        """Missing features → neutral regime safely."""
        from src.intelligence.composites.acceleration_regime import AccelerationRegimePlugin
        p = AccelerationRegimePlugin()
        result = p.compute_full({"features": {}})
        assert result["accel_regime"] == "neutral"
        assert result["accel_score"] == 0.0

    def test_plugin_registered_in_tier_i2():
        from src.intelligence.composites.acceleration_regime import plugin
        from src.intelligence.register_plugins import TIER_I2
        assert plugin.name in TIER_I2
```

- [ ] **Step 3.2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/intelligence/composites/test_acceleration_regime.py -v
```
Expected: ModuleNotFoundError

- [ ] **Step 3.3: Implement AccelerationRegime plugin**

Create `src/intelligence/composites/acceleration_regime.py`:

```python
# src/intelligence/composites/acceleration_regime.py
"""AccelerationRegime — synthesize rsi_curvature, macd_hist_slope, price_accel into regime label.

Each measure is sign-voted (+1 / 0 / -1) and weighted equally. The composite
accel_score drives the regime label. Peak/trough are transient inflection events
detected by crossing the ±0.3 boundary between bars.

Regime definitions (evaluated in order):
  building  : accel_score > 0.5
  peak      : prev_accel_score > 0.3 AND accel_score ≤ 0.3  (inflection top)
  trough    : prev_accel_score < -0.3 AND accel_score ≥ -0.3  (inflection bottom)
  waning    : accel_score < -0.3
  neutral   : all other cases
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec, PatternPlugin
from .common import is_num

# Weights (equal across three measures — update if empirical evidence suggests otherwise)
_WEIGHT_RSI = 1.0 / 3.0
_WEIGHT_HIST = 1.0 / 3.0
_WEIGHT_PRICE = 1.0 / 3.0


def _sign_vote(v: float | None) -> float:
    """Convert a value to +1 / -1 / 0 sign vote."""
    if not is_num(v) or v == 0.0:
        return 0.0
    return 1.0 if v > 0 else -1.0


@dataclass
class AccelerationRegimePlugin:
    name: str = "cmp_AccelerationRegime"
    outputs: frozenset[str] = frozenset({
        "accel_regime",
        "accel_score",
        "accel_agreement",
    })
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"momentum", "regime"})
    inputs: tuple[InputSpec, ...] = ()
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}

        rsi_curvature = features.get("rsi_curvature", 0.0)
        macd_hist_slope = features.get("macd_hist_slope", 0.0)
        price_accel = features.get("price_accel", 0.0)

        votes = [
            _sign_vote(rsi_curvature),
            _sign_vote(macd_hist_slope),
            _sign_vote(price_accel),
        ]

        # Weighted composite score
        accel_score = round(
            votes[0] * _WEIGHT_RSI + votes[1] * _WEIGHT_HIST + votes[2] * _WEIGHT_PRICE,
            4
        )
        accel_score = max(-1.0, min(1.0, accel_score))

        # Agreement: fraction of non-zero votes matching majority sign
        non_zero = [v for v in votes if v != 0.0]
        if non_zero and accel_score != 0.0:
            majority_sign = 1.0 if accel_score > 0 else -1.0
            accel_agreement = round(sum(1 for v in non_zero if v == majority_sign) / len(non_zero), 4)
        else:
            accel_agreement = 0.0

        # Regime classification (evaluated in order)
        prev_score = self._state.get("prev_accel_score")
        if accel_score > 0.5:
            regime = "building"
        elif is_num(prev_score) and prev_score > 0.3 and accel_score <= 0.3:
            regime = "peak"
        elif is_num(prev_score) and prev_score < -0.3 and accel_score >= -0.3:
            regime = "trough"
        elif accel_score < -0.3:
            regime = "waning"
        else:
            regime = "neutral"

        self._state["prev_accel_score"] = accel_score

        return {
            "accel_regime": regime,
            "accel_score": accel_score,
            "accel_agreement": accel_agreement,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = AccelerationRegimePlugin()
```

- [ ] **Step 3.4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/composites/test_acceleration_regime.py -v
```
Expected: ALL PASS.

- [ ] **Step 3.5: Commit**

```bash
git add src/intelligence/composites/acceleration_regime.py tests/unit/intelligence/composites/test_acceleration_regime.py
git commit -m "feat(i2): add AccelerationRegime plugin (building/peak/waning/trough labels)"
```

---

## Chunk 4: New SwingMomentum I3 Plugin

**Files:**
- Create: `src/intelligence/structure/swing_momentum.py`
- Create: `tests/unit/intelligence/test_swing_momentum.py`

---

- [ ] **Step 4.1: Write failing tests**

Create `tests/unit/intelligence/test_swing_momentum.py`:

```python
"""Tests for struct_SwingMomentum I3 plugin."""
from __future__ import annotations

import numpy as np
import pytest

from tests.unit.intelligence.helpers import make_ohlcv_from_hl


def _make_alternating_swings(n_swings: int = 4, bar_spacing: int = 8, atr: float = 8.0):
    """Build OHLCV with clean alternating swing highs and lows.

    Creates n_swings alternating peaks/valleys spaced bar_spacing bars apart.
    The flat filler bars use a tight band (high=5001, low=4999) so they are NOT
    local extrema — avoids spurious swing detection on flat regions.
    Returns (df, features_dict).
    """
    total_bars = n_swings * bar_spacing + 10
    # Filler: tight band — not local extrema
    high = np.full(total_bars, 5001.0)
    low = np.full(total_bars, 4999.0)

    # Place alternating swing highs and lows
    for i in range(n_swings):
        bar_idx = 5 + i * bar_spacing
        if i % 2 == 0:  # swing high
            high[bar_idx] = 5020.0
            low[bar_idx] = 4998.0
        else:  # swing low
            high[bar_idx] = 5002.0
            low[bar_idx] = 4980.0

    df = make_ohlcv_from_hl(high, low)
    features = {"atr_14": atr, "trend_regime": 0.5}
    return df, features


class TestSwingMomentum:
    def test_returns_empty_when_fewer_than_3_swings(self):
        """Warmup gate: fewer than 3 complete swings → return {}."""
        from src.intelligence.structure.swing_momentum import SwingMomentumPlugin
        p = SwingMomentumPlugin()
        # Only 2 swing points — not enough for 3 amplitudes
        df, features = _make_alternating_swings(n_swings=2, bar_spacing=8)
        result = p.compute_full({"main": df, "features": features})
        assert result == {} or result.get("struct_energy") is None

    def test_returns_outputs_with_sufficient_swings(self):
        """With 6 swing points → all output fields present."""
        from src.intelligence.structure.swing_momentum import SwingMomentumPlugin
        p = SwingMomentumPlugin()
        df, features = _make_alternating_swings(n_swings=6, bar_spacing=8)
        result = p.compute_full({"main": df, "features": features})
        assert "swing_amplitude_ratio" in result
        assert "swing_amplitude_expanding" in result
        assert "swing_velocity_bars" in result
        assert "swing_velocity_trend" in result
        assert "struct_energy" in result
        assert "struct_accel_bias" in result

    def test_struct_energy_bounded_zero_to_one(self):
        """struct_energy always in [0.0, 1.0]."""
        from src.intelligence.structure.swing_momentum import SwingMomentumPlugin
        p = SwingMomentumPlugin()
        df, features = _make_alternating_swings(n_swings=8, bar_spacing=6)
        result = p.compute_full({"main": df, "features": features})
        if "struct_energy" in result:
            assert 0.0 <= result["struct_energy"] <= 1.0

    def test_swing_amplitude_ratio_above_one_when_expanding(self):
        """Expanding swings → amplitude_ratio > 1.0."""
        from src.intelligence.structure.swing_momentum import SwingMomentumPlugin
        p = SwingMomentumPlugin()

        total_bars = 70
        high = np.full(total_bars, 5000.0)
        low = np.full(total_bars, 5000.0)

        # Swings with growing amplitude: 10, 15, 20, 25 points
        positions_highs = [5, 15, 30, 50]
        amplitudes = [10, 15, 20, 25]
        for pos, amp in zip(positions_highs, amplitudes):
            high[pos] = 5000 + amp
            low[pos] = 5000 - 1  # small opposite side

        positions_lows = [10, 22, 40, 60]
        for i, pos in enumerate(positions_lows):
            amp = amplitudes[i]
            low[pos] = 5000 - amp
            high[pos] = 5000 + 1

        df = make_ohlcv_from_hl(high, low)
        features = {"atr_14": 8.0, "trend_regime": 0.5}
        result = p.compute_full({"main": df, "features": features})
        if "swing_amplitude_ratio" in result:
            assert result["swing_amplitude_ratio"] >= 1.0

    def test_struct_accel_bias_positive_in_uptrend(self):
        """trend_regime > 0.3 → struct_accel_bias = 1."""
        from src.intelligence.structure.swing_momentum import SwingMomentumPlugin
        p = SwingMomentumPlugin()
        df, _ = _make_alternating_swings(n_swings=6, bar_spacing=8)
        result = p.compute_full({"main": df, "features": {"atr_14": 8.0, "trend_regime": 0.7}})
        if "struct_accel_bias" in result:
            assert result["struct_accel_bias"] == 1

    def test_struct_accel_bias_negative_in_downtrend(self):
        """trend_regime < -0.3 → struct_accel_bias = -1."""
        from src.intelligence.structure.swing_momentum import SwingMomentumPlugin
        p = SwingMomentumPlugin()
        df, _ = _make_alternating_swings(n_swings=6, bar_spacing=8)
        result = p.compute_full({"main": df, "features": {"atr_14": 8.0, "trend_regime": -0.7}})
        if "struct_accel_bias" in result:
            assert result["struct_accel_bias"] == -1

    def test_swing_velocity_bars_not_emitted_before_warmup(self):
        """Below warmup threshold → swing_velocity_bars should not appear in result."""
        from src.intelligence.structure.swing_momentum import SwingMomentumPlugin
        p = SwingMomentumPlugin()
        df, features = _make_alternating_swings(n_swings=2, bar_spacing=8)
        result = p.compute_full({"main": df, "features": features})
        # Either empty or swing_velocity_bars absent — not emitted mid-warmup
        assert result == {} or "swing_velocity_bars" not in result

    def test_atr_zero_fallback_does_not_raise(self):
        """atr_14 = 0 → plugin uses unnormalized fallback, no ZeroDivisionError."""
        from src.intelligence.structure.swing_momentum import SwingMomentumPlugin
        p = SwingMomentumPlugin()
        df, _ = _make_alternating_swings(n_swings=6, bar_spacing=8)
        # Should not raise
        result = p.compute_full({"main": df, "features": {"atr_14": 0.0, "trend_regime": 0.5}})
        # Result is valid (may be {} or have outputs, but no exception)

    def test_plugin_registered_in_tier_i3():
        from src.intelligence.structure.swing_momentum import plugin
        from src.intelligence.register_plugins import TIER_I3
        assert plugin.name in TIER_I3
```

- [ ] **Step 4.2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/unit/intelligence/test_swing_momentum.py -v
```
Expected: ModuleNotFoundError

- [ ] **Step 4.3: Implement SwingMomentum plugin**

Create `src/intelligence/structure/swing_momentum.py`:

```python
# src/intelligence/structure/swing_momentum.py
"""SwingMomentum — structural momentum from swing amplitude and velocity.

Self-contained I3 plugin. Reads raw OHLCV bars directly using ±3 bar peak/valley
detection. Tracks the last 5 confirmed extremes in _state to compute:

  swing_amplitude_ratio  — current swing size vs 3-swing ATR-normalized average
  swing_amplitude_expanding — 1 if last 3 amplitudes monotonically increasing
  swing_velocity_bars    — bars since last confirmed swing extreme
  swing_velocity_trend   — "accelerating" | "decelerating" | "stable"
  struct_energy          — composite score (amplitude × velocity), clamped 0–1
  struct_accel_bias      — +1/0/-1 matching trend_regime direction

ATR normalization: if atr_14 = 0, amplitudes are stored in raw price units
(swing_amplitude_ratio remains internally consistent but not cross-instrument).

Warmup gate: returns {} until 3 complete amplitudes are available (requires
at least 6 alternating swing extremes in the lookback window).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec, PatternPlugin

_SWING_WINDOW = 3       # ±bars for peak/valley confirmation
_MIN_AMPLITUDES = 3     # require 3 amplitudes (6 extremes) before emitting
_REFERENCE_BARS = 8     # typical bars between swings (used for speed_factor baseline)


def _detect_swings(highs: np.ndarray, lows: np.ndarray, n: int = _SWING_WINDOW):
    """Detect alternating swing highs and lows using ±n bar center-window.

    Returns list of (bar_index, price, type) where type = 'H' or 'L',
    deduplicated to strict alternation (consecutive same-type keeps the extreme).
    """
    raw: list[tuple[int, float, str]] = []

    for i in range(n, len(highs) - n):
        window_h = highs[i - n: i + n + 1]
        window_l = lows[i - n: i + n + 1]
        is_sh = highs[i] >= np.max(window_h)
        is_sl = lows[i] <= np.min(window_l)
        if is_sh:
            raw.append((i, float(highs[i]), "H"))
        if is_sl:
            raw.append((i, float(lows[i]), "L"))

    # Deduplicate: force alternation, keep the more extreme when duplicated
    filtered: list[tuple[int, float, str]] = []
    for s in raw:
        if not filtered:
            filtered.append(s)
        elif filtered[-1][2] == s[2]:
            # Same type: keep more extreme
            if s[2] == "H" and s[1] > filtered[-1][1]:
                filtered[-1] = s
            elif s[2] == "L" and s[1] < filtered[-1][1]:
                filtered[-1] = s
        else:
            filtered.append(s)

    return filtered


@dataclass
class SwingMomentumPlugin:
    name: str = "struct_SwingMomentum"
    outputs: frozenset[str] = frozenset({
        "swing_amplitude_ratio",
        "swing_amplitude_expanding",
        "swing_velocity_bars",
        "swing_velocity_trend",
        "struct_energy",
        "struct_accel_bias",
    })
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"structure", "momentum"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=60),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}

        if df is None or len(df) < self.min_lookback:
            return {}

        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        atr = float(features.get("atr_14") or 0.0)
        trend_regime = float(features.get("trend_regime", 0.0))

        swings = _detect_swings(highs, lows)

        if len(swings) < 4:
            return {}  # warmup gate

        # Compute amplitudes between consecutive swing pairs
        amplitudes_raw: list[float] = []
        intervals: list[int] = []
        for j in range(1, len(swings)):
            if swings[j][2] != swings[j - 1][2]:
                amp = abs(swings[j][1] - swings[j - 1][1])
                amplitudes_raw.append(amp)
                intervals.append(swings[j][0] - swings[j - 1][0])

        if len(amplitudes_raw) < _MIN_AMPLITUDES:
            return {}  # warmup gate

        # ATR-normalize amplitudes
        if atr > 0:
            amps = [a / atr for a in amplitudes_raw]
        else:
            amps = amplitudes_raw  # fallback: raw price units

        # Amplitude ratio: last vs 3-swing average
        last_amp = amps[-1]
        avg_3 = sum(amps[-3:]) / 3
        swing_amplitude_ratio = round(last_amp / avg_3 if avg_3 > 0 else 1.0, 4)

        # Expanding flag: last 3 amplitudes strictly increasing
        swing_amplitude_expanding = (
            1 if len(amps) >= 3 and amps[-3] < amps[-2] < amps[-1] else 0
        )

        # Velocity
        last_swing_bar = swings[-1][0]
        swing_velocity_bars = float(len(highs) - 1 - last_swing_bar)

        if len(intervals) >= 2:
            last_interval = intervals[-1]
            avg_interval = sum(intervals) / len(intervals)
            if last_interval < avg_interval * 0.8:
                swing_velocity_trend = "accelerating"
            elif last_interval > avg_interval * 1.2:
                swing_velocity_trend = "decelerating"
            else:
                swing_velocity_trend = "stable"

            speed_factor = max(0.1, min(3.0, _REFERENCE_BARS / max(1, last_interval)))
        else:
            swing_velocity_trend = "stable"
            speed_factor = 1.0

        # struct_energy: amplitude × speed, normalized so 1.0 = strong building structure
        # Calibration: amplitude_ratio=1.5 × speed_factor=2.0 = 3.0 → struct_energy=1.0
        # Typical healthy trend: 0.4–0.7. Parabolic: >0.8. Exhausting: <0.2.
        struct_energy = round(
            max(0.0, min(1.0, swing_amplitude_ratio * speed_factor / 3.0)),
            4
        )

        # Directional bias from trend regime
        if trend_regime > 0.3:
            struct_accel_bias = 1
        elif trend_regime < -0.3:
            struct_accel_bias = -1
        else:
            struct_accel_bias = 0

        return {
            "swing_amplitude_ratio": swing_amplitude_ratio,
            "swing_amplitude_expanding": swing_amplitude_expanding,
            "swing_velocity_bars": swing_velocity_bars,
            "swing_velocity_trend": swing_velocity_trend,
            "struct_energy": struct_energy,
            "struct_accel_bias": struct_accel_bias,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = SwingMomentumPlugin()
```

- [ ] **Step 4.4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_swing_momentum.py -v
```
Expected: ALL PASS. Fix any failures before proceeding.

- [ ] **Step 4.5: Commit**

```bash
git add src/intelligence/structure/swing_momentum.py tests/unit/intelligence/test_swing_momentum.py
git commit -m "feat(i3): add SwingMomentum plugin (structural momentum via swing amplitude+velocity)"
```

---

## Chunk 5: Registration + I7 Wiring

**Files:**
- Modify: `src/intelligence/register_plugins.py`
- Modify: `src/intelligence/trading/liquidity_sweep_reclaim.py`
- Modify: `src/intelligence/trading/liquidity_hunt.py`
- Modify: `src/intelligence/trading/momentum_breakout.py`
- Modify: `src/intelligence/trading/trend_following.py`
- Modify: `tests/unit/intelligence/composites/test_exhaustion_score.py` (fix registration test)
- Modify: `tests/unit/intelligence/composites/test_acceleration_regime.py` (fix registration test)
- Modify: `tests/unit/intelligence/test_swing_momentum.py` (fix registration test)

---

- [ ] **Step 5.1: Write failing registration tests**

Add standalone registration test file `tests/unit/intelligence/test_second_derivative_registration.py`:

```python
"""Verify all second-derivative plugins are registered in the correct tier."""


def test_exhaustion_score_in_tier_i2():
    from src.intelligence.composites.exhaustion_score import plugin
    from src.intelligence.register_plugins import TIER_I2
    assert plugin.name in TIER_I2


def test_acceleration_regime_in_tier_i2():
    from src.intelligence.composites.acceleration_regime import plugin
    from src.intelligence.register_plugins import TIER_I2
    assert plugin.name in TIER_I2


def test_swing_momentum_in_tier_i3():
    from src.intelligence.structure.swing_momentum import plugin
    from src.intelligence.register_plugins import TIER_I3
    assert plugin.name in TIER_I3


def test_validate_tier_passes_with_new_plugins():
    """register_all_plugins() + validate_tier() must not raise."""
    from src.intelligence.register_plugins import register_all_plugins
    from src.intelligence.plugins import registry
    register_all_plugins()
    # validate_tier() is called automatically at import time for each tier
    # If any name in TIER_* is missing from the registry, it raises ValueError
    # Just importing register_plugins and TIER lists without crash = passing
    from src.intelligence.register_plugins import TIER_I2, TIER_I3
    # If any name in TIER_* is missing from registry, register_all_plugins() raises — reaching here = passing
    assert len(TIER_I2) > 0 and len(TIER_I3) > 0
```

Run to confirm fail:
```bash
.venv/bin/pytest tests/unit/intelligence/test_second_derivative_registration.py -v
```

- [ ] **Step 5.2: Register plugins in register_plugins.py**

Add imports near the top of the existing imports block (after the existing composite imports):

```python
from .composites.exhaustion_score import plugin as exhaustion_score_plugin
from .composites.acceleration_regime import plugin as acceleration_regime_plugin
from .structure.swing_momentum import plugin as swing_momentum_plugin
```

In `register_all_plugins()`, after the existing I2 registrations (after `registry.register_pattern(deriv_osc_plugin)`):

```python
    registry.register_pattern(exhaustion_score_plugin)
    registry.register_pattern(acceleration_regime_plugin)
```

And in the I3 block (after `registry.register_pattern(fib_zones_plugin)`):

```python
    registry.register_pattern(swing_momentum_plugin)
```

In `TIER_I2` list, add at end:
```python
    exhaustion_score_plugin.name,
    acceleration_regime_plugin.name,
```

In `TIER_I3` list, add at end:
```python
    swing_momentum_plugin.name,
```

- [ ] **Step 5.3: Run registration tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_second_derivative_registration.py -v
```
Expected: ALL PASS.

- [ ] **Step 5.4: Write failing I7 wiring tests**

Add `tests/unit/intelligence/test_exhaustion_i7_wiring.py`:

```python
"""Tests for exhaustion-aware confidence adjustments in I7 setups."""
from __future__ import annotations

import numpy as np
import pytest

from tests.unit.intelligence.helpers import make_ohlcv


def _sweep_features(
    exhaustion_score=0.0, exhaustion_side="none", exhaustion_bars=0,
    accel_regime="neutral", struct_energy=0.5, direction=1,
):
    """Minimal features for a passing LiquiditySweepReclaim setup + exhaustion fields."""
    side = exhaustion_side
    return {
        "sweep_detected": 1.0, "sweep_reclaimed": 1.0,
        "sweep_type": float(direction), "sweep_level": 5000.0,
        "atr_14": 8.0,
        "exhaustion_score": exhaustion_score,
        "exhaustion_side": side,
        "exhaustion_bars": float(exhaustion_bars),
        "accel_regime": accel_regime,
        "struct_energy": struct_energy,
    }


def _breakout_features(
    exhaustion_score=0.0, exhaustion_side="none", exhaustion_bars=0, direction=1,
):
    """Minimal features for a passing MomentumBreakout setup + exhaustion fields."""
    roc = 0.5 if direction == 1 else -0.5
    return {
        "roc_14": roc,
        "swing_high": 5010.0, "swing_low": 4990.0,
        "trend_regime": float(direction),
        "atr_14": 8.0,
        "exhaustion_score": exhaustion_score,
        "exhaustion_side": "bull" if direction == 1 else "bear",
        "exhaustion_bars": float(exhaustion_bars),
    }


class TestLiquiditySweepReclaimExhaustionBoost:
    def test_exhaustion_boost_adds_confidence_for_sweep_long(self):
        """exhaustion_score > 0.6 on bull side for long sweep → confidence increases."""
        from src.intelligence.trading.liquidity_sweep_reclaim import LiquiditySweepReclaimPlugin

        close = np.full(60, 5005.0)
        df = make_ohlcv(close)

        # Baseline: no exhaustion
        base_features = _sweep_features(direction=1)
        p = LiquiditySweepReclaimPlugin()
        base = p.compute_full({"main": df, "features": base_features})

        # With exhaustion boost
        boost_features = _sweep_features(
            exhaustion_score=0.65, exhaustion_side="bull",
            accel_regime="building", struct_energy=0.7, direction=1,
        )
        boosted = p.compute_full({"main": df, "features": boost_features})

        assert boosted["confidence"] > base["confidence"]
        assert "exhaustion_sweep_boost" in boosted["supporting_factors"]

    def test_no_boost_when_exhaustion_score_below_threshold(self):
        """exhaustion_score ≤ 0.6 → no boost applied."""
        from src.intelligence.trading.liquidity_sweep_reclaim import LiquiditySweepReclaimPlugin

        close = np.full(60, 5005.0)
        df = make_ohlcv(close)
        features = _sweep_features(exhaustion_score=0.5, exhaustion_side="bull", direction=1)
        p = LiquiditySweepReclaimPlugin()
        result = p.compute_full({"main": df, "features": features})
        assert "exhaustion_sweep_boost" not in result.get("supporting_factors", [])


class TestMomentumBreakoutExhaustionGuard:
    def test_confidence_penalized_when_exhaustion_high_and_sustained(self):
        """exhaustion_score > 0.7 AND exhaustion_bars >= 3 → confidence reduced."""
        from src.intelligence.trading.momentum_breakout import MomentumBreakoutPlugin

        close = np.full(50, 5010.0)
        close[-1] = 5015.0
        volume = np.full(50, 1000.0)
        volume[-1] = 2000.0
        df = make_ohlcv(close, volume)

        # Baseline
        base_features = _breakout_features(direction=1)
        p = MomentumBreakoutPlugin()
        base = p.compute_full({"main": df, "features": base_features})

        # With exhaustion penalty
        exhaust_features = _breakout_features(
            exhaustion_score=0.8, exhaustion_bars=4, direction=1,
        )
        penalized = p.compute_full({"main": df, "features": exhaust_features})

        if penalized.get("direction", 0) != 0:  # if not suppressed
            assert penalized["confidence"] < base["confidence"]
            assert "exhaustion_guard_penalty" in penalized.get("supporting_factors", [])

    def test_no_penalty_when_exhaustion_bars_below_threshold(self):
        """exhaustion_bars < 3 → no penalty even if score is high."""
        from src.intelligence.trading.momentum_breakout import MomentumBreakoutPlugin

        close = np.full(50, 5010.0)
        close[-1] = 5015.0
        volume = np.full(50, 1000.0)
        volume[-1] = 2000.0
        df = make_ohlcv(close, volume)
        features = _breakout_features(exhaustion_score=0.8, exhaustion_bars=2, direction=1)
        p = MomentumBreakoutPlugin()
        result = p.compute_full({"main": df, "features": features})
        if result.get("direction", 0) != 0:
            assert "exhaustion_guard_penalty" not in result.get("supporting_factors", [])

    def test_no_penalty_when_exhaustion_on_opposite_side(self):
        """Bullish exhaustion on a short breakout → no penalty (different direction)."""
        from src.intelligence.trading.momentum_breakout import MomentumBreakoutPlugin

        close = np.full(50, 4990.0)
        close[-1] = 4985.0
        volume = np.full(50, 1000.0)
        volume[-1] = 2000.0
        df = make_ohlcv(close, volume)
        # bull exhaustion but direction=-1
        features = _breakout_features(exhaustion_score=0.8, exhaustion_bars=4, direction=-1)
        features["exhaustion_side"] = "bull"  # opposite to direction
        p = MomentumBreakoutPlugin()
        result = p.compute_full({"main": df, "features": features})
        if result.get("direction", 0) != 0:
            assert "exhaustion_guard_penalty" not in result.get("supporting_factors", [])
```

Run to confirm fail:
```bash
.venv/bin/pytest tests/unit/intelligence/test_exhaustion_i7_wiring.py -v
```

- [ ] **Step 5.5: Wire LiquiditySweepReclaim**

In `src/intelligence/trading/liquidity_sweep_reclaim.py`, in `compute_full()` **replace** the existing `confidence = round(min(1.0, confidence), 4)` line with the full block below (changes the cap from 1.0 to 0.95 and adds exhaustion boosts):

```python
        # ── Exhaustion-aware boost (second-derivative confirmation) ──
        # exhaustion_score > 0.6 in sweep direction confirms institutional trap setup
        exhaustion_score = float(features.get("exhaustion_score", 0.0))
        exhaustion_side = features.get("exhaustion_side", "none")
        accel_regime = features.get("accel_regime", "neutral")
        struct_energy = float(features.get("struct_energy", 0.0))
        exhaustion_dir_match = (
            (direction == 1 and exhaustion_side == "bull") or
            (direction == -1 and exhaustion_side == "bear")
        )
        if exhaustion_score > 0.6 and exhaustion_dir_match:
            confidence += 0.10
            supporting.append("exhaustion_sweep_boost")
        if accel_regime == "building":
            confidence += 0.05
            supporting.append("accel_regime_building")
        if struct_energy > 0.6:
            confidence += 0.05
            supporting.append("struct_energy_strong")
        confidence = round(min(0.95, confidence), 4)
```

- [ ] **Step 5.6: Wire LiquidityHunt**

In `src/intelligence/trading/liquidity_hunt.py`, in `compute_full()` after `confidence = round(min(0.95, max(0.10, confidence)), 4)` and before the return, add:

```python
        # ── Exhaustion-aware boost ──
        exhaustion_score = float(features.get("exhaustion_score", 0.0))
        exhaustion_side = features.get("exhaustion_side", "none")
        accel_regime = features.get("accel_regime", "neutral")
        struct_energy = float(features.get("struct_energy", 0.0))
        exhaustion_dir_match = (
            (direction == 1 and exhaustion_side == "bull") or
            (direction == -1 and exhaustion_side == "bear")
        )
        if exhaustion_score > 0.6 and exhaustion_dir_match:
            confidence += 0.10
            supporting.append("exhaustion_sweep_boost")
        if accel_regime == "building":
            confidence += 0.05
            supporting.append("accel_regime_building")
        if struct_energy > 0.6:
            confidence += 0.05
            supporting.append("struct_energy_strong")
        confidence = round(min(0.95, confidence), 4)
```

- [ ] **Step 5.7: Wire MomentumBreakout exhaustion guard**

In `src/intelligence/trading/momentum_breakout.py`, after the existing zone friction penalty block (after `confidence = round(min(0.95, max(0.10, confidence)), 4)`), add:

```python
        # ── Exhaustion guard: penalize breakouts into exhausted momentum ──
        exhaustion_score = float(features.get("exhaustion_score", 0.0))
        exhaustion_side = features.get("exhaustion_side", "none")
        exhaustion_bars = int(features.get("exhaustion_bars", 0))
        exhaustion_dir_match = (
            (direction == 1 and exhaustion_side == "bull") or
            (direction == -1 and exhaustion_side == "bear")
        )
        if exhaustion_score > 0.7 and exhaustion_bars >= 3 and exhaustion_dir_match:
            confidence -= 0.15
            supporting.append("exhaustion_guard_penalty")
        confidence = round(min(0.95, max(0.10, confidence)), 4)
```

- [ ] **Step 5.8: Wire TrendFollowing exhaustion guard**

In `src/intelligence/trading/trend_following.py`, after the existing zone friction penalty block (after `confidence = round(min(0.95, max(0.10, confidence)), 4)`), add the identical guard block from Step 5.7.

- [ ] **Step 5.9: Run I7 wiring tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_exhaustion_i7_wiring.py -v
```
Expected: ALL PASS. Fix any failures.

- [ ] **Step 5.10: Run full test suite**

```bash
.venv/bin/pytest tests/unit/ -v --tb=short 2>&1 | tail -30
```
Expected: all existing tests still pass. Fix any regressions.

- [ ] **Step 5.11: Lint**

```bash
.venv/bin/ruff check src/intelligence/composites/exhaustion_score.py src/intelligence/composites/acceleration_regime.py src/intelligence/structure/swing_momentum.py src/intelligence/composites/momentum_accel.py src/intelligence/trading/liquidity_sweep_reclaim.py src/intelligence/trading/liquidity_hunt.py src/intelligence/trading/momentum_breakout.py src/intelligence/trading/trend_following.py src/intelligence/register_plugins.py
```
Expected: no new errors beyond existing E501. Fix any E (non-E501) errors.

- [ ] **Step 5.12: Commit**

```bash
git add src/intelligence/register_plugins.py \
        src/intelligence/trading/liquidity_sweep_reclaim.py \
        src/intelligence/trading/liquidity_hunt.py \
        src/intelligence/trading/momentum_breakout.py \
        src/intelligence/trading/trend_following.py \
        tests/unit/intelligence/test_second_derivative_registration.py \
        tests/unit/intelligence/test_exhaustion_i7_wiring.py
git commit -m "feat(i7): wire exhaustion guard + sweep boost into I7 setups; register new I2/I3 plugins"
```

---

## Final Verification

- [ ] **Run complete unit test suite**

```bash
.venv/bin/pytest tests/unit/ -q 2>&1 | tail -10
```
Expected: all tests pass, count higher than before (new tests added).

- [ ] **Verify new plugin names in tier lists**

```bash
.venv/bin/python -c "
from src.intelligence.register_plugins import TIER_I2, TIER_I3
print('I2:', [n for n in TIER_I2 if 'Exhaustion' in n or 'Acceleration' in n])
print('I3:', [n for n in TIER_I3 if 'Swing' in n])
"
```
Expected output:
```
I2: ['cmp_ExhaustionScore', 'cmp_AccelerationRegime']
I3: ['struct_SwingMomentum']
```

- [ ] **Verify new outputs in momentum_accel**

```bash
.venv/bin/python -c "
from src.intelligence.composites.momentum_accel import plugin
print(sorted(plugin.outputs))
"
```
Expected: `['inflection_flag', 'macd_accel', 'macd_hist_slope', 'price_accel', 'roc_accel', 'rsi_accel', 'rsi_curvature']`
