"""Does high_bear (under the RECALIBRATED breadth regime signal) replicate across genuinely
independent historical episodes, the same bar low_bull x trending_down failed to clear?

Read-only reporting script, no DB writes. Direct follow-on to
recalibrated_regime_full_sweep_check.py, which found 8/180 cells pass under the recalibrated
(causal-rank, 0.33/0.67) breadth regime labels -- 5 of 8 cluster on high_bear, across both
tf, multiple symbol_hmm sub-states, and multiple scales, a materially more internally
consistent pattern than the earlier (pre-recalibration) low_bull x trending_down finding.

Same discipline as low_bull_trending_down_historical_replication_check.py: uses ONLY raw
forward_returns + recalibrated regime labels (re-derived here from market_regimes'
already-stored raw vix_pct/breadth_frac via the same causal-rank transform, never
ensemble_alpha/alpha_score, which would be circular against pre-OOS training data). Tests
high_bear (pooled across symbol_hmm, and the specific trending_down/trending_up sub-states
that passed in the OOS window) across the same 12 historical episodes used for the
low_bull check.

Usage: .venv/bin/python scripts/analysis/high_bear_recalibrated_historical_replication_check.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services._batch_utils import cfg as _cfg  # noqa: E402
from services.counterfactual_tracker import (  # noqa: E402
    _DEFAULT_BOOTSTRAP_RANDOM_STATE,
    frame_gate_passes,
)
from src.config.settings import Settings  # noqa: E402
from src.intelligence.regime_signals.breadth_vol import _causal_expanding_rank  # noqa: E402

_VIX_TIERS = [("low", 0.33), ("mid", 0.67), ("high", float("inf"))]
_NEW_BREADTH_TIERS = [("bear", 0.33), ("neutral", 0.67), ("bull", float("inf"))]
_SCALES = ("fast", "mid", "slow")

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
    ("2025-12-24", "2026-07-08", "current OOS window (recalibrated)"),
]

_REGIME_SIGNAL_SQL = """
    SELECT ts,
           (regime_prob_vector->>'vix_pct')::double precision AS vix_pct,
           (regime_prob_vector->>'breadth_frac')::double precision AS breadth_frac
    FROM market_regimes
    WHERE regime_group = 'equity' AND tf = $1
    ORDER BY ts
"""

_RETURNS_SQL = """
    SELECT fr.bar_ts, fv.regime AS symbol_regime,
           CASE WHEN fr.return_fast_suspect THEN NULL ELSE fr.return_fast END AS return_fast,
           CASE WHEN fr.return_mid_suspect THEN NULL ELSE fr.return_mid END AS return_mid,
           CASE WHEN fr.return_slow_suspect THEN NULL ELSE fr.return_slow END AS return_slow,
           fr.bar_ts::date AS cluster_id
    FROM forward_returns fr
    LEFT JOIN feature_vectors fv
      ON fv.symbol = fr.symbol AND fv.tf = fr.tf AND fv.bar_ts = fr.bar_ts
    WHERE fr.return_type = 'executable_open_to_open'
      AND fr.tf = $1
"""


def _bucket(vals: np.ndarray, tiers: list[tuple[str, float]]) -> np.ndarray:
    result = np.full(len(vals), tiers[-1][0], dtype=object)
    for name, upper in reversed(tiers[:-1]):
        result = np.where(vals < upper, name, result)
    return result


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

        for tf in ("5m", "15m"):
            print(f"\n########## tf={tf} ##########")
            rows = await conn.fetch(_REGIME_SIGNAL_SQL, tf)
            ts_list = [r["ts"] for r in rows]
            vix_pct = np.array([r["vix_pct"] for r in rows], dtype=float)
            breadth_frac = pd.Series([r["breadth_frac"] for r in rows], index=ts_list, dtype=float)
            breadth_pct = _causal_expanding_rank(breadth_frac).to_numpy()
            vix_label = _bucket(vix_pct, _VIX_TIERS)
            breadth_label = _bucket(breadth_pct, _NEW_BREADTH_TIERS)
            is_high_bear = {
                t: (v == "high" and b == "bear")
                for t, v, b in zip(ts_list, vix_label, breadth_label)
            }

            return_rows = [dict(r) for r in await conn.fetch(_RETURNS_SQL, tf)]
            high_bear_rows = [r for r in return_rows if is_high_bear.get(r["bar_ts"], False)]

            print(
                f"{'episode':<42}{'n':>8}{'n_clust':>9}{'scale':>6}"
                f"{'mean_r':>12}{'ci_lower':>12}{'passes':>8}"
            )
            n_pass = 0
            n_evaluated = 0
            for start, end, label in _EPISODES:
                start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=UTC)
                end_dt = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=UTC)
                episode_rows = [r for r in high_bear_rows if start_dt <= r["bar_ts"] < end_dt]
                if not episode_rows:
                    continue
                for scale in _SCALES:
                    result = _evaluate(
                        episode_rows,
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
                        f"{label:<42}{result['n']:>8}{result['n_clusters']:>9}{scale:>6}"
                        f"{result['mean_r']:>12.6f}{result['ci_lower']:>12.6f}"
                        f"{str(result['passes']):>8}"
                    )
            print(
                f"\n{n_pass}/{n_evaluated} independently-evaluated (episode, scale) cells pass for tf={tf}"
            )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
