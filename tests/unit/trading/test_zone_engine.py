import pytest

from src.intelligence.trading.zone_engine import (
    ZoneCandidate,
    ZoneResult,
    collect_candidates,
    collect_sr_candidates,
    find_best_level,
    resolve_structural_zone,
)

# --- collect_candidates tests ---


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


def test_dedup_same_family_keeps_one():
    """nearest_support and sr_nearest_support are same source_family — dedup keeps one."""
    features = {
        "nearest_support": 99.5,
        "sr_nearest_support": 99.51,
        "atr_14": 0.5,
        "timeframe": "1m",
    }
    candidates = collect_candidates(features, direction=1, entry=100.0, stop=98.0)
    sr_cands = [c for c in candidates if c.source_family == "sr"]
    assert len(sr_cands) == 1


def test_htf_vp_uses_rolling_fields():
    """For 15m+, VP fields use poc_price_rolling not poc_price (session)."""
    features = {
        "poc_price": 100.0,
        "poc_price_rolling": 99.5,
        "atr_14": 0.5,
        "timeframe": "15m",
    }
    candidates = collect_candidates(features, direction=1, entry=100.5, stop=98.0)
    prices = [c.price for c in candidates]
    assert 99.5 in prices
    assert 100.0 not in prices


# --- resolve_structural_zone tests ---


def _feat(**overrides):
    base = {
        "atr_14": 0.5,
        "timeframe": "1m",
        "nearest_support": 0.0,
        "sr_nearest_support": 0.0,
        "swing_low": 0.0,
        "nearest_demand_high": 0.0,
        "ema_21": 0.0,
        "sma_50": 0.0,
        "ssl_level": 0.0,
        "overnight_low": 0.0,
        "nearest_resistance": 0.0,
        "sr_nearest_resistance": 0.0,
        "swing_high": 0.0,
        "nearest_supply_low": 0.0,
        "bsl_level": 0.0,
        "overnight_high": 0.0,
        "poc_price": 0.0,
        "val": 0.0,
        "vah": 0.0,
        "nearest_hvn_below": 0.0,
        "nearest_hvn_above": 0.0,
        "poc_price_rolling": 0.0,
        "val_rolling": 0.0,
        "vah_rolling": 0.0,
    }
    base.update(overrides)
    return base


def test_confluence_cluster_with_diverse_sources():
    """3 candidates from different source_tiers → confluence tier."""
    f = _feat(swing_low=99.5, ema_21=99.52, poc_price=99.48)
    result = resolve_structural_zone(f, direction=1, entry=100.0, stop=98.0, atr=0.5)
    assert result.tier == "confluence"
    assert result.cluster_members >= 3


def test_no_confluence_after_dedup_same_family():
    """nearest_support + sr_nearest_support dedup to 1 → falls to single."""
    f = _feat(nearest_support=99.5, sr_nearest_support=99.51)
    result = resolve_structural_zone(f, direction=1, entry=100.0, stop=98.0, atr=0.5)
    assert result.tier in ("single", "atr")


def test_single_level_isolated():
    f = _feat(swing_low=99.0)
    result = resolve_structural_zone(f, direction=1, entry=100.0, stop=98.0, atr=0.5)
    assert result.tier == "single"
    assert "swing_low" in result.source


def test_atr_fallback_no_candidates():
    f = _feat()
    result = resolve_structural_zone(f, direction=1, entry=100.0, stop=98.0, atr=0.5)
    assert result.tier == "atr"
    assert result.candidate_count == 0


def test_excludes_candidates_outside_stop_entry():
    """Level below stop is excluded."""
    f = _feat(nearest_support=97.5)  # below stop=98.0
    result = resolve_structural_zone(f, direction=1, entry=100.0, stop=98.0, atr=0.5)
    assert result.tier == "atr"


def test_minimum_zone_width_enforced():
    """Two levels very close together → zone width >= 0.25 * ATR."""
    f = _feat(swing_low=99.995, ema_21=100.005)
    result = resolve_structural_zone(f, direction=1, entry=100.5, stop=98.0, atr=0.5)
    width = result.zone_high - result.zone_low
    assert width >= 0.25 * 0.5


def test_zone_result_has_all_fields():
    f = _feat(swing_low=99.0)
    result = resolve_structural_zone(f, direction=1, entry=100.0, stop=98.0, atr=0.5)
    assert isinstance(result, ZoneResult)
    assert result.zone_low <= result.zone_high or result.tier == "atr"
    assert result.tier in ("confluence", "single", "atr")
    assert isinstance(result.source, str)
    assert isinstance(result.candidate_count, int)
    assert isinstance(result.cluster_members, int)


# --- collect_sr_candidates tests ---


def _sr_feat(**overrides):
    """Minimal feature dict for collect_sr_candidates tests."""
    base = {
        "atr_14": 9.0,
        "timeframe": "1m",
        "nearest_fib_level": 0.0,
        "prior_session_low": 0.0,
        "asian_session_low": 0.0,
        "nearest_hvn_below": 0.0,
        "avwap_lower_band": 0.0,
        "kc_mid_20": 0.0,
        "prior_session_high": 0.0,
        "asian_session_high": 0.0,
        "nearest_hvn_above": 0.0,
        "avwap_upper_band": 0.0,
        "poc_price": 0.0,
        "val": 0.0,
        "vah": 0.0,
        "nearest_hvn_dist_atr": 0.0,
        "poc_price_rolling": 0.0,
        "val_rolling": 0.0,
        "vah_rolling": 0.0,
    }
    base.update(overrides)
    return base


