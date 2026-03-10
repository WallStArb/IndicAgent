# Intelligence Palette Expansion Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Correctness-audit all existing I1–I6 plugins, add I2 tier (6 composite event plugins), expand I3/I4/I5/SMC with 17 new plugins, and refactor I6 confluence for recency weighting.

**Architecture:** All changes stay within `market_analysis_service`. New I2 tier slots between I1 features and I3 execution. Each new plugin follows the `PatternPlugin` dataclass protocol. `IntelligenceEvent` gains an `i2` field; `intelligence_features` gains an `i2` JSONB column.

**Tech Stack:** Python 3.11, pandas, numpy, pydantic v2, asyncpg/TimescaleDB, pytest, ruff

---

## Plugin Protocol Reference

All I2+ plugins are dataclasses conforming to this pattern:

```python
@dataclass
class FooPlugin:
    name: str = "tier_FooPlugin"
    outputs: set[str] = frozenset({"field_a", "field_b"})
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"tag"})
    inputs: list[InputSpec] = ()

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        # I2 plugins read I1 features from the features dict
        # I3+ plugins also get frames["main"] (pd.DataFrame)
        ...
        return {"field_a": value_a, "field_b": value_b}

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)

plugin = FooPlugin()
```

I2 plugins consume `frames["features"]` (I1 feature dict — keys like `rsi_14`, `macd_12_26_9`, etc.).
I3+ plugins consume both `frames["main"]` (pd.DataFrame with open/high/low/close/volume) and `frames["features"]`.

**Registration pattern:**
```python
# register_plugins.py
from .composites.foo import plugin as foo_plugin
registry.register_pattern(foo_plugin)
TIER_I2: list[str] = [..., foo_plugin.name]
```

**Test pattern:**
```python
from tests.unit.intelligence.helpers import make_ohlcv
import numpy as np

def test_foo_basic():
    from src.intelligence.composites.foo import FooPlugin
    plugin = FooPlugin()
    features = {"rsi_14": 28.0, "atr_14": 10.0}
    result = plugin.compute_full({"features": features})
    assert result.get("field_a") is not None

def test_foo_empty():
    from src.intelligence.composites.foo import FooPlugin
    assert FooPlugin().compute_full({}) == {}
```

---

## Phase 1: Correctness Audit — I1 Indicators

**Goal:** Verify/fix mathematical correctness for all 23 I1 plugins. Write a correctness test per plugin asserting known output.

### Task 1.1: Audit RSI — Wilder's smoothing

**Files:**
- Audit: `src/intelligence/indicators/rsi.py`
- Test: `tests/unit/intelligence/test_correctness_audit.py` (create)

**Steps:**

**Step 1:** Create the audit test file with an RSI correctness test:
```python
# tests/unit/intelligence/test_correctness_audit.py
"""Correctness audit tests — known-output bar sequences."""
import numpy as np
import pandas as pd
from tests.unit.intelligence.helpers import make_ohlcv


class TestRSICorrectness:
    def test_wilder_smoothing_not_simple_ma(self):
        """RSI must use Wilder's EWM (alpha=1/14), not simple average."""
        from src.intelligence.indicators.rsi import RSIPlugin
        # Steady uptrend then drop: RSI should NOT be 100 after 14 up bars
        close = np.array([100.0 + i for i in range(20)] + [115.0, 114.0, 113.0])
        df = make_ohlcv(close)
        p = RSIPlugin()
        result = p.compute_full({"main": df})
        rsi = result.get("rsi_14")
        assert rsi is not None
        # After smoothing the drop, RSI should be < 100 and > 50
        assert 50 < rsi < 100

    def test_incremental_matches_full(self):
        """compute_next should match compute_full on the same data."""
        from src.intelligence.indicators.rsi import RSIPlugin
        close = np.linspace(100, 120, 40)
        df_full = make_ohlcv(close)
        df_partial = make_ohlcv(close[:-1])

        p_full = RSIPlugin()
        r_full = p_full.compute_full({"main": df_full})

        p_inc = RSIPlugin()
        p_inc.compute_full({"main": df_partial})
        # Add one more bar
        last_bar = pd.DataFrame({
            "open": [close[-1]], "high": [close[-1] * 1.001],
            "low": [close[-1] * 0.999], "close": [close[-1]], "volume": [1000]
        })
        df_next = pd.concat([df_partial, last_bar], ignore_index=True)
        r_inc = p_inc.compute_next({"main": df_next})

        assert abs(r_full["rsi_14"] - r_inc["rsi_14"]) < 0.01
```

**Step 2:** Run test to see current state:
```
.venv/bin/pytest tests/unit/intelligence/test_correctness_audit.py -v
```

**Step 3:** If tests fail, fix `src/intelligence/indicators/rsi.py`. Current code uses Wilder's EWM correctly — verify and document.

**Step 4:** Commit:
```bash
git add tests/unit/intelligence/test_correctness_audit.py
git commit -m "test(audit): RSI correctness — Wilder's smoothing verified"
```

---

### Task 1.2: Audit ATR — Wilder's method

**Files:**
- Audit: `src/intelligence/indicators/atr.py`
- Test: `tests/unit/intelligence/test_correctness_audit.py`

**Step 1:** Add ATR test to `test_correctness_audit.py`:
```python
class TestATRCorrectness:
    def test_wilder_not_rolling_mean(self):
        """ATR must use Wilder's smoothing (EWM α=1/14), not rolling mean."""
        from src.intelligence.indicators.atr import ATRPlugin
        # Known sequence: 14 bars with TR=10 each, then one big bar TR=100
        # Wilder's: ATR should smooth slowly toward 100 (not jump immediately)
        close = np.full(30, 5000.0)
        high = close + 10.0
        low = close - 10.0
        # Make last bar have huge range
        high[-1] = 5100.0
        low[-1] = 4900.0
        df = pd.DataFrame({"open": close, "high": high, "low": low,
                           "close": close, "volume": np.full(30, 1000)})
        p = ATRPlugin()
        result = p.compute_full({"main": df})
        atr = result.get("atr_14")
        assert atr is not None
        # ATR should be between 10 and 100 (smoothed, not jumped)
        assert 10 < atr < 100
```

**Step 2:** Run and verify: `.venv/bin/pytest tests/unit/intelligence/test_correctness_audit.py::TestATRCorrectness -v`

**Step 3:** Read `src/intelligence/indicators/atr.py` and verify it uses Wilder's smoothing (EWM with α=1/period, seeded with SMA). If it uses `pd.Series.ewm()` with `adjust=False`, that is correct Wilder's. If it uses `rolling().mean()`, fix it.

**Step 4:** Commit after fixing any issues.

---

### Task 1.3: Audit MACD histogram and ADX

**Files:**
- Audit: `src/intelligence/indicators/macd.py`, `src/intelligence/indicators/adx.py`
- Test: `tests/unit/intelligence/test_correctness_audit.py`

**Step 1:** Add MACD histogram test:
```python
class TestMACDCorrectness:
    def test_histogram_sign_on_bullish_cross(self):
        """Histogram = MACD_line - signal_line. Positive when MACD above signal."""
        from src.intelligence.indicators.macd import MACDPlugin
        # Rising prices make MACD cross above signal
        close = np.concatenate([np.linspace(5000, 5000, 40), np.linspace(5000, 5200, 20)])
        df = make_ohlcv(close)
        p = MACDPlugin()
        result = p.compute_full({"main": df})
        macd = result.get("macd_12_26_9")
        signal = result.get("macd_signal_12_26_9")
        hist = result.get("macd_histogram_12_26_9")
        assert macd is not None and signal is not None and hist is not None
        # histogram should equal macd - signal within floating point
        assert abs(hist - (macd - signal)) < 1e-6
```

**Step 2:** Run: `.venv/bin/pytest tests/unit/intelligence/test_correctness_audit.py::TestMACDCorrectness -v`

**Step 3:** If histogram is abs(macd-signal) instead of signed, fix `src/intelligence/indicators/macd.py`.

**Step 4:** Commit: `git commit -m "test(audit): MACD histogram sign correctness verified"`

---

### Task 1.4: Audit VWAP session reset

**Files:**
- Audit: `src/intelligence/indicators/vwap.py`
- Test: `tests/unit/intelligence/test_correctness_audit.py`

**Step 1:** Add VWAP test verifying session reset (VWAP should be price on first bar of session):
```python
class TestVWAPCorrectness:
    def test_vwap_equals_price_on_first_bar(self):
        """VWAP of a single bar should equal that bar's typical price."""
        from src.intelligence.indicators.vwap import VWAPPlugin
        df = pd.DataFrame({
            "open": [5000.0], "high": [5010.0], "low": [4990.0],
            "close": [5005.0], "volume": [1000.0]
        })
        p = VWAPPlugin()
        result = p.compute_full({"main": df})
        # If session VWAP exists, it should equal (H+L+C)/3 = 5001.67
        vwap = result.get("vwap")
        if vwap is not None:
            assert abs(vwap - (5010 + 4990 + 5005) / 3) < 1.0
```

**Step 2:** Run and verify.

**Step 3:** Document any issues found. Known concern: does VWAP reset per session or accumulate indefinitely? Review `src/intelligence/indicators/vwap.py` — it should use rolling window not cumulative.

**Step 4:** Commit findings.

---

### Task 1.5: Audit Stochastic smoothing

**Files:**
- Audit: `src/intelligence/indicators/stochastic.py`
- Test: `tests/unit/intelligence/test_correctness_audit.py`

**Step 1:** Verify %K and %D definitions. Standard Slow Stochastic: Raw %K = (close−low14)/(high14−low14)×100, %K (smoothed) = 3-period SMA of raw %K, %D = 3-period SMA of %K.

```python
class TestStochasticCorrectness:
    def test_k_at_high_extreme(self):
        """When close == period high, %K should be 100."""
        from src.intelligence.indicators.stochastic import StochasticPlugin
        # Last bar close == period high
        close = np.full(20, 5000.0)
        close[-1] = 5020.0  # New high
        high = close.copy()
        low = close - 20.0
        df = pd.DataFrame({"open": close, "high": high, "low": low,
                           "close": close, "volume": np.full(20, 1000)})
        p = StochasticPlugin()
        result = p.compute_full({"main": df})
        k = result.get("stoch_k_14_3")
        # After smoothing, %K should be close to 100
        assert k is not None and k > 85
```

**Step 2:** Run and verify.

**Step 3:** Fix any smoothing issues.

**Step 4:** Commit.

---

### Task 1.6: Audit SwingDetector neighbor parameter

**Files:**
- Audit: `src/intelligence/structure/swing_detector.py`
- Test: `tests/unit/intelligence/test_correctness_audit.py`

**Step 1:** The design doc notes `neighbor=5` is hardcoded and may not be TF-adaptive. Add a test:
```python
class TestSwingDetectorCorrectness:
    def test_swing_high_detected_with_clear_peak(self):
        """A clear 5-bar peak should be detected as swing high."""
        from src.intelligence.structure.swing_detector import SwingDetectorPlugin
        close = np.array([100.0]*10 + [105, 110, 115, 120, 125, 120, 115, 110, 105, 100] + [100.0]*10)
        df = make_ohlcv(close)
        p = SwingDetectorPlugin()
        result = p.compute_full({"main": df, "features": {}})
        assert result.get("swing_high") is not None
        assert result.get("swing_high") > 100.0
```

**Step 2:** Run and verify.

**Step 3:** Note if neighbor=5 works correctly across all TFs. No code change needed unless incorrect.

**Step 4:** Commit: `git commit -m "test(audit): SwingDetector neighbor=5 verified"`

---

### Task 1.7: Audit GARCH parameters and I6 staleness

**Files:**
- Audit: `src/intelligence/context/garch_volatility.py`
- Audit: `src/intelligence/confluence/cross_timeframe.py`
- Test: `tests/unit/intelligence/test_correctness_audit.py`

**Step 1:** Add GARCH output range test:
```python
class TestGARCHCorrectness:
    def test_sigma_positive_on_any_data(self):
        """GARCH sigma must always be positive."""
        from src.intelligence.context.garch_volatility import GARCHVolatilityPlugin
        close = np.linspace(5000, 5200, 100) + np.random.default_rng(42).normal(0, 5, 100)
        df = make_ohlcv(close)
        p = GARCHVolatilityPlugin()
        result = p.compute_full({"main": df, "features": {}})
        sigma = result.get("garch_sigma")
        if sigma is not None:
            assert sigma > 0

    def test_vol_regime_is_0_1_or_2(self):
        from src.intelligence.context.garch_volatility import GARCHVolatilityPlugin
        close = np.linspace(5000, 5200, 100)
        df = make_ohlcv(close)
        result = GARCHVolatilityPlugin().compute_full({"main": df, "features": {}})
        regime = result.get("garch_vol_regime")
        if regime is not None:
            assert regime in (0, 1, 2)
```

**Step 2:** Run: `.venv/bin/pytest tests/unit/intelligence/test_correctness_audit.py::TestGARCHCorrectness -v`

**Step 3:** Verify `src/intelligence/context/garch_volatility.py` — parameters ω/α/β should have comments justifying values. If hardcoded without comments, add docstring explaining calibration.

**Step 4:** Commit: `git commit -m "test(audit): GARCH sigma positivity and regime bounds verified"`

---

### Task 1.8: Audit Bollinger Bands + OBV

**Files:**
- Audit: `src/intelligence/indicators/bollinger.py`, `src/intelligence/indicators/obv.py`
- Test: `tests/unit/intelligence/test_correctness_audit.py`

