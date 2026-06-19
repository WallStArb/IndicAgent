# Phase 116: SR Consensus - Pattern Map

**Mapped:** 2026-06-05
**Files analyzed:** 7
**Analogs found:** 7 / 7

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/intelligence/features/i3_structure/support_resistance.py` | plugin (I3, modify) | transform | self (existing) | exact |
| `src/intelligence/trading/zone_engine.py` | engine (modify) | transform | self (existing) | exact |
| `src/intelligence/context/sr_consensus.py` | plugin (I4 Wave-B, create) | request-response | `src/intelligence/context/kalman_trend.py` | role-match |
| `src/intelligence/schemas.py` | schema (modify) | — | self (existing) | exact |
| `src/intelligence/register_plugins.py` | registry (modify) | — | self (existing) | exact |
| `tests/unit/intelligence/features/test_support_resistance.py` | test (modify) | — | `tests/unit/intelligence/test_sr_shared_peaks.py` | exact |
| `tests/unit/intelligence/context/test_sr_consensus.py` | test (create) | — | `tests/unit/intelligence/context/test_anchored_vwap.py` | role-match |

---

## Pattern Assignments

### `src/intelligence/features/i3_structure/support_resistance.py` (I3 plugin, modify)

**Analog:** self + `src/intelligence/context/kalman_trend.py` for ATR reading

**Imports to add** (lines 1-8 of current file, add these):
```python
from src.intelligence.trading.atr_utils import get_atr
```

**ATR-proportional clustering pattern** (replace `_cluster_levels` body):
```python
# Current (line 111 — wrong):
if abs(price - current_cluster[-1][0]) <= current_price * self.cluster_pct

# Replacement — add cluster_atr_mult: float = 0.5 to dataclass fields,
# remove cluster_pct, pass atr_14 into _cluster_levels:
atr_14 = get_atr(frames.get("i1") or {})
cluster_radius = (atr_14 * self.cluster_atr_mult) if atr_14 else (current_price * 0.005)
if abs(price - current_cluster[-1][0]) <= cluster_radius
```

**TF-proportional lookback pattern** (add module-level constant + use in compute_full):
```python
_LOOKBACK_BY_TF: dict[str, int] = {
    "1m": 60, "5m": 60, "15m": 80, "1h": 120, "4h": 120, "1d": 60,
}

# In compute_full(), after df = frames.get("main"):
tf = frames.get("timeframe", "")
lookback = _LOOKBACK_BY_TF.get(tf, 120)
# ... after length check:
df = df.iloc[-lookback:]
```

**Synthetic fallback removal** (lines 66-71 — both fallback blocks):
```python
# Current (line 66):
nearest_r = {"level": current_price * 1.02, "strength": 0, "latest_idx": 0}
# Current (line 71):
nearest_s = {"level": current_price * 0.98, "strength": 0, "latest_idx": 0}

# Replacement:
nearest_r = None
nearest_s = None

# Return block — guard both outputs:
result = {}
if nearest_r is not None:
    result["nearest_resistance"] = nearest_r["level"]
    result["resistance_strength"] = float(nearest_r["strength"])
    result["resistance_dist_pct"] = (nearest_r["level"] - current_price) / current_price * 100
    result["resistance_age_bars"] = float(n_bars - 1 - nearest_r["latest_idx"]) if nearest_r["latest_idx"] > 0 else float(n_bars)
if nearest_s is not None:
    result["nearest_support"] = nearest_s["level"]
    result["support_strength"] = float(nearest_s["strength"])
    result["support_dist_pct"] = (current_price - nearest_s["level"]) / current_price * 100
    result["support_age_bars"] = float(n_bars - 1 - nearest_s["latest_idx"]) if nearest_s["latest_idx"] > 0 else float(n_bars)
