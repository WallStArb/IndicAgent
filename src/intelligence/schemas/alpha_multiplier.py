from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AgentResult(BaseModel):
    """Result of a single swarm agent calculation."""

    model_config = ConfigDict(frozen=True)

    agent_id: str
    multiplier: float = Field(..., ge=0.0, le=2.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AlphaMultiplier(BaseModel):
    """Unified payload for Alpha Multiplier contributions."""

    model_config = ConfigDict(frozen=True)

    signal_id: UUID
    ts: datetime

    path: Literal["deterministic", "llm_swarm"]

    contributors: dict[str, AgentResult]
    final_alpha_multiplier: float = Field(..., ge=0.0, le=2.0)

    @property
    def is_production_ready(self) -> bool:
        """Returns True only for deterministic-path multipliers safe for production injection."""
        return self.path == "deterministic"
