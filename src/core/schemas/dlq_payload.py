"""Dead Letter Queue payload schema.

All agents route unprocessable payloads to DLQ using this schema.
Enables systematic analysis of data quality issues.
"""

from pydantic import BaseModel, ConfigDict, field_serializer
from datetime import datetime, UTC


class DLQPayload(BaseModel):
    """Standard Dead Letter Queue payload.

    All agents route unprocessable payloads to DLQ using this schema.
    Enables systematic analysis of data quality issues.
    """

    agent: str  # Agent name that routed to DLQ
    source_topic: str  # Kafka topic where payload was consumed
    error_type: str  # Exception class name (e.g., "ValidationError", "KeyError")
    error_message: str  # Human-readable error message
    payload: dict  # Original payload that failed processing
    timestamp: datetime  # When routed to DLQ (UTC)
    retry_count: int = 0  # Number of retry attempts (0 = first attempt)

    model_config = ConfigDict(json_encoders={datetime: lambda v: v.isoformat()})

    @field_serializer("timestamp")
    def serialize_timestamp(self, value: datetime) -> str:
        """Serialize datetime to ISO format."""
        return value.isoformat()
