#!/usr/bin/env python3
"""CompressionAuditor — ground-truth verification for TimescaleDB compression policies.

Filed from todo 233: `alpha_events`/`ensemble_alpha`'s compression policy jobs reported
`last_run_status = 'Success'` on every scheduled run for ~29 days while compressing zero
chunks. `timescaledb_information.job_stats` is the job scheduler's self-report of its own
outcome — it is not ground truth about whether compression actually happened, and this
project's own principle is that a silent wrong answer is worse than a loud crash.

This auditor never reads job_stats. It compares each hypertable's compression policy
(`compress_after`, read from the job's own config) directly against
`timescaledb_information.chunks.is_compressed` — the actual storage state — and self-heals
inline via `CALL run_job(job_id)` (idempotent, DB-only, no external dependency, safe to
retry) for any hypertable found overdue beyond `compress_after` + a grace period. The check
is generic over every hypertable with a `policy_compression` job, present or future — it
would have caught alpha_events/ensemble_alpha automatically, and catches the next one too,
whatever table it turns out to be.

DB-aware (reads/writes TimescaleDB catalog views + compresses chunks). Not a ComputeAgent —
an AuditorAgent, same shape as BarAuditor. Unlike BarAuditor's self-healing (which requires
an external IBKR fetch via a separate consumer service), remediation here is pure in-DB SQL,
so it is performed inline — no Kafka round-trip.

Golden Signals (D-14):
- Traffic: audits_run_total
- Latency: audit_duration_seconds
- Errors: audit_errors_total, remediation_errors_total
- Saturation: overdue_chunks_found_total{hypertable} (counter, cumulative across cycles)

Version: 1.0.0
Last Updated: 2026-08-02
Status: todo 233
"""

from __future__ import annotations

import asyncio
import time as _time
from datetime import timedelta

import _path_bootstrap  # noqa: F401 — project root on sys.path
import asyncpg
from opentelemetry import metrics as _otel_metrics

from src.config.config_service import ConfigService
from src.core.agent.base import BaseDaemon
from src.core.database_manager import create_pool as create_db_pool
from src.core.service_utils import setup_service_logging

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CHECK_INTERVAL_KEY = "infra.compression_auditor.check_interval_seconds"
_GRACE_PERIOD_KEY = "infra.compression_auditor.grace_period_hours"
_DEFAULT_CHECK_INTERVAL_SECONDS = 21600  # 6h — cheap catalog-only query, same-day detection
_DEFAULT_GRACE_PERIOD_HOURS = 24  # must exceed the longest policy schedule_interval (12h)

# Ground-truth drift query: for every hypertable with a compression policy, count chunks
# that are (a) not compressed and (b) older than that table's OWN compress_after threshold
# plus a grace period. No hypertable name is hardcoded — this generalizes to every current
# and future compression policy in the database.
_DRIFT_QUERY = """
SELECT
    j.job_id,
    j.hypertable_name,
    j.config->>'compress_after' AS compress_after,
    count(*) FILTER (
        WHERE NOT c.is_compressed
          AND c.range_end < now() - (j.config->>'compress_after')::interval - $1::interval
    ) AS overdue_chunks
FROM timescaledb_information.jobs j
JOIN timescaledb_information.chunks c ON c.hypertable_name = j.hypertable_name
WHERE j.proc_name = 'policy_compression'
GROUP BY j.job_id, j.hypertable_name, j.config
HAVING count(*) FILTER (
    WHERE NOT c.is_compressed
      AND c.range_end < now() - (j.config->>'compress_after')::interval - $1::interval
) > 0
ORDER BY j.hypertable_name
"""

# ---------------------------------------------------------------------------
# OTel metrics (D-14 Golden Signals, service-local per the two-tier metric pattern)
# ---------------------------------------------------------------------------

_ca_meter = _otel_metrics.get_meter("indicagent")
_AUDITS_RUN = _ca_meter.create_counter(
    "compression_auditor_audits_run_total",
    description="Total audit cycles completed",
)
_AUDIT_DURATION = _ca_meter.create_histogram(
    "compression_auditor_audit_duration_seconds",
    description="Wall-clock time for a full audit cycle",
)
_AUDIT_ERRORS = _ca_meter.create_counter(
    "compression_auditor_audit_errors_total",
    description="Exceptions during audit cycles",
)
_OVERDUE_CHUNKS_FOUND = _ca_meter.create_counter(
    "compression_auditor_overdue_chunks_found_total",
    description="Overdue-uncompressed chunks detected, labeled by hypertable",
)
_REMEDIATION_RUNS = _ca_meter.create_counter(
    "compression_auditor_remediation_runs_total",
    description="CALL run_job() remediation attempts, labeled by hypertable and outcome",
)
_REMEDIATION_ERRORS = _ca_meter.create_counter(
    "compression_auditor_remediation_errors_total",
    description="Exceptions while remediating a hypertable's compression drift",
)


