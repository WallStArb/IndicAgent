# Phase 46 Gap Closure: VIX + Cross-Asset → I4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move VIX regime and EQ cross-asset context from I6 (pass-through) to two proper I4 plugins, fix the per-TF VIX z-score data quality defect, and rename `capture_confluence_features` → `capture_signal_features`.

**Architecture:** Two new I4 context plugins (`VIXRegimePlugin`, `CrossAssetContextPlugin`) read from injected frames and emit 4 fields into `I4Context`. `I6Confluence` loses the 4 pass-through fields. `feature_pipeline_service` fixes VIX lookup to always use `VIX_REGIME_TF="1h"`. `CROSS_ASSET_VALID_TFS` moves to `service_utils.py`. All 36 I7 plugins get a mechanical import rename.

**Tech Stack:** Python 3.13, pytest, `src/intelligence/context/` plugin pattern, `src/intelligence/schemas.py` Pydantic models, `src/core/service_utils.py`

**Spec:** `docs/plans/2026-03-22-phase-46-gap-vix-cross-asset-to-i4.md`

**Run all tests with:** `.venv/bin/pytest tests/unit/ -q --tb=short`

---

## File Map

| File | Action |
|------|--------|
| `src/core/service_utils.py` | Add `CROSS_ASSET_VALID_TFS` constant |
| `src/intelligence/schemas.py` | `I4Context` +4 fields; `I6Confluence` −4 fields |
| `src/intelligence/context/vix_regime.py` | **New** — `VIXRegimePlugin` |
| `src/intelligence/context/cross_asset_context.py` | **New** — `CrossAssetContextPlugin` |
| `src/intelligence/register_plugins.py` | Import + register both plugins in `TIER_I4` |
| `services/feature_pipeline_service.py` | `VIX_REGIME_TF="1h"`, remove local `_CROSS_ASSET_VALID_TFS` |
| `services/signal_generator_service.py` | Remove local `_CROSS_ASSET_VALID_TFS`, import from service_utils |
| `src/intelligence/confluence/cross_timeframe.py` | Remove ~20-line VIX/cross-asset pass-through block |
| `src/intelligence/trading/confidence_utils.py` | Rename function + shadow keys + docstrings |
| `src/intelligence/trading/*.py` (36 files) | Mechanical import rename |
| `tests/unit/intelligence/test_vix_regime.py` | **New** |
| `tests/unit/intelligence/test_cross_asset_context.py` | **New** |
| `tests/unit/service_tests/test_feature_pipeline_vix_injection.py` | Update: assert `VIX_REGIME_TF` used |
| `tests/unit/test_cross_timeframe_confluence.py` | Remove 4 field assertions |
| `tests/unit/test_capture_confluence_features.py` | Rename file + update function name + key names |

---

## Task 1: Move CROSS_ASSET_VALID_TFS to service_utils

**Files:**
- Modify: `src/core/service_utils.py`
- Modify: `services/feature_pipeline_service.py`
- Modify: `services/signal_generator_service.py`

- [ ] **Step 1: Add constant to service_utils.py**

Find the constants section near the top of `src/core/service_utils.py` and add:
```python
# Timeframes published by cross_asset_service — shared by all pipeline services
CROSS_ASSET_VALID_TFS: frozenset[str] = frozenset({"1m", "5m", "15m", "1h"})
```

- [ ] **Step 2: Update feature_pipeline_service.py**

In the `from src.core.service_utils import (` block (line ~48), add `CROSS_ASSET_VALID_TFS` to the import list.

Delete line 106:
```python
_CROSS_ASSET_VALID_TFS: frozenset[str] = frozenset({"1m", "5m", "15m", "1h"})
```

Replace all occurrences of `_CROSS_ASSET_VALID_TFS` in this file with `CROSS_ASSET_VALID_TFS`.

- [ ] **Step 3: Update signal_generator_service.py**

In the `from src.core.service_utils import (` block (line ~44), add `CROSS_ASSET_VALID_TFS` to the import list.

Delete line 218:
```python
_CROSS_ASSET_VALID_TFS: frozenset[str] = frozenset({"1m", "5m", "15m", "1h"})
```