def test_collect_sr_candidates_support_vp_direction():
    """direction=-1 (support): val (below price) appears; vah (above price) does NOT."""
    feats = _sr_feat(val=7380.0, vah=7420.0)
    candidates = collect_sr_candidates(feats, direction=-1, price=7400.0, atr=9.0, max_dist=36.0)
    prices = [c.price for c in candidates]
    # val is below price — must appear in support candidates
    assert any(abs(p - 7380.0) < 0.1 for p in prices), f"val missing from support: {prices}"
    # vah is above price — must NOT appear in support candidates
    assert not any(
        abs(p - 7420.0) < 0.1 for p in prices
    ), f"vah must not appear in support: {prices}"


def test_collect_sr_candidates_resistance_vp_direction():
    """direction=1 (resistance): vah (above price) appears; val (below price) does NOT."""
    feats = _sr_feat(val=7380.0, vah=7420.0)
    candidates = collect_sr_candidates(feats, direction=1, price=7400.0, atr=9.0, max_dist=36.0)
    prices = [c.price for c in candidates]
    # vah is above price — must appear in resistance candidates
    assert any(abs(p - 7420.0) < 0.1 for p in prices), f"vah missing from resistance: {prices}"
    # val is below price — must NOT appear in resistance candidates
    assert not any(
        abs(p - 7380.0) < 0.1 for p in prices
    ), f"val must not appear in resistance: {prices}"


def test_collect_sr_candidates_support_bounds():
    """Support candidates fall strictly in [price - max_dist, price]."""
    feats = _sr_feat(nearest_fib_level=7390.0)
    candidates = collect_sr_candidates(feats, direction=-1, price=7400.0, atr=9.0, max_dist=36.0)
    fib_cands = [c for c in candidates if c.name == "fib"]
    assert fib_cands, "nearest_fib_level should appear as support candidate"
    assert all(
        7364.0 < c.price < 7400.0 for c in candidates
    ), f"out of support bounds: {[c.price for c in candidates]}"


def test_collect_sr_candidates_resistance_bounds():
    """Resistance candidates fall strictly in [price, price + max_dist]."""
    feats = _sr_feat(nearest_fib_level=7420.0)
    candidates = collect_sr_candidates(feats, direction=1, price=7400.0, atr=9.0, max_dist=36.0)
    fib_cands = [c for c in candidates if c.name == "fib"]
    assert fib_cands, "nearest_fib_level should appear as resistance candidate"
    assert all(
        7400.0 < c.price < 7436.0 for c in candidates
    ), f"out of resistance bounds: {[c.price for c in candidates]}"


def test_collect_sr_candidates_max_dist_exclusion():
    """A feature exactly at price + max_dist + 1 is excluded."""
    feats = _sr_feat(nearest_fib_level=7437.0)  # 7400 + 36 + 1
    candidates = collect_sr_candidates(feats, direction=1, price=7400.0, atr=9.0, max_dist=36.0)
    assert not any(
        abs(c.price - 7437.0) < 0.1 for c in candidates
    ), "out-of-range level must be excluded"


def test_collect_sr_candidates_invalid_direction():
    """direction=0 raises ValueError."""
    feats = _sr_feat(nearest_fib_level=7390.0)
    with pytest.raises(ValueError, match="direction must be 1 or -1"):
        collect_sr_candidates(feats, direction=0, price=7400.0, atr=9.0, max_dist=36.0)


# --- find_best_level tests ---


def test_find_best_level_empty_returns_none():
    assert find_best_level([], atr=9.0, price=7400.0) is None


def test_find_best_level_single_candidate_returns_candidate():
    cands = [
        ZoneCandidate(price=7390.0, name="fib", strength=0.6, source_tier="i3", source_family="fib")
    ]
    result = find_best_level(cands, atr=9.0, price=7400.0)
    assert result is not None
    assert isinstance(result, ZoneCandidate)


def test_find_best_level_multi_source_consensus():
    """2+ source_tiers within 0.5 ATR -> consensus ZoneCandidate with mean price."""
    # 4.5 = 0.5 * 9.0 ATR cluster radius; put candidates within that window
    cands = [
        ZoneCandidate(
            price=7390.0, name="fib", strength=0.6, source_tier="i3", source_family="fib"
        ),
        ZoneCandidate(
            price=7391.0, name="swing_low", strength=0.7, source_tier="i3", source_family="swing"
        ),
        ZoneCandidate(
            price=7392.0, name="hvn_below", strength=0.8, source_tier="i4", source_family="vp_hvn"
        ),
    ]
    result = find_best_level(cands, atr=9.0, price=7400.0)
    assert result is not None
    assert result.name == "consensus", f"expected consensus, got {result.name!r}"
    expected_price = (7390.0 + 7391.0 + 7392.0) / 3
    assert (
        abs(result.price - expected_price) < 0.01
    ), f"expected mean price {expected_price}, got {result.price}"
