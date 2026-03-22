"""Unit tests for apply_regime_gate pure function."""
from __future__ import annotations

from src.intelligence.pipeline.regime_gate import apply_regime_gate


def make_signal(confidence=0.8, plugin="trad_TrendFollowing", direction=1, regime_type="trend"):
    return {
        "confidence": confidence,
        "setup_plugin": plugin,
        "direction": direction,
        "regime_type": regime_type,
        "regime_type_at_fire": regime_type,
    }


def test_none_regime_data_passes_all():
    """No regime data → all regime_eligible=True."""
    signals = [make_signal(), make_signal(regime_type="mean_reversion")]
    result = apply_regime_gate(signals, None)
    assert all(s["regime_eligible"] is True for s in result)
    assert all(s["suppression_reason"] is None for s in result)


def test_low_prob_suppresses():
    """hmm_regime_prob below default threshold → regime_eligible=False, reason='regime_prob'."""
    sig = make_signal(regime_type="trend")
    regime_data = {"hmm_regime": 1, "hmm_regime_prob": 0.20, "hmm_regime_duration": 5}
    result = apply_regime_gate([sig], regime_data)
    assert result[0]["regime_eligible"] is False
    assert result[0]["suppression_reason"] == "regime_prob"


def test_low_duration_suppresses():
    """hmm_regime_duration=0 (below safety floor dur_min=1) → suppress."""
    sig = make_signal(regime_type="trend")
    regime_data = {"hmm_regime": 1, "hmm_regime_prob": 0.7, "hmm_regime_duration": 0}
    result = apply_regime_gate([sig], regime_data)
    assert result[0]["regime_eligible"] is False
    assert result[0]["suppression_reason"] == "regime_duration"


def test_wrong_regime_suppresses():
    """trend plugin + hmm_regime=0 (ranging) → suppress."""
    sig = make_signal(regime_type="trend")
    regime_data = {"hmm_regime": 0, "hmm_regime_prob": 0.7, "hmm_regime_duration": 5}
    result = apply_regime_gate([sig], regime_data)
    assert result[0]["regime_eligible"] is False
    assert result[0]["suppression_reason"] == "regime_type"


def test_matching_regime_passes():
    """trend plugin + hmm_regime=1 (trending-up) → eligible."""
    sig = make_signal(regime_type="trend")
    regime_data = {"hmm_regime": 1, "hmm_regime_prob": 0.7, "hmm_regime_duration": 5}
    result = apply_regime_gate([sig], regime_data)
    assert result[0]["regime_eligible"] is True
    assert result[0]["suppression_reason"] is None


def test_any_regime_type_always_passes():
    """regime_type='any' always passes the regime check."""
    sig = make_signal(regime_type="any")
    regime_data = {"hmm_regime": 2, "hmm_regime_prob": 0.8, "hmm_regime_duration": 10}
    result = apply_regime_gate([sig], regime_data)
    assert result[0]["regime_eligible"] is True


def test_does_not_mutate_input():
    """Input signal dicts are not mutated."""
    sig = make_signal()
    original = dict(sig)
    apply_regime_gate([sig], None)
    assert sig == original


# --- New parametric interface tests (SHADOW-01 / D-01 through D-05) ---


def test_safety_floor_allows_previously_suppressed_signals():
    """prob_min=0.30, dur_min=1 allows signals with hmm_regime_prob=0.35, duration=2."""
    sig = make_signal(regime_type="any")
    regime_data = {"hmm_regime": 1, "hmm_regime_prob": 0.35, "hmm_regime_duration": 2}
    result = apply_regime_gate([sig], regime_data, prob_min=0.30, dur_min=1)
    assert result[0]["regime_eligible"] is True
    assert result[0]["suppression_reason"] is None


def test_safety_floor_suppresses_below_floor():
    """prob_min=0.30 still suppresses signals with hmm_regime_prob=0.20."""
    sig = make_signal(regime_type="any")
    regime_data = {"hmm_regime": 1, "hmm_regime_prob": 0.20, "hmm_regime_duration": 5}
    result = apply_regime_gate([sig], regime_data, prob_min=0.30, dur_min=1)
    assert result[0]["regime_eligible"] is False
    assert result[0]["suppression_reason"] == "regime_prob"


def test_dur_min_1_suppresses_duration_0():
    """dur_min=1 suppresses signals with hmm_regime_duration=0."""
    sig = make_signal(regime_type="any")
    regime_data = {"hmm_regime": 1, "hmm_regime_prob": 0.50, "hmm_regime_duration": 0}
    result = apply_regime_gate([sig], regime_data, prob_min=0.30, dur_min=1)
    assert result[0]["regime_eligible"] is False
    assert result[0]["suppression_reason"] == "regime_duration"


def test_custom_prob_min_threads_correctly():
    """prob_min=0.70 suppresses signal with hmm_regime_prob=0.65."""
    sig = make_signal(regime_type="any")
    regime_data = {"hmm_regime": 1, "hmm_regime_prob": 0.65, "hmm_regime_duration": 5}
    result = apply_regime_gate([sig], regime_data, prob_min=0.70, dur_min=1)
    assert result[0]["regime_eligible"] is False
    assert result[0]["suppression_reason"] == "regime_prob"


def test_regime_map_unchanged_with_parametric_gate():
    """_REGIME_MAP type gating still applies correctly with new parametric signature."""
    # mean_reversion plugin in hmm_regime=1 (trending-up) → suppressed by type
    sig = make_signal(regime_type="mean_reversion")
    regime_data = {"hmm_regime": 1, "hmm_regime_prob": 0.60, "hmm_regime_duration": 5}
    result = apply_regime_gate([sig], regime_data, prob_min=0.30, dur_min=1)
    assert result[0]["regime_eligible"] is False
    assert result[0]["suppression_reason"] == "regime_type"


def test_default_settings_have_safety_floor_thresholds():
    """Settings() with no env vars creates regime_prob_min=0.30 and regime_dur_min=1."""
    import os

    # Ensure no overrides exist in environment
    os.environ.pop("REGIME_PROB_MIN", None)
    os.environ.pop("REGIME_DUR_MIN", None)

    from src.config.settings import Settings

    s = Settings()
    assert s.regime_prob_min == 0.30
    assert s.regime_dur_min == 1
