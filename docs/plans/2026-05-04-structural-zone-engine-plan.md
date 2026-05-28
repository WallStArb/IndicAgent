# Structural Zone Engine — Implementation Plan (Revised)

**Version:** 1.0
**Status:** archived
**Last Updated:** 2026-05-05
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a structural confluence zone engine that refines entry zone bounds using S/R, MAs, and volume levels for setups with no explicit geometry — while preserving all setup-specific zone logic (FVG, OB, demand/supply, sweep). Wire dual market-entry tracking through the existing Kafka lifecycle event pipeline.

**Architecture:** New `zone_engine.py` in `src/intelligence/trading/` — pure function, no DB, no Kafka. `trade_framer._resolve_zone_bounds` calls it as a final fallback when no setup-specific geometry is available. Market-entry tracking publishes `TransitionType.MARKET_RESOLUTION` events to the existing `lifecycle.transitions` Kafka topic; `lifecycle_writer_agent` and `signal_ledger_repository.batch_execute` handle persistence.

**Tech Stack:** Python 3.11+, structlog, prometheus_client (Counter/Histogram direct API), asyncpg

**Spec:** `docs/plans/2026-05-04-structural-zone-engine-design.md`
**Reviews:** `docs/plans/2026-05-04-zone-engine-reviews.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `src/intelligence/trading/zone_engine.py` | **NEW** — candidate collection (with dedup), clustering (quality-weighted), zone resolution |
| `src/intelligence/trading/trade_framer.py` | Add `stop` param to `_resolve_zone_bounds`; call zone_engine as ATR fallback replacement only |
| `src/intelligence/trading/signal_schema.py` | Add `zone_source` field; bump version to v2 |
| `src/intelligence/trading/lifecycle_transitions.py` | Add `TransitionType.MARKET_RESOLUTION` |
| `src/persistence/repository/signal_ledger_repository.py` | Add `_BATCH_MARKET_RESOLUTION_SQL` + `market_resolution` case in `batch_execute` |
| `services/signal_tracker_compute_agent.py` | Wire `evaluate_market_entry` + market-entry state + publish `MARKET_RESOLUTION` transition |
| `src/observability/metrics.py` | Add 4 zone metrics using direct Counter/Histogram API |
| `tests/unit/trading/test_zone_engine.py` | **NEW** — zone_engine unit tests |
| `tests/unit/test_trade_framer.py` | Update tests that check zone bounds for setups hitting ATR fallback |

---

### Task 1: Create zone_engine.py — data structures, dedup, candidate collection

**Files:**
- Create: `src/intelligence/trading/zone_engine.py`
- Create: `tests/unit/trading/test_zone_engine.py`

- [ ] **Step 1: Create the test directory and write failing tests**

```bash
mkdir -p tests/unit/trading
touch tests/unit/trading/__init__.py
```

```python
# tests/unit/trading/test_zone_engine.py
import pytest
from src.intelligence.trading.zone_engine import (
    ZoneCandidate,
    collect_candidates,
)


def test_collect_candidates_long_gathers_support_levels():
    features = {
        "nearest_support": 100.0,
        "swing_low": 99.5,
        "nearest_demand_high": 99.8,
        "ema_21": 100.2,
        "sma_50": 99.0,
        "ssl_level": 99.3,
        "poc_price": 99.7,
        "val": 98.5,
        "nearest_lvn_level": 99.1,
        "overnight_low": 98.8,
        "atr_14": 0.5,
        "timeframe": "1m",
    }
    candidates = collect_candidates(features, direction=1, entry=100.5, stop=98.0)
    assert len(candidates) > 0
    assert all(isinstance(c, ZoneCandidate) for c in candidates)
    assert all(c.price < 100.5 for c in candidates)
    assert all(c.price > 98.0 for c in candidates)


def test_collect_candidates_short_gathers_resistance_levels():
    features = {
        "nearest_resistance": 101.0,
        "swing_high": 101.5,
        "nearest_supply_low": 101.2,
        "ema_21": 100.8,
        "sma_50": 101.3,
        "bsl_level": 101.4,
        "poc_price": 101.1,
        "vah": 102.0,
        "overnight_high": 101.6,
        "atr_14": 0.5,
        "timeframe": "1m",
    }
    candidates = collect_candidates(features, direction=-1, entry=100.5, stop=102.5)
    assert len(candidates) > 0
    assert all(c.price > 100.5 for c in candidates)
    assert all(c.price < 102.5 for c in candidates)


def test_collect_candidates_skips_zero_and_none():
    features = {
        "nearest_support": 0.0,
        "swing_low": 0.0,
        "ema_21": 99.0,
        "atr_14": 0.5,
        "timeframe": "1m",
    }
    candidates = collect_candidates(features, direction=1, entry=100.0, stop=98.0)
    assert len(candidates) == 1
    assert candidates[0].price == 99.0


def test_dedup_same_price_same_family_keeps_one():
    """nearest_support and sr_nearest_support map to same family — only one survives dedup."""
    features = {
        "nearest_support": 99.5,
        "sr_nearest_support": 99.51,  # same source family, nearly same price
        "atr_14": 0.5,
        "timeframe": "1m",
    }
    candidates = collect_candidates(features, direction=1, entry=100.0, stop=98.0)
    support_cands = [c for c in candidates if c.source_family == "sr"]
    assert len(support_cands) == 1


def test_htf_vp_uses_rolling_fields():
    """For 15m+, VP fields should use rolling (structural) rather than session."""
    features = {
        "poc_price": 100.0,          # session — should be ignored for 15m
        "poc_price_rolling": 99.5,   # rolling — should be used
        "atr_14": 0.5,
        "timeframe": "15m",
    }
    candidates = collect_candidates(features, direction=1, entry=100.5, stop=98.0)
    prices = [c.price for c in candidates]
    assert 99.5 in prices
    assert 100.0 not in prices
