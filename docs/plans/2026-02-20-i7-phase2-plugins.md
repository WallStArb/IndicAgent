> **HISTORICAL DOCUMENT** — `intelligence_processor_service.py` was deleted in Phase 1 (2026-02-23). References to it in this doc are for historical context only. The canonical service is now `market_analysis_service.py`.

# I7 Phase 2: VWAPDeviation + MomentumBreakout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add two new I7 setup plugins (`trad_VWAPDeviation`, `trad_MomentumBreakout`), wire them into the pipeline, and register them.

**Architecture:** Each plugin follows the same dataclass pattern as existing I7 plugins — `compute_full` receives `frames["main"]` (OHLCV DataFrame) and `frames["features"]` (merged dict of all I1–I6 outputs). Plugins are registered as patterns in the registry and added to `I7_PLUGINS` in the signal orchestrator. ROC_PPO is also added to `I1_PLUGINS` so `roc_14` is available in the features dict.

**Tech Stack:** Python, numpy, pandas, pytest. No new dependencies.

---

## Current State

- Registry: 23 indicators + 28 patterns = **51 total**
- I7 plugins: `trad_TrendFollowing`, `trad_MeanReversion`, `trad_LiquiditySweepReclaim`, `trad_MTFAlignment`, `trad_SqueezeExpansion` (5 total)
- After this plan: 23 indicators + 30 patterns = **53 total**, 7 I7 plugins

## Test Command

```bash
.venv/bin/python3 -m pytest tests/ --ignore=tests/integration -q
```

Expected: all tests pass (currently 437).

---

## Task 1: Tests for VWAPDeviation Plugin

**Files:**
- Create: `tests/unit/intelligence/test_vwap_deviation.py`

### Step 1: Write the test file

```python
"""Tests for trad_VWAPDeviation setup plugin."""

import numpy as np
import pytest

from tests.unit.intelligence.helpers import make_ohlcv


def _features(price, vwap=5000.0, vwap_std=10.0, trend_regime=0.0):
    """Build a minimal features dict with VWAP bands centred on vwap."""
    return {
        "vwap": vwap,
        "vwap_std": vwap_std,
        "vwap_upper_1": vwap + vwap_std,
        "vwap_lower_1": vwap - vwap_std,
        "vwap_upper_2": vwap + 2 * vwap_std,
        "vwap_lower_2": vwap - 2 * vwap_std,
        "trend_regime": trend_regime,
        "atr_14": 8.0,
    }


class TestVWAPDeviation:
    def test_long_signal_below_lower_band(self):
        """Price below vwap_lower_2 → vwap_reversion_long."""
        from src.intelligence.trading.vwap_deviation import VWAPDeviationPlugin

        close = np.full(50, 5000.0)
        close[-1] = 4975.0          # below vwap_lower_2 = 4980
        df = make_ohlcv(close)
        features = _features(price=4975.0)

        plugin = VWAPDeviationPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type") == "vwap_reversion_long"
        assert result.get("direction") == 1
        assert 0.0 < result.get("confidence", 0) <= 1.0
        assert result.get("entry_price") == pytest.approx(4975.0, abs=1.0)
        assert result.get("stop_loss") < result["entry_price"]
        targets = result.get("targets", [])
        assert len(targets) == 2
        assert targets[0] == pytest.approx(5000.0, abs=0.1)   # T1 = vwap

    def test_short_signal_above_upper_band(self):
        """Price above vwap_upper_2 → vwap_reversion_short."""
        from src.intelligence.trading.vwap_deviation import VWAPDeviationPlugin

        close = np.full(50, 5000.0)
        close[-1] = 5025.0          # above vwap_upper_2 = 5020
        df = make_ohlcv(close)
        features = _features(price=5025.0)

        plugin = VWAPDeviationPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type") == "vwap_reversion_short"
        assert result.get("direction") == -1
        assert result.get("stop_loss") > result["entry_price"]
        targets = result.get("targets", [])
        assert len(targets) == 2
        assert targets[0] == pytest.approx(5000.0, abs=0.1)   # T1 = vwap

    def test_no_signal_within_bands(self):
        """Price inside ±2σ → no signal."""
        from src.intelligence.trading.vwap_deviation import VWAPDeviationPlugin

        close = np.full(50, 5005.0)
        df = make_ohlcv(close)
        features = _features(price=5005.0)

        plugin = VWAPDeviationPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"
        assert result.get("direction", 0) == 0

    def test_no_signal_zero_vwap_std(self):
        """vwap_std = 0 (no volume yet) → no signal."""
        from src.intelligence.trading.vwap_deviation import VWAPDeviationPlugin

        close = np.full(50, 4970.0)
        df = make_ohlcv(close)
        features = _features(price=4970.0, vwap_std=0.0)

        plugin = VWAPDeviationPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"

    def test_confidence_scales_with_deviation(self):
        """Larger sigma deviation → higher confidence."""
        from src.intelligence.trading.vwap_deviation import VWAPDeviationPlugin

        plugin = VWAPDeviationPlugin()
        close_moderate = np.full(50, 4978.0)   # ~2.2σ below
        close_extreme = np.full(50, 4960.0)    # ~4.0σ below
        features_mod = _features(price=4978.0)
        features_ext = _features(price=4960.0)

        r_mod = plugin.compute_full({"main": make_ohlcv(close_moderate), "features": features_mod})
        r_ext = plugin.compute_full({"main": make_ohlcv(close_extreme), "features": features_ext})

        assert r_mod.get("signal_type") == "vwap_reversion_long"
        assert r_ext.get("signal_type") == "vwap_reversion_long"
        assert r_ext["confidence"] > r_mod["confidence"]

    def test_regime_context_values(self):
        """regime_context identifies the current overextension direction."""
        from src.intelligence.trading.vwap_deviation import VWAPDeviationPlugin

        plugin = VWAPDeviationPlugin()
        close_low = np.full(50, 4970.0)
        close_high = np.full(50, 5030.0)

        r_low = plugin.compute_full({"main": make_ohlcv(close_low), "features": _features(price=4970.0)})
        r_high = plugin.compute_full({"main": make_ohlcv(close_high), "features": _features(price=5030.0)})

        assert r_low.get("regime_context") == "vwap_extended_low"
        assert r_high.get("regime_context") == "vwap_extended_high"

    def test_insufficient_data_returns_empty(self):
        """Too few bars → empty dict."""
        from src.intelligence.trading.vwap_deviation import VWAPDeviationPlugin

        close = np.array([4975.0, 4974.0, 4973.0])
        df = make_ohlcv(close)
        plugin = VWAPDeviationPlugin()
        result = plugin.compute_full({"main": df, "features": {}})
        assert result == {} or result.get("signal_type", "none") == "none"
```

