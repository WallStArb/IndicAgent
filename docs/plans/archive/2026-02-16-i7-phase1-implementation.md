# I7 Phase 1: Signal Generation Foundation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build the I7 signal generation tier with 5 regime-adaptive setup plugins, signal schema, stream publishing, SSE distribution, and dashboard signal panel.

**Architecture:** I7 plugins follow the existing `PatternPlugin` protocol (dataclass with `compute_full`/`compute_next`). Each setup plugin reads I1-I6 outputs from `frames["features"]` and returns signal fields. Signals publish to `env:signals:SYMBOL:TIMEFRAME` Redis Streams and flow to the dashboard via SSE.

**Tech Stack:** Python 3.13, dataclasses, numpy, pandas, Redis Streams, FastAPI SSE, Next.js 15 / React 19

---

## Task 1: Signal Schema & Stream Key

**Files:**
- Modify: `src/core/stream_keys.py`
- Create: `tests/unit/core/test_stream_keys_signals.py`

**Step 1: Write the failing test**

```python
# tests/unit/core/test_stream_keys_signals.py
"""Tests for signal stream key helpers."""

from src.core.stream_keys import signals, signals_pattern, get_stream_maxlen


def test_signals_key_with_prefix():
    assert signals("dev:", "ES", "5m") == "dev:signals:ES:5m"


def test_signals_key_no_prefix():
    assert signals("", "NQ", "1h") == "signals:NQ:1h"


def test_signals_pattern():
    assert signals_pattern("dev:") == "dev:signals:*:*"


def test_signals_maxlen():
    assert get_stream_maxlen("1m", "signals") == 500
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/core/test_stream_keys_signals.py -v`
Expected: FAIL — `signals` not importable

**Step 3: Write minimal implementation**

Add to `src/core/stream_keys.py`:

```python
def signals(env_prefix: str, symbol: str, timeframe: str) -> str:
    return f"{env_prefix}signals:{symbol}:{timeframe}"


def signals_pattern(env_prefix: str) -> str:
    return f"{env_prefix}signals:*:*"
```

And update `get_stream_maxlen` to handle the `"signals"` kind:

```python
def get_stream_maxlen(
    timeframe: str, kind: Literal["ticks", "market", "indicators", "intelligence", "signals"]
) -> int:
    # ... existing cases ...
    if kind == "signals":
        return 500
    return 1000
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/core/test_stream_keys_signals.py -v`
Expected: 4 PASS

**Step 5: Commit**

```bash
git add src/core/stream_keys.py tests/unit/core/test_stream_keys_signals.py
git commit -m "feat(i7): add signal stream key helpers"
```

---

## Task 2: Shared Test Utilities & Signal Validation Helper

**Files:**
- Create: `tests/unit/intelligence/conftest.py`
- Create: `src/intelligence/trading/__init__.py`
- Create: `src/intelligence/trading/signal_schema.py`
- Create: `tests/unit/intelligence/test_signal_schema.py`

**Step 1: Create conftest with shared OHLCV builders**

Extract the `make_ohlcv` helper that's duplicated across test files into a shared conftest:

```python
# tests/unit/intelligence/conftest.py
"""Shared test fixtures for intelligence plugin tests."""

import numpy as np
import pandas as pd
import pytest


@pytest.fixture()
def make_ohlcv():
    """Factory fixture: build OHLCV DataFrame from close array."""
    def _make(close: np.ndarray, volume: np.ndarray | None = None) -> pd.DataFrame:
        n = len(close)
        spread = np.abs(close) * 0.002
        high = close + spread
        low = close - spread
        open_ = close + np.random.default_rng(0).normal(0, 0.001, n) * close
        high = np.maximum(high, np.maximum(open_, close))
        low = np.minimum(low, np.minimum(open_, close))
        if volume is None:
            volume = np.full(n, 1000.0)
        return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})
    return _make
```

**Step 2: Write signal validation test**

