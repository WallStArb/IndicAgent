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

from src.intelligence.trading.atr_utils import get_atr_with_floor
from src.intelligence.trading.plugin_utils import _fval
from src.observability.metrics import (
    ZONE_CANDIDATE_COUNT,
    ZONE_CLUSTER_DENSITY,
    ZONE_TIER_USED,
    ZONE_WIDTH_ATR,
)

EPSILON = 1e-9
CLUSTER_RADIUS_ATR = 0.5
ZONE_BUFFER_ATR = 0.15
MIN_ZONE_WIDTH_ATR = 1.5
SINGLE_LEVEL_RADIUS_ATR = 0.25
DEDUP_TOLERANCE_ATR = 1.0  # wider than CLUSTER_RADIUS_ATR to suppress same-level noise
_SINGLE_STRENGTH_WEIGHT = 0.6
_SINGLE_PROXIMITY_WEIGHT = 0.4
_MAX_DIVERSITY_TIERS = 5  # distinct source_tiers possible in a consensus cluster

_config_service: Any | None = None


def set_config_service(cfg: Any) -> None:
    global _config_service
    _config_service = cfg


def _cfg(key: str, default: float) -> float:
    return _config_service.get_sync(key, default) if _config_service is not None else default


def _cluster_radius_atr() -> float:
    return _cfg("feature.zone_engine.cluster_radius_atr", CLUSTER_RADIUS_ATR)


def _zone_buffer_atr() -> float:
    return _cfg("feature.zone_engine.zone_buffer_atr", ZONE_BUFFER_ATR)


def _min_width_atr() -> float:
    return _cfg("feature.zone_engine.min_width_atr", MIN_ZONE_WIDTH_ATR)


def _single_level_radius_atr() -> float:
    return _cfg("feature.zone_engine.single_level_radius_atr", SINGLE_LEVEL_RADIUS_ATR)


def _strength_weight() -> float:
    return _cfg("weights.zone_engine.strength", _SINGLE_STRENGTH_WEIGHT)


def _proximity_weight() -> float:
    return _cfg("weights.zone_engine.proximity", _SINGLE_PROXIMITY_WEIGHT)


# Maximum structural stop distance per TF — levels beyond this belong to a higher TF.
# Used by trade_framer (stop cap) and sr_consensus (proximity gate radius).
MAX_STOP_ATR_MULTIPLIER_BY_TF: dict[str, float] = {
    "1m": 3.0,
    "5m": 4.0,
    "15m": 5.0,
    "1h": 6.0,
    "4h": 8.0,
    "1d": 8.0,
}
MAX_STOP_ATR_MULTIPLIER_DEFAULT = 5.0


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
    ("nearest_fib_level", "fib", 0.6, "i3", "fib"),
    ("prior_session_low", "prior_sess_l", 0.7, "i3", "session"),
    ("asian_session_low", "asian_l", 0.6, "i3", "session"),
    ("nearest_hvn_below", "hvn_below", 0.8, "i4", "vp_hvn"),
    ("avwap_lower_band", "avwap_lower", 0.6, "i4", "avwap"),
    ("kc_mid_20", "kc_mid", 0.5, "i1", "ma_kc"),
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
    ("nearest_fib_level", "fib", 0.6, "i3", "fib"),
    ("prior_session_high", "prior_sess_h", 0.7, "i3", "session"),
    ("asian_session_high", "asian_h", 0.6, "i3", "session"),
    ("nearest_hvn_above", "hvn_above", 0.8, "i4", "vp_hvn"),
    ("avwap_upper_band", "avwap_upper", 0.6, "i4", "avwap"),
    ("kc_mid_20", "kc_mid", 0.5, "i1", "ma_kc"),
)

