from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProvenanceChain(BaseModel):
    """Zero-copy provenance metadata for intelligence records."""
    origin_ts: datetime
    pipeline_id: str
    plugin_stack: list[str]
    compute_budget_ms: float

class IntelligenceJournal(BaseModel):
    """Atomic IntelligenceJournal record for Unified Intelligence Journaling."""
    ts: datetime = Field(..., description="Journaling timestamp (UTC)")
    sid: str = Field(..., description="Signal ID or unique event identifier")
    payload: dict[str, Any]
    provenance: ProvenanceChain
    version: str = "1.0.0"
