# CIS Universal Ensemble Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Route all unused I1 and I2 outputs into CIS buckets with correlation penalty, event decay, and full per-constituent attribution persisted to signal_ledger.

**Architecture:** Two new I2 bridge composites translate price-relative I1 indicators into directional signals. `_build_features_from_event` is fixed to include I2 fields. CISScorer is extended with intra-bucket weights, a `ContribTracker`, correlation penalty, and event decay. `CISResult` gains `constituent_contributions`. `signal_ledger` gains `cis_attribution JSONB`. I8 receives the top-contributor summary.

**Tech Stack:** Python dataclasses, asyncpg JSONB, TimescaleDB migration, structlog, pytest, ruff

**Design doc:** `docs/plans/2026-03-04-cis-universal-ensemble-design.md`

---

## Task 1: DB Migration 016 — add cis_attribution column

**Files:**
- Create: `production/migrations/016_cis_attribution.sql`

**Step 1: Write the migration**

```sql
-- 016_cis_attribution.sql
-- Add per-constituent CIS attribution to signal_ledger for alpha discovery.

ALTER TABLE signal_ledger
    ADD COLUMN IF NOT EXISTS cis_attribution JSONB;

COMMENT ON COLUMN signal_ledger.cis_attribution IS
  'Per-constituent CIS contributions at signal fire time. Structure: {bucket: {signal_name: contribution_to_final_cis_score}}. Immutable after write.';
```

**Step 2: Apply migration**

```bash
echo '***REDACTED-SUDO-PASSWORD***' | sudo -S -u postgres psql -d indicagent -f production/migrations/016_cis_attribution.sql
```
Expected: `ALTER TABLE`

**Step 3: Verify column exists**

```bash
echo '***REDACTED-SUDO-PASSWORD***' | sudo -S -u postgres psql -d indicagent -c "\d signal_ledger" | grep cis_attr
```
Expected: `cis_attribution | jsonb`

**Step 4: Commit**

```bash
git add production/migrations/016_cis_attribution.sql
git commit -m "feat(db): add cis_attribution JSONB column to signal_ledger"
```

---

## Task 2: LedgerEntry — add cis_attribution field

**Files:**
- Modify: `src/intelligence/trading/signal_ledger.py`

**Step 1: Write failing test**

```python
# tests/unit/intelligence/test_signal_ledger.py
# Add to existing test file

def test_ledger_entry_has_cis_attribution_field():
    entry = LedgerEntry(
        signal_id="test-id",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        symbol="ES", timeframe="1m", setup_plugin="test", signal_type="test",
        direction=1, entry_price=5000.0, stop_loss=4990.0, targets=[5010.0],
        confidence=0.8, confluence_score=0.7, regime_context="trending",
        supporting_factors=[], was_selected=True,
        num_signals_bar=1, num_agreeing=1, num_conflicting=0,
        resolution_method="solo", composite_rank=1,
        cis_attribution={"momentum": {"rsi_14": 0.038, "williams_r_14": 0.011}},
    )
    assert entry.cis_attribution == {"momentum": {"rsi_14": 0.038, "williams_r_14": 0.011}}


def test_ledger_entry_to_insert_params_includes_attribution():
    entry = LedgerEntry(
        signal_id="test-id",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        symbol="ES", timeframe="1m", setup_plugin="test", signal_type="test",
        direction=1, entry_price=5000.0, stop_loss=4990.0, targets=[],
        confidence=0.8, confluence_score=0.7, regime_context="",
        supporting_factors=[], was_selected=True,
        num_signals_bar=1, num_agreeing=1, num_conflicting=0,
        resolution_method="solo", composite_rank=1,
        cis_attribution={"trend": {"psar_direction": 0.05}},
    )
    params = entry.to_insert_params()
    assert len(params) == 37   # was 36, now 37
    assert '"psar_direction"' in params[36]  # last param is JSON string
```

**Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/unit/intelligence/test_signal_ledger.py::test_ledger_entry_has_cis_attribution_field -v
```
Expected: FAIL — `LedgerEntry.__init__() got an unexpected keyword argument 'cis_attribution'`

**Step 3: Add field to LedgerEntry**

In `src/intelligence/trading/signal_ledger.py`, add after line `zone_valid_at_signal: bool | None = None`:

```python
    # Attribution — per-constituent CIS contributions at signal fire time
    cis_attribution: dict | None = None
```

In `to_insert_params()`, change the return tuple to append one new element at the end:

```python
            self.zone_valid_at_signal, # $36
            json.dumps(self.cis_attribution) if self.cis_attribution is not None else None,  # $37
```

Update `_INSERT_SQL` — add to column list:
```sql
INSERT INTO signal_ledger (
    ...
    entry_zone_low, entry_zone_high, zone_valid_at_signal,
    cis_attribution
) VALUES (
    ...
    $34, $35, $36,
    $37::jsonb
)
```

**Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_signal_ledger.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add src/intelligence/trading/signal_ledger.py tests/unit/intelligence/test_signal_ledger.py
git commit -m "feat: add cis_attribution field to LedgerEntry + INSERT SQL"
```

---

## Task 3: Extend CISResult with constituent_contributions

**Files:**
- Modify: `src/intelligence/trading/cis_scorer.py`

**Step 1: Write failing test**

```python
# tests/unit/intelligence/test_cis_scorer.py
# Add to existing test file

def test_cis_result_has_constituent_contributions():
    scorer = CISScorer()
    features = {"rsi_14": 65.0, "trend_regime": 0.8}
    result = scorer.score(features, {})
    assert hasattr(result, "constituent_contributions")
    assert isinstance(result.constituent_contributions, dict)
    assert "momentum" in result.constituent_contributions
    assert "trend" in result.constituent_contributions
    # Each bucket entry is a dict of signal → contribution float
    assert isinstance(result.constituent_contributions["momentum"], dict)


def test_constituent_contributions_values_are_floats():
    scorer = CISScorer()
    features = {"rsi_14": 30.0, "macd_histogram_12_26_9": -0.5}
    result = scorer.score(features, {})
    for bucket, contribs in result.constituent_contributions.items():
        for signal, val in contribs.items():
            assert isinstance(val, float), f"{bucket}.{signal} is not float"
```

**Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/unit/intelligence/test_cis_scorer.py::test_cis_result_has_constituent_contributions -v
```
Expected: FAIL — `CISResult has no attribute 'constituent_contributions'`

**Step 3: Add field to CISResult and stub**

In `src/intelligence/trading/cis_scorer.py`:

```python
@dataclass
class CISResult:
    """Output of a CISScorer.score() call."""

    cis_score: float
    direction: int
    bucket_scores: dict[str, float]
    weights_version: int
    buckets_agreeing: int
    # NEW — per-constituent contributions to final CIS score
    # {bucket: {signal_name: actual_contribution_to_cis_score}}
    constituent_contributions: dict[str, dict[str, float]] = field(default_factory=dict)
```

In `score()`, update the return to include a placeholder (full wiring comes in Task 14):

```python
    return CISResult(
        cis_score=round(cis_score, 4),
        direction=direction,
        bucket_scores={k: round(v, 4) for k, v in bucket_scores.items()},
        weights_version=self._weights_version,
        buckets_agreeing=agreeing,
        constituent_contributions={b: {} for b in BUCKET_NAMES},  # populated in Task 14
    )
