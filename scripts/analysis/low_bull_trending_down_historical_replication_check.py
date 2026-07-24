"""Does low_bull x trending_down replicate across genuinely independent historical episodes,
not just the current 6.5-month OOS window?

Read-only reporting script, no DB writes. Direct follow-on to two things the user surfaced:
(1) the current OOS window (2025-12-24 to 2026-07-07) contains exactly ONE bear episode
(2026-03 to 2026-06) -- any bear-regime finding from it describes one event, not a
generalizable relationship; (2) market_regimes/forward_returns/feature_vectors.regime all
extend back to 2006, including the 2020 COVID crash and 2022 rate-hike bear market -- multiple
independent historical episodes already sit in the database, uncomputed-for nothing new.

DISCIPLINE, not glossed over: this uses ONLY raw forward_returns + market_regimes +
feature_vectors.regime -- fixed, parameter-free constructs -- NEVER ensemble_alpha/alpha_score,
because the ensemble's weights were trained using data that overlaps this pre-OOS history.
Checking whether the (regime_label, forward_return) relationship replicates historically is a
legitimate robustness check on a fixed measurement; scoring historical data with the trained
weights and calling it "confirmation" would be circular. This script never touches
ensemble_alpha or ensemble_weights.

Splits pre-OOS history into distinct historical episodes (not one pooled blob, which could hide
a positive-here/negative-there cancellation) and evaluates low_bull x trending_down in each
independently, at the same three lookahead scales used all day.

Usage: .venv/bin/python scripts/analysis/low_bull_trending_down_historical_replication_check.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services._batch_utils import cfg as _cfg  # noqa: E402
from services.counterfactual_tracker import (  # noqa: E402
    _DEFAULT_BOOTSTRAP_RANDOM_STATE,
    frame_gate_passes,
)
from src.config.settings import Settings  # noqa: E402

_SCALES = ("fast", "mid", "slow")

# Distinct historical episodes, chosen to avoid pooling genuinely different market eras into
# one blob. Bounds are inclusive start, exclusive end.
_EPISODES = [
    ("2007-01-01", "2009-06-01", "2008 GFC + aftermath"),
    ("2009-06-01", "2012-01-01", "2009-2011 recovery + Euro debt crisis"),
    ("2012-01-01", "2015-01-01", "2012-2014 grind-up"),
    ("2015-01-01", "2016-06-01", "2015-16 correction"),
    ("2016-06-01", "2018-09-01", "2016-2018 grind-up"),
    ("2018-09-01", "2019-06-01", "2018 Q4 selloff + recovery"),
    ("2019-06-01", "2020-02-01", "pre-COVID grind-up"),
    ("2020-02-01", "2020-06-01", "2020 COVID crash"),
    ("2020-06-01", "2022-01-01", "2020-2021 recovery"),
    ("2022-01-01", "2022-10-01", "2022 rate-hike bear market"),
    ("2022-10-01", "2025-12-24", "2022-2025 recovery/grind-up"),
    ("2025-12-24", "2026-07-08", "current OOS window (for reference only)"),
]

_QUERY_SQL = """
    SELECT fr.tf,
           CASE WHEN fr.return_fast_suspect THEN NULL ELSE fr.return_fast END AS return_fast,
           CASE WHEN fr.return_mid_suspect THEN NULL ELSE fr.return_mid END AS return_mid,
           CASE WHEN fr.return_slow_suspect THEN NULL ELSE fr.return_slow END AS return_slow,
           fr.bar_ts::date AS cluster_id
    FROM forward_returns fr
    JOIN market_regimes mr
      ON mr.regime_group = 'equity' AND mr.tf = fr.tf AND mr.ts = fr.bar_ts
    JOIN feature_vectors fv
      ON fv.symbol = fr.symbol AND fv.tf = fr.tf AND fv.bar_ts = fr.bar_ts
    WHERE fr.return_type = 'executable_open_to_open'
      AND fr.tf IN ('5m', '15m')
      AND fr.bar_ts >= $1::timestamptz AND fr.bar_ts < $2::timestamptz
      AND mr.regime_label = 'low_bull'
      AND fv.regime = 'trending_down'
"""


async def _load_apr(conn: asyncpg.Connection) -> tuple[int, int, int]:
    apr_rows = await conn.fetch(
        "SELECT config_key, config_value FROM config_state WHERE config_key LIKE $1",
        "alpha.scoring.%",
    )
    apr_cfg = {row["config_key"]: row["config_value"] for row in apr_rows}
    bootstrap_max_n = _cfg(apr_cfg, "alpha.scoring.bootstrap_max_n", 5000)
    bootstrap_batch = _cfg(apr_cfg, "alpha.scoring.bootstrap_batch", 1000)
    bootstrap_random_state = _cfg(
        apr_cfg, "alpha.scoring.bootstrap_random_state", _DEFAULT_BOOTSTRAP_RANDOM_STATE
    )
    return bootstrap_max_n, bootstrap_batch, bootstrap_random_state


def _evaluate(
    rows: list[dict[str, Any]],
    scale: str,
    bootstrap_max_n: int,
    bootstrap_batch: int,
    bootstrap_random_state: int,
) -> dict[str, Any]:
    return_col = f"return_{scale}"
    valid = [r for r in rows if r[return_col] is not None]
    pnl_r = [r[return_col] for r in valid]
    cluster_ids = [r["cluster_id"] for r in valid]
    passes, ci_lower, ci_upper = frame_gate_passes(
        pnl_r, cluster_ids, 1, bootstrap_max_n, bootstrap_batch, bootstrap_random_state
    )
    return {
        "n": len(pnl_r),
        "n_clusters": len(set(cluster_ids)),
        "mean_r": float(np.mean(pnl_r)) if pnl_r else float("nan"),
        "ci_lower": ci_lower,
        "ci_upper": ci_upper,
        "passes": passes,
    }


async def main() -> None:
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(db_dsn)
    try:
        bootstrap_max_n, bootstrap_batch, bootstrap_random_state = await _load_apr(conn)

        print(
            f"{'episode':<42}{'tf':>4}{'scale':>6}{'n':>8}{'n_clust':>9}"
            f"{'mean_r':>12}{'ci_lower':>12}{'passes':>8}"
        )
        n_pass = 0
        n_evaluated = 0
        for start, end, label in _EPISODES:
            start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=UTC)
            end_dt = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=UTC)
            rows = [dict(r) for r in await conn.fetch(_QUERY_SQL, start_dt, end_dt)]
            for tf in ("5m", "15m"):
                tf_rows = [r for r in rows if r["tf"] == tf]
                if not tf_rows:
                    continue
                for scale in _SCALES:
                    result = _evaluate(
                        tf_rows,
                        scale,
                        bootstrap_max_n,
                        bootstrap_batch,
                        bootstrap_random_state,
                    )
                    if result["n_clusters"] >= 20:
                        n_evaluated += 1
                        if result["passes"]:
                            n_pass += 1
                    print(
                        f"{label:<42}{tf:>4}{scale:>6}{result['n']:>8}"
                        f"{result['n_clusters']:>9}{result['mean_r']:>12.6f}"
                        f"{result['ci_lower']:>12.6f}{str(result['passes']):>8}"
                    )
    finally:
        await conn.close()

    print(f"\n{n_pass}/{n_evaluated} independently-evaluated (episode, tf, scale) cells pass")


if __name__ == "__main__":
    asyncio.run(main())
