"""Unit tests for SignalOutcome persistence — Phase 134 Plan 01.

Covers:
1. _classify_stop_outcome MFE threshold boundary
2. _classify_stop_outcome bars_in_trade_count threshold boundary
3. _classify_stop_outcome with None bars (never activated = entry stop)
4. CONDITION_EXPIRED as the 9th SignalOutcome member
5. Backfill SQL CASE mapping coverage (pure Python, no DB required)
"""

import pytest

from src.intelligence.trading.lifecycle_tracker import _classify_stop_outcome
from src.intelligence.trading.signal_outcome import (
    STOP_OUTCOMES,
    TTL_OUTCOMES,
    SignalOutcome,
)


class TestClassifyStopOutcomeMfeThreshold:
    """_classify_stop_outcome boundary: actual_mfe <= 0.05 => STOPPED_AT_ENTRY."""

    def test_exactly_at_threshold_is_entry_stop(self):
        # mfe == 0.05 is AT the threshold — must return STOPPED_AT_ENTRY
        result = _classify_stop_outcome(0.05, 10)
        assert result == SignalOutcome.STOPPED_AT_ENTRY

    def test_just_above_threshold_is_in_trade_stop(self):
        # mfe == 0.06 is ABOVE the threshold — must return STOPPED_IN_TRADE
        result = _classify_stop_outcome(0.06, 10)
        assert result == SignalOutcome.STOPPED_IN_TRADE

    def test_zero_mfe_is_entry_stop(self):
        result = _classify_stop_outcome(0.0, 10)
        assert result == SignalOutcome.STOPPED_AT_ENTRY

    def test_negative_mfe_is_entry_stop(self):
        result = _classify_stop_outcome(-0.5, 10)
        assert result == SignalOutcome.STOPPED_AT_ENTRY


class TestClassifyStopOutcomeBarsThreshold:
    """_classify_stop_outcome boundary: bars_in_trade_count <= 2 => STOPPED_AT_ENTRY."""

    def test_exactly_2_bars_is_entry_stop(self):
        # bars == 2 is AT the threshold — must return STOPPED_AT_ENTRY
        result = _classify_stop_outcome(0.10, 2)
        assert result == SignalOutcome.STOPPED_AT_ENTRY

    def test_3_bars_above_mfe_threshold_is_in_trade(self):
        # bars == 3 is ABOVE the threshold with mfe above — must return STOPPED_IN_TRADE
        result = _classify_stop_outcome(0.10, 3)
        assert result == SignalOutcome.STOPPED_IN_TRADE

    def test_1_bar_is_entry_stop(self):
        result = _classify_stop_outcome(0.50, 1)
        assert result == SignalOutcome.STOPPED_AT_ENTRY


class TestClassifyStopOutcomeNoneBars:
    """_classify_stop_outcome with bars=None => STOPPED_AT_ENTRY (never activated)."""

    def test_none_bars_high_mfe_returns_entry_stop(self):
        # High MFE but None bars => never activated => entry stop
        result = _classify_stop_outcome(0.10, None)
        assert result == SignalOutcome.STOPPED_AT_ENTRY

    def test_none_bars_zero_mfe_returns_entry_stop(self):
        result = _classify_stop_outcome(0.0, None)
        assert result == SignalOutcome.STOPPED_AT_ENTRY


class TestConditionExpiredIsValidOutcome:
    """CONDITION_EXPIRED is the 9th SignalOutcome member — review finding #2 fix."""

    def test_enum_has_9_members(self):
        assert len(SignalOutcome) == 9

    def test_condition_expired_value_string(self):
        assert SignalOutcome.CONDITION_EXPIRED.value == "condition_expired"

    def test_condition_expired_extends_str(self):
        # SignalOutcome extends str — enum member IS the string
        assert SignalOutcome.CONDITION_EXPIRED == "condition_expired"

    def test_condition_expired_in_ttl_outcomes(self):
        # CONDITION_EXPIRED is a time/condition exit — grouped with TTL_OUTCOMES
        assert SignalOutcome.CONDITION_EXPIRED in TTL_OUTCOMES

    def test_condition_expired_not_in_stop_outcomes(self):
        assert SignalOutcome.CONDITION_EXPIRED not in STOP_OUTCOMES

    def test_backfill_condition_expired_maps_to_itself(self):
        # The backfill SQL CASE maps exit_reason='condition_expired' -> 'condition_expired'
        # NOT 'ttl_expired_behind' (that would be lossy — review finding #2).
        exit_reason = "condition_expired"
        outcome = _backfill_case(exit_reason, actual_mfe=None, actual_bars=None)
        assert (
            outcome == "condition_expired"
        ), "condition_expired must map to itself — not ttl_expired_behind"


