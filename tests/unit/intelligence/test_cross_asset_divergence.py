"""Unit tests for CrossAssetDivergencePlugin.

Tests all fire/no-fire conditions, direction logic, and confidence formula.
frame_trade is mocked so tests focus on plugin logic only.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from src.intelligence.archive.trading_i7.cross_asset_divergence import (
    CrossAssetDivergencePlugin,
    plugin,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_df(n: int = 30, close: float = 5000.0) -> pd.DataFrame:
    """Build a minimal DataFrame for frame_trade calls."""
    return pd.DataFrame(
        {
            "open": [close] * n,
            "high": [close + 5] * n,
            "low": [close - 5] * n,
            "close": [close] * n,
            "volume": [1000.0] * n,
        }
    )


def _base_features(symbol: str = "ESM6", close: float = 5000.0) -> dict:
    return {
        "symbol": symbol,
        "atr_14": 10.0,
        "close_price": close,
        "hmm_regime": 0,
        "hmm_regime_prob": 0.5,
    }


def _base_xa(
    es_nq_z: float = 3.0,
    es_rty_z: float = 1.0,
    active_pair: str = "ES_NQ",
    pairs_confirming: int = 1,
    eq_vol_imbalance: float = 1.0,
    low_vol_flag: bool = False,
    ready: bool = True,
) -> dict:
    return {
        "ready": ready,
        "es_nq_spread_z": es_nq_z,
        "es_rty_spread_z": es_rty_z,
        "eq_corr_break": 0.2,
        "eq_vol_imbalance": eq_vol_imbalance,
        "active_pair": active_pair,
        "pairs_confirming": pairs_confirming,
        "data_quality_score": 1.0,
        "low_vol_flag": low_vol_flag,
    }


def _mock_frame(entry: float = 5000.0, direction: int = 1) -> MagicMock:
    """Return a mock TradeFrame that is viable with direction-correct stop and targets."""
    offset = 1 if direction == 1 else -1
    t1, t2, t3 = MagicMock(), MagicMock(), MagicMock()
    t1.price = entry + offset * 20.0
    t2.price = entry + offset * 35.0
    t3.price = entry + offset * 55.0
    frame = MagicMock()
    frame.viable = True
    frame.entry = entry
    frame.stop = entry - offset * 10.0
    frame.targets = [t1, t2, t3]
    frame.stop_basis = "atr_static"
    return frame


def _direction_for(hmm_regime: int | None, spread_z: float) -> int:
    """Compute expected signal direction — mirrors plugin logic for building correct mock frames."""
    spread_positive = spread_z > 0
    if hmm_regime == 1:
        return 1 if spread_positive else -1
    if hmm_regime == 2:
        return -1 if spread_positive else 1
    return -1 if spread_positive else 1  # regime 0 + unknown: reversion


# ---------------------------------------------------------------------------
# Module-level plugin instance checks
# ---------------------------------------------------------------------------


class TestPluginAttributes:
    def test_plugin_name(self):
        assert plugin.name == "trad_CrossAssetDivergence"

    def test_plugin_regime_type(self):
        assert plugin.regime_type == "any"

    def test_plugin_is_stateless(self):
        """Plugin must NOT have a _state dict — fully stateless."""
        assert not hasattr(plugin, "_state")

    def test_plugin_has_outputs(self):
        # Output fields updated to standard signal.v1 names (44-04)
        expected = {
            "signal_type",
            "direction",
            "confidence",
            "entry_price",
            "stop_loss",
            "targets",
            "regime_context",
            "setup_variant",
            "supporting_factors",
            "stop_basis",
        }
        assert expected.issubset(plugin.outputs)

    def test_plugin_no_signal_shape(self):
        ns = plugin._no_signal()
        assert ns == {"signal_type": "none", "direction": 0, "confidence": 0.0}


# ---------------------------------------------------------------------------
# Guard: non-EQ_INDEX symbol
# ---------------------------------------------------------------------------


class TestNoSignalNonEQIndex:
    def test_no_signal_cl_symbol(self):
        """CLM6 (crude oil) must return _no_signal — not in EQ_INDEX group."""
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": _base_features(symbol="CLM6"),
            "i2": _base_features(symbol="CLM6"),
            "i3": _base_features(symbol="CLM6"),
            "i4": _base_features(symbol="CLM6"),
            "i5": _base_features(symbol="CLM6"),
            "smc": _base_features(symbol="CLM6"),
            "i6": _base_features(symbol="CLM6"),
            "cross_asset": _base_xa(es_nq_z=3.5),
            "main": _make_df(),
        }
        result = p.compute_full(frames)
        assert result["signal_type"] == "none"
        assert result["direction"] == 0

    def test_no_signal_gc_symbol(self):
        """GCM6 (gold) must return _no_signal."""
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": _base_features(symbol="GCM6"),
            "i2": _base_features(symbol="GCM6"),
            "i3": _base_features(symbol="GCM6"),
            "i4": _base_features(symbol="GCM6"),
            "i5": _base_features(symbol="GCM6"),
            "smc": _base_features(symbol="GCM6"),
            "i6": _base_features(symbol="GCM6"),
            "cross_asset": _base_xa(es_nq_z=3.5),
            "main": _make_df(),
        }
        result = p.compute_full(frames)
        assert result["signal_type"] == "none"

    def test_no_signal_empty_symbol(self):
        """Empty symbol must return _no_signal."""
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": {"symbol": "", "atr_14": 10.0},
            "i2": {"symbol": "", "atr_14": 10.0},
            "i3": {"symbol": "", "atr_14": 10.0},
            "i4": {"symbol": "", "atr_14": 10.0},
            "i5": {"symbol": "", "atr_14": 10.0},
            "smc": {"symbol": "", "atr_14": 10.0},
            "i6": {"symbol": "", "atr_14": 10.0},
            "cross_asset": _base_xa(es_nq_z=3.5),
            "main": _make_df(),
        }
        result = p.compute_full(frames)
        assert result["signal_type"] == "none"

    def test_es_base_accepted(self):
        """ESM6 must be accepted as an EQ_INDEX symbol."""
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": _base_features(symbol="ESM6"),
            "i2": _base_features(symbol="ESM6"),
            "i3": _base_features(symbol="ESM6"),
            "i4": _base_features(symbol="ESM6"),
            "i5": _base_features(symbol="ESM6"),
            "smc": _base_features(symbol="ESM6"),
            "i6": _base_features(symbol="ESM6"),
            "cross_asset": _base_xa(es_nq_z=3.0),
            "main": _make_df(),
        }
        with patch(
            "src.intelligence.archive.trading_i7.cross_asset_divergence.frame_trade",
            return_value=_mock_frame(direction=-1),
        ):
            result = p.compute_full(frames)
        assert result["signal_type"] != "none"

    def test_nq_base_accepted(self):
        """NQM6 accepted."""
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": _base_features(symbol="NQM6"),
            "i2": _base_features(symbol="NQM6"),
            "i3": _base_features(symbol="NQM6"),
            "i4": _base_features(symbol="NQM6"),
            "i5": _base_features(symbol="NQM6"),
            "smc": _base_features(symbol="NQM6"),
            "i6": _base_features(symbol="NQM6"),
            "cross_asset": _base_xa(es_nq_z=3.0),
            "main": _make_df(),
        }
        with patch(
            "src.intelligence.archive.trading_i7.cross_asset_divergence.frame_trade",
            return_value=_mock_frame(direction=-1),
        ):
            result = p.compute_full(frames)
        assert result["signal_type"] != "none"

    def test_rty_base_accepted(self):
        """RTYM6 accepted."""
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": _base_features(symbol="RTYM6"),
            "i2": _base_features(symbol="RTYM6"),
            "i3": _base_features(symbol="RTYM6"),
            "i4": _base_features(symbol="RTYM6"),
            "i5": _base_features(symbol="RTYM6"),
            "smc": _base_features(symbol="RTYM6"),
            "i6": _base_features(symbol="RTYM6"),
            "cross_asset": _base_xa(es_nq_z=3.0),
            "main": _make_df(),
        }
        with patch(
            "src.intelligence.archive.trading_i7.cross_asset_divergence.frame_trade",
            return_value=_mock_frame(direction=-1),
        ):
            result = p.compute_full(frames)
        assert result["signal_type"] != "none"

    def test_ym_base_accepted(self):
        """YMM6 accepted."""
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": _base_features(symbol="YMM6"),
            "i2": _base_features(symbol="YMM6"),
            "i3": _base_features(symbol="YMM6"),
            "i4": _base_features(symbol="YMM6"),
            "i5": _base_features(symbol="YMM6"),
            "smc": _base_features(symbol="YMM6"),
            "i6": _base_features(symbol="YMM6"),
            "cross_asset": _base_xa(es_nq_z=3.0),
            "main": _make_df(),
        }
        with patch(
            "src.intelligence.archive.trading_i7.cross_asset_divergence.frame_trade",
            return_value=_mock_frame(direction=-1),
        ):
            result = p.compute_full(frames)
        assert result["signal_type"] != "none"


# ---------------------------------------------------------------------------
# Guard: cross_asset data not ready
# ---------------------------------------------------------------------------


class TestNoSignalNotReady:
    def test_no_signal_cross_asset_missing(self):
        """Missing cross_asset key returns _no_signal."""
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": _base_features(),
            "i2": _base_features(),
            "i3": _base_features(),
            "i4": _base_features(),
            "i5": _base_features(),
            "smc": _base_features(),
            "i6": _base_features(),
            "main": _make_df(),
        }
        result = p.compute_full(frames)
        assert result["signal_type"] == "none"

    def test_no_signal_cross_asset_not_ready(self):
        """cross_asset with ready=False returns _no_signal."""
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": _base_features(),
            "i2": _base_features(),
            "i3": _base_features(),
            "i4": _base_features(),
            "i5": _base_features(),
            "smc": _base_features(),
            "i6": _base_features(),
            "cross_asset": _base_xa(ready=False),
            "main": _make_df(),
        }
        result = p.compute_full(frames)
        assert result["signal_type"] == "none"

    def test_no_signal_empty_cross_asset(self):
        """Empty cross_asset dict returns _no_signal."""
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": _base_features(),
            "i2": _base_features(),
            "i3": _base_features(),
            "i4": _base_features(),
            "i5": _base_features(),
            "smc": _base_features(),
            "i6": _base_features(),
            "cross_asset": {},
            "main": _make_df(),
        }
        result = p.compute_full(frames)
        assert result["signal_type"] == "none"


# ---------------------------------------------------------------------------
# Guard: below threshold
# ---------------------------------------------------------------------------


class TestNoSignalBelowThreshold:
    def test_no_signal_spread_z_exactly_2(self):
        """|spread_z| == 2.0 does NOT fire (strict >)."""
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": _base_features(),
            "i2": _base_features(),
            "i3": _base_features(),
            "i4": _base_features(),
            "i5": _base_features(),
            "smc": _base_features(),
            "i6": _base_features(),
            "cross_asset": _base_xa(es_nq_z=2.0),
            "main": _make_df(),
        }
        result = p.compute_full(frames)
        assert result["signal_type"] == "none"

    def test_no_signal_spread_z_below_threshold(self):
        """spread_z = 1.5 does NOT fire."""
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": _base_features(),
            "i2": _base_features(),
            "i3": _base_features(),
            "i4": _base_features(),
            "i5": _base_features(),
            "smc": _base_features(),
            "i6": _base_features(),
            "cross_asset": _base_xa(es_nq_z=1.5),
            "main": _make_df(),
        }
        result = p.compute_full(frames)
        assert result["signal_type"] == "none"

    def test_no_signal_negative_spread_below_threshold(self):
        """spread_z = -1.9 does NOT fire."""
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": _base_features(),
            "i2": _base_features(),
            "i3": _base_features(),
            "i4": _base_features(),
            "i5": _base_features(),
            "smc": _base_features(),
            "i6": _base_features(),
            "cross_asset": _base_xa(es_nq_z=-1.9),
            "main": _make_df(),
        }
        result = p.compute_full(frames)
        assert result["signal_type"] == "none"

    def test_fires_just_above_threshold(self):
        """spread_z = 2.001 fires."""
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": _base_features(),
            "i2": _base_features(),
            "i3": _base_features(),
            "i4": _base_features(),
            "i5": _base_features(),
            "smc": _base_features(),
            "i6": _base_features(),
            "cross_asset": _base_xa(es_nq_z=2.001),
            "main": _make_df(),
        }
        with patch(
            "src.intelligence.archive.trading_i7.cross_asset_divergence.frame_trade",
            return_value=_mock_frame(direction=-1),
        ):
            result = p.compute_full(frames)
        assert result["direction"] != 0


# ---------------------------------------------------------------------------
# Guard: low_vol_flag suppression
# ---------------------------------------------------------------------------


class TestLowVolFlagSuppression:
    def test_no_signal_low_vol_flag(self):
        """low_vol_flag=True suppresses signal even with high spread_z."""
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": _base_features(),
            "i2": _base_features(),
            "i3": _base_features(),
            "i4": _base_features(),
            "i5": _base_features(),
            "smc": _base_features(),
            "i6": _base_features(),
            "cross_asset": _base_xa(es_nq_z=5.0, low_vol_flag=True),
            "main": _make_df(),
        }
        result = p.compute_full(frames)
        assert result["signal_type"] == "none"

    def test_no_suppression_low_vol_false(self):
        """low_vol_flag=False allows signal."""
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": _base_features(),
            "i2": _base_features(),
            "i3": _base_features(),
            "i4": _base_features(),
            "i5": _base_features(),
            "smc": _base_features(),
            "i6": _base_features(),
            "cross_asset": _base_xa(es_nq_z=3.0, low_vol_flag=False),
            "main": _make_df(),
        }
        with patch(
            "src.intelligence.archive.trading_i7.cross_asset_divergence.frame_trade",
            return_value=_mock_frame(direction=-1),
        ):
            result = p.compute_full(frames)
        assert result["direction"] != 0


# ---------------------------------------------------------------------------
# Direction logic — regime-biased
# ---------------------------------------------------------------------------


class TestDirectionLogic:
    """Test all regime × spread_z sign combinations."""

    def _fire(self, hmm_regime, spread_z) -> dict:
        p = CrossAssetDivergencePlugin()
        features = _base_features()
        features["hmm_regime"] = hmm_regime
        features["hmm_regime_prob"] = 0.6
        xa = _base_xa(
            es_nq_z=spread_z,
        )
        frames = {
            "i1": features,
            "i2": features,
            "i3": features,
            "i4": features,
            "i5": features,
            "smc": features,
            "i6": features,
            "cross_asset": xa,
            "main": _make_df(),
        }
        direction = _direction_for(hmm_regime, spread_z)
        with patch(
            "src.intelligence.archive.trading_i7.cross_asset_divergence.frame_trade",
            return_value=_mock_frame(direction=direction),
        ):
            return p.compute_full(frames)

    def test_fire_reversion_ranging_positive_spread(self):
        """spread_z > 2.0, hmm_regime=0 (ranging) → short ES (direction=-1, reversion)."""
        result = self._fire(hmm_regime=0, spread_z=3.0)
        assert result["direction"] == -1
        assert result["setup_variant"] == "cross_asset_reversion"

    def test_fire_reversion_ranging_negative_spread(self):
        """spread_z < -2.0, hmm_regime=0 (ranging) → long ES (direction=1, reversion)."""
        result = self._fire(hmm_regime=0, spread_z=-3.0)
        assert result["direction"] == 1
        assert result["setup_variant"] == "cross_asset_reversion"

    def test_fire_continuation_trending_up_positive_spread(self):
        """spread_z > 2.0, hmm_regime=1 (trending up) → long ES (direction=1, continuation)."""
        result = self._fire(hmm_regime=1, spread_z=3.0)
        assert result["direction"] == 1
        assert result["setup_variant"] == "cross_asset_continuation"

    def test_fire_continuation_trending_up_negative_spread(self):
        """spread_z < -2.0, hmm_regime=1 (trending up) → short ES (direction=-1, continuation)."""
        result = self._fire(hmm_regime=1, spread_z=-3.0)
        assert result["direction"] == -1
        assert result["setup_variant"] == "cross_asset_continuation"

    def test_fire_continuation_trending_down_positive_spread(self):
        """spread_z > 2.0, hmm_regime=2 (trending down) → short ES (direction=-1, continuation)."""
        result = self._fire(hmm_regime=2, spread_z=3.0)
        assert result["direction"] == -1
        assert result["setup_variant"] == "cross_asset_continuation"

    def test_fire_continuation_trending_down_negative_spread(self):
        """spread_z < -2.0, hmm_regime=2 (trending down) → long ES (direction=1, continuation)."""
        result = self._fire(hmm_regime=2, spread_z=-3.0)
        assert result["direction"] == 1
        assert result["setup_variant"] == "cross_asset_continuation"

    def test_direction_default_reversion_unknown_regime(self):
        """hmm_regime not available → defaults to reversion (conservative)."""
        p = CrossAssetDivergencePlugin()
        features = _base_features()
        features.pop("hmm_regime", None)
        features["hmm_regime_prob"] = 0.0
        frames = {
            "i1": features,
            "i2": features,
            "i3": features,
            "i4": features,
            "i5": features,
            "smc": features,
            "i6": features,
            "cross_asset": _base_xa(es_nq_z=3.0),
            "main": _make_df(),
        }
        with patch(
            "src.intelligence.archive.trading_i7.cross_asset_divergence.frame_trade",
            return_value=_mock_frame(direction=-1),
        ):
            result = p.compute_full(frames)
        assert result["direction"] == -1  # positive spread → short (reversion)
        assert result["setup_variant"] == "cross_asset_reversion"


# ---------------------------------------------------------------------------
# Active pair routing
# ---------------------------------------------------------------------------


class TestActivePairRouting:
    def test_es_rty_active_pair_uses_rty_spread(self):
        """When active_pair=ES_RTY, threshold gate uses es_rty_spread_z."""
        p = CrossAssetDivergencePlugin()
        # es_nq_z below threshold but es_rty_z above — active_pair=ES_RTY should fire
        frames = {
            "i1": _base_features(),
            "i2": _base_features(),
            "i3": _base_features(),
            "i4": _base_features(),
            "i5": _base_features(),
            "smc": _base_features(),
            "i6": _base_features(),
            "cross_asset": _base_xa(
                es_nq_z=1.5,  # below threshold
                es_rty_z=3.0,  # above threshold
                active_pair="ES_RTY",
            ),
            "main": _make_df(),
        }
        with patch(
            "src.intelligence.archive.trading_i7.cross_asset_divergence.frame_trade",
            return_value=_mock_frame(direction=-1),
        ):
            result = p.compute_full(frames)
        assert result["direction"] != 0

    def test_es_nq_active_pair_below_threshold_no_fire(self):
        """When active_pair=ES_NQ and es_nq_z <= 2.0, does NOT fire even if es_rty_z is high."""
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": _base_features(),
            "i2": _base_features(),
            "i3": _base_features(),
            "i4": _base_features(),
            "i5": _base_features(),
            "smc": _base_features(),
            "i6": _base_features(),
            "cross_asset": _base_xa(
                es_nq_z=1.8,  # below threshold
                es_rty_z=5.0,  # high but not the active pair
                active_pair="ES_NQ",
            ),
            "main": _make_df(),
        }
        result = p.compute_full(frames)
        assert result["signal_type"] == "none"


# ---------------------------------------------------------------------------
# Confidence formula
# ---------------------------------------------------------------------------


class TestConfidenceFormula:
    """Verify exact confidence values with controlled inputs."""

    def _confidence(self, xa: dict, features: dict | None = None) -> float:
        p = CrossAssetDivergencePlugin()
        f = features or _base_features()
        frames = {
            "i1": f,
            "i2": f,
            "i3": f,
            "i4": f,
            "i5": f,
            "smc": f,
            "i6": f,
            "cross_asset": xa,
            "main": _make_df(),
        }
        with patch(
            "src.intelligence.archive.trading_i7.cross_asset_divergence.frame_trade",
            return_value=_mock_frame(direction=-1),
        ):
            result = p.compute_full(frames)
        return result["confidence"]

    def test_confidence_base_formula(self):
        """base = 0.55 + (|spread_z| - 2.0) * 0.05 for spread_z=3.0: 0.55 + 0.05 = 0.60."""
        xa = _base_xa(
            es_nq_z=3.0,
            pairs_confirming=1,
            eq_vol_imbalance=1.0,
        )
        features = _base_features()
        features["hmm_regime_prob"] = 0.0  # no regime prob boost
        conf = self._confidence(xa, features)
        assert abs(conf - 0.60) < 1e-6

    def test_confidence_multi_pair_boost(self):
        """pairs_confirming=2 multiplies base by 1.2: 0.60 * 1.2 = 0.72."""
        xa = _base_xa(
            es_nq_z=3.0,
            pairs_confirming=2,
            eq_vol_imbalance=1.0,
        )
        features = _base_features()
        features["hmm_regime_prob"] = 0.0
        conf = self._confidence(xa, features)
        expected = 0.60 * 1.2
        assert abs(conf - expected) < 1e-6

    def test_confidence_vol_imbalance_boost(self):
        """eq_vol_imbalance > 1.5 adds 0.05: 0.60 + 0.05 = 0.65."""
        xa = _base_xa(
            es_nq_z=3.0,
            pairs_confirming=1,
            eq_vol_imbalance=1.6,
        )
        features = _base_features()
        features["hmm_regime_prob"] = 0.0
        conf = self._confidence(xa, features)
        expected = 0.60 + 0.05
        assert abs(conf - expected) < 1e-6

    def test_confidence_regime_prob_boost(self):
        """hmm_regime_prob >= 0.75 adds 0.10: 0.60 + 0.10 = 0.70."""
        xa = _base_xa(
            es_nq_z=3.0,
            pairs_confirming=1,
            eq_vol_imbalance=1.0,
        )
        features = _base_features()
        features["hmm_regime_prob"] = 0.80
        conf = self._confidence(xa, features)
        expected = 0.60 + 0.10
        assert abs(conf - expected) < 1e-6

    def test_confidence_regime_prob_no_boost_below_threshold(self):
        """hmm_regime_prob = 0.74 (< 0.75) adds 0.0."""
        xa = _base_xa(
            es_nq_z=3.0,
            pairs_confirming=1,
            eq_vol_imbalance=1.0,
        )
        features = _base_features()
        features["hmm_regime_prob"] = 0.74
        conf = self._confidence(xa, features)
        assert abs(conf - 0.60) < 1e-6

    def test_confidence_multi_tf_boost(self):
        """cross_asset_5m agreeing in sign multiplies base by 1.2: 0.60 * 1.2 = 0.72."""
        xa = _base_xa(
            es_nq_z=3.0,  # positive spread in 1m
            pairs_confirming=1,
            eq_vol_imbalance=1.0,
        )
        xa_5m = {
            "ready": True,
            "es_nq_spread_z": 2.5,  # same sign as 1m (positive)
            "es_rty_spread_z": 0.5,
            "active_pair": "ES_NQ",
        }
        features = _base_features()
        features["hmm_regime_prob"] = 0.0
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": features,
            "i2": features,
            "i3": features,
            "i4": features,
            "i5": features,
            "smc": features,
            "i6": features,
            "cross_asset": xa,
            "cross_asset_5m": xa_5m,
            "main": _make_df(),
        }
        with patch(
            "src.intelligence.archive.trading_i7.cross_asset_divergence.frame_trade",
            return_value=_mock_frame(direction=-1),
        ):
            result = p.compute_full(frames)
        expected = 0.60 * 1.2
        assert abs(result["confidence"] - expected) < 1e-6

    def test_confidence_multi_tf_no_boost_opposite_sign(self):
        """cross_asset_5m with opposite sign does NOT multiply."""
        xa = _base_xa(
            es_nq_z=3.0,  # positive spread
            pairs_confirming=1,
            eq_vol_imbalance=1.0,
        )
        xa_5m = {
            "ready": True,
            "es_nq_spread_z": -1.0,  # opposite sign → no boost
            "es_rty_spread_z": 0.0,
            "active_pair": "ES_NQ",
        }
        features = _base_features()
        features["hmm_regime_prob"] = 0.0
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": features,
            "i2": features,
            "i3": features,
            "i4": features,
            "i5": features,
            "smc": features,
            "i6": features,
            "cross_asset": xa,
            "cross_asset_5m": xa_5m,
            "main": _make_df(),
        }
        with patch(
            "src.intelligence.archive.trading_i7.cross_asset_divergence.frame_trade",
            return_value=_mock_frame(direction=-1),
        ):
            result = p.compute_full(frames)
        assert abs(result["confidence"] - 0.60) < 1e-6

    def test_confidence_clamped_to_1(self):
        """All boosts combined must not exceed 1.0."""
        xa = _base_xa(
            es_nq_z=10.0,  # max spread_z → large base
            pairs_confirming=2,
            eq_vol_imbalance=2.0,
        )
        xa_5m = {
            "ready": True,
            "es_nq_spread_z": 5.0,
            "es_rty_spread_z": 1.0,
            "active_pair": "ES_NQ",
        }
        features = _base_features()
        features["hmm_regime_prob"] = 0.90
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": features,
            "i2": features,
            "i3": features,
            "i4": features,
            "i5": features,
            "smc": features,
            "i6": features,
            "cross_asset": xa,
            "cross_asset_5m": xa_5m,
            "main": _make_df(),
        }
        with patch(
            "src.intelligence.archive.trading_i7.cross_asset_divergence.frame_trade",
            return_value=_mock_frame(direction=-1),
        ):
            result = p.compute_full(frames)
        assert result["confidence"] <= 1.0

    def test_confidence_clamped_to_0(self):
        """Confidence must not drop below 0.0."""
        p = CrossAssetDivergencePlugin()
        # Use minimal spread to get smallest possible base
        xa = _base_xa(es_nq_z=2.001, pairs_confirming=0, eq_vol_imbalance=0.0)
        features = _base_features()
        features["hmm_regime_prob"] = 0.0
        frames = {
            "i1": features,
            "i2": features,
            "i3": features,
            "i4": features,
            "i5": features,
            "smc": features,
            "i6": features,
            "cross_asset": xa,
            "main": _make_df(),
        }
        with patch(
            "src.intelligence.archive.trading_i7.cross_asset_divergence.frame_trade",
            return_value=_mock_frame(direction=-1),
        ):
            result = p.compute_full(frames)
        assert result["confidence"] >= 0.0


# ---------------------------------------------------------------------------
# Supporting factors content
# ---------------------------------------------------------------------------


class TestSupportingFactors:
    def test_supporting_factors_includes_active_pair(self):
        # supporting_factors is now a list[str] (standardized in 44-04)
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": _base_features(),
            "i2": _base_features(),
            "i3": _base_features(),
            "i4": _base_features(),
            "i5": _base_features(),
            "smc": _base_features(),
            "i6": _base_features(),
            "cross_asset": _base_xa(es_nq_z=3.0, active_pair="ES_NQ"),
            "main": _make_df(),
        }
        with patch(
            "src.intelligence.archive.trading_i7.cross_asset_divergence.frame_trade",
            return_value=_mock_frame(direction=-1),
        ):
            result = p.compute_full(frames)
        sf = result["supporting_factors"]
        assert isinstance(sf, list), f"supporting_factors must be list, got {type(sf)}"
        assert any(
            "active_pair=ES_NQ" in s for s in sf
        ), f"active_pair not in supporting_factors: {sf}"

    def test_supporting_factors_includes_spread_z_values(self):
        # supporting_factors is now a list[str] (standardized in 44-04)
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": _base_features(),
            "i2": _base_features(),
            "i3": _base_features(),
            "i4": _base_features(),
            "i5": _base_features(),
            "smc": _base_features(),
            "i6": _base_features(),
            "cross_asset": _base_xa(es_nq_z=3.5, es_rty_z=1.2),
            "main": _make_df(),
        }
        with patch(
            "src.intelligence.archive.trading_i7.cross_asset_divergence.frame_trade",
            return_value=_mock_frame(direction=-1),
        ):
            result = p.compute_full(frames)
        sf = result["supporting_factors"]
        assert isinstance(sf, list), f"supporting_factors must be list, got {type(sf)}"
        assert any("spread_z=" in s for s in sf), f"spread_z not in supporting_factors: {sf}"

    def test_supporting_factors_includes_pairs_confirming(self):
        # supporting_factors is now a list[str] (standardized in 44-04)
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": _base_features(),
            "i2": _base_features(),
            "i3": _base_features(),
            "i4": _base_features(),
            "i5": _base_features(),
            "smc": _base_features(),
            "i6": _base_features(),
            "cross_asset": _base_xa(es_nq_z=3.0, pairs_confirming=2),
            "main": _make_df(),
        }
        with patch(
            "src.intelligence.archive.trading_i7.cross_asset_divergence.frame_trade",
            return_value=_mock_frame(direction=-1),
        ):
            result = p.compute_full(frames)
        sf = result["supporting_factors"]
        assert isinstance(sf, list), f"supporting_factors must be list, got {type(sf)}"
        assert any(
            "pairs_confirming=2" in s for s in sf
        ), f"pairs_confirming not in supporting_factors: {sf}"


# ---------------------------------------------------------------------------
# compute_next delegates to compute_full
# ---------------------------------------------------------------------------


class TestComputeNext:
    def test_compute_next_delegates(self):
        p = CrossAssetDivergencePlugin()
        frames = {
            "i1": _base_features(symbol="CLM6"),
            "i2": _base_features(symbol="CLM6"),
            "i3": _base_features(symbol="CLM6"),
            "i4": _base_features(symbol="CLM6"),
            "i5": _base_features(symbol="CLM6"),
            "smc": _base_features(symbol="CLM6"),
            "i6": _base_features(symbol="CLM6"),  # non-EQ_INDEX, will return _no_signal
            "cross_asset": _base_xa(es_nq_z=3.0),
            "main": _make_df(),
        }
        result_full = p.compute_full(frames)
        result_next = p.compute_next(frames)
        assert result_full == result_next
