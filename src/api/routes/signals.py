"""
Signal History API Routes

Queries signal_events/trade_frames via signal_ledger (join view) for full
feature context at signal time.
"""

from collections import defaultdict
from datetime import datetime
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ...config.settings import Settings
from ...core.database_manager import DatabaseManager
from ...persistence.repository.signal_events_repository import SignalStatus
from ..dependencies import get_db_manager
from ..utils import parse_jsonb as _parse_jsonb
from ..utils import resolve_contract as _resolve_contract
from ..utils import translate_db_errors

router = APIRouter()

_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {SignalStatus.PENDING.value, SignalStatus.ACTIVE.value}
)


# ---------------------------------------------------------------------------
# APR key defaults — the DB values are authoritative; these are fallbacks only
# ---------------------------------------------------------------------------
_APR_DEFAULTS: dict[str, Any] = {
    "ui.signals.recent_window_days": 90,
    "ui.signals.min_confidence": 0.40,
    "ui.signals.min_cis_score": 0.35,
    "ui.signals.today_window_hours": 24,
    "ui.signals.yesterday_window_hours": 48,
    "ui.signals.short_window_days": 7,
    "ui.signals.medium_window_days": 30,
    "ui.signals.latency_threshold_minutes": 5,
    "ui.signals.max_results": 500,
    "ui.signals.top_n_results": 10,
}


async def _get_ui_config(db_manager: DatabaseManager) -> dict[str, Any]:
    """Fetch all ui.signals.* APR keys from config_state, falling back to defaults.

    Always returns a complete dict of APR values. If the DB query fails or returns
    rows without config_key (e.g. in tests), returns _APR_DEFAULTS unchanged.
    """
    keys = list(_APR_DEFAULTS.keys())
    placeholders = ", ".join(f"${i + 1}" for i in range(len(keys)))
    result: dict[str, Any] = dict(_APR_DEFAULTS)
    try:
        rows = await db_manager.fetch(
            f"SELECT cs.config_key, cs.config_value, csc.value_type"
            f" FROM config_state cs JOIN config_schema csc USING (config_key)"
            f" WHERE cs.config_key IN ({placeholders})",
            *keys,
        )
        for row in rows:
            if "config_key" not in row:
                break  # rows are not config rows (test mock); return defaults
            key = row["config_key"]
            if key not in result:
                continue
            raw = row["config_value"]
            vtype = row["value_type"].lower()
            if vtype == "int":
                result[key] = int(raw)
            elif vtype == "float":
                result[key] = float(raw)
            elif vtype == "bool":
                result[key] = raw.lower() in ("true", "1")
            else:
                result[key] = raw
    except Exception:
        pass  # always fall back to defaults rather than crash request
    return result


@lru_cache(maxsize=1)
def _get_settings() -> Settings:
    """Cached Settings instance to avoid re-instantiation on every request."""
    return Settings()


def _to_timestamp(row: Any, primary: str, fallback: str = "timestamp") -> str | None:
    """Serialize a nullable timestamptz row field with a fallback column."""
    v = row[primary] if row[primary] is not None else row[fallback]
    return v.isoformat() if v is not None else None


def _compute_signal_tier(
    was_selected: bool,
    confidence: float | None,
    cis_score: float | None,
    min_confidence: float = 0.40,
    min_cis_score: float = 0.35,
) -> str:
    """Classify a signal into Hero / Monitored / Candidate tier.

    Evaluation order: Hero -> Monitored -> Candidate.
    NULL cis_score -> always Monitored (never Hero).
    Thresholds sourced from ui.signals.min_confidence and ui.signals.min_cis_score APR keys.

    Args:
        was_selected: Whether the signal was selected for trading
        confidence: Signal confidence score (0-1)
        cis_score: Composite Intelligence Score
        min_confidence: Hero confidence gate (default from APR ui.signals.min_confidence)
        min_cis_score: Hero CIS gate (default from APR ui.signals.min_cis_score)

    Returns:
        One of "hero", "monitored", or "candidate".
    """
    if (
        was_selected
        and confidence is not None
        and cis_score is not None
        and confidence >= min_confidence
        and abs(cis_score) > min_cis_score
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
        "tf": row["tf"],
        "setup_plugin": row["setup_plugin"],
        "direction": row["direction"],
        "entry_price": float(row["entry_price"]) if row["entry_price"] is not None else None,
        "stop_loss": float(row["stop_loss"]) if row["stop_loss"] is not None else None,
        "confidence": float(row["raw_confidence"]) if row["raw_confidence"] is not None else None,
        "status": row["status"],
        "feature_ts": row["feature_ts"].isoformat() if row["feature_ts"] is not None else None,
        "signal_computed_at": (
            row["signal_computed_at"].isoformat()
            if row.get("signal_computed_at") is not None
            else None
        ),
        "entry_zone_low": (
            float(row["entry_zone_low"]) if row.get("entry_zone_low") is not None else None
        ),
        "entry_zone_high": (
            float(row["entry_zone_high"]) if row.get("entry_zone_high") is not None else None
        ),
    }
    if include_features:
        # feature_ts NULL -> features=None (pre-Phase-2 signals without feature context)
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


