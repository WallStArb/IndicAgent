"""BarMessage schema and SessionType enum.

BarMessage is the canonical typed representation of a completed 1m (or higher)
bar as it flows through the feature pipeline. All pipeline services deserialize
incoming bar payloads to BarMessage and work with typed fields — no raw dicts.

Design decisions (D-17, D-18, D-20):
- volume is int (not float) — exchange-reported bar volumes are always integers.
- source discriminates bar origin so downstream can weight differently.
- gap_preceding defaults to False — most bars are contiguous; gaps are flagged
  by the bar accumulator or TWS daemon when ts delta > expected TF interval.
- session_type carries session context from ingestion so plugins don't need
  to re-derive it from the timestamp.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from src.core.bar_normalizer import (
    SOURCE_HTF_DERIVED,
    SOURCE_IBKR_GENERIC,
    SOURCE_IBKR_NAMED,
    SOURCE_IBKR_SEED,
    SOURCE_UNKNOWN,
)


class SessionType(str, Enum):
    """Trading session classification for a bar.

    RTH   — Regular Trading Hours (e.g. 09:30–16:00 ET for US equities/futures)
    ETH   — Extended Trading Hours (pre/post market)
    CRYPTO — 24/7 continuous (no session boundaries)
    FX    — 24/5 FX market (Sunday 17:00 – Friday 17:00 ET)
    CLOSED — Bar arrived during a known closed period (holidays, exchange halt)
    """

    RTH = "rth"
    ETH = "eth"
    CRYPTO = "crypto"
    FX = "fx"
    CLOSED = "closed"


class BarMessage(BaseModel):
    """Canonical typed bar flowing through the feature pipeline.

    Fields:
        ts            — Bar open timestamp (UTC, timezone-aware)
        symbol        — Instrument symbol (e.g. "ES", "NQ")
        tf            — Timeframe string (e.g. "1m", "5m", "15m", "1h")
        open          — Open price
        high          — High price
        low           — Low price
        close         — Close price
        volume        — Volume as integer (exchange-reported)
        source        — Bar origin discriminator:
                          "ibkr_named"  — named bar from TWS reqHistoricalData
                          "ibkr_seed"   — historical seed bar from backfill
                          "htf_derived" — aggregated from 1m bars by BarAccumulator
                          "ibkr"        — generic IBKR bar (IBKRAdapter / RTB fallback)
                          "unknown"     — source missing from payload (provider-agnostic fallback)
        session_type  — Trading session at bar close time
        gap_preceding — True when a gap exists before this bar (missing bars)
        is_flat_bar   — True when bar has zero volume (flat fill from prev close);
                        False for normal bars with real trade activity.
                        HTF bars: True only when ALL constituent 1m bars were flat.
        bar_id        — Log-correlation trace handle only. UUID4, auto-generated.
                        Flows through IntelligenceEvent and signal dicts for
                        cross-service log correlation. Never written to the DB —
                        (symbol, tf, ts) is the canonical natural key for joins.
    """

    ts: datetime
    symbol: str
    tf: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    source: Literal[
        SOURCE_IBKR_NAMED, SOURCE_IBKR_SEED, SOURCE_HTF_DERIVED, SOURCE_IBKR_GENERIC, SOURCE_UNKNOWN
    ]
    session_type: SessionType
    gap_preceding: bool = False
    is_flat_bar: bool = False
    bar_id: UUID = Field(default_factory=uuid4)