### Step 2: Run the tests — verify they fail

```bash
.venv/bin/python3 -m pytest tests/unit/intelligence/test_vwap_deviation.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` — plugin doesn't exist yet.

### Step 3: Commit the test file

```bash
git add tests/unit/intelligence/test_vwap_deviation.py
git commit -m "test: add failing tests for trad_VWAPDeviation plugin"
```

---

## Task 2: Implement VWAPDeviation Plugin

**Files:**
- Create: `src/intelligence/trading/vwap_deviation.py`

### Step 1: Write the implementation

```python
"""I7 VWAP Deviation setup detection plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class VWAPDeviationPlugin:
    """VWAP Deviation setup: fires when price extends >2σ from session VWAP.

    Reads vwap, vwap_upper_2, vwap_lower_2, vwap_std from I1 VWAP plugin.
    Long when price < vwap_lower_2, short when price > vwap_upper_2.
    Targets: T1 = VWAP (the mean), T2 = opposite 1σ band.
    Confidence: deviation magnitude, regime compatibility, volume contraction.
    """

    name: str = "trad_VWAPDeviation"
    outputs: frozenset[str] = frozenset({
        "signal_type", "direction", "entry_price", "stop_loss",
        "targets", "confidence", "regime_context", "supporting_factors",
    })
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "vwap", "mean_reversion"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    sigma_threshold: float = 2.0
    atr_stop_multiplier: float = 1.5
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return {}

        # ── VWAP features ──
        vwap = features.get("vwap", 0.0)
        vwap_std = features.get("vwap_std", 0.0)
        vwap_upper_2 = features.get("vwap_upper_2", 0.0)
        vwap_lower_2 = features.get("vwap_lower_2", 0.0)
        vwap_upper_1 = features.get("vwap_upper_1", 0.0)
        vwap_lower_1 = features.get("vwap_lower_1", 0.0)

        # Gate: VWAP must be meaningful (session has volume)
        if vwap_std <= 0 or vwap <= 0:
            return self._no_signal()

        close = df["close"].to_numpy(dtype=float)
        volume = df["volume"].to_numpy(dtype=float)
        price = float(close[-1])

        # Gate: price must be outside ±2σ bands
        if vwap_lower_2 <= price <= vwap_upper_2:
            return self._no_signal()

        # Direction
        direction = 1 if price < vwap_lower_2 else -1

        # ATR
        atr = features.get("atr_14", 0.0)
        if atr <= 0:
            high = df["high"].to_numpy(dtype=float)
            low = df["low"].to_numpy(dtype=float)
            atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            return self._no_signal()

        entry = price

        # Stop loss
        if direction == 1:
            stop = entry - atr * self.atr_stop_multiplier
        else:
            stop = entry + atr * self.atr_stop_multiplier

        # Targets: T1 = vwap, T2 = opposite 1σ band
        if direction == 1:
            t2 = vwap_upper_1 if vwap_upper_1 > 0 else vwap + vwap_std
        else:
            t2 = vwap_lower_1 if vwap_lower_1 > 0 else vwap - vwap_std
        targets = [round(float(vwap), 2), round(float(t2), 2)]

        # ── Confidence ──

        # Deviation score (0.40): sigma excess beyond 2σ, capped at 4σ
        sigma_deviation = abs(price - vwap) / vwap_std
        dev_score = min(1.0, max(0.0, (sigma_deviation - 2.0) / 2.0))

        # Regime compatibility (0.35): trend_regime aligned with reversion direction
        trend_regime = features.get("trend_regime", 0.0)
        regime_aligns = (direction == 1 and trend_regime > 0) or (
            direction == -1 and trend_regime < 0
        )
        if abs(trend_regime) < 0.3:
            regime_compat = 0.50
        elif regime_aligns:
            regime_compat = 0.70 + 0.30 * abs(trend_regime)
        else:
            regime_compat = max(0.0, 0.50 - abs(trend_regime))

        # Volume contraction (0.25): lower volume = better fade
        vol_sma = float(np.mean(volume[-20:])) if len(volume) >= 20 else float(np.mean(volume))
        volume_ratio = float(volume[-1]) / vol_sma if vol_sma > 0 else 1.0
        vol_contraction = max(0.0, 1.0 - max(0.0, volume_ratio - 1.0))

        raw_conf = 0.40 * dev_score + 0.35 * regime_compat + 0.25 * vol_contraction
        confidence = round(min(1.0, max(0.0, raw_conf)), 4)

        # Supporting factors
        supporting = ["vwap_2sigma_breach", f"vwap_{sigma_deviation:.1f}sigma_deviation"]
        if abs(trend_regime) < 0.3:
            supporting.append("ranging_regime")
        if volume_ratio < 1.0:
            supporting.append("low_volume_deviation")
        if regime_aligns and abs(trend_regime) >= 0.3:
            supporting.append("regime_aligned")

        signal_type = "vwap_reversion_long" if direction == 1 else "vwap_reversion_short"
        regime_ctx = "vwap_extended_low" if direction == 1 else "vwap_extended_high"

        return {
            "signal_type": signal_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": round(stop, 2),
            "targets": targets,
            "confidence": confidence,
            "regime_context": regime_ctx,
            "supporting_factors": supporting,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}


plugin = VWAPDeviationPlugin()
```

