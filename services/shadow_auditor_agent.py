"""ShadowAuditorAgent — timer-based automated shadow promotion/demotion.

Timer-triggered: indicagent-shadow-auditor.timer (every 30 minutes).
One-shot: reads shadow_registry, runs statistical gates, writes transitions, exits.

Promotion gate (D-05): n >= min_n AND bootstrap_ci_lower(pnl_r, ci_alpha) > min_ev_r
Demotion gate (D-06): rolling EV[R] < demotion_threshold_ev_r for demotion_min_evaluations
                      consecutive audit cycles.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from datetime import UTC, datetime
from typing import Any

import _path_bootstrap  # noqa: F401 — project root on sys.path
import asyncpg
import structlog

from src.config.settings import Settings
from src.core.database_manager import create_pool as create_db_pool
from src.core.kafka_utils import KafkaProducerClient
from src.core.service_utils import setup_service_logging
from src.core.stats_utils import bootstrap_ci_lower
from src.core.stream_keys import topic_shadow_transitions
from src.intelligence.schemas import ShadowTransitionEvent
from src.observability.metrics import (
    SHADOW_DAYS_TO_GATE,
    SHADOW_EV_CI_LOWER,
    SHADOW_EV_R,
    SHADOW_N_RESOLVED,
    SHADOW_PROMOTION_READY,
    SHADOW_WIN_RATE,
)

logger = structlog.get_logger(__name__)

_WIN_OUTCOMES = {"target_1", "target_1_2", "target_full"}


# ---------------------------------------------------------------------------
# Pure gate functions — tested directly
# ---------------------------------------------------------------------------


def _should_promote(n: int, ci_lower: float, min_n: int, min_ev_r: float) -> bool:
    return n >= min_n and ci_lower > min_ev_r


def _should_demote(new_count: int, min_evaluations: int) -> bool:
    return new_count >= min_evaluations


def _ev_r_below_threshold(ev_r: float, threshold: float) -> bool:
    return ev_r < threshold


# ---------------------------------------------------------------------------
# Core audit logic
# ---------------------------------------------------------------------------


async def _run_audit(pool: asyncpg.Pool, producer: KafkaProducerClient, env_name: str) -> None:
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

        if row["is_shadow"]:
            await _check_promotion(pool, producer, env_name, dict(row))
        else:
            await _check_demotion(pool, producer, env_name, dict(row))

        logger.debug("shadow_audit_component_done", component_name=name, component_type=ctype)


async def _check_promotion(
    pool: asyncpg.Pool,
    producer: KafkaProducerClient,
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
              AND signal_schema_version = 'v2'
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

    # Prometheus gauges
    SHADOW_N_RESOLVED.labels(plugin=name).set(n)
    SHADOW_WIN_RATE.labels(plugin=name).set(round(win_rate, 4))
    SHADOW_EV_R.labels(plugin=name).set(round(ev_r, 4))
    ci_display = round(ci_lower, 4) if ci_lower != float("-inf") else float("-inf")
    SHADOW_EV_CI_LOWER.labels(plugin=name).set(ci_display)

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
    SHADOW_DAYS_TO_GATE.labels(plugin=name).set(
        round(days_to_gate, 1) if days_to_gate != float("inf") else float("inf")
    )

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
        event = ShadowTransitionEvent(
            component_name=name,
            component_type=ctype,
            from_state="shadow",
            to_state="live",
            trigger_reason="promotion_gate_cleared",
            n=n,
            ev_r=ev_r,
            ci_lower=ci_lower,
            win_rate=win_rate,
            triggered_at=now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        )
        await _publish(producer, env_name, event)
        SHADOW_PROMOTION_READY.labels(plugin=name).set(1)
        logger.info("shadow_promoted", component_name=name, n=n, ci_lower=ci_lower)
    else:
        SHADOW_PROMOTION_READY.labels(plugin=name).set(0)


async def _check_demotion(
    pool: asyncpg.Pool,
    producer: KafkaProducerClient,
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
              AND signal_schema_version = 'v2'
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
            event = ShadowTransitionEvent(
                component_name=name,
                component_type=ctype,
                from_state="live",
                to_state="shadow",
                trigger_reason="demotion_ev_r_degraded",
                n=n,
                ev_r=ev_r,
                ci_lower=ci_lower,
                win_rate=win_rate,
                triggered_at=now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            )
            await _publish(producer, env_name, event)
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


async def _publish(
    producer: KafkaProducerClient, env_name: str, event: ShadowTransitionEvent
) -> None:
    try:
        payload = json.dumps(dataclasses.asdict(event)).encode()
        await producer.send(
            topic=topic_shadow_transitions(env_name),
            key=event.component_name.encode(),
            value=payload,
        )
    except Exception as exc:
        logger.warning("shadow_transition_publish_failed", error=str(exc))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _amain() -> None:
    setup_service_logging("logs/shadow_auditor_agent.log")
    settings = Settings()
    pool = await create_db_pool(settings.database_url, min_size=2, max_size=5)
    producer = KafkaProducerClient(bootstrap_servers=settings.kafka_bootstrap_servers)
    await producer.start()
    try:
        await _run_audit(pool, producer, settings.env_name)
    finally:
        await producer.stop()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_amain())
