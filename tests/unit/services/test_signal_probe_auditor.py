"""Unit tests for SignalProbeAuditor simulation logic.

Tests the pure simulate_outcome() function without any DB access.
"""

from __future__ import annotations

from services.signal_probe_auditor import (
    _JOB_LABEL,
    NEEDS_REFACTOR_SETUPS,
    simulate_outcome,
)


def _make_signal(
    direction: int = 1,
    entry_zone_low: float = 100.0,
    entry_zone_high: float = 101.0,
    stop_loss: float | None = 99.0,
) -> dict:
    return {
        "signal_id": "test-signal-uuid",
        "direction": direction,
        "entry_zone_low": entry_zone_low,
        "entry_zone_high": entry_zone_high,
        "stop_loss": stop_loss,
    }


def _make_bar(high: float, low: float, close: float | None = None) -> dict:
    return {
        "timestamp": None,
        "open": (high + low) / 2,
        "high": high,
        "low": low,
        "close": close if close is not None else (high + low) / 2,
    }


class TestSimulateOutcome:
    """Tests for the pure simulate_outcome helper."""

    def test_long_signal_activates_when_bar_dips_to_entry_zone_high(self) -> None:
        """A long signal activates when a forward bar's low <= entry_zone_high."""
        sig = _make_signal(direction=1, entry_zone_high=101.0, stop_loss=99.0)
        # First bar stays above zone; second dips into zone.
        bars = [
            _make_bar(high=103.0, low=101.5, close=102.0),
            _make_bar(high=102.0, low=100.8, close=101.5),  # low <= 101.0 triggers
        ]
        result = simulate_outcome(sig, bars)

        assert result["sim_activated"] is True
        assert result["sim_entry_price"] == 101.0
        assert result["sim_pnl_r"] is not None
        assert result["sim_outcome"] == "window_end"

    def test_long_signal_never_activated_when_bars_stay_above_zone(self) -> None:
        """A long signal is never activated when all bars stay above entry_zone_high."""
        sig = _make_signal(direction=1, entry_zone_high=101.0, stop_loss=99.0)
        bars = [
            _make_bar(high=105.0, low=102.0, close=104.0),
            _make_bar(high=106.0, low=103.0, close=105.0),
        ]
        result = simulate_outcome(sig, bars)

        assert result["sim_activated"] is False
        assert result["sim_pnl_r"] is None
        assert result["sim_outcome"] == "never_activated"

    def test_short_signal_activates_when_bar_rises_to_entry_zone_low(self) -> None:
        """A short signal activates when a forward bar's high >= entry_zone_low."""
        sig = _make_signal(direction=-1, entry_zone_low=100.0, stop_loss=102.0)
        # First bar stays below zone; second rises into zone.
        bars = [
            _make_bar(high=99.0, low=98.0, close=98.5),
            _make_bar(high=100.5, low=99.0, close=99.5),  # high >= 100.0 triggers
        ]
        result = simulate_outcome(sig, bars)

        assert result["sim_activated"] is True
        assert result["sim_entry_price"] == 100.0
        assert result["sim_pnl_r"] is not None

    def test_pnl_r_sign_matches_favorable_movement(self) -> None:
        """After long activation, favorable upward movement produces positive pnl_r."""
        sig = _make_signal(direction=1, entry_zone_high=100.0, stop_loss=99.0)
        # Activating bar dips into zone; subsequent bars rally strongly.
        bars = [
            _make_bar(high=100.5, low=99.5, close=100.0),  # activates at low=99.5 <= 100
            _make_bar(high=103.0, low=101.0, close=102.5),  # favorable
            _make_bar(high=104.0, low=102.0, close=103.5),  # favorable
        ]
        result = simulate_outcome(sig, bars)

        assert result["sim_activated"] is True
        assert result["sim_pnl_r"] is not None
        # Exit at last close (103.5); entry at 100.0; stop distance = 1.0.
        # pnl_r = (103.5 - 100.0) / 1.0 = 3.5 → positive.
        assert result["sim_pnl_r"] > 0

    def test_pnl_r_adverse_movement_produces_negative_pnl_r(self) -> None:
        """After long activation, adverse downward movement produces negative pnl_r."""
        sig = _make_signal(direction=1, entry_zone_high=100.0, stop_loss=99.0)
        # Activating bar; subsequent bars drop below entry.
        bars = [
            _make_bar(high=100.5, low=99.8, close=100.0),  # activates (low=99.8 <= 100)
            _make_bar(high=100.0, low=98.0, close=98.5),  # adverse
        ]
        result = simulate_outcome(sig, bars)

        assert result["sim_activated"] is True
        assert result["sim_pnl_r"] is not None
        # Exit at 98.5; entry at 100.0; pnl = (98.5 - 100.0) = -1.5; R = -1.5 → negative.
        assert result["sim_pnl_r"] < 0

    def test_no_forward_bars_returns_never_activated(self) -> None:
        """Empty forward bars result in never_activated with no pnl."""
        sig = _make_signal()
        result = simulate_outcome(sig, [])

        assert result["sim_activated"] is False
        assert result["sim_outcome"] == "never_activated"
        assert result["bars_forward"] == 0
        assert result["sim_pnl_r"] is None

    def test_missing_entry_zone_returns_never_activated(self) -> None:
        """Signal missing entry zone returns never_activated without crash."""
        sig = {
            "signal_id": "test",
            "direction": 1,
            "entry_zone_low": None,
            "entry_zone_high": None,
            "stop_loss": 99.0,
        }
        bars = [_make_bar(high=102.0, low=100.0)]
        result = simulate_outcome(sig, bars)

        assert result["sim_activated"] is False
        assert result["sim_outcome"] == "never_activated"

    def test_bars_forward_count_is_correct(self) -> None:
        """bars_forward reflects the total number of forward bars provided."""
        sig = _make_signal(direction=1, entry_zone_high=200.0)  # zone not touched
        bars = [_make_bar(high=202.0, low=201.0) for _ in range(5)]
        result = simulate_outcome(sig, bars)

        assert result["bars_forward"] == 5


class TestJobLabelContract:
    """Guards D-06: job label MUST match the systemd unit suffix exactly."""

    def test_job_label_matches_unit_suffix(self) -> None:
        assert _JOB_LABEL == "signal-probe-auditor"


class TestNeedsRefactorSetups:
    """Smoke tests for the NEEDS_REFACTOR_SETUPS frozenset."""

    def test_has_21_setups(self) -> None:
        assert len(NEEDS_REFACTOR_SETUPS) == 21

    def test_known_setups_present(self) -> None:
        assert "trad_OFIContinuation" in NEEDS_REFACTOR_SETUPS
        assert "trad_CVDDivergence" in NEEDS_REFACTOR_SETUPS
        assert "trad_VCP" in NEEDS_REFACTOR_SETUPS