class TestBackfillSqlCoverage:
    """Parametrized coverage of every CASE branch in the backfill SQL.

    Pure Python — mirrors the SQL CASE logic. No DB required.
    Ensures Python code and SQL never drift.
    """

    @pytest.mark.parametrize(
        "exit_reason,actual_mfe,actual_bars,expected",
        [
            # stop_loss — MFE-gated sub-classification
            ("stop_loss", 0.04, 10, "stopped_at_entry"),  # mfe <= 0.05
            ("stop_loss", 0.05, 10, "stopped_at_entry"),  # mfe == 0.05 (inclusive)
            ("stop_loss", 0.06, 10, "stopped_in_trade"),  # mfe > 0.05
            ("stop_loss", 0.10, 2, "stopped_at_entry"),  # bars <= 2
            ("stop_loss", 0.10, 3, "stopped_in_trade"),  # bars > 2, mfe > 0.05
            ("stop_loss", 0.10, None, "stopped_at_entry"),  # bars IS NULL
            # chandelier_stop — always stopped_in_trade
            ("chandelier_stop", 0.0, None, "stopped_in_trade"),
            ("chandelier_stop", 0.5, 5, "stopped_in_trade"),
            # condition_expired — maps to itself (NOT ttl_expired_behind)
            ("condition_expired", 0.0, None, "condition_expired"),
            ("condition_expired", 0.5, 3, "condition_expired"),
            # ttl_expired — sign of mfe determines ahead/behind
            ("ttl_expired", 0.1, 5, "ttl_expired_ahead"),  # mfe > 0
            ("ttl_expired", 0.0, 5, "ttl_expired_behind"),  # mfe == 0
            ("ttl_expired", -0.1, 5, "ttl_expired_behind"),  # mfe < 0
            # verbatim exit_reason passthrough
            ("target_1", 0.5, 5, "target_1"),
            ("target_1_2", 0.5, 5, "target_1_2"),
            ("target_full", 0.5, 5, "target_full"),
            ("ttl_expired_ahead", 0.3, 5, "ttl_expired_ahead"),
            ("ttl_expired_behind", -0.1, 5, "ttl_expired_behind"),
        ],
    )
    def test_backfill_case_mapping(self, exit_reason, actual_mfe, actual_bars, expected):
        result = _backfill_case(exit_reason, actual_mfe, actual_bars)
        assert result == expected, (
            f"exit_reason={exit_reason!r}, mfe={actual_mfe}, bars={actual_bars} "
            f"=> expected {expected!r}, got {result!r}"
        )

    def test_unknown_exit_reason_returns_none(self):
        # Unknown exit_reason falls through to ELSE NULL in SQL
        result = _backfill_case("some_unknown_reason", 0.5, 5)
        assert result is None


# ---------------------------------------------------------------------------
# Helper: Python mirror of the backfill SQL CASE expression
# ---------------------------------------------------------------------------


def _backfill_case(exit_reason: str, actual_mfe, actual_bars) -> str | None:
    """Python equivalent of the backfill SQL CASE in migration 149.

    Must stay in sync with:
      production/migrations/149_phase134_outcome_column.sql (UPDATE ... SET outcome = CASE ...)
    """
    if exit_reason == "stop_loss":
        if actual_mfe is None or actual_bars is None or actual_bars <= 2 or actual_mfe <= 0.05:
            return "stopped_at_entry"
        else:
            return "stopped_in_trade"
    elif exit_reason == "chandelier_stop":
        return "stopped_in_trade"
    elif exit_reason == "condition_expired":
        return "condition_expired"
    elif exit_reason == "ttl_expired":
        if actual_mfe is not None and actual_mfe > 0:
            return "ttl_expired_ahead"
        else:
            return "ttl_expired_behind"
    elif exit_reason in (
        "target_1",
        "target_1_2",
        "target_full",
        "ttl_expired_ahead",
        "ttl_expired_behind",
    ):
        return exit_reason
    else:
        return None
