"""Setup Performance Updater — FEED-01 / FEED-02.

Computes per-setup win rate, avg pnl_r, sample size, and Sharpe ratio
from the rolling 30-day window of resolved signals in signal_ledger.
Only setups with sample_size >= MIN_SAMPLE_SIZE (100) are included.
Minimum 100 samples required; values below 200 are statistically unreliable on fat-tailed returns.

Writes results to:
  - setup_performance table (upsert, nightly)

Phase 30: Redis write removed. signal_generator_service reads perf_weights
directly from setup_performance table via _load_perf_weights_from_db().
CUSUM adjustments are also applied from drift_state table (not Redis).

Perf multiplier formula (FEED-03 consumption):
  sorted by sharpe_ratio ascending → rank 0..n-1
  perf_multiplier = 0.5 + ((n - 1 - rank) / n_eligible)  → range [0.5, ~1.5]
  Best performer: rank=n-1 → multiplier = 0.5 (LOWEST — sorts first in ascending adjusted_rank)
  Worst performer: rank=0  → multiplier approaches 1.5 (sorts last)

Note: Inverted so best Sharpe gets lowest multiplier, minimising adjusted_rank under ascending sort.
If n_eligible == 1, perf_multiplier = 1.0 for the sole eligible setup.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Minimum 100 samples required; values below 200 are statistically unreliable on fat-tailed returns
MIN_SAMPLE_SIZE = 100  # FEED-02 promotion gate
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
        exit_at = row.get("exit_at") or row.get("resolved_at")
        if exit_at is not None:
            # Ensure timezone-aware comparison
            if exit_at.tzinfo is None:
                exit_at = exit_at.replace(tzinfo=UTC)
            if exit_at <= cutoff:
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


def _compute_perf_multipliers(stats: dict[str, dict]) -> dict[str, tuple[float, int]]:
    """Convert setup stats to perf_multipliers using Sharpe rank.

    Returns dict[setup_plugin, (perf_multiplier, sample_size)] where multipliers
    are in [0.5, 1.5].

    Ascending `adjusted_rank` sort selects the MINIMUM value first.
    Best Sharpe -> multiplier=0.5 -> ranks first (lowest value wins ascending sort).
    Worst Sharpe -> multiplier~1.5 -> ranks last.

    If only one eligible setup, returns {plugin: (1.0, sample_size)}.
    With n=1, a single validated setup receives multiplier=1.0 (neutral), which
    intentionally ranks below an unvalidated setup's warm-up penalty (0.5) under
    ascending sort.

    D-16: This function only returns multipliers for setups with sample_size >= MIN_SAMPLE_SIZE.
    Setups below the threshold get the warm-up penalty (0.5) applied by the ranker.
    """
    if not stats:
        return {}

    plugins = list(stats.keys())
    n = len(plugins)

    if n == 1:
        return {plugins[0]: (1.0, int(stats[plugins[0]].get("sample_size", 30)))}

    # Sort by sharpe_ratio ascending so rank 0 = worst, rank n-1 = best
    sorted_plugins = sorted(plugins, key=lambda p: stats[p]["sharpe_ratio"])
    multipliers: dict[str, tuple[float, int]] = {}
    for rank, plugin in enumerate(sorted_plugins):
        m = 0.5 + ((n - 1 - rank) / n)
        multipliers[plugin] = (m, int(stats[plugin].get("sample_size", 30)))

    return multipliers


async def run_setup_performance_update(
    db_manager: Any,
) -> dict[str, tuple[float, int]]:
    """Read perf weights from setup_performance table (30d rolling window).

    Returns dict[setup_plugin, (perf_multiplier, sample_size)] for all setups
    with sample_size >= MIN_SAMPLE_SIZE. Setups absent from the result have
    sample_size < 30 and the ranker applies the warm-up penalty (0.5, D-16).

    Returns empty dict if no eligible setups (n < MIN_SAMPLE_SIZE).
    """
    rows = await db_manager.execute_query(
        """
        SELECT setup_plugin, win_rate, avg_pnl_r, sample_size, sharpe_ratio
        FROM setup_performance
        WHERE sample_size >= $1
        """,
        MIN_SAMPLE_SIZE,
    )

    if not rows:
        logger.info("setup_performance: no eligible setups (n<%d)", MIN_SAMPLE_SIZE)
        return {}

    stats = {
        row["setup_plugin"]: {
            "win_rate": row["win_rate"],
            "avg_pnl_r": row["avg_pnl_r"],
            "sample_size": row["sample_size"],
            "sharpe_ratio": row["sharpe_ratio"],
        }
        for row in rows
    }

    perf_weights = _compute_perf_multipliers(stats)
    logger.info("setup_performance: loaded %d setups from signal_metrics shim", len(stats))
    return perf_weights
