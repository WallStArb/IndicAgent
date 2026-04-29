"""AIContext — typed market context for AI agent computation."""

from __future__ import annotations

import time
import types
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

import structlog
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from src.intelligence.schemas import IntelligenceEvent, RankedSignal

logger = structlog.get_logger(__name__)

_TTL_SECONDS = 300  # 5 minutes


class Tier(str, Enum):
    """Intelligence tier identifiers.

    Extends str for DB compatibility (per CLAUDE.md convention).
    """
    BAR = "bar"
    I1 = "i1"
    I2 = "i2"
    I3 = "i3"
    I4 = "i4"
    I5 = "i5"
    I6 = "i6"
    I7 = "i7"


class TierContext(BaseModel):
    """Base model for tier-specific context (placeholder for future)."""
    model_config = ConfigDict(frozen=True)


class I1Context(TierContext):
    """I1 indicator context."""
    atr: float | None = None
    adx: float | None = None
    rsi: float | None = None


class I4Context(TierContext):
    """I4 context classification."""
    hmm_regime: int | None = None
    trend_regime: float | None = None
    vol_regime: float | None = None
    vol_percentile: float | None = None
    garch_vol_ratio: float | None = None
    garch_vol_regime: int | None = None
    kalman_trend: float | None = None
    kalman_slope: float | None = None
    vwap: float | None = None
    poc_price: float | None = None
    poc_price_rolling: float | None = None


class I6Context(TierContext):
    """I6 cross-timeframe confluence."""
    ctf_score: float | None = None
    ctf_trend_alignment: float | None = None
    ctf_structure_alignment: float | None = None
    ctf_regime_agreement: float | None = None
    ctf_timeframes_aligned: float | None = None
    ctf_fvg_alignment: float | None = None
    ctf_ob_alignment: float | None = None


class I7Context(TierContext):
    """I7 signal context."""
    winner_plugin: str | None = None
    winner_direction: int | None = None
    winner_confidence: float | None = None


class BarContext(TierContext):
    """Bar OHLCV context."""
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None


class AIContext(BaseModel):
    """Typed context for AI agent computation. Immutable after construction.

    Generalized from SwarmContext with tier-specific sub-contexts.
    Self-referential lead_context enabled via model_rebuild().
    """
    model_config = ConfigDict(frozen=True)

    signal_id: Any | None = None  # UUID or None
    symbol: str
    timeframe: str
    ts: Any  # datetime
    trigger: str = "signal"  # "signal" or "bar"

    # Tier contexts (populated conditionally based on tiers_needed)
    bar: BarContext | None = None
    i1: I1Context | None = None
    i4: I4Context | None = None
    i6: I6Context | None = None
    i7: I7Context | None = None
    # i2, i3, i5 placeholders for future (deferred per CONTEXT.md)

    # Enrichment fields (set by context builder)
    lead_context: AIContext | None = None
    volume_profile: dict[str, Any] | None = None


# Enable self-referential lead_context field
AIContext.model_rebuild()


