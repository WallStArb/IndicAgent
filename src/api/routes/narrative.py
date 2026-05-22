"""On-demand narrative generation API route.

Phase 78 D-29/D-30: narrative moved from Kafka consumer to on-demand endpoint.
Narrative text is consumed at click-time, not per-bar. Moving off the hot path
eliminates LLM token contention with the alpha swarm.

Renaissance design:
  - DB-first: check signal_narratives before calling LLM (idempotent, zero repeat cost)
  - Persist every generation: every narrative is a labeled training sample
  - LLM audit: every call flows through LLMProviderChain audit trail
  - Typed AIContext: schemas.py models, no dict[str, Any] escape hatch (D-15)
"""

import hashlib
import json
import time
from functools import lru_cache
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel

from ...config.settings import Settings
from ...core.ai.context import AIContext, BarContext, QuantSignalContext
from ...core.ai.context import Tier as _Tier
from ...core.database_manager import DatabaseManager
from ...core.llm.chain import LLMProviderChain
from ...intelligence.ai.narrative.narrative_agent import NarrativeComputeAgent
from ...intelligence.schemas import (
    I1Indicators,
    I2Events,
    I3Structure,
    I4Context,
    I5Patterns,
    I6Confluence,
    SMCContext,
)
from ..dependencies import get_db_manager
from ..utils import parse_jsonb as _parse_jsonb

logger = structlog.get_logger(__name__)

router = APIRouter()

# Tier values used by _prompt_hash (excludes non-pipeline Tier members)
_HASH_TIERS = tuple(t.value for t in _Tier if t.value not in ("bar", "i7"))


class NarrativeResponse(BaseModel):
    signal_id: str
    narrative: str
    model: str
    cached: bool = False


@lru_cache(maxsize=1)
def _get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def _get_llm_chain() -> LLMProviderChain:
    settings = _get_settings()
    return LLMProviderChain(
        call_type="narrative",
        settings=settings,
        cache_ttl=0,  # no semantic cache — every generation is audited
    )


def _maybe_validate(model_cls, payload):
    """Validate JSONB payload into typed schema, or return None for empty/missing."""
    if payload is None or payload == {} or payload == "":
        return None
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return None
    if not isinstance(payload, dict) or not payload:
        return None
    return model_cls.model_validate(payload)


def _build_context_from_row(row) -> AIContext:
    """Construct typed AIContext from joined signal_ledger + intelligence_features row."""
    bar_data = _parse_jsonb(row.get("bar"), default={})
    bar_ctx = None
    if bar_data:
        bar_ctx = BarContext(
            open=bar_data.get("o") or bar_data.get("open"),
            high=bar_data.get("h") or bar_data.get("high"),
            low=bar_data.get("l") or bar_data.get("low"),
            close=bar_data.get("c") or bar_data.get("close"),
            volume=bar_data.get("v") or bar_data.get("volume"),
        )

    targets = row.get("targets") or []
    i7_ctx = QuantSignalContext(
        winner_plugin=row.get("setup_plugin"),
        winner_direction=row.get("direction"),
        winner_confidence=row.get("confidence"),
        entry_price=row.get("entry_price"),
        stop_price=row.get("stop_loss"),
        target_prices=targets or None,
        entry_type=row.get("entry_type"),
    )

    return AIContext(
        signal_id=row["signal_id"],
        symbol=row["symbol"],
        timeframe=row["feature_tf"],
        ts=row["timestamp"],
        bar=bar_ctx,
        i1=_maybe_validate(
            I1Indicators, _parse_jsonb(row.get("technical_indicators"), default=None)
        ),
        i2=_maybe_validate(I2Events, _parse_jsonb(row.get("market_context"), default=None)),
        i3=_maybe_validate(I3Structure, _parse_jsonb(row.get("pattern_detections"), default=None)),
        i4=_maybe_validate(I4Context, _parse_jsonb(row.get("regime_features"), default=None)),
        i5=_maybe_validate(I5Patterns, _parse_jsonb(row.get("confluence_scores"), default=None)),
        i6=_maybe_validate(
            I6Confluence, _parse_jsonb(row.get("cross_timeframe_context"), default=None)
        ),
        smc=_maybe_validate(SMCContext, _parse_jsonb(row.get("smc"), default=None)),
        i7=i7_ctx,
    )


