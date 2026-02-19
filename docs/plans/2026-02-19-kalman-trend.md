# Kalman Filter Trend Plugin — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build `ctx_KalmanTrend` — a 1D Kalman filter that produces a filtered "fair value" price, standardized deviation signal, trend direction, confidence bands, and a filter trust indicator to improve existing I7 plugins.

**Architecture:** Dataclass plugin in `src/intelligence/context/` following `GARCHVolatilityPlugin` exactly. `compute_full` runs the Kalman recursion from scratch; `compute_next` does O(1) update from stored state. Optional `use_garch_adaptive` flag (default False) replaces fixed R with GARCH-derived measurement noise.

**Tech Stack:** Python dataclass, numpy, pandas, pytest. No new dependencies.

---

## Reference Files

Read these before starting:
- `src/intelligence/context/garch_volatility.py` — exact class structure to follow
- `tests/unit/intelligence/test_garch_volatility.py` — exact test style to follow
- `src/intelligence/register_plugins.py` — how to import and register context plugins
- `docs/plans/2026-02-19-kalman-trend-design.md` — design rationale

---

## Task 1: Core Plugin — `compute_full` + 7 Outputs

**Files:**
- Create: `src/intelligence/context/kalman_trend.py`
- Create: `tests/unit/intelligence/test_kalman_trend.py`

---

**Step 1: Write the failing tests**

Create `tests/unit/intelligence/test_kalman_trend.py`:

```python
"""Tests for Kalman filter trend plugin."""

import math

import numpy as np
import pandas as pd
import pytest

from src.intelligence.context.kalman_trend import KalmanTrendPlugin


def _make_ohlcv(n: int = 100, seed: int = 42, trend: float = 0.5) -> pd.DataFrame:
    """Generate synthetic OHLCV with a gentle uptrend."""
    rng = np.random.default_rng(seed)
    close = 5000.0 + np.arange(n) * trend + np.cumsum(rng.standard_normal(n))
    high = close + rng.uniform(0.5, 2.0, n)
    low = close - rng.uniform(0.5, 2.0, n)
    return pd.DataFrame({
        "open": close - rng.uniform(0, 0.5, n),
        "high": high,
        "low": low,
        "close": close,
        "volume": rng.integers(100, 1000, n).astype(float),
    })


class TestKalmanTrend:
    def test_outputs_expected_keys(self):
        """All 7 output keys must be present with sufficient history."""
        plugin = KalmanTrendPlugin()
        result = plugin.compute_full({"main": _make_ohlcv()})
        for key in [
            "kalman_trend", "kalman_slope", "kalman_price_position",
            "kalman_uncertainty", "kalman_upper", "kalman_lower", "kalman_gain",
        ]:
            assert key in result, f"Missing key: {key}"

    def test_kalman_trend_near_close(self):
        """kalman_trend should be within 2% of the final close on trending data."""
        plugin = KalmanTrendPlugin()
        df = _make_ohlcv(n=100)
        result = plugin.compute_full({"main": df})
        final_close = float(df["close"].iloc[-1])
        assert abs(result["kalman_trend"] - final_close) / final_close < 0.02

    def test_kalman_gain_bounded(self):
        """kalman_gain (K) must be in [0, 1]."""
        plugin = KalmanTrendPlugin()
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert 0.0 <= result["kalman_gain"] <= 1.0

    def test_bands_straddle_trend(self):
        """kalman_upper > kalman_trend > kalman_lower."""
        plugin = KalmanTrendPlugin()
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert result["kalman_upper"] > result["kalman_trend"]
        assert result["kalman_trend"] > result["kalman_lower"]

    def test_short_data_returns_empty(self):
        """Returns {} when fewer than min_lookback bars."""
        plugin = KalmanTrendPlugin()
        result = plugin.compute_full({"main": _make_ohlcv(n=5)})
        assert result == {}

    def test_uncertainty_is_positive(self):
        """kalman_uncertainty (P_est) must always be positive."""
        plugin = KalmanTrendPlugin()
        result = plugin.compute_full({"main": _make_ohlcv()})
        assert result["kalman_uncertainty"] > 0

    def test_compute_next_matches_compute_full_on_final_bar(self):
        """compute_next on the last bar must match compute_full within 0.01%."""
        plugin_full = KalmanTrendPlugin()
        plugin_next = KalmanTrendPlugin()

        df = _make_ohlcv(n=100)
        df_minus_1 = df.iloc[:-1].reset_index(drop=True)
        df_last = df.iloc[-1:]

        # Warm up plugin_next on all-but-last bars
        plugin_next.compute_full({"main": df_minus_1})

        # Both process the full series
        result_full = plugin_full.compute_full({"main": df})
        result_next = plugin_next.compute_next({"main": df_last})

        assert abs(result_full["kalman_trend"] - result_next["kalman_trend"]) < 0.01

    def test_adaptive_mode_uses_garch_sigma(self):
        """With use_garch_adaptive=True, garch_sigma in features changes R."""
        plugin_fixed = KalmanTrendPlugin(use_garch_adaptive=False)
        plugin_adapt = KalmanTrendPlugin(use_garch_adaptive=True)

        df = _make_ohlcv(n=100)
        frames_no_garch = {"main": df, "features": {}}
        frames_with_garch = {"main": df, "features": {"garch_sigma": 0.02}}

        result_fixed = plugin_fixed.compute_full(frames_no_garch)
        result_adapt = plugin_adapt.compute_full(frames_with_garch)

        # Both must produce valid output — but kalman_gain will differ
        assert "kalman_trend" in result_fixed
        assert "kalman_trend" in result_adapt

    def test_adaptive_mode_falls_back_when_no_garch(self):
        """With use_garch_adaptive=True but no garch_sigma, must not raise."""
        plugin = KalmanTrendPlugin(use_garch_adaptive=True)
        df = _make_ohlcv(n=100)
        # No features at all — must fall back to fixed R gracefully
        result = plugin.compute_full({"main": df})
        assert "kalman_trend" in result
```

**Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/unit/intelligence/test_kalman_trend.py -v
```
Expected: `ERROR` — `cannot import name 'KalmanTrendPlugin'`

---

**Step 3: Create `src/intelligence/context/kalman_trend.py`**

```python
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ..plugins import InputSpec

_CONFIG_PATH = Path("config/kalman_parameters.json")

# Scale factor for converting garch_sigma (log-return units) to price-unit R.
# garch_sigma is typically 0.001–0.02; squaring and scaling maps to R range 0.1–40.
_GARCH_R_SCALE = 10_000.0


def _load_parameters() -> dict[str, float]:
    """Load Q/R from JSON if available, otherwise use defaults."""
    if _CONFIG_PATH.exists():
        import json
        with open(_CONFIG_PATH) as f:
            data = json.load(f)
        return {
            "Q": float(data.get("Q", 0.5)),
            "R": float(data.get("R", 2.0)),
        }
    return {"Q": 0.5, "R": 2.0}


@dataclass
class KalmanTrendPlugin:
    """1D Kalman filter (local level model) for trend estimation.

    Produces a filtered 'fair value' price and standardized deviation signal.

    State equation:  x(t) = x(t-1) + w(t),  w ~ N(0, Q)
    Observation:     z(t) = x(t) + v(t),     v ~ N(0, R)

    Predict:
        x_pred = x_est
        P_pred = P_est + Q
    Update:
        K      = P_pred / (P_pred + R)
        x_est  = x_pred + K * (close - x_pred)
        P_est  = (1 - K) * P_pred
    """

    name: str = "ctx_KalmanTrend"
    outputs: set[str] = frozenset({
        "kalman_trend",
        "kalman_slope",
        "kalman_price_position",
        "kalman_uncertainty",
        "kalman_upper",
        "kalman_lower",
        "kalman_gain",
    })
    min_lookback: int = 30
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"context", "trend"})
    inputs: list[InputSpec] = field(
        default_factory=lambda: [InputSpec(symbol=".*", timeframe="1m", lookback=200)]
    )
    use_garch_adaptive: bool = False
    _state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        params = _load_parameters()
        self._Q: float = params["Q"]
        self._R_fixed: float = params["R"]

    def _get_R(self, features: dict[str, Any]) -> float:
        """Return measurement noise R, optionally GARCH-adapted."""
        if self.use_garch_adaptive:
            garch_sigma = features.get("garch_sigma")
            if garch_sigma and float(garch_sigma) > 0:
                R_adaptive = (float(garch_sigma) * _GARCH_R_SCALE) ** 2
                return max(0.1, R_adaptive)
        return self._R_fixed

    def _run_filter(
        self,
        closes: np.ndarray,
        R: float,
    ) -> tuple[list[float], list[float], list[float]]:
        """Run Kalman recursion. Returns (x_est_history, P_est_history, K_history)."""
        Q = self._Q
        x_est = float(closes[0])
        P_est = R  # initialize uncertainty = measurement noise

        x_history: list[float] = []
        P_history: list[float] = []
        K_history: list[float] = []

        for c in closes:
            # Predict
            x_pred = x_est
            P_pred = P_est + Q
            # Update
            K = P_pred / (P_pred + R)
            x_est = x_pred + K * (float(c) - x_pred)
            P_est = (1.0 - K) * P_pred

            x_history.append(x_est)
            P_history.append(P_est)
            K_history.append(K)

        return x_history, P_history, K_history

    def _build_result(
        self,
        close: float,
        x_est: float,
        P_est: float,
        K: float,
        trend_history: list[float],
    ) -> dict[str, Any]:
        """Compute all 7 outputs from final Kalman state."""
        uncertainty_band = 2.0 * math.sqrt(max(P_est, 0.0))

        # Slope: trend[t] - trend[t-5] (use available history)
        if len(trend_history) >= 6:
            slope = trend_history[-1] - trend_history[-6]
        elif len(trend_history) >= 2:
            slope = trend_history[-1] - trend_history[0]
        else:
            slope = 0.0

        # Standardized price deviation
        sqrt_P = math.sqrt(max(P_est, 1e-15))
        price_position = (close - x_est) / sqrt_P

        return {
            "kalman_trend": float(x_est),
            "kalman_slope": float(slope),
            "kalman_price_position": float(price_position),
            "kalman_uncertainty": float(P_est),
            "kalman_upper": float(x_est + uncertainty_band),
            "kalman_lower": float(x_est - uncertainty_band),
            "kalman_gain": float(K),
        }

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        features = frames.get("features", {})
        R = self._get_R(features)
        closes = df["close"].to_numpy(dtype=float)

        x_history, P_history, K_history = self._run_filter(closes, R)

        trend_history = x_history[-6:]  # keep last 6 for slope calc
        x_est = x_history[-1]
        P_est = P_history[-1]
        K = K_history[-1]

        # Save state for incremental updates
        self._state = {
            "x_est": x_est,
            "P_est": P_est,
            "trend_history": trend_history,
            "R": R,
        }

        return self._build_result(float(closes[-1]), x_est, P_est, K, trend_history)

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state:
            return self.compute_full(windows)

        df = windows.get("main")
        if df is None or len(df) < 1:
            return {}

        close = float(df.iloc[-1]["close"])
        features = windows.get("features", {})
        R = self._get_R(features) if self.use_garch_adaptive else self._state["R"]
        Q = self._Q

        x_est = self._state["x_est"]
        P_est = self._state["P_est"]
        trend_history: list[float] = list(self._state["trend_history"])

        # Predict + update
        P_pred = P_est + Q
        K = P_pred / (P_pred + R)
        x_est = x_est + K * (close - x_est)
        P_est = (1.0 - K) * P_pred

        trend_history.append(x_est)
        if len(trend_history) > 6:
            trend_history = trend_history[-6:]

        self._state = {
            "x_est": x_est,
            "P_est": P_est,
            "trend_history": trend_history,
            "R": R,
        }

        return self._build_result(close, x_est, P_est, K, trend_history)


