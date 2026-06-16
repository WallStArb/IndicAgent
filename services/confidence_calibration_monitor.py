"""ConfidenceCalibrationMonitor — timer-triggered oneshot.

Measures, per setup_plugin, the Pearson correlation between cis_score and
aggregator selection (was_selected) over the last 7 days, gated at N >= 100.

Framing: the correlation measures aggregator-selection predictiveness, NOT
profitability.  cis_score is an input to the aggregator; was_selected is the
aggregator output.  Alerting when correlation < 0.3 means the confidence
formula is not predictive of aggregator selection — not a profitability claim.

Timer-triggered: indicagent-confidence-calibration-monitor.timer (every 30 min).
One-shot: queries signal_ledger, publishes OTel gauges/counters, exits.
"""

from __future__ import annotations

import asyncio

import _path_bootstrap  # noqa: F401 — project root on sys.path
import asyncpg
import structlog

from src.config.settings import Settings
from src.core.database_manager import create_pool as create_db_pool
from src.core.service_utils import setup_service_logging
from src.observability.metrics import (
    CONFIDENCE_CALIBRATION_ALERTS_TOTAL,
    JOB_COMPLETED_TOTAL,
    SIGNAL_CONFIDENCE_CALIBRATION,
    flush_and_shutdown_metrics,
)

setup_service_logging("logs/confidence_calibration_monitor.log")
logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

_MIN_N = 100
_CALIBRATION_ALERT_THRESHOLD = 0.3


# ---------------------------------------------------------------------------
# Core audit logic
# ---------------------------------------------------------------------------


async def _run_audit(pool: asyncpg.Pool) -> list[dict]:
    """Compute per-setup calibration correlations and publish OTel metrics.

    Returns the processed rows as a list of dicts for unit-test introspection.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                setup_plugin,
                CORR(cis_score, was_selected::int)::float AS calibration,
                COUNT(*) AS n
            FROM signal_ledger
            WHERE timestamp >= NOW() - INTERVAL '7 days'
              AND NOT is_shadow
              AND cis_score IS NOT NULL
            GROUP BY setup_plugin
            HAVING COUNT(*) >= 100
            ORDER BY calibration ASC
            """,
        )

    processed: list[dict] = []
    for row in rows:
        plugin = row["setup_plugin"]
        calibration = row["calibration"]
        n = int(row["n"])

        calibration_value = calibration if calibration is not None else 0.0
        SIGNAL_CONFIDENCE_CALIBRATION.set(calibration_value, {"setup_plugin": plugin})

        if calibration is not None and calibration < _CALIBRATION_ALERT_THRESHOLD and n >= _MIN_N:
            CONFIDENCE_CALIBRATION_ALERTS_TOTAL.add(1, {"setup_plugin": plugin})
            logger.warning(
                "confidence_calibration.not_predictive_of_selection",
                plugin=plugin,
                calibration=round(calibration, 4),
                n=n,
            )
        else:
            logger.info(
                "confidence_calibration.result",
                plugin=plugin,
                calibration=round(calibration, 4) if calibration is not None else None,
                n=n,
            )

        processed.append({"setup_plugin": plugin, "calibration": calibration, "n": n})

    logger.info("confidence_calibration.audit_complete", setup_count=len(processed))
    return processed


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _amain() -> None:
    settings = Settings()
    pool = await create_db_pool(settings.database_url, min_size=2, max_size=5)
    try:
        await _run_audit(pool)
    finally:
        await pool.close()


def main() -> None:
    """Run the confidence calibration monitor once and emit a completion counter before exit."""
    try:
        asyncio.run(_amain())
        JOB_COMPLETED_TOTAL.add(1, {"job": "confidence-calibration-monitor", "status": "success"})
    except Exception as error:
        JOB_COMPLETED_TOTAL.add(1, {"job": "confidence-calibration-monitor", "status": "failure"})
        raise error
    finally:
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    main()