Replace all occurrences of `_CROSS_ASSET_VALID_TFS` in this file with `CROSS_ASSET_VALID_TFS`.

- [ ] **Step 4: Verify no syntax errors**

```bash
.venv/bin/python -c "from src.core.service_utils import CROSS_ASSET_VALID_TFS; print(CROSS_ASSET_VALID_TFS)"
```
Expected: `frozenset({'1m', '5m', '15m', '1h'})`

- [ ] **Step 5: Commit**

```bash
git add src/core/service_utils.py services/feature_pipeline_service.py services/signal_generator_service.py
git commit -m "refactor(46.1): consolidate CROSS_ASSET_VALID_TFS to service_utils"
```

---

## Task 2: Schema — I4Context +4 fields, I6Confluence −4 fields

**Files:**
- Modify: `src/intelligence/schemas.py`

- [ ] **Step 1: Write failing schema test**

Create `tests/unit/intelligence/test_macro_context_schema.py`:
```python
"""Verify I4Context has VIX/EQ fields and I6Confluence does not."""
from src.intelligence.schemas import I4Context, I6Confluence


def test_i4_context_has_vix_fields():
    ctx = I4Context()
    assert hasattr(ctx, "vix_level")
    assert hasattr(ctx, "vix_z")
    assert ctx.vix_level is None
    assert ctx.vix_z is None


def test_i4_context_has_eq_fields():
    ctx = I4Context()
    assert hasattr(ctx, "eq_spread_z")
    assert hasattr(ctx, "eq_pairs_confirming")
    assert ctx.eq_spread_z is None
    assert ctx.eq_pairs_confirming is None


def test_i6_confluence_does_not_have_vix_fields():
    conf = I6Confluence()
    assert not hasattr(conf, "ctf_vix_level")
    assert not hasattr(conf, "ctf_vix_z")
    assert not hasattr(conf, "ctf_eq_spread_z")
    assert not hasattr(conf, "ctf_eq_pairs_confirming")
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/unit/intelligence/test_macro_context_schema.py -v
```
Expected: `test_i4_context_has_vix_fields` FAILS (AttributeError), last test PASSES (fields don't exist yet in I6 either... wait, they DO exist in I6 from Phase 46)

Expected actual: first 2 tests FAIL, last test FAILS (ctf_vix_level still present in I6Confluence).

- [ ] **Step 3: Update I4Context in schemas.py**

Find the `I4Context` class in `src/intelligence/schemas.py` (line ~250). After the `VolumeProfile` section comment (before the final closing of the class), add:
```python
    # MacroContextPlugin outputs (Phase 46.1)
    vix_level: float | None = None            # VIX close price; computed from 1h bars always
    vix_z: float | None = None                # VIX z-score, 20-bar rolling mean, 1h window
    eq_spread_z: float | None = None          # dominant EQ pair spread z-score; EQ_INDEX only
    eq_pairs_confirming: float | None = None  # 0.0–2.0 confirming pairs; EQ_INDEX only
```

Also update the `I4Context` docstring to add `MacroContext (4 fields)` to the plugin list and update the total count from 93 to 97.

- [ ] **Step 4: Remove 4 fields from I6Confluence in schemas.py**

Find `I6Confluence` (line ~678). Remove these 4 lines:
```python
    ctf_vix_level: float | None = None       # raw VIX close level; all symbols
    ctf_vix_z: float | None = None           # VIX z-score vs 20-bar rolling mean; all symbols
    ctf_eq_spread_z: float | None = None     # dominant EQ pair spread z-score; EQ_INDEX only
    ctf_eq_pairs_confirming: float | None = None  # 0.0-2.0 confirming pairs; EQ_INDEX only
```

- [ ] **Step 5: Run test to verify pass**

```bash
.venv/bin/pytest tests/unit/intelligence/test_macro_context_schema.py -v
```
Expected: all 3 tests PASS.

- [ ] **Step 6: Run full suite to check for regressions from schema change**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short 2>&1 | tail -15
```
Expected: some tests may now fail due to `ctf_vix_*` references in existing test files — that's expected; they'll be fixed in later tasks. If unexpected failures appear, investigate before continuing.

- [ ] **Step 7: Commit**

```bash
git add src/intelligence/schemas.py tests/unit/intelligence/test_macro_context_schema.py
git commit -m "feat(46.1): I4Context +4 macro fields; I6Confluence -4 pass-through fields"
```

---

## Task 3: VIXRegimePlugin

**Files:**
- Create: `src/intelligence/context/vix_regime.py`
- Create: `tests/unit/intelligence/test_vix_regime.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/intelligence/test_vix_regime.py`:
```python
"""Tests for VIXRegimePlugin — I4 context plugin."""
from collections import deque
from unittest.mock import MagicMock

import pytest

from src.intelligence.context.vix_regime import VIXRegimePlugin


@pytest.fixture
def plugin():
    return VIXRegimePlugin()


def _make_vix_frame(ready: bool, level: float = 18.5, z_score: float = 1.2) -> dict:
    if not ready:
        return {"vix": {"ready": False}}
    return {"vix": {"ready": True, "level": level, "z_score": z_score}}


def test_returns_vix_level_and_z_when_ready(plugin):
    frames = _make_vix_frame(ready=True, level=22.0, z_score=-0.5)
    result = plugin.compute_full(frames)
    assert result["vix_level"] == 22.0
    assert result["vix_z"] == -0.5


def test_returns_empty_when_vix_not_ready(plugin):
    frames = _make_vix_frame(ready=False)
    result = plugin.compute_full(frames)
    assert result == {}


def test_returns_empty_when_vix_frame_absent(plugin):
    result = plugin.compute_full({})
    assert result == {}


def test_outputs_frozenset_correct(plugin):
    assert plugin.outputs == frozenset({"vix_level", "vix_z"})


def test_name_follows_i4_convention(plugin):
    assert plugin.name == "ctx_VIXRegime"


def test_compute_next_delegates_to_compute_full(plugin):
    frames = _make_vix_frame(ready=True, level=15.0, z_score=0.3)
    assert plugin.compute_next(frames) == plugin.compute_full(frames)


def test_none_level_passed_through(plugin):
    """If vix context returns level=None (shouldn't happen but guard it), passes through."""
    frames = {"vix": {"ready": True, "level": None, "z_score": 0.0}}
    result = plugin.compute_full(frames)
    assert result["vix_level"] is None
    assert result["vix_z"] == 0.0
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/unit/intelligence/test_vix_regime.py -v
```
Expected: ImportError — `vix_regime` module doesn't exist yet.

- [ ] **Step 3: Implement VIXRegimePlugin**

Create `src/intelligence/context/vix_regime.py`:
```python
"""VIX regime context plugin — I4 macro context layer.

Reads pre-computed VIX context from frames["vix"] (injected by
FeaturePipelineService using a fixed 1h lookback TF) and emits
vix_level and vix_z into I4Context.

Design decisions:
- VIX_REGIME_TF="1h" in feature_pipeline_service gives z_window=20
  over 20 trading hours — captures session-scale fear elevation.
  Complementary to GARCH (multi-week structural vol regime).
- Returns {} when VIX data unavailable — I4Context defaults vix_level
  and vix_z to None. Downstream plugins must treat None as "no data",
  not as "VIX is zero".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec


@dataclass
class VIXRegimePlugin:
    """I4 macro context: VIX fear-regime level and z-score.

    Reads frames["vix"] injected by FeaturePipelineService.
    All symbols receive VIX context (VIX is a global fear gauge).
    Returns {} when VIX bars are insufficient (< z_window=20 at 1h TF).
    """

    name: str = "ctx_VIXRegime"
    outputs: frozenset[str] = frozenset({"vix_level", "vix_z"})
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"context", "macro"})
    inputs: tuple[InputSpec, ...] = ()
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        vix = frames.get("vix") or {}
        if not vix.get("ready"):
            return {}
        return {
            "vix_level": vix.get("level"),
            "vix_z": vix.get("z_score"),
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = VIXRegimePlugin()
```

- [ ] **Step 4: Run tests to verify pass**

```bash
.venv/bin/pytest tests/unit/intelligence/test_vix_regime.py -v
```
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/context/vix_regime.py tests/unit/intelligence/test_vix_regime.py
git commit -m "feat(46.1): add VIXRegimePlugin to I4 context layer"
```

---

## Task 4: CrossAssetContextPlugin

**Files:**
- Create: `src/intelligence/context/cross_asset_context.py`
- Create: `tests/unit/intelligence/test_cross_asset_context.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/intelligence/test_cross_asset_context.py`:
```python
"""Tests for CrossAssetContextPlugin — I4 macro context plugin."""
import pytest
from src.intelligence.context.cross_asset_context import CrossAssetContextPlugin


@pytest.fixture
def plugin():
    return CrossAssetContextPlugin()


def _xa_frame(ready: bool, active_pair: str = "ES_NQ",
               es_nq_spread_z: float = 1.5, es_rty_spread_z: float = -0.8,
               pairs_confirming: int = 2) -> dict:
    if not ready:
        return {"cross_asset": {"ready": False}}
    return {"cross_asset": {
        "ready": True,
        "active_pair": active_pair,
        "es_nq_spread_z": es_nq_spread_z,
        "es_rty_spread_z": es_rty_spread_z,
        "pairs_confirming": pairs_confirming,
    }}


def test_returns_eq_fields_when_ready_es_nq(plugin):
    frames = _xa_frame(ready=True, active_pair="ES_NQ", es_nq_spread_z=2.1, pairs_confirming=2)
    result = plugin.compute_full(frames)
    assert result["eq_spread_z"] == 2.1
    assert result["eq_pairs_confirming"] == 2.0


def test_returns_eq_fields_when_ready_es_rty(plugin):
    frames = _xa_frame(ready=True, active_pair="ES_RTY", es_rty_spread_z=-1.3, pairs_confirming=1)
    result = plugin.compute_full(frames)
    assert result["eq_spread_z"] == -1.3
    assert result["eq_pairs_confirming"] == 1.0


def test_returns_empty_when_not_ready(plugin):
    frames = _xa_frame(ready=False)
    assert plugin.compute_full(frames) == {}


def test_returns_empty_when_frame_absent(plugin):
    assert plugin.compute_full({}) == {}


def test_pairs_confirming_none_when_key_missing(plugin):
    """Missing pairs_confirming key → None, not 0.0 (0.0 is a valid count value)."""
    frames = {"cross_asset": {"ready": True, "active_pair": "ES_NQ",
                               "es_nq_spread_z": 1.0}}
    result = plugin.compute_full(frames)
    assert result["eq_pairs_confirming"] is None


def test_outputs_frozenset_correct(plugin):
    assert plugin.outputs == frozenset({"eq_spread_z", "eq_pairs_confirming"})


def test_name_follows_i4_convention(plugin):
    assert plugin.name == "ctx_CrossAssetContext"


def test_compute_next_delegates(plugin):
    frames = _xa_frame(ready=True)
    assert plugin.compute_next(frames) == plugin.compute_full(frames)
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/unit/intelligence/test_cross_asset_context.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement CrossAssetContextPlugin**

Create `src/intelligence/context/cross_asset_context.py`:
```python
"""Cross-asset EQ_INDEX context plugin — I4 macro context layer.

Reads cross_asset payload from frames["cross_asset"] (injected by
FeaturePipelineService for EQ_INDEX symbols only) and emits
eq_spread_z and eq_pairs_confirming into I4Context.

For non-EQ_INDEX symbols, FeaturePipelineService does not inject
frames["cross_asset"], so this plugin returns {} and I4Context
defaults eq_spread_z and eq_pairs_confirming to None.

Phase 49 segmentation requirement: ML training matrix MUST segment
on symbol group before using eq_* features. Training on non-EQ
symbols (where these fields are None) without segmentation produces
uninformative coefficients.

Note: CrossAssetDivergencePlugin (I7) continues to read the full
frames["cross_asset"] payload directly — it needs ~10 fields
(low_vol_flag, eq_vol_imbalance, eq_corr_break, etc.) that are
not captured here. These two consumers serve different purposes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..plugins import InputSpec


@dataclass
class CrossAssetContextPlugin:
    """I4 macro context: EQ_INDEX sector spread z-score and pair confirmation count.

    Reads frames["cross_asset"] injected by FeaturePipelineService.
    EQ_INDEX symbols only — all others see {} (→ None in I4Context).
    Returns {} when cross_asset data not ready.
    """

    name: str = "ctx_CrossAssetContext"
    outputs: frozenset[str] = frozenset({"eq_spread_z", "eq_pairs_confirming"})
    min_lookback: int = 1
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"context", "macro"})
    inputs: tuple[InputSpec, ...] = ()
    _state: dict = field(default_factory=dict)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        xa = frames.get("cross_asset") or {}
        if not xa.get("ready"):
            return {}

        active = xa.get("active_pair", "ES_NQ")
        spread_key = "es_nq_spread_z" if active == "ES_NQ" else "es_rty_spread_z"
        eq_spread_z = xa.get(spread_key)

        raw_pairs = xa.get("pairs_confirming")
        eq_pairs_confirming = float(raw_pairs) if raw_pairs is not None else None

        return {
            "eq_spread_z": eq_spread_z,
            "eq_pairs_confirming": eq_pairs_confirming,
        }

    def compute_next(self, windows: dict[str, Any]) -> dict[str, Any]:
        return self.compute_full(windows)