### Step 2: Run tests — verify they pass

```bash
.venv/bin/python3 -m pytest tests/unit/intelligence/test_vwap_deviation.py -v
```

Expected: all 7 tests PASS.

### Step 3: Run full suite — verify nothing broken

```bash
.venv/bin/python3 -m pytest tests/ --ignore=tests/integration -q
```

Expected: 437 + 7 = **444 passing**.

### Step 4: Commit

```bash
git add src/intelligence/trading/vwap_deviation.py
git commit -m "feat: add trad_VWAPDeviation setup plugin"
```

---

## Task 3: Tests for MomentumBreakout Plugin

**Files:**
- Create: `tests/unit/intelligence/test_momentum_breakout.py`

### Step 1: Write the test file

```python
"""Tests for trad_MomentumBreakout setup plugin."""

import numpy as np
import pytest

from tests.unit.intelligence.helpers import make_ohlcv


def _base_features(roc=0.5, swing_high=5010.0, swing_low=4990.0, trend_regime=0.0):
    """Minimal features for a passing triple-gate setup."""
    return {
        "roc_14": roc,
        "swing_high": swing_high,
        "swing_low": swing_low,
        "trend_regime": trend_regime,
        "atr_14": 8.0,
    }


class TestMomentumBreakout:
    def test_long_breakout_all_gates_pass(self):
        """ROC spike up + volume expansion + price above swing_high → momentum_breakout_long."""
        from src.intelligence.trading.momentum_breakout import MomentumBreakoutPlugin

        close = np.full(50, 5010.0)
        close[-1] = 5015.0           # above swing_high=5010
        volume = np.full(50, 1000.0)
        volume[-1] = 2000.0          # 2x average → passes 1.5x gate
        df = make_ohlcv(close, volume)
        features = _base_features(roc=0.5, swing_high=5010.0)

        plugin = MomentumBreakoutPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type") == "momentum_breakout_long"
        assert result.get("direction") == 1
        assert 0.0 < result.get("confidence", 0) <= 1.0
        assert result.get("entry_price") == pytest.approx(5015.0, abs=1.0)
        assert result.get("stop_loss") < result["entry_price"]
        # stop should be near swing_high - atr*1.0 = 5010 - 8 = 5002
        assert result["stop_loss"] == pytest.approx(5002.0, abs=2.0)
        assert len(result.get("targets", [])) == 2

    def test_short_breakout_all_gates_pass(self):
        """ROC spike down + volume expansion + price below swing_low → momentum_breakout_short."""
        from src.intelligence.trading.momentum_breakout import MomentumBreakoutPlugin

        close = np.full(50, 4990.0)
        close[-1] = 4985.0           # below swing_low=4990
        volume = np.full(50, 1000.0)
        volume[-1] = 2000.0
        df = make_ohlcv(close, volume)
        features = _base_features(roc=-0.5, swing_low=4990.0)

        plugin = MomentumBreakoutPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type") == "momentum_breakout_short"
        assert result.get("direction") == -1
        assert result.get("stop_loss") > result["entry_price"]

    def test_no_signal_roc_too_weak(self):
        """ROC below threshold → no signal even if volume and structure qualify."""
        from src.intelligence.trading.momentum_breakout import MomentumBreakoutPlugin

        close = np.full(50, 5015.0)
        volume = np.full(50, 1000.0)
        volume[-1] = 2000.0
        df = make_ohlcv(close, volume)
        features = _base_features(roc=0.1, swing_high=5010.0)  # 0.1 < 0.3 threshold

        plugin = MomentumBreakoutPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"

    def test_no_signal_low_volume(self):
        """ROC spike + structure break but volume below 1.5x → no signal."""
        from src.intelligence.trading.momentum_breakout import MomentumBreakoutPlugin

        close = np.full(50, 5015.0)  # above swing_high=5010
        volume = np.full(50, 1000.0)
        volume[-1] = 1200.0          # only 1.2x — below 1.5x threshold
        df = make_ohlcv(close, volume)
        features = _base_features(roc=0.5, swing_high=5010.0)

        plugin = MomentumBreakoutPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"

    def test_no_signal_no_structure_break(self):
        """Strong ROC + volume but price hasn't cleared swing_high → no signal."""
        from src.intelligence.trading.momentum_breakout import MomentumBreakoutPlugin

        close = np.full(50, 5005.0)  # below swing_high=5010
        volume = np.full(50, 1000.0)
        volume[-1] = 2000.0
        df = make_ohlcv(close, volume)
        features = _base_features(roc=0.5, swing_high=5010.0)

        plugin = MomentumBreakoutPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"

    def test_no_signal_roc_direction_mismatch(self):
        """Positive ROC but only swing_low broken (not swing_high) → no signal."""
        from src.intelligence.trading.momentum_breakout import MomentumBreakoutPlugin

        close = np.full(50, 5005.0)  # above swing_low=4990 but below swing_high=5010
        volume = np.full(50, 1000.0)
        volume[-1] = 2000.0
        df = make_ohlcv(close, volume)
        # Positive ROC — only tries long gate. price=5005 < swing_high=5010 → no break.
        features = _base_features(roc=0.5, swing_high=5010.0, swing_low=4990.0)

        plugin = MomentumBreakoutPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"

    def test_inline_roc_fallback_when_feature_absent(self):
        """Plugin computes ROC from df if roc_14 not in features (fallback path)."""
        from src.intelligence.trading.momentum_breakout import MomentumBreakoutPlugin

        # Build 50-bar series where roc_14 is large enough to trigger
        close = np.full(50, 5000.0)
        close[-15:] = np.linspace(5000.0, 5025.0, 15)  # ~0.5% rise over 14 bars
        close[-1] = 5025.0          # above swing_high=5010
        volume = np.full(50, 1000.0)
        volume[-1] = 2000.0
        df = make_ohlcv(close, volume)
        # Note: no roc_14 key — plugin must compute inline
        features = {"swing_high": 5010.0, "swing_low": 4990.0, "trend_regime": 0.0, "atr_14": 8.0}

        plugin = MomentumBreakoutPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type") == "momentum_breakout_long"

    def test_confidence_scales_with_roc_magnitude(self):
        """Larger ROC spike → higher confidence, all else equal."""
        from src.intelligence.trading.momentum_breakout import MomentumBreakoutPlugin

        plugin = MomentumBreakoutPlugin()
        close = np.full(50, 5015.0)
        volume = np.full(50, 1000.0)
        volume[-1] = 2000.0
        df = make_ohlcv(close, volume)

        r_small = plugin.compute_full({"main": df, "features": _base_features(roc=0.35, swing_high=5010.0)})
        r_large = plugin.compute_full({"main": df, "features": _base_features(roc=1.0, swing_high=5010.0)})

        assert r_small.get("signal_type") == "momentum_breakout_long"
        assert r_large.get("signal_type") == "momentum_breakout_long"
        assert r_large["confidence"] > r_small["confidence"]

    def test_insufficient_data_returns_empty(self):
        """Too few bars → empty dict."""
        from src.intelligence.trading.momentum_breakout import MomentumBreakoutPlugin

        close = np.array([5000.0, 5005.0, 5010.0])
        df = make_ohlcv(close)
        plugin = MomentumBreakoutPlugin()
        result = plugin.compute_full({"main": df, "features": {}})
        assert result == {} or result.get("signal_type", "none") == "none"
```

