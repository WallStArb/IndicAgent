"""SwarmContext — typed market context for swarm agent computation.

Built from Kafka-deserialized data at the SwarmOrchestratorAgent boundary.
Never touches the database. Bar loop populates the cache; signal loop reads it.
"""

from __future__ import annotations

import time
import types
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from src.intelligence.schemas import IntelligenceEvent, RankedSignal

logger = structlog.get_logger(__name__)

_TTL_SECONDS = 300  # 5 minutes


class SwarmContext(BaseModel):
    """Typed context for swarm agent computation. Immutable after construction."""

    model_config = ConfigDict(frozen=True)

    signal_id: UUID
    symbol: str
    timeframe: str
    ts: Any  # datetime

    # i1 indicators
    atr: float | None
    adx: float | None
    rsi: float | None

    # i4 context classification
    hmm_regime: int | None
    trend_regime: float | None
    vol_regime: float | None
    vol_percentile: float | None
    garch_vol_ratio: float | None
    garch_vol_regime: int | None
    kalman_trend: float | None
    kalman_slope: float | None
    vwap: float | None
    poc_price: float | None
    poc_price_rolling: float | None

    # i6 cross-timeframe confluence
    ctf_score: float | None
    ctf_trend_alignment: float | None
    ctf_structure_alignment: float | None
    ctf_regime_agreement: float | None
    ctf_timeframes_aligned: float | None
    ctf_fvg_alignment: float | None
    ctf_ob_alignment: float | None

    # Winner signal
    winner_plugin: str | None
    winner_direction: int | None
    winner_confidence: float | None

    # Bar OHLCV
    price: float | None
    volume: float | None

    # D-16: enrichment fields (set by SwarmDispatchComputeAgent._enrich_context)
    lead_context: SwarmContext | None = None
    volume_profile: dict[str, Any] | None = None


class SwarmContextCache:
    """asyncio-safe in-memory context cache (NOT thread-safe).

    Bar loop calls update() after each IntelligenceEvent.
    Signal loop calls build() to construct a SwarmContext for agent computation.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], tuple[Any, float]] = {}

    def update(self, event: IntelligenceEvent) -> None:
        key = (event.symbol, event.tf)
        self._cache[key] = (event, time.monotonic())

    def seed_from_db_row(self, row: dict) -> None:
        """Seed cache from a raw intelligence_features DB row (asyncpg dict).

        Constructs a SimpleNamespace proxy — satisfies getattr() access pattern
        in build() without requiring a full IntelligenceEvent deserialization.
        asyncpg returns JSONB columns as Python dicts; SimpleNamespace unpacks them.
        """
        def _ns(d: dict | None) -> types.SimpleNamespace:
            if isinstance(d, dict):
                return types.SimpleNamespace(**d)
            return types.SimpleNamespace()

        symbol = row["symbol"]
        tf = row["tf"]
        proxy = types.SimpleNamespace(
            symbol=symbol,
            tf=tf,
            ts=row["ts"],
            bar=_ns(row.get("bar")),
            i1=_ns(row.get("i1")),
            i4=_ns(row.get("i4")),
            i6=_ns(row.get("i6")),
        )
        self._cache[(symbol, tf)] = (proxy, time.monotonic())

    def build(
        self,
        symbol: str,
        tf: str,
        signal: RankedSignal,
        signal_id: UUID,
    ) -> SwarmContext | None:
        key = (symbol, tf)
        entry = self._cache.get(key)
        if entry is None:
            logger.warning("swarm_context.no_cache", symbol=symbol, tf=tf)
            return None

        event, cached_at = entry
        age = time.monotonic() - cached_at
        if age > _TTL_SECONDS:
            logger.warning("swarm_context.stale", symbol=symbol, tf=tf, age_s=round(age, 1))
            return None

        def _safe(obj: Any, attr: str) -> Any:
            return getattr(obj, attr, None)

        return SwarmContext(
            signal_id=signal_id,
            symbol=symbol,
            timeframe=tf,
            ts=event.ts,
            atr=_safe(event.i1, "atr_14"),
            adx=_safe(event.i1, "adx"),
            rsi=_safe(event.i1, "rsi_14"),
            hmm_regime=_safe(event.i4, "hmm_regime"),
            trend_regime=_safe(event.i4, "trend_regime"),
            vol_regime=_safe(event.i4, "vol_regime"),
            vol_percentile=_safe(event.i4, "vol_percentile"),
            garch_vol_ratio=_safe(event.i4, "garch_vol_ratio"),
            garch_vol_regime=_safe(event.i4, "garch_vol_regime"),
            kalman_trend=_safe(event.i4, "kalman_trend"),
            kalman_slope=_safe(event.i4, "kalman_slope"),
            vwap=_safe(event.i4, "vwap"),
            poc_price=_safe(event.i4, "poc_price"),
            poc_price_rolling=_safe(event.i4, "poc_price_rolling"),
            ctf_score=_safe(event.i6, "ctf_score"),
            ctf_trend_alignment=_safe(event.i6, "ctf_trend_alignment"),
            ctf_structure_alignment=_safe(event.i6, "ctf_structure_alignment"),
            ctf_regime_agreement=_safe(event.i6, "ctf_regime_agreement"),
            ctf_timeframes_aligned=_safe(event.i6, "ctf_timeframes_aligned"),
            ctf_fvg_alignment=_safe(event.i6, "ctf_fvg_alignment"),
            ctf_ob_alignment=_safe(event.i6, "ctf_ob_alignment"),
            winner_plugin=getattr(signal, "plugin", None),
            winner_direction=getattr(signal, "direction", None),
            winner_confidence=getattr(signal, "calibrated_confidence", None),
            price=_safe(event.bar, "close"),
            volume=_safe(event.bar, "volume"),
        )
