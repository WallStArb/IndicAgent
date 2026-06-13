"""Tests for module-level config getter functions in confidence_utils and volume_profile_utils."""

from __future__ import annotations

from unittest.mock import MagicMock

import src.intelligence.trading.confidence_utils as cu
import src.intelligence.trading.volume_profile_utils as vpu


def _make_cfg(return_val):
    cfg = MagicMock()
    cfg.get_sync.return_value = return_val
    return cfg


def teardown_function():
    cu.set_config_service(None)
    vpu.set_config_service(None)


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
