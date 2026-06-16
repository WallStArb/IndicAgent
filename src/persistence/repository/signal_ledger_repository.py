"""signal_ledger_repository — backward-compat re-export shim.

This module is a thin shim. All implementation has moved to signal_events_repository.py
as part of the Phase 130 rename (D-05): SignalLedgerRepository -> SignalEventsRepository,
targeting the 3-table signal architecture (signal_events / trade_frames / trade_executions).

Import from signal_events_repository directly in new code:
    from src.persistence.repository.signal_events_repository import SignalEventsRepository

Services not yet updated to the new import path (signal_writer, lifecycle_writer,
signal_tracker, run_historical_pipeline, feature_replay, signal_replay_auditor) will
continue to resolve via this shim until their Wave 3 rewrites.
"""

from src.persistence.repository.signal_events_repository import (  # noqa: F401
    STOP_OUTCOMES,
    TTL_OUTCOMES,
    WIN_OUTCOMES,
    LedgerEntry,
    SignalEventRow,
    SignalEventsRepository,
    SignalOutcome,
    SignalStatus,
    TradeFrameRow,
)

# Alias for any caller that still references the old class name
SignalLedgerRepository = SignalEventsRepository

__all__ = [
    "SignalEventsRepository",
    "SignalLedgerRepository",
    "SignalStatus",
    "SignalOutcome",
    "STOP_OUTCOMES",
    "TTL_OUTCOMES",
    "WIN_OUTCOMES",
    "LedgerEntry",
    "SignalEventRow",
    "TradeFrameRow",
]