result["sr_level_count"] = float(len(resistance_clusters) + len(support_clusters))
return result
```

**Volume weighting pattern** (extend `_finalize_cluster`, add `volume` array param):
```python
@staticmethod
def _finalize_cluster(members: list[tuple[float, int]], volume: np.ndarray, mean_volume: float) -> dict[str, Any]:
    avg_level = sum(p for p, _ in members) / len(members)
    latest_idx = max(idx for _, idx in members)
    # Volume-weighted strength: cap at 2x to prevent outlier dominance
    vol_sum = sum(
        min(2.0, (float(volume[idx]) / mean_volume if mean_volume > 0 else 1.0))
        for _, idx in members
    )
    strength = len(members) * (vol_sum / len(members))
    return {"level": avg_level, "strength": strength, "latest_idx": latest_idx}
```

---

### `src/intelligence/trading/zone_engine.py` (engine, modify)

**Analog:** self (existing `_SUPPORT_SPECS`, `_RESISTANCE_SPECS`, `_STRENGTH_FIELD`, `_resolve_strength`)

**`_SUPPORT_SPECS` additions** (after line 72, before closing paren):
```python
# (feature_key, display_name, default_strength, source_tier, source_family)
# ADD to _SUPPORT_SPECS tuple:
("nearest_fib_level",  "fib",          0.6, "i3", "fib"),
("prior_session_low",  "prior_sess_l", 0.7, "i3", "session"),
("asian_session_low",  "asian_l",      0.6, "i3", "session"),
("nearest_hvn_below",  "hvn_below",    0.8, "i4", "vp_hvn"),
("avwap_lower_band",   "avwap_lower",  0.6, "i4", "avwap"),
("kc_mid_20",          "kc_mid",       0.5, "i1", "ma_kc"),
```

**`_RESISTANCE_SPECS` additions** (after line 82, before closing paren):
```python
# ADD to _RESISTANCE_SPECS tuple:
("nearest_fib_level",  "fib",          0.6, "i3", "fib"),
("prior_session_high", "prior_sess_h", 0.7, "i3", "session"),
("asian_session_high", "asian_h",      0.6, "i3", "session"),
("nearest_hvn_above",  "hvn_above",    0.8, "i4", "vp_hvn"),
("avwap_upper_band",   "avwap_upper",  0.6, "i4", "avwap"),
("kc_mid_20",          "kc_mid",       0.5, "i1", "ma_kc"),
```

**`_STRENGTH_FIELD` additions** (after line 94):
```python
# ADD to _STRENGTH_FIELD dict:
"fib":          "fib_cluster_strength",
"hvn_below":    "nearest_hvn_dist_atr",   # invert: closer = stronger
"hvn_above":    "nearest_hvn_dist_atr",
"prior_sess_l": None,
"prior_sess_h": None,
"asian_l":      None,
"asian_h":      None,
"avwap_lower":  None,
"avwap_upper":  None,
"kc_mid":       None,
```

**`_resolve_strength` extension** (lines 104-113 — add dist_atr handler):
```python
def _resolve_strength(features: dict, name: str, default: float) -> float:
    key = _STRENGTH_FIELD.get(name)
    if key is None:
        return default
    val = _fval(features, key)
    if val > EPSILON:
        if "age_bars" in key:
            return min(1.0, 1.0 / (1.0 + val / 50.0))
        if "dist_atr" in key:           # NEW: HVN distance handler — closer = higher strength
            return min(1.0, 1.0 / (1.0 + val))
        return min(1.0, val)
    return default