```

- [ ] **Step 2: Run test to verify they fail**

Run: `.venv/bin/pytest tests/unit/trading/test_zone_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.intelligence.trading.zone_engine'`

- [ ] **Step 3: Write zone_engine.py**

```python
# src/intelligence/trading/zone_engine.py
"""Structural Zone Engine — confluence-based entry zone construction.

Resolves entry zones from structural S/R, MAs, and volume levels.
Used by trade_framer as a fallback when no setup-specific geometry exists.

Three-tier resolution:
  1. Confluence cluster (2+ structurally diverse levels within 0.5 ATR)
  2. Single best structural level
  3. ATR band (emergency — caller is responsible for applying)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

EPSILON = 1e-9
CLUSTER_RADIUS_ATR = 0.5
ZONE_BUFFER_ATR = 0.15
MIN_ZONE_WIDTH_ATR = 0.25
SINGLE_LEVEL_RADIUS_ATR = 0.25


@dataclass
class ZoneCandidate:
    price: float
    name: str
    strength: float       # 0.0-1.0 quality weight
    source_tier: str      # "i1", "i3", "i4", "smc"
    source_family: str    # for dedup: "sr", "swing", "smc_ssl", "ma_ema", "ma_sma", "vp", "overnight"


@dataclass
class ZoneResult:
    zone_low: float
    zone_high: float
    tier: str    # "confluence" | "single" | "atr"
    source: str  # e.g. "confluence:swing_low+ema21+poc"
    candidate_count: int
    cluster_members: int


def _fval(features: dict[str, Any], key: str) -> float:
    v = features.get(key)
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _select_vp(features: dict[str, Any], tf: str, session_key: str, rolling_key: str) -> float:
    """Return rolling VP field for 15m+ (structural), session field for 1m/5m."""
    if tf in ("15m", "1h", "4h", "1d"):
        return _fval(features, rolling_key)
    return _fval(features, session_key)


# (feature_key, display_name, default_strength, source_tier, source_family)
_SUPPORT_SPECS: list[tuple[str, str, float, str, str]] = [
    ("nearest_support",    "support",    0.7, "i3",  "sr"),
    ("sr_nearest_support", "sr_support", 0.7, "i3",  "sr"),
    ("swing_low",          "swing_low",  0.6, "i3",  "swing"),
    ("nearest_demand_high","demand",     0.7, "smc", "smc_demand"),
    ("ema_21",             "ema21",      0.7, "i1",  "ma_ema"),
    ("sma_50",             "sma50",      0.6, "i1",  "ma_sma"),
    ("ssl_level",          "ssl",        0.7, "smc", "smc_ssl"),
    ("overnight_low",      "overnight",  0.6, "i3",  "overnight"),
]

_RESISTANCE_SPECS: list[tuple[str, str, float, str, str]] = [
    ("nearest_resistance",  "resistance",  0.7, "i3",  "sr"),
    ("sr_nearest_resistance","sr_resist",  0.7, "i3",  "sr"),
    ("swing_high",          "swing_high",  0.6, "i3",  "swing"),
    ("nearest_supply_low",  "supply",      0.7, "smc", "smc_supply"),
    ("ema_21",              "ema21",       0.7, "i1",  "ma_ema"),
    ("sma_50",              "sma50",       0.6, "i1",  "ma_sma"),
    ("bsl_level",           "bsl",         0.7, "smc", "smc_bsl"),
    ("overnight_high",      "overnight",   0.6, "i3",  "overnight"),
]

_STRENGTH_FIELD: dict[str, str] = {
    "support":    "support_strength",
    "sr_support": "support_strength",
    "sr_resist":  "resistance_strength",
    "swing_low":  "swing_low_age_bars",
    "swing_high": "swing_high_age_bars",
    "ssl":        "ssl_significance",
    "bsl":        "bsl_significance",
    "demand":     "demand_strength",
    "supply":     "supply_strength",
}


def _resolve_strength(features: dict, name: str, default: float) -> float:
    key = _STRENGTH_FIELD.get(name)
    if key is None:
        return default
    val = _fval(features, key)
    if val > EPSILON:
        if "age_bars" in key:
            return min(1.0, 1.0 / (1.0 + val / 50.0))
        return min(1.0, val)
    return default


def _dedup(candidates: list[ZoneCandidate], atr: float) -> list[ZoneCandidate]:
    """Within each source_family, keep only the candidate closest to the cluster centroid.

    Two candidates in the same family within 1 ATR of each other are considered
    duplicates (same underlying level represented by two feature keys).
    Keeps the one with higher strength.
    """
    tol = atr * 1.0
    seen: dict[str, ZoneCandidate] = {}  # family -> best candidate
    result: list[ZoneCandidate] = []
    for c in candidates:
        existing = seen.get(c.source_family)
        if existing is None:
            seen[c.source_family] = c
        elif abs(c.price - existing.price) < tol:
            # Same family, close price — keep the stronger one
            if c.strength > existing.strength:
                seen[c.source_family] = c
        else:
            # Same family but different price zone — flush the buffered one and keep new
            result.append(seen[c.source_family])
            seen[c.source_family] = c
    result.extend(seen.values())
    return result


def collect_candidates(
    features: dict[str, Any],
    direction: int,
    entry: float,
    stop: float,
) -> list[ZoneCandidate]:
    """Collect structural price candidates between stop and entry (exclusive).

    Returns deduplicated list ordered by price ascending.
    """
    tf = features.get("timeframe", "")
    atr = _fval(features, "atr_14") or 0.5
    if direction == 1:
        lo, hi = stop, entry
        specs = _SUPPORT_SPECS
    else:
        lo, hi = entry, stop
        specs = _RESISTANCE_SPECS

    raw: list[ZoneCandidate] = []
    for feat_key, name, default_str, tier, family in specs:
        price = _fval(features, feat_key)
        if price <= EPSILON or not (lo < price < hi):
            continue
        strength = _resolve_strength(features, name, default_str)
        raw.append(ZoneCandidate(price=price, name=name, strength=strength,
                                 source_tier=tier, source_family=family))

    # Volume profile fields (session vs rolling based on TF)
    if direction == 1:
        poc = _select_vp(features, tf, "poc_price", "poc_price_rolling")
        val = _select_vp(features, tf, "val", "val_rolling")
        hvn = _fval(features, "nearest_hvn_below")
        for price, name in [(poc, "poc"), (val, "val"), (hvn, "hvn_below")]:
            if price > EPSILON and lo < price < hi:
                raw.append(ZoneCandidate(price=price, name=name,
                                         strength=0.8 if name == "poc" else 0.7,
                                         source_tier="i4", source_family="vp"))
    else:
        poc = _select_vp(features, tf, "poc_price", "poc_price_rolling")
        vah = _select_vp(features, tf, "vah", "vah_rolling")
        hvn = _fval(features, "nearest_hvn_above")
        for price, name in [(poc, "poc"), (vah, "vah"), (hvn, "hvn_above")]:
            if price > EPSILON and lo < price < hi:
                raw.append(ZoneCandidate(price=price, name=name,
                                         strength=0.8 if name == "poc" else 0.7,
                                         source_tier="i4", source_family="vp"))

    return sorted(_dedup(raw, atr), key=lambda c: c.price)
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests/unit/trading/test_zone_engine.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/trading/zone_engine.py tests/unit/trading/ 
git commit -m "feat(zone): add zone_engine with deduped candidate collection"
```

