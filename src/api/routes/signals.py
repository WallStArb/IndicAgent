"""
Signal History API Routes

Provides access to signal_ledger with optional JOIN to intelligence_features
for full feature context at signal time.
"""

import json
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from ...core.database_manager import DatabaseManager
from ..dependencies import get_db_manager

logger = structlog.get_logger(__name__)

router = APIRouter()


def _resolve_contract(symbol: str) -> str:
    """Map base symbol (ES) to active contract code (ESH6)."""
    if any(ch.isdigit() for ch in symbol):
        return symbol
    from ...config.settings import Settings

    settings = Settings()
    for c in settings.contracts:
        if c.base == symbol:
            return c.symbol
    return symbol


def _parse_jsonb(value: Any) -> Any:
    """Parse asyncpg JSONB string to dict. Returns None if value is None."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return None
    return value


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
            if row.get("market_price_at_signal") is not None else None
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
                "bar": _parse_jsonb(row["bar"]),
                "i1": _parse_jsonb(row["i1"]),
                "i3": _parse_jsonb(row["i3"]),
                "i4": _parse_jsonb(row["i4"]),
                "i5": _parse_jsonb(row["i5"]),
                "smc": _parse_jsonb(row["smc"]),
                "i6": _parse_jsonb(row["i6"]),
            }
    return signal


# Outcome classes considered wins for summary win_rate computation
_WIN_OUTCOMES = frozenset({"target_1", "target_1_2", "target_full"})


@router.get("/signals/recent")
async def get_recent_signals(
    symbol: str = Query(..., description="Symbol, e.g. ESH6 or ES"),
    timeframe: str | None = Query(None, description="Filter by timeframe, e.g. 1m"),
    limit: int = Query(20, ge=1, le=100, description="Max signals to return"),
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> dict[str, Any]:
    """
    Recent signals from signal_ledger for drill panel history.

    Annotated with 30d setup performance from setup_performance table.
    Includes aggregate summary over the returned window.
    """
    contract = _resolve_contract(symbol)
    try:
        main_query = """
            SELECT
                sl.signal_id,
                sl.setup_plugin,
                sl.signal_type,
                sl.direction,
                sl.entry_price,
                sl.stop_loss,
                sl.confidence,
                sl.status,
                sl.outcome,
                sl.exit_price,
                sl.pnl_r,
                sl.signal_computed_at,
                sl.timeframe,
                sp.win_rate   AS setup_win_rate,
                sp.avg_pnl_r  AS setup_avg_pnl_r
            FROM signal_ledger sl
            LEFT JOIN setup_performance sp ON sp.setup_type = sl.signal_type
            WHERE sl.symbol = $1
              AND ($2::text IS NULL OR sl.timeframe = $2)
            ORDER BY sl.signal_computed_at DESC
            LIMIT $3
        """
        rows = await db_manager.fetch(main_query, contract, timeframe, limit)

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
            WHERE symbol = $1
              AND ($2::text IS NULL OR timeframe = $2)
        """
        summary_row = await db_manager.fetchrow(summary_query, contract, timeframe)

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
                "setup_win_rate": _f(row["setup_win_rate"]),
                "setup_avg_pnl_r": _f(row["setup_avg_pnl_r"]),
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
        logger.error("Error fetching recent signals", symbol=contract, error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Error fetching recent signals: {str(e)}"
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
