# MomentumAcceleration I2 Plugin Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a new I2 composite plugin that computes the first difference (acceleration) of RSI, MACD, and ROC, and fires an `inflection_flag` when any of the three changes sign.

**Architecture:** I2 plugin consuming `features` / `prev_features` from the I1 output dict. Stores previous deltas in `_state` to detect sign changes. Follows the exact same dataclass + `compute_full` / `compute_next` pattern as all other I2 composites.

**Tech Stack:** Python dataclass, `src/intelligence/composites/common.py` (`is_num`), pytest

---

### Task 1: Write failing tests

**Files:**
- Create: `tests/unit/intelligence/composites/test_momentum_accel.py`

**Step 1: Create the test file**

```python
# tests/unit/intelligence/composites/test_momentum_accel.py
from __future__ import annotations

import pytest

from src.intelligence.composites.momentum_accel import MomentumAccelPlugin


def make_frames(
    rsi=None, macd=None, roc=None,
    prev_rsi=None, prev_macd=None, prev_roc=None,
) -> dict:
    features = {}
    prev = {}
    if rsi is not None:
        features["rsi_14"] = rsi
    if macd is not None:
        features["macd_12_26_9"] = macd
    if roc is not None:
        features["roc_14"] = roc
    if prev_rsi is not None:
        prev["rsi_14"] = prev_rsi
    if prev_macd is not None:
        prev["macd_12_26_9"] = prev_macd
    if prev_roc is not None:
        prev["roc_14"] = prev_roc
    return {"features": features, "prev_features": prev}


def test_missing_prev_returns_zeros():
    plugin = MomentumAccelPlugin()
    result = plugin.compute_next({
        "features": {"rsi_14": 50.0, "macd_12_26_9": 0.5, "roc_14": 1.0},
        "prev_features": {},
    })
    assert result["rsi_accel"] == 0.0
    assert result["macd_accel"] == 0.0
    assert result["roc_accel"] == 0.0
    assert result["inflection_flag"] == 0


def test_rsi_accel_computed_correctly():
    plugin = MomentumAccelPlugin()
    result = plugin.compute_next(make_frames(
        rsi=55.0, macd=0.0, roc=0.0,
        prev_rsi=50.0, prev_macd=0.0, prev_roc=0.0,
    ))
    assert result["rsi_accel"] == pytest.approx(5.0)


def test_macd_accel_computed_correctly():
    plugin = MomentumAccelPlugin()
    result = plugin.compute_next(make_frames(
        rsi=50.0, macd=0.8, roc=0.0,
        prev_rsi=50.0, prev_macd=0.5, prev_roc=0.0,
    ))
    assert result["macd_accel"] == pytest.approx(0.3)


def test_roc_accel_computed_correctly():
    plugin = MomentumAccelPlugin()
    result = plugin.compute_next(make_frames(
        rsi=50.0, macd=0.0, roc=2.0,
        prev_rsi=50.0, prev_macd=0.0, prev_roc=3.0,
    ))
    assert result["roc_accel"] == pytest.approx(-1.0)


def test_inflection_flag_zero_on_first_bar():
    """First bar: deltas exist but no prior delta in state yet — flag must be 0."""
    plugin = MomentumAccelPlugin()
    result = plugin.compute_next(make_frames(
        rsi=55.0, macd=0.5, roc=1.0,
        prev_rsi=50.0, prev_macd=0.3, prev_roc=0.5,
    ))
    assert result["inflection_flag"] == 0


def test_inflection_flag_fires_on_rsi_sign_change():
    plugin = MomentumAccelPlugin()
    # Bar 1: rsi_accel = +5.0 → stored in state
    plugin.compute_next(make_frames(
        rsi=55.0, macd=0.0, roc=0.0,
        prev_rsi=50.0, prev_macd=0.0, prev_roc=0.0,
    ))
    # Bar 2: rsi_accel = -2.0 → sign change
    result = plugin.compute_next(make_frames(
        rsi=53.0, macd=0.0, roc=0.0,
        prev_rsi=55.0, prev_macd=0.0, prev_roc=0.0,
    ))
    assert result["inflection_flag"] == 1


def test_inflection_flag_fires_on_macd_sign_change():
    plugin = MomentumAccelPlugin()
    # Bar 1: macd_accel = +0.2
    plugin.compute_next(make_frames(
        rsi=50.0, macd=0.5, roc=0.0,
        prev_rsi=50.0, prev_macd=0.3, prev_roc=0.0,
    ))
    # Bar 2: macd_accel = -0.1 → sign change
    result = plugin.compute_next(make_frames(
        rsi=50.0, macd=0.4, roc=0.0,
        prev_rsi=50.0, prev_macd=0.5, prev_roc=0.0,
    ))
    assert result["inflection_flag"] == 1


def test_inflection_flag_fires_on_roc_sign_change():
    plugin = MomentumAccelPlugin()
    # Bar 1: roc_accel = +1.0
    plugin.compute_next(make_frames(
        rsi=50.0, macd=0.0, roc=2.0,
        prev_rsi=50.0, prev_macd=0.0, prev_roc=1.0,
    ))
    # Bar 2: roc_accel = -0.5 → sign change
    result = plugin.compute_next(make_frames(
        rsi=50.0, macd=0.0, roc=1.5,
        prev_rsi=50.0, prev_macd=0.0, prev_roc=2.0,
    ))
    assert result["inflection_flag"] == 1


def test_inflection_flag_zero_when_no_sign_change():
    plugin = MomentumAccelPlugin()
    # Bar 1: all positive accels
    plugin.compute_next(make_frames(
        rsi=55.0, macd=0.5, roc=2.0,
        prev_rsi=50.0, prev_macd=0.3, prev_roc=1.0,
    ))
    # Bar 2: all still positive
    result = plugin.compute_next(make_frames(
        rsi=58.0, macd=0.7, roc=3.5,
        prev_rsi=55.0, prev_macd=0.5, prev_roc=2.0,
    ))
    assert result["inflection_flag"] == 0


def test_inflection_flag_zero_when_delta_reaches_zero():
    """prev_accel * 0 = 0, which is not < 0 → no inflection."""
    plugin = MomentumAccelPlugin()
    # Bar 1: rsi_accel = +5.0
    plugin.compute_next(make_frames(
        rsi=55.0, macd=0.0, roc=0.0,
        prev_rsi=50.0, prev_macd=0.0, prev_roc=0.0,
    ))
    # Bar 2: rsi_accel = 0.0 (flat)
    result = plugin.compute_next(make_frames(
        rsi=55.0, macd=0.0, roc=0.0,
        prev_rsi=55.0, prev_macd=0.0, prev_roc=0.0,
    ))
    assert result["inflection_flag"] == 0


def test_state_persists_across_multiple_calls():
    """Three bars: up, up, down → inflection only on the third bar."""
    plugin = MomentumAccelPlugin()
    plugin.compute_next(make_frames(
        rsi=52.0, macd=0.0, roc=0.0,
        prev_rsi=50.0, prev_macd=0.0, prev_roc=0.0,
    ))  # accel = +2
    r2 = plugin.compute_next(make_frames(
        rsi=55.0, macd=0.0, roc=0.0,
        prev_rsi=52.0, prev_macd=0.0, prev_roc=0.0,
    ))  # accel = +3, same sign → no inflection
    assert r2["inflection_flag"] == 0
    r3 = plugin.compute_next(make_frames(
        rsi=53.0, macd=0.0, roc=0.0,
        prev_rsi=55.0, prev_macd=0.0, prev_roc=0.0,
    ))  # accel = -2, sign change → inflection
    assert r3["inflection_flag"] == 1


def test_plugin_registered_in_tier_i2():
    from src.intelligence.register_plugins import TIER_I2
    from src.intelligence.composites.momentum_accel import plugin
    assert plugin.name in TIER_I2
```

