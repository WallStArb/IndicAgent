from src.intelligence.trading.signal_outcome import (
    STOP_OUTCOMES,
    TTL_OUTCOMES,
    WIN_OUTCOMES,
    SignalOutcome,
)


def test_signal_outcome_has_9_members():
    # Phase 134: CONDITION_EXPIRED added as the 9th member
    assert len(SignalOutcome) == 9


def test_signal_outcome_values_match_db_strings():
    assert SignalOutcome.TARGET_1.value == "target_1"
    assert SignalOutcome.TARGET_1_2.value == "target_1_2"
    assert SignalOutcome.TARGET_FULL.value == "target_full"
    assert SignalOutcome.NEVER_ACTIVATED.value == "never_activated"
    assert SignalOutcome.STOPPED_AT_ENTRY.value == "stopped_at_entry"
    assert SignalOutcome.STOPPED_IN_TRADE.value == "stopped_in_trade"
    assert SignalOutcome.TTL_EXPIRED_AHEAD.value == "ttl_expired_ahead"
    assert SignalOutcome.TTL_EXPIRED_BEHIND.value == "ttl_expired_behind"


def test_win_outcomes_contains_3_members():
    assert len(WIN_OUTCOMES) == 3
    assert SignalOutcome.TARGET_1 in WIN_OUTCOMES
    assert SignalOutcome.TARGET_1_2 in WIN_OUTCOMES
    assert SignalOutcome.TARGET_FULL in WIN_OUTCOMES


def test_stop_outcomes_contains_2_members():
    assert len(STOP_OUTCOMES) == 2
    assert SignalOutcome.STOPPED_AT_ENTRY in STOP_OUTCOMES
    assert SignalOutcome.STOPPED_IN_TRADE in STOP_OUTCOMES


def test_ttl_outcomes_contains_3_members():
    # Phase 134: CONDITION_EXPIRED added to TTL_OUTCOMES (time/condition exit)
    assert len(TTL_OUTCOMES) == 3
    assert SignalOutcome.TTL_EXPIRED_AHEAD in TTL_OUTCOMES
    assert SignalOutcome.TTL_EXPIRED_BEHIND in TTL_OUTCOMES
    assert SignalOutcome.CONDITION_EXPIRED in TTL_OUTCOMES


def test_outcome_taxonomy_is_exhaustive():
    """All 8 outcomes should be covered by taxonomy sets (no orphaned outcomes)."""
    all_covered = WIN_OUTCOMES | STOP_OUTCOMES | TTL_OUTCOMES | {SignalOutcome.NEVER_ACTIVATED}
    assert all_covered == set(SignalOutcome)


def test_signal_outcome_is_str_compatible():
    """SignalOutcome must work as a plain string for DB writes."""
    assert isinstance(SignalOutcome.TARGET_1, str)
    assert SignalOutcome.TARGET_1 == "target_1"
    assert SignalOutcome.NEVER_ACTIVATED == "never_activated"


def test_win_outcomes_backward_compat():
    """signal_ledger.py must re-export WIN_OUTCOMES for backward compatibility."""
    from src.persistence.repository.signal_ledger_repository import WIN_OUTCOMES as ledger_win

    assert ledger_win == WIN_OUTCOMES


def test_signal_outcome_enum_immutable():
    """Enum members should be immutable and hashable."""
    # Can be used in sets
    outcome_set = {SignalOutcome.TARGET_1, SignalOutcome.TARGET_FULL}
    assert len(outcome_set) == 2

    # Can be used as dict keys
    outcome_dict = {SignalOutcome.TARGET_1: "win", SignalOutcome.STOPPED_AT_ENTRY: "loss"}
    assert outcome_dict[SignalOutcome.TARGET_1] == "win"
