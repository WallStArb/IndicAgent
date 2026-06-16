"""
Signal History API Routes

Provides access to signal_ledger with optional JOIN to intelligence_features
for full feature context at signal time.
"""

from collections import defaultdict
from datetime import datetime
from functools import lru_cache
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from ...config.settings import Settings
from ...core.database_manager import DatabaseManager
from ...persistence.repository.signal_ledger_repository import WIN_OUTCOMES as _WIN_OUTCOMES
from ...persistence.repository.signal_ledger_repository import SignalStatus
from ..dependencies import get_db_manager
from ..utils import parse_jsonb as _parse_jsonb
from ..utils import resolve_contract as _resolve_contract

logger = structlog.get_logger(__name__)

router = APIRouter()

_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {SignalStatus.PENDING.value, SignalStatus.ACTIVE.value}
)

# Default time window for "recent" signals query
_RECENT_SIGNAL_WINDOW_DAYS = 90


@lru_cache(maxsize=1)
def _get_settings() -> Settings:
    """Cached Settings instance to avoid re-instantiation on every request."""
    return Settings()


def _ts(row: Any, primary: str, fallback: str = "timestamp") -> str | None:
    """Serialize a nullable timestamptz row field with a fallback column."""
    v = row[primary] if row[primary] is not None else row[fallback]
    return v.isoformat() if v is not None else None


def _compute_signal_tier(
    was_selected: bool,
    confidence: float | None,
    cis_score: float | None,
) -> str:
    """Classify a signal into Hero / Monitored / Candidate tier.

    Evaluation order: Hero → Monitored → Candidate.
    NULL cis_score → always Monitored (never Hero).
    Thresholds: confidence >= 0.40 (data-derived breakeven);
                abs(cis_score) > 0.35 (CIS fire threshold).

    Args:
        was_selected: Whether the signal was selected for trading
        confidence: Signal confidence score (0-1)
        cis_score: Composite Intelligence Score

    Returns:
        One of "hero", "monitored", or "candidate".
    """
    if (
        was_selected
        and confidence is not None
        and cis_score is not None
        and confidence >= 0.40
        and abs(cis_score) > 0.35
    ):
        return "hero"
    if was_selected:
        return "monitored"
    return "candidate"


def _build_signal_row(row: Any, include_features: bool) -> dict[str, Any]:
    """Build signal response dict from asyncpg row.

    Args:
        row: Database row with signal_ledger columns
        include_features: Whether to include joined intelligence_features

    Returns:
        Signal dict with all applicable fields populated.
    """
    signal: dict[str, Any] = {
        "signal_id": str(row["signal_id"]),
        "timestamp": row["timestamp"].isoformat(),
        "symbol": row["symbol"],
        "timeframe": row["timeframe"],
        "setup_plugin": row["setup_plugin"],
        "signal_type": row["signal_type"],
        "direction": row["direction"],
        "entry_price": float(row["entry_price"]) if row["entry_price"] is not None else None,
        "stop_loss": float(row["stop_loss"]) if row["stop_loss"] is not None else None,
        "confidence": float(row["confidence"]) if row["confidence"] is not None else None,
        "status": row["status"],
        "feature_ts": row["feature_ts"].isoformat() if row["feature_ts"] is not None else None,
        "feature_tf": row["feature_tf"],
        "signal_computed_at": (
            row["signal_computed_at"].isoformat()
            if row.get("signal_computed_at") is not None
            else None
        ),
        "market_price_at_signal": (
            float(row["market_price_at_signal"])
            if row.get("market_price_at_signal") is not None
            else None
        ),
        "ask_at_signal": (
            float(row["ask_at_signal"]) if row.get("ask_at_signal") is not None else None
        ),
        "bid_at_signal": (
            float(row["bid_at_signal"]) if row.get("bid_at_signal") is not None else None
        ),
        "entry_zone_low": (
            float(row["entry_zone_low"]) if row.get("entry_zone_low") is not None else None
        ),
        "entry_zone_high": (
            float(row["entry_zone_high"]) if row.get("entry_zone_high") is not None else None
        ),
        "zone_valid_at_signal": row.get("zone_valid_at_signal"),
    }
    if include_features:
        # feature_ts NULL → features=None (pre-Phase-2 signals without feature context)
        if row["feature_ts"] is None:
            signal["features"] = None
        else:
            signal["features"] = {
                "bar": _parse_jsonb(row["bar"], default=None),
                "i1": _parse_jsonb(row["technical_indicators"], default=None),
                "i3": _parse_jsonb(row["regime_features"], default=None),
                "i4": _parse_jsonb(row["confluence_scores"], default=None),
                "i5": _parse_jsonb(row["pattern_detections"], default=None),
                "smc": _parse_jsonb(row["smc"], default=None),
                "i6": _parse_jsonb(row["cross_timeframe_context"], default=None),
            }
    return signal


def _f(v: Any) -> float | None:
    return float(v) if v is not None else None


def _s(v: Any) -> str | None:
    return str(v) if v is not None else None


def _i(v: Any) -> int | None:
    return int(v) if v is not None else None