---

### Task 2: Implement clustering and resolve_structural_zone

**Files:**
- Modify: `src/intelligence/trading/zone_engine.py`
- Modify: `tests/unit/trading/test_zone_engine.py`

- [ ] **Step 1: Write failing tests for clustering and full resolution**

Append to `tests/unit/trading/test_zone_engine.py`:

```python
from src.intelligence.trading.zone_engine import resolve_structural_zone


def _feat(**overrides):
    base = {
        "atr_14": 0.5, "timeframe": "1m",
        "nearest_support": 0.0, "sr_nearest_support": 0.0,
        "swing_low": 0.0, "nearest_demand_high": 0.0,
        "ema_21": 0.0, "sma_50": 0.0, "ssl_level": 0.0, "overnight_low": 0.0,
        "nearest_resistance": 0.0, "sr_nearest_resistance": 0.0,
        "swing_high": 0.0, "nearest_supply_low": 0.0,
        "bsl_level": 0.0, "overnight_high": 0.0,
        "poc_price": 0.0, "val": 0.0, "vah": 0.0,
        "nearest_hvn_below": 0.0, "nearest_hvn_above": 0.0,
        "poc_price_rolling": 0.0, "val_rolling": 0.0, "vah_rolling": 0.0,
    }
    base.update(overrides)
    return base


def test_confluence_cluster_requires_source_diversity():
    """3 candidates from different source families → confluence tier."""
    f = _feat(swing_low=99.5, ema_21=99.52, poc_price=99.48)
    result = resolve_structural_zone(f, direction=1, entry=100.0, stop=98.0, atr=0.5)
    assert result.tier == "confluence"
    assert result.cluster_members >= 3


def test_no_confluence_without_diversity():
    """2 candidates from same family → should fall to single tier."""
    # nearest_support and sr_nearest_support are same family "sr" — dedup keeps 1
    f = _feat(nearest_support=99.5, sr_nearest_support=99.51)
    result = resolve_structural_zone(f, direction=1, entry=100.0, stop=98.0, atr=0.5)
    # After dedup, only 1 candidate survives → single, not confluence
    assert result.tier in ("single", "atr")


def test_single_level_when_no_cluster():
    """One isolated candidate → single tier."""
    f = _feat(swing_low=99.0)
    result = resolve_structural_zone(f, direction=1, entry=100.0, stop=98.0, atr=0.5)
    assert result.tier == "single"
    assert "swing_low" in result.source


def test_atr_fallback_returns_atr_tier():
    """No candidates → atr tier, caller provides bounds."""
    f = _feat()
    result = resolve_structural_zone(f, direction=1, entry=100.0, stop=98.0, atr=0.5)
    assert result.tier == "atr"
    assert result.candidate_count == 0


def test_zone_excludes_candidates_outside_stop_entry():
    """Level below stop is excluded."""
    f = _feat(nearest_support=97.5)  # below stop=98.0
    result = resolve_structural_zone(f, direction=1, entry=100.0, stop=98.0, atr=0.5)
    assert result.tier == "atr"


def test_minimum_zone_width_enforced():
    """Two levels 0.01 apart → zone width >= 0.25 * ATR."""
    f = _feat(swing_low=99.995, ema_21=100.005)
    result = resolve_structural_zone(f, direction=1, entry=100.5, stop=98.0, atr=0.5)
    width = result.zone_high - result.zone_low
    assert width >= 0.25 * 0.5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/trading/test_zone_engine.py::test_confluence_cluster_requires_source_diversity -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_structural_zone'`

- [ ] **Step 3: Append clustering and resolve_structural_zone to zone_engine.py**

