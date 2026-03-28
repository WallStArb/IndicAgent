"""ProviderQualityEvent schema for the Phase 54 provider abstraction layer.

Published to `topic_market_data_quality` by the MergerAgent on every bar
received, gap detected, failover, or recovery. Used for:
- Prometheus side-channel latency tracking
- ML training signal: bar delivery timing per provider
- Failover audit trail
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator


class ProviderQualityEvent(BaseModel):
    """Side-channel event published for every bar lifecycle event.

    Fields:
        ts           — Bar open timestamp (UTC-aware, matches BarMessage.ts)
        symbol       — Instrument symbol (e.g. "ES", "NQ")
        tf           — Timeframe string (e.g. "1m", "5m")
        provider     — Provider name: "ibkr", "alpaca", etc.
        event_type   — One of: bar_received, gap_detected, failover, recovery
        publish_ts   — When the provider published the bar to its raw topic (UTC-aware)
        consume_ts   — When the merger consumed it from the raw topic (UTC-aware)
        latency_ms   — Merger latency in milliseconds (consume_ts - publish_ts); stored,
                       not recomputed from timestamps to avoid clock skew issues.
        promoted_provider — On failover/recovery: the provider now serving as primary.
                            None for bar_received / gap_detected events.
    """

    ts: datetime
    symbol: str
    tf: str
    provider: str
    event_type: Literal["bar_received", "gap_detected", "failover", "recovery"]
    publish_ts: datetime
    consume_ts: datetime
    latency_ms: float
    promoted_provider: str | None = None

    @field_validator("ts", "publish_ts", "consume_ts", mode="before")
    @classmethod
    def _require_utc_aware(cls, v: object) -> object:
        """Reject naive datetimes — all timestamps must be UTC-aware."""
        if isinstance(v, datetime) and v.tzinfo is None:
            raise ValueError(
                f"datetime must be timezone-aware (UTC); got naive datetime: {v!r}"
            )
        return v