def _to_float(v: Any) -> float | None:
    return float(v) if v is not None else None


def _to_str(v: Any) -> str | None:
    return str(v) if v is not None else None


def _to_int(v: Any) -> int | None:
    return int(v) if v is not None else None


@router.get("/signals/active")
@translate_db_errors
async def get_active_signals(
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """All currently pending or active signals from signal_ledger.

    Called by the dashboard on SSE connect to pre-populate signal state
    before live SSE events arrive. Returns one row per (symbol, timeframe)
    for signals with status in ('pending', 'active').
    """
    cfg = await _get_ui_config(db_manager)
    max_results = int(cfg["ui.signals.max_results"])

    query = """
        SELECT DISTINCT ON (sl.symbol, sl.timeframe)
            sl.signal_id,
            sl.symbol,
            sl.timeframe,
            sl.setup_plugin,
            sl.direction,
            sl.entry_price,
            sl.stop_loss,
            sl.cis_score,
            sl.targets,
            sl.status,
            sl.was_selected,
            sl.frame_details->>'stop_basis' AS stop_basis,
            sl.entry_zone_low,
            sl.entry_zone_high,
            sl.signal_computed_at,
            sl.feature_ts AS bar_close_ts,
            sl.timestamp,
            sl.ttl_bars,
            sl.hmm_regime_at_fire,
            sp.win_rate   AS setup_win_rate,
            sp.avg_pnl_r  AS setup_avg_pnl_r
        FROM signal_ledger sl
        LEFT JOIN setup_performance sp ON sp.setup_plugin = sl.setup_plugin AND sp.symbol = sl.symbol
        WHERE sl.status IN ('pending', 'active')
          -- shadow signals included intentionally: dashboard observability (Phase 80)
          AND sl.timestamp >= NOW() - INTERVAL '7 days'
        ORDER BY sl.symbol, sl.timeframe, COALESCE(sl.signal_computed_at, sl.timestamp) DESC
        LIMIT $1
    """
    rows = await db_manager.fetch(query, max_results)

    signals = []
    for row in rows:
        targets = _parse_jsonb(row["targets"], default=[])
        t1 = float(targets[0]) if len(targets) > 0 else None
        t2 = float(targets[1]) if len(targets) > 1 else None
        t3 = float(targets[2]) if len(targets) > 2 else None
        entry = _to_float(row["entry_price"])
        stop = _to_float(row["stop_loss"])
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
                "direction": row["direction"],
                "entry_price": entry,
                "stop_loss": stop,
                "confidence": None,
                "status": row["status"],
                "was_selected": row["was_selected"],
                "cis_score": _to_float(row["cis_score"]),
                "profit_target": t1,
                "profit_target_2": t2,
                "profit_target_3": t3,
                "risk_reward_ratio": rr,
                "stop_type": _to_str(row["stop_basis"]),
                "regime_context": None,
                "market_price_at_signal": None,
                "ask_at_signal": None,
                "bid_at_signal": None,
                "entry_zone_low": _to_float(row["entry_zone_low"]),
                "entry_zone_high": _to_float(row["entry_zone_high"]),
                "zone_valid_at_signal": None,
                "signal_computed_at": _to_timestamp(row, "signal_computed_at"),
                "bar_close_ts": (
                    row["bar_close_ts"].isoformat() if row["bar_close_ts"] is not None else None
                ),
                "timestamp": (
                    row["timestamp"].isoformat() if row["timestamp"] is not None else None
                ),
                "setup_win_rate": _to_float(row["setup_win_rate"]),
                "setup_avg_pnl_r": _to_float(row["setup_avg_pnl_r"]),
                "ttl_bars": _to_int(row["ttl_bars"]),
                "hmm_regime_at_fire": _to_int(row["hmm_regime_at_fire"]),
                "signal_tier": _compute_signal_tier(
                    row["was_selected"],
                    None,
                    _to_float(row["cis_score"]),
                    min_confidence=cfg["ui.signals.min_confidence"],
                    min_cis_score=cfg["ui.signals.min_cis_score"],
                ),
            }
        )

    return {"signals": signals, "count": len(signals)}