_STRENGTH_FIELD: dict[str, str | None] = {
    "support": "support_strength",
    "sr_support": "support_strength",
    "sr_resist": "resistance_strength",
    "swing_low": "swing_low_age_bars",
    "swing_high": "swing_high_age_bars",
    "ssl": "ssl_significance",
    "bsl": "bsl_significance",
    "demand": "demand_strength",
    "supply": "supply_strength",
    "fib": "fib_cluster_strength",
    "hvn_below": "nearest_hvn_dist_atr",
    "hvn_above": "nearest_hvn_dist_atr",
    "prior_sess_l": None,
    "prior_sess_h": None,
    "asian_l": None,
    "asian_h": None,
    "avwap_lower": None,
    "avwap_upper": None,
    "kc_mid": None,
}

# Direction-specific VP companion fields: (session_key, rolling_key, name, hvn_key, hvn_name)
_VP_DIRECTION: dict[int, tuple[str, str, str, str, str]] = {
    1: ("val", "val_rolling", "val", "nearest_hvn_below", "hvn_below"),
    -1: ("vah", "vah_rolling", "vah", "nearest_hvn_above", "hvn_above"),
}


def _resolve_strength(features: dict, name: str, default: float) -> float:
    key = _STRENGTH_FIELD.get(name)
    if key is None:
        return default
    val = _fval(features, key)
    if val > EPSILON:
        if "age_bars" in key:
            return min(1.0, 1.0 / (1.0 + val / 50.0))
        if "dist_atr" in key:  # HVN distance: closer node scores higher
            return min(1.0, 1.0 / (1.0 + val))
        return min(1.0, val)
    return default


def _dedup(candidates: list[ZoneCandidate], atr: float) -> list[ZoneCandidate]:
    """Within each source_family, collapse same-price duplicates keeping strongest.

    Tolerance of DEDUP_TOLERANCE_ATR (1.0 ATR) is intentionally wider than
    CLUSTER_RADIUS_ATR (0.5 ATR) to suppress noise from multiple feature keys
    referencing the same structural level. Distinct prices in the same family
    (e.g. two sr levels far apart) are both kept.
    """
    tol = atr * DEDUP_TOLERANCE_ATR
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


def _collect_raw(
    features: dict[str, Any],
    specs: tuple,
    lo: float,
    hi: float,
    atr: float,
    vp_direction_key: int,
) -> list[ZoneCandidate]:
    """Shared inner loop: iterate specs + VP block, dedup. Used by both collect_candidates
    and collect_sr_candidates. vp_direction_key indexes _VP_DIRECTION directly."""
    tf = features.get("timeframe", "")
    raw: list[ZoneCandidate] = []
    for feat_key, name, default_str, tier, family in specs:
        p = _fval(features, feat_key)
        if p <= EPSILON or not (lo < p < hi):
            continue
        raw.append(
            ZoneCandidate(
                price=p,
                name=name,
                strength=_resolve_strength(features, name, default_str),
                source_tier=tier,
                source_family=family,
            )
        )
    poc = _select_vp(features, tf, "poc_price", "poc_price_rolling")
    c_sess, c_roll, c_name, hvn_key, hvn_name = _VP_DIRECTION[vp_direction_key]
    companion = _select_vp(features, tf, c_sess, c_roll)
    hvn = _fval(features, hvn_key)
    for p, name in [(poc, "poc"), (companion, c_name), (hvn, hvn_name)]:
        if p > EPSILON and lo < p < hi:
            raw.append(
                ZoneCandidate(
                    price=p,
                    name=name,
                    strength=0.8 if name == "poc" else 0.7,
                    source_tier="i4",
                    source_family=f"vp_{name}",
                )
            )
    return _dedup(raw, atr)


