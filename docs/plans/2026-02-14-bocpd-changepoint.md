# BOCPD Change Point Detection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Bayesian Online Change Point Detection plugin that detects market regime transitions with probability scoring, using log returns as the core signal and I1 features for confirmation.

**Architecture:** Single `@dataclass` plugin implementing `PatternPlugin` protocol. BOCPD core maintains a run length probability distribution updated each bar via Student-t predictive likelihood. Feature confirmation from `frames["features"]` adjusts the raw probability. Supports true incremental `compute_next()` via persisted sufficient statistics.

**Tech Stack:** Python 3.13, numpy, pandas, scipy.stats (Student-t PDF only). Plugin protocol in `src/intelligence/plugins.py`.

---

## Plugin Pattern Reference

Every plugin follows the same structure as existing smart money plugins (see `src/intelligence/smart_money/bos_choch.py`):
- `@dataclass` with `name`, `outputs`, `min_lookback`, `supports_incremental`, `capability_tags`, `inputs`, `_state`
- `compute_full(frames)` does the work, returns `{}` on bad input
- `compute_next(windows)` uses `_state` for O(R) incremental update, falls back to `compute_full`
- Module ends with `plugin = PluginClass()`

Test helpers `make_ohlcv(close, volume)` and `_triangle()` in `tests/unit/intelligence/test_smart_money_plugins.py`.

---

### Task 1: BOCPD core + tests (no feature confirmation)

**Files:**
- Create: `src/intelligence/smart_money/bocpd_changepoint.py`
- Modify: `tests/unit/intelligence/test_smart_money_plugins.py` (append)

**Step 1: Write the failing tests**

Append to `tests/unit/intelligence/test_smart_money_plugins.py`:

```python
# ─── BOCPD Change Point Detection ─────────────────────────────


class TestBOCPDChangePoint:
    def test_detects_regime_change(self):
        """Flat returns then volatile returns → change point detected."""
        from src.intelligence.smart_money.bocpd_changepoint import BOCPDChangePointPlugin

        n = 100
        close = np.full(n, 5000.0)
        # First 50 bars: steady (tiny noise)
        close[:50] += np.random.default_rng(1).normal(0, 0.5, 50)
        # Bar 50+: volatile regime (large moves)
        close[50:] += np.cumsum(np.random.default_rng(2).normal(0, 20, 50))

        df = make_ohlcv(close)
        plugin = BOCPDChangePointPlugin()
        result = plugin.compute_full({"main": df})

        assert "cp_probability" in result
        assert "cp_raw_probability" in result
        assert "cp_run_length" in result
        assert "cp_detected" in result
        # Should detect a change point somewhere
        assert result["cp_raw_probability"] > 0.0

    def test_no_change_steady(self):
        """Steady returns with consistent noise → low change point probability."""
        from src.intelligence.smart_money.bocpd_changepoint import BOCPDChangePointPlugin

        n = 100
        rng = np.random.default_rng(42)
        close = 5000.0 + np.cumsum(rng.normal(0, 1, n))

        df = make_ohlcv(close)
        plugin = BOCPDChangePointPlugin()
        result = plugin.compute_full({"main": df})

        # Steady noise should produce low change point probability
        assert result["cp_raw_probability"] < 0.5

    def test_incremental_matches_full(self):
        """compute_next produces same result as compute_full on same data."""
        from src.intelligence.smart_money.bocpd_changepoint import BOCPDChangePointPlugin

        rng = np.random.default_rng(7)
        close = 5000.0 + np.cumsum(rng.normal(0, 2, 80))

        df_full = make_ohlcv(close)
        plugin_full = BOCPDChangePointPlugin()
        result_full = plugin_full.compute_full({"main": df_full})

        # Incremental: seed with first 50, then feed remaining bars
        plugin_inc = BOCPDChangePointPlugin()
        df_seed = make_ohlcv(close[:50])
        plugin_inc.compute_full({"main": df_seed})

        result_inc = {}
        for i in range(51, len(close) + 1):
            df_inc = make_ohlcv(close[:i])
            result_inc = plugin_inc.compute_next({"main": df_inc})

        # Final values should match (within floating point tolerance)
        assert abs(result_inc["cp_raw_probability"] - result_full["cp_raw_probability"]) < 0.05
        assert abs(result_inc["cp_run_length"] - result_full["cp_run_length"]) < 3

    def test_empty_input(self):
        from src.intelligence.smart_money.bocpd_changepoint import BOCPDChangePointPlugin

        plugin = BOCPDChangePointPlugin()
        assert plugin.compute_full({"main": None}) == {}
        assert plugin.compute_full({}) == {}

    def test_insufficient_data(self):
        from src.intelligence.smart_money.bocpd_changepoint import BOCPDChangePointPlugin

        df = make_ohlcv(np.full(5, 5000.0))
        plugin = BOCPDChangePointPlugin()
        assert plugin.compute_full({"main": df}) == {}

    def test_graceful_without_features(self):
        """Works with just OHLCV, no frames['features'] — confirmation defaults to 0.5."""
        from src.intelligence.smart_money.bocpd_changepoint import BOCPDChangePointPlugin

        n = 80
        close = np.full(n, 5000.0)
        close[40:] += np.cumsum(np.random.default_rng(3).normal(0, 15, 40))

        df = make_ohlcv(close)
        plugin = BOCPDChangePointPlugin()
        # No "features" key — should still work
        result = plugin.compute_full({"main": df})

        assert result["cp_confirmation"] == 0.5
        assert result["cp_probability"] > 0.0
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/intelligence/test_smart_money_plugins.py::TestBOCPDChangePoint -v`
Expected: FAIL (ImportError — module doesn't exist)

**Step 3: Write the implementation**

Create `src/intelligence/smart_money/bocpd_changepoint.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import t as student_t

from ..plugins import InputSpec


@dataclass
class BOCPDChangePointPlugin:
    """Bayesian Online Change Point Detection (Adams & MacKay 2007).

    Detects the moment market regime changes using log returns.
    Maintains a run length distribution updated each bar.
    Feature confirmation from I1 outputs adjusts raw probability.
    """

    name: str = "smc_BOCPDChangePoint"
    outputs: set[str] = frozenset(
        {
            "cp_probability",
            "cp_raw_probability",
            "cp_run_length",
            "cp_confirmation",
            "cp_detected",
        }
    )
    min_lookback: int = 30
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"smart_money"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=200),)
    hazard_lambda: int = 100  # Expected regime duration in bars
    max_run_length: int = 200  # Truncation cap
    cp_threshold: float = 0.5  # Detection threshold
    # Student-t conjugate prior hyperparameters
    mu0: float = 0.0
    kappa0: float = 1.0
    alpha0: float = 0.1
    beta0: float = 0.01
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        close = df["close"].to_numpy(dtype=float)

        # Compute log returns
        returns = np.diff(np.log(close))
        if len(returns) < 2:
            return {}

        # Run BOCPD on all returns, building state as we go
        self._reset_state()
        for x in returns:
            self._update(x)

        raw_prob = self._state["cp_prob"]
        run_length = int(np.argmax(self._state["run_length_probs"]))

        # Store prev_close for incremental
        self._state["prev_close"] = float(close[-1])
        self._state["n_bars"] = len(close)

        # Feature confirmation
        confirmation = self._compute_confirmation(df, frames)
        adjusted = raw_prob * (0.5 + 0.5 * confirmation)

        return {
            "cp_probability": round(float(adjusted), 6),
            "cp_raw_probability": round(float(raw_prob), 6),
            "cp_run_length": float(run_length),
            "cp_confirmation": round(float(confirmation), 4),
            "cp_detected": 1.0 if adjusted > self.cp_threshold else 0.0,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state or "run_length_probs" not in self._state:
            return self.compute_full(windows)

        df = windows.get("main")
        if df is None or len(df) < 2:
            return self.compute_full(windows)

        close = df["close"].to_numpy(dtype=float)
        current_close = float(close[-1])
        prev_close = self._state.get("prev_close", current_close)

        if prev_close <= 0 or current_close <= 0:
            return self.compute_full(windows)

        x = np.log(current_close / prev_close)
        self._update(x)

        raw_prob = self._state["cp_prob"]
        run_length = int(np.argmax(self._state["run_length_probs"]))
        self._state["prev_close"] = current_close
        self._state["n_bars"] = len(close)

        confirmation = self._compute_confirmation(df, windows)
        adjusted = raw_prob * (0.5 + 0.5 * confirmation)

        return {
            "cp_probability": round(float(adjusted), 6),
            "cp_raw_probability": round(float(raw_prob), 6),
            "cp_run_length": float(run_length),
            "cp_confirmation": round(float(confirmation), 4),
            "cp_detected": 1.0 if adjusted > self.cp_threshold else 0.0,
        }

    def _reset_state(self) -> None:
        """Initialize BOCPD state for a fresh run."""
        R = self.max_run_length
        self._state = {
            "run_length_probs": np.zeros(R),
            "mu": np.full(R, self.mu0),
            "kappa": np.full(R, self.kappa0),
            "alpha": np.full(R, self.alpha0),
            "beta": np.full(R, self.beta0),
            "cp_prob": 0.0,
        }
        self._state["run_length_probs"][0] = 1.0  # Start with run length 0

    def _update(self, x: float) -> None:
        """Process one observation through the BOCPD forward pass."""
        R = self.max_run_length
        s = self._state
        rl = s["run_length_probs"]
        mu = s["mu"]
        kappa = s["kappa"]
        alpha = s["alpha"]
        beta = s["beta"]
        hazard = 1.0 / self.hazard_lambda

        # Compute predictive probabilities for each run length
        # Student-t: df=2*alpha, loc=mu, scale=sqrt(beta*(kappa+1)/(alpha*kappa))
        df_param = 2 * alpha
        scale = np.sqrt(beta * (kappa + 1) / (alpha * kappa))
        # Avoid division by zero
        scale = np.where(scale > 0, scale, 1e-10)
        df_param = np.where(df_param > 0, df_param, 1e-10)

        pred_probs = student_t.pdf(x, df=df_param, loc=mu, scale=scale)

        # Growth probabilities: P(r+1) = P(x|r) * P(r) * (1 - hazard)
        growth = rl * pred_probs * (1 - hazard)

        # Change point probability: P(r=0) = sum of P(x|r) * P(r) * hazard
        cp_mass = float(np.sum(rl * pred_probs * hazard))

        # Shift growth probabilities (r -> r+1) and truncate
        new_rl = np.zeros(R)
        new_rl[1:] = growth[: R - 1]
        new_rl[0] = cp_mass

        # Normalize
        total = np.sum(new_rl)
        if total > 0:
            new_rl /= total

        # Update sufficient statistics
        # For existing run lengths: shift and update
        new_mu = np.full(R, self.mu0)
        new_kappa = np.full(R, self.kappa0)
        new_alpha = np.full(R, self.alpha0)
        new_beta = np.full(R, self.beta0)

        # Update for r >= 1 (continued runs)
        old_mu = mu[: R - 1]
        old_kappa = kappa[: R - 1]
        old_alpha = alpha[: R - 1]
        old_beta = beta[: R - 1]

        new_kappa[1:] = old_kappa + 1
        new_mu[1:] = (old_kappa * old_mu + x) / new_kappa[1:]
        new_alpha[1:] = old_alpha + 0.5
        new_beta[1:] = (
            old_beta
            + old_kappa * (x - old_mu) ** 2 / (2 * new_kappa[1:])
        )

        s["run_length_probs"] = new_rl
        s["mu"] = new_mu
        s["kappa"] = new_kappa
        s["alpha"] = new_alpha
        s["beta"] = new_beta
        s["cp_prob"] = float(new_rl[0])

    def _compute_confirmation(
        self, df: pd.DataFrame, frames: dict[str, Any]
    ) -> float:
        """Score feature confirmation from I1 outputs (0-1)."""
        features = frames.get("features")
        if not isinstance(features, dict):
            return 0.5  # No features available — neutral

        confirmation = 0.0
        close = df["close"].to_numpy(dtype=float)
        n = len(close)

        # 1. ATR regime shift: check vol_percentile if available
        vol_pct = features.get("vol_percentile")
        if vol_pct is not None:
            # High volatility percentile suggests regime change
            if float(vol_pct) > 0.75 or float(vol_pct) < 0.25:
                confirmation += 0.25

        # 2. RSI crossed 50 midline
        rsi = features.get("rsi_14")
        if rsi is not None:
            rsi_val = float(rsi)
            # Near the 50 line suggests transition
            if 45 <= rsi_val <= 55:
                confirmation += 0.25

        # 3. Volume spike: check if current volume > 2x average
        if "volume" in df.columns and n > 20:
            vol = df["volume"].to_numpy(dtype=float)
            avg_vol = float(np.mean(vol[-20:]))
            if avg_vol > 0 and vol[-1] > 2 * avg_vol:
                confirmation += 0.25

        # 4. Price crossed SMA-20
        if n >= 20:
            sma20 = float(np.mean(close[-20:]))
            if n >= 21:
                prev_sma20 = float(np.mean(close[-21:-1]))
                # Cross: previous close was on other side of SMA
                if (close[-2] < prev_sma20 and close[-1] > sma20) or (
                    close[-2] > prev_sma20 and close[-1] < sma20
                ):
                    confirmation += 0.25

        return confirmation


plugin = BOCPDChangePointPlugin()
```

**Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/unit/intelligence/test_smart_money_plugins.py::TestBOCPDChangePoint -v`
Expected: 6 PASS

**Step 5: Commit**

```bash
git add src/intelligence/smart_money/bocpd_changepoint.py tests/unit/intelligence/test_smart_money_plugins.py
git commit -m "feat: add BOCPD change point detection plugin with tests"
```

---

### Task 2: Register plugin + final verification

**Files:**
- Modify: `src/intelligence/register_plugins.py`

**Step 1: Update register_plugins.py**

Add import after existing smart_money imports:

```python
from .smart_money.bocpd_changepoint import plugin as bocpd_plugin
```

Add registration inside `register_all_plugins()` after existing smart_money registrations:

```python
    registry.register_pattern(bocpd_plugin)
```

**Step 2: Verify registration**

Run: `python -c "from src.intelligence.register_plugins import register_all_plugins; from src.intelligence.plugins import registry; register_all_plugins(); print(f'Indicators: {len(registry.indicators)}, Patterns: {len(registry.patterns)}, Total: {len(registry.indicators) + len(registry.patterns)}')"`
Expected: `Indicators: 16, Patterns: 15, Total: 31`

**Step 3: Run full test suite**

Run: `python -m pytest tests/unit/ -v`
Expected: All tests pass (~160 tests: 154 existing + 6 new)

**Step 4: Lint check**

Run: `.venv/bin/ruff check src/intelligence/smart_money/bocpd_changepoint.py tests/unit/intelligence/test_smart_money_plugins.py`
Expected: 0 errors

**Step 5: Commit**

```bash
git add src/intelligence/register_plugins.py
git commit -m "feat: register BOCPD plugin (31 total)"
```