### Step 2: Run the tests — verify they fail

```bash
.venv/bin/python3 -m pytest tests/unit/intelligence/test_momentum_breakout.py -v
```

Expected: `ImportError` — plugin doesn't exist yet.

### Step 3: Commit the test file

```bash
git add tests/unit/intelligence/test_momentum_breakout.py
git commit -m "test: add failing tests for trad_MomentumBreakout plugin"
```

---

## Task 4: Implement MomentumBreakout Plugin

**Files:**
- Create: `src/intelligence/trading/momentum_breakout.py`

### Step 1: Write the implementation

```python
"""I7 Momentum Breakout setup detection plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class MomentumBreakoutPlugin:
    """Momentum breakout setup: fires on ROC spike + volume expansion + structure break.

    All three gates are required (triple-gate sequential). Any failure → no signal.
    ROC direction must match structure break direction.
    Stop is placed at the broken structure level (new S/R), not from entry price.
    """

    name: str = "trad_MomentumBreakout"
    outputs: frozenset[str] = frozenset({
        "signal_type", "direction", "entry_price", "stop_loss",
        "targets", "confidence", "regime_context", "supporting_factors",
    })
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "breakout", "momentum"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)
    roc_period: int = 14
    roc_threshold: float = 0.3
    volume_expansion_threshold: float = 1.5
    atr_stop_multiplier: float = 1.0
    atr_target_multipliers: tuple = (1.5, 3.0)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return {}

        close = df["close"].to_numpy(dtype=float)
        volume = df["volume"].to_numpy(dtype=float)
        price = float(close[-1])

        # ── Gate A: ROC spike ──
        # Use pipeline feature if available (ROC_PPO in I1_PLUGINS), else compute inline
        roc = features.get(f"roc_{self.roc_period}")
        if roc is None:
            if len(close) > self.roc_period:
                past = float(close[-1 - self.roc_period])
                roc = (price - past) / past * 100.0 if past != 0 else 0.0
            else:
                return self._no_signal()

        if abs(roc) <= self.roc_threshold:
            return self._no_signal()

        # ── Gate B: volume expansion ──
        vol_sma = float(np.mean(volume[-20:])) if len(volume) >= 20 else float(np.mean(volume))
        if vol_sma <= 0:
            return self._no_signal()
        volume_ratio = float(volume[-1]) / vol_sma
        if volume_ratio <= self.volume_expansion_threshold:
            return self._no_signal()

        # ── Gate C + direction: structure break must match ROC direction ──
        swing_high = features.get("swing_high", 0.0)
        swing_low = features.get("swing_low", 0.0)

        if roc > 0:
            if swing_high <= 0 or price <= swing_high:
                return self._no_signal()
            direction = 1
            structure_level = float(swing_high)
        else:
            if swing_low <= 0 or price >= swing_low:
                return self._no_signal()
            direction = -1
            structure_level = float(swing_low)

        # ── ATR ──
        atr = features.get("atr_14", 0.0)
        if atr <= 0:
            high = df["high"].to_numpy(dtype=float)
            low = df["low"].to_numpy(dtype=float)
            atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            return self._no_signal()

        entry = price

        # Stop at broken structure level (now acts as S/R)
        if direction == 1:
            stop = structure_level - atr * self.atr_stop_multiplier
        else:
            stop = structure_level + atr * self.atr_stop_multiplier

        # Targets
        targets = [
            round(entry + atr * m, 2) if direction == 1 else round(entry - atr * m, 2)
            for m in self.atr_target_multipliers
        ]

        # ── Confidence ──
        roc_score = min(1.0, (abs(roc) - self.roc_threshold) / self.roc_threshold)
        vol_score = min(1.0, (volume_ratio - self.volume_expansion_threshold) / self.volume_expansion_threshold)
        break_margin = min(1.0, max(0.0, abs(price - structure_level) / atr))

        trend_regime = features.get("trend_regime", 0.0)
        regime_aligns = (direction == 1 and trend_regime > 0) or (
            direction == -1 and trend_regime < 0
        )
        if abs(trend_regime) < 0.3:
            regime_score = 0.5
        elif regime_aligns:
            regime_score = 1.0
        else:
            regime_score = 0.1

        raw_conf = (
            0.35 * roc_score
            + 0.30 * vol_score
            + 0.20 * break_margin
            + 0.15 * regime_score
        )
        confidence = round(min(1.0, max(0.0, raw_conf)), 4)

        # Supporting factors
        supporting = [
            f"roc_spike_{abs(roc):.1f}pct",
            f"volume_{volume_ratio:.1f}x_expansion",
            "structure_break_long" if direction == 1 else "structure_break_short",
        ]
        if regime_aligns and abs(trend_regime) >= 0.3:
            supporting.append("trend_regime_aligned")

        signal_type = "momentum_breakout_long" if direction == 1 else "momentum_breakout_short"
        regime_ctx = "breakout_bullish" if direction == 1 else "breakout_bearish"

        return {
            "signal_type": signal_type,
            "direction": direction,
            "entry_price": round(entry, 2),
            "stop_loss": round(stop, 2),
            "targets": targets,
            "confidence": confidence,
            "regime_context": regime_ctx,
            "supporting_factors": supporting,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

    @staticmethod
    def _no_signal() -> dict[str, Any]:
        return {"signal_type": "none", "direction": 0, "confidence": 0.0}


plugin = MomentumBreakoutPlugin()
```

