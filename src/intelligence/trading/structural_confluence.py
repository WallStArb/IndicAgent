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


# ---------------------------------------------------------------------------
# v3 candidate universe (Phase 163 live fields only)
# ---------------------------------------------------------------------------

# EXTENSION POINT (Phase 166 Part 2, deferred -- todo 175): SMC/swing/fib/
# anchored-VWAP source rows are added here once Phases 164/165 + anchored-VWAP
# scoping land (166-CONTEXT.md D-06 / RESEARCH.md Open Question 4 two-part
# split). Do NOT add v2.x zone_engine.py field names to this table -- every
# one of them is 100% absent from v3's live `feature_vectors` schema
# (RESEARCH.md Finding 2/3, Pitfall 3).
#
# (feature_key, display_name, default_strength, source_tier, source_family)
_SR_SPECS: tuple[tuple[str, str, float, str, str], ...] = (
    ("sr_support_dist", "sr_support", 0.7, "sr", "sr"),
    ("sr_resist_dist", "sr_resistance", 0.7, "sr", "sr"),
)

# feature_key -> (display_name, default_strength, price_sign). price = entry +
# price_sign * dist * atr (Phase 163 D-16/D-18 ATR-normalized-distance
# reconstruction -- these fields carry no raw price column by design).
_VP_SPECS: tuple[tuple[str, str, float, float], ...] = (
    ("poc_dist_atr", "poc", 0.8, -1.0),
    ("poc_rolling_dist_atr", "poc_rolling", 0.8, -1.0),
    ("distance_to_vah_atr", "vah", 0.7, 1.0),
    ("distance_to_val_atr", "val", 0.7, -1.0),
)

# name -> Phase 163 D-19 companion strength/age field keys.
_STRENGTH_FIELD: dict[str, str] = {
    "sr_support": "support_strength",
    "sr_resistance": "resistance_strength",
}
_AGE_FIELD: dict[str, str] = {
    "sr_support": "support_age_bars",
    "sr_resistance": "resistance_age_bars",
}


def _resolve_strength(features: dict[str, Any], name: str, default: float) -> float:
    """Map a candidate to its Phase-163 D-19 companion strength/age field(s),
    normalized to 0.0-1.0, decaying to the spec default when both are absent.

    Mirrors zone_engine.py's _STRENGTH_FIELD/_resolve_strength shape (a
    companion-field lookup per candidate name) but combines strength (primary
    quality signal -- D-19's volume-weighted cluster sum, uncapped in
    aggregate) with age (recency bonus, decayed the same way zone_engine.py
    decays *_age_bars) rather than using either alone.
    """
    strength_key = _STRENGTH_FIELD.get(name)
    age_key = _AGE_FIELD.get(name)
    strength_val = _fval(features, strength_key) if strength_key else None
    age_val = _fval(features, age_key) if age_key else None

    normalized_strength = None
    if strength_val is not None and strength_val > EPSILON:
        normalized_strength = min(1.0, strength_val)

    recency = None
    if age_val is not None and age_val > EPSILON:
        recency = min(1.0, 1.0 / (1.0 + age_val / 50.0))

    if normalized_strength is not None and recency is not None:
        return min(1.0, (normalized_strength + recency) / 2.0)
    if normalized_strength is not None:
        return normalized_strength
    if recency is not None:
        return recency
    return default


def _reconstruct_sr_price(name: str, entry: float, dist: float, atr: float) -> float:
    """Reconstruct a S/R price from Phase 163's ATR-normalized distance
    (163-03-PLAN.md: sr_support_dist=(close-support)/atr,
    sr_resist_dist=(resistance-close)/atr -- the sign is applied explicitly
    here rather than assumed)."""
    if name == "sr_support":
        return entry - dist * atr
    if name == "sr_resistance":
        return entry + dist * atr
    raise ValueError(f"structural_confluence: unknown SR candidate name {name!r}")


def collect_candidates(
    features: dict[str, Any],
    direction: int,
    entry: float,
    stop: float,
    atr: float,
) -> list[ZoneCandidate]:
    """Collect v3-native structural candidates strictly between stop and entry.

    Both S/R sides and all 4 VP fields are always reconstructed and then
    filtered to the strict (lo, hi) window -- the reconstruction formula
    itself (not a direction-conditioned spec-table split, unlike
    zone_engine.py's _SUPPORT_SPECS/_RESISTANCE_SPECS) naturally keeps only
    the side relevant to `direction`.
    """
    if direction not in (1, -1):
        raise ValueError(f"structural_confluence: direction must be 1 or -1, got {direction!r}")
    if atr is None or atr <= EPSILON:
        return []
    lo, hi = (stop, entry) if direction == 1 else (entry, stop)
    if lo >= hi:
        return []

    candidates: list[ZoneCandidate] = []

    for feat_key, name, default_strength, tier, family in _SR_SPECS:
        dist = _fval(features, feat_key)
        if dist is None:
            continue
        price = _reconstruct_sr_price(name, entry, dist, atr)
        if not (lo < price < hi):
            continue
        candidates.append(
            ZoneCandidate(
                price=price,
                name=name,
                strength=_resolve_strength(features, name, default_strength),
                source_tier=tier,
                source_family=family,
            )
        )

    for feat_key, name, default_strength, sign in _VP_SPECS:
        dist = _fval(features, feat_key)
        if dist is None:
            continue
        # RESEARCH.md A2: assumes the ATR normalizing this Phase-163 distance
        # matches the `atr` argument passed in here (AlphaFrameWriter's own
        # ATR source) -- flagged, not yet verified against live data (this is
        # a runtime/Plan 166-06 concern, not testable from synthetic fixtures).
        price = entry + sign * dist * atr
        if not (lo < price < hi):
            continue
        candidates.append(
            ZoneCandidate(
                price=price,
                name=name,
                strength=default_strength,
                source_tier="vp",
                source_family="vp",
            )
        )

    return candidates


def resolve_structural_zone(
    features: dict[str, Any],
    direction: int,
    entry: float,
    stop: float,
    atr: float,
) -> ZoneResult:
    """Public entry point: v3-native structural confluence (Phase 166 Part 1).

    Returns tier="atr" (empty zone) when no Phase-163 fields are populated --
    e.g. before Phase 163 executes (NULL_PENDING_163, see 166-01-SUMMARY.md) --
    or when direction/atr are invalid. Caller applies its own ATR-based
    fallback bounds in that case, exactly as zone_engine.py's callers do.
    """
    if atr is None or atr <= EPSILON:
        return ZoneResult(
            zone_low=0.0,
            zone_high=0.0,
            tier="atr",
            source="atr_fallback",
            candidate_count=0,
            cluster_members=0,
        )
    candidates = collect_candidates(features, direction, entry, stop, atr)
    return _resolve_zone(candidates, entry, atr)