class AIContextCache:
    """asyncio-safe in-memory context cache (NOT thread-safe).

    Bar loop calls update() after each IntelligenceEvent.
    Agent callers call build() to construct an AIContext.
    Provides get_lead() for D-10 fix (replaces private _cache access).
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], tuple[Any, float]] = {}

    def update(self, event: IntelligenceEvent) -> None:
        """Update cache with latest IntelligenceEvent."""
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
            i7=_ns(row.get("i7")),
        )
        self._cache[(symbol, tf)] = (proxy, time.monotonic())

    def build(
        self,
        symbol: str,
        tf: str,
        tiers_needed: frozenset[Tier],
        signal: Any | None = None,
        signal_id: Any | None = None,
    ) -> AIContext | None:
        """Build AIContext from cached event, populating only requested tiers.

        Args:
            symbol: Instrument symbol
            tf: Timeframe
            tiers_needed: Frozenset of Tier enums to populate
            signal: Optional RankedSignal for i7 context
            signal_id: Optional signal UUID

        Returns:
            AIContext if cache hit and not stale, None otherwise
        """
        key = (symbol, tf)
        entry = self._cache.get(key)
        if entry is None:
            logger.warning("ai_context.no_cache", symbol=symbol, tf=tf)
            return None

        event, cached_at = entry
        age = time.monotonic() - cached_at
        if age > _TTL_SECONDS:
            logger.warning("ai_context.stale", symbol=symbol, tf=tf, age_s=round(age, 1))
            return None

        def _safe(obj: Any, attr: str) -> Any:
            return getattr(obj, attr, None)

        # Build tier contexts conditionally based on tiers_needed
        bar_ctx = BarContext(
            open=_safe(event.bar, "open"),
            high=_safe(event.bar, "high"),
            low=_safe(event.bar, "low"),
            close=_safe(event.bar, "close"),
            volume=_safe(event.bar, "volume"),
        ) if Tier.BAR in tiers_needed else None

        i1_ctx = I1Context(
            atr=_safe(event.i1, "atr_14"),
            adx=_safe(event.i1, "adx"),
            rsi=_safe(event.i1, "rsi_14"),
        ) if Tier.I1 in tiers_needed else None

        i4_ctx = I4Context(
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
        ) if Tier.I4 in tiers_needed else None

        i6_ctx = I6Context(
            ctf_score=_safe(event.i6, "ctf_score"),
            ctf_trend_alignment=_safe(event.i6, "ctf_trend_alignment"),
            ctf_structure_alignment=_safe(event.i6, "ctf_structure_alignment"),
            ctf_regime_agreement=_safe(event.i6, "ctf_regime_agreement"),
            ctf_timeframes_aligned=_safe(event.i6, "ctf_timeframes_aligned"),
            ctf_fvg_alignment=_safe(event.i6, "ctf_fvg_alignment"),
            ctf_ob_alignment=_safe(event.i6, "ctf_ob_alignment"),
        ) if Tier.I6 in tiers_needed else None

        i7_ctx = None
        if Tier.I7 in tiers_needed and signal is not None:
            i7_ctx = I7Context(
                winner_plugin=getattr(signal, "plugin", None),
                winner_direction=getattr(signal, "direction", None),
                winner_confidence=getattr(signal, "calibrated_confidence", None),
            )

        return AIContext(
            signal_id=signal_id,
            symbol=symbol,
            timeframe=tf,
            ts=event.ts,
            trigger="signal",
            bar=bar_ctx,
            i1=i1_ctx,
            i4=i4_ctx,
            i6=i6_ctx,
            i7=i7_ctx,
        )

    def get_lead(
        self,
        symbol: str,
        tf: str,
        lead_map: dict[str, str],
    ) -> AIContext | None:
        """Look up lead index context without exposing _cache internals.

        Replaces private self._context_cache._cache access in _find_lead_context.
        D-10 fix: encapsulates prefix-search logic in public method.

        Args:
            symbol: Current symbol (e.g., "ESM6")
            tf: Timeframe
            lead_map: Mapping from base symbol to lead base symbol (e.g., {"ES": "ZN"})

        Returns:
            AIContext for lead instrument if found and not stale, None otherwise
        """
        # Extract base symbol (e.g., "ES" from "ESM6")
        def _extract_base(sym: str) -> str:
            """Extract base symbol from futures contract."""
            # Remove trailing month/year codes (e.g., "M6", "U6")
            import re
            match = re.match(r"^([A-Z]+)", sym)
            return match.group(1) if match else sym

        base = _extract_base(symbol)
        lead_base = lead_map.get(base)
        if not lead_base or lead_base == base:
            return None

        # Search cache for lead symbol entries
        for (s, t), entry in self._cache.items():
            if s.startswith(lead_base) and t == tf:
                event, _ = entry
                # Build AIContext with I1/I4/I6 tiers (standard lead context)
                return self.build(s, t, frozenset({Tier.I1, Tier.I4, Tier.I6}))

        return None