```

**Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_cis_scorer.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add src/intelligence/trading/cis_scorer.py tests/unit/intelligence/test_cis_scorer.py
git commit -m "feat: add constituent_contributions field to CISResult"
```

---

## Task 4: Fix _build_features_from_event — wire I2 into features

**Files:**
- Modify: `services/signal_generator_service.py`

**Context:** `_build_features_from_event` currently skips `event.i2`. This means CIS never sees I2 outputs. Fix it.

**Step 1: Write failing test**

```python
# tests/unit/test_signal_generator.py  (or closest existing file)
# Check that _build_features_from_event includes i2 fields

from services.signal_generator_service import _build_features_from_event
from src.intelligence.schemas import IntelligenceEvent, I2Events, I1Indicators, I3Structure, I4Context, I5Patterns, SMCContext, I6Confluence, OHLCVBar
from datetime import datetime, timezone

def _minimal_event(**i2_kwargs) -> IntelligenceEvent:
    """Build a minimal IntelligenceEvent with given I2 fields."""
    return IntelligenceEvent(
        ts=datetime(2026, 1, 1, tzinfo=timezone.utc),
        symbol="ES", tf="1m",
        bar=OHLCVBar(o=5000, h=5010, l=4990, c=5005, v=1000),
        i1=I1Indicators(),
        i2=I2Events(**i2_kwargs),
        i3=I3Structure(),
        i4=I4Context(),
        i5=I5Patterns(),
        smc=SMCContext(),
        i6=I6Confluence(),
    )


def test_build_features_includes_i2_stoch_cross():
    event = _minimal_event(stoch_cross_bullish=1.0, stoch_cross_bearish=0.0)
    features = _build_features_from_event(event)
    assert features.get("stoch_cross_bullish") == 1.0


def test_build_features_includes_i2_adx_events():
    event = _minimal_event(adx_trend_confirmed=1.0, di_spread=25.0)
    features = _build_features_from_event(event)
    assert features.get("adx_trend_confirmed") == 1.0
    assert features.get("di_spread") == 25.0


def test_build_features_includes_i2_vol_events():
    event = _minimal_event(vol_spike=1.0, bb_walking_upper=1.0)
    features = _build_features_from_event(event)
    assert features.get("vol_spike") == 1.0
    assert features.get("bb_walking_upper") == 1.0
```

**Step 2: Run to verify it fails**

```bash
.venv/bin/pytest tests/unit/test_signal_generator.py::test_build_features_includes_i2_stoch_cross -v
```
Expected: FAIL — `assert None == 1.0`

**Step 3: Fix _build_features_from_event**

In `services/signal_generator_service.py`, in `_build_features_from_event`, add after the I1 block:

```python
    # I2 — composite events (crossovers, threshold extremes, volume events)
    for k, v in event.i2.model_dump().items():
        if v is not None:
            f[k] = v

    # Close price — used by bridge composites stored in I2 (DonchianPosition etc.)
    f["close_price"] = event.bar.c
```

**Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_signal_generator.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add services/signal_generator_service.py tests/unit/test_signal_generator.py
git commit -m "fix: wire I2 event fields into features dict in _build_features_from_event"
```

---

## Task 5: DonchianPosition bridge composite

**Files:**
- Create: `src/intelligence/composites/donchian_position.py`
- Modify: `src/intelligence/schemas.py` (add `donchian_position_20` to I2Events)
- Modify: `src/intelligence/register_plugins.py`

**Step 1: Write failing test**

```python
# tests/unit/intelligence/composites/test_donchian_position.py
import pandas as pd
import pytest
from src.intelligence.composites.donchian_position import plugin


def _frames(close: float, d_high: float, d_mid: float, d_low: float) -> dict:
    df = pd.DataFrame({"close": [close - 1, close], "high": [close] * 2, "low": [close] * 2, "volume": [100] * 2})
    return {
        "main": df,
        "features": {"donchian_high_20": d_high, "donchian_mid_20": d_mid, "donchian_low_20": d_low},
    }


def test_price_at_top_of_channel_returns_positive():
    out = plugin.compute_full(_frames(close=5010.0, d_high=5010.0, d_mid=5000.0, d_low=4990.0))
    assert out["donchian_position_20"] == pytest.approx(1.0, abs=0.01)


def test_price_at_bottom_of_channel_returns_negative():
    out = plugin.compute_full(_frames(close=4990.0, d_high=5010.0, d_mid=5000.0, d_low=4990.0))
    assert out["donchian_position_20"] == pytest.approx(-1.0, abs=0.01)


def test_price_at_mid_returns_zero():
    out = plugin.compute_full(_frames(close=5000.0, d_high=5010.0, d_mid=5000.0, d_low=4990.0))
    assert out["donchian_position_20"] == pytest.approx(0.0, abs=0.01)


def test_missing_donchian_returns_zero():
    frames = {"main": pd.DataFrame({"close": [5000.0]}), "features": {}}
    out = plugin.compute_full(frames)
    assert out["donchian_position_20"] == 0.0
```

**Step 2: Run to verify it fails**

```bash
.venv/bin/pytest tests/unit/intelligence/composites/test_donchian_position.py -v
```
Expected: FAIL — ModuleNotFoundError

**Step 3: Implement DonchianPosition composite**

```python
# src/intelligence/composites/donchian_position.py
"""DonchianPosition — bridge composite for Donchian channel position.

Translates price position within the Donchian channel into a [-1, +1]
directional signal: +1 = price at top (bullish), -1 = at bottom (bearish).
Feeds into CIS regime bucket.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec, PatternPlugin


@dataclass
class DonchianPositionPlugin(PatternPlugin):
    name: str = "evt_DonchianPosition"
    outputs: frozenset[str] = field(default_factory=lambda: frozenset({"donchian_position_20"}))
    min_lookback: int = 2
    capability_tags: frozenset[str] = field(default_factory=lambda: frozenset({"structure", "channel"}))
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=25),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features", {})
        df = frames.get("main")

        d_high = features.get("donchian_high_20")
        d_mid = features.get("donchian_mid_20")
        d_low = features.get("donchian_low_20")

        if df is None or d_high is None or d_mid is None or d_low is None:
            return {"donchian_position_20": 0.0}

        half_range = (float(d_high) - float(d_low)) / 2.0
        if half_range == 0:
            return {"donchian_position_20": 0.0}

        close = float(df["close"].iloc[-1])
        position = (close - float(d_mid)) / half_range
        return {"donchian_position_20": max(-1.0, min(1.0, round(position, 4)))}


plugin = DonchianPositionPlugin()
```

Add `donchian_position_20: float | None = None` to `I2Events` in `src/intelligence/schemas.py`.

Register in `src/intelligence/register_plugins.py`:
```python
from .composites.donchian_position import plugin as donchian_pos_plugin
# in register_all_plugins(), after existing I2 registrations:
registry.register_pattern(donchian_pos_plugin)
# in TIER_I2 list:
donchian_pos_plugin.name,
```

**Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/composites/test_donchian_position.py -v
```
Expected: all PASS

**Step 5: Run full suite to check no regressions**

```bash
.venv/bin/pytest tests/unit/ -q
```
Expected: all previously passing tests still PASS

**Step 6: Commit**

```bash
git add src/intelligence/composites/donchian_position.py src/intelligence/schemas.py src/intelligence/register_plugins.py tests/unit/intelligence/composites/test_donchian_position.py
git commit -m "feat(I2): add DonchianPosition bridge composite → donchian_position_20"
```

---

## Task 6: OBVMomentum bridge composite

**Files:**
- Create: `src/intelligence/composites/obv_momentum.py`
- Modify: `src/intelligence/schemas.py` (add `obv_slope_sign` to I2Events)
- Modify: `src/intelligence/register_plugins.py`

**Step 1: Write failing test**

```python
# tests/unit/intelligence/composites/test_obv_momentum.py
import pandas as pd
import numpy as np
from src.intelligence.composites.obv_momentum import plugin


def _frames(closes: list[float], volumes: list[float]) -> dict:
    df = pd.DataFrame({
        "close": closes,
        "volume": volumes,
        "high": [c + 1 for c in closes],
        "low": [c - 1 for c in closes],
    })
    return {"main": df, "features": {}}


def test_rising_obv_returns_positive():
    # Rising price + high volume = rising OBV
    out = plugin.compute_full(_frames(
        closes=[100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0, 110.0],
        volumes=[1000] * 11,
    ))
    assert out["obv_slope_sign"] == 1


def test_falling_obv_returns_negative():
    # Falling price + high volume = falling OBV
    out = plugin.compute_full(_frames(
        closes=[110.0, 109.0, 108.0, 107.0, 106.0, 105.0, 104.0, 103.0, 102.0, 101.0, 100.0],
        volumes=[1000] * 11,
    ))
    assert out["obv_slope_sign"] == -1


def test_insufficient_bars_returns_zero():
    out = plugin.compute_full(_frames(closes=[100.0, 101.0], volumes=[100, 100]))
    assert out["obv_slope_sign"] == 0
```

**Step 2: Run to verify it fails**

```bash
.venv/bin/pytest tests/unit/intelligence/composites/test_obv_momentum.py -v
```
Expected: FAIL — ModuleNotFoundError

**Step 3: Implement OBVMomentum composite**

```python
# src/intelligence/composites/obv_momentum.py
"""OBVMomentum — bridge composite for On-Balance Volume direction.