### Step 2: Run tests — verify they pass

```bash
.venv/bin/python3 -m pytest tests/unit/intelligence/test_momentum_breakout.py -v
```

Expected: all 9 tests PASS.

### Step 3: Run full suite

```bash
.venv/bin/python3 -m pytest tests/ --ignore=tests/integration -q
```

Expected: 444 + 9 = **453 passing**.

### Step 4: Commit

```bash
git add src/intelligence/trading/momentum_breakout.py
git commit -m "feat: add trad_MomentumBreakout setup plugin"
```

---

## Task 5: Register Both Plugins

**Files:**
- Modify: `src/intelligence/register_plugins.py`

### Step 1: Add imports after the existing trading imports (around line 54)

After this block in `register_plugins.py`:
```python
from .trading.squeeze_expansion import plugin as squeeze_exp_plugin
from .trading.trend_following import plugin as trend_follow_plugin
```

Add:
```python
from .trading.momentum_breakout import plugin as momentum_breakout_plugin
from .trading.vwap_deviation import plugin as vwap_deviation_plugin
```

### Step 2: Add registration calls at the end of `register_all_plugins()`

After `registry.register_pattern(squeeze_exp_plugin)`, add:
```python
    registry.register_pattern(vwap_deviation_plugin)
    registry.register_pattern(momentum_breakout_plugin)
```