```python
# tests/unit/intelligence/test_signal_schema.py
"""Tests for signal schema validation."""

from src.intelligence.trading.signal_schema import validate_signal, REQUIRED_SIGNAL_FIELDS


def test_valid_signal_passes():
    signal = {
        "type": "signal.v1",
        "symbol": "ES",
        "timeframe": "5m",
        "timestamp": "2026-02-16T14:30:00Z",
        "signal_type": "trend_long",
        "setup_plugin": "trad_TrendFollowing",
        "direction": 1,
        "entry_price": 5100.0,
        "stop_loss": 5090.0,
        "targets": [5110.0, 5120.0, 5130.0],
        "confidence": 0.75,
        "risk_reward_ratio": 2.0,
        "regime_context": "bullish",
        "confluence_score": 0.82,
        "supporting_factors": ["trend_regime_bullish", "ctf_aligned"],
        "invalidation_conditions": ["price_below_5085"],
        "ttl_bars": 10,
    }
    assert validate_signal(signal) is True


def test_missing_field_fails():
    signal = {"type": "signal.v1", "symbol": "ES"}
    assert validate_signal(signal) is False


def test_confidence_out_of_range_fails():
    signal = _make_valid_signal()
    signal["confidence"] = 1.5
    assert validate_signal(signal) is False


def test_direction_must_be_plus_minus_one():
    signal = _make_valid_signal()
    signal["direction"] = 0
    assert validate_signal(signal) is False


def _make_valid_signal() -> dict:
    return {
        "type": "signal.v1",
        "symbol": "ES",
        "timeframe": "5m",
        "timestamp": "2026-02-16T14:30:00Z",
        "signal_type": "trend_long",
        "setup_plugin": "trad_TrendFollowing",
        "direction": 1,
        "entry_price": 5100.0,
        "stop_loss": 5090.0,
        "targets": [5110.0],
        "confidence": 0.75,
        "risk_reward_ratio": 2.0,
        "regime_context": "bullish",
        "confluence_score": 0.82,
        "supporting_factors": [],
        "invalidation_conditions": [],
        "ttl_bars": 10,
    }
```

**Step 3: Run test to verify it fails**

Run: `python -m pytest tests/unit/intelligence/test_signal_schema.py -v`
Expected: FAIL — module not found

**Step 4: Implement signal schema**

```python
# src/intelligence/trading/__init__.py
"""I7 Trading Intelligence — setup detection and signal generation."""

# src/intelligence/trading/signal_schema.py
"""Signal v1 schema definition and validation."""

from __future__ import annotations

REQUIRED_SIGNAL_FIELDS = frozenset({
    "type", "symbol", "timeframe", "timestamp", "signal_type",
    "setup_plugin", "direction", "entry_price", "stop_loss", "targets",
    "confidence", "risk_reward_ratio", "regime_context", "confluence_score",
    "supporting_factors", "invalidation_conditions", "ttl_bars",
})


def validate_signal(signal: dict) -> bool:
    """Validate a signal.v1 dictionary. Returns True if valid."""
    if not isinstance(signal, dict):
        return False
    # Required fields present
    if not REQUIRED_SIGNAL_FIELDS.issubset(signal.keys()):
        return False
    # Type check
    if signal.get("type") != "signal.v1":
        return False
    # Confidence in range
    conf = signal.get("confidence")
    if not isinstance(conf, (int, float)) or conf < 0.0 or conf > 1.0:
        return False
    # Direction must be +1 or -1
    direction = signal.get("direction")
    if direction not in (1, -1, 1.0, -1.0):
        return False
    # Targets must be a non-empty list
    targets = signal.get("targets")
    if not isinstance(targets, list) or len(targets) == 0:
        return False
    return True


def make_signal(
    *,
    symbol: str,
    timeframe: str,
    timestamp: str,
    signal_type: str,
    setup_plugin: str,
    direction: int,
    entry_price: float,
    stop_loss: float,
    targets: list[float],
    confidence: float,
    regime_context: str,
    confluence_score: float,
    supporting_factors: list[str],
    invalidation_conditions: list[str],
    ttl_bars: int = 10,
) -> dict:
    """Construct a validated signal.v1 dict."""
    rr = abs(targets[0] - entry_price) / abs(entry_price - stop_loss) if entry_price != stop_loss else 0.0
    signal = {
        "type": "signal.v1",
        "symbol": symbol,
        "timeframe": timeframe,
        "timestamp": timestamp,
        "signal_type": signal_type,
        "setup_plugin": setup_plugin,
        "direction": direction,
        "entry_price": round(entry_price, 2),
        "stop_loss": round(stop_loss, 2),
        "targets": [round(t, 2) for t in targets],
        "confidence": round(min(1.0, max(0.0, confidence)), 4),
        "risk_reward_ratio": round(rr, 2),
        "regime_context": regime_context,
        "confluence_score": round(confluence_score, 4),
        "supporting_factors": supporting_factors,
        "invalidation_conditions": invalidation_conditions,
        "ttl_bars": ttl_bars,
    }
    return signal
```

**Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/unit/intelligence/test_signal_schema.py -v`
Expected: 4 PASS

**Step 6: Commit**

```bash
git add src/intelligence/trading/ tests/unit/intelligence/conftest.py tests/unit/intelligence/test_signal_schema.py
git commit -m "feat(i7): add signal schema, validation, and trading module"
```

---

## Task 3: TrendFollowing Setup Plugin

**Files:**
- Create: `src/intelligence/trading/trend_following.py`
- Create: `tests/unit/intelligence/test_trading_setups.py`

**Context:** This plugin reads I3 structure (swing patterns, trend strength), I4 regime (trend_regime, trend_confidence), and I6 confluence (ctf_score) from `frames["features"]`. It fires when regime is bullish/bearish with sufficient confidence, and structure confirms.

**Step 1: Write failing tests**

```python
# tests/unit/intelligence/test_trading_setups.py
"""Tests for I7 trading setup plugins."""

import numpy as np
import pandas as pd


def make_ohlcv(close: np.ndarray, volume: np.ndarray | None = None) -> pd.DataFrame:
    n = len(close)
    spread = np.abs(close) * 0.002
    high = close + spread
    low = close - spread
    open_ = close + np.random.default_rng(0).normal(0, 0.001, n) * close
    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))
    if volume is None:
        volume = np.full(n, 1000.0)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


# ─── TrendFollowing ──────────────────────────────────────────────