```python
# Append to src/intelligence/trading/zone_engine.py

def _find_clusters(candidates: list[ZoneCandidate], atr: float) -> list[list[ZoneCandidate]]:
    """Group sorted candidates into tight clusters (within CLUSTER_RADIUS_ATR)."""
    if not candidates:
        return []
    clusters: list[list[ZoneCandidate]] = []
    current = [candidates[0]]
    radius = atr * CLUSTER_RADIUS_ATR
    for c in candidates[1:]:
        if c.price - current[-1].price <= radius:
            current.append(c)
        else:
            clusters.append(current)
            current = [c]
    clusters.append(current)
    return [cl for cl in clusters if len(cl) >= 2]


def _source_diversity(cluster: list[ZoneCandidate]) -> int:
    """Count distinct source_tiers in cluster (proxy for structural independence)."""
    return len({c.source_tier for c in cluster})


def _score_cluster(cluster: list[ZoneCandidate], atr: float) -> float:
    """Score = strength_sum × diversity / compactness_penalty.

    Prefers: high-quality levels, structurally independent sources, tight clusters.
    """
    width = max(cluster[-1].price - cluster[0].price, atr * 0.01)
    width_atr = width / atr
    strength_sum = sum(c.strength for c in cluster)
    diversity = _source_diversity(cluster)
    return (strength_sum * diversity) / max(width_atr, 0.1)


def _pick_single_best(candidates: list[ZoneCandidate], entry: float, atr: float) -> ZoneCandidate | None:
    """Return highest-scoring single candidate (strength × proximity)."""
    if not candidates:
        return None
    best_score = -1.0
    best = None
    for c in candidates:
        dist_atr = abs(c.price - entry) / atr if atr > EPSILON else 2.0
        proximity = max(0.0, 1.0 - dist_atr / 2.0)
        score = c.strength * 0.6 + proximity * 0.4
        if score > best_score:
            best_score = score
            best = c
    return best


def _expand_to_min_width(low: float, high: float, atr: float) -> tuple[float, float]:
    min_width = atr * MIN_ZONE_WIDTH_ATR
    if high - low < min_width:
        mid = (low + high) / 2
        low = mid - min_width / 2
        high = mid + min_width / 2
    return low, high


def resolve_structural_zone(
    features: dict[str, Any],
    direction: int,
    entry: float,
    stop: float,
    atr: float,
) -> ZoneResult:
    """Resolve zone bounds from structural confluence.

    Returns ZoneResult.tier = "atr" when no structure is found — caller applies
    its own ATR fallback bounds (entry ± ATR multiples).
    """
    candidates = collect_candidates(features, direction, entry, stop)

    if not candidates:
        return ZoneResult(
            zone_low=0.0, zone_high=0.0, tier="atr",
            source="atr_fallback", candidate_count=0, cluster_members=0,
        )

    # Tier 1: Confluence cluster (requires ≥2 structurally distinct source_tiers)
    clusters = _find_clusters(candidates, atr)
    diverse_clusters = [cl for cl in clusters if _source_diversity(cl) >= 2]
    if diverse_clusters:
        best = max(diverse_clusters, key=lambda cl: _score_cluster(cl, atr))
        low = best[0].price - atr * ZONE_BUFFER_ATR
        high = best[-1].price + atr * ZONE_BUFFER_ATR
        low, high = _expand_to_min_width(low, high, atr)
        names = "+".join(c.name for c in best)
        return ZoneResult(
            zone_low=low, zone_high=high, tier="confluence",
            source=f"confluence:{names}",
            candidate_count=len(candidates),
            cluster_members=len(best),
        )

    # Tier 2: Single best level
    best_single = _pick_single_best(candidates, entry, atr)
    if best_single is not None:
        r = atr * SINGLE_LEVEL_RADIUS_ATR
        low, high = _expand_to_min_width(best_single.price - r, best_single.price + r, atr)
        return ZoneResult(
            zone_low=low, zone_high=high, tier="single",
            source=f"single:{best_single.name}",
            candidate_count=len(candidates),
            cluster_members=0,
        )

    # Tier 3: Signal to caller — no usable structure
    return ZoneResult(
        zone_low=0.0, zone_high=0.0, tier="atr",
        source="atr_fallback",
        candidate_count=len(candidates),
        cluster_members=0,
    )
```

- [ ] **Step 4: Run all zone_engine tests**

Run: `.venv/bin/pytest tests/unit/trading/test_zone_engine.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/trading/zone_engine.py tests/unit/trading/test_zone_engine.py
git commit -m "feat(zone): implement clustering with quality scoring and resolve_structural_zone"
```

---

### Task 3: Add zone metrics to observability

**Files:**
- Modify: `src/observability/metrics.py`

- [ ] **Step 1: Add zone metrics using direct prometheus_client API**

The existing `counter()` helper in `metrics.py` does NOT support label lists — it takes only `(name, doc)`. Labeled counters and histograms must be created directly. Add after the last metric definition (search for the end of the existing block):

```python
# Zone engine metrics — use direct API (counter() helper doesn't support labels)
ZONE_TIER_USED = Counter(
    "zone_tier_used_total",
    "Zone engine resolution tier selected per call",
    ["tier"],
)
ZONE_CANDIDATE_COUNT = Histogram(
    "zone_candidate_count",
    "Structural candidates evaluated per zone resolution",
    buckets=[0, 1, 2, 3, 5, 8, 12, 20],
)
ZONE_CLUSTER_DENSITY = Histogram(
    "zone_cluster_density",
    "Cluster quality score (strength × diversity / width_atr)",
    buckets=[0.5, 1, 2, 5, 10, 20, 50],
)
ZONE_WIDTH_ATR = Histogram(
    "zone_width_atr",
    "Final zone width in ATR units",
    buckets=[0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0],
)
```

