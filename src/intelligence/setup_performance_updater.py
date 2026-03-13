"""Setup Performance Updater — FEED-01 / FEED-02.

Computes per-setup win rate, avg pnl_r, sample size, and Sharpe ratio
from the rolling 30-day window of resolved signals in signal_ledger.
Only setups with sample_size >= MIN_SAMPLE_SIZE (30) are included.

Writes results to:
  - setup_performance table (upsert, nightly)
  - Redis: {env_prefix}setup_performance:weights (JSON dict of perf_multipliers)

Perf multiplier formula (FEED-03 consumption):
  sorted by sharpe_ratio ascending → rank 0..n-1
  perf_multiplier = 0.5 + ((n - 1 - rank) / n_eligible)  → range [0.5, ~1.5]
  Best performer: rank=n-1 → multiplier = 0.5 (LOWEST — sorts first in ascending adjusted_rank)
  Worst performer: rank=0  → multiplier approaches 1.5 (sorts last)

Note: Inverted so best Sharpe gets lowest multiplier, minimising adjusted_rank under ascending sort.
If n_eligible == 1, perf_multiplier = 1.0 for the sole eligible setup.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

from src.core import stream_keys
from src.core.stream_keys import setup_performance_weights_cache

logger = logging.getLogger(__name__)

MIN_SAMPLE_SIZE = 30  # FEED-02 promotion gate
ROLLING_DAYS = 30


def compute_setup_performance(rows: list[dict]) -> dict[str, dict]:
    """Group resolved signal rows by setup_plugin, compute stats.

    Returns dict keyed by setup_plugin. Excludes setups with n < MIN_SAMPLE_SIZE.

    Parameters
    ----------
    rows:
        List of dicts with keys: setup_plugin (str), pnl_r (float | None),
        resolved_at (datetime | None), outcome (str).
        Rows with pnl_r=None or resolved_at older than ROLLING_DAYS are excluded.
    """
    if not rows:
        return {}

    cutoff = datetime.now(UTC) - timedelta(days=ROLLING_DAYS)

    # Group valid rows by setup_plugin
    by_plugin: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        pnl_r = row.get("pnl_r")
        if pnl_r is None:
            continue
        resolved_at = row.get("resolved_at")
        if resolved_at is not None:
            # Ensure timezone-aware comparison
            if resolved_at.tzinfo is None:
                resolved_at = resolved_at.replace(tzinfo=UTC)
            if resolved_at <= cutoff:
                continue
        setup_plugin = row.get("setup_plugin")
        if not setup_plugin:
            continue
        by_plugin[setup_plugin].append(float(pnl_r))

    result: dict[str, dict] = {}
    for plugin, pnl_rs in by_plugin.items():
        n = len(pnl_rs)
        if n < MIN_SAMPLE_SIZE:
            continue

        arr = np.array(pnl_rs, dtype=float)
        wins = int((arr > 0).sum())
        win_rate = float(wins / n)
        avg_pnl_r = float(arr.mean())
        sample_size = n

        std = float(arr.std(ddof=1)) if n > 1 else 0.0
        sharpe_ratio = float(arr.mean() / std) if std > 0.0 else 0.0

        result[plugin] = {
            "win_rate": win_rate,
            "avg_pnl_r": avg_pnl_r,
            "sample_size": sample_size,
            "sharpe_ratio": sharpe_ratio,
        }

    return result


def _compute_perf_multipliers(stats: dict[str, dict]) -> dict[str, float]:
    """Convert setup stats to perf_multipliers using Sharpe rank.

    Returns dict[setup_plugin, float] where values are in [0.5, 1.5].
    If only one eligible setup, returns {plugin: 1.0}.
    """
    if not stats:
        return {}

    plugins = list(stats.keys())
    n = len(plugins)

    if n == 1:
        return {plugins[0]: 1.0}

    # Sort by sharpe_ratio ascending so rank 0 = worst, rank n-1 = best
    sorted_plugins = sorted(plugins, key=lambda p: stats[p]["sharpe_ratio"])
    multipliers: dict[str, float] = {}
    for rank, plugin in enumerate(sorted_plugins):
        multipliers[plugin] = 0.5 + ((n - 1 - rank) / n)

    return multipliers


async def run_setup_performance_update(
    db_manager: Any,
    redis_client: Any,
    env_prefix: str,  # Required — no default. Callers must be explicit.
) -> dict[str, float]:
    """Query DB, compute stats, upsert setup_performance, write Redis.

    Returns perf_weights dict (empty if no eligible setups).

    Parameters
    ----------
    db_manager:
        DatabaseManager instance with execute_query / execute_command methods.
    redis_client:
        Async redis client with .set() method.
    env_prefix:
        Environment prefix for Redis key construction (e.g. "development:").
        Required — no default value to prevent silent unqualified-key writes.
    """
    rows = await db_manager.execute_query(
        """
        SELECT setup_plugin, pnl_r
        FROM signal_ledger
        WHERE pnl_r IS NOT NULL
          AND resolved_at > now() - INTERVAL '30 days'
          AND setup_plugin IS NOT NULL
        ORDER BY setup_plugin
        """
    )

    if not rows:
        logger.info("setup_performance: no resolved signals in last 30 days")
        return {}

    stats = compute_setup_performance(list(rows))
    if not stats:
        logger.info(
            "setup_performance: no eligible setups (n<%d for all)", MIN_SAMPLE_SIZE
        )
        return {}

    # Upsert stats to setup_performance table
    for plugin, s in stats.items():
        await db_manager.execute_command(
            """
            INSERT INTO setup_performance
                (setup_plugin, win_rate, avg_pnl_r, sample_size, sharpe_ratio, updated_at)
            VALUES ($1, $2, $3, $4, $5, now())
            ON CONFLICT (setup_plugin) DO UPDATE
                SET win_rate = EXCLUDED.win_rate,
                    avg_pnl_r = EXCLUDED.avg_pnl_r,
                    sample_size = EXCLUDED.sample_size,
                    sharpe_ratio = EXCLUDED.sharpe_ratio,
                    updated_at = EXCLUDED.updated_at
            """,
            plugin,
            s["win_rate"],
            s["avg_pnl_r"],
            s["sample_size"],
            s["sharpe_ratio"],
        )

    # Compute perf multipliers (base from setup_performance table)
    perf_weights = _compute_perf_multipliers(stats)

    # Apply CUSUM penalty adjustments (multiplicative, floor at 0.30)
    # CRITICAL: This is the ONLY place that writes perf_weights to Redis.
    # drift_monitor_service writes CUSUM state; we read and apply it here.
    CUSUM_ADJUSTMENT: dict[str, float] = {"warning": 0.85, "critical": 0.70}
    CUSUM_MULTIPLIER_FLOOR: float = 0.30

    for plugin in list(perf_weights.keys()):
        cusum_key = stream_keys.drift_cusum(env_prefix, plugin)
        raw = await redis_client.get(cusum_key)
        if raw:
            severity = raw.decode() if isinstance(raw, bytes) else raw
            factor = CUSUM_ADJUSTMENT.get(severity, 1.0)
            if factor < 1.0:
                adjusted = round(perf_weights[plugin] * factor, 4)
                perf_weights[plugin] = max(CUSUM_MULTIPLIER_FLOOR, adjusted)
                logger.info(
                    "setup_performance: CUSUM penalty applied",
                    plugin=plugin,
                    severity=severity,
                    factor=factor,
                    adjusted_weight=perf_weights[plugin],
                )

    key = setup_performance_weights_cache(env_prefix)
    await redis_client.set(key, json.dumps(perf_weights))

    logger.info(
        "setup_performance: upserted %d setups, wrote perf_weights to %s",
        len(stats),
        key,
    )
    return perf_weights