@router.get("/signals/active")
async def get_active_signals(
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """All currently pending or active signals from signal_ledger.

    Called by the dashboard on SSE connect to pre-populate signal state
    before live SSE events arrive. Returns one row per (symbol, timeframe)
    for signals with status in ('pending', 'active').
    """
    try:
        query = """
            SELECT DISTINCT ON (sl.symbol, sl.timeframe)
                sl.signal_id,
                sl.symbol,
                sl.timeframe,
                sl.setup_plugin,
                sl.signal_type,
                sl.direction,
                sl.entry_price,
                sl.stop_loss,
                sl.cis_score,
                sl.targets,
                so.status,
                sl.was_selected,
                sl.stop_basis,
                sl.entry_zone_low,
                sl.entry_zone_high,
                sl.signal_computed_at,
                sl.feature_ts AS bar_close_ts,
                sl.timestamp,
                so.staleness_score,
                so.staleness_trigger_reason,
                sl.ttl_bars,
                sl.hmm_regime_at_fire,
                sl.bucket_scores,
                sp.win_rate   AS setup_win_rate,
                sp.avg_pnl_r  AS setup_avg_pnl_r
            FROM signal_ledger sl
            JOIN signal_outcomes so ON sl.signal_id = so.signal_id
            LEFT JOIN setup_performance sp ON sp.setup_plugin = sl.setup_plugin AND sp.symbol = sl.symbol
            WHERE so.status IN ('pending', 'active')
              -- shadow signals included intentionally: dashboard observability (Phase 80)
              AND sl.timestamp >= NOW() - INTERVAL '7 days'
            ORDER BY sl.symbol, sl.timeframe, COALESCE(sl.signal_computed_at, sl.timestamp) DESC
            LIMIT 500
        """
        rows = await db_manager.fetch(query)

        signals = []
        for row in rows:
            targets = _parse_jsonb(row["targets"], default=[])
            t1 = float(targets[0]) if len(targets) > 0 else None
            t2 = float(targets[1]) if len(targets) > 1 else None
            t3 = float(targets[2]) if len(targets) > 2 else None
            entry = _f(row["entry_price"])
            stop = _f(row["stop_loss"])
            rr = (
                round(abs(t1 - entry) / abs(entry - stop), 2)
                if (t1 is not None and entry and stop and entry != stop)
                else None
            )
            signals.append(
                {
                    "signal_id": str(row["signal_id"]),
                    "symbol": row["symbol"],
                    "timeframe": row["timeframe"],
                    "setup_plugin": row["setup_plugin"],
                    "signal_type": row["signal_type"],
                    "direction": row["direction"],
                    "entry_price": entry,
                    "stop_loss": stop,
                    "confidence": None,
                    "status": row["status"],
                    "was_selected": row["was_selected"],
                    "cis_score": _f(row["cis_score"]),
                    "profit_target": t1,
                    "profit_target_2": t2,
                    "profit_target_3": t3,
                    "risk_reward_ratio": rr,
                    "stop_type": _s(row["stop_basis"]),
                    "regime_context": None,
                    "market_price_at_signal": None,
                    "ask_at_signal": None,
                    "bid_at_signal": None,
                    "entry_zone_low": _f(row["entry_zone_low"]),
                    "entry_zone_high": _f(row["entry_zone_high"]),
                    "zone_valid_at_signal": None,
                    "signal_computed_at": _ts(row, "signal_computed_at"),
                    "bar_close_ts": (
                        row["bar_close_ts"].isoformat() if row["bar_close_ts"] is not None else None
                    ),
                    "timestamp": (
                        row["timestamp"].isoformat() if row["timestamp"] is not None else None
                    ),
                    "setup_win_rate": _f(row["setup_win_rate"]),
                    "setup_avg_pnl_r": _f(row["setup_avg_pnl_r"]),
                    "staleness_score": _f(row["staleness_score"]),
                    "staleness_trigger_reason": _s(row["staleness_trigger_reason"]),
                    "ttl_bars": _i(row["ttl_bars"]),
                    "hmm_regime_at_fire": _i(row["hmm_regime_at_fire"]),
                    "bucket_scores": _parse_jsonb(row["bucket_scores"], default=None),
                    "signal_tier": _compute_signal_tier(
                        row["was_selected"],
                        None,
                        _f(row["cis_score"]),
                    ),
                }
            )

        return {"signals": signals, "count": len(signals)}

    except Exception as e:
        logger.error("Error fetching active signals", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Error fetching active signals: {str(e)}"
        ) from e


@router.get("/signals/recent")
async def get_recent_signals(
    symbol: str | None = Query(None, description="Symbol, e.g. ESH6 or ES. Omit for all symbols."),
    timeframe: str | None = Query(None, description="Filter by timeframe, e.g. 1m"),
    limit: int = Query(20, ge=1, le=500, description="Max signals to return"),
    tier: str = Query("hero", pattern="^(hero|monitored|all)$", description="Quality tier filter"),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """Recent signals from signal_ledger for drill panel history.

    Annotated with 30d setup performance from setup_performance table.
    Includes aggregate summary over the returned window.

    Tier filter:
        hero - only hero-quality signals (was_selected=true, high confidence/CIS)
        monitored - all was_selected=true signals
        all - all signals regardless of quality
    """
    # Map tier to boolean filter flags for parameterized query
    require_selected = tier in ("hero", "monitored")
    require_hero_gate = tier == "hero"

    resolved_symbol = _resolve_contract(symbol) if symbol else None

    try:
        main_query = """
            SELECT
                sl.signal_id,
                sl.setup_plugin,
                sl.signal_type,
                sl.direction,
                sl.entry_price,
                sl.stop_loss,
                sl.signal_quality AS confidence,
                sl.was_selected,
                sl.cis_score,
                sl.status,
                sl.outcome,
                sl.exit_price,
                sl.pnl_r,
                sl.signal_computed_at,
                sl.timeframe,
                sl.symbol,
                sl.hmm_regime_at_fire,
                sl.exit_reason,
                sl.mfe,
                sl.ttl_bars,
                sl.bars_in_trade,
                sl.targets,
                sp.win_rate   AS setup_win_rate,
                sp.avg_pnl_r  AS setup_avg_pnl_r
            FROM signal_ledger_full sl
            LEFT JOIN setup_performance sp ON sp.setup_plugin = sl.setup_plugin AND sp.symbol = sl.symbol
            WHERE sl.timestamp >= NOW() - INTERVAL '90 days'
              AND ($1::text IS NULL OR sl.symbol = $1)
              AND ($2::text IS NULL OR sl.timeframe = $2)
              AND (NOT $4::boolean OR sl.was_selected = true)
              AND (NOT $5::boolean OR (sl.signal_quality >= 0.40 AND sl.cis_score IS NOT NULL AND abs(sl.cis_score) > 0.35))
            ORDER BY COALESCE(sl.signal_computed_at, sl.timestamp) DESC
            LIMIT $3
        """
        rows = await db_manager.fetch(
            main_query,
            resolved_symbol,
            timeframe,
            limit,
            require_selected,
            require_hero_gate,
        )

        signals = []
        for row in rows:
            targets = _parse_jsonb(row["targets"], default=[])
            t1 = float(targets[0]) if targets else None
            entry = _f(row["entry_price"])
            stop = _f(row["stop_loss"])
            direction = row["direction"]
            r_ratio = None
            if t1 is not None and entry is not None and stop is not None and entry != stop:
                risk = abs(entry - stop)
                reward = abs(t1 - entry)
                r_ratio = round(reward / risk, 2) if risk > 0 else None
            signals.append(
                {
                    "signal_id": str(row["signal_id"]),
                    "setup_plugin": row["setup_plugin"],
                    "signal_type": row["signal_type"],
                    "direction": direction,
                    "entry_price": entry,
                    "stop_loss": stop,
                    "confidence": _f(row["confidence"]),
                    "was_selected": row["was_selected"],
                    "cis_score": _f(row["cis_score"]),
                    "status": row["status"],
                    "outcome": row["outcome"],
                    "exit_price": _f(row["exit_price"]),
                    "pnl_r": _f(row["pnl_r"]),
                    "computed_at": _ts(row, "signal_computed_at"),
                    "timeframe": row["timeframe"],
                    "symbol": row["symbol"],
                    "setup_win_rate": _f(row["setup_win_rate"]),
                    "setup_avg_pnl_r": _f(row["setup_avg_pnl_r"]),
                    "signal_tier": _compute_signal_tier(
                        row["was_selected"],
                        _f(row["confidence"]),
                        _f(row["cis_score"]),
                    ),
                    "hmm_regime_at_fire": _i(row["hmm_regime_at_fire"]),
                    "exit_reason": _s(row["exit_reason"]),
                    "mfe": _f(row["mfe"]),
                    "ttl_bars": _i(row["ttl_bars"]),
                    "bars_in_trade": _i(row["bars_in_trade"]),
                    "targets": targets,
                    "r_ratio": r_ratio,
                }
            )

        # Compute summary from the returned rows so stats always match what's shown.
        n_resolved = n_suppressed = n_wins = n_with_outcome = 0
        pnl_sum = 0.0
        pnl_count = 0
        for s in signals:
            resolved = s["status"] not in _TERMINAL_STATUSES
            if resolved:
                n_resolved += 1
                if s["outcome"] is not None:
                    n_with_outcome += 1
                    if s["outcome"] in _WIN_OUTCOMES:
                        n_wins += 1
            if s["status"] == SignalStatus.REGIME_SUPPRESSED.value:
                n_suppressed += 1
            if s["pnl_r"] is not None:
                pnl_sum += s["pnl_r"]
                pnl_count += 1
        summary = {
            "n_total": len(signals),
            "n_resolved": n_resolved,
            "n_suppressed": n_suppressed,
            "win_rate": round(n_wins / n_with_outcome, 3) if n_with_outcome else None,
            "avg_pnl_r": round(pnl_sum / pnl_count, 3) if pnl_count else None,
        }

        return {"signals": signals, "summary": summary}

    except Exception as e:
        logger.error("Error fetching recent signals", symbol=resolved_symbol, error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Error fetching recent signals: {str(e)}"
        ) from e


@router.get("/signals/stats")
async def get_signals_stats(
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """Command strip metrics: throughput, hero rate, avg confidence, pipeline latency.

    Computes session counts, hero rate, average confidence, pipeline latency
    percentiles (P50/P95), rolling PnL, and edge trend. Refreshes on a 60s
    client polling cadence.
    """
    try:
        query = """
            SELECT
                -- Session counts (last 24h as proxy for current session)
                COUNT(*) FILTER (
                    WHERE was_selected = true
                      AND COALESCE(signal_computed_at, timestamp) >= NOW() - INTERVAL '24 hours'
                ) AS signals_today,
                COUNT(*) FILTER (
                    WHERE was_selected = true
                      AND COALESCE(signal_computed_at, timestamp) >= NOW() - INTERVAL '48 hours'
                      AND COALESCE(signal_computed_at, timestamp) < NOW() - INTERVAL '24 hours'
                ) AS signals_prev_session,
                -- Hero tier count today
                COUNT(*) FILTER (
                    WHERE was_selected = true
                      AND signal_quality >= 0.40
                      AND cis_score IS NOT NULL
                      AND abs(cis_score) > 0.35
                      AND COALESCE(signal_computed_at, timestamp) >= NOW() - INTERVAL '24 hours'
                ) AS hero_count_today,
                -- Selected count today (denominator for hero_rate)
                COUNT(*) FILTER (
                    WHERE was_selected = true
                      AND COALESCE(signal_computed_at, timestamp) >= NOW() - INTERVAL '24 hours'
                ) AS selected_count_today,
                -- Avg confidence (signal_quality is the post-rename column)
                ROUND(
                    AVG(signal_quality) FILTER (
                        WHERE was_selected = true
                          AND COALESCE(signal_computed_at, timestamp) >= NOW() - INTERVAL '24 hours'
                    )::numeric, 4
                ) AS avg_confidence_today,
                ROUND(
                    AVG(signal_quality) FILTER (
                        WHERE was_selected = true
                          AND COALESCE(signal_computed_at, timestamp) >= NOW() - INTERVAL '7 days'
                    )::numeric, 4
                ) AS avg_confidence_7d,
                -- Pipeline latency: bar close → signal computed (live signals only).
                -- Exclude catch-up signals (pipeline restart replaying stale bars) by
                -- capping to signals fired within 5 minutes of their bar close.
                ROUND(
                    PERCENTILE_CONT(0.5) WITHIN GROUP (
                        ORDER BY EXTRACT(EPOCH FROM (signal_computed_at - timestamp))
                    ) FILTER (
                        WHERE was_selected = true
                          AND signal_computed_at IS NOT NULL
                          AND signal_computed_at >= NOW() - INTERVAL '24 hours'
                          AND signal_computed_at - timestamp <= INTERVAL '5 minutes'
                    )::numeric, 2
                ) AS latency_p50,
                ROUND(
                    PERCENTILE_CONT(0.95) WITHIN GROUP (
                        ORDER BY EXTRACT(EPOCH FROM (signal_computed_at - timestamp))
                    ) FILTER (
                        WHERE was_selected = true
                          AND signal_computed_at IS NOT NULL
                          AND signal_computed_at >= NOW() - INTERVAL '24 hours'
                          AND signal_computed_at - timestamp <= INTERVAL '5 minutes'
                    )::numeric, 2
                ) AS latency_p95,
                -- Rolling pnl_r
                ROUND(
                    AVG(pnl_r) FILTER (
                        WHERE was_selected = true
                          AND pnl_r IS NOT NULL
                          AND timestamp >= NOW() - INTERVAL '7 days'
                    )::numeric, 4
                ) AS avg_pnl_r_7d,
                ROUND(
                    AVG(pnl_r) FILTER (
                        WHERE was_selected = true
                          AND pnl_r IS NOT NULL
                          AND timestamp >= NOW() - INTERVAL '30 days'
                    )::numeric, 4
                ) AS avg_pnl_r_30d
            FROM signal_ledger_full
            WHERE timestamp >= NOW() - INTERVAL '30 days'
        """
        row = await db_manager.fetchrow(query)

        outcomes_query = """
            SELECT outcome, pnl_r
            FROM signal_ledger_full
            WHERE was_selected = true
              AND status NOT IN ('pending', 'active')
              AND outcome IS NOT NULL
            ORDER BY COALESCE(signal_computed_at, timestamp) DESC
            LIMIT 10
        """
        outcome_rows = await db_manager.fetch(outcomes_query)
        recent_outcomes = [{"outcome": r["outcome"], "pnl_r": _f(r["pnl_r"])} for r in outcome_rows]

        signals_today = int(row["signals_today"] or 0)
        signals_prev = int(row["signals_prev_session"] or 0)
        hero_count = int(row["hero_count_today"] or 0)
        selected_count = int(row["selected_count_today"] or 0)
        avg_conf_today = _f(row["avg_confidence_today"])
        avg_conf_7d = _f(row["avg_confidence_7d"])
        latency_p50 = _f(row["latency_p50"])
        latency_p95 = _f(row["latency_p95"])
        alpha_7d = _f(row["avg_pnl_r_7d"])
        alpha_30d = _f(row["avg_pnl_r_30d"])

        hero_rate = round(hero_count / selected_count, 4) if selected_count > 0 else 0.0

        # Edge trend: comparing recent vs baseline rolling pnl_r
        if alpha_7d is not None and alpha_30d is not None:
            diff = alpha_7d - alpha_30d
            if diff > 0.02:
                edge_trend = "expanding"
            elif diff < -0.02:
                edge_trend = "compressing"
            else:
                edge_trend = "stable"
        else:
            edge_trend = "stable"

        # hero_rate_trend: v1 returns 0.0
        hero_rate_trend = 0.0

        return {
            "signals_today": signals_today,
            "signals_prev_session": signals_prev,
            "hero_rate": hero_rate,
            "hero_rate_trend": hero_rate_trend,
            "avg_confidence": avg_conf_today,
            "avg_confidence_7d": avg_conf_7d,
            "pipeline_latency_p50": latency_p50,
            "pipeline_latency_p95": latency_p95,
            "alpha_7d": alpha_7d,
            "alpha_30d": alpha_30d,
            "edge_trend": edge_trend,
            "recent_outcomes": recent_outcomes,
        }

    except Exception as e:
        logger.error("Error fetching signal stats", error=str(e))
        raise HTTPException(status_code=500, detail=f"Error fetching signal stats: {str(e)}") from e


@router.get("/signals/heatmap")
async def get_signals_heatmap(
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """Setup × regime performance matrix for heat map visualization."""
    try:
        query = """
            WITH base AS (
                SELECT
                    setup_plugin,
                    hmm_regime_at_fire AS regime,
                    COUNT(*) AS n,
                    ROUND(AVG(pnl_r)::numeric, 4) AS avg_r,
                    ROUND(
                        AVG(CASE WHEN outcome IN ('target_1', 'target_1_2', 'target_full')
                            THEN 1.0 ELSE 0.0 END)::numeric, 3
                    ) AS win_rate
                FROM signal_ledger_full
                WHERE outcome IS NOT NULL
                  AND pnl_r IS NOT NULL
                  AND was_selected = true
                  AND timestamp >= NOW() - INTERVAL '90 days'
                GROUP BY setup_plugin, hmm_regime_at_fire
            ),
            totals AS (
                SELECT setup_plugin, SUM(n) AS total_n
                FROM base
                GROUP BY setup_plugin
            )
            SELECT b.setup_plugin, b.regime, b.n, b.avg_r, b.win_rate
            FROM base b
            JOIN totals t ON t.setup_plugin = b.setup_plugin
            ORDER BY t.total_n DESC, b.setup_plugin, b.regime
        """
        rows = await db_manager.fetch(query)
        return {
            "cells": [
                {
                    "setup_plugin": row["setup_plugin"],
                    "regime": _i(row["regime"]),
                    "n": int(row["n"]),
                    "avg_r": _f(row["avg_r"]),
                    "win_rate": _f(row["win_rate"]),
                }
                for row in rows
            ]
        }
    except Exception as error:
        logger.error("Error fetching signals heatmap", error=str(error))
        raise HTTPException(status_code=500, detail=str(error)) from error


@router.get("/signals/edge-series")
async def get_signals_edge_series(
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """Daily avg R and win rate for the last 30 days — feeds the edge sparkline."""
    try:
        query = """
            SELECT
                DATE_TRUNC('day', COALESCE(signal_computed_at, timestamp))::date AS day,
                COUNT(*) FILTER (WHERE pnl_r IS NOT NULL) AS n,
                ROUND(AVG(pnl_r) FILTER (WHERE pnl_r IS NOT NULL)::numeric, 4) AS avg_r,
                ROUND(
                    AVG(CASE WHEN outcome IN ('target_1', 'target_1_2', 'target_full')
                        THEN 1.0 ELSE 0.0 END) FILTER (WHERE outcome IS NOT NULL)::numeric, 3
                ) AS win_rate
            FROM signal_ledger_full
            WHERE was_selected = true
              AND COALESCE(signal_computed_at, timestamp) >= NOW() - INTERVAL '30 days'
            GROUP BY 1
            ORDER BY 1
        """
        rows = await db_manager.fetch(query)
        return {
            "series": [
                {
                    "day": str(row["day"]),
                    "n": int(row["n"]),
                    "avg_r": _f(row["avg_r"]),
                    "win_rate": _f(row["win_rate"]),
                }
                for row in rows
            ]
        }
    except Exception as error:
        logger.error("Error fetching edge series", error=str(error))
        raise HTTPException(status_code=500, detail=str(error)) from error


@router.get("/signals/intraday-heatmap")
async def get_signals_intraday_heatmap(
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """Avg R by (hour, day-of-week) — feeds the intraday session heat map."""
    try:
        query = """
            SELECT
                EXTRACT(HOUR FROM COALESCE(signal_computed_at, timestamp) AT TIME ZONE 'America/New_York')::int AS hour,
                EXTRACT(DOW FROM COALESCE(signal_computed_at, timestamp) AT TIME ZONE 'America/New_York')::int AS dow,
                COUNT(*) FILTER (WHERE pnl_r IS NOT NULL) AS n,
                ROUND(AVG(pnl_r) FILTER (WHERE pnl_r IS NOT NULL)::numeric, 4) AS avg_r
            FROM signal_ledger_full
            WHERE was_selected = true
              AND COALESCE(signal_computed_at, timestamp) >= NOW() - INTERVAL '90 days'
              AND EXTRACT(DOW FROM COALESCE(signal_computed_at, timestamp) AT TIME ZONE 'America/New_York') BETWEEN 1 AND 5
              AND EXTRACT(HOUR FROM COALESCE(signal_computed_at, timestamp) AT TIME ZONE 'America/New_York') BETWEEN 8 AND 17
            GROUP BY 1, 2
            ORDER BY 1, 2
        """
        rows = await db_manager.fetch(query)
        return {
            "cells": [
                {
                    "hour": row["hour"],
                    "dow": row["dow"],
                    "n": int(row["n"]),
                    "avg_r": _f(row["avg_r"]),
                }
                for row in rows
            ]
        }
    except Exception as error:
        logger.error("Error fetching intraday heatmap", error=str(error))
        raise HTTPException(status_code=500, detail=str(error)) from error


_WINDOW_MAP: dict[str, str] = {
    "7d": "7 days",
    "30d": "30 days",
    "90d": "90 days",
}


@router.get("/signals/attribution")
async def get_signals_attribution(
    window: str = Query("30d", pattern="^(7d|30d|90d)$"),
    group_by: str = Query("setup", pattern="^(setup|asset_class)$"),
    track: str = Query("zone", pattern="^(zone|market)$"),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """Per-setup or per-asset-class alpha table, read from pre-computed signal_metrics.

    track=zone  → structural setup quality (IC is primary metric)
    track=market → tradeable alpha (Sharpe is primary metric)

    Args:
        window: Time window (7d, 30d, or 90d)
        group_by: Group by "setup" or "asset_class"
        track: "zone" for structural quality, "market" for tradeable alpha
    """
    try:
        window_days_map = {"7d": 7, "30d": 30, "90d": 90}
        window_days = window_days_map.get(window, 30)

        if group_by == "setup":
            rows = await db_manager.fetch(
                """
                SELECT
                    sm.setup_plugin                                                         AS group_key,
                    SUM(sm.n)                                                               AS n,
                    SUM(sm.n_outliers)                                                      AS n_outliers,
                    SUM(sm.win_rate * sm.n)           / NULLIF(SUM(sm.n), 0)               AS win_rate,
                    SUM(sm.avg_r * sm.n)              / NULLIF(SUM(sm.n), 0)               AS avg_pnl_r,
                    SUM(sm.sharpe * sm.n)             / NULLIF(SUM(sm.n), 0)               AS sharpe_proxy,
                    MAX(sm.p_value)                                                         AS p_value,
                    SUM(sm.never_activated_pct * sm.n) / NULLIF(SUM(sm.n), 0)              AS never_activated_pct,
                    SUM(ic.ic * sm.n) / NULLIF(SUM(sm.n) FILTER (WHERE ic.ic IS NOT NULL), 0) AS ic_score,
                    BOOL_OR(ic.is_significant)                                              AS ic_significant
                FROM signal_metrics sm
                LEFT JOIN signal_metrics_ic ic
                       ON ic.setup_plugin = sm.setup_plugin
                      AND ic.tf           = sm.tf
                      AND ic.regime_type  = sm.regime_type
                      AND ic.window_days  = sm.window_days
                WHERE sm.track       = $1
                  AND sm.regime_type = 'all'
                  AND sm.window_days = $2
                GROUP BY sm.setup_plugin
                ORDER BY avg_pnl_r DESC NULLS LAST
                """,
                track,
                window_days,
            )

            groups = []
            for row in rows:
                groups.append(
                    {
                        "name": str(row["group_key"]),
                        "n": int(row["n"] or 0),
                        "win_rate": _f(row["win_rate"]),
                        "avg_pnl_r": _f(row["avg_pnl_r"]),
                        "sharpe_proxy": _f(row["sharpe_proxy"]),
                        "p_value": _f(row["p_value"]),
                        "n_outliers": int(row["n_outliers"] or 0),
                        "never_activated_pct": _f(row["never_activated_pct"]),
                        "ic_score": _f(row["ic_score"]),
                        "ic_significant": (
                            bool(row["ic_significant"])
                            if row["ic_significant"] is not None
                            else None
                        ),
                        "insufficient_data": int(row["n"] or 0) < 30,
                    }
                )

        else:  # asset_class
            # Group by symbol, then bucket into asset classes
            rows = await db_manager.fetch(
                """
                SELECT
                    sm.setup_plugin     AS group_key,
                    sm.n,
                    sm.win_rate,
                    sm.avg_r            AS avg_pnl_r,
                    sm.sharpe           AS sharpe_proxy,
                    sm.p_value
                FROM signal_metrics sm
                WHERE sm.track       = $1
                  AND sm.regime_type = 'all'
                  AND sm.window_days = $2
                """,
                track,
                window_days,
            )
            contracts = _get_settings().contracts
            sym_to_sector: dict[str, str] = {
                c.symbol: (c.sector or c.asset_class.value) for c in contracts
            }
            base_symbols = sorted(sym_to_sector, key=len, reverse=True)

            def _classify(sym: str) -> str:
                if sym in sym_to_sector:
                    return sym_to_sector[sym]
                for base in base_symbols:
                    if sym.startswith(base):
                        return sym_to_sector[base]
                return "unknown"

            buckets: dict[str, dict] = defaultdict(
                lambda: {
                    "n": 0,
                    "pnl_r_sum": 0.0,
                    "win_wins": 0,
                    "win_total": 0,
                    "n_pnl": 0,
                }
            )
            for row in rows:
                sector = _classify(str(row["group_key"]))
                b = buckets[sector]
                b["n"] += int(row["n"] or 0)
                if row["avg_pnl_r"] is not None and row["n"]:
                    b["pnl_r_sum"] += float(row["avg_pnl_r"]) * int(row["n"])
                    b["n_pnl"] += int(row["n"])
                if row["win_rate"] is not None and row["n"]:
                    b["win_wins"] += float(row["win_rate"]) * int(row["n"])
                    b["win_total"] += int(row["n"])

            groups = []
            for sector, b in sorted(
                buckets.items(),
                key=lambda x: x[1]["pnl_r_sum"] / max(x[1]["n_pnl"], 1),
                reverse=True,
            ):
                n_pnl = b["n_pnl"]
                avg_r = round(b["pnl_r_sum"] / n_pnl, 4) if n_pnl > 0 else None
                win_r = round(b["win_wins"] / b["win_total"], 4) if b["win_total"] > 0 else None
                groups.append(
                    {
                        "name": sector,
                        "n": b["n"],
                        "win_rate": win_r,
                        "avg_pnl_r": avg_r,
                        "sharpe_proxy": None,
                        "p_value": None,
                        "insufficient_data": b["n"] < 30,
                    }
                )

        return {"track": track, "window": window, "group_by": group_by, "groups": groups}

    except Exception as error:
        logger.error("Error fetching signal attribution", error=str(error))
        raise HTTPException(status_code=500, detail=str(error)) from error


@router.get("/signals/detail/{signal_id}")
async def get_signal_detail(
    signal_id: str,
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """Full signal detail with intelligence_features JOIN.

    Path is /signals/detail/{signal_id} (not /signals/{signal_id}) to avoid
    shadowing the existing /signals/{symbol} catch-all route.
    """
    try:
        signal_query = """
            SELECT
                sl.signal_id, sl.timestamp, sl.symbol, sl.timeframe,
                sl.setup_plugin, sl.signal_type, sl.direction,
                sl.entry_price, sl.stop_loss, sl.targets, sl.signal_quality AS confidence,
                sl.was_selected, sl.cis_score, sl.bucket_scores,
                sl.status, sl.outcome, sl.exit_price, sl.pnl_r,
                sl.signal_computed_at, sl.feature_ts, sl.feature_tf,
                sl.entry_zone_low, sl.entry_zone_high,
                sl.activation_price, sl.mae, sl.mfe, sl.bars_in_trade,
                sl.hmm_regime_at_fire, sl.activated_at, sl.bars_to_activation,
                sl.exit_reason, sl.ttl_bars, sl.exit_at
            FROM signal_ledger_full sl
            WHERE sl.signal_id = $1::uuid
        """
        row = await db_manager.fetchrow(signal_query, signal_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"Signal {signal_id} not found")

        features = None
        if row["feature_ts"] is not None:
            feat_query = """
                SELECT bar, technical_indicators, pattern_detections, regime_features,
                       confluence_scores, smc, cross_timeframe_context
                FROM intelligence_features
                WHERE ts = $1 AND symbol = $2 AND tf = $3
            """
            feat_row = await db_manager.fetchrow(
                feat_query, row["feature_ts"], row["symbol"], row["feature_tf"]
            )
            if feat_row is not None:
                features = {
                    "bar": _parse_jsonb(feat_row["bar"], default=None),
                    "i1": _parse_jsonb(feat_row["technical_indicators"], default=None),
                    "i3": _parse_jsonb(feat_row["regime_features"], default=None),
                    "i4": _parse_jsonb(feat_row["confluence_scores"], default=None),
                    "i5": _parse_jsonb(feat_row["pattern_detections"], default=None),
                    "smc": _parse_jsonb(feat_row["smc"], default=None),
                    "i6": _parse_jsonb(feat_row["cross_timeframe_context"], default=None),
                }

        return {
            "signal_id": str(row["signal_id"]),
            "timestamp": row["timestamp"].isoformat() if row["timestamp"] else None,
            "symbol": row["symbol"],
            "timeframe": row["timeframe"],
            "setup_plugin": row["setup_plugin"],
            "signal_type": row["signal_type"],
            "direction": row["direction"],
            "entry_price": _f(row["entry_price"]),
            "stop_loss": _f(row["stop_loss"]),
            "targets": _parse_jsonb(row["targets"], default=[]),
            "confidence": _f(row["confidence"]),
            "was_selected": row["was_selected"],
            "cis_score": _f(row["cis_score"]),
            "bucket_scores": _parse_jsonb(row["bucket_scores"], default=None),
            "status": row["status"],
            "outcome": row["outcome"],
            "exit_price": _f(row["exit_price"]),
            "pnl_r": _f(row["pnl_r"]),
            "signal_computed_at": _ts(row, "signal_computed_at"),
            "entry_zone_low": _f(row["entry_zone_low"]),
            "entry_zone_high": _f(row["entry_zone_high"]),
            "zone_valid_at_signal": None,
            "activation_price": _f(row["activation_price"]),
            "mae": _f(row["mae"]),
            "mfe": _f(row["mfe"]),
            "bars_in_trade": row["bars_in_trade"],
            "hmm_regime_at_fire": _i(row["hmm_regime_at_fire"]),
            "activated_at": row["activated_at"].isoformat() if row["activated_at"] else None,
            "bars_to_activation": _i(row["bars_to_activation"]),
            "exit_reason": _s(row["exit_reason"]),
            "ttl_bars": _i(row["ttl_bars"]),
            "exit_at": row["exit_at"].isoformat() if row["exit_at"] else None,
            "signal_tier": _compute_signal_tier(
                row["was_selected"],
                _f(row["confidence"]),
                _f(row["cis_score"]),
            ),
            "features": features,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching signal detail", signal_id=signal_id, error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Error fetching signal detail: {str(e)}"
        ) from e


@router.get("/signals/{symbol}")
async def get_signals(
    symbol: str,
    include_features: bool = Query(
        False, description="Include full feature context from intelligence_features JOIN"
    ),
    from_ts: datetime | None = Query(None, alias="from"),
    to_ts: datetime | None = Query(None, alias="to"),
    timeframe: str | None = Query(None, description="Filter by timeframe, e.g. 5m"),
    limit: int = Query(100, ge=1, le=1000, description="Number of signals to return (max 1000)"),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """Get signal history for a symbol from signal_ledger.

    Accepts both base symbols (ES) and contract codes (ESH6).

    With include_features=true, each signal includes the full intelligence_features
    row at signal time via LEFT JOIN on (symbol, feature_ts, feature_tf).
    Signals with NULL feature_ts (pre-Phase-2) return features: null.
    """
    contract = _resolve_contract(symbol)
    try:
        if include_features:
            query = """
                SELECT sl.signal_id, sl.timestamp, sl.symbol, sl.timeframe,
                       sl.setup_plugin, sl.signal_type, sl.direction,
                       sl.entry_price, sl.stop_loss, sl.signal_quality AS confidence, sl.status,
                       sl.feature_ts, sl.feature_tf, sl.signal_computed_at,
                       sl.entry_zone_low, sl.entry_zone_high,
                       f.bar, f.technical_indicators, f.pattern_detections,
                       f.regime_features, f.confluence_scores, f.smc, f.cross_timeframe_context
                FROM signal_ledger_full sl
                LEFT JOIN intelligence_features f
                  ON sl.symbol = f.symbol
                 AND sl.feature_ts = f.ts
                 AND sl.feature_tf = f.tf
                WHERE sl.symbol = $1
                  AND ($3::timestamptz IS NULL OR sl.timestamp >= $3)
                  AND ($4::timestamptz IS NULL OR sl.timestamp <= $4)
                  AND ($5::text IS NULL OR sl.timeframe = $5)
                ORDER BY sl.timestamp DESC
                LIMIT $2
            """
        else:
            query = """
                SELECT signal_id, timestamp, symbol, timeframe,
                       setup_plugin, signal_type, direction,
                       entry_price, stop_loss, signal_quality AS confidence, status,
                       feature_ts, feature_tf, signal_computed_at,
                       entry_zone_low, entry_zone_high
                FROM signal_ledger_full
                WHERE symbol = $1
                  AND ($3::timestamptz IS NULL OR timestamp >= $3)
                  AND ($4::timestamptz IS NULL OR timestamp <= $4)
                  AND ($5::text IS NULL OR timeframe = $5)
                ORDER BY timestamp DESC
                LIMIT $2
            """

        rows = await db_manager.fetch(query, contract, limit, from_ts, to_ts, timeframe)

        signals = [_build_signal_row(row, include_features) for row in rows]

        return {
            "symbol": contract,
            "count": len(signals),
            "signals": signals,
        }

    except Exception as e:
        logger.error("Error fetching signals", symbol=contract, error=str(e))
        raise HTTPException(status_code=500, detail=f"Error fetching signals: {str(e)}") from e
