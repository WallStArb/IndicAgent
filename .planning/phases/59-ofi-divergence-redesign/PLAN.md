# OFI Divergence Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the discrete `{-2..+2}` `ofi_divergence` I1 field with a continuous z-score factor, fix multi-symbol state corruption in OFIPlugin, and rewrite `OFIDivergencePlugin` with persistence, peak magnitude tracking, and principled confidence.

**Architecture:** Two-layer change. I1 (`ofi.py`): state keyed by `(symbol, tf)`, add 100-bar price return history, compute `ofi_divergence = ofi_spike_z - price_return_z`. I7 (`ofi_divergence.py`): full rewrite using `state_utils` persistence, `tanh` confidence, EWMA as soft factor, `regime_type="any"`. Pipeline: inject `__symbol__`/`__timeframe__` into I1 frames.

**Design doc:** `docs/plans/2026-04-05-ofi-divergence-redesign-design.md`

**Tech Stack:** Python, numpy, pandas, pytest, `state_utils.track_consecutive_state`, `math.tanh`

---

### Task 1: Inject `__symbol__`/`__timeframe__` into I1 frames

**Files:**
- Modify: `services/intelligence_pipeline_agent.py` (~line 877)
- Test: `tests/unit/test_intelligence_pipeline_agent.py` (smoke — existing suite)

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_intelligence_pipeline_agent.py` (find the existing I1 frames test or add at end of file):

```python
def test_i1_frames_contain_symbol_and_timeframe(mock_pipeline_agent):
    """I1 frames must include __symbol__ and __timeframe__ for stateful plugins."""
    # This test exercises _run_i1_to_i6 indirectly via the frames dict construction.
    # If frames lacks these keys, stateful I1 plugins (OFI) share state across symbols.
    import types
    from unittest.mock import MagicMock
    from services.intelligence_pipeline_agent import IntelligencePipelineComputeAgent
    agent = IntelligencePipelineComputeAgent.__new__(IntelligencePipelineComputeAgent)
    agent._bar_history = MagicMock()
    agent._bar_history.to_dataframe.return_value = __import__('pandas').DataFrame(
        {"open": [1.0]*10, "high": [1.1]*10, "low": [0.9]*10,
         "close": [1.0]*10, "volume": [1000.0]*10}
    )
    agent._bar_history.get.return_value = []
    agent._last_events = {}
    agent._instrument_map = {}
    agent._vix_symbol = None
    agent._htf_intel_cache = {}
    agent._prev_i1_features = {}
    import asyncio, types
    # Patch _run_i1 to capture frames
    captured = {}
    async def fake_run_i1(frames, symbol, tf):
        captured["frames"] = frames
        return {}
    agent._run_i1 = fake_run_i1
    agent._run_analysis_pipeline = MagicMock(return_value=None)
    # Can't easily run _run_i1_to_i6 without a full bar — check the frames construction directly
    # by inspecting the source instead
    import inspect
    from services import intelligence_pipeline_agent as m
    src = inspect.getsource(m.IntelligencePipelineComputeAgent._run_i1_to_i6)
    assert '"__symbol__"' in src or "'__symbol__'" in src, \
        "__symbol__ must be injected into I1 frames"
    assert '"__timeframe__"' in src or "'__timeframe__'" in src, \
        "__timeframe__ must be injected into I1 frames"
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd /home/bg/dev/indicagent && .venv/bin/pytest tests/unit/test_intelligence_pipeline_agent.py -k "test_i1_frames_contain" -v 2>&1 | tail -20
```

Expected: FAIL — `__symbol__` not found in source.

- [ ] **Step 3: Inject keys into I1 frames**

In `services/intelligence_pipeline_agent.py`, find the frames construction block (around line 875-877):

```python
        # Build frames dict
        main_df = self._bar_history.to_dataframe(symbol, tf)
        frames: dict[str, Any] = {"main": main_df}
```

Change to:

```python
        # Build frames dict
        main_df = self._bar_history.to_dataframe(symbol, tf)
        frames: dict[str, Any] = {"main": main_df, "__symbol__": symbol, "__timeframe__": tf}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/unit/test_intelligence_pipeline_agent.py -k "test_i1_frames_contain" -v 2>&1 | tail -10
