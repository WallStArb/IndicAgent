"""ShadowValidator — weekly oneshot 5-gate promotion validator.

Timer-triggered: indicagent-shadow-validator.timer (Mon 07:00 UTC).
One-shot: queries shadow_registry setups, runs 5-gate statistical check,
promotes passing setups by writing is_shadow=FALSE to shadow_registry.

5-Gate Promotion Logic (D-02):
  Gate 1: n_resolved >= 100
  Gate 2: win_rate (pnl_r > 0) >= 50%
  Gate 3: binomtest(wins, n_resolved, p=0.5) p < 0.05 (one-sided)
  Gate 4: avg_pnl_r > 0
  Gate 5: calibration_corr (CORR cis_score vs pnl_r>0) >= 0.3

NOTE — was_selected is NOT used: shadow signals are excluded from winner
selection by design (signal_processor.py builds eligible_ranked from
non-shadow only). was_selected is structurally always False for shadow
signals, making any gate on it permanently unpassable.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import _path_bootstrap  # noqa: F401 — project root on sys.path
import asyncpg
import structlog
from scipy.stats import binomtest

from src.config.settings import Settings
from src.core.database_manager import create_pool as create_db_pool
from src.core.kafka_utils import KafkaProducerClient
from src.core.stream_keys import topic_alert_requests
from src.observability.metrics import (
    JOB_COMPLETED_TOTAL,
    SHADOW_VALIDATION_AVG_PNL_R,
    SHADOW_VALIDATION_CALIBRATION,
    SHADOW_VALIDATION_N,
    SHADOW_VALIDATION_P_VALUE,
    SHADOW_VALIDATION_PROMOTED,
    SHADOW_VALIDATION_WIN_RATE,
    flush_and_shutdown_metrics,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Target setup list — verified 2026-06-10 against _PHASE_119_PLUGINS in
# src/intelligence/register_plugins.py:667 (authoritative source).
# Phase 118 (5) + Phase 119 (17) = 22 total.
# ---------------------------------------------------------------------------

_SHADOW_VALIDATION_SETUPS: frozenset[str] = frozenset(
    {
        # Phase 118 (5 setups)
        "trad_OFIContinuation",
        "trad_PatternCompletion",
        "trad_GapAnalysisSetup",
        "trad_CVDDivergence",
        "trad_DivergenceStack",
        # Phase 119 (17 setups)
        "trad_OFISpike",
        "trad_CVDSpike",
        "trad_OFIDivergence",
        "trad_FailedBreakout",
        "trad_CandlestickPatternSetup",
        "trad_SessionExtremesSetup",
        "trad_LiquidityHunt",
        "trad_DeltaExhaustion",
        "trad_LVNBreakout",
        "trad_VWAPReclaim",
        "trad_VWAPDeviation",
        "trad_MomentumBreakout",
        "trad_ORB15",
        "trad_ORB30",
        "trad_SecondLegContinuation",
        "trad_VCP",
        "trad_DualDivergence",
    }
)

assert (
    len(_SHADOW_VALIDATION_SETUPS) == 22
), f"Expected 22 setups, got {len(_SHADOW_VALIDATION_SETUPS)}"

# ---------------------------------------------------------------------------
# Pure gate function — tested directly
# ---------------------------------------------------------------------------


def _check_promotion_criteria(
    n_resolved: int,
    wins: int,
    avg_pnl_r: float | None,
    calibration_corr: float | None,
) -> tuple[bool, str, str]:
    """Return (should_promote, failure_reason, detail).

    Sequential short-circuit: cheapest checks first (D-02).
    Gate order: insufficient_n -> low_win_rate -> not_significant ->
                negative_expectancy -> poor_calibration -> promote.
    """
    # Gate 1: Sufficient resolved outcomes
    if n_resolved < 100:
        return False, "insufficient_n", f"{n_resolved} resolved < 100"

    # Gate 2: Win rate > 50%
    win_rate = wins / n_resolved
    if win_rate < 0.5:
        return False, "low_win_rate", f"{win_rate:.1%} < 50%"

    # Gate 3: Statistical significance (binomial test, one-sided, vs 50% baseline)
    result = binomtest(wins, n_resolved, p=0.5, alternative="greater")
    if result.pvalue >= 0.05:
        return False, "not_significant", f"p={result.pvalue:.3f} >= 0.05"

    # Gate 4: Positive expectancy
    if avg_pnl_r is None or avg_pnl_r <= 0:
        return False, "negative_expectancy", f"avg_pnl_r={avg_pnl_r}"

    # Gate 5: Confidence calibration
    if calibration_corr is None or calibration_corr < 0.3:
        return False, "poor_calibration", f"corr={calibration_corr} < 0.3"

    return True, "", ""


# ---------------------------------------------------------------------------
# Core validation logic
# ---------------------------------------------------------------------------


async def _run_validator(pool: asyncpg.Pool, settings: Settings) -> None:
    """Iterate all 22 setups, run 5-gate check, promote on full pass."""
    producer: KafkaProducerClient | None = None
    try:
        producer = KafkaProducerClient(bootstrap_servers=settings.kafka_bootstrap_servers)
        await producer.start()
    except Exception as error:
        logger.warning("shadow_validator.kafka_unavailable", error=str(error))
        producer = None

    for name in sorted(_SHADOW_VALIDATION_SETUPS):
        await _validate_setup(pool, settings, name, producer)

    if producer is not None:
        try:
            await producer.stop()
        except Exception as error:
            logger.warning("shadow_validator.kafka_stop_error", error=str(error))


async def _validate_setup(
    pool: asyncpg.Pool,
    settings: Settings,
    name: str,
    producer: KafkaProducerClient | None,
) -> None:
    """Run 5-gate promotion check for a single setup and emit OTel gauges."""
    # Per-setup outcome metrics query (D-03).
    # is_backfill = false ensures only post-refactor signals count (D-03).
    # V2.11_ACTIVATED: returns n_resolved=0 until CounterfactualTracker populates counterfactual_pnl_r.
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
              COUNT(*) FILTER (WHERE sl.counterfactual_pnl_r IS NOT NULL) AS n_resolved,
              COUNT(*) FILTER (WHERE sl.counterfactual_pnl_r > 0) AS wins,
              AVG(sl.counterfactual_pnl_r) FILTER (WHERE sl.counterfactual_pnl_r IS NOT NULL) AS avg_pnl_r,
              CORR(sl.cis_score, (sl.counterfactual_pnl_r > 0)::int)
                FILTER (WHERE sl.counterfactual_pnl_r IS NOT NULL) AS calibration_corr
            FROM signal_ledger sl
            WHERE sl.setup_plugin = $1
              AND sl.is_shadow = true
              AND sl.is_backfill = false
            """,
            name,
        )

    n_resolved = int(row["n_resolved"] or 0)
    wins = int(row["wins"] or 0)
    avg_pnl_r: float | None = float(row["avg_pnl_r"]) if row["avg_pnl_r"] is not None else None
    calibration_corr: float | None = (
        float(row["calibration_corr"]) if row["calibration_corr"] is not None else None
    )

    # Compute metrics for gauge emission even when early gate fires.
    # Guard n_resolved > 0 to avoid div-by-zero; emit p_value as 1.0 when n=0.
    win_rate = wins / n_resolved if n_resolved > 0 else 0.0
    if n_resolved > 0:
        binom_result = binomtest(wins, n_resolved, p=0.5, alternative="greater")
        p_value = binom_result.pvalue
    else:
        p_value = 1.0

    # Run 5-gate sequential check
    should_promote, reason, detail = _check_promotion_criteria(
        n_resolved, wins, avg_pnl_r, calibration_corr
    )

    # Always emit all 6 gauges for every setup (D-08)
    labels = {"setup_plugin": name}
    SHADOW_VALIDATION_N.set(n_resolved, labels)
    SHADOW_VALIDATION_WIN_RATE.set(round(win_rate, 4), labels)
    SHADOW_VALIDATION_P_VALUE.set(round(p_value, 4), labels)
    SHADOW_VALIDATION_AVG_PNL_R.set(round(avg_pnl_r, 4) if avg_pnl_r is not None else 0.0, labels)
    SHADOW_VALIDATION_CALIBRATION.set(
        round(calibration_corr, 4) if calibration_corr is not None else 0.0, labels
    )
    SHADOW_VALIDATION_PROMOTED.set(1 if should_promote else 0, labels)

    if not should_promote:
        logger.info(
            "shadow_validator.gate_fail",
            plugin=name,
            reason=reason,
            detail=detail,
            n_resolved=n_resolved,
        )
        return

    # All 5 gates passed — write promotion (D-05)
    now = datetime.now(UTC)
    async with pool.acquire() as conn:
        # AND is_shadow=TRUE guard prevents re-promoting an already-demoted setup
        # if validator runs concurrently with shadow_auditor.
        await conn.execute(
            """
            UPDATE shadow_registry
            SET is_shadow=FALSE, promoted_at=$1, demotion_consecutive_count=0
            WHERE component_name=$2 AND is_shadow=TRUE
            """,
            now,
            name,
        )
        await conn.execute(
            """
            INSERT INTO shadow_transition_log
              (component_name, component_type, from_state, to_state,
               trigger_reason, n, ev_r, ci_lower, win_rate)
            VALUES ($1, 'i7_plugin', 'shadow', 'live', 'shadow_validator_5gate',
                    $2, $3, $4, $5)
            """,
            # Column mapping: ev_r=avg_pnl_r, ci_lower=calibration_corr (schema reuse,
            # shadow_transition_log predates calibration metric — see D-05 in CONTEXT.md),
            # win_rate=actual win_rate
            name,
            n_resolved,
            avg_pnl_r,
            calibration_corr,
            win_rate,
        )

    logger.info(
        "shadow_validator.promoted",
        plugin=name,
        n=n_resolved,
        win_rate=round(win_rate, 4),
        p_value=round(p_value, 4),
        avg_pnl_r=round(avg_pnl_r, 4) if avg_pnl_r is not None else None,
        calibration=round(calibration_corr, 4) if calibration_corr is not None else None,
    )

    # Kafka alert — optional; DB write must NOT be rolled back if Kafka fails (D-07)
    if producer is not None:
        try:
            await producer.publish(
                topic_alert_requests(settings.env_name),
                {
                    "severity": "CRITICAL",
                    "message": (
                        f"Shadow Promotion: {name}\n"
                        f"N={n_resolved}, win_rate={win_rate:.1%}, "
                        f"p={p_value:.3f}, avg_pnl_r={avg_pnl_r:.3f}, "
                        f"calibration={calibration_corr:.3f}"
                    ),
                    "source": "shadow_validator",
                },
            )
        except Exception as error:
            logger.warning(
                "shadow_validator.kafka_unavailable",
                plugin=name,
                error=str(error),
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _amain() -> None:
    settings = Settings()
    pool = await create_db_pool(settings.database_url, min_size=2, max_size=5)
    try:
        await _run_validator(pool, settings)
    finally:
        await pool.close()


def main() -> None:
    """Run the shadow validator once and emit a completion counter before exit."""
    try:
        asyncio.run(_amain())
        JOB_COMPLETED_TOTAL.add(1, {"job": "shadow-validator", "status": "success"})
    except Exception as error:
        JOB_COMPLETED_TOTAL.add(1, {"job": "shadow-validator", "status": "failure"})
        raise error
    finally:
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    main()
