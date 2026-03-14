"""Tests for CISScorer — 6-bucket weighted directional scorer (Phase 7 CIS)."""

from __future__ import annotations

import pytest

from src.intelligence.trading.cis_scorer import (
    BOOTSTRAP_WEIGHTS,
    BUCKET_NAMES,
    CISScorer,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bullish_features() -> dict:
    """Return a features dict that should produce a clearly bullish CIS."""
    return {
        # Trend bucket drivers
        "trend_regime": 0.8,
        "kalman_slope": 0.5,
        "smc_trend_direction": 1,
        "ctf_trend_alignment": 0.8,
        "trend_confluence_score": 0.7,
        # Momentum bucket drivers
        "rsi_14": 70.0,
        "macd_hist_12_26_9": 0.5,
        "roc_14": 2.0,
        "momentum_bias": 0.6,
        # Structure bucket drivers
        "swing_pattern": 0.7,
        "bos_detected": 1.0,
        "bos_direction": 1,
        "choch_detected": 0.0,
        "choch_direction": 0,
        # Pattern bucket (leave mostly neutral)
        "dt_db_pattern": 0.0,
        "dt_db_confidence": 0.0,
        "hs_pattern": 0.0,
        "hs_confidence": 0.0,
        "tri_breakout_bias": 0.0,
        "tri_confidence": 0.0,
        # Institutional bucket drivers
        "ob_type": 1,
        "ob_strength": 0.8,
        "fvg_type": 1,
        "fvg_open_count": 2,
        "in_demand_zone": 1.0,
        "in_supply_zone": 0.0,
        # Regime bucket drivers
        "hmm_prob_trending_up": 0.7,
        "hmm_prob_trending_down": 0.1,
        "cp_probability": 0.2,
        "ctf_regime_agreement": 0.6,
        "vol_regime": 0.2,
    }


def _bearish_features() -> dict:
    """Return a features dict that should produce a clearly bearish CIS."""
    f = _bullish_features()
    f.update(
        {
            "trend_regime": -0.8,
            "kalman_slope": -0.5,
            "smc_trend_direction": -1,
            "ctf_trend_alignment": -0.8,
            "trend_confluence_score": -0.7,
            "rsi_14": 30.0,
            "macd_hist_12_26_9": -0.5,
            "roc_14": -2.0,
            "momentum_bias": -0.6,
            "bos_direction": -1,
            "ob_type": -1,
            "fvg_type": -1,
            "in_demand_zone": 0.0,
            "in_supply_zone": 1.0,
            "hmm_prob_trending_up": 0.1,
            "hmm_prob_trending_down": 0.7,
        }
    )
    return f


def _neutral_features() -> dict:
    """Return a features dict near zero (no clear direction)."""
    return {k: 0.0 for k in _bullish_features()}


# ---------------------------------------------------------------------------
# Bucket scoring tests
# ---------------------------------------------------------------------------


class TestTrendBucket:
    @pytest.mark.unit
    def test_trend_bucket_bullish(self):
        """Strong bullish trend inputs -> trend bucket score > 0.3."""
        features = {
            "trend_regime": 0.8,
            "kalman_slope": 0.5,
            "smc_trend_direction": 1,
            "ctf_trend_alignment": 0.8,
            "trend_confluence_score": 0.7,
        }
        scorer = CISScorer()
        result = scorer.score(features, {})
        assert result.bucket_scores["trend"] > 0.3

    @pytest.mark.unit
    def test_trend_bucket_bearish(self):
        """Strong bearish trend inputs -> trend bucket score < -0.3."""
        features = {
            "trend_regime": -0.8,
            "kalman_slope": -0.5,
            "smc_trend_direction": -1,
            "ctf_trend_alignment": -0.8,
            "trend_confluence_score": -0.7,
        }
        scorer = CISScorer()
        result = scorer.score(features, {})
        assert result.bucket_scores["trend"] < -0.3


# ---------------------------------------------------------------------------
# Fire / no-fire conditions
# ---------------------------------------------------------------------------


class TestCISFireConditions:
    @pytest.mark.unit
    def test_cis_fires_on_three_agreeing_buckets(self):
        """Strong bullish features -> CIS fires (direction=1, |score|>0.35, agreeing>=3)."""
        scorer = CISScorer()
        result = scorer.score(_bullish_features(), {})
        assert result.direction == 1
        assert abs(result.cis_score) > 0.35
        assert result.buckets_agreeing >= 3

    @pytest.mark.unit
    def test_cis_no_fire_below_threshold(self):
        """All bucket scores near zero -> CIS does not fire (direction=0)."""
        scorer = CISScorer()
        result = scorer.score(_neutral_features(), {})
        assert result.direction == 0

    @pytest.mark.unit
    def test_cis_fires_bearish(self):
        """Strong bearish features -> CIS fires with direction=-1."""
        scorer = CISScorer()
        result = scorer.score(_bearish_features(), {})
        assert result.direction == -1
        assert result.cis_score < -0.35


# ---------------------------------------------------------------------------
# Mathematical invariants
# ---------------------------------------------------------------------------


class TestCISInvariants:
    @pytest.mark.unit
    def test_bucket_scores_sum_to_cis(self):
        """CIS score = weighted sum of bucket scores (before clamping)."""
        scorer = CISScorer()
        features = _bullish_features()
        result = scorer.score(features, {})
        expected_raw = sum(BOOTSTRAP_WEIGHTS[b] * result.bucket_scores[b] for b in BUCKET_NAMES)
        # Allow small rounding tolerance
        assert abs(result.cis_score - round(max(-1.0, min(1.0, expected_raw)), 4)) < 1e-6

    @pytest.mark.unit
    def test_cis_score_clamped_to_minus_one_plus_one(self):
        """Extreme feature inputs -> cis_score always in [-1.0, +1.0]."""
        extreme = {k: 999.9 for k in _bullish_features()}
        scorer = CISScorer()
        result = scorer.score(extreme, {})
        assert -1.0 <= result.cis_score <= 1.0

    @pytest.mark.unit
    def test_bucket_names_complete(self):
        """BUCKET_NAMES contains exactly the 6 expected names."""
        assert set(BUCKET_NAMES) == {
            "trend",
            "momentum",
            "structure",
            "pattern",
            "institutional",
            "regime",
        }

    @pytest.mark.unit
    def test_bootstrap_weights_sum_to_one(self):
        """BOOTSTRAP_WEIGHTS must sum to exactly 1.0."""
        total = sum(BOOTSTRAP_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    @pytest.mark.unit
    def test_result_has_all_bucket_keys(self):
        """CISResult.bucket_scores has an entry for every BUCKET_NAME."""
        scorer = CISScorer()
        result = scorer.score({}, {})
        assert set(result.bucket_scores.keys()) == set(BUCKET_NAMES)

    @pytest.mark.unit
    def test_weights_version_is_zero_for_bootstrap(self):
        """Default scorer uses bootstrap weights (version=0)."""
        scorer = CISScorer()
        result = scorer.score({}, {})
        assert result.weights_version == 0


# ---------------------------------------------------------------------------
# Plugin output integration
# ---------------------------------------------------------------------------


class TestCISPluginOutputs:
    @pytest.mark.unit
    def test_cis_uses_plugin_output_for_divergence_stack(self):
        """DivergenceStack plugin direction/confidence contributes to momentum bucket."""
        features = {
            "rsi_14": 50.0,  # neutral RSI
            "macd_hist_12_26_9": 0.0,  # neutral MACD
            "roc_14": 0.0,  # neutral ROC
            "momentum_bias": 0.0,  # neutral bias
        }
        plugin_outputs_bullish = {
            "trad_DivergenceStack": {"direction": 1, "confidence": 0.8},
        }
        plugin_outputs_bearish = {
            "trad_DivergenceStack": {"direction": -1, "confidence": 0.8},
        }

        scorer = CISScorer()
        result_bullish = scorer.score(features, plugin_outputs_bullish)
        result_bearish = scorer.score(features, plugin_outputs_bearish)

        # Momentum bucket should differ between bullish and bearish plugin outputs
        assert result_bullish.bucket_scores["momentum"] > result_bearish.bucket_scores["momentum"]

    @pytest.mark.unit
    def test_unknown_plugin_names_ignored(self):
        """Unknown plugin names in plugin_outputs don't crash scorer."""
        scorer = CISScorer()
        plugin_outputs = {
            "unknown_plugin": {"direction": 1, "confidence": 0.9},
        }
        result = scorer.score({}, plugin_outputs)
        assert result is not None

    @pytest.mark.unit
    def test_missing_plugin_defaults_to_zero_contribution(self):
        """When plugin not in plugin_outputs, its contribution is zero."""
        features = {
            "rsi_14": 50.0,
            "macd_hist_12_26_9": 0.0,
            "roc_14": 0.0,
            "momentum_bias": 0.0,
        }
        scorer = CISScorer()
        result_no_plugin = scorer.score(features, {})
        result_with_neutral = scorer.score(
            features, {"trad_DivergenceStack": {"direction": 0, "confidence": 0.0}}
        )
        assert result_no_plugin.bucket_scores["momentum"] == pytest.approx(
            result_with_neutral.bucket_scores["momentum"], abs=1e-4
        )


# ---------------------------------------------------------------------------
# Custom weights
# ---------------------------------------------------------------------------


class TestCISCustomWeights:
    @pytest.mark.unit
    def test_custom_weights_version_stored(self):
        """Custom weights_version is propagated to CISResult."""
        custom_weights = dict(BOOTSTRAP_WEIGHTS)
        scorer = CISScorer(weights=custom_weights, weights_version=42)
        result = scorer.score({}, {})
        assert result.weights_version == 42

    @pytest.mark.unit
    def test_missing_features_default_to_zero(self):
        """Empty features dict does not crash; all buckets default to zero."""
        scorer = CISScorer()
        result = scorer.score({}, {})
        assert result is not None
        for b in BUCKET_NAMES:
            assert result.bucket_scores[b] == pytest.approx(0.0, abs=0.01)


def test_cis_result_has_constituent_contributions():
    scorer = CISScorer()
    features = {"rsi_14": 65.0, "trend_regime": 0.8}
    result = scorer.score(features, {})
    assert hasattr(result, "constituent_contributions")
    assert isinstance(result.constituent_contributions, dict)
    assert "momentum" in result.constituent_contributions
    assert "trend" in result.constituent_contributions
    # Each bucket entry is a dict of signal → contribution float
    assert isinstance(result.constituent_contributions["momentum"], dict)


def test_constituent_contributions_values_are_floats():
    scorer = CISScorer()
    features = {"rsi_14": 30.0, "macd_histogram_12_26_9": -0.5}
    result = scorer.score(features, {})
    for bucket, contribs in result.constituent_contributions.items():
        for signal, val in contribs.items():
            assert isinstance(val, float), f"{bucket}.{signal} is not float"


# ---------------------------------------------------------------------------
# Constituent contributions — RED tests (QUAL-01)
# ---------------------------------------------------------------------------


def test_constituent_contributions_trend_has_at_least_one_feature():
    """score() returns CISResult where constituent_contributions['trend'] has at least one
    feature key with a float value — not an empty dict."""
    scorer = CISScorer()
    features = {"trend_regime": 0.8, "kalman_slope": 0.5}
    result = scorer.score(features, {})
    assert len(result.constituent_contributions["trend"]) >= 1
    for v in result.constituent_contributions["trend"].values():
        assert isinstance(v, float)


def test_constituent_contributions_momentum_has_rsi_and_macd():
    """constituent_contributions['momentum'] contains 'rsi_14' and
    'macd_histogram_12_26_9' keys."""
    scorer = CISScorer()
    features = {"rsi_14": 65.0, "macd_histogram_12_26_9": 0.3}
    result = scorer.score(features, {})
    contribs = result.constituent_contributions["momentum"]
    assert (
        "rsi_14" in contribs
    ), f"Expected 'rsi_14' in momentum contributions, got {list(contribs)}"
    assert (
        "macd_histogram_12_26_9" in contribs
    ), f"Expected 'macd_histogram_12_26_9' in momentum contributions, got {list(contribs)}"


def test_constituent_contributions_all_six_buckets_present():
    """constituent_contributions keys == set(BUCKET_NAMES) — all 6 buckets present."""
    scorer = CISScorer()
    result = scorer.score({}, {})
    assert set(result.constituent_contributions.keys()) == set(BUCKET_NAMES)


def test_no_bucket_contribution_dict_is_empty():
    """No bucket's contribution dict is empty ({}) — every bucket has at least one entry.
    Uses a features dict with non-zero inputs to trigger non-trivial bucket scoring."""
    scorer = CISScorer()
    features = _bullish_features()
    result = scorer.score(features, {})
    for bucket, contribs in result.constituent_contributions.items():
        assert len(contribs) >= 1, f"Bucket '{bucket}' contribution dict is empty"


def test_bucket_scores_are_floats_not_tuples():
    """bucket_scores values remain floats — not tuples — after the bucket method refactor."""
    scorer = CISScorer()
    result = scorer.score(_bullish_features(), {})
    for bucket, score in result.bucket_scores.items():
        assert isinstance(
            score, float
        ), f"bucket_scores['{bucket}'] is {type(score)}, expected float"


def test_cis_score_value_unchanged_after_contributions_refactor():
    """Regression: same inputs produce same cis_score after refactor.
    The refactor is additive only — contributions don't change scoring math."""
    scorer = CISScorer()
    features = _bullish_features()
    result = scorer.score(features, {})
    # Compute expected raw from bucket scores (same formula as score())
    from src.intelligence.trading.cis_scorer import BOOTSTRAP_WEIGHTS, BUCKET_NAMES  # noqa: PLC0415

    expected_raw = sum(BOOTSTRAP_WEIGHTS[b] * result.bucket_scores[b] for b in BUCKET_NAMES)
    expected_cis = round(max(-1.0, min(1.0, expected_raw)), 4)
    assert result.cis_score == pytest.approx(expected_cis, abs=1e-6)


# ---------------------------------------------------------------------------
# QUAL-05: rel_volume sub-term in CIS momentum bucket
# ---------------------------------------------------------------------------


class TestRelVolumeMomentumSubterm:
    """QUAL-05: rel_volume wired into _momentum() as additive sub-term."""

    @pytest.mark.unit
    def test_high_rel_volume_boosts_momentum_score(self):
        """rel_volume=2.0 → momentum bucket score higher than rel_volume=1.0 (baseline)."""
        base_features = {
            "rsi_14": 50.0,  # neutral RSI
            "macd_histogram_12_26_9": 0.0,  # neutral MACD
            "roc_14": 0.0,  # neutral ROC
            "momentum_bias": 0.0,  # neutral bias
        }
        high_vol = dict(base_features, rel_volume=2.0)
        baseline = dict(base_features, rel_volume=1.0)

        scorer = CISScorer()
        score_high = scorer.score(high_vol, {}).bucket_scores["momentum"]
        score_baseline = scorer.score(baseline, {}).bucket_scores["momentum"]

        assert score_high > score_baseline, (
            f"Expected momentum score with rel_volume=2.0 ({score_high}) "
            f"to be higher than rel_volume=1.0 ({score_baseline})"
        )

    @pytest.mark.unit
    def test_low_rel_volume_suppresses_momentum_score(self):
        """rel_volume=0.3 → momentum bucket score lower than rel_volume=1.0 (baseline)."""
        base_features = {
            "rsi_14": 50.0,
            "macd_histogram_12_26_9": 0.0,
            "roc_14": 0.0,
            "momentum_bias": 0.0,
        }
        low_vol = dict(base_features, rel_volume=0.3)
        baseline = dict(base_features, rel_volume=1.0)

        scorer = CISScorer()
        score_low = scorer.score(low_vol, {}).bucket_scores["momentum"]
        score_baseline = scorer.score(baseline, {}).bucket_scores["momentum"]

        assert score_low < score_baseline, (
            f"Expected momentum score with rel_volume=0.3 ({score_low}) "
            f"to be lower than rel_volume=1.0 ({score_baseline})"
        )

    @pytest.mark.unit
    def test_rel_volume_subterm_in_contributions(self):
        """constituent_contributions['momentum'] contains 'rel_volume' key."""
        scorer = CISScorer()
        result = scorer.score({"rel_volume": 1.5}, {})
        contribs = result.constituent_contributions["momentum"]
        assert (
            "rel_volume" in contribs
        ), f"Expected 'rel_volume' in momentum contributions, got {list(contribs)}"


# ---------------------------------------------------------------------------
# QUAL-06: killzone sub-term in CIS regime bucket
# ---------------------------------------------------------------------------


class TestKillzoneRegimeSubterm:
    """QUAL-06: killzone context wired into _regime() as additive sub-term."""

    @pytest.mark.unit
    def test_active_killzone_boosts_regime_score(self):
        """in_london_killzone=1.0 → regime bucket score higher than no killzone (dead session)."""
        # Use a trend-positive base so regime has a positive direction to boost
        base_features = {
            "hmm_prob_trending_up": 0.6,
            "hmm_prob_trending_down": 0.2,
            "cp_probability": 0.2,
            "ctf_regime_agreement": 0.4,
            "vol_regime": 0.2,
            "in_london_killzone": 0.0,
            "in_ny_killzone": 0.0,
        }
        kz_features = dict(base_features, in_london_killzone=1.0)

        scorer = CISScorer()
        score_kz = scorer.score(kz_features, {}).bucket_scores["regime"]
        score_no_kz = scorer.score(base_features, {}).bucket_scores["regime"]

        assert score_kz > score_no_kz, (
            f"Expected regime score with killzone ({score_kz}) "
            f"to be higher than without killzone ({score_no_kz})"
        )

    @pytest.mark.unit
    def test_dead_session_suppresses_regime_score(self):
        """Both killzones=0.0 → regime bucket score lower than active killzone baseline."""
        kz_features = {
            "hmm_prob_trending_up": 0.6,
            "hmm_prob_trending_down": 0.2,
            "cp_probability": 0.2,
            "ctf_regime_agreement": 0.4,
            "vol_regime": 0.2,
            "in_london_killzone": 1.0,
            "in_ny_killzone": 0.0,
        }
        no_kz_features = dict(kz_features, in_london_killzone=0.0)

        scorer = CISScorer()
        score_kz = scorer.score(kz_features, {}).bucket_scores["regime"]
        score_no_kz = scorer.score(no_kz_features, {}).bucket_scores["regime"]

        assert score_no_kz < score_kz, (
            f"Expected dead session regime score ({score_no_kz}) "
            f"to be lower than killzone-active score ({score_kz})"
        )

    @pytest.mark.unit
    def test_killzone_subterm_in_contributions(self):
        """constituent_contributions['regime'] contains 'killzone' key."""
        scorer = CISScorer()
        result = scorer.score({"in_london_killzone": 1.0}, {})
        contribs = result.constituent_contributions["regime"]
        assert (
            "killzone" in contribs
        ), f"Expected 'killzone' in regime contributions, got {list(contribs)}"
