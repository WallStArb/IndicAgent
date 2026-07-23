"""Structural Confluence -- v3-native VP/S-R confluence resolution (Phase 166 Part 1).

Ports zone_engine.py's generic 3-tier confluence-resolution ARCHITECTURE
(diverse-cluster confluence -> single-best -> ATR fallback) onto ZoneCandidate --
the clustering/scoring core below is generic and ported nearly unmodified. The
candidate UNIVERSE (the v3 spec table, added in Task 2) is fresh: populated
ONLY with the structural fields Phase 163 makes live in `feature_vectors`
(sr_support_dist/sr_resist_dist + VP ATR-distance fields), never the archived
v2.x feature names zone_engine.py's own spec table used.

Three-tier resolution (same shape as zone_engine.py's _resolve_zone):
  1. Confluence cluster (2+ structurally diverse source_tiers within cluster_radius_atr)
  2. Single best structural level (strength x proximity)
  3. ATR fallback (tier="atr" -- caller applies its own bounds)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

EPSILON = 1e-9

_config_service: Any | None = None


def set_config_service(cfg: Any) -> None:
    """Wire a ConfigService instance for APR-backed threshold reads (module-level
    singleton, same shape as zone_engine.py's set_config_service)."""
    global _config_service
    _config_service = cfg


def _read_config(key: str, default: float) -> float:
    return _config_service.get_sync(key, default) if _config_service is not None else default


def _cluster_radius_atr() -> float:
    return _read_config("alpha.frame.cluster_radius_atr", 0.5)


def _single_level_radius_atr() -> float:
    return _read_config("alpha.frame.single_level_radius_atr", 0.25)


def _zone_buffer_atr() -> float:
    return _read_config("alpha.frame.zone_buffer_atr", 0.1)


def _min_width_atr() -> float:
    return _read_config("alpha.frame.min_width_atr", 0.05)


def _strength_weight() -> float:
    return _read_config("alpha.frame.strength_weight", 0.6)


def _proximity_weight() -> float:
    return _read_config("alpha.frame.proximity_weight", 0.4)


def _fval(features: dict[str, Any], key: str) -> float | None:
    """Null-safe float extraction returning None (not 0.0) when absent/invalid.

    Distinct from plugin_utils._fval's 0.0-default: a v3 ATR-distance field of
    exactly 0.0 is a legitimate value (level coincides with entry), so "absent"
    must stay distinguishable from "present and zero" for the Pitfall 3 guard.
    """
    v = features.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@dataclass
class ZoneCandidate:
    price: float
    name: str
    strength: float  # 0.0-1.0 quality weight
    source_tier: str  # "sr" | "vp" (v3 port -- zone_engine.py used "i1"/"i3"/"i4"/"smc")
    source_family: str  # "sr" | "vp" -- dedup/diversity key


@dataclass
class ZoneResult:
    zone_low: float
    zone_high: float
    tier: str  # "confluence" | "single" | "atr"
    source: str
    candidate_count: int
    cluster_members: int


# ---------------------------------------------------------------------------
# Clustering / scoring core -- ported nearly unmodified from zone_engine.py
# (lines 344-395); generic over ZoneCandidate, references no feature names.
# ---------------------------------------------------------------------------


def _find_clusters(candidates: list[ZoneCandidate], atr: float) -> list[list[ZoneCandidate]]:
    """Group candidates into tight clusters (within cluster_radius_atr of each
    other), dropping singleton clusters (len < 2).

    Sorted by price first -- zone_engine.py's analog walks its input in
    insertion order, which is only safe there because its dedup pass happens to
    leave same-family candidates price-sorted; sorting explicitly here is the
    correct, order-independent version of the same algorithm.
    """
    if not candidates:
        return []
    sorted_candidates = sorted(candidates, key=lambda c: c.price)
    clusters: list[list[ZoneCandidate]] = []
    current = [sorted_candidates[0]]
    radius = atr * _cluster_radius_atr()
    for c in sorted_candidates[1:]:
        if abs(c.price - current[-1].price) <= radius:
            current.append(c)
        else:
            clusters.append(current)
            current = [c]
    clusters.append(current)
    return [cl for cl in clusters if len(cl) >= 2]


def _source_diversity(cluster: list[ZoneCandidate]) -> int:
    """Count distinct source_tiers -- proxy for structural independence."""
    return len({c.source_tier for c in cluster})


def _score_cluster(cluster: list[ZoneCandidate], atr: float) -> float:
    """Strength-weighted quality score: rewards strength sum and source-tier
    diversity, penalizes width."""
    prices = [c.price for c in cluster]
    width = max(max(prices) - min(prices), atr * 0.01)
    width_atr = width / atr
    strength_sum = sum(c.strength for c in cluster)
    diversity = _source_diversity(cluster)
    return (strength_sum * diversity) / max(width_atr, 0.1)


def _pick_single_best(
    candidates: list[ZoneCandidate], entry: float, atr: float
) -> ZoneCandidate | None:
    """Return the highest strength x proximity candidate."""
    if not candidates:
        return None
    best_score = -1.0
    best: ZoneCandidate | None = None
    sw = _strength_weight()
    pw = _proximity_weight()
    for c in candidates:
        dist_atr = abs(c.price - entry) / atr if atr > EPSILON else 2.0
        proximity = max(0.0, 1.0 - dist_atr / 2.0)
        score = c.strength * sw + proximity * pw
        if score > best_score:
            best_score = score
            best = c
    return best


def _expand_to_min_width(low: float, high: float, atr: float) -> tuple[float, float]:
    min_width = atr * _min_width_atr()
    if high - low < min_width:
        mid = (low + high) / 2
        low = mid - min_width / 2
        high = mid + min_width / 2
    return low, high


def _resolve_zone(candidates: list[ZoneCandidate], entry: float, atr: float) -> ZoneResult:
    """3-tier confluence resolution: diverse-cluster -> single-best -> ATR
    fallback (tier="atr", empty zone -- caller applies its own bounds)."""
    if not candidates:
        return ZoneResult(
            zone_low=0.0,
            zone_high=0.0,
            tier="atr",
            source="atr_fallback",
            candidate_count=0,
            cluster_members=0,
        )

    # Tier 1: Confluence cluster (requires >=2 distinct source_tiers)
    clusters = _find_clusters(candidates, atr)
    diverse = [cl for cl in clusters if _source_diversity(cl) >= 2]
    if diverse:
        best = max(diverse, key=lambda cl: _score_cluster(cl, atr))
        prices = sorted(c.price for c in best)
        low = prices[0] - atr * _zone_buffer_atr()
        high = prices[-1] + atr * _zone_buffer_atr()
        low, high = _expand_to_min_width(low, high, atr)
        names = "+".join(c.name for c in best)
        return ZoneResult(
            zone_low=low,
            zone_high=high,
            tier="confluence",
            source=f"confluence:{names}",
            candidate_count=len(candidates),
            cluster_members=len(best),
        )

    # Tier 2: Single best level
    best_single = _pick_single_best(candidates, entry, atr)
    if best_single is not None:
        r = atr * _single_level_radius_atr()
        low, high = _expand_to_min_width(best_single.price - r, best_single.price + r, atr)
        return ZoneResult(
            zone_low=low,
            zone_high=high,
            tier="single",
            source=f"single:{best_single.name}",
            candidate_count=len(candidates),
            cluster_members=0,
        )

    # Tier 3: No usable structure -- caller applies ATR bounds
    return ZoneResult(
        zone_low=0.0,
        zone_high=0.0,
        tier="atr",
        source="atr_fallback",
        candidate_count=len(candidates),
        cluster_members=0,
    )