def collect_candidates(
    features: dict[str, Any],
    direction: int,
    entry: float,
    stop: float,
) -> list[ZoneCandidate]:
    """Collect deduplicated structural price candidates strictly between stop and entry."""
    if direction not in _VP_DIRECTION:
        raise ValueError(f"zone_engine: direction must be 1 or -1, got {direction!r}")
    symbol = features.get("symbol", "")
    atr = get_atr_with_floor(features, symbol)
    if atr is None:
        return []
    if direction == 1:
        lo, hi = stop, entry
        specs = _SUPPORT_SPECS
    else:
        lo, hi = entry, stop
        specs = _RESISTANCE_SPECS
    return _collect_raw(features, specs, lo, hi, atr, direction)


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

    VP lookup uses -direction because SR semantics are inverted vs trade semantics:
    resistance (direction=1) maps to the vah/hvn_above side (_VP_DIRECTION[-1]).
    """
    if direction not in (1, -1):
        raise ValueError(
            f"zone_engine: collect_sr_candidates direction must be 1 or -1, got {direction!r}"
        )
    if direction == 1:
        lo, hi = price, price + max_dist
        specs = _RESISTANCE_SPECS
    else:
        lo, hi = price - max_dist, price
        specs = _SUPPORT_SPECS
    return _collect_raw(features, specs, lo, hi, atr, -direction)


def find_best_level(
    candidates: list[ZoneCandidate], atr: float, price: float
) -> ZoneCandidate | None:
    """Return the best structural level from a candidate list.

    Public wrapper around private clustering internals so consumers never need
    to import private zone_engine functions.

    Prefers a structurally diverse cluster (2+ source_tiers); falls back to
    the single highest-scoring candidate when no diverse cluster exists.
    """
    if not candidates:
        return None
    clusters = _find_clusters(candidates, atr)
    diverse = [cl for cl in clusters if _source_diversity(cl) >= 2]
    if diverse:
        best = max(diverse, key=lambda cl: (_source_diversity(cl), sum(c.strength for c in cl)))
        avg_price = sum(c.price for c in best) / len(best)
        diversity = _source_diversity(best)
        normalized = min(1.0, diversity / _MAX_DIVERSITY_TIERS)
        return ZoneCandidate(
            price=avg_price,
            name="consensus",
            strength=normalized,
            source_tier="consensus",
            source_family="consensus",
        )
    return _pick_single_best(candidates, price, atr)


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------


def _find_clusters(candidates: list[ZoneCandidate], atr: float) -> list[list[ZoneCandidate]]:
    """Group sorted candidates into tight clusters (within CLUSTER_RADIUS_ATR of each other)."""
    if not candidates:
        return []
    clusters: list[list[ZoneCandidate]] = []
    current = [candidates[0]]
    radius = atr * _cluster_radius_atr()
    for c in candidates[1:]:
        if abs(c.price - current[-1].price) <= radius:
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


def _emit_metrics(result: ZoneResult, atr: float) -> None:
    ZONE_TIER_USED.add(1, {"tier": result.tier})
    ZONE_CANDIDATE_COUNT.record(result.candidate_count)
    if atr > EPSILON:
        width = result.zone_high - result.zone_low
        ZONE_WIDTH_ATR.record(width / atr)
        if result.cluster_members >= 2 and width > 0:
            density = result.cluster_members / max(width / atr, 0.01)
            ZONE_CLUSTER_DENSITY.record(density)


def _resolve_zone(
    features: dict[str, Any],
    direction: int,
    entry: float,
    stop: float,
    atr: float,
) -> ZoneResult:
    candidates = collect_candidates(features, direction, entry, stop)

    if not candidates:
        return ZoneResult(
            zone_low=0.0,
            zone_high=0.0,
            tier="atr",
            source="atr_fallback",
            candidate_count=0,
            cluster_members=0,
        )

    # Tier 1: Confluence cluster (requires ≥2 distinct source_tiers)
    clusters = _find_clusters(candidates, atr)
    diverse = [cl for cl in clusters if _source_diversity(cl) >= 2]
    if diverse:
        best = max(diverse, key=lambda cl: _score_cluster(cl, atr))
        low = best[0].price - atr * _zone_buffer_atr()
        high = best[-1].price + atr * _zone_buffer_atr()
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

    # Tier 3: No usable structure — caller applies ATR bounds
    return ZoneResult(
        zone_low=0.0,
        zone_high=0.0,
        tier="atr",
        source="atr_fallback",
        candidate_count=len(candidates),
        cluster_members=0,
    )


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
    result = _resolve_zone(features, direction, entry, stop, atr)
    _emit_metrics(result, atr)
    return result
