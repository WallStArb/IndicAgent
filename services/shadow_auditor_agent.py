"""ShadowAuditorAgent — timer-based automated shadow promotion/demotion.

Timer-triggered: indicagent-shadow-auditor.timer (every 30 minutes).
One-shot: reads shadow_registry, runs statistical gates, writes transitions, exits.

Promotion gate (D-05): n >= min_n AND bootstrap_ci_lower(pnl_r, ci_alpha) > min_ev_r
Demotion gate (D-06): rolling EV[R] < demotion_threshold_ev_r for demotion_min_evaluations
                      consecutive audit cycles.
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
from src.core.service_utils import setup_service_logging
from src.core.stats_utils import bootstrap_ci_lower
from src.observability.metrics import (
    SHADOW_DAYS_TO_GATE,
    SHADOW_EV_CI_LOWER,
    SHADOW_EV_R,
    SHADOW_N_RESOLVED,
    SHADOW_PROMOTION_READY,
    SHADOW_TAIL_GATE_DB_ERROR,
    SHADOW_TAIL_RISK_BLOCKED,
    SHADOW_WIN_RATE,
)

logger = structlog.get_logger(__name__)

_WIN_OUTCOMES = {"target_1", "target_1_2", "target_full"}

# ---------------------------------------------------------------------------
# Tail-risk gate thresholds
# ---------------------------------------------------------------------------

TAIL_GATE_MIN_SKEWNESS: float = -2.0
TAIL_GATE_MIN_RECOVERY: float = 0.5


# ---------------------------------------------------------------------------
# Pure gate functions — tested directly
# ---------------------------------------------------------------------------


def _should_promote(n: int, ci_lower: float, min_n: int, min_ev_r: float) -> bool:
    return n >= min_n and ci_lower > min_ev_r


def _should_demote(new_count: int, min_evaluations: int) -> bool:
    return new_count >= min_evaluations


def _ev_r_below_threshold(ev_r: float, threshold: float) -> bool:
    return ev_r < threshold


def _tail_risk_blocks_promotion(
    skewness: float | None,
    recovery_factor: float | None,
    min_skewness: float,
    min_recovery: float,
) -> str | None:
    """Return the name of the breached metric, or None if promotion is not blocked."""
    if skewness is not None and skewness < min_skewness:
        return "skewness"
    if recovery_factor is not None and recovery_factor < min_recovery:
        return "recovery_factor"
    return None


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

        if row["is_shadow"]:
            await _check_promotion(pool, env_name, dict(row))
        else:
            await _check_demotion(pool, env_name, dict(row))

        logger.debug("shadow_audit_component_done", component_name=name, component_type=ctype)


async def _check_promotion(
    pool: asyncpg.Pool,
    env_name: str,
    row: dict[str, Any],
) -> None:
    name = row["component_name"]
    ctype = row["component_type"]

    async with pool.acquire() as conn:
        signal_rows = await conn.fetch(
            """
            SELECT outcome, pnl_r, signal_computed_at
            FROM signal_ledger
            WHERE setup_plugin = $1
              AND is_shadow = TRUE
              AND outcome IS NOT NULL
              AND outcome NOT IN ('never_activated', 'ttl_expired_behind')
            """,
            name,
        )

    n = len(signal_rows)
    pnl_r_values = [float(r["pnl_r"]) for r in signal_rows if r["pnl_r"] is not None]
    ev_r = sum(pnl_r_values) / len(pnl_r_values) if pnl_r_values else 0.0
    win_rate = sum(1 for r in signal_rows if r["outcome"] in _WIN_OUTCOMES) / n if n > 0 else 0.0
    ci_lower = bootstrap_ci_lower(pnl_r_values, alpha=row["ci_alpha"])

    now = datetime.now(UTC)

    # Update shadow_registry stats and fetch tail-risk metrics in a single connection.
    metrics_row = None
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE shadow_registry
            SET last_eval_n=$1, last_eval_ev_r=$2, last_eval_ci_lower=$3,
                last_eval_win_rate=$4, last_eval_at=$5
            WHERE component_name=$6
            """,
            n,
            ev_r,
            ci_lower,
            win_rate,
            now,
            name,
        )
        try:
            metrics_row = await conn.fetchrow(
                """
                SELECT skewness, recovery_factor
                FROM signal_metrics
                WHERE setup_plugin = $1
                  AND symbol = '*'
                  AND entry_type = '*'
                  AND track = 'market'
                ORDER BY computed_at DESC
                LIMIT 1
                """,
                name,
            )
        except Exception as exc:
            SHADOW_TAIL_GATE_DB_ERROR.add(1, {"plugin": name})
            logger.warning("shadow_audit.tail_gate_db_error", plugin=name, error=str(exc))

    # OTel metrics — point gauges use .set() (point-in-time absolute values)
    SHADOW_N_RESOLVED.set(n, {"plugin": name})
    SHADOW_WIN_RATE.set(round(win_rate, 4), {"plugin": name})
    SHADOW_EV_R.set(round(ev_r, 4), {"plugin": name})
    ci_display = round(ci_lower, 4) if ci_lower != float("-inf") else float("-inf")
    SHADOW_EV_CI_LOWER.set(ci_display, {"plugin": name})

    # Days-to-gate estimate
    recent_30d = sum(
        1
        for r in signal_rows
        if r.get("signal_computed_at") is not None
        and (
            now - r["signal_computed_at"].replace(tzinfo=UTC)
            if r["signal_computed_at"].tzinfo is None
            else now - r["signal_computed_at"]
        ).days
        <= 30
    )
    if recent_30d > 0:
        remaining = max(0, row["min_n"] - n)
        days_to_gate = (remaining / recent_30d) * 30
    else:
        days_to_gate = float("inf")
    SHADOW_DAYS_TO_GATE.set(
        round(days_to_gate, 1) if days_to_gate != float("inf") else float("inf"), {"plugin": name}
    )

    # Tail-risk gate — blocks promotion when distribution shape is adverse.
    # Skips when metrics_row is None (plugin too new) or when DB error occurred (fail-open).
    if metrics_row is not None:
        tail_block_reason = _tail_risk_blocks_promotion(
            metrics_row["skewness"],
            metrics_row["recovery_factor"],
            TAIL_GATE_MIN_SKEWNESS,
            TAIL_GATE_MIN_RECOVERY,
        )
        if tail_block_reason is not None:
            SHADOW_TAIL_RISK_BLOCKED.add(1, {"plugin": name, "reason": tail_block_reason})
            logger.info(
                "shadow_audit.tail_risk_blocked",
                plugin=name,
                skewness=metrics_row["skewness"],
                recovery_factor=metrics_row["recovery_factor"],
            )
            return

    if _should_promote(n, ci_lower, row["min_n"], row["min_ev_r"]):
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE shadow_registry
                SET is_shadow=FALSE, promoted_at=$1, demotion_consecutive_count=0
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
                VALUES ($1, $2, 'shadow', 'live', 'promotion_gate_cleared', $3, $4, $5, $6)
                """,
                name,
                ctype,
                n,
                ev_r,
                ci_lower,
                win_rate,
            )
        SHADOW_PROMOTION_READY.set(1, {"plugin": name})
        logger.info("shadow_promoted", component_name=name, n=n, ci_lower=ci_lower)
    else:
        SHADOW_PROMOTION_READY.set(0, {"plugin": name})


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
    setup_service_logging("logs/shadow_auditor_agent.log")
    settings = Settings()
    pool = await create_db_pool(settings.database_url, min_size=2, max_size=5)
    try:
        await _run_audit(pool, settings.env_name)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_amain())
