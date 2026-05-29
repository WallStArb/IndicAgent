"""Remediation ledger — durable persistence + idempotency + rate-limit queries.

All three public query methods (alert_already_processed, attempts_in_last_hour,
get_success_rate) are backed by indexed queries on remediation_ledger so that
idempotency and rate limiting survive process restarts.

MV refresh (refresh_success_rates) is called periodically by the engine background
task. Requires the CONCURRENTLY-capable unique index idx_remediation_success_rates_action.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import asyncpg

from src.observability.metrics import (
    REMEDIATION_ATTEMPT_TOTAL,
    REMEDIATION_DURATION_SECONDS,
    REMEDIATION_SUCCESS_TOTAL,
)


@dataclass
class RemediationRecord:
    timestamp: datetime
    remediation_id: str
    alert_id: str
    state_variable: str
    pre_value: float | None
    post_value: float | None
    target_value: float
    action: str
    outcome: str  # success | partial | failed | no_action
    duration_ms: int
    error_message: str | None
    changed_by: str
    reason: str | None


class RemediationLedger:
    """Write and query the remediation_ledger hypertable."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def record(self, record: RemediationRecord) -> None:
        """Insert a remediation record and emit OTel metrics."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO remediation_ledger "
                "(timestamp, remediation_id, alert_id, state_variable, "
                "pre_value, post_value, target_value, action, outcome, "
                "duration_ms, error_message, changed_by, reason) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)",
                record.timestamp,
                record.remediation_id,
                record.alert_id,
                record.state_variable,
                record.pre_value,
                record.post_value,
                record.target_value,
                record.action,
                record.outcome,
                record.duration_ms,
                record.error_message,
                record.changed_by,
                record.reason,
            )
        REMEDIATION_ATTEMPT_TOTAL.add(
            1,
            {
                "state_variable": record.state_variable,
                "action": record.action,
                "outcome": record.outcome,
            },
        )
        if record.outcome == "success":
            REMEDIATION_SUCCESS_TOTAL.add(1, {"action": record.action})
        REMEDIATION_DURATION_SECONDS.record(
            record.duration_ms / 1000.0,
            {"action": record.action, "outcome": record.outcome},
        )

    async def alert_already_processed(
        self, alert_id: str, within: timedelta = timedelta(hours=24)
    ) -> bool:
        """Durable idempotency check: has this alert_id been acted on within window?

        Uses idx_remediation_alert_time index for sub-ms lookup. Replaces any
        in-memory set that would be lost on process restart.
        """
        cutoff = datetime.now(UTC) - within
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM remediation_ledger " "WHERE alert_id=$1 AND timestamp >= $2 LIMIT 1",
                alert_id,
                cutoff,
            )
        return row is not None

    async def attempts_in_last_hour(self, action: str) -> int:
        """Durable rate-limit count: how many times was action executed in last hour?

        Uses idx_remediation_action_time index for efficient time-range scan.
        Replaces any in-memory counter that would reset on process restart.
        Excludes no_action outcomes to count only actual execution attempts.
        """
        cutoff = datetime.now(UTC) - timedelta(hours=1)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM remediation_ledger "
                "WHERE action=$1 AND timestamp >= $2 AND outcome != 'no_action'",
                action,
                cutoff,
            )
        return int(row["n"]) if row else 0

    async def get_success_rate(self, action: str) -> tuple[float, int]:
        """Return (success_rate, attempt_count) from remediation_success_rates MV.

        Returns (0.0, 0) if no MV row exists for this action (never attempted).
        MV is refreshed periodically by refresh_success_rates().
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT success_rate, attempt_count "
                "FROM remediation_success_rates WHERE action=$1",
                action,
            )
        if not row:
            return (0.0, 0)
        return (float(row["success_rate"] or 0.0), int(row["attempt_count"] or 0))

    async def refresh_success_rates(self) -> None:
        """Refresh the remediation_success_rates MV without locking readers.

        CONCURRENTLY requires the unique index idx_remediation_success_rates_action.
        Call periodically (every 5 min) from engine background task or external timer.
        """
        async with self._pool.acquire() as conn:
            await conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY remediation_success_rates")
