"""SignalOutcome enum — re-exported from canonical location.

Canonical source: src/intelligence/trading/signal_outcome.py

This re-export module allows stage code to import from the enums package
rather than reaching into the trading module directly.
"""

from __future__ import annotations

from src.intelligence.trading.signal_outcome import (
    STOP_OUTCOMES,
    TTL_OUTCOMES,
    WIN_OUTCOMES,
    SignalOutcome,
)

__all__ = ["SignalOutcome", "WIN_OUTCOMES", "STOP_OUTCOMES", "TTL_OUTCOMES"]