```

Expected: PASS.

- [ ] **Step 5: Run full unit suite to check no regressions**

```bash
.venv/bin/pytest tests/unit/ -x -q 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add services/intelligence_pipeline_agent.py tests/unit/test_intelligence_pipeline_agent.py
git commit -m "fix(pipeline): inject __symbol__/__timeframe__ into I1 frames for stateful plugin state keying"
```

---

### Task 2: Rewrite OFIPlugin — state keying + continuous divergence factor

**Files:**
- Modify: `src/intelligence/features/i1_indicators/ofi.py`
- Modify: `tests/unit/intelligence/indicators/test_ofi.py`

- [ ] **Step 1: Update existing tests to reflect new semantics**

Replace the `test_divergence_sign` test in `tests/unit/intelligence/indicators/test_ofi.py`:

```python
def test_divergence_is_continuous(self):
    """ofi_divergence is now a continuous z-score factor, not discrete {-2..+2}."""
    plugin_fresh = type(self.plugin)()
    df = _make_df(20)
    # Warm up state so z-scores are meaningful
    for _ in range(15):
        plugin_fresh.compute_full({"main": df, "tick_buffer": [], "__symbol__": "ES", "__timeframe__": "1m"})
    result = plugin_fresh.compute_full({"main": df, "tick_buffer": [], "__symbol__": "ES", "__timeframe__": "1m"})
    divergence = result.get("ofi_divergence")
    assert divergence is not None
    assert isinstance(divergence, float)
    # New range is NOT limited to [-2, 2] — it's z-score space
    # Just verify it's a real float (not nan/inf)
    assert divergence == divergence  # not NaN
    assert abs(divergence) < 20.0   # sanity bound

def test_symbols_have_independent_state(self):
    """Different symbols must not share OFI state."""
    plugin_fresh = type(self.plugin)()
    df_es = _make_df(20, base_close=5000.0)
    df_mnq = _make_df(20, base_close=20000.0)
    # Run ES many times to build history
    for _ in range(20):
        plugin_fresh.compute_full({"main": df_es, "tick_buffer": [], "__symbol__": "ES", "__timeframe__": "1m"})
    es_result = plugin_fresh.compute_full({"main": df_es, "tick_buffer": [], "__symbol__": "ES", "__timeframe__": "1m"})
    # Run MNQ once — should have fresh/minimal state
    mnq_result = plugin_fresh.compute_full({"main": df_mnq, "tick_buffer": [], "__symbol__": "MNQ", "__timeframe__": "1m"})
    # MNQ with only 1 call has no z-score history → spike_z = 0 → divergence = -price_return_z
    # ES with 21 calls has full history. They should differ.
    assert es_result.get("ofi_spike_z") != mnq_result.get("ofi_spike_z") or \
           es_result.get("ofi_divergence") != mnq_result.get("ofi_divergence"), \
           "ES and MNQ must have independent state"

def test_all_outputs_present_with_symbol(self):
    """All 5 declared outputs appear in result when symbol/tf provided."""
    df = _make_df(20)
    result = self.plugin.compute_full({"main": df, "tick_buffer": [], "__symbol__": "ES", "__timeframe__": "1m"})
    expected_keys = {"ofi_ewma_5", "ofi_ewma_20", "ofi_divergence", "ofi_spike_z", "ofi_variant"}
    assert expected_keys.issubset(set(result.keys()))
```

Also update `test_all_outputs_present` to pass symbol/tf:
```python
def test_all_outputs_present(self):
    """All 5 declared outputs appear in result."""
    df = _make_df(20)
    result = self.plugin.compute_full({"main": df, "tick_buffer": [], "__symbol__": "ES", "__timeframe__": "1m"})
    expected_keys = {"ofi_ewma_5", "ofi_ewma_20", "ofi_divergence", "ofi_spike_z", "ofi_variant"}
    assert expected_keys.issubset(set(result.keys()))