plugin = KalmanTrendPlugin()
```

**Step 4: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/unit/intelligence/test_kalman_trend.py -v
```
Expected: 9 passed

**Step 5: Run full suite to confirm no regressions**

```bash
.venv/bin/python -m pytest tests/unit/ -q --tb=short
```
Expected: 348 + 9 = 357 passing, 0 failures

**Step 6: Commit**

```bash
git add src/intelligence/context/kalman_trend.py tests/unit/intelligence/test_kalman_trend.py
git commit -m "feat: add Kalman filter trend plugin (ctx_KalmanTrend) with 7 outputs"
```

---

## Task 2: Register the Plugin

**Files:**
- Modify: `src/intelligence/register_plugins.py`

**Step 1: Add the import**

Open `src/intelligence/register_plugins.py`. After line 5 (the `garch_vol_plugin` import), add:

```python
from .context.kalman_trend import plugin as kalman_trend_plugin
```

**Step 2: Add the registration**

In the `register_all_plugins()` function, after `registry.register_pattern(garch_vol_plugin)` (line 79), add:

```python
registry.register_pattern(kalman_trend_plugin)
```

**Step 3: Verify registration**

```bash
.venv/bin/python -c "
from src.intelligence.register_plugins import register_all_plugins
from src.intelligence.plugins import registry
register_all_plugins()
print(f'Total: {len(registry.indicators) + len(registry.patterns)}')
assert 'ctx_KalmanTrend' in registry.patterns, 'Not registered!'
print('ctx_KalmanTrend registered OK')
"
```
Expected:
```
Total: 42
ctx_KalmanTrend registered OK
```

