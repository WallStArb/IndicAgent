"""Test suite for SessionExtremesSetup — I7 Asian-session fade plugin (Phase 11)."""

from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.archive.trading_i7.session_extremes_setup import SessionExtremesSetupPlugin
from tests.unit.intelligence.helpers import make_ohlcv

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

ATR = 10.0
ASIAN_HIGH = 5010.0
ASIAN_LOW = 4990.0
BASE_CLOSE = 5000.0


def make_frames(
    close: float = BASE_CLOSE,
    asian_high: float | None = ASIAN_HIGH,
    asian_low: float | None = ASIAN_LOW,
    session_london: float = 1.0,
    session_ny: float = 0.0,
    trend_regime: float = -0.6,  # bearish (fade-high default)
    rsi_14: float = 70.0,  # overbought
    high_volume: bool = False,
    n: int = 60,
    ctf_score: float = 0.5,
    hmm_prob_ranging: float = 0.60,
) -> dict:
    """Build frames dict for SessionExtremesSetupPlugin.compute_full()."""
    close_arr = np.full(n, close)
    df = make_ohlcv(close_arr)

    if high_volume:
        vol = df["volume"].to_numpy().copy()
        vol[-1] = vol[-1] * 2.0  # spike last bar to 2× mean
        df["volume"] = vol

    features: dict = {
        "atr_14": ATR,
        "session_london": session_london,
        "session_ny": session_ny,
        "trend_regime": trend_regime,
        "rsi_14": rsi_14,
        # Phase 119: gate-passing values for mean_reversion dual gate
        "ctf_score": ctf_score,
        "hmm_prob_ranging": hmm_prob_ranging,
    }
    if asian_high is not None:
        features["asian_session_high"] = asian_high
    if asian_low is not None:
        features["asian_session_low"] = asian_low

    return {
        "main": df,
        "i1": features,
        "i2": features,
        "i3": features,
        "i4": features,
        "i5": features,
        "smc": features,
        "i6": features,
    }


# ---------------------------------------------------------------------------
# SESS-01: Asian extremes gate
# ---------------------------------------------------------------------------


class TestSess01AsianExtremesGate:
    def test_no_signal_when_asian_high_missing(self):
        frames = make_frames(asian_high=None)
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") == "none"

    def test_no_signal_when_asian_low_is_none(self):
        frames = make_frames(asian_low=None)
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") == "none"

    def test_no_signal_when_both_extremes_missing(self):
        frames = make_frames(asian_high=None, asian_low=None)
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") == "none"


# ---------------------------------------------------------------------------
# SESS-02: Session window gate
# ---------------------------------------------------------------------------


class TestSess02SessionWindowGate:
    def test_no_signal_during_asia_session(self):
        # close=5009.0 puts price within proximity range; session gate should still block it
        frames = make_frames(close=5009.0, session_london=0.0, session_ny=0.0)
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") == "none"

    def test_fires_during_london_session(self):
        # Price near asian_high (5010), close = 5009 → dist = 1/10 = 0.1 ATR < 0.3
        frames = make_frames(close=5009.0, session_london=1.0, session_ny=0.0)
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") != "none"

    def test_fires_during_ny_session(self):
        # Price near asian_low (4990), close = 4992 → dist = 2/10 = 0.2 ATR < 0.3
        frames = make_frames(
            close=4992.0,
            session_london=0.0,
            session_ny=1.0,
            trend_regime=0.6,  # bullish for fade-low
            rsi_14=30.0,  # oversold
        )
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") != "none"


# ---------------------------------------------------------------------------
# SESS-03: Confirming factor gate
# ---------------------------------------------------------------------------


