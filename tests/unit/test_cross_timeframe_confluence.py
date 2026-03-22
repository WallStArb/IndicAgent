"""Tests for CrossTimeframeConfluencePlugin VIX and cross-asset field emission (Phase 46)."""

import pytest

from src.intelligence.confluence.cross_timeframe import CrossTimeframeConfluencePlugin


@pytest.fixture
def plugin():
    return CrossTimeframeConfluencePlugin()


def _base_frames() -> dict:
    """Minimal frames with at least one intel_* key so the plugin does not early-return."""
    return {
        "features": {"trend_direction": 1, "ema_20": 100.0},
        "timeframe": "1m",
        "intel_5m": {"trend_direction": 1},
    }


# ─── VIX field tests ────────────────────────────────────────────────────────


def test_vix_ready_populates_level_and_z(plugin):
    """frames['vix'] with ready=True → ctf_vix_level and ctf_vix_z populated."""
    frames = _base_frames()
    frames["vix"] = {"ready": True, "level": 18.5, "z_score": -0.32}
    result = plugin.compute_full(frames)
    assert result["ctf_vix_level"] == 18.5
    assert result["ctf_vix_z"] == -0.32


def test_vix_not_ready_returns_none(plugin):
    """frames['vix'] with ready=False → ctf_vix_level=None, ctf_vix_z=None."""
    frames = _base_frames()
    frames["vix"] = {"ready": False}
    result = plugin.compute_full(frames)
    assert result["ctf_vix_level"] is None
    assert result["ctf_vix_z"] is None


def test_vix_key_absent_returns_none(plugin):
    """No frames['vix'] key → ctf_vix_level=None, ctf_vix_z=None."""
    frames = _base_frames()
    # Do NOT add 'vix' key
    result = plugin.compute_full(frames)
    assert result["ctf_vix_level"] is None
    assert result["ctf_vix_z"] is None


# ─── Cross-asset field tests ─────────────────────────────────────────────────


def test_cross_asset_es_nq_pair_populates_fields(plugin):
    """frames['cross_asset'] with active_pair='ES_NQ' → ctf_eq_spread_z from es_nq_spread_z."""
    frames = _base_frames()
    frames["cross_asset"] = {
        "ready": True,
        "active_pair": "ES_NQ",
        "es_nq_spread_z": 2.3,
        "pairs_confirming": 1,
    }
    result = plugin.compute_full(frames)
    assert result["ctf_eq_spread_z"] == 2.3
    assert result["ctf_eq_pairs_confirming"] == 1.0


def test_cross_asset_es_rty_pair_populates_fields(plugin):
    """frames['cross_asset'] with active_pair='ES_RTY' → ctf_eq_spread_z from es_rty_spread_z."""
    frames = _base_frames()
    frames["cross_asset"] = {
        "ready": True,
        "active_pair": "ES_RTY",
        "es_rty_spread_z": -1.8,
        "pairs_confirming": 2,
    }
    result = plugin.compute_full(frames)
    assert result["ctf_eq_spread_z"] == -1.8
    assert result["ctf_eq_pairs_confirming"] == 2.0


def test_cross_asset_not_ready_returns_none(plugin):
    """frames['cross_asset'] with ready=False → ctf_eq_spread_z=None, ctf_eq_pairs_confirming=None."""
    frames = _base_frames()
    frames["cross_asset"] = {"ready": False}
    result = plugin.compute_full(frames)
    assert result["ctf_eq_spread_z"] is None
    assert result["ctf_eq_pairs_confirming"] is None


def test_cross_asset_key_absent_returns_none(plugin):
    """No frames['cross_asset'] key → ctf_eq_spread_z=None, ctf_eq_pairs_confirming=None."""
    frames = _base_frames()
    # Do NOT add 'cross_asset' key
    result = plugin.compute_full(frames)
    assert result["ctf_eq_spread_z"] is None
    assert result["ctf_eq_pairs_confirming"] is None


# ─── ctf_score stability test ────────────────────────────────────────────────


def test_ctf_score_unchanged_with_vix_and_cross_asset(plugin):
    """ctf_score is bit-for-bit identical with and without VIX/cross-asset frames."""
    frames_without = _base_frames()
    result_without = plugin.compute_full(frames_without)

    frames_with = _base_frames()
    frames_with["vix"] = {"ready": True, "level": 20.0, "z_score": 0.5}
    frames_with["cross_asset"] = {
        "ready": True,
        "active_pair": "ES_NQ",
        "es_nq_spread_z": 1.5,
        "pairs_confirming": 1,
    }
    result_with = plugin.compute_full(frames_with)

    assert result_with["ctf_score"] == result_without["ctf_score"]
    assert result_with["ctf_trend_alignment"] == result_without["ctf_trend_alignment"]
    assert result_with["ctf_structure_alignment"] == result_without["ctf_structure_alignment"]
    assert result_with["ctf_regime_agreement"] == result_without["ctf_regime_agreement"]
