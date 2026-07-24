"""Does splitting high_bear by longer-horizon trend context separate "buyable dip" from
"structural bear market"?

Read-only reporting script, no DB writes. Direct follow-on to
high_bear_recalibrated_historical_replication_check.py's finding: high_bear (recalibrated,
causal-rank breadth) passes cleanly in non-crisis "dip within an uptrend" episodes
(2016-2018 grind-up, 2020-2021 recovery) and fails cleanly in every genuine structural bear
market (2008 GFC, 2018 Q4 selloff, 2020 COVID crash, 2022 rate-hike bear market) -- a pattern
too clean to be noise, but not yet a tradeable rule since the current 9-cell cross-sectional
taxonomy has no dimension to tell these two cases apart in real time.

Hypothesis: the same 200-bar-scaled MA already used for the breadth signal itself
(alpha.equity_regime.ma_window) can distinguish them directly -- is SPY's own close above or
below its own long-horizon trailing MA at this timestamp? A "dip within an uptrend" should
show SPY still above its long MA (temporary vol spike, longer trend intact); a "structural
bear market" should show SPY below its long MA (the longer trend itself has broken). Fully
causal (trailing MA only, matches the existing ma_window convention via _tf_window) -- no
look-ahead.

Splits high_bear bars into (spy_above_long_ma, spy_below_long_ma) and re-runs the same
day-clustered bootstrap CI test, per historical episode, per split -- reusing frame_gate_passes
verbatim. Raw forward_returns only, never ensemble_alpha (circular against pre-OOS training
data, same discipline as every other script today).

Usage: .venv/bin/python scripts/analysis/high_bear_trend_context_split_check.py
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
from src.intelligence.regime_signals.tf_window import _tf_window  # noqa: E402

_VIX_TIERS = [("low", 0.33), ("mid", 0.67), ("high", float("inf"))]
_NEW_BREADTH_TIERS = [("bear", 0.33), ("neutral", 0.67), ("bull", float("inf"))]
_SCALES = ("fast", "mid", "slow")
_MA_DAILY_WINDOW = 200  # matches alpha.equity_regime.ma_window's own default

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
    ("2025-12-24", "2026-07-08", "current OOS window"),
]

_REGIME_SIGNAL_SQL = """
    SELECT ts,
           (regime_prob_vector->>'vix_pct')::double precision AS vix_pct,
           (regime_prob_vector->>'breadth_frac')::double precision AS breadth_frac
    FROM market_regimes
    WHERE regime_group = 'equity' AND tf = $1
    ORDER BY ts
"""

_SPY_CLOSE_SQL = """
    SELECT timestamp AS ts, close
    FROM market_data_ohlcv_tradeable
    WHERE symbol = 'SPY' AND timeframe = $1
    ORDER BY timestamp
"""

_RETURNS_SQL = """
    SELECT fr.bar_ts, fr.bar_ts::date AS cluster_id,
           CASE WHEN fr.return_fast_suspect THEN NULL ELSE fr.return_fast END AS return_fast,
           CASE WHEN fr.return_mid_suspect THEN NULL ELSE fr.return_mid END AS return_mid,
           CASE WHEN fr.return_slow_suspect THEN NULL ELSE fr.return_slow END AS return_slow
    FROM forward_returns fr
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

            # Recalibrated high_bear label per ts.
            regime_rows = await conn.fetch(_REGIME_SIGNAL_SQL, tf)
            ts_list = [r["ts"] for r in regime_rows]
            vix_pct = np.array([r["vix_pct"] for r in regime_rows], dtype=float)
            breadth_frac = pd.Series(
                [r["breadth_frac"] for r in regime_rows], index=ts_list, dtype=float
            )
            breadth_pct = _causal_expanding_rank(breadth_frac).to_numpy()
            vix_label = _bucket(vix_pct, _VIX_TIERS)
            breadth_label = _bucket(breadth_pct, _NEW_BREADTH_TIERS)
            is_high_bear = {
                t: (v == "high" and b == "bear")
                for t, v, b in zip(ts_list, vix_label, breadth_label)
            }

            # SPY's own causal trailing MA -- trend-context filter.
            spy_rows = await conn.fetch(_SPY_CLOSE_SQL, tf)
            spy_ts = [r["ts"] for r in spy_rows]
            spy_close = pd.Series([r["close"] for r in spy_rows], index=spy_ts, dtype=float)
            ma_window = _tf_window(_MA_DAILY_WINDOW, tf)
            spy_ma = spy_close.rolling(window=ma_window, min_periods=ma_window).mean()
            spy_above_ma = (spy_close > spy_ma).to_dict()

            return_rows = [dict(r) for r in await conn.fetch(_RETURNS_SQL, tf)]
            high_bear_rows = [r for r in return_rows if is_high_bear.get(r["bar_ts"], False)]
            for r in high_bear_rows:
                r["trend_context"] = spy_above_ma.get(r["bar_ts"])

            above_rows = [r for r in high_bear_rows if r["trend_context"] is True]
            below_rows = [r for r in high_bear_rows if r["trend_context"] is False]
            n_unknown_trend = sum(1 for r in high_bear_rows if r["trend_context"] is None)
            print(
                f"high_bear bars: {len(high_bear_rows)} total, "
                f"{len(above_rows)} SPY-above-long-MA, {len(below_rows)} SPY-below-long-MA, "
                f"{n_unknown_trend} unknown (MA warmup)\n"
            )

            for split_label, split_rows in (
                ("SPY ABOVE long MA (dip-in-uptrend hypothesis)", above_rows),
                ("SPY BELOW long MA (structural-bear hypothesis)", below_rows),
            ):
                print(f"--- {split_label} ---")
                print(
                    f"{'episode':<42}{'n':>8}{'n_clust':>9}{'scale':>6}"
                    f"{'mean_r':>12}{'ci_lower':>12}{'passes':>8}"
                )
                n_pass = 0
                n_evaluated = 0
                for start, end, label in _EPISODES:
                    start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=UTC)
                    end_dt = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=UTC)
                    episode_rows = [r for r in split_rows if start_dt <= r["bar_ts"] < end_dt]
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
                print(f"{n_pass}/{n_evaluated} cells pass for this split\n")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
