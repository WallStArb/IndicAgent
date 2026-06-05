"""
PgvectorRegimeBackend — Tier-5 regime transition priors from memory_regime_transitions.

Queries the single open row (ts_end IS NULL) for a (symbol, timeframe) pair and
computes elapsed_bars at query time from (NOW() - ts_start). The elapsed value
is never stored — it would stale immediately (D-17).

Design decisions:
    D-17: elapsed_bars computed at query time; never stored in the DB.
    D-17: win_rate / transition_probs are None when sample counts < 30 (C-03).
    D-19: 40ms asyncio.wait_for; returns None on timeout/error, never raises.

Phase: 097 (agent-memory)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import asyncpg
import structlog

from src.core.memory.types import RegimeHistory

log = structlog.get_logger(__name__)

_DEFAULT_TIMEOUT_MS = 40

# Timeframe string to bar duration in seconds — used to compute elapsed_bars.
# This is a Ring 0 lookup; no dependency on src.core.service_utils to avoid
# circular imports. Extend as new timeframes are added to the platform.
_TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "10m": 600,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "1d": 86400,
}


class PgvectorRegimeBackend:
    """RegimeBackend implementation against memory_regime_transitions.

    Returns the currently open regime period for a (symbol, timeframe) pair.
    The UNIQUE INDEX WHERE ts_end IS NULL on the table guarantees at most one
    open period — this backend relies on that structural guarantee.

    elapsed_bars is computed at query time from (NOW() - ts_start) divided by
    the bar duration for the given timeframe. Unknown timeframes fall back to 60s.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> None:
        self._pool = pool
        self._timeout_ms = timeout_ms

    async def get_regime_history(
        self,
        symbol: str,
        timeframe: str,
    ) -> RegimeHistory | None:
        """Retrieve Markov priors and duration stats for the current regime.

        Queries the open row (ts_end IS NULL) for (symbol, timeframe).
        Computes elapsed_bars at query time from (NOW() - ts_start).
        transition_probs and win_rate are None when below the N>=30 gate (C-03).

        Args:
            symbol: Instrument symbol (e.g. 'ES', 'MES').
            timeframe: Bar timeframe string (e.g. '5m', '15m').

        Returns:
            RegimeHistory for the currently open regime. None when no open
            period exists, on timeout, or on any exception. Never raises (D-19).
        """
        try:
            return await asyncio.wait_for(
                self._get_regime_history_inner(symbol, timeframe),
                timeout=self._timeout_ms / 1000.0,
            )
        except TimeoutError:
            log.warning(
                "regime_history_timeout",
                symbol=symbol,
                timeframe=timeframe,
                timeout_ms=self._timeout_ms,
            )
            return None
        except Exception as error:
            log.warning(
                "regime_history_error",
                symbol=symbol,
                timeframe=timeframe,
                error=str(error),
                error_type=type(error).__name__,
            )
            return None

    async def _get_regime_history_inner(
        self,
        symbol: str,
        timeframe: str,
    ) -> RegimeHistory | None:
        """Core regime query — runs inside the wait_for wrapper."""
        sql = """
            SELECT
                symbol,
                timeframe,
                to_regime        AS current_regime,
                ts_start,
                win_rate,
                avg_pnl_r,
                transition_probs,
                transition_n,
                duration_median_bars,
                duration_p25_bars,
                duration_p75_bars,
                signal_count
            FROM memory_regime_transitions
            WHERE symbol    = $1
              AND timeframe = $2
              AND ts_end IS NULL
            LIMIT 1
        """
        row = await self._pool.fetchrow(sql, symbol, timeframe)
        if row is None:
            return None

        return self._row_to_history(row, timeframe)

    @staticmethod
    def _row_to_history(row: asyncpg.Record, timeframe: str) -> RegimeHistory:
        """Map a DB row to a RegimeHistory frozen dataclass.

        elapsed_bars is computed at call time from (NOW() - ts_start) divided
        by the bar duration for the timeframe. This ensures elapsed_bars is
        always fresh — it is never read from the DB (D-17).

        transition_probs and win_rate are passed through as-is: the DB
        stores NULL when sample counts are below the N>=30 gate (C-03), and
        asyncpg returns None for SQL NULL values on JSONB and FLOAT columns.
        """
        ts_start: datetime = row["ts_start"]

        # Compute elapsed_bars at query time (D-17).
        now_utc = datetime.now(UTC)
        # ts_start from asyncpg is timezone-aware (timestamptz → datetime with tzinfo).
        bar_seconds = _TIMEFRAME_SECONDS.get(timeframe, 60)
        elapsed_seconds = max(0.0, (now_utc - ts_start).total_seconds())
        elapsed_bars = int(elapsed_seconds / bar_seconds)

        # transition_probs: asyncpg returns dict for JSONB, None for SQL NULL.
        # C-03: None when transition_n < 30 — the DB stores NULL; we pass through.
        transition_probs: dict | None = row["transition_probs"]
        transition_n: int = row["transition_n"] or 0

        # win_rate: None when signal_count < 30 (C-03 discipline on satellite table).
        win_rate: float | None = row["win_rate"]

        return RegimeHistory(
            symbol=row["symbol"],
            timeframe=row["timeframe"],
            current_regime=str(row["current_regime"]),
            ts_start=ts_start,
            elapsed_bars=elapsed_bars,
            duration_median_bars=row["duration_median_bars"] or 0,
            duration_p25_bars=row["duration_p25_bars"] or 0,
            duration_p75_bars=row["duration_p75_bars"] or 0,
            transition_probs=transition_probs,
            transition_n=transition_n,
            win_rate=win_rate,
            avg_pnl_r=row["avg_pnl_r"] or 0.0,
        )