### Step 3: Add ROC_PPO to I1_PLUGINS in the intelligence processor

File: `services/intelligence_processor_service.py`

Find the `I1_PLUGINS` list (around line 54):
```python
I1_PLUGINS = [
    "RSI",
    "MovingAverages",
    "MACD",
    "ATR",
    "BollingerBands",
    "Stochastic",
    "CCI",
    "WilliamsR",
    "MFI",
    "OBV",
    "VWAP",
    "Supertrend",
]
```

Add `"ROC_PPO"` to the list:
```python
I1_PLUGINS = [
    "RSI",
    "MovingAverages",
    "MACD",
    "ATR",
    "BollingerBands",
    "Stochastic",
    "CCI",
    "WilliamsR",
    "MFI",
    "OBV",
    "VWAP",
    "Supertrend",
    "ROC_PPO",
]
```

### Step 4: Add new plugins to `I7_PLUGINS` in the signal orchestrator

File: `services/signal_orchestrator_service.py`

Find the `I7_PLUGINS` list (around line 61):
```python
I7_PLUGINS = [
    "trad_TrendFollowing",
    "trad_MeanReversion",
    "trad_LiquiditySweepReclaim",
    "trad_MTFAlignment",
    "trad_SqueezeExpansion",
]
```

Update to:
```python
I7_PLUGINS = [
    "trad_TrendFollowing",
    "trad_MeanReversion",
    "trad_LiquiditySweepReclaim",
    "trad_MTFAlignment",
    "trad_SqueezeExpansion",
    "trad_VWAPDeviation",
    "trad_MomentumBreakout",
]
```