plugin = CrossAssetContextPlugin()
```

- [ ] **Step 4: Run tests to verify pass**

```bash
.venv/bin/pytest tests/unit/intelligence/test_cross_asset_context.py -v
```
Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/context/cross_asset_context.py tests/unit/intelligence/test_cross_asset_context.py
git commit -m "feat(46.1): add CrossAssetContextPlugin to I4 context layer"
```

---

## Task 5: Register both plugins in TIER_I4

**Files:**
- Modify: `src/intelligence/register_plugins.py`

- [ ] **Step 1: Add imports**

In `src/intelligence/register_plugins.py`, find the block of `context/` imports (around line 14–25). Add after the existing context imports:
```python
from .context.cross_asset_context import plugin as cross_asset_ctx_plugin
from .context.vix_regime import plugin as vix_regime_plugin
```

- [ ] **Step 2: Add to TIER_I4**

Find `TIER_I4` (line ~373). Add both new plugins at the end of the list:
```python
TIER_I4: list[str] = [
    vol_regime_plugin.name,
    trend_regime_plugin.name,
    momentum_ctx_plugin.name,
    garch_vol_plugin.name,
    hurst_plugin.name,
    shannon_plugin.name,
    kalman_trend_plugin.name,
    session_ctx_plugin.name,
    mtf_vol_plugin.name,
    anchored_vwap_plugin.name,
    volume_profile_plugin.name,
    vix_regime_plugin.name,           # Phase 46.1
    cross_asset_ctx_plugin.name,      # Phase 46.1
]
```

