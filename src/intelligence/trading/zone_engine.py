"""Structural Zone Engine — confluence-based entry zone construction.

Resolves entry zones from structural S/R, MAs, and volume levels.
Used by trade_framer as a fallback when no setup-specific geometry exists.

Three-tier resolution:
  1. Confluence cluster (2+ structurally diverse levels within 0.5 ATR)
  2. Single best structural level
  3. ATR band signal (tier="atr" — caller applies its own bounds)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.observability.metrics import (
    ZONE_CANDIDATE_COUNT,
    ZONE_CLUSTER_DENSITY,
    ZONE_TIER_USED,
    ZONE_WIDTH_ATR,
)

EPSILON = 1e-9
CLUSTER_RADIUS_ATR = 0.5
ZONE_BUFFER_ATR = 0.15
MIN_ZONE_WIDTH_ATR = 0.25
SINGLE_LEVEL_RADIUS_ATR = 0.25


@dataclass
class ZoneCandidate:
    price: float
    name: str
    strength: float  # 0.0–1.0 quality weight
    source_tier: str  # "i1", "i3", "i4", "smc"
    source_family: str  # for dedup: "sr", "swing", "smc_ssl", "ma_ema", "ma_sma", "vp", "overnight"


@dataclass
class ZoneResult:
    zone_low: float
    zone_high: float
    tier: str  # "confluence" | "single" | "atr"
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
_SUPPORT_SPECS: tuple[tuple[str, str, float, str, str], ...] = (
    ("nearest_support", "support", 0.7, "i3", "sr"),
    ("sr_nearest_support", "sr_support", 0.7, "i3", "sr"),
    ("swing_low", "swing_low", 0.6, "i3", "swing"),
    ("nearest_demand_high", "demand", 0.7, "smc", "smc_demand"),
    ("ema_21", "ema21", 0.7, "i1", "ma_ema"),
    ("sma_50", "sma50", 0.6, "i1", "ma_sma"),
    ("ssl_level", "ssl", 0.7, "smc", "smc_ssl"),
    ("overnight_low", "overnight", 0.6, "i3", "overnight"),
)

_RESISTANCE_SPECS: tuple[tuple[str, str, float, str, str], ...] = (
    ("nearest_resistance", "resistance", 0.7, "i3", "sr"),
    ("sr_nearest_resistance", "sr_resist", 0.7, "i3", "sr"),
    ("swing_high", "swing_high", 0.6, "i3", "swing"),
    ("nearest_supply_low", "supply", 0.7, "smc", "smc_supply"),
    ("ema_21", "ema21", 0.7, "i1", "ma_ema"),
    ("sma_50", "sma50", 0.6, "i1", "ma_sma"),
    ("bsl_level", "bsl", 0.7, "smc", "smc_bsl"),
    ("overnight_high", "overnight", 0.6, "i3", "overnight"),
)

_STRENGTH_FIELD: dict[str, str] = {
    "support": "support_strength",
    "sr_support": "support_strength",
    "sr_resist": "resistance_strength",
    "swing_low": "swing_low_age_bars",
    "swing_high": "swing_high_age_bars",
    "ssl": "ssl_significance",
    "bsl": "bsl_significance",
    "demand": "demand_strength",
    "supply": "supply_strength",
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
    """Within each source_family, collapse same-price duplicates (within 1 ATR) keeping strongest.

    1 ATR tolerance is intentional — wider than CLUSTER_RADIUS_ATR to suppress
    duplicate-level noise from feature keys that reference the same structural level.
    Distinct prices in the same family (e.g. two sr levels far apart) are both kept.
    """
    tol = atr  # 1 ATR dedup radius
    by_family: dict[str, list[ZoneCandidate]] = {}
    for c in candidates:
        by_family.setdefault(c.source_family, []).append(c)

    result: list[ZoneCandidate] = []
    for family_cands in by_family.values():
        sorted_cands = sorted(family_cands, key=lambda c: c.price)
        cluster: list[ZoneCandidate] = [sorted_cands[0]]
        for c in sorted_cands[1:]:
            if c.price - cluster[-1].price < tol:
                cluster.append(c)
            else:
                result.append(max(cluster, key=lambda x: x.strength))
                cluster = [c]
        result.append(max(cluster, key=lambda x: x.strength))
    return result


def collect_candidates(
    features: dict[str, Any],
    direction: int,
    entry: float,
    stop: float,
) -> list[ZoneCandidate]:
    """Collect deduplicated structural price candidates strictly between stop and entry.

    Returns list sorted by price ascending.
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
        raw.append(
            ZoneCandidate(
                price=price, name=name, strength=strength, source_tier=tier, source_family=family
            )
        )

    # Volume profile (session vs rolling based on TF)
    if direction == 1:
        poc = _select_vp(features, tf, "poc_price", "poc_price_rolling")
        val = _select_vp(features, tf, "val", "val_rolling")
        hvn = _fval(features, "nearest_hvn_below")
        for price, name in [(poc, "poc"), (val, "val"), (hvn, "hvn_below")]:
            if price > EPSILON and lo < price < hi:
                raw.append(
                    ZoneCandidate(
                        price=price,
                        name=name,
                        strength=0.8 if name == "poc" else 0.7,
                        source_tier="i4",
                        source_family=f"vp_{name}",
                    )
                )
    else:
        poc = _select_vp(features, tf, "poc_price", "poc_price_rolling")
        vah = _select_vp(features, tf, "vah", "vah_rolling")
        hvn = _fval(features, "nearest_hvn_above")
        for price, name in [(poc, "poc"), (vah, "vah"), (hvn, "hvn_above")]:
            if price > EPSILON and lo < price < hi:
                raw.append(
                    ZoneCandidate(
                        price=price,
                        name=name,
                        strength=0.8 if name == "poc" else 0.7,
                        source_tier="i4",
                        source_family=f"vp_{name}",
                    )
                )

    return sorted(_dedup(raw, atr), key=lambda c: c.price)


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------


