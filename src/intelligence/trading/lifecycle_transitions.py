"""Lifecycle transition types and serialization for signal state changes.

Published by IntelligencePipelineComputeAgent to lifecycle.transitions topic.
Consumed by LifecycleWriterAgent for atomic persistence to signal_ledger.

Version: 1.0.0
Last Updated: 2026-04-10
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class TransitionType(StrEnum):
    """Signal lifecycle transition types."""

    ACTIVATION = "activation"
    EXIT = "exit"
    CHANDELIER_UPDATE = "chandelier_update"
    MAE_MFE_UPDATE = "mae_mfe_update"
    SHADOW_OUTCOME = "shadow_outcome"


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


def to_dict(t: LifecycleTransition) -> dict:
    """Serialize a LifecycleTransition to a JSON-friendly dict."""
    return {
        "transition_type": t.transition_type.value,
        "signal_id": t.signal_id,
        "symbol": t.symbol,
        "timeframe": t.timeframe,
        "bar_ts": t.bar_ts.isoformat(),
        "data": t.data,
    }


def from_dict(d: dict) -> LifecycleTransition:
    """Deserialize a dict to a LifecycleTransition.

    Raises:
        ValueError: If transition_type is not a valid TransitionType.
    """
    raw_type = d["transition_type"]
    try:
        transition_type = TransitionType(raw_type)
    except ValueError as exc:
        valid = ", ".join(t.value for t in TransitionType)
        raise ValueError(
            f"Invalid transition_type '{raw_type}'. Must be one of: {valid}"
        ) from exc

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
