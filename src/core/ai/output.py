"""AgentOutput — universal output envelope for all AI agents."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AgentOutput(BaseModel):
    """Universal output envelope for all AI agents.

    payload is intentionally untyped at the infrastructure level.
    Consumers (aggregator, writer) interpret payload internals.
    Infrastructure (dispatcher, SafeAgentWrapper, graduation) handles
    AgentOutput without knowing payload internals.
    """

    model_config = ConfigDict(frozen=True)

    agent_id: str
    group: str
    signal_id: UUID | None = None
    symbol: str = ""
    timeframe: str = ""
    ts: datetime | None = None
    output_type: str = "neutral"
    payload: dict[str, Any] = Field(default_factory=dict)
    shadow_only: bool = True
    latency_ms: float = 0.0
    error: str | None = None