def _find_clusters(candidates: list[ZoneCandidate], atr: float) -> list[list[ZoneCandidate]]:
    """Group sorted candidates into tight clusters (within CLUSTER_RADIUS_ATR of each other)."""
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
    """Count distinct source_tiers — proxy for structural independence."""
    return len({c.source_tier for c in cluster})


def _score_cluster(cluster: list[ZoneCandidate], atr: float) -> float:
    """Strength-weighted quality score.

    Prefers: high-quality levels, structurally independent sources, tight clusters.
    """
    width = max(cluster[-1].price - cluster[0].price, atr * 0.01)
    width_atr = width / atr
    strength_sum = sum(c.strength for c in cluster)
    diversity = _source_diversity(cluster)
    return (strength_sum * diversity) / max(width_atr, 0.1)


def _pick_single_best(
    candidates: list[ZoneCandidate], entry: float, atr: float
) -> ZoneCandidate | None:
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


def _emit_metrics(result: ZoneResult, atr: float) -> None:
    ZONE_TIER_USED.labels(tier=result.tier).inc()
    ZONE_CANDIDATE_COUNT.observe(result.candidate_count)
    if atr > EPSILON:
        width = result.zone_high - result.zone_low
        ZONE_WIDTH_ATR.observe(width / atr)
        if result.cluster_members >= 2 and width > 0:
            density = result.cluster_members / max(width / atr, 0.01)
            ZONE_CLUSTER_DENSITY.observe(density)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_structural_zone(
    features: dict[str, Any],
    direction: int,
    entry: float,
    stop: float,
    atr: float,
) -> ZoneResult:
    """Resolve zone bounds from structural confluence.

    Returns ZoneResult.tier = "atr" when no usable structure is found.
    The caller (trade_framer) applies its own ATR bounds in that case.
    """
    candidates = collect_candidates(features, direction, entry, stop)

    if not candidates:
        result = ZoneResult(
            zone_low=0.0,
            zone_high=0.0,
            tier="atr",
            source="atr_fallback",
            candidate_count=0,
            cluster_members=0,
        )
        _emit_metrics(result, atr)
        return result

    # Tier 1: Confluence cluster (requires ≥2 distinct source_tiers)
    clusters = _find_clusters(candidates, atr)
    diverse = [cl for cl in clusters if _source_diversity(cl) >= 2]
    if diverse:
        best = max(diverse, key=lambda cl: _score_cluster(cl, atr))
        low = best[0].price - atr * ZONE_BUFFER_ATR
        high = best[-1].price + atr * ZONE_BUFFER_ATR
        low, high = _expand_to_min_width(low, high, atr)
        names = "+".join(c.name for c in best)
        result = ZoneResult(
            zone_low=low,
            zone_high=high,
            tier="confluence",
            source=f"confluence:{names}",
            candidate_count=len(candidates),
            cluster_members=len(best),
        )
        _emit_metrics(result, atr)
        return result

    # Tier 2: Single best level
    best_single = _pick_single_best(candidates, entry, atr)
    if best_single is not None:
        r = atr * SINGLE_LEVEL_RADIUS_ATR
        low, high = _expand_to_min_width(best_single.price - r, best_single.price + r, atr)
        result = ZoneResult(
            zone_low=low,
            zone_high=high,
            tier="single",
            source=f"single:{best_single.name}",
            candidate_count=len(candidates),
            cluster_members=0,
        )
        _emit_metrics(result, atr)
        return result

    # Tier 3: Signal to caller — no usable structure
    result = ZoneResult(
        zone_low=0.0,
        zone_high=0.0,
        tier="atr",
        source="atr_fallback",
        candidate_count=len(candidates),
        cluster_members=0,
    )
    _emit_metrics(result, atr)
    return result