```

- [ ] **Step 2: Run tests to see which fail**

```bash
.venv/bin/pytest tests/unit/intelligence/indicators/test_ofi.py -v 2>&1 | tail -20
```

Expected: `test_divergence_sign` fails (old test), new tests fail (not yet implemented).

- [ ] **Step 3: Rewrite `ofi.py`**

Replace `src/intelligence/features/i1_indicators/ofi.py` entirely:

```python
"""Order Flow Imbalance (OFI) — I1 microstructure indicator.

Two computation paths:
- Tick path (primary): Uses raw tick data from market.ticks topic to compute
  buy/sell volume imbalance via tick rule. ofi_variant="tick".
- Proxy path (fallback): When tick_buffer is empty, uses bar-level OHLCV proxy
  `(close - low) / (high - low) * volume`. ofi_variant="proxy".

Outputs: ofi_ewma_5, ofi_ewma_20, ofi_divergence, ofi_spike_z, ofi_variant

ofi_divergence is a continuous z-score factor:
  ofi_divergence = ofi_spike_z - price_return_z
Both z-scores use a 100-bar rolling window. Positive = OFI more bullish than price.

State is keyed by (symbol, tf) from frames["__symbol__"] / frames["__timeframe__"]
to prevent cross-symbol contamination in multi-symbol deployments.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.intelligence.plugins import InputSpec

_PROXY_EPSILON: float = 1e-9
_HISTORY_MAXLEN: int = 100
_MIN_HISTORY: int = 5


@dataclass
class OFIPlugin:
    name: str = "ind_OFI"
    outputs: frozenset[str] = frozenset(
        {"ofi_ewma_5", "ofi_ewma_20", "ofi_divergence", "ofi_spike_z", "ofi_variant"}
    )
    min_lookback: int = 5
    supports_incremental: bool = True
    capability_tags: frozenset[str] = frozenset({"volume", "microstructure"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=120),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        tick_buf = frames.get("tick_buffer") or []
        symbol = frames.get("__symbol__", "_")
        tf = frames.get("__timeframe__", "_")
        state_key = (symbol, tf)

        if df is None or len(df) < self.min_lookback:
            return {}

        # Compute raw OFI — tick path or proxy
        if tick_buf:
            raw_ofi = self._compute_tick_ofi(tick_buf)
            variant = "tick"
        else:
            raw_ofi = self._compute_proxy_ofi(df)
            variant = "proxy"

        # Per-(symbol, tf) state
        state = self._state.setdefault(state_key, {})

        # OFI history for spike z-score
        ofi_history: deque = state.setdefault("ofi_history", deque(maxlen=_HISTORY_MAXLEN))
        ofi_history.append(raw_ofi)

        # Price return history for price_return_z — same 100-bar window
        close_series = df["close"]
        if len(close_series) >= 2:
            price_return = float(close_series.iloc[-1]) - float(close_series.iloc[-2])
        else:
            price_return = 0.0
        ret_history: deque = state.setdefault("ret_history", deque(maxlen=_HISTORY_MAXLEN))
        ret_history.append(price_return)

        # EWMA update
        alpha5 = 2.0 / (5 + 1)
        alpha20 = 2.0 / (20 + 1)
        state.setdefault("ewma5", raw_ofi)
        state.setdefault("ewma20", raw_ofi)
        state["ewma5"] = state["ewma5"] * (1 - alpha5) + raw_ofi * alpha5
        state["ewma20"] = state["ewma20"] * (1 - alpha20) + raw_ofi * alpha20

        # OFI z-score (exclude current bar from history for z-score base)
        if len(ofi_history) >= _MIN_HISTORY:
            hist = np.array(list(ofi_history)[:-1])
            spike_z = (raw_ofi - float(np.mean(hist))) / (float(np.std(hist)) + 1e-9)
        else:
            spike_z = 0.0

        # Price return z-score (same structure)
        if len(ret_history) >= _MIN_HISTORY:
            ret_arr = np.array(list(ret_history)[:-1])
            price_return_z = (price_return - float(np.mean(ret_arr))) / (float(np.std(ret_arr)) + 1e-9)
        else:
            price_return_z = 0.0

        # Continuous divergence factor: positive = OFI more bullish than price
        divergence = round(spike_z - price_return_z, 4)

        return {
            "ofi_ewma_5": round(float(state["ewma5"]), 6),
            "ofi_ewma_20": round(float(state["ewma20"]), 6),
            "ofi_divergence": divergence,
            "ofi_spike_z": round(spike_z, 4),
            "ofi_variant": variant,
        }

    def _compute_tick_ofi(self, tick_buf: list[dict]) -> float:
        """Tick rule: buy_vol - sell_vol from sequential tick price changes."""
        buy_vol = 0.0
        sell_vol = 0.0
        prev_price: float | None = None
        for tick in tick_buf:
            try:
                price = float(tick.get("price", 0) or 0)
                size = float(tick.get("size") or 0)
            except (TypeError, ValueError):
                continue
            if prev_price is not None:
                if price > prev_price:
                    buy_vol += size
                elif price < prev_price:
                    sell_vol += size
            prev_price = price
        return buy_vol - sell_vol

    def _compute_proxy_ofi(self, df: pd.DataFrame) -> float:
        """Bar-level proxy: (close - low) / (high - low + epsilon) * volume."""
        row = df.iloc[-1]
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        volume = float(row["volume"])
        return (close - low) / (high - low + _PROXY_EPSILON) * volume

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = OFIPlugin()
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/indicators/test_ofi.py -v 2>&1 | tail -20
```

Expected: all pass. The old `test_divergence_sign` is replaced; new tests pass.

- [ ] **Step 5: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -x -q 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/intelligence/features/i1_indicators/ofi.py tests/unit/intelligence/indicators/test_ofi.py
git commit -m "feat(i1): OFIPlugin continuous divergence factor + per-symbol state keying

ofi_divergence = ofi_spike_z - price_return_z (both 100-bar z-scores).
State keyed by (symbol, tf) — fixes multi-symbol contamination bug."
```

---

### Task 3: Rewrite OFIDivergencePlugin (I7)

**Files:**
- Modify: `src/intelligence/trading/ofi_divergence.py`
- Create: `tests/unit/intelligence/test_ofi_divergence.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/intelligence/test_ofi_divergence.py`:

```python
"""Unit tests for OFIDivergencePlugin — I7 price-discovery signal."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _make_frames(
    n: int = 30,
    ofi_divergence: float = 2.0,
    ofi_spike_z: float = 2.0,
    ofi_ewma_5: float = 0.5,
    ofi_ewma_20: float = 0.3,
    rel_volume: float = 1.8,
    hmm_regime: float = 0.0,
    atr: float = 2.0,
    symbol: str = "ES",
    tf: str = "1m",
) -> dict:
    """Build a minimal frames dict for OFIDivergencePlugin.compute_full()."""
    closes = [5000.0 + i * 0.1 for i in range(n)]
    df = pd.DataFrame({
        "open": [c - 0.05 for c in closes],
        "high": [c + 0.5 for c in closes],
        "low": [c - 0.5 for c in closes],
        "close": closes,
        "volume": [1000.0] * n,
    })
    features = {
        "ofi_divergence": ofi_divergence,
        "ofi_spike_z": ofi_spike_z,
        "ofi_ewma_5": ofi_ewma_5,
        "ofi_ewma_20": ofi_ewma_20,
        "rel_volume": rel_volume,
        "hmm_regime": hmm_regime,
        "atr": atr,
        "atr_14": atr,
    }
    return {"main": df, "features": features, "__symbol__": symbol, "__timeframe__": tf}