- [ ] **Step 3: Add to register_all_plugins()**

Find `register_all_plugins()` (line ~176). Locate where I4 plugins are registered (look for `garch_vol_plugin` or `hurst_plugin`). Add after the last existing I4 plugin registration:
```python
    registry.register(vix_regime_plugin)
    registry.register(cross_asset_ctx_plugin)
```

- [ ] **Step 4: Verify validate_tier passes**

```bash
.venv/bin/python -c "
from src.intelligence.register_plugins import register_all_plugins, TIER_I4
from src.intelligence.plugins import registry
register_all_plugins()
print('TIER_I4 count:', len(TIER_I4))
print('VIX plugin:', 'ctx_VIXRegime' in TIER_I4)
print('XA plugin:', 'ctx_CrossAssetContext' in TIER_I4)
"
```
Expected: `TIER_I4 count: 13`, both True.

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/register_plugins.py
git commit -m "feat(46.1): register VIXRegimePlugin and CrossAssetContextPlugin in TIER_I4"
```

---

## Task 6: Fix VIX frame injection TF in feature_pipeline_service

**Files:**
- Modify: `services/feature_pipeline_service.py`
- Modify: `tests/unit/service_tests/test_feature_pipeline_vix_injection.py`

- [ ] **Step 1: Write failing test for fixed TF**

In `tests/unit/service_tests/test_feature_pipeline_vix_injection.py`, add a new test (the file already exists from Phase 46):
```python
def test_vix_injection_uses_fixed_1h_tf_not_trading_tf(monkeypatch):
    """VIX regime context must use 1h bars regardless of the bar's trading TF.

    This is the Phase 46 data-quality fix: the same market moment must
    produce identical vix_z regardless of whether a 1m or 1h bar triggered
    the computation.
    """
    from services.feature_pipeline_service import VIX_REGIME_TF
    assert VIX_REGIME_TF == "1h"
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/unit/service_tests/test_feature_pipeline_vix_injection.py::test_vix_injection_uses_fixed_1h_tf_not_trading_tf -v
```
Expected: ImportError — `VIX_REGIME_TF` doesn't exist yet.

- [ ] **Step 3: Add VIX_REGIME_TF constant and fix injection**

In `services/feature_pipeline_service.py`:

After the `_OHLCV_FLUSH_INTERVAL` constant block (around line 111), add:
```python
# VIX regime context always uses 1h bars — fixed window regardless of trading TF.
# 20 × 1h = ~20 trading hours: captures session-scale fear elevation.
# Complementary to GARCH (multi-week structural vol regime).
VIX_REGIME_TF: str = "1h"
```

Find the VIX injection block in `_run_bar()` (around line 660):
```python
# BEFORE (broken — uses trading symbol's TF):
if self._vix_symbol:
    vix_deque = self._bar_history.get(self._vix_symbol, tf)
    frames["vix"] = compute_vix_context(vix_deque)
