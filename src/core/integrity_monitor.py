"""Shared helper for writing to the generic `integrity_monitor` observability fact
table (schema: production/migrations/211_integrity_monitor.sql).

Ring 0 (no domain vocabulary -- "an observability fact table with a monitor_type/
subject/metric_name/metric_value shape" is a generic concept, not alpha/IC-specific).
Before this extraction (todo 150), the exact INSERT + composite `ON CONFLICT
(monitor_type, training_window_end, metric_name, COALESCE(subject, ''), evaluated_at)
DO NOTHING` statement shape was hand-copied at 4 independent call sites --
services/ic_engine.py (x2), src/config/vocabulary_drift.py, services/
forward_return_writer.py -- a correctness risk (a future copy silently drifting from
the real unique index), not just a style complaint.

Two variants, mirroring the sync/async split already established elsewhere in this
codebase (e.g. FeatureRegistryService.record_transition_sync vs. its async sibling):
callers on a plain psycopg2 connection (ic_engine.py, forward_return_writer.py -- both
sync, argparse-style batch scripts) use emit_integrity_fact_sync(); callers on an
asyncpg connection (vocabulary_drift.py) use emit_integrity_fact_async().

Guard behavior lives here, once: on failure, log a warning and return -- never raise.
Every fact this table records is ABOUT a primary write that already committed
successfully elsewhere; a failure writing the audit trail must never look like (or
cause) a failure of that primary write. This was previously re-derived independently
at each call site (forward_return_writer.py's try/except) or relied on an outer
wrapping try/except one or more call frames up (ic_engine.py's `_run_lifecycle_hook`
callers) -- now callers get it for free.

commit=False by default: several existing call sites share their connection with
other statements under a single deferred commit point (ic_engine.py's
_apply_feature_transitions commits once at the end of _run_lifecycle_hook, after this
INSERT and several others) -- an unconditional commit() here would break that
invariant. Pass commit=True only for a call site that owns its own transaction
boundary and wants the fact durable immediately (forward_return_writer.py's
price_sanity fact).

idempotency_check=False by default: the DB-level UNIQUE index (keyed on
monitor_type/training_window_end/metric_name/subject/evaluated_at) only catches an
exact-instant duplicate insert, not a rerun of the same training_window_end
hours/days later (evaluated_at defaults to now() and is part of that key). Some
callers already sit behind an equivalent pre-check one call frame up
(ic_engine.py's `_run_lifecycle_hook` Step 0 checks the same monitor_type +
training_window_end before calling into either of its two emit sites) -- for those,
a second pre-check here would be redundant, not wrong, so it defaults off rather than
forcing every caller to pay for a check some of them already have. Callers with no
equivalent outer guard (forward_return_writer.py's price_sanity fact, called once per
run with nothing upstream deduping reruns) should pass True. vocabulary_drift.py's
audit intentionally records one fact per run for calibration history (like
ic_lifecycle's guard_fail_fraction facts) rather than being idempotent per
training_window_end, so it also leaves this off -- not an oversight.
"""

from __future__ import annotations

from typing import Any

import structlog

_logger = structlog.get_logger(__name__)

# Shared INSERT shape -- the one place that defines the composite ON CONFLICT key.
# psycopg2-style (%s positional placeholders).
INTEGRITY_MONITOR_INSERT_SQL = """
INSERT INTO integrity_monitor
    (monitor_type, subject, metric_name, metric_value, threshold_value, passed, training_window_end)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (monitor_type, training_window_end, metric_name, COALESCE(subject, ''), evaluated_at) DO NOTHING
"""

# Same statement, asyncpg-style ($N positional placeholders).
_INTEGRITY_MONITOR_INSERT_SQL_ASYNCPG = """
INSERT INTO integrity_monitor
    (monitor_type, subject, metric_name, metric_value, threshold_value, passed, training_window_end)
VALUES ($1, $2, $3, $4, $5, $6, $7)
ON CONFLICT (monitor_type, training_window_end, metric_name, COALESCE(subject, ''), evaluated_at) DO NOTHING
"""

_IDEMPOTENCY_PRECHECK_SQL = """
SELECT 1 FROM integrity_monitor
WHERE monitor_type = %s
  AND training_window_end = %s
  AND metric_name = %s
LIMIT 1
"""

_IDEMPOTENCY_PRECHECK_SQL_ASYNCPG = """
SELECT 1 FROM integrity_monitor
WHERE monitor_type = $1
  AND training_window_end = $2
  AND metric_name = $3
LIMIT 1
"""


def emit_integrity_fact_sync(
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
    commit: bool = False,
) -> None:
    """Guarded single-row INSERT into integrity_monitor over a sync psycopg2 conn.

    See module docstring for the idempotency_check and commit design rationale.
    Never raises -- an emit failure is logged and swallowed (guard behavior).
    """
    try:
        if idempotency_check:
            with conn.cursor() as cur:
                cur.execute(
                    _IDEMPOTENCY_PRECHECK_SQL, (monitor_type, training_window_end, metric_name)
                )
                if cur.fetchone() is not None:
                    _logger.info(
                        "integrity_monitor.emit_skipped_already_ran",
                        monitor_type=monitor_type,
                        metric_name=metric_name,
                        training_window_end=str(training_window_end),
                    )
                    return

        with conn.cursor() as cur:
            cur.execute(
                INTEGRITY_MONITOR_INSERT_SQL,
                (
                    monitor_type,
                    subject,
                    metric_name,
                    metric_value,
                    threshold_value,
                    passed,
                    training_window_end,
                ),
            )
        if commit:
            conn.commit()
    except Exception as error:
        _logger.warning(
            "integrity_monitor.emit_failed",
            monitor_type=monitor_type,
            metric_name=metric_name,
            error=str(error),
        )


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
    """asyncpg variant of emit_integrity_fact_sync -- see module docstring for the
    guard and idempotency-check design rationale.

    No commit parameter: asyncpg connections autocommit each statement outside an
    explicit `conn.transaction()` block, and none of today's async call sites
    (vocabulary_drift.py) wrap this in one.
    """
    try:
        if idempotency_check:
            exists = await conn.fetchval(
                _IDEMPOTENCY_PRECHECK_SQL_ASYNCPG,
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
            _INTEGRITY_MONITOR_INSERT_SQL_ASYNCPG,
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
