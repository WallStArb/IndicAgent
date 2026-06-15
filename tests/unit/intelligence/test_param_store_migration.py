"""Tests for module-level config getter functions in confidence_utils and volume_profile_utils."""

from __future__ import annotations

from unittest.mock import MagicMock

import src.intelligence.trading.aggregator as agg
import src.intelligence.trading.confidence_utils as cu
import src.intelligence.trading.volume_profile_utils as vpu
import src.intelligence.trading.zone_engine as ze


def _make_cfg(return_val):
    cfg = MagicMock()
    cfg.get_sync.return_value = return_val
    return cfg


def teardown_function():
    cu.set_config_service(None)
    vpu.set_config_service(None)
    agg.set_config_service(None)
    ze.set_config_service(None)


def test_get_min_regime_weight_returns_config_value():
    cu.set_config_service(_make_cfg(0.45))
    assert cu.get_min_regime_weight() == 0.45


def test_get_min_regime_weight_returns_constant_when_no_config():
    assert cu.get_min_regime_weight() == cu.MIN_REGIME_WEIGHT


def test_get_min_ctf_score_returns_config_value():
    cu.set_config_service(_make_cfg(0.30))
    assert cu.get_min_ctf_score() == 0.30


def test_get_min_ctf_score_returns_constant_when_no_config():
    assert cu.get_min_ctf_score() == cu.MIN_CTF_SCORE


def test_get_div_threshold_returns_config_value():
    vpu.set_config_service(_make_cfg(0.4))
    assert vpu.get_div_threshold() == 0.4


def test_get_div_threshold_returns_constant_when_no_config():
    assert vpu.get_div_threshold() == vpu.DIV_THRESHOLD


def test_get_stoch_oversold_returns_config_value():
    vpu.set_config_service(_make_cfg(25.0))
    assert vpu.get_stoch_oversold() == 25.0


def test_get_stoch_overbought_returns_config_value():
    vpu.set_config_service(_make_cfg(75.0))
    assert vpu.get_stoch_overbought() == 75.0


def test_get_regime_tiebreak_returns_config_value():
    agg.set_config_service(_make_cfg(0.55))
    assert agg._get_regime_tiebreak() == 0.55
    agg.set_config_service(None)


def test_get_regime_tiebreak_returns_constant_when_no_config():
    assert agg._get_regime_tiebreak() == agg._REGIME_TIEBREAK_THRESHOLD


def test_zone_cluster_radius_returns_config_value():
    ze.set_config_service(_make_cfg(0.75))
    assert ze._cluster_radius_atr() == 0.75
    ze.set_config_service(None)


def test_zone_cluster_radius_returns_constant_when_no_config():
    assert ze._cluster_radius_atr() == ze.CLUSTER_RADIUS_ATR


def test_zone_strength_weight_returns_config_value():
    ze.set_config_service(_make_cfg(0.7))
    assert ze._strength_weight() == 0.7
    ze.set_config_service(None)


# ---------------------------------------------------------------------------
# _validate_weights_sum tests
# ---------------------------------------------------------------------------

import pytest

from src.intelligence.trading.confidence_utils import _validate_weights_sum


def test_validate_weights_sum_passes_on_exact():
    _validate_weights_sum({"a": 0.40, "b": 0.35, "c": 0.25}, "TestPlugin")


def test_validate_weights_sum_passes_within_tolerance():
    # 0.4+0.3+0.3 may not be exactly 1.0 due to float repr; must pass
    _validate_weights_sum({"a": 0.4, "b": 0.3, "c": 0.3}, "TestPlugin")


def test_validate_weights_sum_raises_on_bad_seed():
    with pytest.raises(ValueError, match="TestPlugin weights sum to"):
        _validate_weights_sum({"a": 0.40, "b": 0.40, "c": 0.25}, "TestPlugin")


def test_validate_weights_sum_raises_value_error_not_assertion_error():
    """ValueError must fire even under Python -O (which disables asserts)."""
    with pytest.raises(ValueError):
        _validate_weights_sum({"a": 0.60, "b": 0.60}, "BadPlugin")
