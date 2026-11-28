"""Shared helper for writing to the generic `integrity_monitor` observability fact
table (schema: production/migrations/211_integrity_monitor.sql).

Ring 0 (no domain vocabulary: an observability fact table with a monitor_type/subject/
metric_name/metric_value shape is a generic concept). The INSERT and its composite
`ON CONFLICT (monitor_type, training_window_end, metric_name, COALESCE(subject, ''),
evaluated_at) DO NOTHING` key are defined here once (todo 150), so no call site drifts from
the real unique index.

Guard behavior: on failure, log a warning and return, never raise. A fact recorded here
is about a primary result that already exists elsewhere; a failure writing the audit
trail must never look like (or cause) a failure of that primary result.

No commit parameter: asyncpg connections autocommit each statement outside an explicit
`conn.transaction()` block.

idempotency_check=False by default: the DB-level UNIQUE index only catches an exact-instant
duplicate insert, not a rerun of the same training_window_end hours or days later
(evaluated_at defaults to now() and is part of that key). It defaults off because some facts
are meant to repeat per window: vocabulary_drift.py records one fact per run for calibration
history. Callers with nothing upstream deduping reruns pass True.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import structlog

_logger = structlog.get_logger(__name__)

# Shared INSERT shape: the one place that defines the composite ON CONFLICT key.
INTEGRITY_MONITOR_INSERT_SQL = """
INSERT INTO integrity_monitor
    (monitor_type, subject, metric_name, metric_value, threshold_value, passed, training_window_end)
VALUES ($1, $2, $3, $4, $5, $6, $7)
ON CONFLICT (monitor_type, training_window_end, metric_name, COALESCE(subject, ''), evaluated_at) DO NOTHING
"""

_IDEMPOTENCY_PRECHECK_SQL = """
SELECT 1 FROM integrity_monitor
WHERE monitor_type = $1
  AND training_window_end = $2
  AND metric_name = $3
LIMIT 1
"""


async def emit_integrity_fact_async(
    conn: Any,
    monitor_type: str,
    subject: str | None,
    metric_name: str,
    metric_value: float | None,
    threshold_value: float | None,
    passed: bool,
    training_window_end: Any,
    *,
    idempotency_check: bool = False,
) -> None:
    """One guarded INSERT; see the module docstring for the guard and idempotency check."""
    try:
        if idempotency_check:
            exists = await conn.fetchval(
                _IDEMPOTENCY_PRECHECK_SQL,
                monitor_type,
                training_window_end,
                metric_name,
            )
            if exists is not None:
                _logger.info(
                    "integrity_monitor.emit_skipped_already_ran",
                    monitor_type=monitor_type,
                    metric_name=metric_name,
                    training_window_end=str(training_window_end),
                )
                return

        await conn.execute(
            INTEGRITY_MONITOR_INSERT_SQL,
            monitor_type,
            subject,
            metric_name,
            metric_value,
            threshold_value,
            passed,
            training_window_end,
        )
    except Exception as error:
        _logger.warning(
            "integrity_monitor.emit_failed",
            monitor_type=monitor_type,
            metric_name=metric_name,
            error=str(error),
        )


async def emit_integrity_facts_async(
    conn: Any,
    facts: Sequence[tuple[str, str | None, str, float | None, float | None, bool, Any]],
) -> None:
    """Write many facts in one round trip: each tuple is the positional arguments of
    `emit_integrity_fact_async` after `conn` (monitor_type, subject, metric_name,
    metric_value, threshold_value, passed, training_window_end), with no idempotency check.

    Same guard: never raises. `executemany` is one implicit transaction, so a failing row
    rolls the batch back; the facts are then written one by one through
    `emit_integrity_fact_async`, so a bad fact costs only itself, as before batching. The
    rows the batch inserts share one `evaluated_at` (the transaction's now()); the unique key
    still differs per subject and metric.
    """
    if not facts:
        return
    try:
        await conn.executemany(INTEGRITY_MONITOR_INSERT_SQL, facts)
    except Exception as error:
        _logger.warning(
            "integrity_monitor.emit_batch_failed",
            n_facts=len(facts),
            error=str(error),
        )
        for fact in facts:
            await emit_integrity_fact_async(conn, *fact)