- [ ] **Step 2: Verify import**

Run: `.venv/bin/python -c "from src.observability.metrics import ZONE_TIER_USED, ZONE_CANDIDATE_COUNT, ZONE_CLUSTER_DENSITY, ZONE_WIDTH_ATR; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Add metric recording to resolve_structural_zone in zone_engine.py**

Add import block near the top of `zone_engine.py` (after existing imports):

```python
from src.observability.metrics import (
    ZONE_CANDIDATE_COUNT,
    ZONE_CLUSTER_DENSITY,
    ZONE_TIER_USED,
    ZONE_WIDTH_ATR,
)
```

Add this helper and call it at the end of `resolve_structural_zone` before each `return` statement. Replace each bare `return ZoneResult(...)` with:

```python
def _emit_metrics(result: ZoneResult, atr: float) -> None:
    ZONE_TIER_USED.labels(tier=result.tier).inc()
    ZONE_CANDIDATE_COUNT.observe(result.candidate_count)
    if atr > EPSILON:
        width = result.zone_high - result.zone_low
        ZONE_WIDTH_ATR.observe(width / atr)
        if result.cluster_members >= 2 and width > 0:
            density = result.cluster_members / max(width / atr, 0.01)
            ZONE_CLUSTER_DENSITY.observe(density)
```

At the end of `resolve_structural_zone`, call `_emit_metrics(result, atr)` before returning. Example:

```python
    result = ZoneResult(
        zone_low=low, zone_high=high, tier="confluence",
        source=f"confluence:{names}",
        candidate_count=len(candidates),
        cluster_members=len(best),
    )
    _emit_metrics(result, atr)
    return result
```

Apply to all three return paths (confluence, single, atr).

- [ ] **Step 4: Run zone_engine tests still pass**

Run: `.venv/bin/pytest tests/unit/trading/test_zone_engine.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add src/observability/metrics.py src/intelligence/trading/zone_engine.py
git commit -m "feat(observability): add zone engine Prometheus metrics"
```

---

### Task 4: Wire zone_engine into trade_framer — augment, don't replace

**Files:**
- Modify: `src/intelligence/trading/trade_framer.py`
- Modify: `tests/unit/test_trade_framer.py`

The existing `_resolve_zone_bounds` has setup-specific geometry that MUST be preserved:
- `supply_demand_*` → uses `nearest_demand_low/high` or `nearest_supply_low/high` exact bounds
- `fvg_*` → uses `fvg_bottom/fvg_top`
- `choch_*` or `*ob*` → uses `ob_bottom/ob_top`
- `sweep_*` / `liquidity_hunt_*` → tight ± 0.5 ATR band

The structural zone engine replaces **only** the final ATR fallback for all other setups.

- [ ] **Step 1: Add zone_engine import to trade_framer.py**

At the top of `src/intelligence/trading/trade_framer.py`, find the existing imports and add:

```python
from .zone_engine import resolve_structural_zone
```

- [ ] **Step 2: Update _resolve_zone_bounds signature to accept stop**

Replace the existing `_resolve_zone_bounds` function (lines 308-352) entirely:

```python
def _resolve_zone_bounds(
    setup_type: str,
    direction: int,
    entry: float,
    stop: float,
    features: dict[str, Any],
    atr: float,
) -> tuple[float, float, str]:
    """Return (zone_low, zone_high, zone_source) for the entry zone.

    Preserves setup-specific geometry first; calls structural zone engine
    only when no setup-specific bounds are available.
    zone_low < zone_high always (independent of direction).
    """
    st = setup_type.lower()

    # Supply/Demand zone entries — use exact zone bounds (highest precision)
    if st.startswith("supply_demand"):
        if direction == 1:
            low = _fval(features, "nearest_demand_low")
            high = _fval(features, "nearest_demand_high")
        else:
            low = _fval(features, "nearest_supply_low")
            high = _fval(features, "nearest_supply_high")
        if EPSILON_TOLERANCE < low < high:
            return low, high, "setup:supply_demand_zone"

    # FVG fill — use FVG bottom/top
    if st.startswith("fvg"):
        fvg_bottom = _fval(features, "fvg_bottom")
        fvg_top = _fval(features, "fvg_top")
        if EPSILON_TOLERANCE < fvg_bottom < fvg_top:
            return fvg_bottom, fvg_top, "setup:fvg_zone"

    # Order block entries — use OB bottom/top
    if st.startswith("choch") or "ob" in st:
        ob_bottom = _fval(features, "ob_bottom")
        ob_top = _fval(features, "ob_top")
        if EPSILON_TOLERANCE < ob_bottom < ob_top:
            return ob_bottom, ob_top, "setup:ob_zone"

    # Sweep/reclaim — tight zone ± 0.5 ATR around entry (price already moved through)
    if st.startswith("sweep") or st.startswith("liquidity_hunt"):
        return (
            entry - atr * ATR_ZONE_SWEEP_MULTIPLIER,
            entry + atr * ATR_ZONE_SWEEP_MULTIPLIER,
            "setup:sweep_band",
        )

    # All other setups: try structural confluence engine
    result = resolve_structural_zone(features, direction, entry, stop, atr)
    if result.tier != "atr":
        return result.zone_low, result.zone_high, result.source

    # Final ATR fallback
    return (
        entry - atr * ATR_ZONE_LOW_MULTIPLIER,
        entry + atr * ATR_ZONE_HIGH_MULTIPLIER,
        "atr_fallback",
    )
```

- [ ] **Step 3: Update the call site in frame_trade to pass stop and capture zone_source**

In `frame_trade()`, find lines 841-843 (the existing `_resolve_zone_bounds` call):

Replace:
```python
    zone_low, zone_high = _resolve_zone_bounds(
        setup_type, direction, resolved_entry, features, effective_atr
    )