@router.get("/signals/recent")
@translate_db_errors
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

    cfg = await _get_ui_config(db_manager)
    recent_window_days = int(cfg["ui.signals.recent_window_days"])
    min_confidence = float(cfg["ui.signals.min_confidence"])
    min_cis_score = float(cfg["ui.signals.min_cis_score"])

    main_query = """
        SELECT
            sl.signal_id,
            sl.setup_plugin,
            sl.direction,
            sl.entry_price,
            sl.stop_loss,
            sl.raw_confidence AS confidence,
            sl.was_selected,
            sl.cis_score,
            sl.status,
            sl.actual_pnl_r AS pnl_r,
            sl.exit_reason,
            sl.signal_computed_at,
            sl.timeframe,
            sl.symbol,
            sl.hmm_regime_at_fire,
            sl.ttl_bars,
            sl.targets,
            sl.entry_type,
            sp.win_rate   AS setup_win_rate,
            sp.avg_pnl_r  AS setup_avg_pnl_r
        FROM signal_ledger sl
        LEFT JOIN setup_performance sp ON sp.setup_plugin = sl.setup_plugin AND sp.symbol = sl.symbol
        WHERE sl.timestamp >= NOW() - ($6::int * INTERVAL '1 day')
          AND ($1::text IS NULL OR sl.symbol = $1)
          AND ($2::text IS NULL OR sl.timeframe = $2)
          AND (NOT $4::boolean OR sl.was_selected = true)
          AND (NOT $5::boolean OR (sl.raw_confidence >= $7::float AND sl.cis_score IS NOT NULL AND abs(sl.cis_score) > $8::float))
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
        recent_window_days,
        min_confidence,
        min_cis_score,
    )

    signals = []
    for row in rows:
        targets = _parse_jsonb(row["targets"], default=[])
        t1 = float(targets[0]) if targets else None
        entry = _to_float(row["entry_price"])
        stop = _to_float(row["stop_loss"])
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
                "direction": direction,
                "entry_price": entry,
                "stop_loss": stop,
                "confidence": _to_float(row["confidence"]),
                "was_selected": row["was_selected"],
                "cis_score": _to_float(row["cis_score"]),
                "status": row["status"],
                "pnl_r": _to_float(row["pnl_r"]),
                "computed_at": _to_timestamp(row, "signal_computed_at"),
                "timeframe": row["timeframe"],
                "symbol": row["symbol"],
                "setup_win_rate": _to_float(row["setup_win_rate"]),
                "setup_avg_pnl_r": _to_float(row["setup_avg_pnl_r"]),
                "signal_tier": _compute_signal_tier(
                    row["was_selected"],
                    _to_float(row["confidence"]),
                    _to_float(row["cis_score"]),
                    min_confidence=min_confidence,
                    min_cis_score=min_cis_score,
                ),
                "hmm_regime_at_fire": _to_int(row["hmm_regime_at_fire"]),
                "exit_reason": _to_str(row["exit_reason"]),
                "ttl_bars": _to_int(row["ttl_bars"]),
                "targets": targets,
                "r_ratio": r_ratio,
                "entry_type": _to_str(row["entry_type"]),
            }
        )

    # Compute summary from the returned rows so stats always match what's shown.
    n_resolved = n_suppressed = n_wins = n_with_pnl = 0
    pnl_sum = 0.0
    pnl_count = 0
    for s in signals:
        resolved = s["status"] not in _TERMINAL_STATUSES
        if resolved:
            n_resolved += 1
            if s["pnl_r"] is not None:
                n_with_pnl += 1
                if s["pnl_r"] > 0:
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
        "win_rate": round(n_wins / n_with_pnl, 3) if n_with_pnl else None,
        "avg_pnl_r": round(pnl_sum / pnl_count, 3) if pnl_count else None,
    }

    return {"signals": signals, "summary": summary}


@router.get("/signals/stats")
@translate_db_errors
async def get_signals_stats(
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """Command strip metrics: throughput, hero rate, avg confidence, pipeline latency.

    Computes session counts, hero rate, average confidence, pipeline latency
    percentiles (P50/P95), rolling PnL, and edge trend. Refreshes on a 60s
    client polling cadence.
    """
    cfg = await _get_ui_config(db_manager)
    today_hours = int(cfg["ui.signals.today_window_hours"])
    yesterday_hours = int(cfg["ui.signals.yesterday_window_hours"])
    short_days = int(cfg["ui.signals.short_window_days"])
    medium_days = int(cfg["ui.signals.medium_window_days"])
    latency_mins = int(cfg["ui.signals.latency_threshold_minutes"])
    top_n = int(cfg["ui.signals.top_n_results"])
    min_confidence = float(cfg["ui.signals.min_confidence"])
    min_cis_score = float(cfg["ui.signals.min_cis_score"])

    query = f"""
        SELECT
            -- Session counts (last {today_hours}h as proxy for current session)
            COUNT(*) FILTER (
                WHERE was_selected = true
                  AND COALESCE(signal_computed_at, timestamp) >= NOW() - INTERVAL '{today_hours} hours'
            ) AS signals_today,
            COUNT(*) FILTER (
                WHERE was_selected = true
                  AND COALESCE(signal_computed_at, timestamp) >= NOW() - INTERVAL '{yesterday_hours} hours'
                  AND COALESCE(signal_computed_at, timestamp) < NOW() - INTERVAL '{today_hours} hours'
            ) AS signals_prev_session,
            -- Hero tier count today
            COUNT(*) FILTER (
                WHERE was_selected = true
                  AND raw_confidence >= {min_confidence}
                  AND cis_score IS NOT NULL
                  AND abs(cis_score) > {min_cis_score}
                  AND COALESCE(signal_computed_at, timestamp) >= NOW() - INTERVAL '{today_hours} hours'
            ) AS hero_count_today,
            -- Selected count today (denominator for hero_rate)
            COUNT(*) FILTER (
                WHERE was_selected = true
                  AND COALESCE(signal_computed_at, timestamp) >= NOW() - INTERVAL '{today_hours} hours'
            ) AS selected_count_today,
            -- Avg confidence (raw_confidence is the canonical column)
            ROUND(
                AVG(raw_confidence) FILTER (
                    WHERE was_selected = true
                      AND COALESCE(signal_computed_at, timestamp) >= NOW() - INTERVAL '{today_hours} hours'
                )::numeric, 4
            ) AS avg_confidence_today,
            ROUND(
                AVG(raw_confidence) FILTER (
                    WHERE was_selected = true
                      AND COALESCE(signal_computed_at, timestamp) >= NOW() - INTERVAL '{short_days} days'
                )::numeric, 4
            ) AS avg_confidence_7d,
            -- Pipeline latency: bar close -> signal computed (live signals only).
            -- Exclude catch-up signals (pipeline restart replaying stale bars) by
            -- capping to signals fired within {latency_mins} minutes of their bar close.
            ROUND(
                PERCENTILE_CONT(0.5) WITHIN GROUP (
                    ORDER BY EXTRACT(EPOCH FROM (signal_computed_at - timestamp))
                ) FILTER (
                    WHERE was_selected = true
                      AND signal_computed_at IS NOT NULL
                      AND signal_computed_at >= NOW() - INTERVAL '{today_hours} hours'
                      AND signal_computed_at - timestamp <= INTERVAL '{latency_mins} minutes'
                )::numeric, 2
            ) AS latency_p50,
            ROUND(
                PERCENTILE_CONT(0.95) WITHIN GROUP (
                    ORDER BY EXTRACT(EPOCH FROM (signal_computed_at - timestamp))
                ) FILTER (
                    WHERE was_selected = true
                      AND signal_computed_at IS NOT NULL
                      AND signal_computed_at >= NOW() - INTERVAL '{today_hours} hours'
                      AND signal_computed_at - timestamp <= INTERVAL '{latency_mins} minutes'
                )::numeric, 2
            ) AS latency_p95,
            -- Rolling actual_pnl_r from trade_executions via view
            ROUND(
                AVG(actual_pnl_r) FILTER (
                    WHERE was_selected = true
                      AND actual_pnl_r IS NOT NULL
                      AND timestamp >= NOW() - INTERVAL '{short_days} days'
                )::numeric, 4
            ) AS avg_pnl_r_7d,
            ROUND(
                AVG(actual_pnl_r) FILTER (
                    WHERE was_selected = true
                      AND actual_pnl_r IS NOT NULL
                      AND timestamp >= NOW() - INTERVAL '{medium_days} days'
                )::numeric, 4
            ) AS avg_pnl_r_30d
        FROM signal_ledger
        WHERE timestamp >= NOW() - INTERVAL '{medium_days} days'
    """
    row = await db_manager.fetchrow(query)

    outcomes_query = f"""
        SELECT exit_reason, actual_pnl_r
        FROM signal_ledger
        WHERE was_selected = true
          AND status NOT IN ('pending', 'active')
          AND exit_reason IS NOT NULL
        ORDER BY COALESCE(signal_computed_at, timestamp) DESC
        LIMIT {top_n}
    """
    outcome_rows = await db_manager.fetch(outcomes_query)
    recent_outcomes = [
        {"outcome": r["exit_reason"], "pnl_r": _to_float(r["actual_pnl_r"])} for r in outcome_rows
    ]

    signals_today = int(row["signals_today"] or 0)
    signals_prev = int(row["signals_prev_session"] or 0)
    hero_count = int(row["hero_count_today"] or 0)
    selected_count = int(row["selected_count_today"] or 0)
    avg_conf_today = _to_float(row["avg_confidence_today"])
    avg_conf_7d = _to_float(row["avg_confidence_7d"])
    latency_p50 = _to_float(row["latency_p50"])
    latency_p95 = _to_float(row["latency_p95"])
    alpha_7d = _to_float(row["avg_pnl_r_7d"])
    alpha_30d = _to_float(row["avg_pnl_r_30d"])

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


@router.get("/signals/heatmap")
@translate_db_errors
async def get_signals_heatmap(
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """Setup x regime performance matrix for heat map visualization."""
    cfg = await _get_ui_config(db_manager)
    recent_window_days = int(cfg["ui.signals.recent_window_days"])

    query = f"""
        WITH base AS (
            SELECT
                setup_plugin,
                hmm_regime_at_fire AS regime,
                COUNT(*) AS n,
                ROUND(AVG(actual_pnl_r)::numeric, 4) AS avg_r,
                ROUND(
                    AVG(CASE WHEN exit_reason IN ('target_1', 'target_1_2', 'target_full')
                        THEN 1.0 ELSE 0.0 END)::numeric, 3
                ) AS win_rate
            FROM signal_ledger
            WHERE exit_reason IS NOT NULL
              AND actual_pnl_r IS NOT NULL
              AND was_selected = true
              AND timestamp >= NOW() - INTERVAL '{recent_window_days} days'
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
                "regime": _to_int(row["regime"]),
                "n": int(row["n"]),
                "avg_r": _to_float(row["avg_r"]),
                "win_rate": _to_float(row["win_rate"]),
            }
            for row in rows
        ]
    }