### Step 5: Update the registration test counts

File: `tests/unit/intelligence/test_i7_registration.py`

Update `test_i7_plugins_registered` to include the two new plugin names:
```python
def test_i7_plugins_registered(self):
    """All 7 I7 plugins should be in the registry."""
    expected_i7 = {
        "trad_TrendFollowing",
        "trad_MeanReversion",
        "trad_LiquiditySweepReclaim",
        "trad_MTFAlignment",
        "trad_SqueezeExpansion",
        "trad_VWAPDeviation",
        "trad_MomentumBreakout",
    }
    registered = set(registry.patterns.keys())
    assert expected_i7.issubset(registered), f"Missing: {expected_i7 - registered}"
```

Update `test_total_plugin_count` to reflect 53 total (23 indicators + 30 patterns):
```python
def test_total_plugin_count(self):
    """Should have 23 indicators + 30 patterns = 53 total."""
    total = len(registry.indicators) + len(registry.patterns)
    n_ind = len(registry.indicators)
    n_pat = len(registry.patterns)
    assert total == 53, f"Expected 53, got {total} (indicators={n_ind}, patterns={n_pat})"
```

### Step 6: Run the full test suite

```bash
.venv/bin/python3 -m pytest tests/ --ignore=tests/integration -q
```

Expected: **453 passing** (or 454 if registration test count update adds a passing test that was previously failing).

### Step 7: Commit all wiring changes

```bash
git add src/intelligence/register_plugins.py \
        services/intelligence_processor_service.py \
        services/signal_orchestrator_service.py \
        tests/unit/intelligence/test_i7_registration.py
git commit -m "feat: register VWAPDeviation + MomentumBreakout, add ROC_PPO to I1 pipeline"
```

---

## Verification Checklist

After all tasks complete:

- [ ] `test_vwap_deviation.py` — 7 tests passing
- [ ] `test_momentum_breakout.py` — 9 tests passing
- [ ] `test_i7_registration.py` — expects 53 total, 7 I7 plugins
- [ ] Full suite: `453+` passing, 0 failures
- [ ] `registry.patterns` contains `trad_VWAPDeviation` and `trad_MomentumBreakout`
- [ ] `I7_PLUGINS` in orchestrator has 7 entries
- [ ] `I1_PLUGINS` in processor includes `"ROC_PPO"`