Computes OBV from raw bars, runs linear regression over a rolling window,
and emits the slope sign as +1 (accumulation) / 0 (neutral) / -1 (distribution).
Feeds into CIS institutional bucket.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..plugins import InputSpec, PatternPlugin

_WINDOW = 10  # bars for slope regression


@dataclass
class OBVMomentumPlugin(PatternPlugin):
    name: str = "evt_OBVMomentum"
    outputs: frozenset[str] = field(default_factory=lambda: frozenset({"obv_slope_sign"}))
    min_lookback: int = _WINDOW + 2
    capability_tags: frozenset[str] = field(default_factory=lambda: frozenset({"volume", "momentum"}))
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", timeframe="1m", lookback=_WINDOW + 5),)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {"obv_slope_sign": 0}

        close = df["close"].to_numpy(dtype=float)
        volume = df["volume"].to_numpy(dtype=float)

        # Compute OBV
        obv = np.zeros(len(close))
        for i in range(1, len(close)):
            if close[i] > close[i - 1]:
                obv[i] = obv[i - 1] + volume[i]
            elif close[i] < close[i - 1]:
                obv[i] = obv[i - 1] - volume[i]
            else:
                obv[i] = obv[i - 1]

        # Linear regression slope over last _WINDOW bars
        window = obv[-_WINDOW:]
        x = np.arange(len(window), dtype=float)
        slope = float(np.polyfit(x, window, 1)[0])

        sign = 1 if slope > 0 else (-1 if slope < 0 else 0)
        return {"obv_slope_sign": sign}


plugin = OBVMomentumPlugin()
```

Add `obv_slope_sign: float | None = None` to `I2Events` in `src/intelligence/schemas.py`.

Register in `src/intelligence/register_plugins.py`:
```python
from .composites.obv_momentum import plugin as obv_momentum_plugin
# in register_all_plugins():
registry.register_pattern(obv_momentum_plugin)
# in TIER_I2 list:
obv_momentum_plugin.name,
```

**Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/composites/test_obv_momentum.py tests/unit/ -q
```
Expected: all PASS

**Step 7: Commit**

```bash
git add src/intelligence/composites/obv_momentum.py src/intelligence/schemas.py src/intelligence/register_plugins.py tests/unit/intelligence/composites/test_obv_momentum.py
git commit -m "feat(I2): add OBVMomentum bridge composite → obv_slope_sign"
```

---

## Task 7: Add MomentumAccel + bars_ago fields to I2Events schema

**Files:**
- Modify: `src/intelligence/schemas.py`

**Context:** MomentumAcceleration outputs (`rsi_accel`, `macd_accel`, `roc_accel`, `inflection_flag`) currently go to I2Events via `extra="allow"` but are not typed. Event decay needs `*_bars_ago` fields for stoch/MACD/vol events. Add all explicitly.

**Step 1: Write failing test**

```python
# tests/unit/intelligence/test_schemas.py (or add to existing schema tests)

def test_i2_events_has_momentum_accel_fields():
    from src.intelligence.schemas import I2Events
    e = I2Events(rsi_accel=0.5, macd_accel=-0.2, roc_accel=0.1, inflection_flag=0.0)
    assert e.rsi_accel == 0.5
    assert e.inflection_flag == 0.0


def test_i2_events_has_bars_ago_fields():
    from src.intelligence.schemas import I2Events
    e = I2Events(macd_cross_bars_ago=3.0, stoch_cross_bars_ago=5.0, vol_spike_bars_ago=2.0)
    assert e.stoch_cross_bars_ago == 5.0
```

**Step 2: Run to verify it fails**

```bash
.venv/bin/pytest tests/unit/intelligence/test_schemas.py -k "momentum_accel or bars_ago" -v
```
Expected: FAIL

**Step 3: Add fields to I2Events**

In `src/intelligence/schemas.py`, `class I2Events`, add:

```python
    # MomentumAcceleration outputs
    rsi_accel: float | None = None
    macd_accel: float | None = None
    roc_accel: float | None = None
    inflection_flag: float | None = None  # 1.0 when momentum inflecting

    # Event age tracking — bars since each event last fired (for decay)
    macd_cross_bars_ago: float | None = None   # already existed; kept here for clarity
    stoch_cross_bars_ago: float | None = None  # NEW
    vol_spike_bars_ago: float | None = None    # NEW
    adx_confirmed_bars_ago: float | None = None  # NEW
```

**Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_schemas.py -v
.venv/bin/pytest tests/unit/ -q
```
Expected: all PASS

**Step 5: Commit**

```bash
git add src/intelligence/schemas.py tests/unit/intelligence/test_schemas.py
git commit -m "feat: add MomentumAccel + bars_ago fields to I2Events schema"
```

---

## Task 8: Event decay framework in CISScorer

**Files:**
- Modify: `src/intelligence/trading/cis_scorer.py`

**Context:** Events (I2 composite outputs) become stale over time. Add `_decay(value, bars_ago, halflife)` utility and `_event_ages` internal state dict. CISScorer must be stateful to track bars_ago when `*_bars_ago` features are not present.

**Step 1: Write failing test**

```python
# tests/unit/intelligence/test_cis_scorer.py — add:

def test_decay_returns_full_value_at_zero_bars():
    scorer = CISScorer()
    assert scorer._decay(1.0, bars_ago=0, halflife=5) == pytest.approx(1.0, abs=0.001)


def test_decay_returns_half_at_halflife():
    scorer = CISScorer()
    result = scorer._decay(1.0, bars_ago=5, halflife=5)
    assert result == pytest.approx(0.5, abs=0.02)


def test_decay_returns_near_zero_at_2x_halflife():
    scorer = CISScorer()
    result = scorer._decay(1.0, bars_ago=10, halflife=5)
    assert result < 0.3


def test_stale_event_has_reduced_contribution():
    """A momentum event that fired 15 bars ago should contribute ~15% vs fresh."""
    scorer = CISScorer()
    # Fresh event
    features_fresh = {"stoch_cross_bullish": 1.0, "stoch_cross_bars_ago": 0.0, "rsi_14": 50.0}
    result_fresh = scorer.score(features_fresh, {})
    # Stale event (15 bars ago with halflife=5)
    features_stale = {"stoch_cross_bullish": 1.0, "stoch_cross_bars_ago": 15.0, "rsi_14": 50.0}
    result_stale = scorer.score(features_stale, {})
    # stale bucket score should be meaningfully lower than fresh
    fresh_mom = result_fresh.bucket_scores["momentum"]
    stale_mom = result_stale.bucket_scores["momentum"]
    assert stale_mom < fresh_mom * 0.5
```

**Step 2: Run to verify it fails**

```bash
.venv/bin/pytest tests/unit/intelligence/test_cis_scorer.py::test_decay_returns_full_value_at_zero_bars -v
```
Expected: FAIL — `CISScorer has no attribute '_decay'`

**Step 3: Add event decay to CISScorer**

In `src/intelligence/trading/cis_scorer.py`, add after imports:

```python
import math

# Event decay halflives (in bars) by category
_DECAY_HALFLIVES: dict[str, int] = {
    "momentum_event": 5,   # stoch cross, accel signals
    "trend_event": 10,     # MACD cross, BB walking
    "confirm_event": 20,   # ADX trend confirmed
    "inflection": 3,       # inflection_flag
}
```

In `CISScorer` class, add method:

```python
    @staticmethod
    def _decay(value: float, bars_ago: float, halflife: int) -> float:
        """Apply exponential decay: value * exp(-bars_ago * ln(2) / halflife)."""
        if bars_ago <= 0:
            return value
        return value * math.exp(-bars_ago * math.log(2) / halflife)