else:
    frames["vix"] = {"ready": False}
```

Replace with:
```python
# AFTER (fixed — always 1h VIX regardless of trading TF):
if self._vix_symbol:
    vix_deque = self._bar_history.get(self._vix_symbol, VIX_REGIME_TF)
    frames["vix"] = compute_vix_context(vix_deque)
else:
    frames["vix"] = {"ready": False}
```

- [ ] **Step 4: Run tests to verify pass**

```bash
.venv/bin/pytest tests/unit/service_tests/test_feature_pipeline_vix_injection.py -v
```
Expected: all tests PASS (including new one).

- [ ] **Step 5: Commit**

```bash
git add services/feature_pipeline_service.py tests/unit/service_tests/test_feature_pipeline_vix_injection.py
git commit -m "fix(46.1): VIX frame injection uses fixed VIX_REGIME_TF='1h' — fixes per-TF z-score defect"
```

---

## Task 7: Remove VIX/cross-asset pass-through from I6

**Files:**
- Modify: `src/intelligence/confluence/cross_timeframe.py`
- Modify: `tests/unit/test_cross_timeframe_confluence.py`

- [ ] **Step 1: Write failing test verifying I6 no longer emits VIX fields**

In `tests/unit/test_cross_timeframe_confluence.py`, add:
```python
def test_i6_does_not_emit_vix_or_eq_fields():
    """After Phase 46.1, I6 is pure cross-TF alignment — no VIX/EQ pass-through."""
    plugin = CrossTimeframeConfluencePlugin()
    assert "ctf_vix_level" not in plugin.outputs
    assert "ctf_vix_z" not in plugin.outputs
    assert "ctf_eq_spread_z" not in plugin.outputs
    assert "ctf_eq_pairs_confirming" not in plugin.outputs
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/unit/test_cross_timeframe_confluence.py::test_i6_does_not_emit_vix_or_eq_fields -v
```
Expected: FAIL — fields still present in `outputs` frozenset.

- [ ] **Step 3: Remove pass-through from CrossTimeframeConfluencePlugin**

In `src/intelligence/confluence/cross_timeframe.py`:

**Remove from `outputs` frozenset** (4 entries):
```python
# Remove these 4 lines from the frozenset:
"ctf_vix_level",
"ctf_vix_z",
"ctf_eq_spread_z",
"ctf_eq_pairs_confirming",
```

**Remove the comment and Phase 46 block** from `compute_full()`. Find and delete lines 126–165 (the block from `# Phase 46: VIX regime raw measurements` through the 4 field entries in the return dict):
```python
# DELETE this entire block:
# Phase 46: VIX regime raw measurements (D-16) — all symbols
vix = frames.get("vix", {})
if vix.get("ready"):
    ctf_vix_level = vix.get("level")
    ctf_vix_z = vix.get("z_score")
else:
    ctf_vix_level = None
    ctf_vix_z = None

# Phase 46: EQ_INDEX sector rotation raw measurements (D-15) — EQ_INDEX only
cross_asset = frames.get("cross_asset", {})
if cross_asset.get("ready"):
    active = cross_asset.get("active_pair", "ES_NQ")
    spread_key = "es_nq_spread_z" if active == "ES_NQ" else "es_rty_spread_z"
    ctf_eq_spread_z = cross_asset.get(spread_key)
    ctf_eq_pairs_confirming = float(cross_asset.get("pairs_confirming", 0))
else:
    ctf_eq_spread_z = None
    ctf_eq_pairs_confirming = None
```