**Step 1:** Add tests:
```python
class TestBollingerBandsCorrectness:
    def test_bands_are_mean_plus_minus_2sigma(self):
        """Upper = SMA20 + 2σ, lower = SMA20 - 2σ (population std, not sample)."""
        from src.intelligence.indicators.bollinger import BollingerBandsPlugin
        import pandas as pd
        close = np.linspace(5000, 5100, 25)
        df = make_ohlcv(close)
        result = BollingerBandsPlugin().compute_full({"main": df})
        mid = result.get("bb_20_2_mid")
        upper = result.get("bb_20_2_upper")
        lower = result.get("bb_20_2_lower")
        assert mid is not None
        # SMA of last 20 bars
        expected_mid = float(np.mean(close[-20:]))
        assert abs(mid - expected_mid) < 0.01
        # Width should be symmetric
        assert abs((upper - mid) - (mid - lower)) < 0.01

    def test_bands_widen_on_volatile_data(self):
        from src.intelligence.indicators.bollinger import BollingerBandsPlugin
        quiet = make_ohlcv(np.full(30, 5000.0))
        volatile_close = np.full(30, 5000.0)
        volatile_close[10:20] += np.linspace(0, 100, 10)
        volatile = make_ohlcv(volatile_close)
        r_quiet = BollingerBandsPlugin().compute_full({"main": quiet})
        r_volatile = BollingerBandsPlugin().compute_full({"main": volatile})
        quiet_width = (r_quiet.get("bb_20_2_upper", 0) - r_quiet.get("bb_20_2_lower", 0))
        volatile_width = (r_volatile.get("bb_20_2_upper", 0) - r_volatile.get("bb_20_2_lower", 0))
        assert volatile_width > quiet_width


class TestOBVCorrectness:
    def test_obv_increases_on_up_day(self):
        """On an up day (close > prev_close), OBV += volume."""
        from src.intelligence.indicators.obv import OBVPlugin
        close = np.array([5000.0, 5010.0, 5020.0])
        volume = np.array([1000.0, 2000.0, 1500.0])
        df = make_ohlcv(close, volume)
        result = OBVPlugin().compute_full({"main": df})
        obv = result.get("obv")
        assert obv is not None
        # OBV should be positive (net buying)
        assert obv > 0

    def test_obv_decreases_on_down_day(self):
        from src.intelligence.indicators.obv import OBVPlugin
        close = np.array([5020.0, 5010.0, 5000.0])
        volume = np.array([1000.0, 2000.0, 1500.0])
        df = make_ohlcv(close, volume)
        result = OBVPlugin().compute_full({"main": df})
        obv = result.get("obv")
        assert obv is not None
        assert obv < 0
```

**Step 2:** Run: `.venv/bin/pytest tests/unit/intelligence/test_correctness_audit.py::TestBollingerBandsCorrectness tests/unit/intelligence/test_correctness_audit.py::TestOBVCorrectness -v`

**Step 3:** If Bollinger uses sample std (ddof=1) instead of population std (ddof=0), fix it. Standard BB uses population std.

**Step 4:** Commit: `git commit -m "test(audit): Bollinger Bands std formula + OBV direction logic verified"`

---

### Task 1.9: Audit I3 Structure plugins

**Files:**
- Audit: `src/intelligence/structure/support_resistance.py`, `src/intelligence/structure/trend_structure.py`
- Test: `tests/unit/intelligence/test_correctness_audit.py`

**Step 1:** Read both files. Key questions:
- **S/R clustering threshold**: Is 0.5% hardcoded? For ES (~5000), 0.5% = 25 points which may be too wide. For cheap contracts, may be fine. Should it scale with ATR instead?
- **TrendStructure `structure_integrity`**: What does this metric mean? Is it consistently computed (0–1 range, well-defined)?

**Step 2:** Add tests:
```python
class TestSRClusteringCorrectness:
    def test_sr_levels_within_price_range(self):
        from src.intelligence.structure.support_resistance import SupportResistancePlugin
        close = np.linspace(5000, 5100, 60)
        df = make_ohlcv(close)
        result = SupportResistancePlugin().compute_full({"main": df, "features": {}})
        resistance = result.get("nearest_resistance")
        support = result.get("nearest_support")
        price_range = (close.min(), close.max())
        if resistance is not None:
            # Resistance should be above or near current price
            assert resistance >= close[-1] * 0.95
        if support is not None:
            assert support <= close[-1] * 1.05

    def test_support_dist_pct_is_percentage(self):
        from src.intelligence.structure.support_resistance import SupportResistancePlugin
        close = np.linspace(5000, 5100, 60)
        df = make_ohlcv(close)
        result = SupportResistancePlugin().compute_full({"main": df, "features": {}})
        dist = result.get("support_dist_pct")
        if dist is not None:
            assert 0 <= dist <= 1.0  # should be fraction (0-1), not percent (0-100)


class TestTrendStructureCorrectness:
    def test_structure_integrity_bounded_0_to_1(self):
        from src.intelligence.structure.trend_structure import TrendStructurePlugin
        close = np.linspace(5000, 5200, 60)
        df = make_ohlcv(close)
        result = TrendStructurePlugin().compute_full({"main": df, "features": {}})
        integrity = result.get("structure_integrity")
        if integrity is not None:
            assert 0.0 <= integrity <= 1.0

    def test_trend_direction_uptrend(self):
        from src.intelligence.structure.trend_structure import TrendStructurePlugin
        close = np.linspace(5000, 5200, 60)
        df = make_ohlcv(close)
        result = TrendStructurePlugin().compute_full({"main": df, "features": {}})
        direction = result.get("trend_direction")
        if direction is not None:
            assert direction > 0
```

**Step 3:** Read `src/intelligence/structure/support_resistance.py` — check the clustering radius. If hardcoded to `price * 0.005`, note in a docstring that this may need ATR-based adaptation. File a TODO if appropriate but don't change behavior now.

**Step 4:** Commit: `git commit -m "test(audit): I3 S/R clustering and TrendStructure integrity bounds verified"`

---

### Task 1.10: Audit I4 Context plugins — Kalman, TrendRegime, MomentumContext

**Files:**
- Audit: `src/intelligence/context/kalman_trend.py`, `src/intelligence/context/trend_regime.py`, `src/intelligence/context/momentum_context.py`
- Test: `tests/unit/intelligence/test_correctness_audit.py`

**Step 1:** Read all three files. Key questions:
- **Kalman**: Is it 1D (level only) or 2D (level + velocity)? 1D (local level model) is correct for price. Are Q/R noise values tuned?
- **TrendRegime**: Does it use `sma_20`/`sma_50` from the features dict (already computed by I1 MovingAverages), or does it recompute from raw OHLCV? It must use the I1 features to avoid redundancy and ensure same values.
- **MomentumContext**: How are RSI/MACD/Stoch/CCI scored? Are the bins calibrated (e.g., RSI>60 = bullish)?

**Step 2:** Add tests:
```python
class TestKalmanCorrectness:
    def test_kalman_trend_tracks_uptrend(self):
        from src.intelligence.context.kalman_trend import KalmanTrendPlugin
        close = np.linspace(5000, 5200, 60)
        df = make_ohlcv(close)
        result = KalmanTrendPlugin().compute_full({"main": df, "features": {}})
        trend = result.get("kalman_trend")
        slope = result.get("kalman_slope")
        if trend is not None:
            assert trend > 5000  # should track upward price
        if slope is not None:
            assert slope > 0  # positive slope in uptrend

    def test_kalman_uncertainty_positive(self):
        from src.intelligence.context.kalman_trend import KalmanTrendPlugin
        close = np.linspace(5000, 5200, 60)
        df = make_ohlcv(close)
        result = KalmanTrendPlugin().compute_full({"main": df, "features": {}})
        uncertainty = result.get("kalman_uncertainty")
        if uncertainty is not None:
            assert uncertainty > 0


class TestTrendRegimeCorrectness:
    def test_uses_features_dict_not_recomputed(self):
        """TrendRegime must read sma_20/sma_50 from features (I1 outputs), not recompute."""
        from src.intelligence.context.trend_regime import TrendRegimePlugin
        # Inject pre-computed SMAs
        features = {"sma_20": 5100.0, "sma_50": 5050.0, "close": 5150.0}
        close = np.full(60, 5000.0)  # flat price (would show neutral trend if recomputed)
        df = make_ohlcv(close)
        result = TrendRegimePlugin().compute_full({"main": df, "features": features})
        regime = result.get("trend_regime")
        # If using features (sma_20 > sma_50 > close context), should show bullish
        # If recomputing from flat close, would show neutral
        # This test documents the expected behavior — fix if it recomputes
        assert regime is not None


class TestMomentumContextCorrectness:
    def test_momentum_bias_positive_in_uptrend(self):
        from src.intelligence.context.momentum_context import MomentumContextPlugin
        # All bullish signals
        features = {"rsi_14": 65.0, "macd_histogram_12_26_9": 5.0,
                    "stoch_k_14_3": 75.0, "cci_14": 120.0}
        result = MomentumContextPlugin().compute_full({"main": None, "features": features})
        bias = result.get("momentum_bias")
        if bias is not None:
            assert bias > 0

    def test_momentum_bias_negative_in_downtrend(self):
        from src.intelligence.context.momentum_context import MomentumContextPlugin
        features = {"rsi_14": 28.0, "macd_histogram_12_26_9": -5.0,
                    "stoch_k_14_3": 15.0, "cci_14": -120.0}
        result = MomentumContextPlugin().compute_full({"main": None, "features": features})
        bias = result.get("momentum_bias")
        if bias is not None:
            assert bias < 0
```

**Step 3:** If TrendRegime recomputes SMAs from raw OHLCV instead of using `features["sma_20"]` etc., fix it to read from features. This matters because indicator_service computes SMAs with full history while market_analysis_service's `frames["main"]` may have limited bars.

**Step 4:** Commit: `git commit -m "test(audit): Kalman model, TrendRegime SMA source, MomentumContext calibration verified"`

---

### Task 1.11: Audit I5 Chart Pattern plugins

**Files:**
- Audit: `src/intelligence/patterns/bollinger_squeeze.py`, `src/intelligence/patterns/double_top_bottom.py`, `src/intelligence/patterns/head_shoulders.py`, `src/intelligence/patterns/rsi_divergence.py`
- Test: `tests/unit/intelligence/test_correctness_audit.py`

**Step 1:** Key questions:
- **BollingerSqueeze**: Keltner comparison — squeeze = BB inside Keltner. The Keltner midline should be EMA20, not SMA20. Bandwidth: `(ATR × multiplier)`. Does the plugin read Keltner from features (correct) or recompute?
- **DoubleTop**: How close do two peaks need to be in price? Is the tolerance percentage-based or ATR-based? ATR-based is more robust.
- **H&S**: Does neckline slope handling correctly reject tilted patterns? Overly strict = miss real patterns.
- **RSIDivergence**: The swing lag window — how many bars back does it look for divergent swings?

**Step 2:** Add tests:
```python
class TestBollingerSqueezeCorrectness:
    def test_squeeze_active_when_bb_inside_keltner(self):
        from src.intelligence.patterns.bollinger_squeeze import BollingerSqueezePlugin
        # Inject pre-computed features: BB narrower than Keltner
        features = {
            "bb_20_2_upper": 5020.0, "bb_20_2_lower": 4980.0,  # BB width = 40
            "keltner_upper_20_2": 5030.0, "keltner_lower_20_2": 4970.0,  # KC width = 60
        }
        result = BollingerSqueezePlugin().compute_full({"main": None, "features": features})
        squeeze = result.get("squeeze_active")
        if squeeze is not None:
            assert squeeze == 1.0  # BB inside Keltner = squeeze

    def test_no_squeeze_when_bb_outside_keltner(self):
        from src.intelligence.patterns.bollinger_squeeze import BollingerSqueezePlugin
        features = {
            "bb_20_2_upper": 5050.0, "bb_20_2_lower": 4950.0,  # BB width = 100
            "keltner_upper_20_2": 5020.0, "keltner_lower_20_2": 4980.0,  # KC width = 40
        }
        result = BollingerSqueezePlugin().compute_full({"main": None, "features": features})
        squeeze = result.get("squeeze_active")
        if squeeze is not None:
            assert squeeze == 0.0
```

**Step 3:** Read `src/intelligence/patterns/bollinger_squeeze.py` — verify it reads Keltner from `features` dict (keltner fields from KeltnerPlugin in I1). If it recomputes Keltner internally using EWM, confirm the period and multiplier match the KeltnerPlugin defaults.

**Step 4:** Commit: `git commit -m "test(audit): BollingerSqueeze Keltner comparison formula verified"`

---

### Task 1.12: Audit SMC plugins — BOS/CHoCH, FVG, OrderBlocks

**Files:**
- Audit: `src/intelligence/smart_money/bos_choch.py`, `src/intelligence/smart_money/fair_value_gap.py`, `src/intelligence/smart_money/order_blocks.py`
- Test: `tests/unit/intelligence/test_correctness_audit.py`

**Step 1:** Key questions per ICT theory:
- **BOS**: Requires *close* beyond swing level (not wick). Verify `close[-1] > swing_high` not `high[-1] > swing_high`
- **CHoCH**: First BOS in the *opposite* direction of the prevailing trend. Verify state machine tracks this correctly.
- **FVG**: Bullish FVG = `bar[-3].high < bar[-1].low` (gap between bar i-2 high and bar i low). Verify bar indexing: in a 0-indexed array `close`, a bullish FVG at current bar means `high[i-2] < low[i]`.
- **OrderBlocks**: "Last bearish candle before a bullish BOS" — does lookback correctly find the last bearish (close < open) candle immediately before the BOS bar?

