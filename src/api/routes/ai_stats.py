"""AI observability and per-signal swarm breakdown routes."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Path

from ...core.database_manager import DatabaseManager
from ..dependencies import get_db_manager
from ..utils import translate_db_errors

router = APIRouter()

_AGENT_DISPLAY = {
    "skeptic": "Skeptic",
    "correlation_v1": "Correlation",
    "regime_coherence_v1": "Regime Coherence",
    "counterfactual_v1": "Counterfactual",
    "narrative_v1": "Narrative",
    "ml_scorer_v1": "ML Scorer",
}


@router.get("/ai/stats")
@translate_db_errors
async def get_ai_stats(
    db: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """Aggregate AI observability stats for the last 24 hours.

    Returns per-agent call counts, avg latency, token burn, parse success rate,
    provider breakdown, and the 20 most recent narrative calls.
    """
    async with db.pool.acquire() as conn:
        agent_rows = await conn.fetch(
            """
            SELECT
                agent_id,
                model,
                provider,
                COUNT(*)                                            AS calls,
                AVG(latency_ms)::int                               AS avg_ms,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)::int AS p95_ms,
                SUM(tokens_est)                                    AS tokens,
                SUM(CASE WHEN succeeded THEN 1 ELSE 0 END)        AS succeeded,
                SUM(CASE WHEN parse_success THEN 1 ELSE 0 END)    AS parsed
            FROM llm_calls
            WHERE called_at > NOW() - INTERVAL '24 hours'
              AND agent_id IS NOT NULL
            GROUP BY agent_id, model, provider
            ORDER BY calls DESC
            """,
        )

        provider_rows = await conn.fetch(
            """
            SELECT
                provider,
                COUNT(*)         AS calls,
                SUM(tokens_est)  AS tokens,
                AVG(latency_ms)::int AS avg_ms
            FROM llm_calls
            WHERE called_at > NOW() - INTERVAL '24 hours'
            GROUP BY provider
            ORDER BY calls DESC
            """,
        )

        narrative_rows = await conn.fetch(
            """
            SELECT
                lc.signal_id,
                lc.symbol,
                lc.timeframe,
                lc.model,
                lc.provider,
                lc.latency_ms,
                lc.tokens_est,
                lc.succeeded,
                lc.called_at,
                lc.response
            FROM llm_calls lc
            WHERE lc.agent_id = 'narrative_v1'
              AND lc.called_at > NOW() - INTERVAL '24 hours'
            ORDER BY lc.called_at DESC
            LIMIT 20
            """,
        )

        total_row = await conn.fetchrow(
            """
            SELECT
                COUNT(*)        AS total_calls,
                SUM(tokens_est) AS total_tokens,
                SUM(CASE WHEN succeeded THEN 1 ELSE 0 END) AS total_succeeded
            FROM llm_calls
            WHERE called_at > NOW() - INTERVAL '24 hours'
            """,
        )

    agents = []
    for r in agent_rows:
        calls = r["calls"] or 0
        agents.append(
            {
                "agent_id": r["agent_id"],
                "display_name": _AGENT_DISPLAY.get(r["agent_id"], r["agent_id"]),
                "model": r["model"],
                "provider": r["provider"],
                "calls_24h": calls,
                "avg_latency_ms": r["avg_ms"],
                "p95_latency_ms": r["p95_ms"],
                "tokens_24h": r["tokens"] or 0,
                "parse_rate": round(r["parsed"] / calls, 3) if calls else None,
                "success_rate": round(r["succeeded"] / calls, 3) if calls else None,
            }
        )

    narratives = []
    for r in narrative_rows:
        # Truncate response text to 300 chars for the feed preview
        text = (r["response"] or "")[:300]
        narratives.append(
            {
                "signal_id": str(r["signal_id"]) if r["signal_id"] else None,
                "symbol": r["symbol"],
                "timeframe": r["timeframe"],
                "model": r["model"],
                "provider": r["provider"],
                "latency_ms": r["latency_ms"],
                "tokens": r["tokens_est"],
                "succeeded": r["succeeded"],
                "called_at": r["called_at"].isoformat() if r["called_at"] else None,
                "text_preview": text,
            }
        )

    return {
        "agents": agents,
        "providers": [
            {
                "provider": r["provider"],
                "calls_24h": r["calls"],
                "tokens_24h": r["tokens"] or 0,
                "avg_latency_ms": r["avg_ms"],
            }
            for r in provider_rows
        ],
        "narratives": narratives,
        "totals": {
            "calls_24h": total_row["total_calls"] or 0,
            "tokens_24h": total_row["total_tokens"] or 0,
            "success_rate": (
                round(total_row["total_succeeded"] / total_row["total_calls"], 3)
                if total_row["total_calls"]
                else None
            ),
        },
    }


@router.get("/signals/{signal_id}/ai")
@translate_db_errors
async def get_signal_ai(
    signal_id: UUID = Path(..., description="Signal UUID"),
    db: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """Per-signal swarm agent breakdown.

    Returns each swarm agent's multiplier + confidence from signal_lineage,
    plus the aggregate swarm_multiplier from signal_ai_enrichment.
    """
    async with db.pool.acquire() as conn:
        lineage_rows = await conn.fetch(
            """
            SELECT source, multiplier, metadata, ts
            FROM signal_lineage
            WHERE signal_id = $1::uuid
              AND event_type = 'agent_prediction'
            ORDER BY ts ASC
            """,
            signal_id,
        )

        enrichment = await conn.fetchrow(
            """
            SELECT swarm_multiplier, adjusted_confidence, swarm_agent_count, ml_score
            FROM signal_ai_enrichment
            WHERE signal_id = $1::uuid
            """,
            signal_id,
        )

        narrative_row = await conn.fetchrow(
            """
            SELECT lc.response, lc.model, lc.latency_ms, lc.called_at
            FROM llm_calls lc
            WHERE lc.signal_id = $1::uuid
              AND lc.agent_id = 'narrative_v1'
            ORDER BY lc.called_at DESC
            LIMIT 1
            """,
            signal_id,
        )

    agents = []
    for r in lineage_rows:
        meta = r["metadata"] or {}
        payload = meta.get("payload", {}) if isinstance(meta, dict) else {}
        agents.append(
            {
                "agent_id": r["source"],
                "display_name": _AGENT_DISPLAY.get(r["source"], r["source"]),
                "multiplier": r["multiplier"],
                "confidence": meta.get("confidence") if isinstance(meta, dict) else None,
                "shadow_at_write": (
                    meta.get("shadow_at_write") if isinstance(meta, dict) else None
                ),
                "error": meta.get("error") if isinstance(meta, dict) else None,
                "reasoning": payload.get("reasoning") if isinstance(payload, dict) else None,
            }
        )

    return {
        "signal_id": str(signal_id),
        "agents": agents,
        "swarm": {
            "multiplier": enrichment["swarm_multiplier"] if enrichment else None,
            "adjusted_confidence": enrichment["adjusted_confidence"] if enrichment else None,
            "agent_count": enrichment["swarm_agent_count"] if enrichment else None,
            "ml_score": enrichment["ml_score"] if enrichment else None,
        },
        "narrative": {
            "text": narrative_row["response"] if narrative_row else None,
            "model": narrative_row["model"] if narrative_row else None,
            "latency_ms": narrative_row["latency_ms"] if narrative_row else None,
            "generated_at": (
                narrative_row["called_at"].isoformat()
                if narrative_row and narrative_row["called_at"]
                else None
            ),
        },
    }
