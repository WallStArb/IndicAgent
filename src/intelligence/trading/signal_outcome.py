from __future__ import annotations

from enum import Enum


class SignalOutcome(str, Enum):
    """Signal exit outcome — the 8-class classification used as ML training labels.

    Extends str so asyncpg accepts values directly and .value matches DB strings.
    No DB migration needed for existing rows — values are identical to current strings.

    CRITICAL: These are the labels for the ML training dataset. Never add a new
    outcome without also updating the DB CHECK constraint in signal_ledger.
    """

    NEVER_ACTIVATED = "never_activated"
    STOPPED_AT_ENTRY = "stopped_at_entry"
    STOPPED_IN_TRADE = "stopped_in_trade"
    TARGET_1 = "target_1"
    TARGET_1_2 = "target_1_2"
    TARGET_FULL = "target_full"
    TTL_EXPIRED_AHEAD = "ttl_expired_ahead"
    TTL_EXPIRED_BEHIND = "ttl_expired_behind"
    CONDITION_EXPIRED = "condition_expired"  # emitted by lifecycle_tracker staleness exit (lifecycle_tracker.py:379)


# Outcome taxonomy groupings — single source of truth for win/loss classification
WIN_OUTCOMES: frozenset[str] = frozenset(
    {
        SignalOutcome.TARGET_1,
        SignalOutcome.TARGET_1_2,
        SignalOutcome.TARGET_FULL,
    }
)

STOP_OUTCOMES: frozenset[str] = frozenset(
    {
        SignalOutcome.STOPPED_AT_ENTRY,
        SignalOutcome.STOPPED_IN_TRADE,
    }
)

TTL_OUTCOMES: frozenset[str] = frozenset(
    {
        SignalOutcome.TTL_EXPIRED_AHEAD,
        SignalOutcome.TTL_EXPIRED_BEHIND,
        SignalOutcome.CONDITION_EXPIRED,
    }
)