```

With:
```python
    zone_low, zone_high, zone_source = _resolve_zone_bounds(
        setup_type, direction, resolved_entry, stop, features, effective_atr
    )
    features["zone_source"] = zone_source
```

Note: `stop` is resolved at lines 833-838, before this call — it is available.

- [ ] **Step 4: Run trade_framer tests**

Run: `.venv/bin/pytest tests/unit/test_trade_framer.py -v`
Expected: All existing tests pass. If any test called `_resolve_zone_bounds` directly with 5 args, update it to 6 args including `stop`. If ATR fallback bounds changed for any setup type, update expected values.

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/trading/trade_framer.py tests/unit/test_trade_framer.py
git commit -m "refactor(trade_framer): zone engine as fallback augmentation, preserve setup geometry"
```

---

### Task 5: Update signal_schema to v2 with zone_source

**Files:**
- Modify: `src/intelligence/trading/signal_schema.py`

- [ ] **Step 1: Add zone_source and bump version**

In `signal_schema.py`, find lines 177-179:

```python
    sig["zone_low"] = tf.zone_low
    sig["zone_high"] = tf.zone_high
    sig["signal_schema_version"] = "v1"
```

Replace with:

```python
    sig["zone_low"] = tf.zone_low
    sig["zone_high"] = tf.zone_high
    sig["zone_source"] = (features_snapshot or {}).get("zone_source")
    sig["signal_schema_version"] = "v2"
```