class TestSess03ConfirmingFactorGate:
    def _near_high_neutral_frames(self) -> dict:
        """Price near asian_high, but no confirming factors."""
        return make_frames(
            close=5009.0,
            trend_regime=0.0,  # flat — no trend align
            rsi_14=50.0,  # neutral RSI
            high_volume=False,
        )

    def test_no_signal_without_confirming_factor(self):
        frames = self._near_high_neutral_frames()
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") == "none"

    def test_fires_with_trend_align_only(self):
        frames = make_frames(
            close=5009.0,
            trend_regime=-0.6,  # bearish → aligns with fade-high short
            rsi_14=50.0,
            high_volume=False,
        )
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") != "none"
        factors = result.get("supporting_factors", [])
        assert "trend_align" in factors
        assert any(f.startswith("session:") for f in factors)

    def test_fires_with_volume_spike_only(self):
        frames = make_frames(
            close=5009.0,
            trend_regime=0.0,  # flat
            rsi_14=50.0,
            high_volume=True,  # spike
        )
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") != "none"
        assert "volume_spike" in result.get("supporting_factors", [])

    def test_fires_with_rsi_extreme_only(self):
        frames = make_frames(
            close=5009.0,
            trend_regime=0.0,  # flat
            rsi_14=72.0,  # overbought > 65
            high_volume=False,
        )
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") != "none"
        factors = result.get("supporting_factors", [])
        assert "rsi_extreme" in factors
        assert any(f.startswith("session:") for f in factors)

    def test_confidence_scales_with_factors(self):
        """More confirming factors produce higher confidence (Phase 119: 4-factor composite)."""
        plugin = SessionExtremesSetupPlugin()

        # 1 factor: trend_align only
        f1 = make_frames(close=5009.0, trend_regime=-0.6, rsi_14=50.0, high_volume=False)
        r1 = plugin.compute_full(f1)

        # 3 factors: trend + volume + rsi
        f3 = make_frames(close=5009.0, trend_regime=-0.6, rsi_14=72.0, high_volume=True)
        r3 = plugin.compute_full(f3)

        # Both fire; 3-factor confidence must exceed 1-factor confidence
        assert r1.get("direction") != 0, "1-factor should fire"
        assert r3.get("direction") != 0, "3-factor should fire"
        assert r3.get("confidence", 0) > r1.get("confidence", 0), (
            f"3-factor confidence {r3.get('confidence')} must exceed "
            f"1-factor {r1.get('confidence')}"
        )

    def test_confidence_two_factors(self):
        """trend + rsi (no volume) fires with positive confidence (Phase 119: 4-factor composite)."""
        frames = make_frames(close=5009.0, trend_regime=-0.6, rsi_14=72.0, high_volume=False)
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("direction") != 0, "trend + rsi should fire"
        assert result.get("confidence", 0) > 0


# ---------------------------------------------------------------------------
# Signal field correctness
# ---------------------------------------------------------------------------


class TestSignalFields:
    def test_signal_type_near_high(self):
        frames = make_frames(close=5009.0)  # near asian_high=5010
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") == "session_extreme_high_fade_short"

    def test_signal_type_near_low(self):
        frames = make_frames(
            close=4992.0,
            session_london=0.0,
            session_ny=1.0,
            trend_regime=0.6,
            rsi_14=30.0,
        )
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") == "session_extreme_low_fade_long"

    def test_direction_and_entry_near_high(self):
        frames = make_frames(close=5009.0)
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("direction") == -1
        assert result.get("entry_price") == pytest.approx(ASIAN_HIGH)
        # Stop must be above entry for a short fade
        assert result.get("stop_loss") > ASIAN_HIGH

    def test_direction_and_entry_near_low(self):
        frames = make_frames(
            close=4992.0,
            session_london=0.0,
            session_ny=1.0,
            trend_regime=0.6,
            rsi_14=30.0,
        )
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("direction") == 1
        assert result.get("entry_price") == pytest.approx(ASIAN_LOW)
        # Stop must be below entry for a long fade
        assert result.get("stop_loss") < ASIAN_LOW

    def test_targets_ordered_for_short(self):
        """Fade-short: all targets below entry price (asian_high)."""
        frames = make_frames(close=5009.0)
        result = SessionExtremesSetupPlugin().compute_full(frames)
        targets = result.get("targets", [])
        assert len(targets) == 3
        # For short, targets should be descending (each further below entry)
        assert targets[0] < ASIAN_HIGH
        assert targets[1] < targets[0]
        assert targets[2] < targets[1]

    def test_targets_ordered_for_long(self):
        """Fade-long: all targets above entry price (asian_low)."""
        frames = make_frames(
            close=4992.0,
            session_london=0.0,
            session_ny=1.0,
            trend_regime=0.6,
            rsi_14=30.0,
        )
        result = SessionExtremesSetupPlugin().compute_full(frames)
        targets = result.get("targets", [])
        assert len(targets) == 3
        assert targets[0] > ASIAN_LOW
        assert targets[1] > targets[0]
        assert targets[2] > targets[1]

    def test_entry_type_is_at_limit(self):
        frames = make_frames(close=5009.0)
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("entry_type") == "at_limit"

    def test_complete_output_fields(self):
        expected = {
            "signal_type",
            "direction",
            "bias",
            "proximity_atr",
            "confidence",
            "entry_type",
            "entry_price",
            "stop_loss",
            "targets",
            "regime_context",
            "supporting_factors",
        }
        frames = make_frames(close=5009.0)
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") != "none", "Expected signal to fire"
        assert expected.issubset(result.keys())

    def test_regime_context_london(self):
        frames = make_frames(close=5009.0, session_london=1.0, session_ny=0.0)
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") != "none", "Expected signal to fire"
        assert result.get("regime_context") == "session_extreme_london"

    def test_regime_context_ny(self):
        frames = make_frames(
            close=4992.0,
            session_london=0.0,
            session_ny=1.0,
            trend_regime=0.6,
            rsi_14=30.0,
        )
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") != "none", "Expected signal to fire"
        assert result.get("regime_context") == "session_extreme_ny"


