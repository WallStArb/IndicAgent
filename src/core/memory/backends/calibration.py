"""
PgvectorCalibrationBackend — Tier-2 calibration stats from memory_calibration_promoted.

Reads ONLY from memory_calibration_promoted (never raw or labeled episode tables).
The physical table separation is the structural guarantee — no application-layer
view or filter bridges the raw→promoted boundary (D-03).

Design decisions:
    D-19: 40ms asyncio.wait_for; returns None on timeout/error, never raises.
    D-20: correction_factor is None when correction_factor_stable is False.
    D-03: promoted-table-only reads; quarantined cohorts excluded via index.
    D-F3 (CalibrationBackend Protocol): get_partial_sample_n() for cold-start path.

Phase: 097 (agent-memory)
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import asyncpg
import structlog

from src.core.memory.types import CalibrationStats

log = structlog.get_logger(__name__)

_DEFAULT_TIMEOUT_MS = 40


class PgvectorCalibrationBackend:
    """CalibrationBackend implementation reading from memory_calibration_promoted.

    get_calibration(): reads the latest non-quarantined promoted row for a cohort.
    get_partial_sample_n(): counts labeled episodes below the N>=30 gate (cold-start).

    Both methods wrap DB calls in asyncio.wait_for and return None/0 on any
    error — agents are never blocked by calibration subsystem failures.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> None:
        self._pool = pool
        self._timeout_ms = timeout_ms

    async def get_calibration(
        self,
        agent_id: str,
        symbol: str,
        hmm_regime: str,
        entry_type: str,
        regime_epoch: int,
    ) -> CalibrationStats | None:
        """Retrieve the latest promoted calibration stats for a cohort.

        Reads from memory_calibration_promoted only (D-03). Quarantined cohorts
        are excluded (WHERE feedback_loop_quarantine = FALSE). Uses the
        mem_cal_cohort_latest partial index for efficient lookup.

        Args:
            agent_id: Agent whose calibration stats are requested.
            symbol: Instrument symbol cohort dimension.
            hmm_regime: HMM regime cohort dimension.
            entry_type: Entry type cohort dimension.
            regime_epoch: Distributional epoch — matches C-01 column.

        Returns:
            CalibrationStats(bootstrapped=True) if a promoted row exists.
            None when no row found, on timeout, or on any exception.
            Never raises (D-19).
        """
        try:
            return await asyncio.wait_for(
                self._get_calibration_inner(agent_id, symbol, hmm_regime, entry_type, regime_epoch),
                timeout=self._timeout_ms / 1000.0,
            )
        except TimeoutError:
            log.warning(
                "calibration_get_timeout",
                agent_id=agent_id,
                symbol=symbol,
                timeout_ms=self._timeout_ms,
            )
            return None
        except Exception as error:
            log.warning(
                "calibration_get_error",
                agent_id=agent_id,
                symbol=symbol,
                error=str(error),
                error_type=type(error).__name__,
            )
            return None

    async def _get_calibration_inner(
        self,
        agent_id: str,
        symbol: str,
        hmm_regime: str,
        entry_type: str,
        regime_epoch: int,
    ) -> CalibrationStats | None:
        """Core calibration fetch — runs inside the wait_for wrapper."""
        sql = """
            SELECT
                agent_id,
                symbol,
                hmm_regime,
                entry_type,
                regime_epoch,
                sample_n,
                mean_prediction,
                actual_rate,
                calibration_error,
                calibration_error_variance,
                correction_factor,
                correction_factor_stable,
                brier_score,
                base_rate,
                skill_score,
                information_coefficient,
                ic_p_value,
                ci_lower,
                ci_upper,
                p_value_corrected,
                n_eligible,
                p_signal,
                feedback_loop_quarantine,
                quarantine_review_at,
                promoted_at,
                window_start,
                window_end
            FROM memory_calibration_promoted
            WHERE agent_id   = $1
              AND symbol     = $2
              AND hmm_regime = $3
              AND entry_type = $4
              AND regime_epoch = $5
              AND feedback_loop_quarantine = FALSE
            ORDER BY promoted_at DESC
            LIMIT 1
        """
        row = await self._pool.fetchrow(sql, agent_id, symbol, hmm_regime, entry_type, regime_epoch)
        if row is None:
            return None

        return self._row_to_stats(row, bootstrapped=True)

    async def get_partial_sample_n(
        self,
        agent_id: str,
        symbol: str,
        hmm_regime: str,
        entry_type: str,
        regime_epoch: int,
    ) -> int:
        """Count labeled episodes for a cohort below the N>=30 promotion gate.

        Used by MemoryClient on the cold-start path (D-F3): if partial_n > 0
        but no promoted row exists, the agent knows calibration is accumulating.

        Reads from memory_episodes_labeled (not the promoted table). This is the
        only CalibrationBackend method that may read from the labeled table.

        Returns:
            Episode count (>= 0). Returns 0 on timeout or any exception.
            Never raises.
        """
        try:
            return await asyncio.wait_for(
                self._get_partial_sample_n_inner(
                    agent_id, symbol, hmm_regime, entry_type, regime_epoch
                ),
                timeout=self._timeout_ms / 1000.0,
            )
        except TimeoutError:
            log.warning(
                "calibration_partial_n_timeout",
                agent_id=agent_id,
                symbol=symbol,
                timeout_ms=self._timeout_ms,
            )
            return 0
        except Exception as error:
            log.warning(
                "calibration_partial_n_error",
                agent_id=agent_id,
                symbol=symbol,
                error=str(error),
                error_type=type(error).__name__,
            )
            return 0

    async def _get_partial_sample_n_inner(
        self,
        agent_id: str,
        symbol: str,
        hmm_regime: str,
        entry_type: str,
        regime_epoch: int,
    ) -> int:
        """Core count query — runs inside the wait_for wrapper."""
        sql = """
            SELECT COUNT(*)
            FROM memory_episodes_labeled
            WHERE agent_id    = $1
              AND symbol      = $2
              AND hmm_regime  = $3
              AND entry_type  = $4
              AND regime_epoch = $5
              AND outcome IS NOT NULL
        """
        result = await self._pool.fetchval(
            sql, agent_id, symbol, hmm_regime, entry_type, regime_epoch
        )
        return int(result) if result is not None else 0

    @staticmethod
    def _row_to_stats(row: asyncpg.Record, bootstrapped: bool) -> CalibrationStats:
        """Map a DB row to a CalibrationStats frozen dataclass.

        D-20: correction_factor is set to None when correction_factor_stable
        is False — agents must gate on correction_factor_stable before applying
        the factor; returning it unconditionally would be misleading.
        """
        correction_factor_stable: bool = row["correction_factor_stable"]

        # D-20: None when not stable — do not expose an unstable correction factor.
        correction_factor: float | None = (
            row["correction_factor"] if correction_factor_stable else None
        )

        return CalibrationStats(
            agent_id=row["agent_id"],
            symbol=row["symbol"] or "",
            hmm_regime=row["hmm_regime"] or "",
            entry_type=row["entry_type"] or "",
            regime_epoch=row["regime_epoch"],
            sample_n=row["sample_n"],
            mean_prediction=row["mean_prediction"],
            actual_rate=row["actual_rate"],
            calibration_error=row["calibration_error"],
            calibration_error_variance=row["calibration_error_variance"],
            correction_factor=correction_factor,
            correction_factor_stable=correction_factor_stable,
            bootstrapped=bootstrapped,
            skill_score=row["skill_score"],
            information_coefficient=row["information_coefficient"],
            ic_p_value=row["ic_p_value"],
            brier_score=row["brier_score"],
            base_rate=row["base_rate"],
            ci_lower=row["ci_lower"],
            ci_upper=row["ci_upper"],
            p_value_corrected=row["p_value_corrected"],
            p_signal=row["p_signal"],
            feedback_loop_quarantine=row["feedback_loop_quarantine"],
            quarantine_review_at=_as_dt(row["quarantine_review_at"]),
            promoted_at=_as_dt(row["promoted_at"]),
            window_start=_as_dt(row["window_start"]),
            window_end=_as_dt(row["window_end"]),
        )


def _as_dt(value: datetime | None) -> datetime | None:
    """Pass through datetime from asyncpg (already datetime); guard None."""
    return value  # asyncpg returns datetime objects directly for TIMESTAMPTZ