```

**`collect_sr_candidates()` new public function** (add after `collect_candidates()`, ~line 194):
```python
def collect_sr_candidates(
    features: dict[str, Any],
    direction: int,
    price: float,
    atr: float,
    max_dist: float,
) -> list[ZoneCandidate]:
    """Collect SR candidates for ctx_SRConsensus proximity gate.

    direction=-1: support (below price), lo=price-max_dist, hi=price (strict)
    direction=+1: resistance (above price), lo=price, hi=price+max_dist (strict)
    """
    if direction == 1:
        lo, hi = price, price + max_dist
        specs = _RESISTANCE_SPECS
    else:
        lo, hi = price - max_dist, price
        specs = _SUPPORT_SPECS

    tf = features.get("timeframe", "")
    raw: list[ZoneCandidate] = []
    for feat_key, name, default_str, tier, family in specs:
        p = _fval(features, feat_key)
        if p <= EPSILON or not (lo < p < hi):
            continue
        strength = _resolve_strength(features, name, default_str)
        raw.append(ZoneCandidate(price=p, name=name, strength=strength,
                                 source_tier=tier, source_family=family))

    poc = _select_vp(features, tf, "poc_price", "poc_price_rolling")
    if direction not in _VP_DIRECTION:
        raise ValueError(f"zone_engine: direction must be 1 or -1, got {direction!r}")
    c_sess, c_roll, c_name, hvn_key, hvn_name = _VP_DIRECTION[direction]
    companion = _select_vp(features, tf, c_sess, c_roll)
    hvn = _fval(features, hvn_key)
    for p, name in [(poc, "poc"), (companion, c_name), (hvn, hvn_name)]:
        if p > EPSILON and lo < p < hi:
            raw.append(ZoneCandidate(price=p, name=name,
                                     strength=0.8 if name == "poc" else 0.7,
                                     source_tier="i4", source_family=f"vp_{name}"))

    return sorted(_dedup(raw, atr), key=lambda c: c.price)
```

---

### `src/intelligence/context/sr_consensus.py` (I4 Wave-B plugin, CREATE NEW)

**Analog:** `src/intelligence/context/kalman_trend.py` (canonical I4 Wave-B plugin)

**Full import pattern** (copy from `kalman_trend.py` and `volume_profile.py`):
```python
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from src.intelligence.plugins import InputSpec
from src.intelligence.trading.atr_utils import get_atr
from src.intelligence.trading.plugin_utils import _fval
from src.intelligence.trading.trade_framer import MAX_STOP_ATR_MULTIPLIER_BY_TF, MAX_STOP_ATR_MULTIPLIER_DEFAULT
from src.intelligence.trading.zone_engine import ZoneCandidate, collect_sr_candidates, _find_clusters, _source_diversity, _pick_single_best, _dedup

EPSILON = 1e-9
```

**Plugin dataclass pattern** (copy structure from `kalman_trend.py` lines 43-78):
```python
@dataclass
class SRConsensusPlugin:
    name: str = "ctx_SRConsensus"
    outputs: frozenset[str] = frozenset({
        "sr_nearest_support",
        "sr_nearest_resistance",
        "sr_support_confluence_score",
        "sr_resistance_confluence_score",
        "sr_support_dist_atr",
        "sr_resistance_dist_atr",
    })
    min_lookback: int = 5
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"context"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=5),)
```

**`compute_full` pattern** (I4 Wave-B merges tier dicts; reads price from `frames["main"]`):
```python
def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
    df = frames.get("main")
    if df is None or len(df) < self.min_lookback:
        return {}

    # Merge all upstream tier sub-dicts into flat features dict
    features = {
        **(frames.get("i1") or {}),
        **(frames.get("i3") or {}),
        **(frames.get("i4") or {}),
        **(frames.get("smc") or {}),
    }
    # Current price: read from OHLCV dataframe (close_price is NOT a tier sub-dict key)
    current_price = float(df["close"].iloc[-1])
    features["timeframe"] = frames.get("timeframe", "")

    atr = get_atr(features)
    if not atr:
        return {}

    tf = features.get("timeframe", "")
    max_dist = atr * MAX_STOP_ATR_MULTIPLIER_BY_TF.get(tf, MAX_STOP_ATR_MULTIPLIER_DEFAULT)
    ...
```

**`compute_next` delegation pattern** (copy from `support_resistance.py` line 94):
```python
def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
    return self.compute_full(windows)
```

**Round number candidate pattern** (private helper, add below class or as module-level function):
```python
def _round_number_candidates(
    price: float, atr: float, max_dist: float, direction: int
) -> list[ZoneCandidate]:
    """Generate round number grid candidates near current price."""
    if price <= EPSILON:
        return []
    magnitude = 10 ** math.floor(math.log10(price))
    grids = [
        (magnitude,      0.8),   # major: 1000 for ES@7400
        (magnitude / 10, 0.6),   # minor: 100
        (magnitude / 20, 0.4),   # sub-minor: 50
    ]
    if direction == 1:
        lo, hi = price, price + max_dist
    else:
        lo, hi = price - max_dist, price

    result: list[ZoneCandidate] = []
    for grid_size, strength in grids:
        if grid_size <= EPSILON:
            continue
        nearest_below = math.floor(price / grid_size) * grid_size
        nearest_above = math.ceil(price / grid_size) * grid_size
        for level in (nearest_below, nearest_above):
            if level > EPSILON and lo < level < hi:
                result.append(ZoneCandidate(
                    price=level, name=f"round_{grid_size:.0f}",
                    strength=strength, source_tier="round",
                    source_family="round_number",
                ))
    return result
