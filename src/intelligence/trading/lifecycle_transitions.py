"""Lifecycle transition types and serialization for signal state changes.

Published by IntelligencePipeline to lifecycle.transitions topic.
Consumed by LifecycleWriter for atomic persistence to signal_ledger.

Version: 1.0.0
Last Updated: 2026-04-10
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from src.core.service_utils import format_iso_ts


class TransitionType(StrEnum):
    """Signal lifecycle transition types."""

    ACTIVATION = "activation"
    EXIT = "exit"
    CHANDELIER_UPDATE = "chandelier_update"
    MAE_MFE_UPDATE = "mae_mfe_update"
    SHADOW_OUTCOME = "shadow_outcome"
    MARKET_RESOLUTION = "market_resolution"


@dataclass
class LifecycleTransition:
    """A single signal lifecycle state transition event.

    Attributes:
        transition_type: The type of lifecycle transition.
        signal_id: Unique identifier for the signal.
        symbol: Ticker symbol (e.g. "ESM6").
        timeframe: Bar timeframe (e.g. "1m", "15m").
        bar_ts: UTC timestamp of the bar that triggered this transition.
        data: Arbitrary payload specific to the transition type.
    """

    transition_type: TransitionType
    signal_id: str
    symbol: str
    timeframe: str
    bar_ts: datetime
    data: dict = field(default_factory=dict)


def _json_safe(obj: Any) -> Any:
    """Recursively convert non-serializable types (UUID, datetime) for JSON."""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, datetime):
        return format_iso_ts(obj)
    try:
        from uuid import UUID

        if isinstance(obj, UUID):
            return str(obj)
    except ImportError:
        pass
    return obj


def to_dict(t: LifecycleTransition) -> dict:
    """Serialize a LifecycleTransition to a JSON-friendly dict."""
    return {
        "transition_type": t.transition_type.value,
        "signal_id": str(t.signal_id),
        "symbol": t.symbol,
        "timeframe": t.timeframe,
        "bar_ts": format_iso_ts(t.bar_ts),
        "data": _json_safe(t.data),
    }


def from_dict(d: dict) -> LifecycleTransition:
    """Deserialize a dict to a LifecycleTransition.

    Raises:
        ValueError: If transition_type is not a valid TransitionType.
    """
    raw_type = d["transition_type"]
    try:
        transition_type = TransitionType(raw_type)
    except ValueError as error:
        valid = ", ".join(t.value for t in TransitionType)
        raise ValueError(
            f"Invalid transition_type '{raw_type}'. Must be one of: {valid}"
        ) from error

    bar_ts_str = d["bar_ts"]
    bar_ts = datetime.fromisoformat(bar_ts_str)
    # Handle naive timestamps by assuming UTC
    if bar_ts.tzinfo is None:
        bar_ts = bar_ts.replace(tzinfo=UTC)

    return LifecycleTransition(
        transition_type=transition_type,
        signal_id=d["signal_id"],
        symbol=d["symbol"],
        timeframe=d["timeframe"],
        bar_ts=bar_ts,
        data=d.get("data", {}),
    )