**Remove from the return dict** the 4 Phase 46 field entries:
```python
# DELETE these 4 lines from the return dict:
"ctf_vix_level": ctf_vix_level,
"ctf_vix_z": ctf_vix_z,
"ctf_eq_spread_z": ctf_eq_spread_z,
"ctf_eq_pairs_confirming": ctf_eq_pairs_confirming,
```

Also remove the comment `# Phase 46: VIX and cross-asset fields (D-15, D-16) — None when data unavailable`.

- [ ] **Step 4: Remove stale assertions from existing tests**

In `tests/unit/test_cross_timeframe_confluence.py`, search for any assertions referencing `ctf_vix_level`, `ctf_vix_z`, `ctf_eq_spread_z`, `ctf_eq_pairs_confirming` and remove them. These were added in Phase 46 and are now invalid.

- [ ] **Step 5: Run I6 tests to verify**

```bash
.venv/bin/pytest tests/unit/test_cross_timeframe_confluence.py -v
```
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/intelligence/confluence/cross_timeframe.py tests/unit/test_cross_timeframe_confluence.py
git commit -m "refactor(46.1): remove VIX/cross-asset pass-through from I6 — I6 is pure cross-TF alignment again"
```

---

## Task 8: Rename capture_confluence_features → capture_signal_features

**Files:**
- Modify: `src/intelligence/trading/confidence_utils.py`
- Modify: all 36 `src/intelligence/trading/*.py` plugin files
- Rename/modify: `tests/unit/test_capture_confluence_features.py`

- [ ] **Step 1: Rename the function and update docstrings/keys in confidence_utils.py**

In `src/intelligence/trading/confidence_utils.py`:

**Update module docstring** (line 9): change:
```python
capture_confluence_features() captures I6 ctf_* scores and exhaustion state into
```
to:
```python
capture_signal_features() captures I4 macro context + I6 ctf_* scores + exhaustion
state into
```

**Rename the function** (line 91): change `def capture_confluence_features(` to `def capture_signal_features(`.

**Update function docstring** (around line 98): change:
```
Returns a standardized dict stored as signal["_shadow"] for ML training — zero confidence modification.
```
to:
```
Returns a standardized dict stored as signal["_shadow"] for ML training.
Shadow dict has 15 keys: 4 I4 macro context (vix_level, vix_z, eq_spread_z,
eq_pairs_confirming) + 7 I6 confluence + exhaustion (3 fields). Zero confidence modification.
```

**Rename 4 shadow dict keys** in the function body (lines ~123–128):
```python
# BEFORE:
"ctf_vix_level": features.get("ctf_vix_level"),
"ctf_vix_z": features.get("ctf_vix_z"),
"ctf_eq_spread_z": features.get("ctf_eq_spread_z"),
"ctf_eq_pairs_confirming": features.get("ctf_eq_pairs_confirming"),

# AFTER:
"vix_level": features.get("vix_level"),
"vix_z": features.get("vix_z"),
"eq_spread_z": features.get("eq_spread_z"),
"eq_pairs_confirming": features.get("eq_pairs_confirming"),
```

- [ ] **Step 2: Update all 36 I7 plugin import lines**

Run this sed command to update all 36 import lines in one shot:
```bash
cd /home/bg/dev/indicagent
sed -i 's/from \.confidence_utils import capture_confluence_features/from .confidence_utils import capture_signal_features/g' src/intelligence/trading/*.py
```

Then rename all call sites:
```bash
sed -i 's/capture_confluence_features(/capture_signal_features(/g' src/intelligence/trading/*.py
```

Verify no old name remains:
```bash
grep -r "capture_confluence_features" src/intelligence/trading/
```
Expected: no output (zero matches).

- [ ] **Step 3: Update the test file**

Rename the test file:
```bash
mv tests/unit/test_capture_confluence_features.py tests/unit/test_capture_signal_features.py
```

In the renamed file, update:
- All imports: `capture_confluence_features` → `capture_signal_features`
- All call sites: same rename
- Shadow dict key assertions: `ctf_vix_level` → `vix_level`, `ctf_vix_z` → `vix_z`, `ctf_eq_spread_z` → `eq_spread_z`, `ctf_eq_pairs_confirming` → `eq_pairs_confirming`
- Any comment or docstring references to the old name

- [ ] **Step 4: Run tests to verify**

```bash
.venv/bin/pytest tests/unit/test_capture_signal_features.py -v
```
Expected: all tests PASS.

```bash
.venv/bin/pytest tests/unit/intelligence/ -q --tb=short
```
Expected: all pass (new plugin tests included).

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/trading/ tests/unit/test_capture_signal_features.py
git commit -m "refactor(46.1): rename capture_confluence_features→capture_signal_features; update I4 shadow keys"
```

---

## Task 9: Final verification

- [ ] **Step 1: Run full test suite**

```bash
.venv/bin/pytest tests/unit/ -q --tb=short 2>&1 | tail -10
```
Expected: ≥2716 tests PASS (regression baseline), 0 failures.

- [ ] **Step 2: Verify all 9 spec criteria**

```bash
# 1. VIXRegimePlugin in TIER_I4
.venv/bin/python -c "from src.intelligence.register_plugins import TIER_I4; assert 'ctx_VIXRegime' in TIER_I4; print('✓ VIXRegimePlugin in TIER_I4')"

# 2. CrossAssetContextPlugin in TIER_I4
.venv/bin/python -c "from src.intelligence.register_plugins import TIER_I4; assert 'ctx_CrossAssetContext' in TIER_I4; print('✓ CrossAssetContextPlugin in TIER_I4')"

# 3+4. I4Context +4 / I6Confluence -4
.venv/bin/python -c "
from src.intelligence.schemas import I4Context, I6Confluence
assert hasattr(I4Context(), 'vix_level'), 'I4 missing vix_level'
assert hasattr(I4Context(), 'eq_spread_z'), 'I4 missing eq_spread_z'
assert not hasattr(I6Confluence(), 'ctf_vix_level'), 'I6 still has ctf_vix_level'
print('✓ Schema changes correct')
"

# 5. VIX injection uses fixed TF
.venv/bin/python -c "from services.feature_pipeline_service import VIX_REGIME_TF; assert VIX_REGIME_TF == '1h'; print('✓ VIX_REGIME_TF=1h')"

# 6. CROSS_ASSET_VALID_TFS in service_utils only
.venv/bin/python -c "from src.core.service_utils import CROSS_ASSET_VALID_TFS; print('✓ CROSS_ASSET_VALID_TFS in service_utils')"
grep -r "_CROSS_ASSET_VALID_TFS\s*=" services/ && echo "FAIL: local constant still exists" || echo "✓ No local CROSS_ASSET_VALID_TFS"

# 7. capture_signal_features is the name
.venv/bin/python -c "from src.intelligence.trading.confidence_utils import capture_signal_features; print('✓ capture_signal_features exists')"
python -c "from src.intelligence.trading.confidence_utils import capture_confluence_features" 2>&1 | grep -q "ImportError" && echo "✓ Old name gone" || echo "FAIL: old name still importable"

# 8. No old function name in trading plugins
grep -r "capture_confluence_features" src/intelligence/trading/ && echo "FAIL: old name found" || echo "✓ All 36 callers updated"
```

- [ ] **Step 3: Run ruff lint**

```bash
.venv/bin/ruff check src/intelligence/context/vix_regime.py src/intelligence/context/cross_asset_context.py src/intelligence/trading/confidence_utils.py --fix
```
Expected: no errors.

- [ ] **Step 4: Final commit if any lint fixes applied**

```bash
git add -p && git commit -m "style(46.1): ruff fixes after gap closure"
```
(Only commit if there were actual changes from ruff.)