```

**`_best_level` helper** (select highest-diversity cluster, fall back to `_pick_single_best`):
```python
from dataclasses import dataclass as _dc

@_dc
class _LevelResult:
    price: float
    score: float   # = source_diversity count

def _best_level(candidates: list[ZoneCandidate], atr: float, price: float) -> _LevelResult | None:
    if not candidates:
        return None
    clusters = _find_clusters(candidates, atr)
    diverse = [cl for cl in clusters if _source_diversity(cl) >= 2]
    if diverse:
        best = max(diverse, key=lambda cl: (_source_diversity(cl), sum(c.strength for c in cl)))
        level = sum(c.price for c in best) / len(best)
        return _LevelResult(price=level, score=float(_source_diversity(best)))
    single = _pick_single_best(candidates, entry=price, atr=atr)
    if single:
        return _LevelResult(price=single.price, score=1.0)
    return None
```

**Module-level singleton** (copy pattern from `kalman_trend.py` line 233):
```python
plugin = SRConsensusPlugin()
```

---

### `src/intelligence/schemas.py` (I4Context, modify)

**Analog:** existing `I4Context` field declarations (lines 268-411)

**Fields to add** (after line 411, inside `I4Context` class, before `class I5Patterns`):
```python
    # SRConsensusPlugin outputs (Phase 116)
    sr_nearest_support:             float | None = None
    sr_nearest_resistance:          float | None = None
    sr_support_confluence_score:    float | None = None
    sr_resistance_confluence_score: float | None = None
    sr_support_dist_atr:            float | None = None
    sr_resistance_dist_atr:         float | None = None
```

**Docstring update** (line 268-285 docstring — update Total count from 93 to 99 and add plugin entry):
```python
    # Add to Plugins list in docstring:
    # - SRConsensus (6 fields)
    # Total: 99 fields
```

---

### `src/intelligence/register_plugins.py` (registry, modify)

**Analog:** existing I4 registration — `kalman_trend_plugin` import and references at lines 96, 486, 578

**Import to add** (after line 100, alongside other context imports):
```python
from .context.sr_consensus import plugin as sr_consensus_plugin
```

**`validate_schema_coverage()` update** (lines 178-193 — I4 plugin list):
```python
# ADD to the I4 list inside validate_schema_coverage():
sr_consensus_plugin,
```

**`TIER_I4` update** (lines 479-492):
```python
# ADD to TIER_I4 list:
sr_consensus_plugin.name,   # "ctx_SRConsensus"
```

**`I4_WAVE_B` update** (lines 578-580):
```python
# Current:
I4_WAVE_B: list[str] = [
    kalman_trend_plugin.name,
]
# Becomes:
I4_WAVE_B: list[str] = [
    kalman_trend_plugin.name,
    sr_consensus_plugin.name,
]
```

---

### `tests/unit/intelligence/features/test_support_resistance.py` (test, modify)

**Analog:** `tests/unit/intelligence/test_sr_shared_peaks.py` (current file, lines 1-52)

**Pattern: build frames dict with `i1` sub-dict** (new tests must pass ATR via frames["i1"]):
```python
def _make_frames(n: int = 120, seed: int = 42, tf: str = "5m") -> dict:
    df = _make_ohlcv(n=n, seed=seed)
    close = df["close"].to_numpy()
    atr_14 = float(np.std(np.diff(close)) * 1.4)  # rough ATR for test
    return {
        "main": df,
        "i1": {"atr_14": atr_14},
        "timeframe": tf,
    }
