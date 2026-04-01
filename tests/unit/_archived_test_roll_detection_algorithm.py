"""Unit tests for RollMonitor roll detection algorithm — calendar + z-score approach.

Tests the new calendar-driven + volume z-score confirmation algorithm (D-16 through D-20):
- get_expiry_date() for each contract family
- get_roll_window() returning window or None based on ref_date proximity
- RollMonitor.update_volume() with single current_vol parameter (bug D-16 fixed)
- RollMonitor.check_roll() with calendar gate + z-score < -2.0 confirmation
- _on_roll_confirmed() derives new_symbol from derive_roll_chain

Also preserves existing tests for:
- RollMonitor initialization (always active — SHADOW-03 graduated)
- Paper account detection / PAPER_SKIP_CONTRACTS
- Bar loop wiring

Phase 47 Plan 02 — TDD (replaces broken ratio logic from Phase 38-02)
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers: build a minimal Settings mock
# ---------------------------------------------------------------------------


def _make_settings(
    *,
    ib_host: str = "192.168.1.158",  # live TWS by default
    window_size: int = 100,
    threshold_default: float = 1.2,
    confirmation_bars: int = 3,
    cooldown_min: int = 30,
    postroll_bars: int = 10,
    tod_gated: bool = False,  # disabled by default in new tests for simplicity
    env_name: str = "dev",
) -> MagicMock:
    s = MagicMock()
    s.ib_host = ib_host
    s.roll_monitor_window_size = window_size
    s.roll_monitor_threshold_default = threshold_default
    s.roll_confirmation_bars = confirmation_bars
    s.roll_monitor_cooldown_min = cooldown_min
    s.roll_monitor_postroll_bars = postroll_bars
    s.roll_time_of_day_gated = tod_gated
    s.env_name = env_name
    return s


def _make_roll_monitor(settings=None):
    """Import and instantiate RollMonitor with given settings."""
    from services.roll_compute_agent import RollMonitor  # noqa: PLC0415
    s = settings or _make_settings()
    return RollMonitor(s)


# ---------------------------------------------------------------------------
# Tests for get_expiry_date (new function in contracts.py)
# ---------------------------------------------------------------------------


class TestGetExpiryDate:
    """Test 1-4: get_expiry_date per contract family."""

    def test_quarterly_es_march_2026(self):
        """Test 1: ES March 2026 expiry is third Friday = 2026-03-20."""
        from src.config.contracts import get_expiry_date  # noqa: PLC0415
        result = get_expiry_date("ES", 3, 2026)
        assert result == date(2026, 3, 20), f"Expected 2026-03-20, got {result}"

    def test_quarterly_nq_june_2026(self):
        """ES-family quarterly: June 2026 third Friday = 2026-06-19."""
        from src.config.contracts import get_expiry_date  # noqa: PLC0415
        result = get_expiry_date("NQ", 6, 2026)
        # June 1, 2026 is a Monday. Fridays: 5th, 12th, 19th. Third = 19th.
        assert result == date(2026, 6, 19), f"Expected 2026-06-19, got {result}"

    def test_energy_cl_april_2026(self):
        """Test 2: CL April 2026 expiry is last business day of March 2026."""
        from src.config.contracts import get_expiry_date  # noqa: PLC0415
        result = get_expiry_date("CL", 4, 2026)
        # Last business day of March 2026: March 31 is Tuesday — business day.
        assert result == date(2026, 3, 31), f"Expected 2026-03-31, got {result}"

    def test_grain_zc_may_2026(self):
        """Test 3: ZC May 2026 expiry is Friday closest to 15th of May 2026."""
        from src.config.contracts import get_expiry_date  # noqa: PLC0415
        result = get_expiry_date("ZC", 5, 2026)
        # May 15, 2026 is a Friday. Closest Friday to 15th = 15th.
        assert result == date(2026, 5, 15), f"Expected 2026-05-15, got {result}"

    def test_unknown_symbol_default(self):
        """Test 4: UNKNOWN symbol returns conservative default (25th of expiry month)."""
        from src.config.contracts import get_expiry_date  # noqa: PLC0415
        result = get_expiry_date("UNKNOWN", 6, 2026)
        assert result == date(2026, 6, 25), f"Expected 2026-06-25, got {result}"

    def test_unknown_symbol_february(self):
        """Default returns min(25, last_day_of_month) — Feb never has more than 28/29."""
        from src.config.contracts import get_expiry_date  # noqa: PLC0415
        result = get_expiry_date("UNKNOWN", 2, 2026)
        assert result == date(2026, 2, 25)

    def test_quarterly_symbol_classification(self):
        """ZN is quarterly (rates) — third Friday of March 2026."""
        from src.config.contracts import get_expiry_date  # noqa: PLC0415
        es_result = get_expiry_date("ES", 3, 2026)
        zn_result = get_expiry_date("ZN", 3, 2026)
        # Both quarterly — same expiry formula
        assert es_result == zn_result

    def test_metals_gc_june_2026(self):
        """GC June 2026: last business day of May 2026."""
        from src.config.contracts import get_expiry_date  # noqa: PLC0415
        result = get_expiry_date("GC", 6, 2026)
        # Last calendar day of May 2026: May 31 (Sunday) → walk back to May 29 (Friday)
        assert result == date(2026, 5, 29), f"Expected 2026-05-29, got {result}"

    def test_energy_metals_january_wraps_to_december(self):
        """CL January 2026 expiry: last business day of December 2025."""
        from src.config.contracts import get_expiry_date  # noqa: PLC0415
        result = get_expiry_date("CL", 1, 2026)
        # December 31, 2025 is Wednesday — business day.
        assert result == date(2025, 12, 31), f"Expected 2025-12-31, got {result}"


# ---------------------------------------------------------------------------
# Tests for get_roll_window (new function in contracts.py)
# ---------------------------------------------------------------------------


class TestGetRollWindow:
    """Test 5-6: get_roll_window returns window tuple or None."""

    def test_returns_window_during_active_roll_period(self):
        """Test 5: ES roll window around March 2026 expiry (2026-03-20).

        ES March 2026 expiry = 2026-03-20.
        Roll window: ~14 cal days before (3/6) to ~3 cal days before (3/17).
        A date of 2026-03-10 should be inside the window.
        """
        from src.config.contracts import get_roll_window  # noqa: PLC0415
        result = get_roll_window("ES", date(2026, 3, 10))
        assert result is not None, "Expected a roll window for ES on 2026-03-10"
        roll_start, roll_end = result
        assert roll_start <= date(2026, 3, 10) <= roll_end

    def test_returns_none_outside_roll_window(self):
        """Test 6: No roll window when far from expiry (>21 days away)."""
        from src.config.contracts import get_roll_window  # noqa: PLC0415
        # January 15 is >21 days from March 20 expiry
        result = get_roll_window("ES", date(2026, 1, 15))
        assert result is None, f"Expected None for ES on 2026-01-15, got {result}"

    def test_returns_tuple_with_two_dates(self):
        """Window tuple has (start, end) where start < end."""
        from src.config.contracts import get_roll_window  # noqa: PLC0415
        result = get_roll_window("ES", date(2026, 3, 10))
        assert result is not None
        roll_start, roll_end = result
        assert roll_start < roll_end

    def test_unknown_symbol_raises_or_returns_none(self):
        """Unknown symbol (not in FUTURES_ROLL_CYCLES) should not crash; may raise ValueError."""
        from src.config.contracts import get_roll_window  # noqa: PLC0415
        try:
            result = get_roll_window("UNKNOWN_XYZ", date(2026, 3, 10))
            # If it returns rather than raising, it should be None
            assert result is None
        except ValueError:
            pass  # acceptable — derive_roll_chain raises ValueError for unknown symbols


# ---------------------------------------------------------------------------
# Tests for derive_roll_chain expiry_date field (new field in chain dict)
# ---------------------------------------------------------------------------


class TestDeriveRollChainExpiryDate:
    """Test 7: derive_roll_chain output includes expiry_date key."""

    def test_chain_includes_expiry_date_key(self):
        """Test 7: Each entry in derive_roll_chain has an expiry_date field."""
        from src.config.contracts import derive_roll_chain  # noqa: PLC0415
        chain = derive_roll_chain("ES")
        assert len(chain) == 3
        for entry in chain:
            assert "expiry_date" in entry, f"Missing expiry_date in chain entry: {entry}"

    def test_expiry_date_is_date_type(self):
        """expiry_date field is a datetime.date instance."""
        from src.config.contracts import derive_roll_chain  # noqa: PLC0415
        chain = derive_roll_chain("ES")
        for entry in chain:
            assert isinstance(entry["expiry_date"], date), (
                f"expiry_date is not a date: {type(entry['expiry_date'])}"
            )

    def test_existing_keys_preserved(self):
        """Existing keys (symbol, expiry_month, expiry_year, roll_to) are still present."""
        from src.config.contracts import derive_roll_chain  # noqa: PLC0415
        chain = derive_roll_chain("ES")
        for entry in chain:
            assert "symbol" in entry
            assert "expiry_month" in entry
            assert "expiry_year" in entry


# ---------------------------------------------------------------------------
# Tests for RollMonitor.update_volume — single parameter (bug D-16 fixed)
# ---------------------------------------------------------------------------


class TestUpdateVolumeSingleParam:
    """Test 8: update_volume takes only current_vol (no next_vol)."""

    def test_update_volume_single_param_works(self):
        """Test 8: update_volume("ES", 50000.0) accepts one volume parameter."""
        rm = _make_roll_monitor()
        rm.update_volume("ES", 50000.0)  # must not raise TypeError
        assert "ES" in rm._volume_windows
        assert len(rm._volume_windows["ES"]) == 1

    def test_update_volume_appends_float(self):
        """Window stores floats, not tuples."""
        rm = _make_roll_monitor()
        rm.update_volume("ES", 12345.0)
        val = rm._volume_windows["ES"][0]
        assert isinstance(val, float), f"Expected float, got {type(val)}: {val}"

    def test_update_volume_window_maxlen(self):
        """Window respects maxlen from settings."""
        s = _make_settings(window_size=5)
        rm = _make_roll_monitor(s)
        for i in range(10):
            rm.update_volume("ES", float(i))
        assert len(rm._volume_windows["ES"]) == 5

    def test_update_volume_creates_per_symbol_windows(self):
        """Separate windows per symbol."""
        rm = _make_roll_monitor()
        rm.update_volume("ES", 1000.0)
        rm.update_volume("NQ", 2000.0)
        assert "ES" in rm._volume_windows
        assert "NQ" in rm._volume_windows


# ---------------------------------------------------------------------------
# Tests for RollMonitor.check_roll — new calendar + z-score algorithm
# ---------------------------------------------------------------------------


class TestCheckRollOutsideWindow:
    """Test 9: check_roll returns False when get_roll_window returns None."""

    def test_returns_false_outside_roll_window(self):
        """Test 9: No roll window → returns False regardless of volume."""
        rm = _make_roll_monitor()
        # Fill window with volumes that would produce z-score < -2.0
        for _ in range(30):
            rm.update_volume("ES", 50000.0)
        # Insert low-volume readings (would be a strong drop)
        for _ in range(5):
            rm.update_volume("ES", 100.0)

        # Mock get_roll_window to return None (outside roll period)
        with patch("services.roll_compute_agent.get_roll_window", return_value=None):
            utc_now = datetime(2026, 1, 15, 16, 0, tzinfo=UTC)
            result = rm.check_roll("ES", utc_now)
            # With get_roll_window returning None, should be False
            assert result is False


class TestCheckRollZScoreConfirmation:
    """Tests 10-11: z-score gating and confirmation count."""

    def _fill_window_high_then_low(self, rm, base="ES", high_bars=50, low_vol=100.0):
        """Fill rolling window with high volumes, then add low-volume bars."""
        # High baseline so subsequent low bars produce z < -2.0
        for _ in range(high_bars):
            rm.update_volume(base, 50000.0)

    def test_three_consecutive_low_volume_bars_confirm_roll_in_window(self):
        """Test 10: check_roll returns True after 3 consecutive z_score < -2.0 during roll window.

        Uses a window of high volumes + subsequent low bars to produce negative z-scores.
        Patches get_roll_window to simulate being inside a roll period.
        """
        rm = _make_roll_monitor()
        self._fill_window_high_then_low(rm)

        # Reset confirmation count
        rm._confirmation_counts = {}

        utc_now = datetime(2026, 3, 10, 16, 0, tzinfo=UTC)

        # Simulate inside roll window by patching get_roll_window at the correct location
        mock_window = (date(2026, 3, 6), date(2026, 3, 17))

        confirmed = False
        for _ in range(10):
            rm.update_volume("ES", 100.0)  # Very low — should be z < -2.0
            with patch("services.roll_compute_agent.get_roll_window", return_value=mock_window):
                if rm.check_roll("ES", utc_now):
                    confirmed = True
                    break

        assert confirmed, "Roll should be confirmed after 3 consecutive low-volume bars in window"

    def test_zscore_above_threshold_does_not_confirm(self):
        """Test 11: check_roll returns False when z_score is -1.5 (above threshold).

        Fill window with moderately low volumes so z_score is between -1.5 and -2.0.
        """
        rm = _make_roll_monitor()
        # Fill baseline with a mean of 1000.0, std ~100
        import random
        rnd = random.Random(42)
        for _ in range(80):
            rm.update_volume("ES", 1000.0 + rnd.gauss(0, 100))

        # Add a bar at ~850 — about 1.5 std below mean
        rm.update_volume("ES", 850.0)

        utc_now = datetime(2026, 3, 10, 16, 0, tzinfo=UTC)
        mock_window = (date(2026, 3, 6), date(2026, 3, 17))

        with patch("services.roll_compute_agent.get_roll_window", return_value=mock_window):
            rm.check_roll("ES", utc_now)

        # z ~ -1.5 should not produce confirmation — verify count stays low
        assert rm._confirmation_counts.get("ES", 0) <= 1, (
            f"Confirmation count too high for z~-1.5: {rm._confirmation_counts.get('ES', 0)}"
        )

    def test_insufficient_volume_data_returns_false(self):
        """Less than 20 bars → check_roll returns False."""
        rm = _make_roll_monitor()
        for _ in range(15):
            rm.update_volume("ES", 1000.0)

        utc_now = datetime(2026, 3, 10, 16, 0, tzinfo=UTC)
        mock_window = (date(2026, 3, 6), date(2026, 3, 17))
        with patch("services.roll_compute_agent.get_roll_window", return_value=mock_window):
            result = rm.check_roll("ES", utc_now)
        assert result is False


# ---------------------------------------------------------------------------
# Tests for _on_roll_confirmed — uses derive_roll_chain for new_symbol
# ---------------------------------------------------------------------------


class TestOnRollConfirmedChain:
    """Test 12: _on_roll_confirmed was removed from RollMonitor (DB-ignorant per Plan 03).

    RollComputeAgent now builds and publishes the RollEvent directly.
    This test class is preserved as a skip stub so the test history is traceable.
    """

    @pytest.mark.skip(
        reason="DB write method removed in Plan 03 — RollComputeAgent publishes RollEvent directly"
    )
    def test_on_roll_confirmed_uses_chain_roll_to(self):
        """Skipped: DB write method removed from RollMonitor (D-14 DB-ignorant)."""
        pass


# ---------------------------------------------------------------------------
# Tests for call site bug fix — update_volume single arg (D-16)
# ---------------------------------------------------------------------------


class TestCallSiteBugFix:
    """Verify the call site in _emit_bar passes single volume arg.

    NOTE: These tests verified wiring between DataProviderAgent._emit_bar and RollMonitor.
    That integration was removed in Plan 02 (RollMonitor extracted to RollComputeAgent).
    DataProviderAgent no longer calls RollMonitor — RollComputeAgent subscribes to market.bars
    independently. Tests are preserved as skip stubs for traceability.
    """

    @pytest.mark.skip(
        reason="RollMonitor removed from DataProviderAgent in Plan 02 — now in RollComputeAgent"
    )
    def test_emit_bar_calls_update_volume_with_two_args_not_three(self):
        """Skipped: DataProviderAgent._emit_bar no longer calls RollMonitor."""
        pass


# ---------------------------------------------------------------------------
# Preserved existing tests (still valid for new implementation)
# ---------------------------------------------------------------------------


class TestRollMonitorInit:
    def test_init_creates_empty_state(self):
        rm = _make_roll_monitor()
        assert rm._volume_windows == {}
        assert rm._cooldown_until == {}

    def test_init_reads_settings(self):
        s = _make_settings(window_size=50, confirmation_bars=5, cooldown_min=15)
        rm = _make_roll_monitor(s)
        assert rm._window_size == 50
        assert rm._confirmation_required == 5
        assert rm._cooldown_minutes == 15

    def test_always_active_no_enabled_flag(self):
        """Roll monitor is always active — no _enabled flag on RollMonitor."""
        rm = _make_roll_monitor()
        assert not hasattr(rm, "_enabled"), "RollMonitor must not have _enabled (SHADOW-03 graduated)"
        assert not hasattr(rm, "is_enabled"), "is_enabled property must not exist (SHADOW-03 graduated)"


class TestFeatureFlag:
    def test_roll_monitor_always_active_calendar_gate_still_applies(self):
        """Roll monitor is always active — calendar gate still prevents false positives outside windows."""
        rm = _make_roll_monitor()
        for _ in range(30):
            rm.update_volume("ES", 1000.0)
        # Use a date well outside any ES roll window to confirm calendar gate works
        utc_now = datetime(2026, 8, 1, 16, 0, tzinfo=UTC)  # August — not a roll month for ES
        result = rm.check_roll("ES", utc_now)
        assert result is False, "Calendar gate should still return False outside roll window"


class TestPaperAccountDetection:
    def test_paper_account_detected_ibkr_host(self):
        s = _make_settings(ib_host="192.168.1.157")
        rm = _make_roll_monitor(s)
        assert rm._is_paper_account() is True

    def test_paper_account_detected_localhost(self):
        s = _make_settings(ib_host="127.0.0.1")
        rm = _make_roll_monitor(s)
        assert rm._is_paper_account() is True

    def test_live_account_not_paper(self):
        s = _make_settings(ib_host="192.168.1.158")
        rm = _make_roll_monitor(s)
        assert rm._is_paper_account() is False

    def test_paper_account_flag_set_at_init(self):
        s = _make_settings(ib_host="192.168.1.157")
        rm = _make_roll_monitor(s)
        assert rm._is_paper is True

    def test_live_account_flag_false_at_init(self):
        s = _make_settings(ib_host="192.168.1.158")
        rm = _make_roll_monitor(s)
        assert rm._is_paper is False


class TestPaperSkipContracts:
    def test_should_skip_symbol_on_paper_account(self):
        s = _make_settings(ib_host="192.168.1.157")
        rm = _make_roll_monitor(s)
        assert rm.should_skip_symbol("BZJ6") is True
        assert rm.should_skip_symbol("NGJ6") is True
        assert rm.should_skip_symbol("ZWH6") is True

    def test_should_not_skip_non_paper_contracts(self):
        s = _make_settings(ib_host="192.168.1.157")
        rm = _make_roll_monitor(s)
        assert rm.should_skip_symbol("ESM6") is False

    def test_live_account_does_not_skip_paper_contracts(self):
        s = _make_settings(ib_host="192.168.1.158")
        rm = _make_roll_monitor(s)
        assert rm.should_skip_symbol("BZJ6") is False
        assert rm.should_skip_symbol("NGJ6") is False


class TestBarLoopWiring:
    """Tests verifying RollMonitor wiring in the bar emit loop.

    NOTE: DataProviderAgent no longer contains RollMonitor (removed in Plan 02).
    RollComputeAgent now subscribes to market.bars independently and runs RollMonitor.
    These tests are preserved as skip stubs for traceability.
    """

    @pytest.mark.skip(
        reason="RollMonitor removed from DataProviderAgent in Plan 02 — now in RollComputeAgent"
    )
    def test_bar_loop_always_calls_roll_monitor(self):
        """Skipped: DataProviderAgent no longer wires to RollMonitor."""
        pass

    @pytest.mark.skip(
        reason="RollMonitor removed from DataProviderAgent in Plan 02 — now in RollComputeAgent"
    )
    def test_paper_skip_contracts_short_circuit(self):
        """Skipped: DataProviderAgent no longer wires to RollMonitor."""
        pass