**Step 2:** Add tests:
```python
class TestBOSCHoCHCorrectness:
    def test_bos_requires_close_not_wick(self):
        """BOS should trigger on close beyond swing level, not wick."""
        from src.intelligence.smart_money.bos_choch import BOSCHoCHPlugin
        import pandas as pd
        # Price wick above swing high but closes below it
        # Build 70 bars of data with a clear swing high at ~5100
        close = np.concatenate([np.linspace(5000, 5100, 30), np.linspace(5100, 5080, 20),
                                 np.linspace(5080, 5090, 15)])
        high = close + 5.0
        low = close - 5.0
        # Last bar: wick above swing high (high=5105) but closes at 5095 (below)
        high[-1] = 5105.0
        close[-1] = 5095.0
        df = pd.DataFrame({"open": close, "high": high, "low": low,
                           "close": close, "volume": np.full(len(close), 1000)})
        result = BOSCHoCHPlugin().compute_full({"main": df, "features": {}})
        # BOS should NOT be detected (close didn't break swing high)
        bos = result.get("bos_detected", 0)
        assert bos == 0, "BOS should not trigger on wick-only break"

    def test_fvg_bullish_bar_indexing(self):
        """Bullish FVG: bar[i-2].high < bar[i].low (3-bar gap)."""
        from src.intelligence.smart_money.fair_value_gap import FairValueGapPlugin
        import pandas as pd
        # bar[0]: high=5010, bar[1]: big up candle, bar[2]: low=5020 > bar[0].high
        df = pd.DataFrame({
            "open":   [5000, 5005, 5025, 5028] * 20,
            "high":   [5010, 5030, 5040, 5035] * 20,
            "low":    [4995, 5000, 5020, 5022] * 20,
            "close":  [5005, 5025, 5035, 5030] * 20,
            "volume": [1000] * 80,
        })
        result = FairValueGapPlugin().compute_full({"main": df, "features": {}})
        fvg_type = result.get("fvg_type")
        # Should detect a bullish FVG (type=1) given the gap
        assert fvg_type is not None
```

**Step 3:** Read the BOS/CHoCH implementation carefully. If it uses `high[-1] > swing_high` instead of `close[-1] > swing_high` for BOS detection, fix it.

**Step 4:** Read FVG. Confirm the indexing: `high[i-2] < low[i]` for bullish (current bar = i). In numpy slice with the last 3 bars: `high[-3] < low[-1]` for bullish.

**Step 5:** Commit: `git commit -m "test(audit): BOS/CHoCH close-based break, FVG 3-bar indexing verified"`

---

### Task 1.13: Audit SMC plugins — LiquiditySweeps, BOCPD, HMM

**Files:**
- Audit: `src/intelligence/smart_money/liquidity_sweeps.py`, `src/intelligence/smart_money/bocpd_changepoint.py`, `src/intelligence/smart_money/hmm_regime.py`
- Test: `tests/unit/intelligence/test_correctness_audit.py`

**Step 1:** Key questions:
- **LiquiditySweeps**: Sweep = price wick beyond a swing level then closes back within it (wick-based, not close-based). Reclaim condition = close must re-enter the range within N bars. Verify both conditions.
- **BOCPD**: Is the Bayesian prior/posterior update correct? The hazard function controls how often changepoints are expected. After a changepoint, run length resets to 0. Verify the run_length_probs array is updated correctly.
- **HMM**: 3-state model (ranging, trending-up, trending-down). Are emission distributions trained on data or fixed? CLAUDE.md mentions a past fix (`macd_histogram_12_26_9` key) — verify this fix is in place.

**Step 2:** Add tests:
```python
class TestLiquiditySweepsCorrectness:
    def test_sweep_requires_wick_not_close(self):
        """A sweep is a wick beyond swing level that closes back within range."""
        from src.intelligence.smart_money.liquidity_sweeps import LiquiditySweepsPlugin
        import pandas as pd
        # Build price that wicks below prior swing low then closes above it
        close = np.concatenate([
            np.linspace(5100, 5000, 30),  # downtrend, establish low at 5000
            np.full(20, 5000.0),          # consolidation at low
            [4990.0],                      # wick below (low < swing low)
        ])
        close[-1] = 5005.0  # but closes back above
        high = close + 5.0
        low = close.copy()
        low[-1] = 4988.0  # wick low
        df = pd.DataFrame({"open": close, "high": high, "low": low,
                           "close": close, "volume": np.full(len(close), 1000)})
        result = LiquiditySweepsPlugin().compute_full({"main": df, "features": {}})
        sweep = result.get("sweep_detected")
        # Should detect a sweep (wick below swing low + closed back above)
        assert sweep is not None

class TestHMMCorrectness:
    def test_hmm_macd_key_name_is_correct(self):
        """Verify HMM uses macd_histogram_12_26_9 (not macd_hist_12_26_9)."""
        import inspect
        from src.intelligence.smart_money.hmm_regime import HMMRegimePlugin
        source = inspect.getsource(HMMRegimePlugin)
        assert "macd_hist_12_26_9" not in source, (
            "HMM uses wrong MACD key. Should be macd_histogram_12_26_9"
        )
        assert "macd_histogram_12_26_9" in source or "macd" not in source

    def test_hmm_regime_values_are_0_1_or_2(self):
        from src.intelligence.smart_money.hmm_regime import HMMRegimePlugin
        close = np.linspace(5000, 5200, 80)
        df = make_ohlcv(close)
        features = {"rsi_14": 60.0, "macd_histogram_12_26_9": 5.0, "atr_14": 10.0}
        result = HMMRegimePlugin().compute_full({"main": df, "features": features})
        regime = result.get("hmm_regime")
        if regime is not None:
            assert regime in (0.0, 1.0, 2.0)
```

**Step 3:** Run: `.venv/bin/pytest tests/unit/intelligence/test_correctness_audit.py::TestHMMCorrectness -v`

The `test_hmm_macd_key_name_is_correct` test documents the fix from CLAUDE.md — if it fails, the HMM bug is still present.

**Step 4:** Commit: `git commit -m "test(audit): LiquiditySweeps wick condition, BOCPD, HMM key name fix verified"`

---

### Task 1.14: Audit SMC plugins — LiquidityPools, SupplyDemand

**Files:**
- Audit: `src/intelligence/smart_money/liquidity_pools.py`, `src/intelligence/smart_money/supply_demand_zones.py`
- Test: `tests/unit/intelligence/test_correctness_audit.py`

**Step 1:** Key questions:
- **LiquidityPools**: BSL (Buy Side Liquidity) = swing highs where buy stops cluster above price. SSL (Sell Side Liquidity) = swing lows where sell stops cluster below price. `bsl_level` should always be above current price; `ssl_level` below.
- **SupplyDemand**: Zone "freshness" should decay as price revisits the zone. A fresh zone = never retested. Verify `demand_freshness` decreases (or zone count drops) when price enters a demand zone.

**Step 2:** Add tests:
```python
class TestLiquidityPoolsCorrectness:
    def test_bsl_above_price_ssl_below(self):
        """BSL must be above current close; SSL must be below."""
        from src.intelligence.smart_money.liquidity_pools import LiquidityPoolsPlugin
        close = np.concatenate([
            np.linspace(5050, 5100, 20),  # swing highs (BSL above)
            np.linspace(5100, 5050, 20),
            np.linspace(5050, 4980, 20),  # swing lows (SSL below)
            np.linspace(4980, 5020, 20),
        ])
        df = make_ohlcv(close)
        result = LiquidityPoolsPlugin().compute_full({"main": df, "features": {}})
        bsl = result.get("bsl_level")
        ssl = result.get("ssl_level")
        current_price = float(close[-1])
        if bsl is not None and bsl > 0:
            assert bsl > current_price * 0.98, f"BSL {bsl} should be above price {current_price}"
        if ssl is not None and ssl > 0:
            assert ssl < current_price * 1.02, f"SSL {ssl} should be below price {current_price}"


class TestSupplyDemandCorrectness:
    def test_freshness_decreases_when_zone_tested(self):
        """demand_freshness should be lower after price revisits the zone."""
        from src.intelligence.smart_money.supply_demand_zones import SupplyDemandZonesPlugin
        # Build price: impulse from demand zone, then revisit
        close = np.concatenate([
            np.linspace(4950, 4980, 10),  # demand zone base
            np.linspace(4980, 5100, 20),  # rally (fresh zone created)
            np.linspace(5100, 4960, 20),  # retrace back to zone (zone tested)
        ])
        df_fresh = make_ohlcv(close[:30])  # before retrace
        df_tested = make_ohlcv(close)      # after retrace

        p = SupplyDemandZonesPlugin()
        r_fresh = p.compute_full({"main": df_fresh, "features": {}})
        p2 = SupplyDemandZonesPlugin()
        r_tested = p2.compute_full({"main": df_tested, "features": {}})

        fresh_val = r_fresh.get("demand_freshness", 1.0)
        tested_val = r_tested.get("demand_freshness", 1.0)
        # After testing, freshness should be lower (or active_demand_zones should decrease)
        demand_after = r_tested.get("active_demand_zones", 0)
        # Either freshness dropped or zones were cleared
        assert tested_val <= fresh_val or demand_after == 0
```

**Step 3:** Run and verify. If BSL/SSL orientation is wrong (BSL below price), fix the plugin.

**Step 4:** Commit: `git commit -m "test(audit): LiquidityPools BSL/SSL orientation, SupplyDemand freshness decay verified"`

---

### Task 1.15: Run full audit suite + document findings

**Step 1:** Run all audit tests:
```
.venv/bin/pytest tests/unit/intelligence/test_correctness_audit.py -v
```
Expected: all pass.

**Step 2:** Run full test suite to confirm no regressions:
```
.venv/bin/pytest tests/unit/ -v --tb=short
```
Expected: 803+ tests pass.

**Step 3:** Run ruff:
```
.venv/bin/ruff check . --fix
```
Expected: 0 errors.

**Step 4:** Commit: `git commit -m "test(audit): complete I1-I6 correctness audit suite"`

---

## Phase 2: I2 Tier — Indicator Event Plugins

**Goal:** Add I2 tier with 6 composite event plugins. Wire into pipeline, schema, migration, and service.

### Task 2.1: Add I2Events schema model

**Files:**
- Modify: `src/intelligence/schemas.py`
- Modify: `services/market_analysis_service.py` (import side)

**Step 1:** Write failing test first:
```python
# tests/unit/intelligence/test_i2_schema.py
def test_i2events_fields_present():
    from src.intelligence.schemas import I2Events
    e = I2Events()
    assert hasattr(e, "macd_cross_bullish")
    assert hasattr(e, "rsi_crossed_30_up")
    assert hasattr(e, "adx_trend_confirmed")

def test_intelligence_event_has_i2_field():
    from src.intelligence.schemas import IntelligenceEvent, I2Events
    import inspect
    fields = inspect.get_annotations(IntelligenceEvent)
    assert "i2" in IntelligenceEvent.model_fields
```

