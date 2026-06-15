"""SignalContext — typed market context for AI agent computation."""

from __future__ import annotations

import re as _re
import time
import types
from enum import Enum
from typing import TYPE_CHECKING, Any

import structlog
from pydantic import BaseModel, ConfigDict

from src.core.service_utils import TF_SECONDS
from src.intelligence.schemas import (
    I1Indicators,
    I2Events,
    I3Structure,
    I4Context,
    I5Patterns,
    I6Confluence,
    SMCContext,
)
from src.observability.metrics import AI_CONTEXT_CACHE_HITS_TOTAL, AI_CONTEXT_CACHE_MISSES_TOTAL

if TYPE_CHECKING:
    from src.intelligence.schemas import IntelligenceEvent

logger = structlog.get_logger(__name__)

# TTL is 2× the bar interval so the cache stays valid across one full bar period
# even with asyncio scheduling jitter between bar_loop and trigger_loop.
# Falls back to 10 minutes for unknown timeframes.
_DEFAULT_TTL_SECONDS = 600


def _ttl_for_tf(tf: str) -> float:
    return TF_SECONDS.get(tf, _DEFAULT_TTL_SECONDS) * 2


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
    SMC = "smc"


class TierContext(BaseModel):
    """Base model for tier-specific context (custom types not in schemas.py)."""

    model_config = ConfigDict(frozen=True)


class QuantSignalContext(TierContext):
    """Quantitative signal parameters — the specific trade setup from the aggregator.

    Populated from the signal dict produced by the aggregator. Fields here
    are signal-level properties NOT available in pipeline tiers (I1-I6, SMC).
    """

    winner_plugin: str | None = None
    winner_direction: int | None = None
    winner_confidence: float | None = None
    entry_price: float | None = None
    stop_price: float | None = None
    target_prices: list[float] | None = None
    entry_type: str | None = None
    stop_type: str | None = None
    target_types: list[str] | None = None
    risk_reward_ratio: float | None = None
    confluence_score: float | None = None
    regime_eligible: bool | None = None
    quality_score: float | None = None
    adjusted_rank: float | None = None
    co_fire_count: int | None = None
    co_fire_partners: list[str] | None = None
    zone_low: float | None = None
    zone_high: float | None = None


class BarContext(TierContext):
    """Bar OHLCV context — custom shape for AI agent consumption."""

    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: float | None = None


class SignalContext(BaseModel):
    """Typed context for AI agent computation. Immutable after construction.

    Pipeline tiers (i1-i6, smc) use schemas.py types directly (D-09).
    No sparse subclasses, no untyped dict escape hatch (D-10, D-15).
    Self-referential lead_context enabled via model_rebuild().
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=False)

    signal_id: Any | None = None  # UUID or None
    symbol: str
    timeframe: str
    ts: Any  # datetime
    trigger: str = "signal"  # "signal" or "bar"

    # Custom contract types — not pipeline tier outputs
    bar: BarContext | None = None
    i7: QuantSignalContext | None = None

    # Pipeline tier types — schemas.py is the SINGLE source of truth (D-09).
    # Direct assignment from IntelligenceEvent fields; no field-by-field copy (D-13).
    i1: I1Indicators | None = None
    i2: I2Events | None = None
    i3: I3Structure | None = None
    i4: I4Context | None = None
    i5: I5Patterns | None = None
    i6: I6Confluence | None = None
    smc: SMCContext | None = None  # SMC tier; hmm_regime lives here, NOT on i4

    # Enrichment fields
    lead_context: SignalContext | None = None


# Enable self-referential lead_context field
SignalContext.model_rebuild()


# ---------------------------------------------------------------------------
# Shared context rendering — used by all prompt builders (skeptic, narrative)
# ---------------------------------------------------------------------------

_CONTEXT_NON_TIER_FIELDS: frozenset[str] = frozenset(
    {
        "signal_id",
        "symbol",
        "timeframe",
        "ts",
        "trigger",
        "bar",
        "i7",
        "lead_context",
    }
)


_TIER_SECTION_LABELS: dict[str, str] = {
    "i1": "Quantitative Indicators (i1)",
    "i2": "Composite Events (i2)",
    "i3": "Market Structure (i3)",
    "i4": "Context & Regime (i4)",
    "i5": "Pattern Recognition (i5)",
    "i6": "Cross-Timeframe Confluence (i6)",
    "smc": "Smart Money Concepts (smc)",
}
"""Semantic labels for pipeline tiers — tells the LLM what kind of data it's reasoning about.

