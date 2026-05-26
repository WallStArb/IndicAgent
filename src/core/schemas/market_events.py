"""Market event schemas for gap fill requests and contract updates.

BarGapRequest is the typed contract published by BarAuditorAgent to topic_gap_requests.
ContractUpdateEvent is broadcast by roll_batch to topic_contract_updates.

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
from datetime import datetime

from pydantic import BaseModel, Field


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
