"""ShadowAuditorAgent — timer-based automated shadow demotion.

Timer-triggered: indicagent-shadow-auditor.timer (every 30 minutes).
One-shot: reads shadow_registry, runs statistical gates, writes transitions, exits.

Demotion gate (D-06): rolling EV[R] < demotion_threshold_ev_r for demotion_min_evaluations
                      consecutive audit cycles.

Promotion is handled by shadow_validator.py (weekly, Plan 01 SoC split).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import _path_bootstrap  # noqa: F401 — project root on sys.path
import asyncpg
import structlog

from src.config.settings import Settings
from src.core.database_manager import create_pool as create_db_pool
from src.core.stats_utils import bootstrap_ci_lower
from src.observability.metrics import (
    JOB_COMPLETED_TOTAL,
    flush_and_shutdown_metrics,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Pure gate functions — tested directly
# ---------------------------------------------------------------------------


def _should_demote(new_count: int, min_evaluations: int) -> bool:
    return new_count >= min_evaluations


def _ev_r_below_threshold(ev_r: float, threshold: float) -> bool:
    return ev_r < threshold


# ---------------------------------------------------------------------------
# Core audit logic
# ---------------------------------------------------------------------------


async def _run_audit(pool: asyncpg.Pool, env_name: str) -> None:
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT component_name, component_type, is_shadow,
                   min_n, min_ev_r, ci_alpha,
                   demotion_lookback_days, demotion_threshold_ev_r,
                   demotion_min_evaluations, demotion_consecutive_count
            FROM shadow_registry
            """)

    for row in rows:
        name = row["component_name"]
        ctype = row["component_type"]

        # Swarm agents have no signal_ledger rows; evaluating them yields n=0 and
        # resets demotion_consecutive_count to 0 every cycle, neutralizing demotion.
        if ctype == "swarm_agent":
            logger.debug("shadow_audit_skip_swarm_agent", component_name=name)
            continue

        if not row["is_shadow"]:
            await _check_demotion(pool, env_name, dict(row))

        logger.debug("shadow_audit_component_done", component_name=name, component_type=ctype)


async def _check_demotion(
    pool: asyncpg.Pool,
    env_name: str,
    row: dict[str, Any],
) -> None:
    name = row["component_name"]
    ctype = row["component_type"]

    async with pool.acquire() as conn:
        signal_rows = await conn.fetch(
            """
            SELECT pnl_r FROM signal_ledger
            WHERE setup_plugin = $1
              AND is_shadow = FALSE
              AND outcome IS NOT NULL
              AND outcome NOT IN ('never_activated', 'ttl_expired_behind')
              AND signal_computed_at > NOW() - INTERVAL '1 day' * $2
            """,
            name,
            row["demotion_lookback_days"],
        )

    pnl_r_values = [float(r["pnl_r"]) for r in signal_rows if r["pnl_r"] is not None]
    n = len(pnl_r_values)
    ev_r = sum(pnl_r_values) / n if n > 0 else 0.0
    ci_lower = bootstrap_ci_lower(pnl_r_values)
    win_rate = 0.0  # not tracked for demotion path

    now = datetime.now(UTC)

    if _ev_r_below_threshold(ev_r, row["demotion_threshold_ev_r"]):
        new_count = row["demotion_consecutive_count"] + 1
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE shadow_registry SET demotion_consecutive_count=$1, last_eval_at=$2 WHERE component_name=$3",
                new_count,
                now,
                name,
            )
        if _should_demote(new_count, row["demotion_min_evaluations"]):
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE shadow_registry
                    SET is_shadow=TRUE, demoted_at=$1, demotion_consecutive_count=0
                    WHERE component_name=$2
                    """,
                    now,
                    name,
                )
                await conn.execute(
                    """
                    INSERT INTO shadow_transition_log
                      (component_name, component_type, from_state, to_state,
                       trigger_reason, n, ev_r, ci_lower, win_rate)
                    VALUES ($1, $2, 'live', 'shadow', 'demotion_ev_r_degraded', $3, $4, $5, $6)
                    """,
                    name,
                    ctype,
                    n,
                    ev_r,
                    ci_lower,
                    win_rate,
                )
            logger.warning(
                "shadow_demoted", component_name=name, ev_r=ev_r, consecutive_count=new_count
            )
    else:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE shadow_registry SET demotion_consecutive_count=0, last_eval_at=$1 WHERE component_name=$2",
                now,
                name,
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _amain() -> None:
    settings = Settings()
    pool = await create_db_pool(settings.database_url, min_size=2, max_size=5)
    try:
        await _run_audit(pool, settings.env_name)
    finally:
        await pool.close()


def main() -> None:
    """Run the shadow auditor once and emit a completion counter before exit."""
    try:
        asyncio.run(_amain())
        JOB_COMPLETED_TOTAL.add(1, {"job": "shadow-auditor", "status": "success"})
    except Exception as error:
        JOB_COMPLETED_TOTAL.add(1, {"job": "shadow-auditor", "status": "failure"})
        raise error
    finally:
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    main()