class TestTrendFollowing:
    def test_bullish_signal_in_uptrend(self):
        """Strong bullish regime + confirming structure → long signal."""
        from src.intelligence.trading.trend_following import TrendFollowingPlugin

        # Uptrending price
        close = np.linspace(5000, 5200, 100)
        df = make_ohlcv(close)
        features = {
            "trend_regime": 0.8,       # Strong bullish
            "trend_confidence": 0.75,
            "swing_pattern": 1.0,      # HH/HL
            "trend_strength": 0.7,
            "ctf_score": 0.6,
            "atr_14": 10.0,
            "sma_20": 5180.0,
            "ema_21": 5185.0,
        }
        plugin = TrendFollowingPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type") == "trend_long"
        assert result.get("direction") == 1
        assert 0.0 < result.get("confidence", 0) <= 1.0
        assert result.get("entry_price", 0) > 0
        assert result.get("stop_loss", 0) < result["entry_price"]
        assert len(result.get("targets", [])) >= 1

    def test_bearish_signal_in_downtrend(self):
        """Strong bearish regime + confirming structure → short signal."""
        from src.intelligence.trading.trend_following import TrendFollowingPlugin

        close = np.linspace(5200, 5000, 100)
        df = make_ohlcv(close)
        features = {
            "trend_regime": -0.8,
            "trend_confidence": 0.75,
            "swing_pattern": -1.0,     # LH/LL
            "trend_strength": -0.7,
            "ctf_score": -0.6,
            "atr_14": 10.0,
            "sma_20": 5020.0,
            "ema_21": 5015.0,
        }
        plugin = TrendFollowingPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type") == "trend_short"
        assert result.get("direction") == -1
        assert result.get("stop_loss", 0) > result["entry_price"]

    def test_no_signal_in_weak_regime(self):
        """Weak/neutral regime → no signal generated."""
        from src.intelligence.trading.trend_following import TrendFollowingPlugin

        close = np.full(100, 5100.0) + np.random.default_rng(0).normal(0, 2, 100)
        df = make_ohlcv(close)
        features = {
            "trend_regime": 0.2,       # Weak, below threshold
            "trend_confidence": 0.3,
            "swing_pattern": 0.0,
            "trend_strength": 0.1,
            "ctf_score": 0.1,
            "atr_14": 10.0,
            "sma_20": 5100.0,
            "ema_21": 5100.0,
        }
        plugin = TrendFollowingPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"
        assert result.get("direction", 0) == 0

    def test_insufficient_data_returns_empty(self):
        """Too few bars → empty result."""
        from src.intelligence.trading.trend_following import TrendFollowingPlugin

        close = np.array([5000.0, 5001.0, 5002.0])
        df = make_ohlcv(close)
        plugin = TrendFollowingPlugin()
        result = plugin.compute_full({"main": df, "features": {}})
        assert result == {} or result.get("signal_type", "none") == "none"
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/intelligence/test_trading_setups.py::TestTrendFollowing -v`
Expected: FAIL — module not found

**Step 3: Implement TrendFollowing plugin**

```python
# src/intelligence/trading/trend_following.py
"""I7 Trend Following setup detection plugin."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec


@dataclass
class TrendFollowingPlugin:
    """Trend-following setup: fires when regime = trending with structure confirmation.

    Reads I4 trend_regime, I3 swing_pattern/trend_strength, I6 ctf_score.
    Entry on pullback to EMA, stop below last swing, ATR-based targets.
    """

    name: str = "trad_TrendFollowing"
    outputs: set[str] = frozenset({
        "signal_type", "direction", "entry_price", "stop_loss",
        "targets", "confidence", "regime_context", "supporting_factors",
    })
    min_lookback: int = 50
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"trading", "trend"})
    inputs: list[InputSpec] = (InputSpec(symbol=".*", timeframe="1m", lookback=100),)

    # Thresholds (configurable)
    regime_threshold: float = 0.5       # Min |trend_regime| to consider
    confidence_threshold: float = 0.4   # Min trend_confidence to consider
    atr_stop_multiplier: float = 1.5    # Stop = entry ± ATR * multiplier
    atr_target_multipliers: tuple = (1.0, 2.0, 3.0)  # T1, T2, T3 in ATR units

    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        if df is None or len(df) < self.min_lookback:
            return {}

        trend_regime = features.get("trend_regime", 0.0)
        trend_conf = features.get("trend_confidence", 0.0)
        swing_pattern = features.get("swing_pattern", 0.0)
        trend_strength = features.get("trend_strength", 0.0)
        ctf_score = features.get("ctf_score", 0.0)
        atr = features.get("atr_14", 0.0)

        # Gate: regime must be strong enough
        if abs(trend_regime) < self.regime_threshold or trend_conf < self.confidence_threshold:
            return self._no_signal()

        # Gate: structure must confirm direction
        direction = 1 if trend_regime > 0 else -1
        if direction == 1 and swing_pattern <= 0:
            return self._no_signal()
        if direction == -1 and swing_pattern >= 0:
            return self._no_signal()

        close = df["close"].to_numpy(dtype=float)
        price = float(close[-1])
        low = df["low"].to_numpy(dtype=float)
        high = df["high"].to_numpy(dtype=float)

        if atr <= 0:
            atr = float(np.mean(high[-14:] - low[-14:]))
        if atr <= 0:
            return self._no_signal()

        # Entry: current price (at bar close)
        entry = price

        # Stop: ATR-based from entry
        if direction == 1:
            stop = entry - atr * self.atr_stop_multiplier
            targets = [round(entry + atr * m, 2) for m in self.atr_target_multipliers]
        else:
            stop = entry + atr * self.atr_stop_multiplier
            targets = [round(entry - atr * m, 2) for m in self.atr_target_multipliers]

        # Confidence: weighted blend
        raw_conf = (
            0.35 * min(1.0, abs(trend_regime))
            + 0.25 * min(1.0, trend_conf)
            + 0.20 * min(1.0, abs(trend_strength))
            + 0.20 * min(1.0, abs(ctf_score))
        )
        confidence = round(min(1.0, max(0.0, raw_conf)), 4)

        supporting = []
        if abs(trend_regime) >= 0.7:
            supporting.append("strong_trend_regime")
        if abs(ctf_score) >= 0.5:
            supporting.append("cross_timeframe_aligned")
        if abs(swing_pattern) >= 0.5:
            supporting.append("structure_confirmed")

        signal_type = "trend_long" if direction == 1 else "trend_short"
        regime_ctx = "bullish" if direction == 1 else "bearish"

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


plugin = TrendFollowingPlugin()
```

**Step 4: Run tests**

Run: `python -m pytest tests/unit/intelligence/test_trading_setups.py::TestTrendFollowing -v`
Expected: 4 PASS

**Step 5: Commit**

```bash
git add src/intelligence/trading/trend_following.py tests/unit/intelligence/test_trading_setups.py
git commit -m "feat(i7): add TrendFollowing setup plugin with tests"
```

---

## Task 4: MeanReversion Setup Plugin

**Files:**
- Create: `src/intelligence/trading/mean_reversion.py`
- Modify: `tests/unit/intelligence/test_trading_setups.py` (append tests)

**Context:** Fires when regime = ranging. Reads I4 vol_regime, I3 S/R levels, I5 RSI divergence, I1 RSI/BB.

**Step 1: Write failing tests**

Append to `tests/unit/intelligence/test_trading_setups.py`:

```python
# ─── MeanReversion ──────────────────────────────────────────────

class TestMeanReversion:
    def test_bullish_reversion_at_support(self):
        """Price at support + RSI divergence + ranging regime → long signal."""
        from src.intelligence.trading.mean_reversion import MeanReversionPlugin

        # Price dropping to support
        close = np.concatenate([np.linspace(5100, 5000, 80), np.linspace(5000, 5010, 20)])
        df = make_ohlcv(close)
        features = {
            "vol_regime": 1.0,          # Normal volatility (ranging)
            "trend_regime": 0.1,        # Weak/no trend
            "rsi_14": 28.0,             # Oversold
            "rsi_div_bullish": 0.6,     # Bullish divergence present
            "bb_lower": 4995.0,         # At lower BB
            "bb_middle": 5050.0,
            "sr_nearest_support": 5000.0,
            "sr_nearest_resistance": 5100.0,
            "atr_14": 8.0,
            "ctf_score": 0.2,
        }
        plugin = MeanReversionPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type") == "reversion_long"
        assert result.get("direction") == 1
        assert result.get("confidence", 0) > 0

    def test_bearish_reversion_at_resistance(self):
        """Price at resistance + overbought → short signal."""
        from src.intelligence.trading.mean_reversion import MeanReversionPlugin

        close = np.concatenate([np.linspace(5000, 5100, 80), np.linspace(5100, 5095, 20)])
        df = make_ohlcv(close)
        features = {
            "vol_regime": 1.0,
            "trend_regime": -0.1,
            "rsi_14": 75.0,
            "rsi_div_bearish": 0.5,
            "bb_upper": 5105.0,
            "bb_middle": 5050.0,
            "sr_nearest_support": 5000.0,
            "sr_nearest_resistance": 5100.0,
            "atr_14": 8.0,
            "ctf_score": -0.2,
        }
        plugin = MeanReversionPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type") == "reversion_short"
        assert result.get("direction") == -1

    def test_no_signal_in_trending_regime(self):
        """Strong trend → mean reversion should not fire."""
        from src.intelligence.trading.mean_reversion import MeanReversionPlugin

        close = np.linspace(5000, 5200, 100)
        df = make_ohlcv(close)
        features = {
            "vol_regime": 1.0,
            "trend_regime": 0.8,        # Strong trend — not ranging
            "rsi_14": 65.0,
            "rsi_div_bullish": 0.0,
            "atr_14": 10.0,
            "ctf_score": 0.7,
        }
        plugin = MeanReversionPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/intelligence/test_trading_setups.py::TestMeanReversion -v`
Expected: FAIL

**Step 3: Implement MeanReversion plugin**

Create `src/intelligence/trading/mean_reversion.py` following the same dataclass pattern as TrendFollowing. Key logic:
- Gate: `|trend_regime| < 0.4` (must NOT be trending)
- Gate: RSI extreme (< 35 for longs, > 65 for shorts) OR RSI divergence > 0.3
- Entry: current price
- Stop: beyond S/R level + ATR buffer
- Targets: BB middle (T1), opposite S/R (T2)
- Confidence: weighted from RSI extreme, divergence strength, vol regime stability, S/R proximity

**Step 4: Run tests**

Run: `python -m pytest tests/unit/intelligence/test_trading_setups.py::TestMeanReversion -v`
Expected: 3 PASS

**Step 5: Commit**

```bash
git add src/intelligence/trading/mean_reversion.py tests/unit/intelligence/test_trading_setups.py
git commit -m "feat(i7): add MeanReversion setup plugin with tests"
```

---

## Task 5: LiquiditySweepReclaim Setup Plugin

**Files:**
- Create: `src/intelligence/trading/liquidity_sweep_reclaim.py`
- Modify: `tests/unit/intelligence/test_trading_setups.py` (append tests)

**Context:** Highest-conviction SMC setup. Reads I6 sweep_detected, sweep_type, sweep_reclaimed, FVG data, order block data. Fires when a sweep is detected AND reclaimed with FVG/OB at the reclaim zone.

**Step 1: Write failing tests**

```python
# ─── LiquiditySweepReclaim ──────────────────────────────────────

class TestLiquiditySweepReclaim:
    def test_bullish_sweep_reclaim_signal(self):
        """Bullish sweep + reclaimed + FVG → long signal."""
        from src.intelligence.trading.liquidity_sweep_reclaim import LiquiditySweepReclaimPlugin

        close = np.concatenate([
            np.full(60, 5050.0),
            np.array([5020.0, 5010.0, 5000.0]),  # Sweep down
            np.array([5030.0, 5045.0, 5055.0]),   # Reclaim up
            np.full(34, 5060.0),
        ])
        df = make_ohlcv(close)
        features = {
            "sweep_detected": 1.0,
            "sweep_type": 1.0,         # Bullish sweep
            "sweep_level": 5020.0,
            "sweep_reclaimed": 1.0,
            "sweep_depth_pct": 0.4,
            "fvg_detected": 1.0,
            "fvg_type": 1.0,           # Bullish FVG
            "fvg_top": 5055.0,
            "fvg_bottom": 5040.0,
            "ob_detected": 1.0,
            "ob_type": 1.0,
            "trend_regime": 0.3,
            "atr_14": 12.0,
            "ctf_score": 0.4,
        }
        plugin = LiquiditySweepReclaimPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type") == "sweep_reclaim_long"
        assert result.get("direction") == 1
        assert result.get("confidence", 0) > 0.5  # High conviction setup

    def test_no_signal_without_reclaim(self):
        """Sweep detected but NOT reclaimed → no signal."""
        from src.intelligence.trading.liquidity_sweep_reclaim import LiquiditySweepReclaimPlugin

        close = np.full(100, 5050.0)
        df = make_ohlcv(close)
        features = {
            "sweep_detected": 1.0,
            "sweep_type": 1.0,
            "sweep_reclaimed": 0.0,     # Not reclaimed
            "atr_14": 12.0,
        }
        plugin = LiquiditySweepReclaimPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"

    def test_no_signal_without_sweep(self):
        """No sweep detected → no signal."""
        from src.intelligence.trading.liquidity_sweep_reclaim import LiquiditySweepReclaimPlugin

        close = np.full(100, 5050.0)
        df = make_ohlcv(close)
        features = {"sweep_detected": 0.0, "atr_14": 12.0}
        plugin = LiquiditySweepReclaimPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/unit/intelligence/test_trading_setups.py::TestLiquiditySweepReclaim -v`

**Step 3: Implement plugin**

Create `src/intelligence/trading/liquidity_sweep_reclaim.py`. Key logic:
- Gate: `sweep_detected == 1.0` AND `sweep_reclaimed == 1.0`
- Direction: from `sweep_type` (+1 bullish, -1 bearish)
- Confidence boost: if `fvg_detected` at reclaim zone (+0.15), if `ob_detected` at reclaim zone (+0.10)
- Entry: at FVG midpoint or current price
- Stop: beyond the sweep extreme (`sweep_level - ATR * 0.5` for longs)
- Targets: ATR-based from entry

**Step 4: Run tests, Step 5: Commit**

```bash
git add src/intelligence/trading/liquidity_sweep_reclaim.py tests/unit/intelligence/test_trading_setups.py
git commit -m "feat(i7): add LiquiditySweepReclaim setup plugin with tests"
```

---

## Task 6: MultiTimeframeAlignment Setup Plugin

**Files:**
- Create: `src/intelligence/trading/mtf_alignment.py`
- Modify: `tests/unit/intelligence/test_trading_setups.py` (append tests)

**Context:** Simplest setup — fires when I6 cross-timeframe confluence score exceeds threshold. The intelligence is already computed by `i6_CrossTimeframeConfluence`.

**Step 1: Write failing tests**

```python
# ─── MultiTimeframeAlignment ──────────────────────────────────

class TestMultiTimeframeAlignment:
    def test_strong_bullish_alignment(self):
        """CTF score > 0.7 + multiple TFs aligned → long signal."""
        from src.intelligence.trading.mtf_alignment import MTFAlignmentPlugin

        close = np.linspace(5000, 5100, 100)
        df = make_ohlcv(close)
        features = {
            "ctf_score": 0.85,
            "ctf_trend_alignment": 0.9,
            "ctf_structure_alignment": 0.8,
            "ctf_regime_agreement": 0.7,
            "ctf_timeframes_aligned": 3.0,
            "ctf_highest_aligned_tf": 60.0,  # 1h
            "trend_regime": 0.6,
            "atr_14": 10.0,
        }
        plugin = MTFAlignmentPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type") == "mtf_alignment_long"
        assert result.get("direction") == 1
        assert result.get("confidence", 0) >= 0.7

    def test_weak_alignment_no_signal(self):
        """CTF score < threshold → no signal."""
        from src.intelligence.trading.mtf_alignment import MTFAlignmentPlugin

        close = np.full(100, 5050.0)
        df = make_ohlcv(close)
        features = {
            "ctf_score": 0.3,           # Below threshold
            "ctf_timeframes_aligned": 1.0,
            "atr_14": 10.0,
        }
        plugin = MTFAlignmentPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"

    def test_minimum_timeframes_required(self):
        """High CTF score but only 1 TF aligned → no signal (need >= 2)."""
        from src.intelligence.trading.mtf_alignment import MTFAlignmentPlugin

        close = np.linspace(5000, 5100, 100)
        df = make_ohlcv(close)
        features = {
            "ctf_score": 0.8,
            "ctf_timeframes_aligned": 1.0,  # Only 1 TF
            "atr_14": 10.0,
        }
        plugin = MTFAlignmentPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"
```

**Step 2-5:** Same TDD cycle. Key implementation notes:
- Gate: `ctf_score > 0.7` AND `ctf_timeframes_aligned >= 2`
- Direction: sign of `ctf_score`
- Confidence: directly from `ctf_score` (already 0-1 range)
- Entry: current price. Stop/targets: ATR-based.

```bash
git commit -m "feat(i7): add MultiTimeframeAlignment setup plugin with tests"
```

---

## Task 7: SqueezeExpansion Setup Plugin

**Files:**
- Create: `src/intelligence/trading/squeeze_expansion.py`
- Modify: `tests/unit/intelligence/test_trading_setups.py` (append tests)

**Context:** Fires when BB squeeze (I5) resolves with volume expansion. Reads I5 `squeeze_active`/`squeeze_bars`, I4 momentum context for direction, I1 volume.

**Step 1: Write failing tests**

```python
# ─── SqueezeExpansion ──────────────────────────────────────────

class TestSqueezeExpansion:
    def test_bullish_squeeze_breakout(self):
        """Squeeze resolved + volume expansion + bullish momentum → long signal."""
        from src.intelligence.trading.squeeze_expansion import SqueezeExpansionPlugin

        # Tight range then breakout
        close = np.concatenate([np.full(80, 5050.0) + np.random.default_rng(0).normal(0, 2, 80),
                                np.linspace(5055, 5090, 20)])
        volume = np.concatenate([np.full(80, 1000.0), np.full(20, 2500.0)])  # Volume spike
        df = make_ohlcv(close, volume)
        features = {
            "squeeze_active": 0.0,      # Squeeze just released
            "squeeze_fired": 1.0,       # Squeeze was active recently
            "squeeze_bars": 15.0,       # Duration of squeeze
            "momentum_bias": 0.6,       # Bullish momentum
            "bb_upper": 5060.0,
            "bb_lower": 5040.0,
            "bb_middle": 5050.0,
            "atr_14": 8.0,
            "volume_sma_20": 1000.0,
        }
        plugin = SqueezeExpansionPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type") == "squeeze_long"
        assert result.get("direction") == 1

    def test_no_signal_during_active_squeeze(self):
        """Squeeze still active (not resolved) → no signal."""
        from src.intelligence.trading.squeeze_expansion import SqueezeExpansionPlugin

        close = np.full(100, 5050.0)
        df = make_ohlcv(close)
        features = {
            "squeeze_active": 1.0,      # Still in squeeze
            "squeeze_fired": 0.0,
            "momentum_bias": 0.0,
            "atr_14": 8.0,
        }
        plugin = SqueezeExpansionPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"

    def test_no_signal_without_volume_expansion(self):
        """Squeeze released but volume is low → no signal."""
        from src.intelligence.trading.squeeze_expansion import SqueezeExpansionPlugin

        close = np.concatenate([np.full(80, 5050.0), np.linspace(5055, 5070, 20)])
        volume = np.full(100, 500.0)  # Low volume throughout
        df = make_ohlcv(close, volume)
        features = {
            "squeeze_active": 0.0,
            "squeeze_fired": 1.0,
            "squeeze_bars": 15.0,
            "momentum_bias": 0.6,
            "atr_14": 8.0,
            "volume_sma_20": 1000.0,   # Current vol < SMA
        }
        plugin = SqueezeExpansionPlugin()
        result = plugin.compute_full({"main": df, "features": features})

        assert result.get("signal_type", "none") == "none"
```

**Step 2-5:** Same TDD cycle. Key implementation:
- Gate: `squeeze_fired == 1.0` AND `squeeze_active == 0.0` (just released)
- Gate: current volume > `volume_sma_20 * 1.3` (volume expansion)
- Direction: sign of `momentum_bias`
- Targets: measured move = `(bb_upper - bb_lower) * squeeze_bars / 10` projected from entry

```bash
git commit -m "feat(i7): add SqueezeExpansion setup plugin with tests"
```

---

## Task 8: Register I7 Plugins

**Files:**
- Modify: `src/intelligence/register_plugins.py`
- Create: `tests/unit/intelligence/test_i7_registration.py`

**Step 1: Write failing test**

```python
# tests/unit/intelligence/test_i7_registration.py
"""Tests for I7 plugin registration."""

from src.intelligence.plugins import PluginRegistry


def test_i7_plugins_registered():
    """All 5 Phase 1 I7 plugins should be in the registry after registration."""
    from src.intelligence.register_plugins import register_all_plugins
    from src.intelligence.plugins import registry

    # Reset registry for isolation
    registry.indicators.clear()
    registry.patterns.clear()
    register_all_plugins()

    expected_i7 = {
        "trad_TrendFollowing",
        "trad_MeanReversion",
        "trad_LiquiditySweepReclaim",
        "trad_MTFAlignment",
        "trad_SqueezeExpansion",
    }
    registered = set(registry.patterns.keys())
    assert expected_i7.issubset(registered), f"Missing: {expected_i7 - registered}"


def test_total_plugin_count():
    """Should have 33 existing + 5 I7 = 38 total plugins."""
    from src.intelligence.register_plugins import register_all_plugins
    from src.intelligence.plugins import registry

    registry.indicators.clear()
    registry.patterns.clear()
    register_all_plugins()

    total = len(registry.indicators) + len(registry.patterns)
    assert total == 38, f"Expected 38, got {total}"
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/intelligence/test_i7_registration.py -v`

**Step 3: Update register_plugins.py**

Add imports and registrations for all 5 I7 plugins:

```python
# Add to imports at top of register_plugins.py:
from .trading.trend_following import plugin as trend_follow_plugin
from .trading.mean_reversion import plugin as mean_revert_plugin
from .trading.liquidity_sweep_reclaim import plugin as liq_sweep_reclaim_plugin
from .trading.mtf_alignment import plugin as mtf_align_plugin
from .trading.squeeze_expansion import plugin as squeeze_exp_plugin

# Add to register_all_plugins(), after the ctf_plugin registration:
    # I7 Trading Setups
    registry.register_pattern(trend_follow_plugin)
    registry.register_pattern(mean_revert_plugin)
    registry.register_pattern(liq_sweep_reclaim_plugin)
    registry.register_pattern(mtf_align_plugin)
    registry.register_pattern(squeeze_exp_plugin)
```

**Step 4: Run tests**

Run: `python -m pytest tests/unit/intelligence/test_i7_registration.py -v`
Expected: 2 PASS

**Step 5: Run full test suite to verify no regressions**

Run: `python -m pytest tests/unit/ -v`
Expected: All 178 existing + ~20 new tests PASS

**Step 6: Commit**

```bash
git add src/intelligence/register_plugins.py tests/unit/intelligence/test_i7_registration.py
git commit -m "feat(i7): register 5 Phase 1 setup plugins (38 total)"
```

---

## Task 9: Signal Stream Publishing via SSE

**Files:**
- Modify: `src/api/routes/sse.py`
- Modify: `src/core/stream_keys.py` (already done in Task 1)

**Step 1: Update SSE to include signal streams**

In `src/api/routes/sse.py`, update `_build_stream_list` to include signal streams:

```python
from ...core.stream_keys import signals as sk_signals  # add import

def _build_stream_list(symbols: list[str], timeframe: str) -> list[str]:
    # ... existing code ...
    for sym in symbols:
        contract = _resolve_contract(sym)
        streams.append(sk_live_tick(env_prefix, contract))
        streams.append(sk_market(env_prefix, contract, timeframe))
        streams.append(sk_indicators(env_prefix, contract, timeframe))
        streams.append(sk_intelligence(env_prefix, contract, timeframe))
        streams.append(sk_signals(env_prefix, contract, timeframe))  # NEW
    return streams
```

Update `_event_name_for_stream` to handle signal streams:

```python
known_domains = {"ticks", "market", "indicators", "intelligence", "signals"}  # add signals
# ... existing logic ...
if candidate.startswith("signals:"):
    return "signal_data"
```

**Step 2: Commit**

```bash
git add src/api/routes/sse.py
git commit -m "feat(i7): wire signal streams into SSE distribution"
```

---

## Task 10: Lint, Full Test Suite, Update CLAUDE.md

**Step 1: Run linter**

```bash
.venv/bin/ruff check src/intelligence/trading/ tests/unit/intelligence/test_trading_setups.py tests/unit/intelligence/test_signal_schema.py --fix
```

**Step 2: Run full test suite**

```bash
python -m pytest tests/unit/ -v
```

Expected: All tests PASS (178 existing + ~25 new)

**Step 3: Update CLAUDE.md plugin counts**

Update the following in `CLAUDE.md`:
- Plugin count: 33 → 38
- Test count: 178 → ~203
- I7 status: "NOT IMPLEMENTED" → "5 Phase 1 plugins WORKING"
- Add I7 to completed phases table

**Step 4: Commit**

```bash
git add CLAUDE.md src/ tests/
git commit -m "feat(i7): Phase 1 complete — 5 setup plugins, signal schema, SSE distribution"
```

---

## Summary

| Task | What | Tests | Est. |
|------|------|-------|------|
| 1 | Signal stream keys | 4 | 5 min |
| 2 | Signal schema + validation | 4 | 10 min |
| 3 | TrendFollowing plugin | 4 | 15 min |
| 4 | MeanReversion plugin | 3 | 15 min |
| 5 | LiquiditySweepReclaim plugin | 3 | 15 min |
| 6 | MTFAlignment plugin | 3 | 10 min |
| 7 | SqueezeExpansion plugin | 3 | 15 min |
| 8 | Register plugins | 2 | 5 min |
| 9 | SSE signal distribution | 0 | 5 min |
| 10 | Lint + full suite + CLAUDE.md | 0 | 10 min |
| **Total** | **10 tasks** | **~26 tests** | |

**Next phase:** After Phase 1 is complete and validated, create a separate plan for Phase 2 (AI Layer: LLM abstraction + first two expert agents).
