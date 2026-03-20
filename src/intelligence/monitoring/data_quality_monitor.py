"""Data quality monitoring for pipeline stage validation."""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class DataQualityMonitor:
    """Validates data integrity at each pipeline stage.

    Each stage has a named schema that declares required fields and numeric
    constraints (type, min, max).  Validation failures are logged with full
    context so they surface in observability tooling without crashing the
    pipeline.
    """

    # Stage output schemas: field → {type, required, min, max}
    STAGE_SCHEMAS: dict[str, dict[str, dict[str, Any]]] = {
        "intelligence": {
            "symbol": {"type": str, "required": True},
            "timeframe": {"type": str, "required": True},
            "timestamp": {"type": str, "required": True},
        },
        "quality_gated": {
            "confidence": {"type": (int, float), "min": 0.0, "max": 1.0, "required": True},
            "symbol": {"type": str, "required": True},
            "timeframe": {"type": str, "required": True},
        },
        "regime_gated": {
            "confidence": {"type": (int, float), "min": 0.0, "max": 1.0, "required": True},
            "regime_eligible": {"type": bool, "required": True},
        },
        "tod_adjusted": {
            "confidence": {"type": (int, float), "min": 0.0, "max": 1.0, "required": True},
            "tod_multiplier": {"type": (int, float), "min": 0.0, "max": 2.0},
        },
        "calibrated": {
            "confidence": {"type": (int, float), "min": 0.0, "max": 1.0, "required": True},
            "calibrated_confidence": {"type": (int, float), "min": 0.0, "max": 1.0},
        },
        "ranked": {
            "adjusted_rank": {
                "type": (int, float),
                "min": 0.0,
                "max": 1000.0,
                "required": True,
            },
            "confidence": {"type": (int, float), "min": 0.0, "max": 1.0, "required": True},
        },
        "winner": {
            "confidence": {"type": (int, float), "min": 0.0, "max": 1.0, "required": True},
            "direction": {"type": int, "required": True},
        },
    }

    def __init__(self, stage_name: str) -> None:
        self.stage_name = stage_name
        self.schema = self.STAGE_SCHEMAS.get(stage_name, {})

    async def validate_input(self, event: dict) -> bool:
        """Validate input event dict against stage schema.

        Parameters
        ----------
        event:
            Raw event dict (already deserialized).

        Returns
        -------
        bool
            True if valid, False if any constraint violated.
        """
        if not event:
            logger.error(f"[{self.stage_name}] Empty input event")
            return False

        if self.schema:
            return self._validate_against_schema(event, self.schema, "input")

        return True

    async def validate_output(self, output: dict) -> bool:
        """Validate stage output dict against stage schema.

        Parameters
        ----------
        output:
            Stage output dict.

        Returns
        -------
        bool
            True if valid, False if any constraint violated.
        """
        if not output:
            logger.error(f"[{self.stage_name}] Empty output")
            return False

        if self.schema:
            return self._validate_against_schema(output, self.schema, "output")

        return True

    def _validate_against_schema(self, data: dict, schema: dict, context: str) -> bool:
        """Validate a data dict against a schema definition.

        Parameters
        ----------
        data:
            Dict to validate.
        schema:
            Field constraint mapping.
        context:
            "input" or "output" — used in log messages only.

        Returns
        -------
        bool
            True if all constraints satisfied, False on first violation.
        """
        for field, constraints in schema.items():
            # Required field must be present
            if constraints.get("required", False) and field not in data:
                logger.error(
                    f"[{self.stage_name}] Missing required field '{field}' in {context}",
                    field=field,
                    context=context,
                )
                return False

            # Skip optional fields that are absent
            if field not in data:
                continue

            value = data[field]

            # Type check
            expected_types = constraints.get("type")
            if expected_types and not isinstance(value, expected_types):
                logger.error(
                    f"[{self.stage_name}] Field '{field}' has wrong type in {context}",
                    field=field,
                    expected_type=str(expected_types),
                    actual_type=type(value).__name__,
                    context=context,
                )
                return False

            # Numeric lower bound
            if "min" in constraints and value < constraints["min"]:
                logger.error(
                    f"[{self.stage_name}] Field '{field}' below minimum in {context}",
                    field=field,
                    value=value,
                    min_value=constraints["min"],
                    context=context,
                )
                return False

            # Numeric upper bound
            if "max" in constraints and value > constraints["max"]:
                logger.error(
                    f"[{self.stage_name}] Field '{field}' above maximum in {context}",
                    field=field,
                    value=value,
                    max_value=constraints["max"],
                    context=context,
                )
                return False

        return True
