"""Unit tests for src.intelligence.trading.structural_confluence (Phase 166 Part 1).

Fixtures use ONLY Phase-163 live feature_vectors field names -- never v2.x
zone_engine.py names (Pitfall 3 regression guard, see Task 2's tests below).
"""

import pytest

from src.intelligence.trading.structural_confluence import (
    ZoneCandidate,
    ZoneResult,
    _find_clusters,
    _pick_single_best,
    _resolve_strength,
    _resolve_zone,
    _score_cluster,
    collect_candidates,
    resolve_structural_zone,
)

# --- Task 1: generic clustering/scoring core ---


def test_find_clusters_groups_within_radius_and_drops_singletons():
    """Test 1: _find_clusters groups candidates within cluster_radius_atr and
    drops singletons (len < 2)."""
    candidates = [
        ZoneCandidate(price=100.0, name="a", strength=0.7, source_tier="sr", source_family="sr"),
        ZoneCandidate(price=100.1, name="b", strength=0.7, source_tier="vp", source_family="vp"),
        # isolated singleton -- far outside cluster_radius_atr (0.5 default) * atr (1.0) = 0.5
        ZoneCandidate(price=110.0, name="c", strength=0.7, source_tier="sr", source_family="sr"),
    ]
    clusters = _find_clusters(candidates, atr=1.0)
    assert len(clusters) == 1
    assert len(clusters[0]) == 2
    assert {c.name for c in clusters[0]} == {"a", "b"}


def test_score_cluster_rewards_strength_and_diversity_penalizes_width():
    """Test 2: _score_cluster rewards strength-sum x source-tier diversity,
    penalizes width."""
    tight_diverse = [
        ZoneCandidate(price=100.0, name="a", strength=0.7, source_tier="sr", source_family="sr"),
        ZoneCandidate(price=100.05, name="b", strength=0.7, source_tier="vp", source_family="vp"),
    ]
    wide_single_tier = [
        ZoneCandidate(price=100.0, name="a", strength=0.7, source_tier="sr", source_family="sr"),
        ZoneCandidate(price=100.4, name="b", strength=0.7, source_tier="sr", source_family="sr"),
    ]
    score_tight_diverse = _score_cluster(tight_diverse, atr=1.0)
    score_wide_single_tier = _score_cluster(wide_single_tier, atr=1.0)
    assert score_tight_diverse > score_wide_single_tier


def test_pick_single_best_returns_highest_strength_times_proximity():
    """Test 3: _pick_single_best returns the highest strength x proximity
    candidate."""
    near_weak = ZoneCandidate(
        price=100.4, name="near_weak", strength=0.3, source_tier="sr", source_family="sr"
    )
    far_strong = ZoneCandidate(
        price=99.0, name="far_strong", strength=0.95, source_tier="sr", source_family="sr"
    )
    best = _pick_single_best([near_weak, far_strong], entry=100.5, atr=1.0)
    assert best is not None
    assert best.name == "far_strong"


def test_resolve_zone_prefers_diverse_cluster_over_single_level():
    """Test 4a: 3-tier resolution prefers a diverse cluster (>=2 distinct
    source_tier) over a single level."""
    diverse_cluster = [
        ZoneCandidate(
            price=99.0, name="sr_support", strength=0.7, source_tier="sr", source_family="sr"
        ),
        ZoneCandidate(price=99.05, name="poc", strength=0.8, source_tier="vp", source_family="vp"),
        ZoneCandidate(
            price=95.0, name="isolated", strength=0.9, source_tier="sr", source_family="sr"
        ),
    ]
    result = _resolve_zone(diverse_cluster, entry=100.0, atr=1.0)
    assert isinstance(result, ZoneResult)
    assert result.tier == "confluence"
    assert result.cluster_members == 2


def test_resolve_zone_empty_candidates_returns_atr_tier():
    """Test 4b: returns tier="atr" empty result when no candidates exist."""
    result = _resolve_zone([], entry=100.0, atr=1.0)
    assert result.tier == "atr"
    assert result.zone_low == 0.0
    assert result.zone_high == 0.0
    assert result.candidate_count == 0


# --- Task 2: v3 spec table + collect_candidates + public API ---


def test_collect_candidates_emits_sr_support_from_dist_field():
    """Test 5: collect_candidates(features, direction=1, entry, stop, atr) with a
    synthetic features dict containing sr_support_dist emits an S/R support
    candidate at the reconstructed price entry - sr_support_dist*atr (long),
    between stop and entry."""
    features = {"sr_support_dist": 1.0}
    candidates = collect_candidates(features, direction=1, entry=100.0, stop=95.0, atr=1.0)
    sr_candidates = [c for c in candidates if c.name == "sr_support"]
    assert len(sr_candidates) == 1
    assert sr_candidates[0].price == pytest.approx(99.0)
    assert 95.0 < sr_candidates[0].price < 100.0
    assert sr_candidates[0].source_tier == "sr"


def test_collect_candidates_reconstructs_vp_prices():
    """Test 6: VP fields (poc_dist_atr / distance_to_vah_atr / distance_to_val_atr)
    reconstruct POC/VAH/VAL price candidates via entry +/- dist*atr."""
    features = {
        "poc_dist_atr": 0.5,  # poc = entry - 0.5*atr = 99.5
        "distance_to_val_atr": 1.5,  # val = entry - 1.5*atr = 98.5
    }
    candidates = collect_candidates(features, direction=1, entry=100.0, stop=95.0, atr=1.0)
    by_name = {c.name: c.price for c in candidates}
    assert by_name["poc"] == pytest.approx(99.5)
    assert by_name["val"] == pytest.approx(98.5)


def test_resolve_strength_decays_to_default_when_absent():
    """Test 7a: absent companion strength/age fields -> the spec default."""
    assert _resolve_strength({}, "sr_support", 0.7) == 0.7


def test_resolve_strength_uses_companion_strength_field():
    """Test 7b: support_strength present -> normalized (clamped to 1.0),
    distinct from the spec default."""
    result = _resolve_strength({"support_strength": 1.5}, "sr_support", 0.7)
    assert result == pytest.approx(1.0)
    assert result != 0.7


def test_resolve_structural_zone_confluence_from_vp_and_sr():
    """Test 8: a VP level and an S/R level clustering within cluster_radius_atr
    -> confluence tier with 2 distinct source_tier ("vp" and "sr")."""
    features = {
        "sr_support_dist": 1.0,  # support = 99.0
        "poc_dist_atr": 0.95,  # poc = 99.05, within 0.5 ATR cluster radius of 99.0
    }
    result = resolve_structural_zone(features, direction=1, entry=100.0, stop=95.0, atr=1.0)
    assert result.tier == "confluence"
    assert result.cluster_members == 2


def test_resolve_structural_zone_all_none_features_yields_atr_tier():
    """Test 9 (Pitfall 3 regression guard): a features dict missing ALL
    Phase-163 fields (all None) yields zero candidates -> tier="atr"."""
    features = {
        "sr_support_dist": None,
        "sr_resist_dist": None,
        "poc_dist_atr": None,
        "poc_rolling_dist_atr": None,
        "distance_to_vah_atr": None,
        "distance_to_val_atr": None,
    }
    result = resolve_structural_zone(features, direction=1, entry=100.0, stop=95.0, atr=1.0)
    assert result.tier == "atr"
    assert result.candidate_count == 0