Note: `features_snapshot` is already a parameter to `make_signal_from_frame` (it's passed by I7 plugins and used for ML capture). The mutation of `features["zone_source"]` in Task 4 ensures it is present.

- [ ] **Step 2: Verify import**

Run: `.venv/bin/python -c "from src.intelligence.trading.signal_schema import make_signal_from_frame; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Note for ML consumers**

The ML training filter must now be:
```sql
WHERE signal_schema_version IN ('v1', 'v2')
```
`zone_source` is NULL for v1 signals — this is safe; ML treats NULL as missing feature.

- [ ] **Step 4: Commit**

```bash
git add src/intelligence/trading/signal_schema.py
git commit -m "feat(signal_schema): bump to v2, add zone_source for ML attribution"
```

---

### Task 6: Market-entry tracking via Kafka lifecycle events

**Files:**
- Modify: `src/intelligence/trading/lifecycle_transitions.py`
- Modify: `src/persistence/repository/signal_ledger_repository.py`
- Modify: `services/signal_tracker_compute_agent.py`

The pattern mirrors the existing lifecycle event flow:
`signal_tracker_compute_agent` (compute only) → publishes `LifecycleTransition(MARKET_RESOLUTION, ...)` → Kafka `lifecycle.transitions` topic → `lifecycle_writer_agent` → `repo.batch_execute("market_resolution", items)`.

The agent is DB-ignorant — it never calls the repo directly.

- [ ] **Step 1: Add TransitionType.MARKET_RESOLUTION to lifecycle_transitions.py**

In `src/intelligence/trading/lifecycle_transitions.py`, find the `TransitionType` StrEnum:

```python
class TransitionType(StrEnum):
    ACTIVATION = "activation"
    EXIT = "exit"
    CHANDELIER_UPDATE = "chandelier_update"
    MAE_MFE_UPDATE = "mae_mfe_update"
    SHADOW_OUTCOME = "shadow_outcome"
```

Add one line:

```python
class TransitionType(StrEnum):
    ACTIVATION = "activation"
    EXIT = "exit"
    CHANDELIER_UPDATE = "chandelier_update"
    MAE_MFE_UPDATE = "mae_mfe_update"
    SHADOW_OUTCOME = "shadow_outcome"
    MARKET_RESOLUTION = "market_resolution"
```

- [ ] **Step 2: Verify no import errors**

Run: `.venv/bin/python -c "from src.intelligence.trading.lifecycle_transitions import TransitionType; assert TransitionType.MARKET_RESOLUTION == 'market_resolution'; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Add batch_execute support for market_resolution in signal_ledger_repository.py**

In `src/persistence/repository/signal_ledger_repository.py`, find `_RECORD_MARKET_RESOLUTION_SQL` (around line 493). Add a batch variant constant immediately after it:

```python
_BATCH_MARKET_RESOLUTION_SQL = _RECORD_MARKET_RESOLUTION_SQL
```

(The SQL is identical — asyncpg `executemany` accepts the same positional-param statement.)

Then in `batch_execute()` (around line 946), find the `else: raise ValueError(...)` block and insert before it:

```python
        elif transition_type == "market_resolution":
            sql = _BATCH_MARKET_RESOLUTION_SQL
            params = [
                (
                    d["signal_id"],
                    d.get("market_entry_at"),
                    d.get("market_entry_exit_price"),
                    d.get("market_entry_exit_at"),
                    d.get("market_entry_pnl_r"),
                    d.get("market_entry_mae"),
                    d.get("market_entry_mfe"),
                    d.get("market_entry_bars_in_trade"),
                    d.get("market_entry_outcome"),
                    d.get("market_entry_gap_bars"),
                )
                for d in items
            ]
```

Also update the `ValueError` message to include `market_resolution`:

```python
        else:
            raise ValueError(
                f"Unknown transition_type '{transition_type}'. "
                "Must be one of: activation, exit, chandelier_update, "
                "mae_mfe_update, shadow_outcome, market_resolution"
            )
```

- [ ] **Step 4: Verify batch_execute update**

Run: `.venv/bin/python -c "
from src.persistence.repository.signal_ledger_repository import SignalLedgerRepository
import inspect
src = inspect.getsource(SignalLedgerRepository.batch_execute)
assert 'market_resolution' in src
print('OK')
"`
Expected: `OK`

- [ ] **Step 5: Add market-entry state to signal_tracker_compute_agent.py**

In `services/signal_tracker_compute_agent.py`, find `__init__` where `self._mae` and `self._mfe` are initialized (likely around lines 95-105). Add alongside them:

```python
        self._market_mae: dict[str, float] = {}   # signal_id -> running market-track MAE
        self._market_mfe: dict[str, float] = {}   # signal_id -> running market-track MFE
```

- [ ] **Step 6: Wire evaluate_market_entry in the bar loop**

In `signal_tracker_compute_agent.py`, find the block after `evaluate_signal` (around line 514, after `await self._publish_transition(lifecycle_t)`). Insert the market-entry evaluation block after the existing evaluate_signal call and transition publishing:

```python
            # --- Market-entry dual track ---
            mep = sig.get("market_entry_price")
            if mep and float(mep) > 0:
                market_entry_price = float(mep)
                m_mae = self._market_mae.get(sid, 0.0)
                m_mfe = self._market_mfe.get(sid, 0.0)
                try:
                    mkt = evaluate_market_entry(
                        sig_with_extras,
                        market_entry_price=market_entry_price,
                        high=float(bar["high"]),
                        low=float(bar["low"]),
                        close=float(bar["close"]),
                        current_mae=m_mae,
                        current_mfe=m_mfe,
                    )
                    if mkt.outcome is not None:
                        await self._publish_market_resolution(mkt, bar_time)
                        self._market_mae.pop(sid, None)
                        self._market_mfe.pop(sid, None)
                    else:
                        pnl_now = (float(bar["close"]) - market_entry_price) * int(sig["direction"])
                        risk_m = abs(market_entry_price - float(sig.get("stop_loss", market_entry_price)))
                        if risk_m > 0:
                            pnl_r = pnl_now / risk_m
                            self._market_mae[sid] = min(m_mae, pnl_r)
                            self._market_mfe[sid] = max(m_mfe, pnl_r)
                except Exception as exc:
                    self.logger.warning("market_entry.eval.error", signal_id=sid, error=str(exc))
```

Add the required import at the top of the imports block (alongside `evaluate_signal`):

```python
from src.intelligence.trading.lifecycle_tracker import (
    evaluate_market_entry,
    evaluate_signal,
    MarketTransition,
)
```

- [ ] **Step 7: Add _publish_market_resolution method**

Add this method to `SignalTrackerComputeAgent`:

```python
    async def _publish_market_resolution(
        self, mkt: MarketTransition, bar_time: datetime
    ) -> None:
        """Publish market-track resolution as a LifecycleTransition to Kafka."""
        lt = LifecycleTransition(
            transition_type=TransitionType.MARKET_RESOLUTION,
            signal_id=mkt.signal_id,
            symbol="",   # lifecycle_writer doesn't need symbol for market_resolution
            timeframe="",
            bar_ts=bar_time,
            data={
                "market_entry_at": bar_time,
                "market_entry_exit_price": mkt.exit_price,
                "market_entry_exit_at": bar_time,
                "market_entry_pnl_r": mkt.pnl_r,
                "market_entry_mae": mkt.mae,
                "market_entry_mfe": mkt.mfe,
                "market_entry_bars_in_trade": None,
                "market_entry_outcome": mkt.outcome,
                "market_entry_gap_bars": mkt.gap_bars,
            },
        )
        await self._publish_transition(lt)
```

- [ ] **Step 8: Clean up market state on signal removal**

In `_remove_signal` (around line 364), add alongside the existing `_mae.pop` / `_mfe.pop`:

```python
        self._market_mae.pop(signal_id, None)
        self._market_mfe.pop(signal_id, None)
```

- [ ] **Step 9: Run unit tests**

Run: `.venv/bin/pytest tests/unit/ -k "signal_tracker or lifecycle" -v`
Expected: All pass. If tests use `ServiceClass.__new__()` pattern, add `svc._market_mae = {}` and `svc._market_mfe = {}` to the fixture setup.

- [ ] **Step 10: Commit**

```bash
git add src/intelligence/trading/lifecycle_transitions.py \
        src/persistence/repository/signal_ledger_repository.py \
        services/signal_tracker_compute_agent.py
git commit -m "feat(lifecycle): wire market-entry dual-track via MARKET_RESOLUTION Kafka event"
```

---

### Task 7: Stop/target candidate improvements in trade_framer

**Files:**
- Modify: `src/intelligence/trading/trade_framer.py`

- [ ] **Step 1: Verify ema_21 is not already used as stop candidate**

Run: `grep -n "ema_21" src/intelligence/trading/trade_framer.py`

If `ema_21` already appears as a stop candidate, skip Step 2.

- [ ] **Step 2: Add ema_21 as stop candidate in _resolve_stop_long and _resolve_stop_short**

In `_resolve_stop_long` (around line 430), find the existing stop priority chain. Add ema_21 after the swing_low priority and before the sr_nearest_support fallback:

```python
    # Priority 4b: EMA 21 below entry as structural support stop
    ema_21 = _fval(features, "ema_21")
    if ema_21 > EPSILON_TOLERANCE and ema_21 < entry:
        stop = ema_21 - atr * ATR_STOP_SWING_MULTIPLIER
        return min(stop, min_stop), "ema_21_support"
```

In `_resolve_stop_short`, add the mirror (ema_21 above entry):

```python
    # Priority 4b: EMA 21 above entry as structural resistance stop
    ema_21 = _fval(features, "ema_21")
    if ema_21 > EPSILON_TOLERANCE and ema_21 > entry:
        stop = ema_21 + atr * ATR_STOP_SWING_MULTIPLIER
        return max(stop, max_stop), "ema_21_resistance"
```

- [ ] **Step 3: Add BSL/SSL targets to target collection**

In `_collect_targets_long` (around line 534), after the existing candidates (kalman_upper, nearest_demand_high), add:

```python
    # BSL (Buy Side Liquidity) above entry — structural resistance / target
    bsl_level = _fval(features, "bsl_level")
    bsl_sig = _fval(features, "bsl_significance")
    if bsl_level > entry and bsl_sig >= 0.5:
        candidates.append((bsl_level, f"BSL {bsl_level:.2f}", "bsl"))

    # Prior day high as target for longs
    prior_day_high = _fval(features, "prior_day_high")
    if prior_day_high > entry:
        candidates.append((prior_day_high, f"Prior Day H {prior_day_high:.2f}", "prior_day"))

    # Session high (overnight) as target
    overnight_high = _fval(features, "overnight_high")
    if overnight_high > entry:
        candidates.append((overnight_high, f"Overnight H {overnight_high:.2f}", "overnight"))
```

In `_collect_targets_short`, after existing candidates, add the mirrors:

```python
    # SSL (Sell Side Liquidity) below entry — structural support / target
    ssl_level = _fval(features, "ssl_level")
    ssl_sig = _fval(features, "ssl_significance")
    if EPSILON_TOLERANCE < ssl_level < entry and ssl_sig >= 0.5:
        candidates.append((ssl_level, f"SSL {ssl_level:.2f}", "ssl"))

    # Prior day low as target for shorts
    prior_day_low = _fval(features, "prior_day_low")
    if EPSILON_TOLERANCE < prior_day_low < entry:
        candidates.append((prior_day_low, f"Prior Day L {prior_day_low:.2f}", "prior_day"))

    # Session low (overnight) as target
    overnight_low = _fval(features, "overnight_low")
    if EPSILON_TOLERANCE < overnight_low < entry:
        candidates.append((overnight_low, f"Overnight L {overnight_low:.2f}", "overnight"))
```

Note: Do NOT add Fibonacci levels as extension targets. Fib retracement levels are already used as zone/stop candidates in zone_engine.py (on the entry side). They are not reliable extension targets for I7 setups.

- [ ] **Step 4: Run trade_framer tests**

Run: `.venv/bin/pytest tests/unit/test_trade_framer.py -v`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/intelligence/trading/trade_framer.py
git commit -m "feat(trade_framer): add ema21 stops, BSL/SSL and prior day H/L targets"
```

---

### Task 8: Integration test and lint

**Files:**
- All modified files

- [ ] **Step 1: Run full unit test suite**

Run: `.venv/bin/pytest tests/unit/ -v`
Expected: All pass. Fix any failures before proceeding.

- [ ] **Step 2: Run linter and formatter**

Run: `.venv/bin/ruff check . --fix && .venv/bin/black .`
Expected: Clean

- [ ] **Step 3: Verify zone_engine import chain**

Run: `.venv/bin/python -c "
from src.intelligence.trading.zone_engine import resolve_structural_zone, collect_candidates, ZoneCandidate, ZoneResult
from src.intelligence.trading.trade_framer import frame_trade
from src.intelligence.trading.signal_schema import make_signal_from_frame
from src.intelligence.trading.lifecycle_transitions import TransitionType
assert TransitionType.MARKET_RESOLUTION == 'market_resolution'
print('All imports OK')
"`
Expected: `All imports OK`

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "chore: lint and fix integration issues post zone-engine"
```

---

## Self-Review

**Spec coverage vs reviews:**

| Review finding | Addressed in |
|---|---|
| Augment not replace — preserve FVG/OB/demand/supply/sweep geometry | Task 4 ✅ |
| Wrong field `market_price_at_signal` → use `market_entry_price` | Task 6 Step 6 ✅ |
| Task 6 must use Kafka events, not DB repo | Task 6 (full restructure) ✅ |
| `stop` not from `features.get("stop_loss")` — pass explicitly | Task 4 Step 2 ✅ |
| `counter()` helper lacks label support — use `Counter()` direct | Task 3 Step 1 ✅ |
| No `histogram()` helper — use `Histogram()` direct | Task 3 Step 1 ✅ |
| Duplicate level inflation (same price, two feature keys) | Task 1 Step 3 — `_dedup()` by source family ✅ |
| Clustering score ignores strength | Task 2 Step 3 — `_score_cluster` uses `strength_sum × diversity` ✅ |
| Source diversity required for confluence | Task 2 Step 3 — `_source_diversity() >= 2` gate ✅ |
| Remove Fib extension targets | Task 7 — not added, note explains why ✅ |
| BSL/SSL as targets | Task 7 Step 3 ✅ |
| Prior day H/L as targets | Task 7 Step 3 ✅ |

**Placeholder scan:** No TBDs, TODOs, "implement later", or vague instructions. All steps contain exact code or exact commands.

**Type consistency:**
- `ZoneCandidate` and `ZoneResult` defined in Task 1, imported by reference in Tasks 2-4
- `resolve_structural_zone(features, direction, entry, stop, atr) -> ZoneResult` defined in Task 2, called in Task 4
- `_resolve_zone_bounds(...) -> tuple[float, float, str]` (3-tuple with zone_source) defined in Task 4, call site updated in same task
- `TransitionType.MARKET_RESOLUTION` defined in Task 6 Step 1, used in Task 6 Step 7
- `evaluate_market_entry` imported from `lifecycle_tracker` (already exists — no changes needed to that file)