def _prompt_hash(context: AIContext) -> str:
    """Deterministic hash of AIContext for cache invalidation detection."""
    h = hashlib.sha256()
    h.update(f"{context.symbol}|{context.timeframe}".encode())
    for tier in _HASH_TIERS:
        val = getattr(context, tier, None)
        if val is not None:
            h.update(str(val.model_dump(sorted_keys=True)).encode())
    return h.hexdigest()[:16]


_SIGNAL_QUERY = """
    SELECT sl.signal_id, sl.symbol, sl.timestamp, sl.feature_tf,
           sl.setup_plugin, sl.direction, sl.confidence,
           tf_sig.value->>'entry_price' AS entry_price,
           tf_sig.value->>'stop_loss' AS stop_loss,
           tf_sig.value->'targets' AS targets,
           tf_sig.value->>'regime_type_at_fire' AS regime_type_at_fire,
           tf_sig.value->>'entry_type' AS entry_type,
           f.bar, f.technical_indicators, f.market_context, f.pattern_detections,
           f.regime_features, f.confluence_scores, f.smc, f.cross_timeframe_context
    FROM signal_ledger sl
    LEFT JOIN intelligence_features f
      ON sl.symbol = f.symbol
     AND sl.feature_ts = f.ts
     AND sl.feature_tf = f.tf
    LEFT JOIN LATERAL jsonb_array_elements(f.trading_signals) AS tf_sig(value)
        ON tf_sig.value->>'signal_id' = sl.signal_id::text
    WHERE sl.signal_id = $1::uuid
    LIMIT 1
"""

_NARRATIVE_UPSERT = """
    INSERT INTO signal_narratives (signal_id, symbol, timeframe, narrative, model,
                                   agent_id, prompt_version, prompt_hash, latency_ms)
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
    ON CONFLICT (signal_id) DO NOTHING
    RETURNING narrative, model
"""


@router.get("/signals/{signal_id}/narrative", response_model=NarrativeResponse)
async def get_narrative(
    signal_id: UUID = Path(..., description="Signal UUID"),
    db: DatabaseManager = Depends(get_db_manager),
) -> NarrativeResponse:
    """Generate or retrieve cached narrative for a signal.

    Idempotent: same signal_id always returns the same narrative.
    On first request, calls LLM and persists. On repeat, returns from DB.
    """
    try:
        async with db.pool.acquire() as conn:
            # 1. Check for existing cached narrative
            cached = await conn.fetchrow(
                "SELECT narrative, model FROM signal_narratives WHERE signal_id = $1",
                signal_id,
            )
            if cached is not None:
                return NarrativeResponse(
                    signal_id=str(signal_id),
                    narrative=cached["narrative"],
                    model=cached["model"],
                    cached=True,
                )

            # 2. Look up signal + features
            row = await conn.fetchrow(_SIGNAL_QUERY, signal_id)
            if row is None:
                raise HTTPException(status_code=404, detail="Signal not found")

            context = _build_context_from_row(row)

            # 3. Generate narrative
            agent = NarrativeComputeAgent(llm_chain=_get_llm_chain())
            t0 = time.monotonic()
            output = await agent.compute(context)
            latency_ms = (time.monotonic() - t0) * 1000

            if output.error or not output.payload.get("text"):
                detail = f"Narrative generation failed: {output.error or 'empty narrative'}"
                raise HTTPException(status_code=502, detail=detail)

            narrative_text = output.payload["text"]
            model_name = output.payload.get("model", "")

            # 4. Persist (idempotent upsert)
            phash = _prompt_hash(context)
            prompt_version = output.payload.get("prompt_version", "")
            await conn.execute(
                _NARRATIVE_UPSERT,
                signal_id,
                row["symbol"],
                row["feature_tf"],
                narrative_text,
                model_name,
                output.agent_id,
                prompt_version,
                phash,
                round(latency_ms, 1),
            )

            return NarrativeResponse(
                signal_id=str(signal_id),
                narrative=narrative_text,
                model=model_name,
                cached=False,
            )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("narrative.route.error", signal_id=str(signal_id), exc_info=exc)
        raise HTTPException(status_code=500, detail="Database error") from exc
