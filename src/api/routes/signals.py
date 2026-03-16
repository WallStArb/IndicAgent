"""
Signal History API Routes

Provides access to signal_ledger with optional JOIN to intelligence_features
for full feature context at signal time.
"""

import math
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from scipy import stats as _scipy_stats

from ...core.database_manager import DatabaseManager
from ..dependencies import get_db_manager
from ..utils import parse_jsonb as _parse_jsonb
from ..utils import resolve_contract as _resolve_contract

logger = structlog.get_logger(__name__)

router = APIRouter()


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


def _compute_p_value(avg_pnl_r: float, std_pnl_r: float, n: int) -> float | None:
    """Two-sided one-sample t-test p-value against null hypothesis mean=0.

    Returns None if inputs are invalid (n < 2, std near-zero or NaN/Inf).
    """
    if n < 2 or std_pnl_r < 1e-9 or math.isnan(std_pnl_r) or math.isinf(std_pnl_r):
        return None
    t_stat = avg_pnl_r / (std_pnl_r / math.sqrt(n))
    return float(_scipy_stats.t.sf(abs(t_stat), df=n - 1) * 2)


def _build_signal_row(row: Any, include_features: bool) -> dict[str, Any]:
    """Build signal response dict from asyncpg row."""
    signal: dict[str, Any] = {
        "signal_id": str(row["signal_id"]),
        "timestamp": (
            row["timestamp"].isoformat()
            if hasattr(row["timestamp"], "isoformat")
            else str(row["timestamp"])
        ),
        "symbol": row["symbol"],
        "timeframe": row["timeframe"],
        "setup_plugin": row["setup_plugin"],
        "signal_type": row["signal_type"],
        "direction": row["direction"],
        "entry_price": float(row["entry_price"]) if row["entry_price"] is not None else None,
        "stop_loss": float(row["stop_loss"]) if row["stop_loss"] is not None else None,
        "confidence": float(row["confidence"]) if row["confidence"] is not None else None,
        "status": row["status"],
        "feature_ts": (
            row["feature_ts"].isoformat()
            if row["feature_ts"] is not None and hasattr(row["feature_ts"], "isoformat")
            else None
        ),
        "feature_tf": row["feature_tf"],
        "signal_computed_at": (
            row["signal_computed_at"].isoformat()
            if row.get("signal_computed_at") is not None
            and hasattr(row["signal_computed_at"], "isoformat")
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
                "i1": _parse_jsonb(row["i1"], default=None),
                "i3": _parse_jsonb(row["i3"], default=None),
                "i4": _parse_jsonb(row["i4"], default=None),
                "i5": _parse_jsonb(row["i5"], default=None),
                "smc": _parse_jsonb(row["smc"], default=None),
                "i6": _parse_jsonb(row["i6"], default=None),
            }
    return signal


# Outcome classes considered wins for summary win_rate computation
_WIN_OUTCOMES = frozenset({"target_1", "target_1_2", "target_full"})


@router.get("/signals/recent")
async def get_recent_signals(
    symbol: str | None = Query(None, description="Symbol, e.g. ESH6 or ES. Omit for all symbols."),
    timeframe: str | None = Query(None, description="Filter by timeframe, e.g. 1m"),
    limit: int = Query(20, ge=1, le=500, description="Max signals to return"),
    tier: str = Query("hero", pattern="^(hero|monitored|all)$", description="Quality tier filter"),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """
    Recent signals from signal_ledger for drill panel history.

    Annotated with 30d setup performance from setup_performance table.
    Includes aggregate summary over the returned window.
    """
    # Build tier WHERE clause
    if tier == "hero":
        tier_clause = """
        AND sl.was_selected = true
        AND sl.confidence >= 0.40
        AND sl.cis_score IS NOT NULL
        AND abs(sl.cis_score) > 0.35
    """
    elif tier == "monitored":
        tier_clause = "AND sl.was_selected = true"
    else:  # all
        tier_clause = ""

    resolved_symbol = _resolve_contract(symbol) if symbol else None

    try:
        main_query = f"""
            SELECT
                sl.signal_id,
                sl.setup_plugin,
                sl.signal_type,
                sl.direction,
                sl.entry_price,
                sl.stop_loss,
                sl.confidence,
                sl.was_selected,
                sl.cis_score,
                sl.status,
                sl.outcome,
                sl.exit_price,
                sl.pnl_r,
                sl.signal_computed_at,
                sl.timeframe,
                sl.symbol,
                sp.win_rate   AS setup_win_rate,
                sp.avg_pnl_r  AS setup_avg_pnl_r
            FROM signal_ledger sl
            LEFT JOIN setup_performance sp ON sp.setup_type = sl.signal_type
            WHERE ($1::text IS NULL OR sl.symbol = $1)
              AND ($2::text IS NULL OR sl.timeframe = $2)
              {tier_clause}
            ORDER BY sl.signal_computed_at DESC
            LIMIT $3
        """
        rows = await db_manager.fetch(main_query, resolved_symbol, timeframe, limit)

        summary_query = """
            SELECT
                COUNT(*)                                                          AS n_total,
                COUNT(*) FILTER (WHERE status NOT IN ('pending', 'active'))       AS n_resolved,
                COUNT(*) FILTER (WHERE status = 'regime_suppressed')              AS n_suppressed,
                ROUND(
                    AVG(CASE WHEN outcome IN ('target_1','target_1_2','target_full') THEN 1.0
                             WHEN outcome IS NOT NULL
                              AND status NOT IN ('pending','active') THEN 0.0
                             ELSE NULL END)::numeric, 3
                )                                                                 AS win_rate,
                ROUND(AVG(pnl_r) FILTER (WHERE pnl_r IS NOT NULL)::numeric, 3)   AS avg_pnl_r
            FROM signal_ledger
            WHERE ($1::text IS NULL OR symbol = $1)
              AND ($2::text IS NULL OR timeframe = $2)
        """
        summary_row = await db_manager.fetchrow(summary_query, resolved_symbol, timeframe)

        def _f(v: Any) -> float | None:
            return float(v) if v is not None else None

        signals = [
            {
                "signal_id": str(row["signal_id"]),
                "setup_plugin": row["setup_plugin"],
                "signal_type": row["signal_type"],
                "direction": row["direction"],
                "entry_price": _f(row["entry_price"]),
                "stop_loss": _f(row["stop_loss"]),
                "confidence": _f(row["confidence"]),
                "was_selected": row["was_selected"],
                "cis_score": _f(row["cis_score"]),
                "status": row["status"],
                "outcome": row["outcome"],
                "exit_price": _f(row["exit_price"]),
                "pnl_r": _f(row["pnl_r"]),
                "computed_at": (
                    row["signal_computed_at"].isoformat()
                    if row["signal_computed_at"] is not None
                    and hasattr(row["signal_computed_at"], "isoformat")
                    else None
                ),
                "timeframe": row["timeframe"],
                "symbol": row["symbol"],
                "setup_win_rate": _f(row["setup_win_rate"]),
                "setup_avg_pnl_r": _f(row["setup_avg_pnl_r"]),
                "signal_tier": _compute_signal_tier(
                    row["was_selected"],
                    _f(row["confidence"]),
                    _f(row["cis_score"]),
                ),
            }
            for row in rows
        ]

        summary = {
            "n_total": int(summary_row["n_total"]) if summary_row else 0,
            "n_resolved": int(summary_row["n_resolved"]) if summary_row else 0,
            "n_suppressed": int(summary_row["n_suppressed"]) if summary_row else 0,
            "win_rate": _f(summary_row["win_rate"]) if summary_row else None,
            "avg_pnl_r": _f(summary_row["avg_pnl_r"]) if summary_row else None,
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
    """
    Command strip metrics: throughput, hero rate, avg confidence,
    pipeline latency percentiles, alpha composite, edge trend.
    Refreshes on a 60s client polling cadence.
    """
    try:
        query = """
            SELECT
                -- Session counts (last 24h as proxy for current session)
                COUNT(*) FILTER (
                    WHERE was_selected = true
                      AND signal_computed_at >= NOW() - INTERVAL '24 hours'
                ) AS signals_today,
                COUNT(*) FILTER (
                    WHERE was_selected = true
                      AND signal_computed_at >= NOW() - INTERVAL '48 hours'
                      AND signal_computed_at < NOW() - INTERVAL '24 hours'
                ) AS signals_prev_session,
                -- Hero tier count today
                COUNT(*) FILTER (
                    WHERE was_selected = true
                      AND confidence >= 0.40
                      AND cis_score IS NOT NULL
                      AND abs(cis_score) > 0.35
                      AND signal_computed_at >= NOW() - INTERVAL '24 hours'
                ) AS hero_count_today,
                -- Selected count today (denominator for hero_rate)
                COUNT(*) FILTER (
                    WHERE was_selected = true
                      AND signal_computed_at >= NOW() - INTERVAL '24 hours'
                ) AS selected_count_today,
                -- Avg confidence
                ROUND(
                    AVG(confidence) FILTER (
                        WHERE was_selected = true
                          AND signal_computed_at >= NOW() - INTERVAL '24 hours'
                    )::numeric, 4
                ) AS avg_confidence_today,
                ROUND(
                    AVG(confidence) FILTER (
                        WHERE was_selected = true
                          AND signal_computed_at >= NOW() - INTERVAL '7 days'
                    )::numeric, 4
                ) AS avg_confidence_7d,
                -- Pipeline latency: signal_computed_at - timestamp (bar close time)
                ROUND(
                    PERCENTILE_CONT(0.5) WITHIN GROUP (
                        ORDER BY EXTRACT(EPOCH FROM (signal_computed_at - timestamp))
                    ) FILTER (
                        WHERE was_selected = true
                          AND signal_computed_at IS NOT NULL
                          AND signal_computed_at >= NOW() - INTERVAL '24 hours'
                    )::numeric, 2
                ) AS latency_p50,
                ROUND(
                    PERCENTILE_CONT(0.95) WITHIN GROUP (
                        ORDER BY EXTRACT(EPOCH FROM (signal_computed_at - timestamp))
                    ) FILTER (
                        WHERE was_selected = true
                          AND signal_computed_at IS NOT NULL
                          AND signal_computed_at >= NOW() - INTERVAL '24 hours'
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
            FROM signal_ledger
        """
        row = await db_manager.fetchrow(query)

        def _f(v: Any) -> float | None:
            return float(v) if v is not None else None

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
        }

    except Exception as e:
        logger.error("Error fetching signal stats", error=str(e))
        raise HTTPException(status_code=500, detail=f"Error fetching signal stats: {str(e)}") from e


_WINDOW_MAP: dict[str, str] = {
    "7d": "7 days",
    "30d": "30 days",
    "90d": "90 days",
}


@router.get("/signals/attribution")
async def get_signals_attribution(
    window: str = Query("30d", pattern="^(7d|30d|90d)$"),
    group_by: str = Query("setup", pattern="^(setup|asset_class)$"),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """
    Per-setup or per-asset-class alpha table.

    Computes AVG/STDDEV of pnl_r from signal_ledger directly (NOT setup_performance).
    Includes sharpe_proxy and two-sided t-test p-value.
    """
    try:
        interval = _WINDOW_MAP.get(window, "30 days")

        if group_by == "setup":
            group_field = "sl.setup_plugin"
        else:
            group_field = "sl.symbol"  # will be remapped to asset_class in Python

        query = f"""
            SELECT
                {group_field}                                                 AS group_key,
                COUNT(*) FILTER (
                    WHERE sl.outcome IS NOT NULL
                      AND sl.status NOT IN ('pending', 'active')
                )                                                             AS n,
                ROUND(
                    AVG(CASE
                            WHEN sl.outcome IN ('target_1','target_1_2','target_full') THEN 1.0
                            WHEN sl.outcome IS NOT NULL
                             AND sl.status NOT IN ('pending','active') THEN 0.0
                            ELSE NULL
                        END)::numeric, 4
                )                                                             AS win_rate,
                ROUND(
                    AVG(sl.pnl_r) FILTER (WHERE sl.pnl_r IS NOT NULL)::numeric, 4
                )                                                             AS avg_pnl_r,
                ROUND(
                    STDDEV(sl.pnl_r) FILTER (WHERE sl.pnl_r IS NOT NULL)::numeric, 4
                )                                                             AS std_pnl_r,
                COUNT(*) FILTER (WHERE sl.pnl_r IS NOT NULL)                 AS n_pnl
            FROM signal_ledger sl
            WHERE sl.was_selected = true
              AND sl.timestamp >= NOW() - INTERVAL '{interval}'
            GROUP BY {group_field}
            ORDER BY avg_pnl_r DESC NULLS LAST
        """
        rows = await db_manager.fetch(query)

        if group_by == "asset_class":
            from collections import defaultdict

            from src.config.settings import Settings

            _settings = Settings()
            contracts = _settings.get_active_contracts()
            sym_to_sector: dict[str, str] = {
                c.symbol: (c.sector or c.asset_class.value) for c in contracts
            }
            base_symbols = sorted(sym_to_sector, key=len, reverse=True)

            def _classify(contract_sym: str) -> str:
                if contract_sym in sym_to_sector:
                    return sym_to_sector[contract_sym]
                for base in base_symbols:
                    if contract_sym.startswith(base):
                        return sym_to_sector[base]
                return "unknown"

            sector_buckets: dict[str, dict[str, Any]] = defaultdict(
                lambda: {
                    "n": 0,
                    "win_wins": 0,
                    "win_total": 0,
                    "pnl_r_sum": 0.0,
                    "pnl_r_sq_sum": 0.0,
                    "n_pnl": 0,
                }
            )
            for row in rows:
                sector = _classify(str(row["group_key"]))
                b = sector_buckets[sector]
                b["n"] += int(row["n"] or 0)
                b["n_pnl"] += int(row["n_pnl"] or 0)
                if row["avg_pnl_r"] is not None and row["n_pnl"]:
                    b["pnl_r_sum"] += float(row["avg_pnl_r"]) * int(row["n_pnl"])
                if row["win_rate"] is not None and row["n"]:
                    b["win_wins"] += float(row["win_rate"]) * int(row["n"])
                    b["win_total"] += int(row["n"])

            groups = []
            for sector, b in sorted(
                sector_buckets.items(),
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
                        "std_pnl_r": None,
                    }
                )
        else:

            def _f(v: Any) -> float | None:
                return float(v) if v is not None else None

            groups = []
            for row in rows:
                avg_r = _f(row["avg_pnl_r"])
                std_r = _f(row["std_pnl_r"])
                n_pnl = int(row["n_pnl"] or 0)
                sharpe = (
                    round(avg_r / std_r, 4)
                    if avg_r is not None and std_r and std_r != 0
                    else None
                )
                p_val = (
                    _compute_p_value(avg_r, std_r, n_pnl)
                    if avg_r is not None and std_r is not None
                    else None
                )
                groups.append(
                    {
                        "name": str(row["group_key"]),
                        "n": int(row["n"] or 0),
                        "win_rate": _f(row["win_rate"]),
                        "avg_pnl_r": avg_r,
                        "std_pnl_r": std_r,
                        "sharpe_proxy": sharpe,
                        "p_value": round(p_val, 4) if p_val is not None else None,
                    }
                )

        return {"window": window, "group_by": group_by, "groups": groups}

    except Exception as e:
        logger.error("Error fetching signal attribution", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Error fetching attribution: {str(e)}"
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
    """
    Get signal history for a symbol from signal_ledger.

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
                       sl.entry_price, sl.stop_loss, sl.confidence, sl.status,
                       sl.feature_ts, sl.feature_tf, sl.signal_computed_at,
                       sl.market_price_at_signal, sl.ask_at_signal, sl.bid_at_signal,
                       sl.entry_zone_low, sl.entry_zone_high, sl.zone_valid_at_signal,
                       f.bar, f.i1, f.i3, f.i4, f.i5, f.smc, f.i6
                FROM signal_ledger sl
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
                       entry_price, stop_loss, confidence, status,
                       feature_ts, feature_tf, signal_computed_at,
                       market_price_at_signal, ask_at_signal, bid_at_signal,
                       entry_zone_low, entry_zone_high, zone_valid_at_signal
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

    except Exception as e:
        logger.error("Error fetching signals", symbol=contract, error=str(e))
        raise HTTPException(status_code=500, detail=f"Error fetching signals: {str(e)}") from e