```

**Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_cis_scorer.py -v
```
Expected: decay unit tests PASS (stale_event test may not fully pass yet — it depends on bucket expansion in Task 10; that's OK, just verify the `_decay` method tests pass)

**Step 5: Commit**

```bash
git add src/intelligence/trading/cis_scorer.py tests/unit/intelligence/test_cis_scorer.py
git commit -m "feat: add event decay framework to CISScorer (_decay method)"
```

---

## Task 9: Correlation penalty in CISScorer

**Files:**
- Modify: `src/intelligence/trading/cis_scorer.py`

**Step 1: Write failing test**

```python
# tests/unit/intelligence/test_cis_scorer.py — add:

def test_correlation_penalty_reduces_overdrive():
    """5 perfectly correlated oscillators all maxing out should not hit bucket=1.0."""
    scorer = CISScorer()
    # All momentum oscillators maximally bullish
    features = {
        "rsi_14": 90.0,          # maps to +0.8
        "williams_r_14": -5.0,   # maps to ~+0.9 (near 0 = overbought → bearish for mean-rev)
        "mfi_14": 90.0,          # maps to +0.8
        "stoch_rsi_k_14": 0.95,  # maps to +0.9
        "macd_histogram_12_26_9": 2.0,  # positive
        "roc_14": 3.0,           # positive
        "momentum_bias": 0.9,
    }
    result = scorer.score(features, {})
    # Without penalty, 5 correlated oscillators could push momentum near 1.0
    # With penalty, effective_n=2.5 means it should stay below 0.85
    assert result.bucket_scores["momentum"] < 0.85


def test_uncorrelated_signals_not_penalized():
    """Signals in different correlation groups should add normally."""
    scorer = CISScorer()
    features = {
        "rsi_14": 75.0,           # oscillator group
        "trend_regime": 0.9,      # trend signal (different group)
        "kalman_slope": 0.5,      # trend signal
    }
    result = scorer.score(features, {})
    # Trend bucket can still score high from uncorrelated signals
    assert result.bucket_scores["trend"] > 0.3
```

**Step 2: Run to verify it fails**

```bash
.venv/bin/pytest tests/unit/intelligence/test_cis_scorer.py::test_correlation_penalty_reduces_overdrive -v
```
Expected: FAIL (test may pass or fail depending on current weights — confirm the assertion logic)

**Step 3: Add correlation groups and penalty to CISScorer**

In `src/intelligence/trading/cis_scorer.py`, add after `BOOTSTRAP_WEIGHTS`:

```python
# Correlation groups — members are treated as ~effective_n independent signals.
# Prevents correlated oscillators from collectively overdriving a bucket.
_CORR_GROUPS: list[dict] = [
    {
        "members": frozenset({
            "rsi_14", "williams_r_14", "mfi_14", "stoch_rsi_k_14",
            "stoch_cross_bullish", "stoch_cross_bearish",
            "stoch_oversold_reversal", "stoch_overbought_reversal",
        }),
        "effective_n": 2.5,
    },
    {
        "members": frozenset({
            "psar_direction", "aroon_osc_25", "di_spread",
            "adx_trend_confirmed",
        }),
        "effective_n": 2.0,
    },
]


def _apply_corr_penalty(raw_sum: float, firing_names: set[str]) -> float:
    """Scale down contribution from correlated signal groups.

    For each correlation group, if more members fire than effective_n,
    scale the group's combined contribution by (effective_n / actual_count).
    """
    penalty_factor = 1.0
    for group in _CORR_GROUPS:
        firing_in_group = group["members"] & firing_names
        count = len(firing_in_group)
        if count > group["effective_n"]:
            penalty_factor = min(penalty_factor, group["effective_n"] / count)
    return raw_sum * penalty_factor
```

The penalty is applied at the end of each bucket's computation by passing the set of signal names that contributed non-zero values.

**Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_cis_scorer.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add src/intelligence/trading/cis_scorer.py tests/unit/intelligence/test_cis_scorer.py
git commit -m "feat: add correlation penalty to CISScorer to prevent oscillator overdrive"
```

---

## Task 10: Expand momentum bucket

**Files:**
- Modify: `src/intelligence/trading/cis_scorer.py`

**New intra-bucket weights (sum = 1.0):**

Existing scaled down by ×0.75 to make room for 0.25 of new signals:
- `rsi_14`: 0.225 (was 0.30)
- `macd_histogram`: 0.1875 (was 0.25)
- `roc_14`: 0.15 (was 0.20)
- `momentum_bias`: 0.1125 (was 0.15)
- `DivergenceStack`: 0.075 (was 0.10)

New (bootstrap, conservative):
- `williams_r_14`: 0.04
- `mfi_14`: 0.04
- `stoch_rsi_k_14`: 0.03
- `cmf_20`: 0.03
- `rsi_accel`: 0.02 (decayed event, halflife=5)
- `macd_accel`: 0.02 (decayed event, halflife=5)
- `roc_accel`: 0.01 (decayed event, halflife=5)
- `stoch_cross_bullish / bearish`: 0.02 each (combined → 0.02 split by sign)
- `stoch_oversold_reversal`: 0.01
- `stoch_overbought_reversal`: 0.01

**Step 1: Write failing test**

```python
# tests/unit/intelligence/test_cis_scorer.py — add:

def test_williams_r_contributes_to_momentum_bucket():
    scorer = CISScorer()
    # Williams%R at -90 (oversold) = bullish signal
    features_with_wr = {"rsi_14": 50.0, "williams_r_14": -90.0}
    features_without_wr = {"rsi_14": 50.0}
    result_with = scorer.score(features_with_wr, {})
    result_without = scorer.score(features_without_wr, {})
    # Oversold WR should push momentum bullish
    assert result_with.bucket_scores["momentum"] > result_without.bucket_scores["momentum"]


def test_mfi_contributes_to_momentum_bucket():
    scorer = CISScorer()
    features_high = {"rsi_14": 50.0, "mfi_14": 80.0}  # bullish MFI
    features_low = {"rsi_14": 50.0, "mfi_14": 20.0}   # bearish MFI
    result_high = scorer.score(features_high, {})
    result_low = scorer.score(features_low, {})
    assert result_high.bucket_scores["momentum"] > result_low.bucket_scores["momentum"]


def test_stoch_rsi_contributes_to_momentum_bucket():
    scorer = CISScorer()
    features_bull = {"stoch_rsi_k_14": 0.9}
    features_bear = {"stoch_rsi_k_14": 0.1}
    r_bull = scorer.score(features_bull, {})
    r_bear = scorer.score(features_bear, {})
    assert r_bull.bucket_scores["momentum"] > r_bear.bucket_scores["momentum"]


def test_stoch_cross_event_contributes_with_decay():
    scorer = CISScorer()
    # Fresh stoch cross bullish
    features = {"stoch_cross_bullish": 1.0, "stoch_cross_bars_ago": 0.0}
    result = scorer.score(features, {})
    assert result.bucket_scores["momentum"] > 0.0  # some positive contribution
```

**Step 2: Run to verify it fails**

```bash
.venv/bin/pytest tests/unit/intelligence/test_cis_scorer.py::test_williams_r_contributes_to_momentum_bucket -v
```
Expected: FAIL

**Step 3: Rewrite _momentum method**

Replace `_momentum` in `src/intelligence/trading/cis_scorer.py`:

```python
    def _momentum(self, f: dict, po: dict) -> float:
        """Momentum bucket [-1, +1]."""
        rsi = self._fval(f, "rsi_14", default=50.0)
        rsi_dir = clamp((rsi - 50.0) / 50.0)

        macd = self._fval(f, "macd_histogram_12_26_9")
        macd_dir = 1.0 if macd > 0 else (-1.0 if macd < 0 else 0.0)

        roc = self._fval(f, "roc_14")
        roc_dir = 1.0 if roc > 0 else (-1.0 if roc < 0 else 0.0)

        d, c = self._plug(po, "trad_DivergenceStack")

        # New oscillators
        wr = self._fval(f, "williams_r_14", default=-50.0)
        wr_dir = clamp(-(wr + 50.0) / 50.0)  # -100=oversold=bullish, 0=overbought=bearish

        mfi = self._fval(f, "mfi_14", default=50.0)
        mfi_dir = clamp((mfi - 50.0) / 50.0)

        stoch_rsi_k = self._fval(f, "stoch_rsi_k_14", default=0.5)
        srsi_dir = clamp((stoch_rsi_k - 0.5) / 0.5)

        cmf = clamp(self._fval(f, "cmf_20"))

        # Decayed events
        stoch_bull = self._fval(f, "stoch_cross_bullish") * self._decay(
            1.0, self._fval(f, "stoch_cross_bars_ago"), _DECAY_HALFLIVES["momentum_event"]
        )
        stoch_bear = self._fval(f, "stoch_cross_bearish") * self._decay(
            1.0, self._fval(f, "stoch_cross_bars_ago"), _DECAY_HALFLIVES["momentum_event"]
        )
        stoch_event_dir = stoch_bull - stoch_bear

        rsi_accel = self._fval(f, "rsi_accel")
        rsi_accel_dir = self._decay(
            1.0 if rsi_accel > 0 else (-1.0 if rsi_accel < 0 else 0.0),
            self._fval(f, "stoch_cross_bars_ago"),  # reuse age as proxy
            _DECAY_HALFLIVES["momentum_event"],
        )
        macd_accel = self._fval(f, "macd_accel")
        macd_accel_dir = 1.0 if macd_accel > 0 else (-1.0 if macd_accel < 0 else 0.0)

        roc_accel = self._fval(f, "roc_accel")
        roc_accel_dir = 1.0 if roc_accel > 0 else (-1.0 if roc_accel < 0 else 0.0)

        os_rev = self._fval(f, "stoch_oversold_reversal") - self._fval(f, "stoch_overbought_reversal")

        firing = set()
        contributions = {
            "rsi_14": 0.225 * rsi_dir,
            "macd_histogram_12_26_9": 0.1875 * macd_dir,
            "roc_14": 0.15 * roc_dir,
            "momentum_bias": 0.1125 * clamp(self._fval(f, "momentum_bias")),
            "DivergenceStack": 0.075 * float(d) * float(c),
            "williams_r_14": 0.04 * wr_dir,
            "mfi_14": 0.04 * mfi_dir,
            "stoch_rsi_k_14": 0.03 * srsi_dir,
            "cmf_20": 0.03 * cmf,
            "rsi_accel": 0.02 * rsi_accel_dir,
            "macd_accel": 0.02 * macd_accel_dir,
            "roc_accel": 0.01 * roc_accel_dir,
            "stoch_cross": 0.02 * stoch_event_dir,
            "stoch_zone_reversal": 0.01 * clamp(os_rev),
        }

        for name, val in contributions.items():
            if val != 0.0:
                firing.add(name)

        raw = sum(contributions.values())
        return clamp(_apply_corr_penalty(raw, firing))
```

**Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_cis_scorer.py -v
```
Expected: new momentum tests PASS

**Step 5: Commit**

```bash
git add src/intelligence/trading/cis_scorer.py tests/unit/intelligence/test_cis_scorer.py
git commit -m "feat(cis): expand momentum bucket — add williams_r, mfi, stoch_rsi, cmf, accel events"
```

---

## Task 11: Expand trend bucket

**Files:**
- Modify: `src/intelligence/trading/cis_scorer.py`

**New intra-bucket weights (sum = 1.0):**

Existing ×0.82:
- `trend_regime`: 0.287 (was 0.35)
- `kalman_slope`: 0.164 (was 0.20)
- `smc_trend_direction`: 0.205 (was 0.25)
- `ctf_trend_alignment`: 0.082 (was 0.10)
- `trend_confluence_score`: 0.082 (was 0.10)

New:
- `aroon_osc_25`: 0.05
- `psar_direction`: 0.05
- `di_spread`: 0.04 (current indicator, not event)
- `macd_cross_event`: 0.03 (decayed, halflife=10)
- `adx_confirmed_event`: 0.02 (decayed, halflife=20)

**Step 1: Write failing test**

```python
# tests/unit/intelligence/test_cis_scorer.py — add:

def test_aroon_contributes_to_trend_bucket():
    scorer = CISScorer()
    features_bull = {"aroon_osc_25": 80.0, "trend_regime": 0.0}
    features_bear = {"aroon_osc_25": -80.0, "trend_regime": 0.0}
    r_bull = scorer.score(features_bull, {})
    r_bear = scorer.score(features_bear, {})
    assert r_bull.bucket_scores["trend"] > r_bear.bucket_scores["trend"]


def test_psar_direction_contributes_to_trend_bucket():
    scorer = CISScorer()
    r_bull = scorer.score({"psar_direction": 1.0}, {})
    r_bear = scorer.score({"psar_direction": -1.0}, {})
    assert r_bull.bucket_scores["trend"] > r_bear.bucket_scores["trend"]


def test_macd_cross_event_decays():
    scorer = CISScorer()
    # Fresh MACD bullish cross
    features_fresh = {"macd_cross_bullish": 1.0, "macd_cross_bars_ago": 0.0}
    features_stale = {"macd_cross_bullish": 1.0, "macd_cross_bars_ago": 20.0}
    r_fresh = scorer.score(features_fresh, {})
    r_stale = scorer.score(features_stale, {})
    assert r_fresh.bucket_scores["trend"] > r_stale.bucket_scores["trend"]
```

**Step 2: Run to verify it fails**

```bash
.venv/bin/pytest tests/unit/intelligence/test_cis_scorer.py::test_aroon_contributes_to_trend_bucket -v
```
Expected: FAIL

**Step 3: Rewrite _trend method**

Replace `_trend` in `src/intelligence/trading/cis_scorer.py`:

```python
    def _trend(self, f: dict) -> float:
        """Trend bucket [-1, +1]."""
        slope = self._fval(f, "kalman_slope")
        slope_dir = 1.0 if slope > 0 else (-1.0 if slope < 0 else 0.0)

        aroon_osc = self._fval(f, "aroon_osc_25")
        aroon_dir = clamp(aroon_osc / 100.0)

        psar = self._fval(f, "psar_direction")  # already +1/-1

        di_spread = clamp(self._fval(f, "di_spread") / 50.0)

        # Decayed MACD cross event (halflife=10)
        bars_macd = self._fval(f, "macd_cross_bars_ago")
        macd_cross_dir = self._decay(
            self._fval(f, "macd_cross_bullish") - self._fval(f, "macd_cross_bearish"),
            bars_macd,
            _DECAY_HALFLIVES["trend_event"],
        )

        # Decayed ADX confirmed event (halflife=20)
        adx_confirmed = self._fval(f, "adx_trend_confirmed")
        adx_dir_sign = 1.0 if di_spread > 0 else (-1.0 if di_spread < 0 else 0.0)
        adx_contrib = self._decay(
            adx_confirmed * adx_dir_sign,
            self._fval(f, "adx_confirmed_bars_ago"),
            _DECAY_HALFLIVES["confirm_event"],
        )

        firing = set()
        contributions = {
            "trend_regime": 0.287 * clamp(self._fval(f, "trend_regime")),
            "kalman_slope": 0.164 * slope_dir,
            "smc_trend_direction": 0.205 * clamp(self._fval(f, "smc_trend_direction")),
            "ctf_trend_alignment": 0.082 * clamp(self._fval(f, "ctf_trend_alignment")),
            "trend_confluence_score": 0.082 * clamp(self._fval(f, "trend_confluence_score")),
            "aroon_osc_25": 0.05 * aroon_dir,
            "psar_direction": 0.05 * clamp(psar),
            "di_spread": 0.04 * di_spread,
            "macd_cross_event": 0.03 * clamp(macd_cross_dir),
            "adx_confirmed_event": 0.02 * clamp(adx_contrib),
        }

        for name, val in contributions.items():
            if val != 0.0:
                firing.add(name)

        raw = sum(contributions.values())
        return clamp(_apply_corr_penalty(raw, firing))
```

**Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_cis_scorer.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add src/intelligence/trading/cis_scorer.py tests/unit/intelligence/test_cis_scorer.py
git commit -m "feat(cis): expand trend bucket — add aroon, psar, di_spread, macd cross event, adx event"
```

---

## Task 12: Expand regime + institutional buckets

**Files:**
- Modify: `src/intelligence/trading/cis_scorer.py`

**Regime additions:** `hv_ratio_20` (inverted — high HV = uncertainty), `donchian_position_20`, `inflection_flag` (suppressant)

**Institutional additions:** `obv_slope_sign`, `vol_spike` (direction-weighted), `bb_walking_upper/lower`, `bb_upper/lower_touch`

**Step 1: Write failing tests**

```python
# tests/unit/intelligence/test_cis_scorer.py — add:

def test_hv_ratio_high_reduces_regime_score():
    scorer = CISScorer()
    # Same HMM state, but one has elevated HV ratio
    base = {"hmm_prob_trending_up": 0.7, "hmm_prob_trending_down": 0.2}
    high_vol = {**base, "hv_ratio_20": 2.5}   # high vol = uncertainty
    norm_vol = {**base, "hv_ratio_20": 1.0}   # normal vol
    r_high = scorer.score(high_vol, {})
    r_norm = scorer.score(norm_vol, {})
    assert r_norm.bucket_scores["regime"] > r_high.bucket_scores["regime"]


def test_donchian_position_contributes_to_regime():
    scorer = CISScorer()
    r_top = scorer.score({"donchian_position_20": 1.0}, {})
    r_bot = scorer.score({"donchian_position_20": -1.0}, {})
    assert r_top.bucket_scores["regime"] > r_bot.bucket_scores["regime"]


def test_obv_slope_sign_contributes_to_institutional():
    scorer = CISScorer()
    r_bull = scorer.score({"obv_slope_sign": 1.0}, {})
    r_bear = scorer.score({"obv_slope_sign": -1.0}, {})
    assert r_bull.bucket_scores["institutional"] > r_bear.bucket_scores["institutional"]


def test_bb_walking_upper_contributes_bullish_to_institutional():
    scorer = CISScorer()
    r_walk = scorer.score({"bb_walking_upper": 1.0}, {})
    r_none = scorer.score({}, {})
    assert r_walk.bucket_scores["institutional"] > r_none.bucket_scores["institutional"]
```

**Step 2: Run to verify it fails**

```bash
.venv/bin/pytest tests/unit/intelligence/test_cis_scorer.py::test_hv_ratio_high_reduces_regime_score -v
```
Expected: FAIL

**Step 3: Rewrite _regime and _institutional methods**

Replace `_regime` in CISScorer:

```python
    def _regime(self, f: dict, po: dict) -> float:
        """Regime bucket [-1, +1]."""
        hmm_dir = (
            self._fval(f, "hmm_prob_trending_up")
            - self._fval(f, "hmm_prob_trending_down")
        )

        cp = self._fval(f, "cp_probability")
        cp_contribution = 0.0 if cp > 0.5 else clamp(hmm_dir) * (1.0 - cp * 2.0)

        d, c = self._plug(po, "trad_RegimeTransition")

        # HV ratio: above 1.0 = elevated vol = uncertainty → reduce directional confidence
        hv_ratio = self._fval(f, "hv_ratio_20", default=1.0)
        hv_contrib = clamp(-(hv_ratio - 1.0))  # 1.0 → 0, 2.0 → -1.0

        donchian_pos = clamp(self._fval(f, "donchian_position_20"))

        # inflection_flag = 1 means momentum is inflecting → uncertainty (like cp_probability)
        inflection = self._fval(f, "inflection_flag")
        inflection_suppressor = 0.0 if inflection > 0.5 else 1.0

        contributions = {
            "hmm_trending": 0.35 * clamp(hmm_dir) * inflection_suppressor,
            "bocpd_stability": 0.15 * cp_contribution * inflection_suppressor,
            "ctf_regime_agreement": 0.18 * clamp(self._fval(f, "ctf_regime_agreement")),
            "vol_regime": 0.14 * clamp(self._fval(f, "vol_regime") * -1.0),
            "RegimeTransition": 0.08 * float(d) * float(c),
            "hv_ratio_20": 0.05 * hv_contrib,
            "donchian_position_20": 0.05 * donchian_pos,
        }
        # weights: 0.35+0.15+0.18+0.14+0.08+0.05+0.05 = 1.00

        return clamp(sum(contributions.values()))
```

Replace `_institutional` in CISScorer:

```python
    def _institutional(self, f: dict, po: dict) -> float:
        """Institutional bucket [-1, +1]."""
        fvg_active = 1.0 if self._fval(f, "fvg_open_count") > 0 else 0.0
        zone = clamp(self._fval(f, "in_demand_zone") - self._fval(f, "in_supply_zone"))

        fd, fc = self._plug(po, "trad_FVGFill")
        sd_d, sd_c = self._plug(po, "trad_SupplyDemandSetup")

        # OBV slope sign: +1=accumulation(bullish), -1=distribution(bearish)
        obv_sign = self._fval(f, "obv_slope_sign")

        # Volume spike — directional: needs momentum_bias as direction proxy
        vol_spike = self._fval(f, "vol_spike")
        mb = self._fval(f, "momentum_bias", default=0.0)
        mb_sign = 1.0 if mb > 0 else (-1.0 if mb < 0 else 0.0)
        vol_spike_bars = self._fval(f, "vol_spike_bars_ago")
        vol_spike_contrib = self._decay(
            vol_spike * mb_sign, vol_spike_bars, _DECAY_HALFLIVES["momentum_event"]
        )

        # BB walking = strong institutional momentum
        bb_walk_bull = self._decay(
            self._fval(f, "bb_walking_upper"),
            self._fval(f, "vol_spike_bars_ago"),  # reuse as proxy
            _DECAY_HALFLIVES["trend_event"],
        )
        bb_walk_bear = self._decay(
            self._fval(f, "bb_walking_lower"),
            self._fval(f, "vol_spike_bars_ago"),
            _DECAY_HALFLIVES["trend_event"],
        )

        # BB touch = overextension (mean-reversion: upper touch = bearish, lower = bullish)
        bb_touch_bull = self._decay(
            self._fval(f, "bb_lower_touch"),
            self._fval(f, "vol_spike_bars_ago"),
            _DECAY_HALFLIVES["momentum_event"],
        )
        bb_touch_bear = self._decay(
            self._fval(f, "bb_upper_touch"),
            self._fval(f, "vol_spike_bars_ago"),
            _DECAY_HALFLIVES["momentum_event"],
        )

        contributions = {
            "ob_zone": 0.22 * clamp(self._fval(f, "ob_type") * self._fval(f, "ob_strength")),
            "fvg_active": 0.12 * clamp(self._fval(f, "fvg_type") * fvg_active),
            "supply_demand_zone": 0.18 * zone,
            "FVGFill": 0.16 * float(fd) * float(fc),
            "SupplyDemandSetup": 0.16 * float(sd_d) * float(sd_c),
            "obv_slope_sign": 0.06 * clamp(obv_sign),
            "vol_spike_dir": 0.04 * clamp(vol_spike_contrib),
            "bb_walking": 0.03 * clamp(bb_walk_bull - bb_walk_bear),
            "bb_touch": 0.03 * clamp(bb_touch_bull - bb_touch_bear),
        }
        # weights: 0.22+0.12+0.18+0.16+0.16+0.06+0.04+0.03+0.03 = 1.00

        return clamp(sum(contributions.values()))
```

**Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_cis_scorer.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add src/intelligence/trading/cis_scorer.py tests/unit/intelligence/test_cis_scorer.py
git commit -m "feat(cis): expand regime + institutional buckets — hv_ratio, donchian, obv, bb events"
```

---

## Task 13: ContribTracker — wire constituent_contributions into score()

**Files:**
- Modify: `src/intelligence/trading/cis_scorer.py`

**Context:** All bucket methods currently return a float. Refactor each to also return a `dict[str, float]` of per-signal contributions (signal_name → contribution_to_final_cis). The `score()` method collects these into `CISResult.constituent_contributions`.

**Step 1: Write failing test**

```python
# tests/unit/intelligence/test_cis_scorer.py — add:

def test_constituent_contributions_populated_for_active_signals():
    scorer = CISScorer()
    features = {
        "rsi_14": 70.0,
        "trend_regime": 0.8,
        "psar_direction": 1.0,
        "ob_type": 1.0, "ob_strength": 0.7,
    }
    result = scorer.score(features, {})
    assert result.constituent_contributions["momentum"].get("rsi_14") is not None
    assert result.constituent_contributions["trend"].get("trend_regime") is not None
    assert result.constituent_contributions["trend"].get("psar_direction") is not None
    assert result.constituent_contributions["institutional"].get("ob_zone") is not None


def test_constituent_contributions_zero_for_missing_signals():
    scorer = CISScorer()
    result = scorer.score({}, {})
    # Missing signals should be 0 or absent
    for bucket, contribs in result.constituent_contributions.items():
        for name, val in contribs.items():
            assert isinstance(val, float)


def test_constituent_contributions_sum_approximates_bucket_score():
    scorer = CISScorer()
    features = {"rsi_14": 75.0, "momentum_bias": 0.5, "macd_histogram_12_26_9": 1.0}
    result = scorer.score(features, {})
    # Sum of constituent contributions × (1/bucket_weight) should ≈ bucket_score
    mom_bucket_weight = 0.20
    contribs_sum = sum(result.constituent_contributions["momentum"].values())
    # Each contribution is already scaled by bucket_weight, so raw sum ≈ bucket_score * bucket_weight
    assert abs(contribs_sum - result.bucket_scores["momentum"] * mom_bucket_weight) < 0.1
```

**Step 2: Run to verify it fails**

```bash
.venv/bin/pytest tests/unit/intelligence/test_cis_scorer.py::test_constituent_contributions_populated_for_active_signals -v
```
Expected: FAIL — contributions dict is empty `{}`

**Step 3: Refactor bucket methods to return contributions**

Refactor each bucket method signature: `def _momentum(self, f, po) -> tuple[float, dict[str, float]]`

For each method:
1. Add a `contributions` dict tracking `signal_name → raw_contribution` (before bucket weight scaling)
2. Return `(bucket_score, {k: round(v * bucket_weight, 6) for k, v in contributions.items()})`

In `score()`, change to:

```python
    def score(self, features, plugin_outputs) -> CISResult:
        bw = self._weights  # bucket weights

        m_score, m_contribs = self._momentum(features, plugin_outputs)
        tr_score, tr_contribs = self._trend(features)
        st_score, st_contribs = self._structure(features, plugin_outputs)
        pt_score, pt_contribs = self._pattern(features, plugin_outputs)
        inst_score, inst_contribs = self._institutional(features, plugin_outputs)
        rg_score, rg_contribs = self._regime(features, plugin_outputs)

        bucket_scores = {
            "momentum": m_score,
            "trend": tr_score,
            "structure": st_score,
            "pattern": pt_score,
            "institutional": inst_score,
            "regime": rg_score,
        }

        constituent_contributions = {
            "momentum": m_contribs,
            "trend": tr_contribs,
            "structure": st_contribs,
            "pattern": pt_contribs,
            "institutional": inst_contribs,
            "regime": rg_contribs,
        }

        cis_raw = sum(bw[b] * bucket_scores[b] for b in BUCKET_NAMES)
        cis_score = clamp(cis_raw)
        # ... rest of score() logic unchanged ...

        return CISResult(
            cis_score=round(cis_score, 4),
            direction=direction,
            bucket_scores={k: round(v, 4) for k, v in bucket_scores.items()},
            weights_version=self._weights_version,
            buckets_agreeing=agreeing,
            constituent_contributions=constituent_contributions,
        )
```

Apply the same tuple-return pattern to all bucket methods (`_structure`, `_pattern` — the ones not yet refactored in Tasks 10-12).

**Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_cis_scorer.py -v
```
Expected: all PASS

**Step 5: Run full suite**

```bash
.venv/bin/pytest tests/unit/ -q
```
Expected: all PASS (1083+)

**Step 6: Commit**

```bash
git add src/intelligence/trading/cis_scorer.py tests/unit/intelligence/test_cis_scorer.py
git commit -m "feat(cis): wire constituent_contributions into score() — full per-signal attribution"
```

---

## Task 14: signal_generator_service — write cis_attribution to LedgerEntry

**Files:**
- Modify: `services/signal_generator_service.py`
- Modify: `src/intelligence/trading/aggregator.py`

**Context:** `AggregatedResult` currently carries `cis_score`, `bucket_scores`, `weights_version`. Add `cis_attribution`. `build_ledger_entries` must pass it to `LedgerEntry`.

**Step 1: Write failing test**

```python
# tests/unit/intelligence/test_aggregator.py — add:

def test_aggregated_result_has_cis_attribution():
    from src.intelligence.trading.aggregator import AggregatedResult
    result = AggregatedResult(
        cis_attribution={"momentum": {"rsi_14": 0.038}},
    )
    assert result.cis_attribution == {"momentum": {"rsi_14": 0.038}}
```

**Step 2: Run to verify it fails**

```bash
.venv/bin/pytest tests/unit/intelligence/test_aggregator.py::test_aggregated_result_has_cis_attribution -v
```
Expected: FAIL

**Step 3: Add cis_attribution to AggregatedResult**

In `src/intelligence/trading/aggregator.py`:

```python
@dataclass
class AggregatedResult:
    ...
    cis_attribution: dict | None = None  # NEW
```

Wherever `AggregatedResult(...)` is constructed (after calls to `cis_scorer.score()`), pass:
```python
cis_attribution=cis_result.constituent_contributions,
```

In `build_ledger_entries` in `signal_generator_service.py`, pass to `LedgerEntry`:
```python
cis_attribution=result.cis_attribution,
```

**Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/intelligence/test_aggregator.py tests/unit/intelligence/test_signal_ledger.py -v
```
Expected: all PASS

**Step 5: Commit**

```bash
git add src/intelligence/trading/aggregator.py services/signal_generator_service.py
git commit -m "feat: propagate cis_attribution through AggregatedResult → LedgerEntry → signal_ledger"
```

---

## Task 15: I8 narrative — include top-contributor summary in prompt

**Files:**
- Modify: `services/ai_narrative_service.py` (or wherever the I8 prompt is built)

**Step 1: Locate prompt builder**

```bash
grep -n "def.*prompt\|prompt.*=\|constituent\|attribution\|bucket_scores" services/ai_narrative_service.py | head -20
```

**Step 2: Write failing test**

```python
# tests/unit/test_ai_narrative.py or closest file
# Find the prompt builder function and test that attribution summary is included

def test_narrative_prompt_includes_top_contributors_when_present():
    from services.ai_narrative_service import _build_signal_prompt  # adjust import as needed
    cis_attribution = {
        "trend": {"trend_regime": 0.062, "psar_direction": 0.008},
        "momentum": {"rsi_14": 0.038},
        "institutional": {"ob_zone": 0.055},
    }
    prompt = _build_signal_prompt(
        signal={"signal_type": "fvg_fill_long", "direction": 1, "confidence": 0.85},
        features={},
        cis_attribution=cis_attribution,
    )
    assert "psar_direction" in prompt or "trend_regime" in prompt
    assert "ob_zone" in prompt or "institutional" in prompt
```

**Step 3: Implement**

Find the I8 prompt builder. Add a helper that formats top contributors:

```python
def _format_attribution_summary(cis_attribution: dict | None) -> str:
    """Format top-3 contributors per bucket for I8 prompt."""
    if not cis_attribution:
        return ""
    lines = ["Top CIS contributors:"]
    for bucket, contribs in cis_attribution.items():
        if not contribs:
            continue
        top = sorted(contribs.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
        if top:
            parts = [f"{name}[{val:+.3f}]" for name, val in top if abs(val) > 0.001]
            if parts:
                lines.append(f"  {bucket}: {', '.join(parts)}")
    return "\n".join(lines)
```

Pass `cis_attribution` through to the prompt builder and inject `_format_attribution_summary(cis_attribution)` into the prompt.

**Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/ -q
```
Expected: all PASS

**Step 5: Commit**

```bash
git add services/ai_narrative_service.py
git commit -m "feat(I8): include CIS top-contributor attribution in AI narrative prompt"
```

---

## Task 16: Final regression — full suite + ruff

**Step 1: Run full test suite**

```bash
.venv/bin/pytest tests/unit/ -v --tb=short 2>&1 | tail -30
```
Expected: all tests PASS, count ≥ 1083

**Step 2: Run ruff**

```bash
.venv/bin/ruff check . --fix
```
Expected: `All checks passed.` (0 errors after auto-fix)

**Step 3: Run ruff format**

```bash
.venv/bin/black src/ services/ tests/unit/
```

**Step 4: Commit clean state**

```bash
git add -u
git commit -m "chore: ruff + black cleanup after CIS universal ensemble implementation"
```

---

## Summary

| Phase | Tasks | What it does |
|-------|-------|-------------|
| A: DB + Schema | 1–3 | Migration, LedgerEntry field, CISResult field |
| B: Pipeline fix | 4 | Wire I2 into features dict (root fix) |
| C: Bridge composites | 5–7 | DonchianPosition, OBVMomentum, I2Events schema |
| D: CIS infrastructure | 8–9 | Event decay + correlation penalty |
| E: Bucket expansion | 10–12 | All 4 buckets get unused indicators + I2 events |
| F: Attribution | 13–14 | Full per-signal contributions into signal_ledger |
| G: I8 | 15 | AI narrative references top contributors by name |
| H: Regression | 16 | Full suite green, ruff 0 errors |

After this plan, every I1 and I2 output either contributes to CIS scores or is retired with a documented reason.
