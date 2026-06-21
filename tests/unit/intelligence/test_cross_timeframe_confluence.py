"""Tests for CrossTimeframeConfluencePlugin core behavior.

Phase 46.1 note: VIX and cross-asset fields were moved from I6Confluence
to I4Context (VIXRegimePlugin and CrossAssetContextPlugin). Tests for
those fields are in test_vix_regime.py and test_cross_asset_context.py.
"""

import pytest

from src.intelligence.archive.confluence.cross_timeframe import CrossTimeframeConfluencePlugin


@pytest.fixture
def plugin():
    return CrossTimeframeConfluencePlugin()


def _base_frames() -> dict:
    """Minimal frames with at least one intel_* key so the plugin does not early-return."""
    return {
        "i1": {"trend_direction": 1, "ema_20": 100.0},
        "i2": {"trend_direction": 1, "ema_20": 100.0},
        "i3": {"trend_direction": 1, "ema_20": 100.0},
        "i4": {"trend_direction": 1, "ema_20": 100.0},
        "i5": {"trend_direction": 1, "ema_20": 100.0},
        "smc": {"trend_direction": 1, "ema_20": 100.0},
        "i6": {"trend_direction": 1, "ema_20": 100.0},
        "timeframe": "1m",
        "intel_5m": {"trend_direction": 1},
    }


# ─── ctf_score stability test ────────────────────────────────────────────────


def test_ctf_score_unchanged_with_extra_frames(plugin):
    """ctf_score is identical whether or not extra frames (vix, cross_asset) are present.

    VIX and cross-asset data now flow through I4 plugins (VIXRegimePlugin,
    CrossAssetContextPlugin), not through I6. Passing them in frames should
    have no effect on the ctf_score output.
    """
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


def test_vix_and_cross_asset_not_in_i6_output(plugin):
    """VIX and cross-asset fields must NOT appear in CrossTimeframeConfluencePlugin output.

    These fields belong to I4 (Phase 46.1 migration) — they should not be
    emitted by I6.
    """
    frames = _base_frames()
    frames["vix"] = {"ready": True, "level": 18.5, "z_score": -0.32}
    frames["cross_asset"] = {
        "ready": True,
        "active_pair": "ES_NQ",
        "es_nq_spread_z": 2.3,
        "pairs_confirming": 1,
    }
    result = plugin.compute_full(frames)
    assert "ctf_vix_level" not in result
    assert "ctf_vix_z" not in result
    assert "ctf_eq_spread_z" not in result
    assert "ctf_eq_pairs_confirming" not in result


def test_i6_does_not_emit_vix_or_eq_fields(plugin):
    """After Phase 46.1, I6 is pure cross-TF alignment — no VIX/EQ pass-through.

    Checks the outputs frozenset (contract) — runtime check is in test_vix_and_cross_asset_not_in_i6_output.
    """
    assert "ctf_vix_level" not in plugin.outputs
    assert "ctf_vix_z" not in plugin.outputs
    assert "ctf_eq_spread_z" not in plugin.outputs
    assert "ctf_eq_pairs_confirming" not in plugin.outputs
