from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Multiplier bounds: 2.0 = 2x position size (aggressive), 0.0 = complete exit
# Derived from risk management limits and maximum allowable leverage
MIN_MULTIPLIER = 0.0
MAX_MULTIPLIER = 2.0

class AgentTelemetry(BaseModel):
    """Telemetry data for LangSmith and OpenTelemetry integration."""
    trace_id: str
    span_id: str
    latency_ms: float
    model_name: str
    prompt_tokens: int
    completion_tokens: int

class AgentResult(BaseModel):
    """The result of a single swarm agent's analysis."""
    agent_id: str
    multiplier: float = Field(
        ..., ge=MIN_MULTIPLIER, le=MAX_MULTIPLIER, description="Scaling factor for position size."
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    telemetry: AgentTelemetry

class AlphaMultiplier(BaseModel):
    """The aggregate output consumed by the Signal Lifecycle Service."""
    model_config = ConfigDict(frozen=True)

    signal_id: UUID
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    agents: dict[str, AgentResult]
    final_alpha_multiplier: float = Field(..., ge=MIN_MULTIPLIER, le=MAX_MULTIPLIER)

    # Global flag for safety kill-switch
    is_safe: bool = True
    validation_error: str | None = None