Unknown tiers (future: qualitative, fundamental) fall through to raw field name.
This map is the single place to add labels for new intelligence categories.
"""


def render_full_context(ctx: SignalContext) -> str:
    """Render populated pipeline tier fields as deterministic LLM-friendly text.

    Open-ended: iterates ctx.model_fields, NOT a hardcoded tier list.
    Any new tier added to SignalContext automatically appears with zero prompt changes.
    Null fields are omitted — only populated values reach the prompt.
    Section headers use semantic labels from _TIER_SECTION_LABELS.
    """
    lines: list[str] = []
    for field_name in sorted(ctx.__class__.model_fields):
        if field_name in _CONTEXT_NON_TIER_FIELDS:
            continue
        value = getattr(ctx, field_name, None)
        if value is None:
            continue
        if not isinstance(value, BaseModel):
            continue
        tier_dict = value.model_dump(exclude_none=True)
        if not tier_dict:
            continue
        tier_lines: list[str] = []
        for k, v in sorted(tier_dict.items()):
            if isinstance(v, float):
                tier_lines.append(f"- {k}: {v:.6g}")
            else:
                tier_lines.append(f"- {k}: {v}")
        if tier_lines:
            label = _TIER_SECTION_LABELS.get(field_name, field_name)
            lines.append(f"## {label}")
            lines.extend(tier_lines)
    return "\n".join(lines) if lines else "(no features available)"


class SignalContextCache:
    """asyncio-safe in-memory context cache (NOT thread-safe).

    Bar loop calls update() after each IntelligenceEvent.
    Agent callers call build() to construct an SignalContext.
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

        Uses model_validate with mode='python'. Column→schema mapping may drift
        as the pipeline evolves; unknown fields are silently dropped (extra='ignore'
        override) rather than crashing the AI layer startup.
        """
        symbol = row["symbol"]
        tf = row["tf"]

        def _safe(cls, data: dict):
            try:
                return cls.model_validate(data)
            except Exception:
                return (
                    cls.model_validate(data, context={"extra": "ignore"})
                    if False
                    else cls.model_validate(
                        {k: v for k, v in data.items() if k in cls.model_fields}
                    )
                )

        # Build typed proxy — DB-seeded paths only access event.iN attributes
        proxy = types.SimpleNamespace(
            symbol=symbol,
            tf=tf,
            ts=row["ts"],
            bar=types.SimpleNamespace(**(row.get("bar") or {})),
            i1=I1Indicators.model_validate(row.get("technical_indicators") or {}),
            i2=I2Events.model_validate(row.get("market_context") or {}),
            i3=_safe(I3Structure, row.get("confluence_scores") or {}),
            i4=_safe(I4Context, row.get("regime_features") or {}),
            i5=_safe(I5Patterns, row.get("pattern_detections") or {}),
            i6=_safe(I6Confluence, row.get("cross_timeframe_context") or {}),
            i7=None,  # trading_signals JSONB array, not unpacked here
            smc=_safe(SMCContext, row.get("smc") or {}),
        )
        self._cache[(symbol, tf)] = (proxy, time.monotonic())

    def build(
        self,
        symbol: str,
        tf: str,
        tiers_needed: frozenset[Tier],
        signal: Any | None = None,
        signal_id: Any | None = None,
        group_id: str = "",
    ) -> SignalContext | None:
        """Build SignalContext from cached event, populating only requested tiers.

        D-13: Direct pass-through — event.iN is assigned to ctx.iN with no copy.
        None-safe: Pydantic accepts None for Optional fields.

        Args:
            symbol: Instrument symbol
            tf: Timeframe
            tiers_needed: Frozenset of Tier enums to populate
            signal: Optional signal dict for i7 context
            signal_id: Optional signal UUID
            group_id: Optional group_id for cache hit/miss metrics

        Returns:
            SignalContext if cache hit and not stale, None otherwise
        """
        key = (symbol, tf)
        entry = self._cache.get(key)
        if entry is None:
            AI_CONTEXT_CACHE_MISSES_TOTAL.add(1, {"group_id": group_id})
            logger.warning("ai_context.no_cache", symbol=symbol, tf=tf)
            return None

        event, cached_at = entry
        age = time.monotonic() - cached_at
        if age > _ttl_for_tf(tf):
            AI_CONTEXT_CACHE_MISSES_TOTAL.add(1, {"group_id": group_id})
            logger.warning(
                "ai_context.stale", symbol=symbol, tf=tf, age_s=round(age, 1), ttl_s=_ttl_for_tf(tf)
            )
            return None

        AI_CONTEXT_CACHE_HITS_TOTAL.add(1, {"group_id": group_id})

        # Bar context — custom BarContext type (not in schemas.py)
        bar_ctx = None
        if Tier.BAR in tiers_needed and getattr(event, "bar", None) is not None:
            bar_ctx = BarContext(
                open=getattr(event.bar, "o", None) or getattr(event.bar, "open", None),
                high=getattr(event.bar, "h", None) or getattr(event.bar, "high", None),
                low=getattr(event.bar, "l", None) or getattr(event.bar, "low", None),
                close=getattr(event.bar, "c", None) or getattr(event.bar, "close", None),
                volume=getattr(event.bar, "v", None) or getattr(event.bar, "volume", None),
            )

        # I7 context — QuantSignalContext (signal-specific, not pipeline output)
        i7_ctx = None
        if Tier.I7 in tiers_needed and signal is not None:
            s = (
                signal
                if isinstance(signal, dict)
                else {
                    k: getattr(signal, k, None)
                    for k in (
                        "plugin",
                        "setup_plugin",
                        "direction",
                        "calibrated_confidence",
                        "confidence",
                        "entry_price",
                        "stop_loss",
                        "targets",
                        "entry_type",
                        "stop_type",
                        "target_types",
                        "risk_reward_ratio",
                        "confluence_score",
                        "regime_eligible",
                        "quality_score",
                        "pre_quality_confidence",
                        "adjusted_rank",
                        "co_fire_count",
                        "co_fire_partners",
                        "zone_low",
                        "zone_high",
                    )
                }
            )
            i7_ctx = QuantSignalContext(
                winner_plugin=s.get("plugin") or s.get("setup_plugin"),
                winner_direction=s.get("direction"),
                winner_confidence=s.get("calibrated_confidence") or s.get("confidence"),
                entry_price=s.get("entry_price"),
                stop_price=s.get("stop_loss"),
                target_prices=s.get("targets"),
                entry_type=s.get("entry_type"),
                stop_type=s.get("stop_type"),
                target_types=s.get("target_types"),
                risk_reward_ratio=s.get("risk_reward_ratio"),
                confluence_score=s.get("confluence_score"),
                regime_eligible=s.get("regime_eligible"),
                quality_score=s.get("quality_score") or s.get("pre_quality_confidence"),
                adjusted_rank=s.get("adjusted_rank"),
                co_fire_count=s.get("co_fire_count"),
                co_fire_partners=s.get("co_fire_partners"),
                zone_low=s.get("zone_low"),
                zone_high=s.get("zone_high"),
            )

        # Pipeline tiers — direct pass-through (D-13). None-safe by Pydantic.
        return SignalContext(
            signal_id=signal_id,
            symbol=symbol,
            timeframe=tf,
            ts=event.ts,
            trigger="signal",
            bar=bar_ctx,
            i1=getattr(event, "i1", None) if Tier.I1 in tiers_needed else None,
            i2=getattr(event, "i2", None) if Tier.I2 in tiers_needed else None,
            i3=getattr(event, "i3", None) if Tier.I3 in tiers_needed else None,
            i4=getattr(event, "i4", None) if Tier.I4 in tiers_needed else None,
            i5=getattr(event, "i5", None) if Tier.I5 in tiers_needed else None,
            i6=getattr(event, "i6", None) if Tier.I6 in tiers_needed else None,
            smc=getattr(event, "smc", None) if Tier.SMC in tiers_needed else None,
            i7=i7_ctx,
        )

    def get_lead(
        self,
        symbol: str,
        tf: str,
        lead_map: dict[str, str],
    ) -> SignalContext | None:
        """Look up lead index context without exposing _cache internals.

        Replaces private self._context_cache._cache access in _find_lead_context.
        D-10 fix: encapsulates prefix-search logic in public method.

        Args:
            symbol: Current symbol (e.g., "ESM6")
            tf: Timeframe
            lead_map: Mapping from base symbol to lead base symbol (e.g., {"ES": "ZN"})

        Returns:
            SignalContext for lead instrument if found and not stale, None otherwise
        """

        def _extract_base(sym: str) -> str:
            """Extract base symbol from futures contract."""
            match = _re.match(r"^([A-Z]+)", sym)
            return match.group(1) if match else sym

        base = _extract_base(symbol)
        lead_base = lead_map.get(base)
        if not lead_base or lead_base == base:
            return None

        # Search cache for lead symbol entries
        for (s, t), _entry in self._cache.items():
            if s.startswith(lead_base) and t == tf:
                # Build SignalContext with I1/I4/I6 tiers (standard lead context)
                return self.build(s, t, frozenset({Tier.I1, Tier.I4, Tier.I6}))

        return None
