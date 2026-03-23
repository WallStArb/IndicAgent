"""
CUSUM Performance Monitor — QUAL-10

Detects per-setup win-rate degradation using Page's CUSUM algorithm.
When a setup's pnl_r series degrades below the baseline window, writes a
penalty severity to the drift_state DB table. setup_performance_updater reads
these flags and applies multiplicative adjustment to perf_weights.

Design decisions:
- Baseline window: first 20 outcomes in the series
- Minimum N: 20 outcomes required (insufficient data gate)
- CUSUM parameters: k=0.5 (reference value), h=4.0 (threshold)
- Severity: critical if s_neg >= 2h, warning if s_neg >= h, info if s_pos >= h (winning)
- CUSUM rows in drift_state: symbol=setup_plugin_name, tf='_cusum' (sentinel)
- Run interval: every 1 hour via run_forever()

Phase 30: Redis dependency removed. drift_state table replaces Redis keys.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from prometheus_client import Counter

# drift_cusum Redis key function removed in Phase 30 — replaced by drift_state DB table
# CUSUM rows use: symbol=setup_plugin_name, tf='_cusum' sentinel

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# CUSUM algorithm parameters
CUSUM_K: float = 0.5  # Reference value (allowance)
CUSUM_H: float = 4.0  # Decision threshold

# Minimum outcomes required before CUSUM is valid
_CUSUM_MIN_OUTCOMES: int = 20

# Baseline window size (first N outcomes used to compute mu0/sigma0)
_BASELINE_WINDOW: int = 20

# Run interval: 1 hour
_RUN_INTERVAL_SECONDS: int = 3600

# ---------------------------------------------------------------------------
# Prometheus metrics (direct prometheus_client — NOT metrics.py helpers)
# ---------------------------------------------------------------------------

CUSUM_CHECKS_TOTAL = Counter(
    "cusum_checks_total",
    "CUSUM checks run",
    ["setup_plugin"],
)
CUSUM_ALERTS_TOTAL = Counter(
    "cusum_alerts_total",
    "CUSUM alerts fired",
    ["setup_plugin", "severity"],
)


# ---------------------------------------------------------------------------
# Pure algorithm function
# ---------------------------------------------------------------------------


def _compute_cusum(
    pnl_r_series: list[float],
    mu0: float,
    sigma0: float,
    k: float = CUSUM_K,
    h: float = CUSUM_H,
) -> tuple[float, float, str]:
    """Page's CUSUM algorithm for detecting pnl_r degradation.

    Args:
        pnl_r_series: Full list of pnl_r values (baseline + monitoring window).
        mu0: Baseline mean (computed from first _BASELINE_WINDOW outcomes).
        sigma0: Baseline std (floor at 0.5 to avoid division by near-zero).
        k: Reference value / allowance (default 0.5).
        h: Decision threshold (default 4.0).

    Returns:
        (S_pos, S_neg, severity) where:
        - severity="critical" if s_neg >= 2*h (strong degradation)
        - severity="warning" if s_neg >= h (degradation signal)
        - severity="info" if s_pos >= h (winning streak — not penalised)
        - severity="none" if no signal
    """
    s_pos, s_neg = 0.0, 0.0
    effective_sigma = max(sigma0, 0.5)

    # Skip baseline window — only monitor from index _BASELINE_WINDOW onwards
    for pnl in pnl_r_series[_BASELINE_WINDOW:]:
        x_n = (pnl - mu0) / effective_sigma
        s_pos = max(0.0, s_pos + x_n - k)
        s_neg = max(0.0, s_neg + (-x_n) - k)

    if s_neg >= 2 * h:
        return s_pos, s_neg, "critical"
    if s_neg >= h:
        return s_pos, s_neg, "warning"
    if s_pos >= h:
        return s_pos, s_neg, "info"
    return s_pos, s_neg, "none"


# ---------------------------------------------------------------------------
# CUSUMMonitor
# ---------------------------------------------------------------------------


class CUSUMMonitor:
    """CUSUM performance monitor for per-setup pnl_r degradation.

    Reads the last 90 days of resolved outcomes from signal_ledger,
    computes Page's CUSUM on the pnl_r series, and writes severity flags
    to the drift_state DB table. setup_performance_updater reads these flags
    to automatically apply multiplicative penalties to perf_weights.

    Phase 30: Redis dependency removed. drift_state table replaces Redis keys.
    CUSUM rows use: symbol=setup_plugin_name, tf='_cusum' sentinel.

    Args:
        db_pool: asyncpg connection pool (from DatabaseManager.pool).
        env_prefix: Environment prefix for logging context.
    """

    def __init__(
        self,
        db_pool: Any,
        env_prefix: str,
    ) -> None:
        self.db_pool = db_pool
        self.env_prefix = env_prefix
        self.logger = structlog.get_logger(__name__)

    # ------------------------------------------------------------------
    # Core check
    # ------------------------------------------------------------------

    async def check_setup(self, setup_plugin: str) -> str:
        """Run CUSUM check for a single setup_plugin.

        1. Query signal_ledger for last 90d pnl_r values (outcome IS NOT NULL).
        2. Require N >= _CUSUM_MIN_OUTCOMES — return "none" if insufficient.
        3. Compute mu0, sigma0 from first _BASELINE_WINDOW outcomes.
        4. Run _compute_cusum() on full series.
        5. Write Redis key if severity != "none".

        Returns:
            Severity string: "none", "warning", "critical", or "info".
        """
        pnl_r_series = await self._fetch_outcomes(setup_plugin)

        CUSUM_CHECKS_TOTAL.labels(setup_plugin=setup_plugin).inc()

        if len(pnl_r_series) < _CUSUM_MIN_OUTCOMES:
            self.logger.debug(
                "CUSUM skip: insufficient outcomes",
                setup_plugin=setup_plugin,
                n=len(pnl_r_series),
            )
            return "none"

        # Baseline statistics from first _BASELINE_WINDOW outcomes
        baseline = pnl_r_series[:_BASELINE_WINDOW]
        mu0 = sum(baseline) / len(baseline)
        variance = sum((x - mu0) ** 2 for x in baseline) / max(len(baseline) - 1, 1)
        sigma0 = variance**0.5

        s_pos, s_neg, severity = _compute_cusum(pnl_r_series, mu0=mu0, sigma0=sigma0)

        if severity != "none":
            await self._upsert_cusum_state(setup_plugin, severity)
            CUSUM_ALERTS_TOTAL.labels(setup_plugin=setup_plugin, severity=severity).inc()
            self.logger.info(
                "CUSUM drift detected",
                setup_plugin=setup_plugin,
                severity=severity,
                s_pos=round(s_pos, 3),
                s_neg=round(s_neg, 3),
                n=len(pnl_r_series),
            )

        return severity

    async def _upsert_cusum_state(self, setup_plugin: str, cusum_severity: str) -> None:
        """Upsert cusum_severity into drift_state table for (setup_plugin, '_cusum')."""
        query = """
            INSERT INTO drift_state (symbol, tf, cusum_severity, updated_at)
            VALUES ($1, '_cusum', $2, NOW())
            ON CONFLICT (symbol, tf)
            DO UPDATE SET cusum_severity = EXCLUDED.cusum_severity,
                          updated_at = NOW()
        """  # noqa: S608
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(query, setup_plugin, cusum_severity)
        except Exception as exc:
            self.logger.warning(
                "drift_state CUSUM upsert failed",
                setup_plugin=setup_plugin,
                cusum_severity=cusum_severity,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # DB fetch
    # ------------------------------------------------------------------

    async def _fetch_outcomes(self, setup_plugin: str) -> list[float]:
        """Fetch last 90 days of pnl_r values for a setup_plugin."""
        query = """
            SELECT pnl_r
            FROM signal_ledger
            WHERE setup_plugin = $1
              AND outcome IS NOT NULL
              AND pnl_r IS NOT NULL
              AND resolved_at > now() - INTERVAL '90 days'
            ORDER BY resolved_at ASC
        """  # noqa: S608
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(query, setup_plugin)
        return [float(row["pnl_r"]) for row in rows]

    # ------------------------------------------------------------------
    # Eligible setups
    # ------------------------------------------------------------------

    async def _fetch_eligible_setups(self) -> list[str]:
        """Fetch all setup_plugins with N >= _CUSUM_MIN_OUTCOMES in last 90d."""
        query = """
            SELECT setup_plugin, COUNT(*) as n
            FROM signal_ledger
            WHERE outcome IS NOT NULL
              AND pnl_r IS NOT NULL
              AND resolved_at > now() - INTERVAL '90 days'
              AND setup_plugin IS NOT NULL
            GROUP BY setup_plugin
            HAVING COUNT(*) >= $1
        """  # noqa: S608
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch(query, _CUSUM_MIN_OUTCOMES)
        return [row["setup_plugin"] for row in rows]

    # ------------------------------------------------------------------
    # run_forever
    # ------------------------------------------------------------------

    async def run_forever(self, interval_seconds: int = _RUN_INTERVAL_SECONDS) -> None:
        """Run CUSUM checks for all eligible setups every interval_seconds.

        Args:
            interval_seconds: Check interval (default: 1h).
        """
        self.logger.info(
            "CUSUM monitor starting",
            interval_hours=interval_seconds // 3600,
        )

        while True:
            cycle_start = asyncio.get_event_loop().time()
            try:
                setups = await self._fetch_eligible_setups()
                self.logger.debug("CUSUM cycle", num_setups=len(setups))
                for setup_plugin in setups:
                    try:
                        await self.check_setup(setup_plugin)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        self.logger.warning(
                            "CUSUM check error",
                            setup_plugin=setup_plugin,
                            error=str(exc),
                        )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.logger.error("CUSUM cycle error", error=str(exc))

            elapsed = asyncio.get_event_loop().time() - cycle_start
            sleep_secs = max(0, interval_seconds - elapsed)
            try:
                await asyncio.sleep(sleep_secs)
            except asyncio.CancelledError:
                break