**Step 4: Commit**

```bash
git add src/intelligence/register_plugins.py
git commit -m "feat: register ctx_KalmanTrend in plugin registry (42 total)"
```

---

## Task 3: Sync Docs and CLAUDE.md

**Step 1: Get verified counts**

```bash
.venv/bin/python -c "
from src.intelligence.register_plugins import register_all_plugins
from src.intelligence.plugins import registry
register_all_plugins()
print(f'Indicators: {len(registry.indicators)}')
print(f'Patterns: {len(registry.patterns)}')
print(f'Total: {len(registry.indicators) + len(registry.patterns)}')
"
.venv/bin/python -m pytest tests/unit/ -q --tb=no 2>&1 | tail -1
```

**Step 2: Update `docs/for-ai-assistants/CLAUDE.md`**

Update these fields with verified numbers:
- Line 5: `Status:` — change plugin count to 42, add Kalman to I4 context tier
- In `## Plugin System (38 total)` header → `## Plugin System (42 total)`
- In `### I4 Context Classification (3 plugins)` → `(4 plugins)` — add bullet: `- Kalman filter trend (adaptive trend estimation, fair value, 7 outputs)`
- In `### Current Development Status` → update `38 registered` to `42 registered`, test count
- In `### Intelligence Tiers` → update `I4 Context` status line to include Kalman
- In `### Completed Phases` → add `I4-Kalman` entry

**Step 3: Run linter**

```bash
.venv/bin/ruff check src/intelligence/context/kalman_trend.py
```
Expected: 0 errors. Fix any issues before committing.

**Step 4: Commit docs**

```bash
git add docs/for-ai-assistants/CLAUDE.md
git commit -m "docs: update CLAUDE.md v4.5.0 — ctx_KalmanTrend added (42 plugins, 357 tests)"
```

---

## Task 4: Final Verification

**Step 1: Full test suite**

```bash
.venv/bin/python -m pytest tests/unit/ -v --tb=short 2>&1 | tail -15
```
Expected: 357 passed, 0 failures.

**Step 2: Lint all touched files**

```bash
.venv/bin/ruff check src/intelligence/context/kalman_trend.py src/intelligence/register_plugins.py
```
Expected: 0 errors.

**Step 3: Smoke test plugin produces output**

```bash
.venv/bin/python -c "
import numpy as np
import pandas as pd
from src.intelligence.context.kalman_trend import KalmanTrendPlugin

rng = np.random.default_rng(42)
close = 5000.0 + np.cumsum(rng.standard_normal(100))
df = pd.DataFrame({'open': close, 'high': close+1, 'low': close-1, 'close': close, 'volume': 100.0})

plugin = KalmanTrendPlugin()
result = plugin.compute_full({'main': df})
for k, v in result.items():
    print(f'  {k}: {v:.6f}')
"
```
Expected: all 7 keys printed with finite values.

**Step 4: Push to remote**

```bash
git push origin main
```

---

## Summary

| Task | Files | Tests |
|------|-------|-------|
| 1. Core plugin | `kalman_trend.py`, `test_kalman_trend.py` | 9 |
| 2. Register | `register_plugins.py` | verification only |
| 3. Sync docs | `CLAUDE.md` | — |
| 4. Verify + push | — | full suite |

**Total new tests: 9**
**Registry after: 42 plugins (17 indicators + 25 patterns)**