**Step 2: Run to confirm all tests fail (ImportError expected)**

```bash
.venv/bin/pytest tests/unit/intelligence/composites/test_momentum_accel.py -v
```

Expected: all 12 tests fail with `ModuleNotFoundError: No module named 'src.intelligence.composites.momentum_accel'`

---

### Task 2: Implement the plugin

**Files:**
- Create: `src/intelligence/composites/momentum_accel.py`

**Step 1: Create the plugin file**

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
        })
    )
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset = field(
        default_factory=lambda: frozenset({"momentum"})
    )
    inputs: list[InputSpec] = field(default_factory=list)
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        features = frames.get("features") or {}
        prev = frames.get("prev_features") or {}

        rsi = features.get("rsi_14")
        macd = features.get("macd_12_26_9")
        roc = features.get("roc_14")

        prev_rsi = prev.get("rsi_14")
        prev_macd = prev.get("macd_12_26_9")
        prev_roc = prev.get("roc_14")

        out: dict[str, Any] = {}
        inflection = 0

        # RSI acceleration
        if is_num(rsi) and is_num(prev_rsi):
            rsi_accel = rsi - prev_rsi
            prev_rsi_accel = self._state.get("prev_rsi_accel")
            if is_num(prev_rsi_accel) and prev_rsi_accel * rsi_accel < 0:
                inflection = 1
            self._state["prev_rsi_accel"] = rsi_accel
            out["rsi_accel"] = rsi_accel
        else:
            out["rsi_accel"] = 0.0

        # MACD acceleration
        if is_num(macd) and is_num(prev_macd):
            macd_accel = macd - prev_macd
            prev_macd_accel = self._state.get("prev_macd_accel")
            if is_num(prev_macd_accel) and prev_macd_accel * macd_accel < 0:
                inflection = 1
            self._state["prev_macd_accel"] = macd_accel
            out["macd_accel"] = macd_accel
        else:
            out["macd_accel"] = 0.0

        # ROC acceleration
        if is_num(roc) and is_num(prev_roc):
            roc_accel = roc - prev_roc
            prev_roc_accel = self._state.get("prev_roc_accel")
            if is_num(prev_roc_accel) and prev_roc_accel * roc_accel < 0:
                inflection = 1
            self._state["prev_roc_accel"] = roc_accel
            out["roc_accel"] = roc_accel
        else:
            out["roc_accel"] = 0.0

        out["inflection_flag"] = inflection
        return out

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = MomentumAccelPlugin()
```

**Step 2: Run tests (all except `test_plugin_registered_in_tier_i2` should pass)**

```bash
.venv/bin/pytest tests/unit/intelligence/composites/test_momentum_accel.py -v
```

Expected: 11 pass, 1 fail (`test_plugin_registered_in_tier_i2` — not yet registered)

---

### Task 3: Register the plugin

**Files:**
- Modify: `src/intelligence/register_plugins.py`

The file has an import block at the top for composites, a `register_all_plugins()` function that calls `registry.register_pattern()` for each I2 plugin, and a `TIER_I2` list constant.

**Step 1: Add the import** — find the block where other composite plugins are imported (near `from .composites.macd_events import ...`) and add:

```python
from .composites.momentum_accel import plugin as momentum_accel_plugin
```

**Step 2: Register in `register_all_plugins()`** — find the I2 registration block (5 lines calling `registry.register_pattern(...)` for I2 composites) and append:

```python
registry.register_pattern(momentum_accel_plugin)
```

**Step 3: Add to `TIER_I2`** — find the `TIER_I2` list and append:

```python
momentum_accel_plugin.name,
```

**Step 4: Run all tests**

```bash
.venv/bin/pytest tests/unit/intelligence/composites/test_momentum_accel.py -v
```

Expected: all 12 pass

**Step 5: Commit**

```bash
git add src/intelligence/composites/momentum_accel.py \
        src/intelligence/register_plugins.py \
        tests/unit/intelligence/composites/test_momentum_accel.py
git commit -m "feat: add MomentumAcceleration I2 plugin (rsi/macd/roc accel + inflection_flag)"
```

---

### Task 4: Full suite verification

**Step 1: Run full test suite**

```bash
.venv/bin/pytest tests/unit/ -v --tb=short 2>&1 | tail -20
```

Expected: all existing tests still pass + 12 new ones

**Step 2: Lint**

```bash
.venv/bin/ruff check . --fix
```

Expected: 0 errors

**Step 3: Final commit if ruff made any fixes**

```bash
git add -p
git commit -m "chore: ruff fixes for momentum_accel plugin"
```

Only commit if `git diff --staged` is non-empty.
