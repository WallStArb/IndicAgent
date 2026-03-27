"""Parity schema — FieldViolation model for parity audit violations.

Phase 52.5: ParityAuditorAgent
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class FieldViolation(BaseModel):
    """A single field-level parity violation between primary and shadow tables.

    Attributes:
        ts: Bar timestamp (join key — identifies which bar had the violation).
        symbol: Instrument symbol.
        tf: Timeframe (e.g. "1m", "5m").
        field_name: Dotted path to the diverging field (e.g. "i1.sma", "winner_confidence").
        primary_value: JSON-serialized value from intelligence_features (legacy_val in DB).
        shadow_value: JSON-serialized value from feature_snapshots_shadow.
        abs_diff: Absolute difference for numeric fields; None for non-numeric.
    """

    ts: datetime
    symbol: str
    tf: str
    field_name: str  # dotted path: "i1.sma", "i3.regime_type"
    primary_value: str  # json-serialized
    shadow_value: str  # json-serialized
    abs_diff: float | None  # for numeric fields only
