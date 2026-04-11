"""GuardrailsValidator — Pydantic schema validation for LLM responses.

Each call_type registers a schema. generate() responses are validated before
returned to callers. Invalid responses → None (logged, published to DLQ by chain).
"""
from __future__ import annotations

import json
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class GuardrailsValidator:
    """Registry of Pydantic schemas per call_type."""

    def __init__(self) -> None:
        self._schemas: dict[str, Any] = {}  # call_type → Pydantic model class

    def register(self, call_type: str, schema: Any) -> None:
        """Register a Pydantic schema for a call_type."""
        self._schemas[call_type] = schema

    def validate(self, call_type: str, response: str) -> dict[str, Any] | None:
        """Parse and validate response against registered schema.

        Returns validated dict on success, None on failure.
        No schema registered → returns None (treat as unvalidated; caller decides).
        """
        schema = self._schemas.get(call_type)
        if schema is None:
            return None

        try:
            raw = json.loads(response)
            validated = schema.model_validate(raw)
            return validated.model_dump()
        except Exception as exc:
            logger.warning(
                "guardrails.validation_failed",
                call_type=call_type,
                error=str(exc),
                response_preview=response[:100],
            )
            return None
