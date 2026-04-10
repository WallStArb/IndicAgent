"""Market event schemas for roll detection, gap fill requests, and contract updates.

RollEvent is the typed contract published by RollComputeAgent to topic_roll_events.
BarGapRequest is the typed contract published by BarAuditorAgent to topic_gap_requests.
ContractUpdateEvent is broadcast by ContractMetadataWriterAgent to topic_contract_updates.

Design decisions (D-11, D-12, D-13):
- All 8 RollEvent fields are required — partial roll data must not flow downstream.
- volume_zscore and confirmation_count are ML features (D-13); captured at fire time.
- roll_gap_pct is signed: positive = contango, negative = backwardation.
- detection_ts is UTC timezone-aware datetime.

BarGapRequest design decisions (Phase 53.1):
- request_id is auto-generated UUID for DLQ correlation/traceability.
- source identifies the requesting agent for audit trail.
- start_ts/end_ts must be UTC-aware datetimes.

ContractUpdateEvent design decisions (Phase 58.1):
- Latency optimization for contract-switch propagation: services flush cache on receipt.
- NOT required for correctness; services converge within TTL cache cycle (~60s).
- promoted_at is UTC-aware datetime; base_symbol is the root (ES, CL, NQ).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


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
    """Gap fill request published by BarAuditorAgent to topic_gap_requests.

    DataProviderAgent consumes these and fetches historical bars from IBKR.
    request_id enables DLQ correlation. source identifies the requesting agent.
    """

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    tf: str
    start_ts: datetime
    end_ts: datetime
    source: str = "bar_auditor"


class ContractUpdateEvent(BaseModel):
    """Broadcast when ContractMetadataWriterAgent promotes a new front-month contract.

    Consumed by BarAuditorAgent (cache flush) and any service that caches contract
    state. Not required for correctness — TTL cache handles convergence — but reduces
    contract-switch latency from ~60s to ~1s.

    base_symbol: root symbol (ES, CL, NQ — not the contract code)
    old_contract: outgoing front-month (ESH6)
    new_contract: promoted front-month (ESM6)
    promoted_at: UTC datetime when the promotion was persisted to DB
    """

    base_symbol: str
    old_contract: str
    new_contract: str
    promoted_at: datetime  # UTC


class SignalReplayRequest(BaseModel):
    """Replay request published by SignalAuditorAgent to topic_signal_replay_requests.

    BarReplayAgent consumes these, fetches bars from market_data_ohlcv,
    and republishes to market.bars / market.bars.htf for signal recomputation.

    All datetimes must be UTC-aware (validated at construction time).
    """

    request_id: UUID = Field(default_factory=uuid4)
    symbol: str
    tf: str
    session_start: datetime  # UTC-aware
    session_end: datetime  # UTC-aware
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
