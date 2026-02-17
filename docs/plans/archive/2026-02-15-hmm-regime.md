# HMM Market Regime Detection — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an HMM regime classification plugin that identifies ranging/trending-up/trending-down states with probabilistic confidence, using multivariate Gaussian emissions on 5 features.

**Architecture:** Pure numpy HMM with 3 hidden states and diagonal-covariance multivariate Gaussian emissions. Forward algorithm runs incrementally per bar in O(K²·D). Hardcoded default parameters with optional JSON override. Follows the same `@dataclass` plugin pattern as BOCPD.

**Tech Stack:** Python 3.13, numpy, pandas (DataFrame input), pytest

---

### Task 1: Write tests for HMM regime plugin

**Files:**
- Modify: `tests/unit/intelligence/test_smart_money_plugins.py` (append after line 412)

**Step 1: Append 6 tests to the test file**

Add the following test class at the end of `tests/unit/intelligence/test_smart_money_plugins.py`:

```python
# ─── HMM Regime Detection ────────────────────────────────────


class TestHMMRegime:
    def test_trending_up_detection(self):
        """Rising prices should be classified as trending-up (state 1)."""
        from src.intelligence.smart_money.hmm_regime import HMMRegimePlugin

        rng = np.random.default_rng(42)
        # Strong uptrend: consistent positive drift
        close = 5000.0 + np.cumsum(np.abs(rng.normal(0.5, 0.3, 200)))
        df = make_ohlcv(close)
        features = {"rsi_14": 65.0, "adx_14": 30.0, "macd_hist_12_26_9": 2.0, "atr_14": 10.0}

        plugin = HMMRegimePlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result != {}
        assert result["hmm_regime"] == 1.0  # Trending up
        assert result["hmm_prob_trending_up"] > result["hmm_prob_ranging"]
        assert result["hmm_prob_trending_up"] > result["hmm_prob_trending_down"]
        assert result["hmm_regime_prob"] > 0.5
        assert result["hmm_regime_duration"] >= 1.0

    def test_trending_down_detection(self):
        """Falling prices should be classified as trending-down (state 2)."""
        from src.intelligence.smart_money.hmm_regime import HMMRegimePlugin

        rng = np.random.default_rng(42)
        # Strong downtrend: consistent negative drift
        close = 5000.0 - np.cumsum(np.abs(rng.normal(0.5, 0.3, 200)))
        df = make_ohlcv(close)
        features = {"rsi_14": 35.0, "adx_14": 30.0, "macd_hist_12_26_9": -2.0, "atr_14": 10.0}

        plugin = HMMRegimePlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result != {}
        assert result["hmm_regime"] == 2.0  # Trending down
        assert result["hmm_prob_trending_down"] > result["hmm_prob_ranging"]
        assert result["hmm_prob_trending_down"] > result["hmm_prob_trending_up"]

    def test_ranging_detection(self):
        """Flat oscillating prices should be classified as ranging (state 0)."""
        from src.intelligence.smart_money.hmm_regime import HMMRegimePlugin

        rng = np.random.default_rng(42)
        # Ranging: oscillate around 5000 with small noise, no drift
        close = 5000.0 + rng.normal(0, 0.5, 200)
        df = make_ohlcv(close)
        features = {"rsi_14": 50.0, "adx_14": 12.0, "macd_hist_12_26_9": 0.0, "atr_14": 10.0}

        plugin = HMMRegimePlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result != {}
        assert result["hmm_regime"] == 0.0  # Ranging
        assert result["hmm_prob_ranging"] > result["hmm_prob_trending_up"]
        assert result["hmm_prob_ranging"] > result["hmm_prob_trending_down"]

    def test_incremental_parity(self):
        """compute_next() on full history should match compute_full()."""
        from src.intelligence.smart_money.hmm_regime import HMMRegimePlugin

        rng = np.random.default_rng(99)
        close = 5000.0 + np.cumsum(rng.normal(0.3, 0.5, 100))
        features = {"rsi_14": 60.0, "adx_14": 25.0, "macd_hist_12_26_9": 1.0, "atr_14": 10.0}

        # Full computation
        plugin_full = HMMRegimePlugin()
        df_full = make_ohlcv(close)
        result_full = plugin_full.compute_full({"main": df_full, "features": features})

        # Incremental: seed with first 30, then feed remaining one at a time
        plugin_inc = HMMRegimePlugin()
        df_seed = make_ohlcv(close[:30])
        plugin_inc.compute_full({"main": df_seed, "features": features})

        result_inc = {}
        for i in range(31, len(close) + 1):
            df_inc = make_ohlcv(close[:i])
            result_inc = plugin_inc.compute_next({"main": df_inc, "features": features})

        assert result_full["hmm_regime"] == result_inc["hmm_regime"]
        assert abs(result_full["hmm_regime_prob"] - result_inc["hmm_regime_prob"]) < 0.01

    def test_graceful_without_features(self):
        """Works with just OHLCV in 2D fallback mode."""
        from src.intelligence.smart_money.hmm_regime import HMMRegimePlugin

        rng = np.random.default_rng(42)
        close = 5000.0 + np.cumsum(np.abs(rng.normal(0.5, 0.3, 200)))
        df = make_ohlcv(close)

        plugin = HMMRegimePlugin()
        # No "features" key — should still produce results in 2D mode
        result = plugin.compute_full({"main": df})

        assert result != {}
        assert "hmm_regime" in result
        assert "hmm_regime_prob" in result
        assert 0 <= result["hmm_regime_prob"] <= 1.0

    def test_empty_insufficient_input(self):
        """Returns {} for empty or insufficient data."""
        from src.intelligence.smart_money.hmm_regime import HMMRegimePlugin

        plugin = HMMRegimePlugin()
        assert plugin.compute_full({"main": None}) == {}
        assert plugin.compute_full({}) == {}

        # Fewer than min_lookback (20) bars
        df = make_ohlcv(np.full(10, 5000.0))
        assert plugin.compute_full({"main": df}) == {}
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/intelligence/test_smart_money_plugins.py::TestHMMRegime -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError` (hmm_regime doesn't exist yet)

**Step 3: Commit failing tests**

```bash
git add tests/unit/intelligence/test_smart_money_plugins.py
git commit -m "test: add 6 failing tests for HMM regime plugin"
```

---

### Task 2: Implement HMM regime plugin

**Files:**
- Create: `src/intelligence/smart_money/hmm_regime.py`

**Step 1: Create the HMM regime plugin**

Create `src/intelligence/smart_money/hmm_regime.py` with this content:

```python
from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..plugins import InputSpec

# Default parameters — sensible starting points for 1m futures bars.
# Override via config/hmm_parameters.json if trained on your data.

_DEFAULT_TRANSITION = np.array(
    [
        [0.95, 0.025, 0.025],  # Ranging stays ranging 95%
        [0.03, 0.94, 0.03],  # Trending-up stays 94%
        [0.03, 0.03, 0.94],  # Trending-down stays 94%
    ]
)

_DEFAULT_MEANS = np.array(
    [
        [0.0, 0.005, 0.0, 0.3, 0.0],  # Ranging
        [0.001, 0.008, 0.3, 0.5, 0.2],  # Trending up
        [-0.001, 0.012, -0.3, 0.5, -0.2],  # Trending down
    ]
)

_DEFAULT_VARIANCES = np.array(
    [
        [0.0001, 0.001, 0.04, 0.04, 0.04],  # Ranging: tight
        [0.0002, 0.002, 0.06, 0.06, 0.06],  # Up: moderate
        [0.0003, 0.003, 0.06, 0.06, 0.06],  # Down: wider
    ]
)

_CONFIG_PATH = Path("config/hmm_parameters.json")


def _load_parameters() -> (
    tuple[np.ndarray, np.ndarray, np.ndarray]
):
    """Load parameters from JSON if available, otherwise use defaults."""
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH) as f:
            data = json.load(f)
        return (
            np.array(data["transition_matrix"], dtype=float),
            np.array(data["emission_means"], dtype=float),
            np.array(data["emission_variances"], dtype=float),
        )
    return _DEFAULT_TRANSITION.copy(), _DEFAULT_MEANS.copy(), _DEFAULT_VARIANCES.copy()


def _diag_gaussian_log_prob(
    x: np.ndarray, means: np.ndarray, variances: np.ndarray
) -> np.ndarray:
    """Log probability of x under each of K diagonal Gaussians.

    Args:
        x: observation vector (D,)
        means: (K, D) mean vectors
        variances: (K, D) variance vectors (diagonal covariance)

    Returns:
        (K,) log probabilities
    """
    D = len(x)
    diff = x - means  # (K, D)
    log_probs = -0.5 * np.sum(diff * diff / variances, axis=1)
    log_probs -= 0.5 * np.sum(np.log(variances), axis=1)
    log_probs -= 0.5 * D * math.log(2 * math.pi)
    return log_probs


@dataclass
class HMMRegimePlugin:
    """Hidden Markov Model regime classifier.

    Classifies market into 3 regimes (ranging/trending-up/trending-down)
    using multivariate Gaussian emissions on 5 features. Runs the forward
    algorithm incrementally per bar.
    """

    name: str = "smc_HMMRegime"
    outputs: set[str] = frozenset(
        {
            "hmm_regime",
            "hmm_regime_prob",
            "hmm_prob_ranging",
            "hmm_prob_trending_up",
            "hmm_prob_trending_down",
            "hmm_regime_duration",
        }
    )
    min_lookback: int = 20
    supports_incremental: bool = True
    capability_tags: set[str] = frozenset({"smart_money"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=200),)
    vol_window: int = 20  # Rolling window for realized vol
    _state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._A, self._means, self._variances = _load_parameters()
        self._K = self._A.shape[0]  # Number of states (3)

    def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}

        close = df["close"].to_numpy(dtype=float)

        # Compute log returns
        with np.errstate(divide="ignore", invalid="ignore"):
            ratios = close[1:] / close[:-1]
            ratios = np.where(ratios > 0, ratios, 1e-10)
            returns = np.log(ratios)

        if len(returns) < self.vol_window:
            return {}

        # Determine feature dimensions
        features = frames.get("features")
        n_dims = self._resolve_dims(features)

        # Initialize state
        self._reset_state()

        # Process all bars through forward algorithm
        for i in range(len(returns)):
            obs = self._build_observation(
                returns[i],
                returns[max(0, i - self.vol_window + 1) : i + 1],
                features,
                n_dims,
            )
            self._forward_step(obs, n_dims)

        self._state["prev_close"] = float(close[-1])

        return self._build_output()

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        if not self._state or "alpha" not in self._state:
            return self.compute_full(windows)

        df = windows.get("main")
        if df is None or len(df) < 2:
            return self.compute_full(windows)

        close = df["close"].to_numpy(dtype=float)
        current_close = float(close[-1])
        prev_close = self._state.get("prev_close", current_close)

        if prev_close <= 0 or current_close <= 0:
            return self.compute_full(windows)

        ret = math.log(current_close / prev_close)
        self._state["return_buffer"].append(ret)

        features = windows.get("features")
        n_dims = self._resolve_dims(features)
        buf = list(self._state["return_buffer"])
        obs = self._build_observation(ret, buf, features, n_dims)
        self._forward_step(obs, n_dims)

        self._state["prev_close"] = current_close

        return self._build_output()

    def _resolve_dims(self, features: Any) -> int:
        """Determine how many emission dimensions to use."""
        if not isinstance(features, dict):
            return 2  # Fallback: log return + realized vol only
        rsi = features.get("rsi_14")
        adx = features.get("adx_14")
        atr = features.get("atr_14")
        macd_hist = features.get("macd_hist_12_26_9")
        if rsi is not None and adx is not None and atr is not None and macd_hist is not None:
            return 5
        return 2

    def _build_observation(
        self,
        log_return: float,
        return_window: list | np.ndarray,
        features: Any,
        n_dims: int,
    ) -> np.ndarray:
        """Build the observation vector (2D or 5D)."""
        realized_vol = float(np.std(return_window)) if len(return_window) >= 2 else 0.005
        obs = np.array([log_return, realized_vol])

        if n_dims == 5 and isinstance(features, dict):
            rsi_norm = (float(features["rsi_14"]) - 50.0) / 50.0
            adx_norm = float(features["adx_14"]) / 50.0
            atr = float(features["atr_14"])
            macd_hist = float(features["macd_hist_12_26_9"])
            macd_norm = macd_hist / atr if atr > 0 else 0.0
            obs = np.array([log_return, realized_vol, rsi_norm, adx_norm, macd_norm])

        return obs

    def _forward_step(self, obs: np.ndarray, n_dims: int) -> None:
        """One step of the forward algorithm."""
        alpha = self._state["alpha"]
        A = self._A

        # Slice parameters to match observation dimensionality
        means = self._means[:, :n_dims]
        variances = self._variances[:, :n_dims]

        # Emission log-probabilities
        log_emit = _diag_gaussian_log_prob(obs, means, variances)

        # Forward update: alpha_new[k] = sum_j(alpha[j] * A[j,k]) * P(x|k)
        # Work in log space for numerical stability
        log_alpha = np.log(np.maximum(alpha, 1e-300))
        log_alpha_new = np.zeros(self._K)
        for k in range(self._K):
            log_trans = log_alpha + np.log(np.maximum(A[:, k], 1e-300))
            max_lt = np.max(log_trans)
            log_alpha_new[k] = max_lt + math.log(np.sum(np.exp(log_trans - max_lt)))
        log_alpha_new += log_emit

        # Normalize in log space
        max_la = np.max(log_alpha_new)
        alpha_new = np.exp(log_alpha_new - max_la)
        total = np.sum(alpha_new)
        if total > 0:
            alpha_new /= total

        # Track regime changes
        new_regime = int(np.argmax(alpha_new))
        prev_regime = self._state["prev_regime"]
        if new_regime == prev_regime:
            self._state["regime_duration"] += 1
        else:
            self._state["regime_duration"] = 1
            self._state["prev_regime"] = new_regime

        self._state["alpha"] = alpha_new

    def _reset_state(self) -> None:
        """Initialize forward algorithm state."""
        self._state = {
            "alpha": np.full(self._K, 1.0 / self._K),  # Uniform prior
            "prev_close": 0.0,
            "return_buffer": deque(maxlen=self.vol_window),
            "prev_regime": 0,
            "regime_duration": 1,
        }

    def _build_output(self) -> dict[str, Any]:
        """Build output dict from current state."""
        alpha = self._state["alpha"]
        regime = int(np.argmax(alpha))
        return {
            "hmm_regime": float(regime),
            "hmm_regime_prob": round(float(alpha[regime]), 6),
            "hmm_prob_ranging": round(float(alpha[0]), 6),
            "hmm_prob_trending_up": round(float(alpha[1]), 6),
            "hmm_prob_trending_down": round(float(alpha[2]), 6),
            "hmm_regime_duration": float(self._state["regime_duration"]),
        }


plugin = HMMRegimePlugin()
```

**Step 2: Run the tests**

Run: `python -m pytest tests/unit/intelligence/test_smart_money_plugins.py::TestHMMRegime -v`
Expected: 6/6 PASS

**Step 3: Lint check**

Run: `.venv/bin/ruff check src/intelligence/smart_money/hmm_regime.py`
Expected: All checks passed

**Step 4: Commit**

```bash
git add src/intelligence/smart_money/hmm_regime.py tests/unit/intelligence/test_smart_money_plugins.py
git commit -m "feat: add HMM regime detection plugin with 6 tests

Multivariate Gaussian HMM (3 states, 5D emissions) classifies market
as ranging/trending-up/trending-down with probabilistic confidence.
Pure numpy, hardcoded defaults with optional JSON override."
```

---

### Task 3: Register plugin + final verification

**Files:**
- Modify: `src/intelligence/register_plugins.py` (add import + registration)

**Step 1: Add import and registration**

In `src/intelligence/register_plugins.py`:

Add import after the `bocpd_plugin` import (line 27):
```python
from .smart_money.hmm_regime import plugin as hmm_plugin
```

Add registration after `registry.register_pattern(bocpd_plugin)` (line 72):
```python
    registry.register_pattern(hmm_plugin)
```

**Step 2: Verify registration count**

Run: `python -c "from src.intelligence.register_plugins import register_all_plugins; from src.intelligence.plugins import registry; register_all_plugins(); print(f'Indicators: {len(registry.indicators)}, Patterns: {len(registry.patterns)}, Total: {len(registry.indicators) + len(registry.patterns)}')"`
Expected: `Indicators: 16, Patterns: 16, Total: 32`

**Step 3: Run full unit test suite**

Run: `python -m pytest tests/unit/ -v --tb=short`
Expected: 166+ tests passing, 0 failures

**Step 4: Lint check**

Run: `.venv/bin/ruff check src/intelligence/smart_money/hmm_regime.py src/intelligence/register_plugins.py`
Expected: All checks passed

**Step 5: Commit**

```bash
git add src/intelligence/register_plugins.py
git commit -m "feat: register HMM regime plugin (32 total plugins)"
```