@router.get("/signals/edge-series")
@translate_db_errors
async def get_signals_edge_series(
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """Daily avg R and win rate for the last 30 days - feeds the edge sparkline."""
    cfg = await _get_ui_config(db_manager)
    medium_days = int(cfg["ui.signals.medium_window_days"])

    query = f"""
        SELECT
            DATE_TRUNC('day', COALESCE(signal_computed_at, timestamp))::date AS day,
            COUNT(*) FILTER (WHERE actual_pnl_r IS NOT NULL) AS n,
            ROUND(AVG(actual_pnl_r) FILTER (WHERE actual_pnl_r IS NOT NULL)::numeric, 4) AS avg_r,
            ROUND(
                AVG(CASE WHEN exit_reason IN ('target_1', 'target_1_2', 'target_full')
                    THEN 1.0 ELSE 0.0 END) FILTER (WHERE exit_reason IS NOT NULL)::numeric, 3
            ) AS win_rate
        FROM signal_ledger
        WHERE was_selected = true
          AND COALESCE(signal_computed_at, timestamp) >= NOW() - INTERVAL '{medium_days} days'
        GROUP BY 1
        ORDER BY 1
    """
    rows = await db_manager.fetch(query)
    return {
        "series": [
            {
                "day": str(row["day"]),
                "n": int(row["n"]),
                "avg_r": _to_float(row["avg_r"]),
                "win_rate": _to_float(row["win_rate"]),
            }
            for row in rows
        ]
    }


@router.get("/signals/intraday-heatmap")
@translate_db_errors
async def get_signals_intraday_heatmap(
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """Avg R by (hour, day-of-week) - feeds the intraday session heat map."""
    cfg = await _get_ui_config(db_manager)
    recent_window_days = int(cfg["ui.signals.recent_window_days"])

    query = f"""
        SELECT
            EXTRACT(HOUR FROM COALESCE(signal_computed_at, timestamp) AT TIME ZONE 'America/New_York')::int AS hour,
            EXTRACT(DOW FROM COALESCE(signal_computed_at, timestamp) AT TIME ZONE 'America/New_York')::int AS dow,
            COUNT(*) FILTER (WHERE actual_pnl_r IS NOT NULL) AS n,
            ROUND(AVG(actual_pnl_r) FILTER (WHERE actual_pnl_r IS NOT NULL)::numeric, 4) AS avg_r
        FROM signal_ledger
        WHERE was_selected = true
          AND COALESCE(signal_computed_at, timestamp) >= NOW() - INTERVAL '{recent_window_days} days'
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
                "avg_r": _to_float(row["avg_r"]),
            }
            for row in rows
        ]
    }


_WINDOW_MAP: dict[str, str] = {
    "7d": "7 days",
    "30d": "30 days",
    "90d": "90 days",
}


@router.get("/signals/attribution")
@translate_db_errors
async def get_signals_attribution(
    window: str = Query("30d", pattern="^(7d|30d|90d)$"),
    group_by: str = Query("setup", pattern="^(setup|asset_class)$"),
    track: str = Query("zone", pattern="^(zone|market)$"),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """Per-setup or per-asset-class alpha table, read from pre-computed signal_metrics.

    track=zone  -> structural setup quality (IC is primary metric)
    track=market -> tradeable alpha (Sharpe is primary metric)

    Args:
        window: Time window (7d, 30d, or 90d)
        group_by: Group by "setup" or "asset_class"
        track: "zone" for structural quality, "market" for tradeable alpha
    """
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
                    "win_rate": _to_float(row["win_rate"]),
                    "avg_pnl_r": _to_float(row["avg_pnl_r"]),
                    "sharpe_proxy": _to_float(row["sharpe_proxy"]),
                    "p_value": _to_float(row["p_value"]),
                    "n_outliers": int(row["n_outliers"] or 0),
                    "never_activated_pct": _to_float(row["never_activated_pct"]),
                    "ic_score": _to_float(row["ic_score"]),
                    "ic_significant": (
                        bool(row["ic_significant"]) if row["ic_significant"] is not None else None
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


@router.get("/signals/detail/{signal_id}")
@translate_db_errors
async def get_signal_detail(
    signal_id: str,
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """Full signal detail with intelligence_features JOIN.

    Path is /signals/detail/{signal_id} (not /signals/{signal_id}) to avoid
    shadowing the existing /signals/{symbol} catch-all route.
    """
    signal_query = """
        SELECT
            sl.signal_id, sl.timestamp, sl.symbol, sl.timeframe, sl.tf,
            sl.setup_plugin, sl.direction,
            sl.entry_price, sl.stop_loss, sl.targets, sl.raw_confidence AS confidence,
            sl.was_selected, sl.cis_score,
            sl.status, sl.exit_reason,
            sl.actual_pnl_r AS pnl_r, sl.actual_fill_price AS exit_price,
            sl.signal_computed_at, sl.feature_ts,
            sl.entry_zone_low, sl.entry_zone_high,
            sl.activated_at, sl.hmm_regime_at_fire,
            sl.ttl_bars, sl.exit_at,
            sl.frame_details->>'stop_basis' AS stop_basis,
            sl.counterfactual_pnl_r,
            sl.entry_type,
            sl.r_multiple
        FROM signal_ledger sl
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
            feat_query, row["feature_ts"], row["symbol"], row["tf"]
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

    cfg = await _get_ui_config(db_manager)

    return {
        "signal_id": str(row["signal_id"]),
        "timestamp": row["timestamp"].isoformat() if row["timestamp"] else None,
        "symbol": row["symbol"],
        "timeframe": row["timeframe"],
        "tf": row["tf"],
        "setup_plugin": row["setup_plugin"],
        "direction": row["direction"],
        "entry_price": _to_float(row["entry_price"]),
        "stop_loss": _to_float(row["stop_loss"]),
        "targets": _parse_jsonb(row["targets"], default=[]),
        "confidence": _to_float(row["confidence"]),
        "was_selected": row["was_selected"],
        "cis_score": _to_float(row["cis_score"]),
        "status": row["status"],
        "exit_reason": _to_str(row["exit_reason"]),
        "pnl_r": _to_float(row["pnl_r"]),
        "exit_price": _to_float(row["exit_price"]),
        "counterfactual_pnl_r": _to_float(row["counterfactual_pnl_r"]),
        "signal_computed_at": _to_timestamp(row, "signal_computed_at"),
        "entry_zone_low": _to_float(row["entry_zone_low"]),
        "entry_zone_high": _to_float(row["entry_zone_high"]),
        "zone_valid_at_signal": None,
        "stop_basis": _to_str(row["stop_basis"]),
        "hmm_regime_at_fire": _to_int(row["hmm_regime_at_fire"]),
        "activated_at": row["activated_at"].isoformat() if row["activated_at"] else None,
        "ttl_bars": _to_int(row["ttl_bars"]),
        "exit_at": row["exit_at"].isoformat() if row["exit_at"] else None,
        "entry_type": _to_str(row["entry_type"]),
        "r_multiple": _to_float(row["r_multiple"]),
        "signal_tier": _compute_signal_tier(
            row["was_selected"],
            _to_float(row["confidence"]),
            _to_float(row["cis_score"]),
            min_confidence=cfg["ui.signals.min_confidence"],
            min_cis_score=cfg["ui.signals.min_cis_score"],
        ),
        "features": features,
    }


@router.get("/signals/{symbol}")
@translate_db_errors
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
    row at signal time via LEFT JOIN on (symbol, feature_ts, tf).
    Signals with NULL feature_ts (pre-Phase-2) return features: null.
    """
    contract = _resolve_contract(symbol)
    if include_features:
        query = """
            SELECT sl.signal_id, sl.timestamp, sl.symbol, sl.timeframe, sl.tf,
                   sl.setup_plugin, sl.direction,
                   sl.entry_price, sl.stop_loss, sl.raw_confidence AS confidence, sl.status,
                   sl.feature_ts, sl.signal_computed_at,
                   sl.entry_zone_low, sl.entry_zone_high,
                   f.bar, f.technical_indicators, f.pattern_detections,
                   f.regime_features, f.confluence_scores, f.smc, f.cross_timeframe_context
            FROM signal_ledger sl
            LEFT JOIN intelligence_features f
              ON sl.symbol = f.symbol
             AND sl.feature_ts = f.ts
             AND sl.tf = f.tf
            WHERE sl.symbol = $1
              AND ($3::timestamptz IS NULL OR sl.timestamp >= $3)
              AND ($4::timestamptz IS NULL OR sl.timestamp <= $4)
              AND ($5::text IS NULL OR sl.timeframe = $5)
            ORDER BY sl.timestamp DESC
            LIMIT $2
        """
    else:
        query = """
            SELECT signal_id, timestamp, symbol, timeframe, tf,
                   setup_plugin, direction,
                   entry_price, stop_loss, raw_confidence AS confidence, status,
                   feature_ts, signal_computed_at,
                   entry_zone_low, entry_zone_high
            FROM signal_ledger
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
