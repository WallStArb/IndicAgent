"""Market event schemas for gap fill requests.

BarGapRequest is the typed contract published by BarAuditor to topic_gap_requests.

BarGapRequest design decisions (Phase 53.1):
- request_id is auto-generated UUID for DLQ correlation/traceability.
- source identifies the requesting agent for audit trail.
- start_ts/end_ts must be UTC-aware datetimes.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class BarGapRequest(BaseModel):
    """Gap fill request published by BarAuditor to topic_gap_requests.

    DataProviderAgent consumes these and fetches historical bars from IBKR.
    request_id enables DLQ correlation. source identifies the requesting agent.
    """

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    tf: str
    start_ts: datetime
    end_ts: datetime
    source: str = "bar_auditor"