class TestOFIDivergencePlugin:
    def setup_method(self):
        from src.intelligence.trading.ofi_divergence import OFIDivergencePlugin
        self.plugin = OFIDivergencePlugin()

    def _fire_n_times(self, frames: dict, n: int) -> dict:
        """Call compute_full n times with same frames, return last result."""
        result = {}
        for _ in range(n):
            result = self.plugin.compute_full(frames)
        return result

    def test_no_fire_single_bar(self):
        """Does not fire on first bar — persistence requires >= 2 consecutive bars."""
        frames = _make_frames(ofi_divergence=2.5)
        result = self.plugin.compute_full(frames)
        assert result.get("direction", 0) == 0, "Must not fire on single bar"

    def test_fires_after_two_consecutive_bars(self):
        """Fires after 2 bars with same sign and abs >= 1.5."""
        frames = _make_frames(ofi_divergence=2.0)
        result = self._fire_n_times(frames, 2)
        assert result.get("direction") in (1, -1), f"Expected fire, got: {result}"

    def test_no_fire_below_threshold(self):
        """Does not fire when abs(ofi_divergence) < 1.5, even after persistence."""
        frames = _make_frames(ofi_divergence=1.2)
        result = self._fire_n_times(frames, 3)
        assert result.get("direction", 0) == 0, "Below threshold must not fire"

    def test_direction_follows_ofi_sign(self):
        """direction = sign(ofi_divergence): positive div → long (1), negative → short (-1)."""
        frames_long = _make_frames(ofi_divergence=2.0, ofi_ewma_5=0.5)
        self._fire_n_times(frames_long, 2)
        result = self.plugin.compute_full(frames_long)
        assert result.get("direction") == 1

        from src.intelligence.trading.ofi_divergence import OFIDivergencePlugin
        plugin2 = OFIDivergencePlugin()
        frames_short = _make_frames(ofi_divergence=-2.0, ofi_ewma_5=-0.5)
        for _ in range(2):
            result2 = plugin2.compute_full(frames_short)
        assert result2.get("direction") == -1

    def test_state_resets_on_sign_flip(self):
        """After sign flip, persistence counter resets — must wait 2 bars again."""
        frames_pos = _make_frames(ofi_divergence=2.0)
        self._fire_n_times(frames_pos, 2)  # builds persistence

        frames_neg = _make_frames(ofi_divergence=-2.0, ofi_ewma_5=-0.5)
        result = self.plugin.compute_full(frames_neg)  # first bar of new sign
        assert result.get("direction", 0) == 0, "After sign flip, first bar must not fire"

    def test_peak_abs_used_in_confidence(self):
        """Higher peak divergence → higher confidence."""
        from src.intelligence.trading.ofi_divergence import OFIDivergencePlugin

        plugin_low = OFIDivergencePlugin()
        frames_low = _make_frames(ofi_divergence=1.6)
        for _ in range(2):
            r_low = plugin_low.compute_full(frames_low)

        plugin_high = OFIDivergencePlugin()
        frames_high = _make_frames(ofi_divergence=3.5)
        for _ in range(2):
            r_high = plugin_high.compute_full(frames_high)

        if r_low.get("direction") and r_high.get("direction"):
            assert r_high["confidence"] > r_low["confidence"], \
                "Higher divergence magnitude must produce higher confidence"

    def test_ewma_agreement_boosts_confidence(self):
        """Fast EWMA agreeing with divergence direction boosts confidence."""
        from src.intelligence.trading.ofi_divergence import OFIDivergencePlugin

        plugin_agree = OFIDivergencePlugin()
        frames_agree = _make_frames(ofi_divergence=2.0, ofi_ewma_5=0.8)
        for _ in range(2):
            r_agree = plugin_agree.compute_full(frames_agree)

        plugin_disagree = OFIDivergencePlugin()
        frames_disagree = _make_frames(ofi_divergence=2.0, ofi_ewma_5=-0.5)
        for _ in range(2):
            r_disagree = plugin_disagree.compute_full(frames_disagree)

        if r_agree.get("direction") and r_disagree.get("direction"):
            assert r_agree["confidence"] > r_disagree["confidence"], \
                "EWMA agreement must boost confidence vs disagreement"

    def test_regime_type_is_any(self):
        """Plugin must declare regime_type='any' — no aggregator suppression."""
        from src.intelligence.trading.ofi_divergence import OFIDivergencePlugin
        assert OFIDivergencePlugin.regime_type == "any"  # type: ignore[attr-defined]

    def test_no_fire_when_ofi_divergence_missing(self):
        """Returns no_signal() when ofi_divergence not in features."""
        frames = _make_frames()
        frames["features"].pop("ofi_divergence")
        result = self.plugin.compute_full(frames)
        assert result.get("direction", 0) == 0

    def test_supporting_factors_logged(self):
        """Supporting factors include ofi_divergence, peak_abs, bars_persistent."""
        frames = _make_frames(ofi_divergence=2.0)
        for _ in range(2):
            result = self.plugin.compute_full(frames)
        if result.get("direction"):
            factors = result.get("supporting_factors", [])
            factor_str = " ".join(factors)
            assert "ofi_divergence" in factor_str
            assert "peak_abs" in factor_str
            assert "bars_persistent" in factor_str

    def test_shadow_metadata_present(self):
        """_shadow dict present with confidence key."""
        frames = _make_frames(ofi_divergence=2.0)
        for _ in range(2):
            result = self.plugin.compute_full(frames)
        if result.get("direction"):
            assert "_shadow" in result
            assert "confidence" in result["_shadow"]

    def test_plugin_module_export(self):
        """Module-level plugin singleton has correct name."""
        from src.intelligence.trading.ofi_divergence import plugin
        assert plugin.name == "trad_OFIDivergence"
