"""Unit tests for DivergenceStackPlugin — extrinsic strip, 4-factor confidence, always-log."""

from __future__ import annotations

import pandas as pd

from src.intelligence.archive.trading_i7.divergence_stack import (
    DIVERGENCE_MIN_AGREEING,
    DIVERGENCE_WEIGHTS,
    DivergenceStackPlugin,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_ALL_INPUTS = list(DIVERGENCE_WEIGHTS.keys())  # ["rsi", "macd", "vol", "obv", "cmf"]


def _make_df(n: int = 30, price: float = 5000.0) -> pd.DataFrame:
    """Minimal OHLCV DataFrame."""
    closes = [price + i * 0.1 for i in range(n)]
    return pd.DataFrame(
        {
            "open": [c - 0.05 for c in closes],
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "volume": [1000.0] * n,
        }
    )


def _make_bullish_features(
    n_inputs: int = 5,
    score: float = 0.9,
    atr: float = 5.0,
    extra: dict | None = None,
) -> dict:
    """Build features dict where the first n_inputs divergence inputs agree bullish.

    n_inputs controls breadth (>=3 to exceed DIVERGENCE_MIN_AGREEING=3).
    score is the per-input divergence score (applied to bullish side).
    """
    f: dict = {
        "atr_14": atr,
        "timeframe": "1m",
        "timestamp": "2026-01-01T00:00:00Z",
    }
    for i, inp in enumerate(_ALL_INPUTS):
        if i < n_inputs:
            f[f"{inp}_div_bullish"] = score
            f[f"{inp}_div_bearish"] = 0.0
            f[f"{inp}_div_strength"] = score
        else:
            f[f"{inp}_div_bullish"] = 0.0
            f[f"{inp}_div_bearish"] = 0.0
            f[f"{inp}_div_strength"] = 0.0
    if extra:
        f.update(extra)
    return f


def _make_frames(features: dict, df: pd.DataFrame | None = None) -> dict:
    """Wrap features dict into the frames structure expected by compute_full."""
    if df is None:
        df = _make_df()
    return {
        "main": df,
        "i1": features,
        "i2": features,
        "i3": features,
        "i4": features,
        "i5": features,
        "smc": features,
        "i6": features,
        "symbol": "ES",
        "timeframe": "1m",
    }


def _fire_plugin(plugin: DivergenceStackPlugin, frames: dict, times: int = 1) -> dict:
    """Call compute_full `times` times; return the last result.

    Multiple calls let state accumulate (age tracking).
    """
    result: dict = {}
    for _ in range(times):
        result = plugin.compute_full(frames)
    return result


# ---------------------------------------------------------------------------
# Test 1: exhaustion guard removed — extrinsic exhaustion fields don't change confidence
# ---------------------------------------------------------------------------


class TestNoExhaustionGuardInConfidence:
    def test_no_exhaustion_guard_in_confidence(self):
        """Confidence must be identical whether exhaustion data is present or absent."""
        base_features = _make_bullish_features(n_inputs=5)

        plugin_a = DivergenceStackPlugin()
        plugin_b = DivergenceStackPlugin()

        result_a = _fire_plugin(plugin_a, _make_frames(base_features))

        # Add exhaustion fields that apply_exhaustion_guard would have used
        enriched_features = {
            **base_features,
            "delta_exhaustion": 0.9,
            "exhaustion_score": 0.95,
            "delta_reversal_signal": 1,
        }
        result_b = _fire_plugin(plugin_b, _make_frames(enriched_features))

        assert (
            abs(result_a.get("confidence", 0.0) - result_b.get("confidence", 0.0)) < 1e-9
        ), f"Exhaustion fields must not affect confidence: {result_a['confidence']} vs {result_b['confidence']}"


# ---------------------------------------------------------------------------
# Test 2: ctf_score removed — extrinsic ctf data doesn't change confidence
# ---------------------------------------------------------------------------


class TestNoCtfInConfidence:
    def test_no_ctf_in_confidence(self):
        """ctf_score=0.8 vs 0.0 must produce identical confidence."""
        base_features = _make_bullish_features(n_inputs=5)

        plugin_a = DivergenceStackPlugin()
        plugin_b = DivergenceStackPlugin()

        result_a = _fire_plugin(plugin_a, _make_frames(base_features))

        high_ctf_features = {**base_features, "ctf_score": 0.8}
        result_b = _fire_plugin(plugin_b, _make_frames(high_ctf_features))

        assert (
            abs(result_a.get("confidence", 0.0) - result_b.get("confidence", 0.0)) < 1e-9
        ), f"ctf_score must not affect confidence: {result_a['confidence']} vs {result_b['confidence']}"


# ---------------------------------------------------------------------------
# Test 3: base_score fires when n_agreeing meets minimum gate
# ---------------------------------------------------------------------------


class TestBaseScoreFromWeightedInputs:
    def test_base_score_from_weighted_inputs(self):
        """Signal fires with n_agreeing == DIVERGENCE_MIN_AGREEING and confidence > 0.0."""
        # Use exactly 3 agreeing inputs with high individual scores to clear DIVERGENCE_SCORE_THRESHOLD
        # Weights: rsi(0.30)+macd(0.25)+vol(0.20)=0.75*score. At score=1.0 -> 0.75 > 0.40.
        features = _make_bullish_features(n_inputs=DIVERGENCE_MIN_AGREEING, score=1.0)
        plugin = DivergenceStackPlugin()
        result = _fire_plugin(plugin, _make_frames(features))

        assert result.get("direction", 0) in (1, -1), "Signal must fire"
        assert result.get("confidence", 0.0) > 0.0, "Confidence must be positive"


# ---------------------------------------------------------------------------
# Test 4: purity_score increases with unanimity
# ---------------------------------------------------------------------------


class TestPurityScoreIncreasesWithUnanimity:
    def test_purity_score_increases_with_unanimity(self):
        """Unanimous direction yields higher confidence than mixed-direction inputs."""
        # Unanimous: all 5 bullish, meeting gate
        unanimous_features = _make_bullish_features(n_inputs=5, score=0.9)

        # Mixed: 3 bullish + 2 bearish (still meets n_agreeing=5 gate).
        mixed_features = {
            **_make_bullish_features(n_inputs=3, score=0.9),
            "obv_div_bullish": 0.0,
            "obv_div_bearish": 0.9,
            "cmf_div_bullish": 0.0,
            "cmf_div_bearish": 0.9,
            "obv_div_strength": 0.9,
            "cmf_div_strength": 0.9,
        }

        plugin_unanimous = DivergenceStackPlugin()
        plugin_mixed = DivergenceStackPlugin()

        r_unanimous = _fire_plugin(plugin_unanimous, _make_frames(unanimous_features))
        r_mixed = _fire_plugin(plugin_mixed, _make_frames(mixed_features))

        # Both must fire (ensure gate clears) — otherwise the test is vacuous
        assert r_unanimous.get("direction", 0) != 0, "Unanimous scenario must fire"
        assert r_mixed.get("direction", 0) != 0, "Mixed scenario must fire"

        assert r_unanimous["confidence"] > r_mixed["confidence"], (
            f"Unanimous confidence {r_unanimous['confidence']} must exceed "
            f"mixed confidence {r_mixed['confidence']}"
        )


# ---------------------------------------------------------------------------
# Test 5: breadth_score increases with n_agreeing
# ---------------------------------------------------------------------------


class TestBreadthScoreIncreasesWithNAgreeing:
    def test_breadth_score_increases_with_n_agreeing(self):
        """5 agreeing inputs produce higher confidence than exactly 3 agreeing inputs."""
        # Minimum gate: 3 inputs at score=1.0 (weighted sum=0.75 > threshold)
        features_3 = _make_bullish_features(n_inputs=3, score=1.0)
        # Maximum: 5 inputs at same per-input score
        features_5 = _make_bullish_features(n_inputs=5, score=1.0)

        plugin_3 = DivergenceStackPlugin()
        plugin_5 = DivergenceStackPlugin()

        r3 = _fire_plugin(plugin_3, _make_frames(features_3))
        r5 = _fire_plugin(plugin_5, _make_frames(features_5))

        assert r3.get("direction", 0) != 0, "3-agreeing scenario must fire"
        assert r5.get("direction", 0) != 0, "5-agreeing scenario must fire"
        assert r5["confidence"] > r3["confidence"], (
            f"5-agreeing confidence {r5['confidence']} must exceed "
            f"3-agreeing confidence {r3['confidence']}"
        )


# ---------------------------------------------------------------------------
# Test 6: freshness persistence — recent higher than stale
# ---------------------------------------------------------------------------


class TestFreshnessPersistenceRecentHigherThanStale:
    def test_freshness_persistence_recent_higher_than_stale(self):
        """A freshly-confirmed stack (age=1) scores higher than a stale stack (age=9).

        This is a regression guard for the max_age -> freshness fix. The old implementation
        rewarded OLDER stacks (max_age grew); the new implementation rewards FRESHER ones
        (min active age small = high persistence_score).
        """
        features = _make_bullish_features(n_inputs=5, score=0.9)

        # Fresh: call once, age=1 on all inputs
        plugin_fresh = DivergenceStackPlugin()
        r_fresh = _fire_plugin(plugin_fresh, _make_frames(features), times=1)

        # Stale: call 9 times (age accumulates to 9)
        plugin_stale = DivergenceStackPlugin()
        r_stale = _fire_plugin(plugin_stale, _make_frames(features), times=9)

        assert r_fresh.get("direction", 0) != 0, "Fresh scenario must fire"
        assert r_stale.get("direction", 0) != 0, "Stale scenario must fire"
        assert r_fresh["confidence"] > r_stale["confidence"], (
            f"Fresh confidence {r_fresh['confidence']} must exceed "
            f"stale confidence {r_stale['confidence']}"
        )


# ---------------------------------------------------------------------------
# Test 7: always-log base_output populated even on no-signal
# ---------------------------------------------------------------------------


class TestBaseOutputPopulatedOnNoSignal:
    def test_base_output_populated_on_no_signal(self):
        """When signal does not fire, always-log fields must still be present in result."""
        # Use only 1 agreeing input — below DIVERGENCE_MIN_AGREEING gate
        features: dict = {
            "atr_14": 5.0,
            "timeframe": "1m",
            "timestamp": "2026-01-01T00:00:00Z",
        }
        # All inputs zero except rsi (n_agreeing=1 < 3)
        for inp in _ALL_INPUTS:
            features[f"{inp}_div_bullish"] = 0.0
            features[f"{inp}_div_bearish"] = 0.0
            features[f"{inp}_div_strength"] = 0.0
        features["rsi_div_bullish"] = 0.9
        features["rsi_div_strength"] = 0.9

        plugin = DivergenceStackPlugin()
        result = _fire_plugin(plugin, _make_frames(features))

        assert result.get("signal_type") == "none", "Must not fire"
        assert result.get("direction", 0) == 0

        # All always-logged fields must be present
        always_log_fields = [
            "div_weighted_score",
            "div_n_agreeing",
            "rsi_div_score",
            "macd_div_score",
            "vol_div_score",
            "obv_div_score",
            "cmf_div_score",
            "rsi_divergence_age_bars",
            "macd_divergence_age_bars",
            "vol_divergence_age_bars",
            "obv_divergence_age_bars",
            "cmf_divergence_age_bars",
        ]
        for field_name in always_log_fields:
            assert (
                field_name in result
            ), f"Always-log field '{field_name}' missing on no-signal path"


# ---------------------------------------------------------------------------
# Test 8: shadow_only flag
# ---------------------------------------------------------------------------


class TestShadowOnlyFlag:
    def test_shadow_only_flag(self):
        """DivergenceStackPlugin.shadow_only must be True."""
        plugin = DivergenceStackPlugin()
        assert plugin.shadow_only is True


# ---------------------------------------------------------------------------
# Test 9: extrinsic perturbation delta zero
# ---------------------------------------------------------------------------


class TestExtrinsicPerturbationDeltaZero:
    def test_extrinsic_perturbation_delta_zero(self):
        """Adding extrinsic fields (ctf_score, hmm_regime, exhaustion) must not move confidence.

        Baseline: minimal firing scenario. Perturbed: identical intrinsic inputs plus
        maximum extrinsic values. Confidence difference must be < 1e-9.
        """
        base_features = _make_bullish_features(n_inputs=5, score=0.9)

        # Perturbed: add every extrinsic field that was previously modifying confidence
        perturbed_features = {
            **base_features,
            # ctf_score block (was: raw_div_conf += 0.15 * ...)
            "ctf_score": 0.9,
            # hmm_regime_weight inputs (was: raw_div_conf += 0.10 * ...)
            "hmm_regime": 1,
            # apply_exhaustion_guard inputs
            "delta_exhaustion": 0.8,
            "exhaustion_score": 0.9,
            "delta_reversal_signal": 1,
        }

        plugin_a = DivergenceStackPlugin()
        plugin_b = DivergenceStackPlugin()

        r_a = _fire_plugin(plugin_a, _make_frames(base_features))
        r_b = _fire_plugin(plugin_b, _make_frames(perturbed_features))

        # Both must produce a signal (otherwise test is vacuous)
        assert r_a.get("direction", 0) != 0, "Baseline must fire"
        assert r_b.get("direction", 0) != 0, "Perturbed must fire"

        delta = abs(r_a["confidence"] - r_b["confidence"])
        assert delta < 1e-9, (
            f"Extrinsic perturbation must not move confidence: "
            f"baseline={r_a['confidence']}, perturbed={r_b['confidence']}, delta={delta}"
        )
