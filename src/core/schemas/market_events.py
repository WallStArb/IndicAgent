"""Market event schemas for roll detection and gap fill requests.

RollEvent is the typed contract published by RollComputeAgent to topic_roll_events.
BarGapRequest is a stub for Phase 53.1 BarAuditorAgent gap fill request.

Design decisions (D-11, D-12, D-13):
- All 8 RollEvent fields are required — partial roll data must not flow downstream.
- volume_zscore and confirmation_count are ML features (D-13); captured at fire time.
- roll_gap_pct is signed: positive = contango, negative = backwardation.
- detection_ts is UTC timezone-aware datetime.
- BarGapRequest is a stub only — Phase 53.1 owns the full implementation.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class RollEvent(BaseModel):
    """Typed roll detection event published by RollComputeAgent to topic_roll_events."""

    symbol: str  # base symbol (ES, CL)
    old_contract: str  # ESH6
    new_contract: str  # ESM6
    roll_gap_price: float
    roll_gap_pct: float  # signed: positive=contango, negative=backwardation
    detection_ts: datetime  # UTC
    volume_zscore: float  # confirmation strength — ML feature (D-13)
    confirmation_count: int  # number of bars confirming volume shift (D-13)


class BarGapRequest(BaseModel):
    """Stub for Phase 53.1 BarAuditorAgent — gap fill request."""

    symbol: str
    tf: str
    start_ts: datetime
    end_ts: datetime