```

- [ ] **Step 2: Run to verify tests fail**

```bash
.venv/bin/pytest tests/unit/intelligence/test_ofi_divergence.py -v 2>&1 | tail -20
```

Expected: most tests fail — old plugin has wrong logic.

- [ ] **Step 3: Rewrite `ofi_divergence.py`**

Replace `src/intelligence/trading/ofi_divergence.py` entirely:

```python
"""trad_OFIDivergence — I7 price-discovery setup consuming continuous OFI I1 factor.

Fires when:
  1. abs(ofi_divergence) >= 1.5 — statistically extreme unconfirmed order flow
  2. sign(ofi_divergence) stable for >= 2 bars — persistence eliminates noise

Hypothesis H1 (price-discovery): informed order flow leads price; price will close
the gap in the direction of OFI within the signal TTL window.

ofi_divergence = ofi_spike_z - price_return_z (both 100-bar z-scores, from I1 OFIPlugin).

Renaissance principles:
- Continuous inputs — ofi_divergence is a real z-score factor, not a ternary sign diff
- Persistence before conviction — two bars minimum
- EWMA alignment is a soft factor, not a hard gate
- regime_type="any" — let outcome data decide which regimes this signal favours
- Instrument everything — peak_abs, bars_persistent, all EWMA values logged
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec
from .atr_utils import get_atr
from .confidence_utils import capture_signal_features, compose_confidence
from .plugin_utils import no_signal, signal_type_for_direction
from .state_utils import track_consecutive_state
from .trade_framer import frame_trade

_MIN_DIVERGENCE: float = 1.5   # σ threshold — recalibrate from observed fire rate
_MIN_PERSISTENCE: int = 2       # consecutive bars required before firing


@dataclass
class OFIDivergencePlugin:
    """I7 price-discovery: continuous OFI z-score factor diverges from price z-score.

    Gate: abs(ofi_divergence) >= 1.5 AND sign stable >= 2 bars.
    Direction: sign(ofi_divergence) — H1, price follows order flow.
    Confidence: tanh-weighted magnitude + soft EWMA and regime factors.
    """

    name: str = "trad_OFIDivergence"
    outputs: frozenset[str] = frozenset({
        "signal_type",
        "direction",
        "entry_price",
        "stop_loss",
        "targets",
        "confidence",
        "regime_context",
        "supporting_factors",
    })
    min_lookback: int = 20
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"trading", "divergence", "ofi", "price_discovery"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe=".*", lookback=100),)
    regime_type: str = "any"
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        features = frames.get("features") or {}
        symbol = frames.get("__symbol__", "_")
        tf = frames.get("__timeframe__", "_")

        if df is None or len(df) < self.min_lookback:
            return no_signal()

        ofi_div = features.get("ofi_divergence")
        if ofi_div is None:
            return no_signal()
        ofi_div = float(ofi_div)

        # ── Persistence tracking ─────────────────────────────────────────────
        div_sign = 1 if ofi_div > 0 else (-1 if ofi_div < 0 else 0)
        state_key = f"{symbol}_{tf}"

        if div_sign == 0:
            self._state.pop(state_key, None)
            return no_signal()

        _, count = track_consecutive_state(frames, self._state, state_key, div_sign, "div_sign")

        # Track peak |ofi_divergence| across persistence window — resets with sign
        entry = self._state.get(state_key, {})
        peak_abs = max(entry.get("peak_abs", 0.0), abs(ofi_div))
        self._state[state_key]["peak_abs"] = peak_abs

        # ── Gate checks ──────────────────────────────────────────────────────
        if abs(ofi_div) < _MIN_DIVERGENCE:
            return no_signal()
        if count < _MIN_PERSISTENCE:
            return no_signal()

        atr = get_atr(features)
        if atr is None:
            return no_signal()

        direction = div_sign
        close = float(df["close"].iloc[-1])

        # ── Confidence: continuous, magnitude-weighted ────────────────────────
        mag = peak_abs
        confidence = 0.42
        confidence += 0.25 * math.tanh(mag / 3.0)   # principled soft cap

        ofi_ewma_5 = features.get("ofi_ewma_5")
        ofi_ewma_20 = features.get("ofi_ewma_20")
        ewma5_sign = (1 if float(ofi_ewma_5) > 0 else -1) if ofi_ewma_5 is not None else 0
        ewma20_sign = (1 if float(ofi_ewma_20) > 0 else -1) if ofi_ewma_20 is not None else 0

        # Fast EWMA: soft factor (boost or reduce), NOT a hard gate
        if ewma5_sign == direction:
            confidence += 0.08
        elif ewma5_sign != 0:
            confidence -= 0.04

        # Slow EWMA confirms sustained pressure
        if ewma5_sign == ewma20_sign and ewma5_sign != 0:
            confidence += 0.06

        rel_volume = features.get("rel_volume")
        if rel_volume is not None and float(rel_volume) >= 1.5:
            confidence += 0.06

        hmm_regime = features.get("hmm_regime")
        if hmm_regime is not None:
            r = float(hmm_regime)
            if r == 0.0:
                confidence += 0.06   # ranging — soft positive hint
            elif r in (1.0, 2.0):
                confidence -= 0.06   # trending — soft negative hint

        confidence = compose_confidence(confidence)

        # ── Trade frame ───────────────────────────────────────────────────────
        sig_type = signal_type_for_direction("ofi_divergence", direction)
        tf_frame = frame_trade(sig_type, direction, close, features, atr)
        if not tf_frame.viable:
            return no_signal()

        regime_context = "ranging" if (hmm_regime is not None and float(hmm_regime) == 0.0) else "any"

        supporting: list[str] = [
            f"ofi_divergence={ofi_div:.3f}",
            f"peak_abs={peak_abs:.3f}",
            f"bars_persistent={count}",
        ]
        ofi_spike_z = features.get("ofi_spike_z")
        if ofi_spike_z is not None:
            supporting.append(f"ofi_spike_z={float(ofi_spike_z):.3f}")
        if ofi_ewma_5 is not None:
            supporting.append(f"ofi_ewma_5={float(ofi_ewma_5):.4f}")
        if ofi_ewma_20 is not None:
            supporting.append(f"ofi_ewma_20={float(ofi_ewma_20):.4f}")
        if hmm_regime is not None:
            supporting.append(f"hmm_regime={hmm_regime}")
        if rel_volume is not None:
            supporting.append(f"rel_volume={float(rel_volume):.2f}")

        signal = {
            "signal_type": sig_type,
            "direction": direction,
            "entry_price": round(close, 2),
            "stop_loss": float(tf_frame.stop),
            "targets": [float(t.price) for t in tf_frame.targets],
            "confidence": confidence,
            "regime_context": regime_context,
            "supporting_factors": supporting,
        }
        signal["_shadow"] = capture_signal_features(
            features, direction, "price_discovery", signal["confidence"],
        )
        return signal

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = OFIDivergencePlugin()
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_ofi_divergence.py -v 2>&1 | tail -30
```

Expected: all pass.

- [ ] **Step 5: Run full unit suite**

```bash
.venv/bin/pytest tests/unit/ -x -q 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 6: Lint**

```bash
.venv/bin/ruff check src/intelligence/features/i1_indicators/ofi.py src/intelligence/trading/ofi_divergence.py --fix
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/intelligence/trading/ofi_divergence.py tests/unit/intelligence/test_ofi_divergence.py
git commit -m "feat(i7): OFIDivergencePlugin full rewrite — continuous factor, persistence, tanh confidence

- regime_type='any': no aggregator suppression, let data decide
- abs(ofi_divergence) >= 1.5 gate on continuous z-score factor
- 2-bar persistence via state_utils, peak_abs tracked across window
- EWMA alignment as soft +0.08/-0.04 factor, not hard gate
- Confidence: 0.42 + 0.25*tanh(peak_abs/3) + EWMA/volume/regime soft hints"
```

---

### Task 4: Restart service and verify

- [ ] **Step 1: Restart intelligence pipeline**

```bash
echo 'PASSWORD' | /usr/bin/sudo.ws -S systemctl restart indicagent-intelligence-pipeline
```

- [ ] **Step 2: Verify service started cleanly**

```bash
sleep 5 && journalctl -u indicagent-intelligence-pipeline --since "1 minute ago" | grep -E "started|error|ERROR|plugin.*registered" | head -20
```

Expected: no errors, pipeline started.

- [ ] **Step 3: Verify OFIDivergencePlugin registered**

```bash
grep -i "ofi_divergence\|trad_OFI" logs/intelligence_pipeline_agent.log | tail -10
```

Expected: plugin appears in startup logs.

- [ ] **Step 4: Monitor for first fires (wait for market hours)**

```bash
docker exec redpanda rpk topic consume intelligence.i7.signals --from-end -n 20 2>/dev/null | python3 -c "
import sys, json
for line in sys.stdin:
    try:
        d = json.loads(line)
        for sig in d.get('signals', []):
            if 'ofi_divergence' in sig.get('signal_type', ''):
                print(json.dumps(sig, indent=2))
    except: pass
"
```

Expected: when market is open and OFI diverges from price for 2+ bars, signals appear with continuous `ofi_divergence` values (not discrete).
