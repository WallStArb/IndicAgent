"""Config schema models and validation for Phase 109 config foundation.

Pydantic v2 models mirroring the config_schema / config_state / config_history DB tables.
Only OPS config is managed here — INFRA keys live in .env, STRUCT keys in code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class ConfigSchemaEntry(BaseModel):
    """Mirrors config_schema DB table (no category, no depends_on per plan spec)."""

    config_key: str
    value_type: str
    default_value: str | None = None
    min_value: float | None = None
    max_value: float | None = None
    allowed_values: list[str] | None = None
    is_secret: bool = False
    version: int = 1
    description: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ConfigChange(BaseModel):
    """Represents a completed config change returned from ConfigService.set()."""

    key: str
    value: Any
    version: int
    changed_at: datetime
    changed_by: str
    reason: str | None = None


class ConfigValidationError(Exception):
    """Raised when a config value fails validation or the key is not allowed."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ConfigVersionConflict(Exception):
    """Raised when an optimistic-lock version check fails on set()."""

    def __init__(self, expected_version: int, actual_version: int) -> None:
        super().__init__(f"Version conflict: expected={expected_version}, actual={actual_version}")
        self.expected_version = expected_version
        self.actual_version = actual_version


@dataclass
class ValidationResult:
    """Result of validate_value() — indicates whether a value is valid."""

    valid: bool
    reason: str | None = None


def validate_value(value: Any, schema: ConfigSchemaEntry) -> ValidationResult:
    """Validate a config value against its schema entry.

    Checks:
    - Type compatibility (int, float, bool, str, json)
    - Numeric range (min_value / max_value)
    - Allowed values membership

    Returns ValidationResult(valid=True) on success or ValidationResult(valid=False, reason=...)
    on failure. Never raises.
    """
    vt = schema.value_type.lower()
    numeric: float | None = None

    # --- Type check ---
    if vt == "int":
        if not isinstance(value, (int, str)):
            return ValidationResult(valid=False, reason=f"Expected int, got {type(value).__name__}")
        try:
            numeric = float(int(value))
        except (ValueError, TypeError):
            return ValidationResult(valid=False, reason=f"Cannot convert {value!r} to int")
    elif vt == "float":
        if not isinstance(value, (int, float, str)):
            return ValidationResult(
                valid=False, reason=f"Expected float, got {type(value).__name__}"
            )
        try:
            numeric = float(value)
        except (ValueError, TypeError):
            return ValidationResult(valid=False, reason=f"Cannot convert {value!r} to float")
    elif vt == "bool":
        if isinstance(value, bool):
            pass
        elif isinstance(value, str) and value.lower() in ("true", "false", "1", "0"):
            pass
        else:
            return ValidationResult(
                valid=False, reason=f"Expected bool ('true'/'false'), got {value!r}"
            )
    elif vt in ("str", "string"):
        pass
    elif vt == "json":
        # Any serialisable Python value is accepted; actual JSON parse done in ConfigService
        pass
    else:
        return ValidationResult(valid=False, reason=f"Unknown value_type: {schema.value_type!r}")

    # --- Range check (only for numeric types) ---
    if vt in ("int", "float") and numeric is not None:
        if schema.min_value is not None and numeric < schema.min_value:
            return ValidationResult(
                valid=False,
                reason=(f"Value {numeric} is below min_value={schema.min_value}"),
            )
        if schema.max_value is not None and numeric > schema.max_value:
            return ValidationResult(
                valid=False,
                reason=(f"Value {numeric} exceeds max_value={schema.max_value}"),
            )

    # --- Allowed values check ---
    if schema.allowed_values is not None:
        str_value = str(value).lower() if vt == "bool" else str(value)
        allowed_lower = [av.lower() for av in schema.allowed_values]
        if str_value.lower() not in allowed_lower:
            return ValidationResult(
                valid=False,
                reason=f"Value {value!r} not in allowed_values={schema.allowed_values}",
            )

    return ValidationResult(valid=True)
