"""Quality Floor Bootstrap — oneshot helper for empirical confidence floor.

DAG compliance: This script runs OUTSIDE the pipeline daemon (DAG Invariant #3).
It queries signal_ledger once at system startup and writes a single float to
.pipeline_quality_floor in the project root. The pipeline daemon reads the floor
file at startup via quality_gate.load_quality_floor() — no inline DB access.

Usage:
    python services/quality_floor_bootstrap.py

Invocation strategy:
    Run as a systemd ExecStartPre= step before indicagent-intelligence-pipeline.service,
    or run manually before starting the pipeline daemon. Example systemd unit:

        [Service]
        ExecStartPre=/path/to/.venv/bin/python services/quality_floor_bootstrap.py
        ExecStart=...indicagent-intelligence-pipeline...

Floor file: .pipeline_quality_floor (project root, single float on one line).
Default: 0.12 (D-05 spec default when total_outcomes < 500 or query fails).

Win-rate query: finds lowest confidence bucket where win_rate >= 0.50,
filtered to feature_schema_version >= 2 (clean data only). If < 500 total
outcomes with feature_schema_version >= 2, outputs the default 0.12.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Bootstrap path so this script can be run from the project root
_here = Path(__file__).resolve().parent
_project_root = _here.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import structlog  # noqa: E402

from src.config.settings import Settings  # noqa: E402
from src.core.database_manager import DatabaseManager  # noqa: E402
from src.observability.metrics import flush_and_shutdown_metrics  # noqa: E402

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)

_log = structlog.get_logger(__name__)

# Output path: project root / .pipeline_quality_floor
FLOOR_FILE_PATH = _project_root / ".pipeline_quality_floor"
DEFAULT_FLOOR = 0.12
MIN_OUTCOMES = 500  # D-05: if fewer outcomes, use default
BUCKET_SIZE = 0.05  # 5% confidence buckets for win-rate analysis


async def compute_floor(db_manager: DatabaseManager) -> float:
    """Query signal_ledger for the empirical confidence floor.

    Returns the lowest confidence bucket (bucket_lower) where win_rate >= 0.50.
    Falls back to DEFAULT_FLOOR when:
    - fewer than MIN_OUTCOMES total resolved outcomes with feature_schema_version >= 2
    - no bucket meets the win_rate >= 0.50 threshold
    - any query error

    Parameters
    ----------
    db_manager:
        Initialized DatabaseManager instance with a live connection pool.

    Returns
    -------
    float
        The empirical floor, rounded to 4 decimal places.
    """
    try:
        # Count total eligible outcomes (clean data only)
        count_rows = await db_manager.execute_query(
            """
            SELECT COUNT(*) AS total
            FROM signal_ledger
            WHERE feature_schema_version >= 2
              AND outcome IS NOT NULL
              AND pnl_r IS NOT NULL
            """,
        )
        total = int(count_rows[0]["total"]) if count_rows else 0

        if total < MIN_OUTCOMES:
            _log.info(
                "quality_floor_bootstrap.insufficient_data",
                total_outcomes=total,
                min_required=MIN_OUTCOMES,
                floor=DEFAULT_FLOOR,
            )
            return DEFAULT_FLOOR

        # Compute win rate per confidence bucket (5% buckets)
        bucket_rows = await db_manager.execute_query(
            """
            SELECT
                FLOOR(calibrated_confidence / $1) * $1 AS bucket_lower,
                COUNT(*) AS n,
                SUM(CASE WHEN pnl_r > 0 THEN 1 ELSE 0 END)::float / COUNT(*) AS win_rate
            FROM signal_ledger
            WHERE feature_schema_version >= 2
              AND outcome IS NOT NULL
              AND pnl_r IS NOT NULL
              AND calibrated_confidence IS NOT NULL
            GROUP BY 1
            ORDER BY 1 ASC
            """,
            BUCKET_SIZE,
        )

        if not bucket_rows:
            _log.warning(
                "quality_floor_bootstrap.no_buckets",
                floor=DEFAULT_FLOOR,
            )
            return DEFAULT_FLOOR

        # Find the lowest bucket where win_rate >= 0.50
        for row in bucket_rows:
            bucket_lower = float(row["bucket_lower"])
            win_rate = float(row["win_rate"])
            if win_rate >= 0.50:
                floor = round(bucket_lower, 4)
                _log.info(
                    "quality_floor_bootstrap.floor_derived",
                    floor=floor,
                    win_rate=win_rate,
                    n=row["n"],
                    total_outcomes=total,
                )
                return floor

        _log.warning(
            "quality_floor_bootstrap.no_winning_bucket",
            n_buckets=len(bucket_rows),
            floor=DEFAULT_FLOOR,
        )
        return DEFAULT_FLOOR

    except Exception as error:  # noqa: BLE001
        _log.error(
            "quality_floor_bootstrap.query_failed",
            error=str(error),
            floor=DEFAULT_FLOOR,
        )
        return DEFAULT_FLOOR


async def main() -> None:
    """Run the bootstrap query and write the floor to FLOOR_FILE_PATH."""
    settings = Settings()
    db_manager = DatabaseManager(settings.database_url)
    try:
        await db_manager.initialize()
        floor = await compute_floor(db_manager)
        FLOOR_FILE_PATH.write_text(str(floor))
        _log.info(
            "quality_floor_bootstrap.written",
            floor=floor,
            path=str(FLOOR_FILE_PATH),
        )
    finally:
        await db_manager.close()
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    asyncio.run(main())