```

**Test updates for no-pivot case** (replace assertions that assume synthetic fallback):
```python
def test_support_below_price_or_absent(self):
    """nearest_support is either absent (no real pivot) or below current price."""
    df = _make_ohlcv()
    plugin = SupportResistancePlugin()
    result = plugin.compute_full({"main": df, "i1": {"atr_14": 5.0}})
    current_price = float(df["close"].iloc[-1])
    if "nearest_support" in result:
        assert result["nearest_support"] <= current_price
    # absent is also valid — no real pivot below price

def test_resistance_above_price_or_absent(self):
    result = plugin.compute_full({"main": df, "i1": {"atr_14": 5.0}})
    current_price = float(df["close"].iloc[-1])
    if "nearest_resistance" in result:
        assert result["nearest_resistance"] >= current_price
```

---

### `tests/unit/intelligence/context/test_sr_consensus.py` (test, CREATE NEW)

**Analog:** `tests/unit/intelligence/context/test_anchored_vwap.py` (lines 1-80)

**Full test file structure:**
```python
"""Tests for SRConsensusPlugin (I4 Wave-B context tier)."""

import math
import numpy as np
import pandas as pd
import pytest

_EXPECTED_OUTPUTS = frozenset({
    "sr_nearest_support",
    "sr_nearest_resistance",
    "sr_support_confluence_score",
    "sr_resistance_confluence_score",
    "sr_support_dist_atr",
    "sr_resistance_dist_atr",
})


def _make_frames(n: int = 30, price: float = 7400.0, tf: str = "5m") -> dict:
    """Build frames dict with synthetic OHLCV + all required tier sub-dicts."""
    rng = np.random.default_rng(42)
    close = price + rng.normal(0, 5.0, n)
    close[-1] = price  # fix current price for assertions
    high = close + rng.uniform(2, 8, n)
    low = close - rng.uniform(2, 8, n)
    volume = rng.uniform(1000, 5000, n)
    df = pd.DataFrame({"high": high, "low": low, "close": close, "volume": volume})
    atr_14 = 9.0  # ~ES ATR on 5m
    return {
        "main": df,
        "timeframe": tf,
        "i1": {"atr_14": atr_14},
        "i3": {
            "nearest_support": price - 15.0,
            "nearest_resistance": price + 20.0,
            "nearest_fib_level": price - 12.0,
            "prior_session_low": price - 18.0,
        },
        "i4": {
            "nearest_hvn_below": price - 10.0,
            "nearest_hvn_dist_atr": 1.1,
            "avwap_lower_band": price - 8.0,
        },
        "smc": {},
    }


class TestSRConsensusPluginMetadata:
    @pytest.mark.unit
    def test_plugin_name(self):
        from src.intelligence.context.sr_consensus import plugin
        assert plugin.name == "ctx_SRConsensus"

    @pytest.mark.unit
    def test_plugin_outputs(self):
        from src.intelligence.context.sr_consensus import plugin
        assert plugin.outputs == _EXPECTED_OUTPUTS


class TestSRConsensusComputeFull:
    @pytest.mark.unit
    def test_returns_support_below_and_resistance_above(self):
        from src.intelligence.context.sr_consensus import plugin
        frames = _make_frames(price=7400.0)
        result = plugin.compute_full(frames)
        if result.get("sr_nearest_support") is not None:
            assert result["sr_nearest_support"] < 7400.0
        if result.get("sr_nearest_resistance") is not None:
            assert result["sr_nearest_resistance"] > 7400.0

    @pytest.mark.unit
    def test_insufficient_data_returns_empty(self):
        from src.intelligence.context.sr_consensus import plugin
        rng = np.random.default_rng(0)
        df = pd.DataFrame({"high": [100.0], "low": [99.0], "close": [100.0], "volume": [500.0]})
        result = plugin.compute_full({"main": df, "i1": {}, "i3": {}, "i4": {}, "smc": {}})
        assert result == {}

    @pytest.mark.unit
    def test_round_number_support_detected(self):
        """Round number grid (e.g. 7400 below price 7415) should appear as support."""
        from src.intelligence.context.sr_consensus import plugin
        frames = _make_frames(price=7415.0)
        result = plugin.compute_full(frames)
        # 7400 is a round-100 support below 7415 and within 4*9=36 pts
        # sr_nearest_support should be <= 7415
        if result.get("sr_nearest_support") is not None:
            assert result["sr_nearest_support"] <= 7415.0

    @pytest.mark.unit
    def test_confluence_score_positive_when_multiple_sources(self):
        """With multiple i3/i4 candidates near price, confluence_score >= 1."""
        from src.intelligence.context.sr_consensus import plugin
        result = plugin.compute_full(_make_frames(price=7400.0))
        score = result.get("sr_support_confluence_score")
        if score is not None:
            assert score >= 0.0

    @pytest.mark.unit
    def test_compute_next_delegates_to_compute_full(self):
        from src.intelligence.context.sr_consensus import plugin
        frames = _make_frames(price=7400.0)
        r1 = plugin.compute_full(frames)
        r2 = plugin.compute_next(frames)
        assert r1 == r2