class CompressionAuditor(BaseDaemon):
    """AuditorAgent: detects TimescaleDB compression-policy drift and self-heals inline.

    Runs an audit on startup, then every infra.compression_auditor.check_interval_seconds.
    For each hypertable with a compress_after policy, flags chunks overdue beyond that
    threshold plus a grace period, and remediates via CALL run_job(job_id) — the same
    call this session used to manually fix alpha_events/ensemble_alpha, proven safe and
    idempotent.

    DB-aware (reads timescaledb_information.*, writes via run_job()). Not DB-ignorant.
    """

    def __init__(self) -> None:
        # max_idle_seconds=0: this is a slow periodic sweep (hours, not seconds), not a
        # message-consuming stream processor — the internal stall self-kill watchdog
        # doesn't apply. _record_message_consumed() is still called each cycle purely to
        # keep the agent_last_message_timestamp_seconds liveness gauge meaningful on
        # Grafana; systemd's own WatchdogSec ping stays unconditional at max_idle_seconds=0.
        super().__init__(max_idle_seconds=0)
        setup_service_logging("logs/compression_auditor.log")
        self._db_pool: asyncpg.Pool | None = None
        self._config: ConfigService | None = None
        self._agent_attrs = {"agent": self.name}

    # ------------------------------------------------------------------
    # BaseDaemon interface
    # ------------------------------------------------------------------

    async def _setup(self) -> None:
        """Connect asyncpg pool and ConfigService. No Kafka — pure DB-only auditor."""
        self._db_pool = await create_db_pool(self.settings.database_url, min_size=1, max_size=2)
        self._config = ConfigService(self.settings.database_url, pool=self._db_pool)
        self.logger.info("compression_auditor.setup_complete")

    async def _teardown(self) -> None:
        if self._db_pool is not None:
            await self._db_pool.close()

    async def _run(self) -> None:
        """Main loop: audit on startup, then every check_interval_seconds.

        Uses _stop_event.wait(timeout=...) for interruptible sleep — SIGTERM wakes the
        wait and exits cleanly. Mirrors BarAuditor's loop shape exactly.
        """
        await self._run_audit()

        while self.running:
            interval = await self._config.get(
                _CHECK_INTERVAL_KEY, default=_DEFAULT_CHECK_INTERVAL_SECONDS
            )
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=float(interval))
                break  # stop_event fired — exit loop
            except TimeoutError:
                pass  # normal path: interval elapsed

            if not self.running:
                break
            await self._run_audit()

    # ------------------------------------------------------------------
    # Business logic
    # ------------------------------------------------------------------

    async def _run_audit(self) -> None:
        """Run a single audit cycle: detect compression drift and remediate inline.

        Catches all exceptions to prevent the audit loop from crashing on transient
        failures — same contract as BarAuditor._run_audit().
        """
        try:
            _t0 = _time.monotonic()
            grace_hours = await self._config.get(
                _GRACE_PERIOD_KEY, default=_DEFAULT_GRACE_PERIOD_HOURS
            )
            async with self._db_pool.acquire() as conn:
                rows = await conn.fetch(_DRIFT_QUERY, timedelta(hours=float(grace_hours)))

            for row in rows:
                # Each hypertable is its own failure domain: an anomaly processing one
                # row (metric emission, logging, or remediation) must never prevent the
                # remaining drifted hypertables in the same cycle from being fixed.
                # _remediate() already swallows its own exceptions internally — this
                # try/except is defense-in-depth for anything else in the row body.
                try:
                    hypertable = row["hypertable_name"]
                    job_id = row["job_id"]
                    overdue = row["overdue_chunks"]
                    attrs = {**self._agent_attrs, "hypertable": hypertable}

                    _OVERDUE_CHUNKS_FOUND.add(overdue, attrs)
                    self.logger.warning(
                        "compression_auditor.overdue_chunks_detected",
                        hypertable=hypertable,
                        job_id=job_id,
                        overdue_chunks=overdue,
                        compress_after=row["compress_after"],
                        grace_hours=grace_hours,
                    )
                    await self._remediate(
                        conn_pool=self._db_pool, hypertable=hypertable, job_id=job_id
                    )
                except Exception as row_error:
                    _AUDIT_ERRORS.add(1, self._agent_attrs)
                    self.logger.error(
                        "compression_auditor.row_processing_error",
                        hypertable=row.get("hypertable_name", "unknown"),
                        error=str(row_error),
                    )
                    # Do not re-raise — one hypertable's anomaly must not block the rest

            _AUDIT_DURATION.record(_time.monotonic() - _t0, self._agent_attrs)
            _AUDITS_RUN.add(1, self._agent_attrs)
            self._record_message_consumed()  # liveness gauge only; no stall self-kill (max_idle_seconds=0)
            self.logger.info(
                "compression_auditor.audit_complete",
                hypertables_with_drift=len(rows),
            )

        except Exception as error:
            _AUDIT_ERRORS.add(1, self._agent_attrs)
            self.logger.error("compression_auditor.audit_error", error=str(error))
            # Do not re-raise — audit loop must continue on transient failures

    async def _remediate(self, conn_pool: asyncpg.Pool, hypertable: str, job_id: int) -> None:
        """Directly invoke the hypertable's own compression policy job.

        CALL run_job(job_id) is idempotent and DB-only — proven safe this session on
        alpha_events/ensemble_alpha (compressed 79/81 and 80/81 chunks instantly, zero
        errors). One hypertable's remediation failure must never block another's — each
        call is isolated in its own try/except, same contract as the outer audit cycle.
        """
        attrs = {**self._agent_attrs, "hypertable": hypertable}
        try:
            async with conn_pool.acquire() as conn:
                await conn.execute("CALL run_job($1)", job_id)
            _REMEDIATION_RUNS.add(1, {**attrs, "outcome": "success"})
            self.logger.info(
                "compression_auditor.remediation_complete",
                hypertable=hypertable,
                job_id=job_id,
            )
        except Exception as error:
            _REMEDIATION_RUNS.add(1, {**attrs, "outcome": "error"})
            _REMEDIATION_ERRORS.add(1, attrs)
            self.logger.error(
                "compression_auditor.remediation_error",
                hypertable=hypertable,
                job_id=job_id,
                error=str(error),
            )
            # Do not re-raise — one hypertable's remediation failure must not block others


if __name__ == "__main__":
    asyncio.run(CompressionAuditor().start())