# ---------------------------------------------------------------------------
# Regime vocabulary correctness (LLM score cache key alignment)
# ---------------------------------------------------------------------------


class TestRegimeVocabulary:
    def test_regime_context_london(self):
        frames = make_frames(close=5009.0, session_london=1.0, session_ny=0.0)
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") != "none", "Expected signal to fire"
        assert result.get("regime_context") == "session_extreme_london"

    def test_regime_context_ny(self):
        frames = make_frames(
            close=4992.0,
            session_london=0.0,
            session_ny=1.0,
            trend_regime=0.6,
            rsi_14=30.0,
        )
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") != "none", "Expected signal to fire"
        assert result.get("regime_context") == "session_extreme_ny"

    def test_regime_context_overlap_both(self):
        frames = make_frames(close=5009.0, session_london=1.0, session_ny=1.0)
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") != "none", "Expected signal to fire"
        assert result.get("regime_context") == "session_extreme_both"

    def test_supporting_factors_includes_session_label_london(self):
        frames = make_frames(close=5009.0, session_london=1.0, session_ny=0.0)
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") != "none", "Expected signal to fire"
        factors = result.get("supporting_factors", [])
        assert "session:london" in factors

    def test_supporting_factors_includes_session_label_ny(self):
        frames = make_frames(
            close=4992.0,
            session_london=0.0,
            session_ny=1.0,
            trend_regime=0.6,
            rsi_14=30.0,
        )
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") != "none", "Expected signal to fire"
        factors = result.get("supporting_factors", [])
        assert "session:ny" in factors

    def test_supporting_factors_includes_session_label_both(self):
        frames = make_frames(close=5009.0, session_london=1.0, session_ny=1.0)
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") != "none", "Expected signal to fire"
        factors = result.get("supporting_factors", [])
        assert "session:both" in factors


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_no_signal_when_price_at_midpoint(self):
        """Price at 5000 — equidistant from 4990/5010 (1 ATR away), beyond 0.3 ATR."""
        frames = make_frames(close=5000.0)  # dist = 10/10 = 1.0 ATR >> 0.3
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") == "none"

    def test_proximity_boundary_fires_at_exact_threshold(self):
        """Price exactly 0.3 * ATR from asian_high → fires."""
        close = ASIAN_HIGH - 0.3 * ATR  # = 5010 - 3 = 5007
        frames = make_frames(close=close)
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") != "none"

    def test_proximity_boundary_no_signal_just_outside(self):
        """Price at 0.31 * ATR from asian_high → does not fire (proximity gate, not factor gate)."""
        close = ASIAN_HIGH - 0.31 * ATR  # = 5006.9
        # Confirming factors present so only the proximity gate can block the signal
        frames = make_frames(close=close, trend_regime=-0.6, rsi_14=70.0, high_volume=False)
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") == "none"

    def test_insufficient_bars_returns_empty(self):
        close_arr = np.full(20, BASE_CLOSE)  # < min_lookback=50
        df = make_ohlcv(close_arr)
        features = {
            "atr_14": ATR,
            "asian_session_high": ASIAN_HIGH,
            "asian_session_low": ASIAN_LOW,
            "session_london": 1.0,
        }
        result = SessionExtremesSetupPlugin().compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        assert result == {}

    def test_tight_asian_range_picks_closer_extreme(self):
        """When simultaneously near both extremes, picks the closer one (near_low wins here)."""
        # dist_high = |5001 - 5002| / 10 = 0.1; dist_low = |5001 - 5000.5| / 10 = 0.05
        # near_low wins (closer); use bullish factors to confirm the long direction
        frames = make_frames(
            close=5001.0,
            asian_high=5002.0,
            asian_low=5000.5,
            trend_regime=0.6,  # bullish — aligns with fade-low (long)
            rsi_14=30.0,  # oversold — aligns with fade-low (long)
        )
        result = SessionExtremesSetupPlugin().compute_full(frames)
        assert result.get("signal_type") != "none", "Expected signal to fire"
        assert result.get("direction") == 1  # fade low = long
