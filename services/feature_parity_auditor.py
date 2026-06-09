"""FeatureParityAuditor — timer-triggered oneshot for I5 pattern field validation.

Timer-triggered: indicagent-feature-parity-auditor.timer (every 5 minutes).
One-shot: queries intelligence_features for the last hour, checks that expected
pattern_detections JSONB keys are present, emits OTel gauge on violation, exits.

Regression guard for the Phase 117 Wave 1 write-path fix. Catches 100% NULL
fields (count==0 with total>0) within 5 minutes of a recurrence.
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
    FEATURE_PARITY_AUDITS_RUN_TOTAL,
    FEATURE_PARITY_NULL_FIELDS_TOTAL,
    JOB_COMPLETED_TOTAL,
    flush_and_shutdown_metrics,
)

setup_service_logging("logs/feature_parity_auditor.log")
logger = structlog.get_logger(__name__)

_EXPECTED_FIELDS = ["dt_db_confidence", "hs_confidence", "tri_confidence"]
_LOOKBACK = "1 hour"


async def _run_audit(pool: asyncpg.Pool) -> list[str]:
    """Query intelligence_features for the last hour and return a list of 100%-NULL fields.

    Returns the violations list so callers (including unit tests) can inspect it.
    """
    async with pool.acquire() as conn:
        total: int = await conn.fetchval(
            "SELECT COUNT(*) FROM intelligence_features WHERE ts >= NOW() - INTERVAL '1 hour'"
        )

        if total == 0:
            logger.info("feature_parity_audit.no_recent_rows")
            FEATURE_PARITY_NULL_FIELDS_TOTAL.set(0, {})
            FEATURE_PARITY_AUDITS_RUN_TOTAL.add(1, {})
            return []

        violations: list[str] = []
        for field in _EXPECTED_FIELDS:
            count: int = await conn.fetchval(
                "SELECT COUNT(*) FILTER (WHERE pattern_detections ? $1)"
                " FROM intelligence_features WHERE ts >= NOW() - INTERVAL '1 hour'",
                field,
            )
            if count == 0:
                violations.append(field)

    FEATURE_PARITY_NULL_FIELDS_TOTAL.set(len(violations), {})
    FEATURE_PARITY_AUDITS_RUN_TOTAL.add(1, {})

    if violations:
        logger.error(
            "feature_parity_audit.violations_found",
            fields=violations,
            total_rows=total,
        )
    else:
        logger.info("feature_parity_audit.clean", total_rows=total)

    return violations


async def _amain() -> None:
    settings = Settings()
    pool = await create_db_pool(settings.database_url, min_size=2, max_size=5)
    try:
        await _run_audit(pool)
    finally:
        await pool.close()


def main() -> None:
    """Run the feature parity auditor once and emit a completion counter before exit."""
    try:
        asyncio.run(_amain())
        JOB_COMPLETED_TOTAL.add(1, {"job": "feature-parity-auditor", "status": "success"})
    except Exception as error:
        JOB_COMPLETED_TOTAL.add(1, {"job": "feature-parity-auditor", "status": "failure"})
        raise error
    finally:
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    main()