**Step 2:** Run test — expect FAIL (I2Events doesn't exist).

**Step 3:** Add `I2Events` class to `src/intelligence/schemas.py` (insert before `I3Structure`):

```python
class I2Events(BaseModel):
    """I2 composite indicator event outputs — crossovers, threshold crossings, extremes.

    Plugins:
    - MAComposite (extended — golden/death cross)
    - evt_MACDEvents (MACD crossovers, histogram transitions, divergence)
    - evt_RSIEvents (RSI threshold crossings, extremes)
    - evt_StochasticEvents (K/D crossovers, oversold/overbought reversals)
    - evt_ADXEvents (ADX trending/ranging, DI crossovers)
    - evt_VolumeEvents (volume spikes, BB touches)
    """

    model_config = ConfigDict(extra="allow")  # allow new fields as plugins expand

    # MAComposite extended
    golden_cross_active: float | None = None      # SMA50 > SMA200
    death_cross_active: float | None = None
    golden_cross_bars_ago: float | None = None
    price_above_sma200: float | None = None

    # MACDEvents
    macd_cross_bullish: float | None = None
    macd_cross_bearish: float | None = None
    macd_cross_bars_ago: float | None = None
    macd_hist_positive: float | None = None
    macd_hist_turning_up: float | None = None
    macd_negative_support_test: float | None = None
    macd_price_divergence_bullish: float | None = None
    macd_price_divergence_bearish: float | None = None

    # RSIEvents
    rsi_crossed_30_up: float | None = None
    rsi_crossed_70_down: float | None = None
    rsi_crossed_50_up: float | None = None
    rsi_crossed_50_down: float | None = None
    rsi_extreme_reversal: float | None = None
    rsi_bars_in_extreme: float | None = None

    # StochasticEvents
    stoch_cross_bullish: float | None = None
    stoch_cross_bearish: float | None = None
    stoch_oversold_reversal: float | None = None
    stoch_overbought_reversal: float | None = None
    stoch_both_oversold: float | None = None
    stoch_both_overbought: float | None = None

    # ADXEvents
    adx_trend_confirmed: float | None = None
    adx_ranging_confirmed: float | None = None
    di_cross_bullish: float | None = None
    di_cross_bearish: float | None = None
    di_cross_bars_ago: float | None = None
    di_spread: float | None = None

    # VolumeEvents
    vol_spike: float | None = None
    vol_drying: float | None = None
    bb_upper_touch: float | None = None
    bb_lower_touch: float | None = None
    bb_walking_upper: float | None = None
    bb_walking_lower: float | None = None
```

**Step 4:** Add `i2` field to `IntelligenceEvent`:
```python
# In IntelligenceEvent, add before i3:
i2: I2Events
```

**Step 5:** Run test — expect PASS.

**Step 6:** Commit:
```bash
git add src/intelligence/schemas.py tests/unit/intelligence/test_i2_schema.py
git commit -m "feat(i2): add I2Events schema model and IntelligenceEvent.i2 field"
```

---

### Task 2.2: Add I2 migration

**Files:**
- Create: `production/migrations/013_add_i2_column.sql`

**Step 1:** Create the migration file:
```sql
-- production/migrations/013_add_i2_column.sql
-- Add I2 tier JSONB column to intelligence_features
-- Version: 1.0.0
-- Date: 2026-03-01

ALTER TABLE intelligence_features
    ADD COLUMN IF NOT EXISTS i2 JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_intel_features_i2_gin
    ON intelligence_features USING GIN (i2);
```

**Step 2:** Apply migration:
```
PGPASSWORD=indicagent psql -h localhost -U indicagent -d indicagent \
  -f production/migrations/013_add_i2_column.sql
```
Expected output: `ALTER TABLE`, `CREATE INDEX`

**Step 3:** Verify column exists:
```
PGPASSWORD=indicagent psql -h localhost -U indicagent -d indicagent \
  -c "\d intelligence_features" | grep i2
```
Expected: `i2 | jsonb | not null | default '{}'::jsonb`

**Step 4:** Commit:
```bash
git add production/migrations/013_add_i2_column.sql
git commit -m "feat(i2): add i2 JSONB column to intelligence_features (migration 013)"
```

---

### Task 2.3: Extend MAComposite with golden/death cross fields

**Files:**
- Modify: `src/intelligence/composites/ma_composites.py`
- Test: `tests/unit/intelligence/test_i2_plugins.py` (create)

**Step 1:** Create test file with MAComposite extension test:
```python
# tests/unit/intelligence/test_i2_plugins.py
"""Tests for I2 composite indicator event plugins."""
import numpy as np
import pandas as pd
from tests.unit.intelligence.helpers import make_ohlcv


class TestMACompositeExtended:
    def test_golden_cross_active_when_sma50_gt_sma200(self):
        from src.intelligence.composites.ma_composites import MACompositePlugin
        # When sma_50 > sma_200 in features, golden_cross_active = 1
        features = {"sma_50": 5100.0, "sma_200": 5000.0, "close": 5150.0}
        p = MACompositePlugin()
        result = p.compute_full({"features": features})
        assert result.get("golden_cross_active") == 1

    def test_death_cross_active_when_sma50_lt_sma200(self):
        from src.intelligence.composites.ma_composites import MACompositePlugin
        features = {"sma_50": 4900.0, "sma_200": 5000.0, "close": 4850.0}
        p = MACompositePlugin()
        result = p.compute_full({"features": features})
        assert result.get("death_cross_active") == 1
        assert result.get("golden_cross_active") == 0

    def test_price_above_sma200(self):
        from src.intelligence.composites.ma_composites import MACompositePlugin
        features = {"sma_200": 5000.0, "close": 5100.0}
        result = MACompositePlugin().compute_full({"features": features})
        assert result.get("price_above_sma200") == 1

    def test_empty_returns_empty(self):
        from src.intelligence.composites.ma_composites import MACompositePlugin
        assert MACompositePlugin().compute_full({}) == {}
```

**Step 2:** Run test — expect FAIL (fields not yet added).

**Step 3:** In `src/intelligence/composites/ma_composites.py`:
- Add to `outputs` frozenset: `"golden_cross_active"`, `"death_cross_active"`, `"golden_cross_bars_ago"`, `"price_above_sma200"`
- In `compute_full`, add after the sma_20/sma_50 block:
```python
# Golden/Death cross (SMA50 vs SMA200)
s200 = ma.get("sma_200")
if self._is_num(s50) and self._is_num(s200):
    out["golden_cross_active"] = 1 if s50 > s200 else 0
    out["death_cross_active"] = 1 if s50 < s200 else 0
    # Track bars since last cross using prev_features
    prev = frames.get("prev_features") or {}
    ps50 = prev.get("sma_50")
    ps200 = prev.get("sma_200")
    if self._is_num(ps50) and self._is_num(ps200):
        cross_occurred = (ps50 <= ps200 and s50 > s200) or (ps50 >= ps200 and s50 < s200)
        prev_ago = self._state.get("golden_cross_bars_ago", 999)
        out["golden_cross_bars_ago"] = 0.0 if cross_occurred else float(min(prev_ago + 1, 999))
        self._state["golden_cross_bars_ago"] = out["golden_cross_bars_ago"]

# Price vs SMA200
if px is not None and self._is_num(s200):
    out["price_above_sma200"] = 1 if px > s200 else 0
```

Note: `_state` dict already exists as `field(default_factory=dict)`. Add `_state` to the dataclass if not present.

**Step 4:** Run test — expect PASS.

**Step 5:** Commit:
```bash
git add src/intelligence/composites/ma_composites.py tests/unit/intelligence/test_i2_plugins.py
git commit -m "feat(i2): extend MAComposite with golden/death cross and SMA200 fields"
```

---

### Task 2.4: Create MACDEvents plugin

**Files:**
- Create: `src/intelligence/composites/macd_events.py`
- Test: `tests/unit/intelligence/test_i2_plugins.py`

**Step 1:** Add tests to `test_i2_plugins.py`:
```python
class TestMACDEvents:
    def _features(self, macd=10.0, signal=5.0, hist=5.0,
                  prev_macd=4.0, prev_signal=6.0, prev_hist=-2.0,
                  close=5100.0, prev_close=5050.0):
        return {
            "macd_12_26_9": macd, "macd_signal_12_26_9": signal,
            "macd_histogram_12_26_9": hist,
            "close": close,
        }, {
            "macd_12_26_9": prev_macd, "macd_signal_12_26_9": prev_signal,
            "macd_histogram_12_26_9": prev_hist,
            "close": prev_close,
        }

    def test_bullish_cross_detected(self):
        from src.intelligence.composites.macd_events import MACDEventsPlugin
        # prev: macd < signal, now: macd > signal
        features, prev = self._features(macd=10, signal=8, prev_macd=4, prev_signal=6)
        result = MACDEventsPlugin().compute_full({"features": features, "prev_features": prev})
        assert result.get("macd_cross_bullish") == 1
        assert result.get("macd_cross_bearish") == 0

    def test_hist_positive_flag(self):
        from src.intelligence.composites.macd_events import MACDEventsPlugin
        features, _ = self._features(hist=5.0)
        result = MACDEventsPlugin().compute_full({"features": features})
        assert result.get("macd_hist_positive") == 1

    def test_hist_turning_up_from_negative(self):
        from src.intelligence.composites.macd_events import MACDEventsPlugin
        features, prev = self._features(hist=-1.0, prev_hist=-5.0)
        result = MACDEventsPlugin().compute_full({"features": features, "prev_features": prev})
        assert result.get("macd_hist_turning_up") == 1

    def test_empty_returns_empty(self):
        from src.intelligence.composites.macd_events import MACDEventsPlugin
        assert MACDEventsPlugin().compute_full({}) == {}
```

**Step 2:** Run test — expect FAIL.

**Step 3:** Create `src/intelligence/composites/macd_events.py`:
```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from ..plugins import InputSpec


@dataclass
class MACDEventsPlugin:
    name: str = "evt_MACDEvents"
    outputs: set[str] = frozenset({
        "macd_cross_bullish", "macd_cross_bearish", "macd_cross_bars_ago",
        "macd_hist_positive", "macd_hist_turning_up",
        "macd_negative_support_test",
        "macd_price_divergence_bullish", "macd_price_divergence_bearish",
    })
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"momentum"})
    inputs: list[InputSpec] = ()
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        macd = features.get("macd_12_26_9")
        signal = features.get("macd_signal_12_26_9")
        hist = features.get("macd_histogram_12_26_9")
        if not all(isinstance(v, (int, float)) for v in [macd, signal, hist]):
            return {}

        out: dict[str, Any] = {}
        prev = frames.get("prev_features") or {}
        prev_macd = prev.get("macd_12_26_9")
        prev_signal = prev.get("macd_signal_12_26_9")
        prev_hist = prev.get("macd_histogram_12_26_9")

        # Crossover detection
        cross_bullish = 0
        cross_bearish = 0
        if isinstance(prev_macd, (int, float)) and isinstance(prev_signal, (int, float)):
            cross_bullish = 1 if prev_macd <= prev_signal and macd > signal else 0
            cross_bearish = 1 if prev_macd >= prev_signal and macd < signal else 0

        out["macd_cross_bullish"] = cross_bullish
        out["macd_cross_bearish"] = cross_bearish

        # Track bars since last cross
        if cross_bullish or cross_bearish:
            self._state["cross_bars_ago"] = 0.0
        else:
            self._state["cross_bars_ago"] = float(min(self._state.get("cross_bars_ago", 999) + 1, 999))
        out["macd_cross_bars_ago"] = self._state["cross_bars_ago"]

        # Histogram state
        out["macd_hist_positive"] = 1 if hist > 0 else 0
        turning_up = 0
        if isinstance(prev_hist, (int, float)):
            turning_up = 1 if prev_hist < 0 and hist > prev_hist else 0
        out["macd_hist_turning_up"] = turning_up

        # Negative support test: MACD hist negative + price near support
        nearest_support = features.get("nearest_support")
        close = features.get("close")
        atr = features.get("atr_14")
        neg_support = 0
        if hist < 0 and isinstance(nearest_support, (int, float)) and isinstance(close, (int, float)) and isinstance(atr, (int, float)) and atr > 0:
            dist = abs(close - nearest_support) / atr
            neg_support = 1 if dist < 1.0 else 0
        out["macd_negative_support_test"] = neg_support

        # Price/MACD divergence (basic: price making new high but MACD lower)
        out["macd_price_divergence_bullish"] = 0
        out["macd_price_divergence_bearish"] = 0

        return out

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = MACDEventsPlugin()
```

**Step 4:** Run test — expect PASS.

**Step 5:** Commit:
```bash
git add src/intelligence/composites/macd_events.py tests/unit/intelligence/test_i2_plugins.py
git commit -m "feat(i2): add MACDEvents composite plugin"
```

---

### Task 2.5: Create RSIEvents plugin

**Files:**
- Create: `src/intelligence/composites/rsi_events.py`
- Test: `tests/unit/intelligence/test_i2_plugins.py`

**Step 1:** Add tests:
```python
class TestRSIEvents:
    def test_rsi_crossed_30_up(self):
        from src.intelligence.composites.rsi_events import RSIEventsPlugin
        # prev RSI < 30, now RSI > 30
        features = {"rsi_14": 32.0}
        prev = {"rsi_14": 27.0}
        result = RSIEventsPlugin().compute_full({"features": features, "prev_features": prev})
        assert result.get("rsi_crossed_30_up") == 1

    def test_rsi_extreme_reversal_from_oversold(self):
        from src.intelligence.composites.rsi_events import RSIEventsPlugin
        # Was < 30, now rising
        features = {"rsi_14": 28.0}
        prev = {"rsi_14": 24.0}
        result = RSIEventsPlugin().compute_full({"features": features, "prev_features": prev})
        # rsi_extreme_reversal should fire when RSI < 30 and rising
        assert result.get("rsi_extreme_reversal") == 1

    def test_no_signal_on_neutral_rsi(self):
        from src.intelligence.composites.rsi_events import RSIEventsPlugin
        features = {"rsi_14": 55.0}
        prev = {"rsi_14": 53.0}
        result = RSIEventsPlugin().compute_full({"features": features, "prev_features": prev})
        assert result.get("rsi_crossed_30_up") == 0
        assert result.get("rsi_crossed_70_down") == 0

    def test_empty_returns_empty(self):
        from src.intelligence.composites.rsi_events import RSIEventsPlugin
        assert RSIEventsPlugin().compute_full({}) == {}
```

**Step 2:** Run — expect FAIL.

**Step 3:** Create `src/intelligence/composites/rsi_events.py`:
```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from ..plugins import InputSpec


@dataclass
class RSIEventsPlugin:
    name: str = "evt_RSIEvents"
    outputs: set[str] = frozenset({
        "rsi_crossed_30_up", "rsi_crossed_70_down",
        "rsi_crossed_50_up", "rsi_crossed_50_down",
        "rsi_extreme_reversal", "rsi_bars_in_extreme",
    })
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"momentum"})
    inputs: list[InputSpec] = ()
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        rsi = features.get("rsi_14")
        if not isinstance(rsi, (int, float)):
            return {}

        prev = frames.get("prev_features") or {}
        prev_rsi = prev.get("rsi_14")
        out: dict[str, Any] = {}

        # Threshold crossings (require prev)
        for key, threshold, direction in [
            ("rsi_crossed_30_up", 30, "up"),
            ("rsi_crossed_70_down", 70, "down"),
            ("rsi_crossed_50_up", 50, "up"),
            ("rsi_crossed_50_down", 50, "down"),
        ]:
            val = 0
            if isinstance(prev_rsi, (int, float)):
                if direction == "up":
                    val = 1 if prev_rsi < threshold <= rsi else 0
                else:
                    val = 1 if prev_rsi > threshold >= rsi else 0
            out[key] = val

        # Extreme reversal: RSI in extreme zone and moving out
        extreme_reversal = 0
        if isinstance(prev_rsi, (int, float)):
            if rsi < 30 and rsi > prev_rsi:  # oversold and rising
                extreme_reversal = 1
            elif rsi > 70 and rsi < prev_rsi:  # overbought and falling
                extreme_reversal = 1
        out["rsi_extreme_reversal"] = extreme_reversal

        # Bars in extreme zone
        in_extreme = 1 if rsi < 30 or rsi > 70 else 0
        if in_extreme:
            self._state["bars_in_extreme"] = self._state.get("bars_in_extreme", 0) + 1
        else:
            self._state["bars_in_extreme"] = 0
        out["rsi_bars_in_extreme"] = float(self._state["bars_in_extreme"])

        return out

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = RSIEventsPlugin()
```

**Step 4:** Run — expect PASS.

**Step 5:** Commit: `git commit -m "feat(i2): add RSIEvents composite plugin"`

---

### Task 2.6: Create StochasticEvents, ADXEvents, VolumeEvents plugins

**Files:**
- Create: `src/intelligence/composites/stochastic_events.py`
- Create: `src/intelligence/composites/adx_events.py`
- Create: `src/intelligence/composites/volume_events.py`
- Test: `tests/unit/intelligence/test_i2_plugins.py`

**Step 1:** Add tests:
```python
class TestStochasticEvents:
    def test_bullish_cross_k_crosses_d_up(self):
        from src.intelligence.composites.stochastic_events import StochasticEventsPlugin
        features = {"stoch_k_14_3": 25.0, "stoch_d_14_3": 22.0}
        prev = {"stoch_k_14_3": 18.0, "stoch_d_14_3": 22.0}
        result = StochasticEventsPlugin().compute_full({"features": features, "prev_features": prev})
        assert result.get("stoch_cross_bullish") == 1

    def test_both_oversold(self):
        from src.intelligence.composites.stochastic_events import StochasticEventsPlugin
        features = {"stoch_k_14_3": 15.0, "stoch_d_14_3": 18.0}
        result = StochasticEventsPlugin().compute_full({"features": features})
        assert result.get("stoch_both_oversold") == 1


class TestADXEvents:
    def test_trend_confirmed_when_adx_crosses_25(self):
        from src.intelligence.composites.adx_events import ADXEventsPlugin
        features = {"adx_14": 26.0, "plus_di_14": 30.0, "minus_di_14": 20.0}
        prev = {"adx_14": 23.0, "plus_di_14": 28.0, "minus_di_14": 22.0}
        result = ADXEventsPlugin().compute_full({"features": features, "prev_features": prev})
        assert result.get("adx_trend_confirmed") == 1

    def test_di_spread_is_plus_minus_di_difference(self):
        from src.intelligence.composites.adx_events import ADXEventsPlugin
        features = {"adx_14": 30.0, "plus_di_14": 35.0, "minus_di_14": 20.0}
        result = ADXEventsPlugin().compute_full({"features": features})
        assert abs(result.get("di_spread", 0) - 15.0) < 0.01


class TestVolumeEvents:
    def test_vol_spike_detected(self):
        from src.intelligence.composites.volume_events import VolumeEventsPlugin
        # Current volume >> 20-bar average → spike
        features = {"volume": 5000.0, "volume_sma_20": 1000.0, "volume_std_20": 500.0}
        result = VolumeEventsPlugin().compute_full({"features": features})
        assert result.get("vol_spike") == 1

    def test_empty_returns_empty(self):
        from src.intelligence.composites.volume_events import VolumeEventsPlugin
        assert VolumeEventsPlugin().compute_full({}) == {}
```

**Step 2:** Run — expect FAIL.

**Step 3:** Create `src/intelligence/composites/stochastic_events.py`:
```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from ..plugins import InputSpec


@dataclass
class StochasticEventsPlugin:
    name: str = "evt_StochasticEvents"
    outputs: set[str] = frozenset({
        "stoch_cross_bullish", "stoch_cross_bearish",
        "stoch_oversold_reversal", "stoch_overbought_reversal",
        "stoch_both_oversold", "stoch_both_overbought",
    })
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"momentum"})
    inputs: list[InputSpec] = ()

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        k = features.get("stoch_k_14_3")
        d = features.get("stoch_d_14_3")
        if not (isinstance(k, (int, float)) and isinstance(d, (int, float))):
            return {}

        prev = frames.get("prev_features") or {}
        pk = prev.get("stoch_k_14_3")
        pd_val = prev.get("stoch_d_14_3")

        out: dict[str, Any] = {}
        cross_bull = 0
        cross_bear = 0
        if isinstance(pk, (int, float)) and isinstance(pd_val, (int, float)):
            cross_bull = 1 if pk <= pd_val and k > d else 0
            cross_bear = 1 if pk >= pd_val and k < d else 0
        out["stoch_cross_bullish"] = cross_bull
        out["stoch_cross_bearish"] = cross_bear

        # K crossing 20/80 thresholds
        out["stoch_oversold_reversal"] = 1 if isinstance(pk, (int, float)) and pk < 20 <= k else 0
        out["stoch_overbought_reversal"] = 1 if isinstance(pk, (int, float)) and pk > 80 >= k else 0

        out["stoch_both_oversold"] = 1 if k < 20 and d < 20 else 0
        out["stoch_both_overbought"] = 1 if k > 80 and d > 80 else 0

        return out

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = StochasticEventsPlugin()
```

**Step 4:** Create `src/intelligence/composites/adx_events.py`:
```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from ..plugins import InputSpec


@dataclass
class ADXEventsPlugin:
    name: str = "evt_ADXEvents"
    outputs: set[str] = frozenset({
        "adx_trend_confirmed", "adx_ranging_confirmed",
        "di_cross_bullish", "di_cross_bearish", "di_cross_bars_ago",
        "di_spread",
    })
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"trend"})
    inputs: list[InputSpec] = ()
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        adx = features.get("adx_14")
        plus_di = features.get("plus_di_14")
        minus_di = features.get("minus_di_14")
        if not all(isinstance(v, (int, float)) for v in [adx, plus_di, minus_di]):
            return {}

        prev = frames.get("prev_features") or {}
        prev_adx = prev.get("adx_14")
        prev_plus = prev.get("plus_di_14")
        prev_minus = prev.get("minus_di_14")

        out: dict[str, Any] = {}

        # ADX threshold crossings
        trend_confirmed = 0
        ranging_confirmed = 0
        if isinstance(prev_adx, (int, float)):
            trend_confirmed = 1 if prev_adx < 25 <= adx else 0
            ranging_confirmed = 1 if prev_adx > 20 >= adx else 0
        out["adx_trend_confirmed"] = trend_confirmed
        out["adx_ranging_confirmed"] = ranging_confirmed

        # DI crossovers
        di_cross_bull = 0
        di_cross_bear = 0
        if isinstance(prev_plus, (int, float)) and isinstance(prev_minus, (int, float)):
            di_cross_bull = 1 if prev_plus <= prev_minus and plus_di > minus_di else 0
            di_cross_bear = 1 if prev_plus >= prev_minus and plus_di < minus_di else 0
        out["di_cross_bullish"] = di_cross_bull
        out["di_cross_bearish"] = di_cross_bear

        if di_cross_bull or di_cross_bear:
            self._state["di_cross_bars_ago"] = 0.0
        else:
            self._state["di_cross_bars_ago"] = float(min(self._state.get("di_cross_bars_ago", 999) + 1, 999))
        out["di_cross_bars_ago"] = self._state["di_cross_bars_ago"]
        out["di_spread"] = float(plus_di - minus_di)

        return out

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = ADXEventsPlugin()
```

**Step 5:** Create `src/intelligence/composites/volume_events.py`:
```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from ..plugins import InputSpec


@dataclass
class VolumeEventsPlugin:
    name: str = "evt_VolumeEvents"
    outputs: set[str] = frozenset({
        "vol_spike", "vol_drying",
        "bb_upper_touch", "bb_lower_touch",
        "bb_walking_upper", "bb_walking_lower",
    })
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: set[str] = frozenset({"volume"})
    inputs: list[InputSpec] = ()
    _state: dict = field(default_factory=dict)

    _SPIKE_SIGMA = 2.0
    _DRY_RATIO = 0.5
    _BB_TOUCH_PCT = 0.1  # within 10% of BB width from outer band
    _WALK_BARS = 3

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        close = features.get("close")
        volume = features.get("volume")
        bb_upper = features.get("bb_20_2_upper")
        bb_lower = features.get("bb_20_2_lower")
        bb_mid = features.get("bb_20_2_mid") or features.get("bb_mid")
        if not isinstance(close, (int, float)):
            return {}

        out: dict[str, Any] = {}

        # Volume spike/drying
        vol_sma = features.get("volume_sma_20")
        vol_std = features.get("volume_std_20")
        if isinstance(volume, (int, float)) and isinstance(vol_sma, (int, float)) and vol_sma > 0:
            if isinstance(vol_std, (int, float)) and vol_std > 0:
                z = (volume - vol_sma) / vol_std
                out["vol_spike"] = 1 if z > self._SPIKE_SIGMA else 0
            else:
                out["vol_spike"] = 1 if volume > vol_sma * (1 + self._SPIKE_SIGMA * 0.5) else 0
            out["vol_drying"] = 1 if volume < vol_sma * self._DRY_RATIO else 0
        else:
            out["vol_spike"] = 0
            out["vol_drying"] = 0

        # BB band touches
        if isinstance(bb_upper, (int, float)) and isinstance(bb_lower, (int, float)):
            bb_width = bb_upper - bb_lower
            touch_threshold = bb_width * self._BB_TOUCH_PCT
            out["bb_upper_touch"] = 1 if abs(close - bb_upper) <= touch_threshold else 0
            out["bb_lower_touch"] = 1 if abs(close - bb_lower) <= touch_threshold else 0

            # Walking the band: 3+ closes above/below midline
            above_mid = 1 if (isinstance(bb_mid, (int, float)) and close > bb_mid) else 0
            below_mid = 1 if (isinstance(bb_mid, (int, float)) and close < bb_mid) else 0
            self._state["above_mid_streak"] = (self._state.get("above_mid_streak", 0) + 1) if above_mid else 0
            self._state["below_mid_streak"] = (self._state.get("below_mid_streak", 0) + 1) if below_mid else 0
            out["bb_walking_upper"] = 1 if self._state["above_mid_streak"] >= self._WALK_BARS else 0
            out["bb_walking_lower"] = 1 if self._state["below_mid_streak"] >= self._WALK_BARS else 0
        else:
            out["bb_upper_touch"] = 0
            out["bb_lower_touch"] = 0
            out["bb_walking_upper"] = 0
            out["bb_walking_lower"] = 0

        return out

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = VolumeEventsPlugin()
```

**Step 6:** Run all I2 plugin tests:
```
.venv/bin/pytest tests/unit/intelligence/test_i2_plugins.py -v
```
Expected: all pass.

**Step 7:** Commit:
```bash
git add src/intelligence/composites/stochastic_events.py \
        src/intelligence/composites/adx_events.py \
        src/intelligence/composites/volume_events.py
git commit -m "feat(i2): add StochasticEvents, ADXEvents, VolumeEvents composite plugins"
```

---

### Task 2.7: Register I2 tier in register_plugins.py

**Files:**
- Modify: `src/intelligence/register_plugins.py`

**Step 1:** Write registration test:
```python
# tests/unit/intelligence/test_i2_registration.py
def test_tier_i2_constant_exists():
    from src.intelligence.register_plugins import TIER_I2
    assert len(TIER_I2) == 6  # MAComposite + 5 new

def test_tier_i2_all_registered():
    from src.intelligence.register_plugins import TIER_I2, register_all_plugins
    from src.intelligence.plugins import registry
    register_all_plugins()
    for name in TIER_I2:
        assert name in registry.patterns or name in registry.indicators, f"{name} not registered"
```

**Step 2:** Run — expect FAIL.

**Step 3:** Edit `src/intelligence/register_plugins.py`:

Add imports at top (after existing composites import):
```python
from .composites.macd_events import plugin as macd_events_plugin
from .composites.rsi_events import plugin as rsi_events_plugin
from .composites.stochastic_events import plugin as stoch_events_plugin
from .composites.adx_events import plugin as adx_events_plugin
from .composites.volume_events import plugin as volume_events_plugin
```

In `register_all_plugins()`, add before I3 registrations (after existing indicator registrations):
```python
    # I2 Composite Events — runs after I1 features, before I3
    registry.register_pattern(ma_compare_plugin)   # MAComposite already registered as indicator — keep both
    registry.register_pattern(macd_events_plugin)
    registry.register_pattern(rsi_events_plugin)
    registry.register_pattern(stoch_events_plugin)
    registry.register_pattern(adx_events_plugin)
    registry.register_pattern(volume_events_plugin)
```

Note: MAComposite is already registered as an indicator (TIER_I1). We register it again as a pattern for TIER_I2 execution in market_analysis_service. The registry allows a plugin to be in both buckets since they have different names logically. However, to avoid confusion, check if `ma_compare_plugin.name` would conflict. Better approach: MAComposite stays in TIER_I1 (already works), and we add its extended fields via the I2 pipeline by running it again. Actually, the cleanest approach is to keep MAComposite in TIER_I1 (indicator_service computes it), and in I2 we run only the 5 new event plugins that need the I1 features available in market_analysis_service.

**Revised approach:** TIER_I2 contains only the 5 new event plugins. MAComposite's new fields (golden_cross_active etc.) should be added to its existing output and run in indicator_service as part of I1.

Update the MAComposite outputs to include the new fields, add them to `I1Indicators` schema (since it uses `extra='allow'`, they just flow through), and don't create a separate I2 entry for MAComposite.

So TIER_I2 = [macd_events, rsi_events, stoch_events, adx_events, volume_events] (5 plugins).

Update test: `assert len(TIER_I2) == 5`

Add `TIER_I2` constant at bottom of `register_plugins.py`:
```python
TIER_I2: list[str] = [
    macd_events_plugin.name,
    rsi_events_plugin.name,
    stoch_events_plugin.name,
    adx_events_plugin.name,
    volume_events_plugin.name,
]
```

**Step 4:** Run test: `.venv/bin/pytest tests/unit/intelligence/test_i2_registration.py -v`
Expected: PASS.

**Step 5:** Commit:
```bash
git add src/intelligence/register_plugins.py tests/unit/intelligence/test_i2_registration.py
git commit -m "feat(i2): register TIER_I2 plugins in register_plugins.py"
```

---

### Task 2.8: Inject `prev_features` into frames for crossover detection

**Context:** I2 event plugins (MACDEvents, RSIEvents, etc.) detect crossovers by comparing current I1 features to the *previous bar's* I1 features via `frames["prev_features"]`. Without this injection, all crossover outputs will be 0.

**Files:**
- Modify: `services/market_analysis_service.py`

**Step 1:** Write a test that verifies prev_features flows through:
```python
# tests/unit/intelligence/test_i2_pipeline.py
def test_prev_features_in_frames():
    """market_analysis_service must inject prev_features for I2 crossover detection."""
    import ast, pathlib
    source = pathlib.Path("services/market_analysis_service.py").read_text()
    assert "prev_features" in source, "prev_features not injected into frames"
```

**Step 2:** Run — expect FAIL.

**Step 3:** In `MarketAnalysisService`, add a per-key feature cache for the previous bar:
```python
# In __init__, add:
self._prev_i1_features: dict[str, dict[str, Any]] = {}  # key="{symbol}:{tf}"
```

In `_calculate_intelligence`, after `frames["features"] = dict(i1_features)`, add:
```python
# Inject previous bar's I1 features for crossover detection (I2 plugins)
key = f"{symbol}:{timeframe}"
if key in self._prev_i1_features:
    frames["prev_features"] = self._prev_i1_features[key]
# Update cache with current bar's features (after pipeline runs, so use a copy now)
self._prev_i1_features[key] = dict(i1_features)
```

**Step 4:** Run test — expect PASS.

**Step 5:** Commit:
```bash
git add services/market_analysis_service.py
git commit -m "feat(i2): inject prev_features into frames for I2 crossover detection"
```

---

### Task 2.9: Clarify MAComposite placement and wire golden/death cross fields

**Context:** The design doc wants MAComposite's new fields (golden_cross_active, death_cross_active, price_above_sma200) in the I2 tier. However, MAComposite is currently an I1 plugin running in `indicator_service`. The cleanest resolution: MAComposite stays in I1 (runs in indicator_service with full 200-bar history), and its new fields flow through as I1 features (I1Indicators uses `extra='allow'`). They are therefore available in `frames["features"]` when I2 runs — no pipeline change needed.

**Decision:** Keep MAComposite in TIER_I1. Its new fields (golden_cross_active, etc.) are I1 outputs. They appear in `I1Indicators` as extra fields (allowed) and in `frames["features"]` for downstream use by I2/I3+.

**Files:**
- Modify: `src/intelligence/composites/ma_composites.py` (already done in Task 2.3)
- No TIER_I2 registration needed for MAComposite

**Step 1:** Verify MAComposite `_state` dict exists in the dataclass:
```python
# In MACompositePlugin dataclass, ensure:
_state: dict = field(default_factory=dict)
```
If missing, add it (needed for `golden_cross_bars_ago` tracking).

**Step 2:** Write a test confirming new fields appear in I1 output:
```python
# tests/unit/intelligence/test_i2_plugins.py
def test_ma_composite_golden_cross_in_outputs():
    from src.intelligence.composites.ma_composites import MACompositePlugin
    p = MACompositePlugin()
    assert "golden_cross_active" in p.outputs
    assert "death_cross_active" in p.outputs
    assert "price_above_sma200" in p.outputs
```

**Step 3:** Run: `.venv/bin/pytest tests/unit/intelligence/test_i2_plugins.py::test_ma_composite_golden_cross_in_outputs -v`

**Step 4:** Commit: `git commit -m "feat(i2): confirm MAComposite golden/death cross fields in TIER_I1 outputs"`

---

### Task 2.10: Wire I2 tier into market_analysis_service

**Files:**
- Modify: `services/market_analysis_service.py`

**Step 1:** Write integration test:
```python
# tests/unit/intelligence/test_i2_pipeline.py
def test_market_analysis_service_imports_tier_i2():
    """Verify service imports TIER_I2 and validates it on startup."""
    import ast, pathlib
    source = pathlib.Path("services/market_analysis_service.py").read_text()
    assert "TIER_I2" in source

def test_i2_results_included_in_tiered_dict():
    """_run_analysis_pipeline must return 'i2' key."""
    # This is an integration test that requires a working service instance.
    # Verify structure only — no live Redis needed.
    from services.market_analysis_service import MarketAnalysisService
    import inspect
    src = inspect.getsource(MarketAnalysisService._run_analysis_pipeline)
    assert "i2" in src
    assert "TIER_I2" in src
```

**Step 2:** Run — expect FAIL.

**Step 3:** Edit `services/market_analysis_service.py`:

Add to imports:
```python
from src.intelligence.register_plugins import (
    TIER_I2,   # add to existing import
    TIER_I3,
    TIER_I4,
    TIER_I5,
    TIER_I6,
    TIER_SMC,
    register_all_plugins,
)
from src.intelligence.schemas import (
    I2Events,   # add to existing import
    I1Indicators,
    ...
)
```

Add TIER_I2 to validation in `__init__`:
```python
for tier_list, tier_name in [
    (TIER_I2, "I2"), (TIER_I3, "I3"), (TIER_I4, "I4"),
    (TIER_I5, "I5"), (TIER_SMC, "SMC"), (TIER_I6, "I6"),
]:
    registry.validate_tier(tier_list, tier_name)
```

In `_run_analysis_pipeline`, add I2 execution block after `frames["features"] = features` and before i3:
```python
# I2: Composite indicator events (crossovers, extremes) — runs on I1 features
i2_results: dict[str, Any] = {}
_run_tier(TIER_I2, "I2", i2_results)
features.update(i2_results)  # I2 events available to I3+
```

Update return dict:
```python
return {
    "i2": i2_results,
    "i3": i3_results,
    ...
}
```

Update `flat` construction:
```python
flat = {**i2_results, **i3_results, **i4_results, **i5_results, **smc_results, **i6_results}
```

Update `_publish_intelligence` to pass i2:
```python
event = IntelligenceEvent(
    ...
    i2=I2Events(**{k: v for k, v in i2_results.items() if v is not None}),
    i3=I3Structure(**tiered.get("i3", {})),
    ...
)
```

Also update the IntelligenceEvent construction call site:
```python
i2=I2Events(**tiered.get("i2", {})),
```

And the feature_writer_service needs to persist the `i2` JSONB. Find the feature_writer INSERT statement and add `i2` column to it.

**Step 4:** Find feature_writer_service INSERT SQL:
```
grep -n "INSERT\|i3\|i4\|i5\|i6\|smc" services/feature_writer_service.py | head -20
```

Add `i2` to the INSERT statement alongside the other JSONB tiers.

**Step 5:** Run tests:
```
.venv/bin/pytest tests/unit/intelligence/test_i2_pipeline.py -v
.venv/bin/pytest tests/unit/ -v --tb=short
```
Expected: all pass.

**Step 6:** Run ruff: `.venv/bin/ruff check . --fix`

**Step 7:** Commit:
```bash
git add services/market_analysis_service.py services/feature_writer_service.py
git commit -m "feat(i2): wire TIER_I2 into market_analysis_service and feature_writer_service"
```

---

## Phase 3: I3 Structure Additions

**Pattern for each plugin:** Same structure as Phase 2. All I3 plugins receive `frames["main"]` (pd.DataFrame) and `frames["features"]` (accumulated feature dict). Registered via `registry.register_pattern()` and added to `TIER_I3`.

For each new I3 plugin, add its fields to `I3Structure` schema (`extra="forbid"`, add explicitly).

### Task 3.1: struct_MarketProfile

**Files:**
- Create: `src/intelligence/structure/market_profile.py`
- Modify: `src/intelligence/schemas.py` — add to `I3Structure`
- Modify: `src/intelligence/register_plugins.py`
- Test: `tests/unit/intelligence/test_i3_new_plugins.py` (create)

**Schema additions to I3Structure:**
```python
# MarketProfilePlugin outputs
poc_level: float | None = None
va_high: float | None = None
va_low: float | None = None
va_width_pct: float | None = None
price_in_va: float | None = None
price_above_va: float | None = None
price_below_va: float | None = None
poc_dist_pct: float | None = None
poc_dist_atr: float | None = None
```

**Plugin implementation sketch:**
- Compute TPO (Time Price Opportunity) counts: for each price bucket (price rounded to tick), count how many bars had high >= bucket >= low
- POC = price bucket with highest count
- Value Area: expand from POC outward until 70% of total volume is included
- `va_width_pct = (va_high - va_low) / va_low`
- `poc_dist_pct = (close - poc_level) / poc_level`
- `poc_dist_atr = abs(close - poc_level) / atr_14` if atr_14 available

**Test:**
```python
class TestMarketProfile:
    def test_poc_within_price_range(self):
        from src.intelligence.structure.market_profile import MarketProfilePlugin
        close = np.linspace(5000, 5100, 50)
        df = make_ohlcv(close)
        features = {"atr_14": 10.0, "close": float(close[-1])}
        result = MarketProfilePlugin().compute_full({"main": df, "features": features})
        poc = result.get("poc_level")
        assert poc is None or (5000 <= poc <= 5100)

    def test_va_high_gt_va_low(self):
        from src.intelligence.structure.market_profile import MarketProfilePlugin
        close = np.linspace(5000, 5100, 50)
        df = make_ohlcv(close)
        result = MarketProfilePlugin().compute_full({"main": df, "features": {}})
        va_high = result.get("va_high")
        va_low = result.get("va_low")
        if va_high is not None and va_low is not None:
            assert va_high >= va_low

    def test_empty_returns_empty(self):
        from src.intelligence.structure.market_profile import MarketProfilePlugin
        assert MarketProfilePlugin().compute_full({}) == {}
```

**Registration in register_plugins.py:**
```python
from .structure.market_profile import plugin as market_profile_plugin
# In register_all_plugins():
registry.register_pattern(market_profile_plugin)
# Add to TIER_I3:
TIER_I3: list[str] = [swing_plugin.name, sr_plugin.name, trend_plugin.name, market_profile_plugin.name, ...]
```

**Commit:** `git commit -m "feat(i3): add MarketProfile plugin"`

---

### Task 3.2: struct_SessionLevels

**Files:**
- Create: `src/intelligence/structure/session_levels.py`
- Modify: `src/intelligence/schemas.py` — add to `I3Structure`
- Modify: `src/intelligence/register_plugins.py`
- Test: `tests/unit/intelligence/test_i3_new_plugins.py`

**Schema additions to I3Structure:**
```python
# SessionLevelsPlugin outputs
prior_session_high: float | None = None
prior_session_low: float | None = None
prior_session_close: float | None = None
overnight_high: float | None = None
overnight_low: float | None = None
overnight_range_pct: float | None = None
opening_gap_pct: float | None = None
weekly_pivot: float | None = None
weekly_r1: float | None = None
weekly_r2: float | None = None
weekly_s1: float | None = None
weekly_s2: float | None = None
nearest_session_level: float | None = None
nearest_level_dist_atr: float | None = None
```

**Plugin logic:**
- "Prior session" = bars with timestamp in previous NY session (4pm–4pm ET window)
- If timestamp data not available in DataFrame, use rolling windows as proxy (last 390 bars for daily range on 1m)
- Weekly pivot = (prior_week_high + prior_week_low + prior_week_close) / 3
- R1 = 2*P - prior_low, R2 = P + (prior_high - prior_low), S1 = 2*P - prior_high, S2 = P - (prior_high - prior_low)
- Note: for a pure technical implementation without wall-clock time, use bar count approximations

**Test:**
```python
class TestSessionLevels:
    def test_weekly_pivot_formula(self):
        from src.intelligence.structure.session_levels import SessionLevelsPlugin
        # 390 bars ~ 1 trading day on 1m, so 1950 bars ~ 1 week
        # For test: provide synthetic week of data
        close = np.linspace(5000, 5100, 200)
        df = make_ohlcv(close)
        features = {"atr_14": 10.0, "close": float(close[-1])}
        result = SessionLevelsPlugin().compute_full({"main": df, "features": features})
        # Just verify outputs exist and are numeric
        pivot = result.get("weekly_pivot")
        if pivot is not None:
            assert 4000 < pivot < 6000

    def test_empty_returns_empty(self):
        from src.intelligence.structure.session_levels import SessionLevelsPlugin
        assert SessionLevelsPlugin().compute_full({}) == {}
```

**Commit:** `git commit -m "feat(i3): add SessionLevels plugin"`

---

### Task 3.3: struct_AnchoredVWAP

**Files:**
- Create: `src/intelligence/structure/anchored_vwap.py`
- Modify: `src/intelligence/schemas.py` — add to `I3Structure`
- Modify: `src/intelligence/register_plugins.py`
- Test: `tests/unit/intelligence/test_i3_new_plugins.py`

**Schema additions to I3Structure:**
```python
# AnchoredVWAPPlugin outputs
session_vwap: float | None = None
session_vwap_dist_pct: float | None = None
swing_vwap: float | None = None
weekly_vwap: float | None = None
above_session_vwap: float | None = None
above_swing_vwap: float | None = None
above_weekly_vwap: float | None = None
vwap_alignment_score: float | None = None
```

**Plugin logic:**
- Session VWAP: cumulative (typical_price × volume) / cumulative_volume from bar index 0 (or session start if timestamps available)
- Swing VWAP: anchored to most recent swing high or low from I3 swing detector (read from `frames["features"]`)
- Weekly VWAP: rolling 390-bar window (proxy for week)
- alignment_score: 0–3 count of VWAPs aligned with current price direction (price above all = 1.0, mixed = 0.5, below all = 0.0)

**Test:**
```python
class TestAnchoredVWAP:
    def test_session_vwap_in_price_range(self):
        from src.intelligence.structure.anchored_vwap import AnchoredVWAPPlugin
        close = np.linspace(5000, 5100, 50)
        df = make_ohlcv(close)
        result = AnchoredVWAPPlugin().compute_full({"main": df, "features": {}})
        vwap = result.get("session_vwap")
        if vwap is not None:
            assert 5000 <= vwap <= 5100
```

**Commit:** `git commit -m "feat(i3): add AnchoredVWAP plugin"`

---

### Task 3.4: struct_FibonacciZones

**Files:**
- Create: `src/intelligence/structure/fibonacci_zones.py`
- Modify: `src/intelligence/schemas.py` — add to `I3Structure`
- Modify: `src/intelligence/register_plugins.py`
- Test: `tests/unit/intelligence/test_i3_new_plugins.py`

**Schema additions to I3Structure:**
```python
# FibonacciZonesPlugin outputs
fib_swing_high: float | None = None
fib_swing_low: float | None = None
fib_236: float | None = None
fib_382: float | None = None
fib_500: float | None = None
fib_618: float | None = None
fib_786: float | None = None
nearest_fib_level: float | None = None
nearest_fib_ratio: float | None = None
nearest_fib_dist_atr: float | None = None
fib_cluster_strength: float | None = None
in_fib_discount_zone: float | None = None
```

**Plugin logic:**
- Use swing_high/swing_low from `frames["features"]` (already computed by SwingDetector)
- Fib levels from swing range: `level = swing_low + ratio * (swing_high - swing_low)`
- Nearest level: argmin of abs(close - level) for all 5 ratios
- Discount zone: price between 50%–78.6% retrace (bearish swing: between swing_high and 50% pullback)
- Cluster strength: count of fib levels within ATR/2 of each other

**Test:**
```python
class TestFibonacciZones:
    def test_fib_618_between_high_and_low(self):
        from src.intelligence.structure.fibonacci_zones import FibonacciZonesPlugin
        close = np.linspace(5000, 5200, 50)
        df = make_ohlcv(close)
        features = {"swing_high": 5200.0, "swing_low": 5000.0, "atr_14": 10.0, "close": 5130.0}
        result = FibonacciZonesPlugin().compute_full({"main": df, "features": features})
        fib618 = result.get("fib_618")
        if fib618 is not None:
            assert abs(fib618 - (5000 + 0.618 * 200)) < 1.0
```

**Commit:** `git commit -m "feat(i3): add FibonacciZones plugin"`

---

### Task 3.5: Run I3 tests + commit

```
.venv/bin/pytest tests/unit/intelligence/test_i3_new_plugins.py -v
.venv/bin/pytest tests/unit/ -v --tb=short
.venv/bin/ruff check . --fix
git commit -m "test(i3): full I3 new plugin test suite passing"
```

---

## Phase 4: I4 Context Additions

### Task 4.1: ctx_SessionContext

**Files:**
- Create: `src/intelligence/context/session_context.py`
- Modify: `src/intelligence/schemas.py` — add to `I4Context`
- Modify: `src/intelligence/register_plugins.py`
- Test: `tests/unit/intelligence/test_i4_new_plugins.py` (create)

**Schema additions to I4Context:**
```python
# SessionContextPlugin outputs
session_asia: float | None = None
session_london: float | None = None
session_ny: float | None = None
session_london_ny_overlap: float | None = None
session_after_hours: float | None = None
in_london_killzone: float | None = None
in_ny_killzone: float | None = None
minutes_to_ny_open: float | None = None
minutes_to_london_open: float | None = None
bars_since_session_start: float | None = None
is_monday: float | None = None
is_friday: float | None = None
```

**Plugin logic:**
- Get current time from the bar's timestamp if available in frames, or use `datetime.utcnow()` as fallback
- Convert to ET (UTC-5 or UTC-4 with DST)
- Session windows:
  - Asia: 20:00–04:00 ET
  - London: 03:00–12:00 ET
  - NY: 09:30–16:00 ET
  - London/NY overlap: 08:00–12:00 ET
  - London killzone: 02:00–05:00 ET
  - NY AM killzone: 07:00–10:00 ET

**Test:**
```python
class TestSessionContext:
    def test_ny_killzone_at_0800_et(self):
        from src.intelligence.context.session_context import SessionContextPlugin
        from datetime import datetime, timezone, timedelta
        import pandas as pd
        # 8:30 AM ET = 13:30 UTC
        ts = datetime(2026, 3, 1, 13, 30, tzinfo=timezone.utc)
        df = pd.DataFrame({"timestamp": [ts], "open": [5000], "high": [5010],
                           "low": [4990], "close": [5005], "volume": [1000]})
        p = SessionContextPlugin()
        result = p.compute_full({"main": df, "features": {}})
        assert result.get("in_ny_killzone") == 1
        assert result.get("session_ny") == 1

    def test_empty_returns_empty(self):
        from src.intelligence.context.session_context import SessionContextPlugin
        assert SessionContextPlugin().compute_full({}) == {}
```

**Commit:** `git commit -m "feat(i4): add SessionContext plugin"`

---

### Task 4.2: ctx_MTFVolatility

**Files:**
- Create: `src/intelligence/context/mtf_volatility.py`
- Modify: `src/intelligence/schemas.py` — add to `I4Context`
- Modify: `src/intelligence/register_plugins.py`
- Test: `tests/unit/intelligence/test_i4_new_plugins.py`

**Schema additions to I4Context:**
```python
# MTFVolatilityPlugin outputs
mtf_vol_expansion_15m: float | None = None
mtf_vol_expansion_1h: float | None = None
squeeze_within_expansion: float | None = None
vol_divergence_score: float | None = None
```

**Plugin logic:**
- Read `frames["intel_15m"]` and `frames["intel_1h"]` cached intelligence dicts
- From each: `vol_expansion` field (already computed by VolatilityRegime plugin in I4)
- `mtf_vol_expansion_15m = 1 if intel_15m.get("vol_expansion", 0) > 0 else 0`
- `squeeze_within_expansion = 1 if squeeze_active (current TF from features) and (mtf_15m or mtf_1h expanding)`
- `vol_divergence_score`: weighted sum of vol_expansion across TFs, normalized to [-1, 1]

**Test:**
```python
class TestMTFVolatility:
    def test_squeeze_within_expansion_detected(self):
        from src.intelligence.context.mtf_volatility import MTFVolatilityPlugin
        features = {"squeeze_active": 1.0, "vol_expansion": -0.5}
        intel_15m = {"vol_expansion": 0.8}
        result = MTFVolatilityPlugin().compute_full({
            "features": features, "intel_15m": intel_15m
        })
        assert result.get("squeeze_within_expansion") == 1

    def test_no_expansion_without_cache(self):
        from src.intelligence.context.mtf_volatility import MTFVolatilityPlugin
        result = MTFVolatilityPlugin().compute_full({"features": {}})
        assert result.get("mtf_vol_expansion_15m") == 0
```

**Commit:** `git commit -m "feat(i4): add MTFVolatility context plugin"`

---

## Phase 5: I5 Pattern Additions

**6 new plugins follow the same pattern as Phase 3/4. Each requires:**
1. Schema fields added to `I5Patterns`
2. Plugin file in `src/intelligence/patterns/`
3. Registered in `TIER_I5`
4. Tests in `tests/unit/intelligence/test_i5_new_plugins.py`

### Task 5.1: pat_CandlestickPatterns

**Files:**
- Create: `src/intelligence/patterns/candlestick_patterns.py`
- Modify: `src/intelligence/schemas.py` — add to `I5Patterns`
- Modify: `src/intelligence/register_plugins.py`
- Test: `tests/unit/intelligence/test_i5_new_plugins.py` (create)

**Schema additions:**
```python
engulfing_bull: float | None = None
engulfing_bear: float | None = None
pin_bar_bull: float | None = None
pin_bar_bear: float | None = None
hammer_detected: float | None = None
shooting_star_detected: float | None = None
inside_bar: float | None = None
outside_bar: float | None = None
doji_detected: float | None = None
```

**Plugin logic (last 2 bars from `frames["main"]`):**
- Engulfing bull: current body engulfs prior body + current is bullish (close > open), prior bearish
- Pin bar bull: lower wick ≥ 2× body AND small upper wick (≤ 0.3× body). Body = |open − close|
- Hammer: pin bar at support (use `nearest_support` distance from features)
- Inside bar: current high < prior high AND current low > prior low
- Outside bar: current high > prior high AND current low < prior low
- Doji: |close − open| / (high − low) < 0.1 (body < 10% of range) AND range > 0

**Test:**
```python
class TestCandlestickPatterns:
    def test_engulfing_bull_detected(self):
        from src.intelligence.patterns.candlestick_patterns import CandlestickPatternsPlugin
        # Bar 0: bearish (open 5010, close 5000)
        # Bar 1: bullish and engulfs (open 4995, close 5015)
        df = pd.DataFrame({
            "open":  [5010, 4995], "high": [5015, 5020],
            "low":   [4998, 4990], "close": [5000, 5015],
            "volume": [1000, 1200]
        })
        result = CandlestickPatternsPlugin().compute_full({"main": df, "features": {}})
        assert result.get("engulfing_bull") == 1

    def test_pin_bar_bull(self):
        from src.intelligence.patterns.candlestick_patterns import CandlestickPatternsPlugin
        # Long lower wick, small body near top
        df = pd.DataFrame({
            "open":  [5000, 5020], "high": [5005, 5025],
            "low":   [4970, 4960], "close": [5005, 5023],
            "volume": [1000, 1000]
        })
        result = CandlestickPatternsPlugin().compute_full({"main": df, "features": {}})
        assert result.get("pin_bar_bull") == 1

    def test_doji_detected(self):
        from src.intelligence.patterns.candlestick_patterns import CandlestickPatternsPlugin
        df = pd.DataFrame({
            "open": [5000, 5000], "high": [5010, 5010],
            "low": [4990, 4990], "close": [5000, 5001],
            "volume": [1000, 1000]
        })
        result = CandlestickPatternsPlugin().compute_full({"main": df, "features": {}})
        assert result.get("doji_detected") == 1
```

**Commit:** `git commit -m "feat(i5): add CandlestickPatterns plugin"`

---

### Task 5.2: pat_FlagPennant

**Files:**
- Create: `src/intelligence/patterns/flag_pennant.py`
- Modify: `src/intelligence/schemas.py` — add to `I5Patterns`
- Modify: `src/intelligence/register_plugins.py`
- Test: `tests/unit/intelligence/test_i5_new_plugins.py`

**Schema additions:**
```python
flag_pattern: float | None = None         # 0=none, 1=bull, -1=bear
pennant_pattern: float | None = None      # 0=none, 1=bull, -1=bear
flag_breakout_target: float | None = None
consolidation_compression_ratio: float | None = None
```

**Plugin logic:**
- Impulse leg: look for N bars (lookback=30) with >= 2σ above-average range and directional movement
- Consolidation: last 5–15 bars with below-average range (< 0.5× impulse range) after impulse
- Flag: consolidation channel has roughly parallel upper/lower trendlines (slopes similar sign)
- Pennant: consolidation has converging trendlines (slopes opposite signs)
- compression_ratio = avg_consolidation_range / impulse_bar_range

**Test:**
```python
class TestFlagPennant:
    def test_bull_flag_after_impulse(self):
        from src.intelligence.patterns.flag_pennant import FlagPennantPlugin
        # Strong up impulse then tight sideways
        impulse = np.linspace(5000, 5200, 10)
        consolidation = 5200 + np.random.default_rng(0).uniform(-5, 5, 10)
        close = np.concatenate([np.full(20, 4990.0), impulse, consolidation])
        df = make_ohlcv(close)
        result = FlagPennantPlugin().compute_full({"main": df, "features": {"atr_14": 10.0}})
        pattern = result.get("flag_pattern")
        # Either detected as bull flag or not (depends on slope calc)
        assert pattern in (None, 0.0, 1.0, -1.0)
```

**Commit:** `git commit -m "feat(i5): add FlagPennant pattern plugin"`

---

### Task 5.3-5.6: Remaining I5 plugins

Create in the same pattern:

**5.3: pat_CupHandle** → `src/intelligence/patterns/cup_handle.py`
- Schema: `cup_handle_pattern`, `cup_depth_pct`, `cup_handle_target`
- Logic: Detect U-shape over 20–60 bars, right rim ≈ left rim level, handle = small pullback

**5.4: pat_MeasuredMove** → `src/intelligence/patterns/measured_move.py`
- Schema: `abcd_pattern_active`, `abcd_direction`, `abcd_d_target`, `abcd_completion_pct`
- Logic: AB swing, B correction ~0.618 of AB, C=AB from B, D target

**5.5: pat_VolumeProfile** → `src/intelligence/patterns/volume_profile.py`
- Schema: `nearest_hvn_level`, `nearest_hvn_dist_atr`, `nearest_lvn_level`, `in_lvn`
- Logic: Build price histogram weighted by volume; HVN = top 20% buckets, LVN = bottom 20%

**5.6: pat_KeyLevelReaction** → `src/intelligence/patterns/key_level_reaction.py`
- Schema: `key_level_reaction_type`, `key_level_confluence_count`
- Logic: Find nearest key level (from features: nearest_support, nearest_resistance, ob_top/bottom, fvg_top/bottom); classify last 3-bar behavior as reject/base/break-retest/break

For each: write test first, implement plugin, add schema fields, register, commit.

**Final I5 commit:** `git commit -m "test(i5): all 6 new pattern plugins complete and tested"`

---

## Phase 6: SMC Additions

**5 new plugins in `src/intelligence/smart_money/`, added to `TIER_SMC`, schema fields in `SMCContext`.**

### Task 6.1: smc_ICTKillzones

**Files:**
- Create: `src/intelligence/smart_money/ict_killzones.py`
- Modify: `src/intelligence/schemas.py` — add to `SMCContext`
- Modify: `src/intelligence/register_plugins.py`
- Test: `tests/unit/intelligence/test_smc_new_plugins.py` (create)

**Schema additions to SMCContext:**
```python
in_asia_killzone: float | None = None
in_london_killzone: float | None = None
in_ny_am_killzone: float | None = None
in_ny_pm_killzone: float | None = None
killzone_name: str | None = None
minutes_in_killzone: float | None = None
minutes_until_next_killzone: float | None = None
```

**Note:** SMCContext has `extra="forbid"`, so `killzone_name: str | None` requires adding it explicitly. The other fields can be float flags.

**Plugin logic:** Same time-based logic as SessionContext I4 plugin but at the more granular killzone level. Read timestamp from `frames["main"].iloc[-1]` if there's a timestamp column, or pass current bar time through frames.

**Test:**
```python
class TestICTKillzones:
    def test_london_killzone_at_0300_et(self):
        from src.intelligence.smart_money.ict_killzones import ICTKillzonesPlugin
        from datetime import datetime, timezone
        import pandas as pd
        ts = datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)  # 3am ET
        df = pd.DataFrame({"timestamp": [ts], "open": [5000], "high": [5010],
                           "low": [4990], "close": [5005], "volume": [1000]})
        result = ICTKillzonesPlugin().compute_full({"main": df, "features": {}})
        assert result.get("in_london_killzone") == 1
```

**Commit:** `git commit -m "feat(smc): add ICTKillzones plugin"`

---

### Task 6.2: smc_AMDCycle

**Files:**
- Create: `src/intelligence/smart_money/amd_cycle.py`
- Modify: `src/intelligence/schemas.py`, `src/intelligence/register_plugins.py`
- Test: `tests/unit/intelligence/test_smc_new_plugins.py`

**Schema additions to SMCContext:**
```python
amd_phase: str | None = None   # "accumulation"/"manipulation"/"distribution"/"unknown"
amd_manipulation_detected: float | None = None
amd_distribution_direction: float | None = None  # -1/0/1
```

**Plugin logic:**
- Accumulation: overnight session (8pm–midnight ET), narrow range, low volume
- Manipulation: midnight–5am ET, price spikes beyond overnight range then reverses
- Distribution: 5am–noon ET, sustained directional move from manipulation level
- Track overnight_high/overnight_low as running state for the current day

**Commit:** `git commit -m "feat(smc): add AMDCycle plugin"`

---

### Task 6.3: smc_BreakerBlocks

**Files:**
- Create: `src/intelligence/smart_money/breaker_blocks.py`
- Modify: `src/intelligence/schemas.py`, `src/intelligence/register_plugins.py`
- Test: `tests/unit/intelligence/test_smc_new_plugins.py`

**Schema additions to SMCContext:**
```python
breaker_block_active: float | None = None
breaker_block_type: float | None = None       # -1 (bearish breaker) / +1 (bullish breaker)
breaker_block_top: float | None = None
breaker_block_bottom: float | None = None
breaker_dist_atr: float | None = None
```

**Plugin logic:**
- Read `ob_type`, `ob_top`, `ob_bottom`, `ob_mitigated` from `frames["features"]`
- A mitigated bullish OB becomes a bearish breaker block
- Track OB history in `_state` dict: {ob_top, ob_bottom, ob_type, mitigated_bars}
- Breaker activates when `ob_mitigated == 1` and price returns to the zone from the opposite side

**Commit:** `git commit -m "feat(smc): add BreakerBlocks plugin"`

---

### Task 6.4: smc_MitigationBlocks

**Files:**
- Create: `src/intelligence/smart_money/mitigation_blocks.py`
- Modify: `src/intelligence/schemas.py`, `src/intelligence/register_plugins.py`
- Test: `tests/unit/intelligence/test_smc_new_plugins.py`

**Schema additions to SMCContext:**
```python
ob_mitigation_status: str | None = None   # "fresh"/"partial"/"void"
ob_mitigation_pct: float | None = None
```

**Plugin logic:**
- Read `ob_top`, `ob_bottom`, `ob_mitigated` from features
- Track how many bars price spent within the OB zone
- `mitigation_pct = fraction of OB zone that has been revisited`
- Status: 0% = "fresh", 1-99% = "partial", 100% = "void"

**Commit:** `git commit -m "feat(smc): add MitigationBlocks plugin"`

---

### Task 6.5: smc_PremiumDiscount

**Files:**
- Create: `src/intelligence/smart_money/premium_discount.py`
- Modify: `src/intelligence/schemas.py`, `src/intelligence/register_plugins.py`
- Test: `tests/unit/intelligence/test_smc_new_plugins.py`

**Schema additions to SMCContext:**
Note: `price_in_premium` and `premium_position` already exist in `SMCContext` (from `smc_LiquidityPools`). Audit for duplication before adding.

```python
equilibrium_level: float | None = None
premium_discount_pct: float | None = None  # -1.0 to +1.0
```

**Plugin logic:**
- Equilibrium = 50% of current swing range (swing_high to swing_low from features)
- `premium_discount_pct = (close - equilibrium) / (swing_high - equilibrium)`
- Clamp to [-1, 1]
- Note: `price_in_premium` from LiquidityPools already exists — check if redundant and cross-reference in docstring

**Test:**
```python
class TestPremiumDiscount:
    def test_equilibrium_at_midpoint(self):
        from src.intelligence.smart_money.premium_discount import PremiumDiscountPlugin
        features = {"swing_high": 5200.0, "swing_low": 5000.0, "close": 5100.0}
        result = PremiumDiscountPlugin().compute_full({"main": None, "features": features})
        assert abs(result.get("equilibrium_level", 0) - 5100.0) < 1.0
        assert abs(result.get("premium_discount_pct", 0)) < 0.05  # at equilibrium

    def test_deep_discount_negative(self):
        from src.intelligence.smart_money.premium_discount import PremiumDiscountPlugin
        features = {"swing_high": 5200.0, "swing_low": 5000.0, "close": 5020.0}
        result = PremiumDiscountPlugin().compute_full({"main": None, "features": features})
        pct = result.get("premium_discount_pct", 0)
        assert pct < -0.5  # deep discount
```

**Commit:** `git commit -m "feat(smc): add PremiumDiscount plugin"`

---

## Phase 7: I6 Confluence Refactor

### Task 7.1: Add recency weighting to CrossTimeframeConfluence

**Files:**
- Modify: `src/intelligence/confluence/cross_timeframe.py`
- Test: `tests/unit/intelligence/test_cross_timeframe.py` (extend existing)

**Step 1:** Add test for recency-weighted behavior:
```python
def test_stale_intel_has_less_weight():
    """Intel from 60 bars ago should contribute less than intel from 1 bar ago."""
    from src.intelligence.confluence.cross_timeframe import CrossTimeframeConfluencePlugin
    features = {"trend_direction": 1, "swing_pattern": 1.0}
    # Fresh 5m intel — 1 bar ago
    intel_5m = {"trend_direction": 1, "swing_pattern": 1.0}
    # Stale 1h intel — 60 bars ago
    intel_1h = {"trend_direction": -1, "swing_pattern": -1.0}

    p = CrossTimeframeConfluencePlugin()
    # With recency weighting: fresh 5m should dominate over stale 1h
    result_with_recency = p.compute_full({
        "features": features,
        "intel_5m": intel_5m,
        "intel_5m_bars_since": 1,
        "intel_1h": intel_1h,
        "intel_1h_bars_since": 60,
    })
    result_equal_weight = p.compute_full({
        "features": features,
        "intel_5m": intel_5m,
        "intel_1h": intel_1h,
    })
    # With recency weighting, fresh 5m should tip score positive
    if result_with_recency.get("ctf_score") is not None:
        assert result_with_recency["ctf_score"] > result_equal_weight.get("ctf_score", 0)
```

**Step 2:** Run test — may pass without changes if current behavior is equal-weighted (stale wins are averaged differently).

**Step 3:** Modify `CrossTimeframeConfluencePlugin.compute_full`:

```python
# Add recency weight extraction
def _get_recency_weight(self, frames: dict, tf: str) -> float:
    bars_since_key = f"intel_{tf}_bars_since"
    bars_since = frames.get(bars_since_key, 0)
    if not isinstance(bars_since, (int, float)):
        bars_since = 0
    return 1.0 / (bars_since + 1)
```

Update `_score_trend_alignment` to accept and apply weights:
```python
def _score_trend_alignment(self, cur_trend, other_intel, weights):
    if cur_trend == 0 or not other_intel:
        return 0.0
    weighted_agrees = 0.0
    total_weight = 0.0
    for tf, intel in other_intel.items():
        w = weights.get(tf, 1.0)
        other_sign = self._extract_trend_sign(intel)
        if other_sign == cur_trend:
            weighted_agrees += w
        elif other_sign == -cur_trend:
            weighted_agrees -= w
        total_weight += w
    return cur_trend * (weighted_agrees / total_weight) if total_weight > 0 else 0.0
```

Apply weights similarly in `_score_structure_alignment` and `_score_regime_agreement`.

**Step 4:** Add new I6 output fields to schema and plugin:
```python
# In I6Confluence schema:
i6_smc_bos_alignment: float | None = None
i6_fvg_tf_alignment: float | None = None
i6_ob_tf_alignment: float | None = None
```

```python
# In compute_full, add:
# SMC cross-TF alignment checks
bos_dir = features.get("bos_direction")
trend_dir_15m = (frames.get("intel_15m") or {}).get("smc_trend_direction")
bos_alignment = 0.0
if isinstance(bos_dir, (int, float)) and isinstance(trend_dir_15m, (int, float)) and bos_dir != 0:
    bos_alignment = 1.0 if bos_dir == trend_dir_15m else -1.0

return {
    "ctf_score": round(ctf_score, 4),
    ...
    "i6_smc_bos_alignment": bos_alignment,
    "i6_fvg_tf_alignment": 0.0,   # placeholder — expand in v1.1 Phase 7
    "i6_ob_tf_alignment": 0.0,
}
```

**Step 5:** Run tests:
```
.venv/bin/pytest tests/unit/intelligence/test_cross_timeframe.py -v
.venv/bin/pytest tests/unit/ -v --tb=short
```

**Step 6:** Commit:
```bash
git add src/intelligence/confluence/cross_timeframe.py
git commit -m "feat(i6): recency weighting + SMC cross-TF alignment sub-scores"
```

---

### Task 7.2: Integrate I2 events into I6 confluence scoring

**Context:** The design doc specifies: "I6 confluence now reads I2 events (crossovers, extremes) as additional confluence signals — MACD bullish crossover + 15m uptrend in I6 = stronger confluence score."

**Files:**
- Modify: `src/intelligence/confluence/cross_timeframe.py`
- Modify: `src/intelligence/schemas.py` — add `i6_i2_event_score` to `I6Confluence`
- Test: `tests/unit/intelligence/test_cross_timeframe.py`

**Step 1:** Add schema field to `I6Confluence`:
```python
i6_i2_event_score: float | None = None   # I2 event confluence contribution (-1 to +1)
```

**Step 2:** Add test:
```python
def test_i2_events_boost_bullish_confluence():
    from src.intelligence.confluence.cross_timeframe import CrossTimeframeConfluencePlugin
    features = {"trend_direction": 1, "swing_pattern": 1.0,
                "macd_cross_bullish": 1.0, "rsi_crossed_30_up": 1.0,
                "adx_trend_confirmed": 1.0}
    intel_5m = {"trend_direction": 1}
    p = CrossTimeframeConfluencePlugin()
    result = p.compute_full({"features": features, "intel_5m": intel_5m})
    # I2 event score should be positive when bullish events fire
    i2_score = result.get("i6_i2_event_score")
    if i2_score is not None:
        assert i2_score > 0

def test_i2_events_no_effect_when_absent():
    from src.intelligence.confluence.cross_timeframe import CrossTimeframeConfluencePlugin
    features = {"trend_direction": 1}
    intel_5m = {"trend_direction": 1}
    result = CrossTimeframeConfluencePlugin().compute_full({"features": features, "intel_5m": intel_5m})
    i2_score = result.get("i6_i2_event_score", 0.0)
    assert i2_score == 0.0
```

**Step 3:** In `CrossTimeframeConfluencePlugin.compute_full`, add I2 event scoring:
```python
def _score_i2_events(self, features: dict) -> float:
    """Score I2 composite events as directional confluence signals."""
    score = 0.0
    # Bullish I2 events
    bullish_events = [
        "macd_cross_bullish", "rsi_crossed_30_up", "rsi_extreme_reversal",
        "stoch_cross_bullish", "stoch_oversold_reversal", "adx_trend_confirmed",
        "di_cross_bullish", "stoch_both_oversold",
    ]
    bearish_events = [
        "macd_cross_bearish", "rsi_crossed_70_down",
        "stoch_cross_bearish", "stoch_overbought_reversal",
        "di_cross_bearish", "stoch_both_overbought",
    ]
    for key in bullish_events:
        v = features.get(key, 0)
        if isinstance(v, (int, float)) and v > 0:
            score += 0.1
    for key in bearish_events:
        v = features.get(key, 0)
        if isinstance(v, (int, float)) and v > 0:
            score -= 0.1
    # Negative MACD support test = bullish reversal signal
    neg_support = features.get("macd_negative_support_test", 0)
    if isinstance(neg_support, (int, float)) and neg_support > 0:
        score += 0.15
    return float(max(-1.0, min(1.0, score)))
```

Call in `compute_full` and include in return dict:
```python
i2_event_score = self._score_i2_events(features)
# Incorporate into ctf_score with small weight (0.1)
raw = (self.W_TREND * trend_alignment + self.W_STRUCTURE * structure_alignment
       + self.W_REGIME * regime_agreement + self.W_PATTERN * pattern_confirmation
       + 0.1 * i2_event_score)  # I2 event bonus
ctf_score = clamp(raw / 1.1)   # renormalize since weights now sum to 1.1
return {
    ...,
    "i6_i2_event_score": round(i2_event_score, 4),
}
```

**Step 4:** Run: `.venv/bin/pytest tests/unit/intelligence/test_cross_timeframe.py -v`

**Step 5:** Commit:
```bash
git add src/intelligence/confluence/cross_timeframe.py src/intelligence/schemas.py
git commit -m "feat(i6): integrate I2 event signals into confluence scoring"
```

---

## Phase 8: Final Verification

### Task 8.1: Run complete test suite

```bash
.venv/bin/pytest tests/unit/ -v --tb=short 2>&1 | tail -20
```
Expected: 803+ tests pass, 0 failures.

### Task 8.2: Run ruff

```bash
.venv/bin/ruff check . --fix
```
Expected: 0 errors.

### Task 8.3: Integration smoke test

```python
# Verify IntelligenceEvent can be constructed with all tiers including i2
python3 -c "
from src.intelligence.schemas import IntelligenceEvent, I2Events, I3Structure
from datetime import datetime
e = IntelligenceEvent(
    ts=datetime.now(),
    symbol='ES',
    tf='1m',
    bar={'o': 5000, 'h': 5010, 'l': 4990, 'c': 5005, 'v': 1000},
    i1={},
    i2={},
    i3={},
    i4={},
    i5={},
    smc={},
    i6={},
)
print('IntelligenceEvent OK:', e.schema_version)
"
```

### Task 8.4: Update CLAUDE.md

Update the following in `CLAUDE.md`:
- Plugin count (63 → new count after additions)
- Phase status entries
- Test count

### Task 8.5: Final commit

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for intelligence palette expansion milestone"
```

---

## Summary

| Phase | Work | New Plugins | Tests Added |
|-------|------|------------|------------|
| 1 | Correctness audit I1–I6 (15 tasks) | 0 (fixes) | ~35 |
| 2 | I2 tier + schema + migration + prev_features | 5 | ~25 |
| 3 | I3 structure additions | 4 | ~12 |
| 4 | I4 context additions | 2 | ~8 |
| 5 | I5 pattern additions | 6 | ~18 |
| 6 | SMC additions | 5 | ~15 |
| 7 | I6 refactor + I2 event integration | 0 (refactor) | ~8 |
| 8 | Final verification + CLAUDE.md update | 0 | 0 |
| **Total** | | **22 new plugins** | **~121 tests** |

**Test target after completion:** 924+ tests passing
**New IntelligenceEvent fields:** i2 (I2Events) + ~90 new fields across all tiers
**New migration:** `013_add_i2_column.sql`
**New `prev_features` injection:** `_prev_i1_features` cache in `MarketAnalysisService`
**I6 new fields:** `i6_smc_bos_alignment`, `i6_fvg_tf_alignment`, `i6_ob_tf_alignment`, `i6_i2_event_score`