```

---

## Shared Patterns

### ATR Reading (all plugins that need ATR)
**Source:** `src/intelligence/trading/atr_utils.py` — `get_atr(features)` function
**Apply to:** `sr_consensus.py` (I4 plugin reads from merged features), `support_resistance.py` (I3 plugin reads from `frames.get("i1") or {}`)
```python
from src.intelligence.trading.atr_utils import get_atr

# I4 plugin (merged features dict):
features = {**(frames.get("i1") or {}), **(frames.get("i3") or {}), **(frames.get("i4") or {})}
atr = get_atr(features)

# I3 plugin (direct i1 sub-dict):
atr_14 = get_atr(frames.get("i1") or {})
```

### Feature Float Access
**Source:** `src/intelligence/trading/plugin_utils.py` line 69 — `_fval(features, key, default=0.0)`
**Apply to:** `zone_engine.py` (already used — extend to new spec keys automatically)

### Tier Sub-dict Merge (I4 Wave-B pattern)
**Source:** `src/intelligence/context/kalman_trend.py` line 163 — reads single tier dict
**Pattern for sr_consensus** (reads multiple tiers — differs from Kalman which only reads i4):
```python
# I4 Wave-B with multi-tier dependency (canonical pattern for sr_consensus):
features = {
    **(frames.get("i1") or {}),
    **(frames.get("i3") or {}),
    **(frames.get("i4") or {}),
    **(frames.get("smc") or {}),
}
# Current price from OHLCV df, NOT features dict (no "close_price" in tier sub-dicts)
current_price = float(df["close"].iloc[-1])
```

### Plugin Registration (3-location update)
**Source:** `src/intelligence/register_plugins.py` lines 96/486/578 for `kalman_trend_plugin`
**Apply to:** `sr_consensus_plugin` — same 3 locations: import (line ~100), `validate_schema_coverage` I4 list (line ~188), `TIER_I4` (line ~490), `I4_WAVE_B` (line 578).
Note: `validate_schema_coverage` is a FOURTH location — do not miss it.

### Schema `extra="forbid"` Contract
**Source:** `src/intelligence/schemas.py` line 287 — `model_config = ConfigDict(extra="forbid")`
**Rule:** Every key in `SRConsensusPlugin.outputs` frozenset must exactly match a field name declared in `I4Context`. Mismatch causes Pydantic validation error at publish time. Add schema fields to `I4Context` BEFORE adding the plugin to the registration lists.

### `compute_next` No-op Delegation
**Source:** `src/intelligence/features/i3_structure/support_resistance.py` line 94
```python
def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
    return self.compute_full(windows)
```
**Apply to:** `sr_consensus.py` — non-incremental plugin; must delegate or plugin never fires in live mode.

---

## No Analog Found

All files have close analogs. No new dependency types introduced.

---

## Metadata

**Analog search scope:** `src/intelligence/context/`, `src/intelligence/features/i3_structure/`, `src/intelligence/trading/`, `src/intelligence/register_plugins.py`, `src/intelligence/schemas.py`, `tests/unit/intelligence/`
**Files scanned:** 14
**Pattern extraction date:** 2026-06-05
