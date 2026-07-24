"""Does high_neutral clear a real bootstrap CI once alpha_publisher's regime-blind gate stops
silently truncating its day-cluster coverage?

Read-only reporting script, no DB writes. Direct follow-on to today's (2026-07-24) finding
that Gate 1's pooled-across-regime IC concentrates in high_neutral (83% sign-agreement) while
mid_bull -- the regime dominating trade volume -- is a coin flip (58%). The Tier-1 validation
(regime_eligibility_joint_stratification_validation.py) found high_neutral/15m one day-cluster
short of the coverage floor (19 vs 20) using alpha_frames -- but alpha_frames only contains
bars that ALREADY cleared alpha_publisher's regime-blind CI/cost-hurdle gate. market_regimes
shows 26 distinct high_neutral calendar days exist in the OOS window at 15m (29 at 5m) -- the
gate is silently skipping about a third of them, not a genuine data-scarcity limit.

This script pulls the FULL ungated high_neutral population (every scored ensemble_alpha bar
in a high_neutral day, not just the ones that already fired) joined to raw forward_returns,
and tests two entry rules against the real day-cluster ceiling:
  1. current rule: alpha_score > 0 (what alpha_publisher already does, gate-agnostic version)
  2. within-cell top-half by alpha_score percentile (the regime-relative rule tested earlier
     today, alpha_score_regime_relative_monotonicity_check.py)
across three lookahead horizons (fast/mid/slow) since the regime-decomposed IC check found
high_neutral passes concentrated across multiple scales, not just fast.

Usage: .venv/bin/python scripts/analysis/high_neutral_full_coverage_ci_check.py
"""

from __future__ import annotations

import asyncio
import sys
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

_CHAMPION_WEIGHT_EPOCH = "143.1-08-champion"
_SCALES = ("fast", "mid", "slow")

_FULL_POPULATION_SQL = """
    SELECT ea.tf, ea.alpha_score,
           CASE WHEN fr.return_fast_suspect THEN NULL ELSE fr.return_fast END AS return_fast,
           CASE WHEN fr.return_mid_suspect THEN NULL ELSE fr.return_mid END AS return_mid,
           CASE WHEN fr.return_slow_suspect THEN NULL ELSE fr.return_slow END AS return_slow,
           ea.bar_ts::date AS cluster_id
    FROM ensemble_alpha ea
    JOIN forward_returns fr
      ON fr.symbol = ea.symbol AND fr.tf = ea.tf AND fr.bar_ts = ea.bar_ts
      AND fr.return_type = 'executable_open_to_open'
    JOIN market_regimes mr
      ON mr.regime_group = 'equity' AND mr.tf = ea.tf AND mr.ts = ea.bar_ts
    WHERE ea.weight_version = $1
      AND ea.bar_ts >= $2
      AND mr.regime_label = 'high_neutral'
      AND ea.tf IN ('5m', '15m')
"""


async def _load_apr(conn: asyncpg.Connection) -> tuple[int, int, int, int]:
    apr_rows = await conn.fetch(
        "SELECT config_key, config_value FROM config_state WHERE config_key LIKE ANY($1::text[])",
        ["alpha.scoring.%", "alpha.validation.regime_gate_min_clusters"],
    )
    apr_cfg = {row["config_key"]: row["config_value"] for row in apr_rows}
    bootstrap_max_n = _cfg(apr_cfg, "alpha.scoring.bootstrap_max_n", 5000)
    bootstrap_batch = _cfg(apr_cfg, "alpha.scoring.bootstrap_batch", 1000)
    bootstrap_random_state = _cfg(
        apr_cfg, "alpha.scoring.bootstrap_random_state", _DEFAULT_BOOTSTRAP_RANDOM_STATE
    )
    min_clusters = _cfg(apr_cfg, "alpha.validation.regime_gate_min_clusters", 20)
    return bootstrap_max_n, bootstrap_batch, bootstrap_random_state, min_clusters


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
        (
            bootstrap_max_n,
            bootstrap_batch,
            bootstrap_random_state,
            min_clusters,
        ) = await _load_apr(conn)
        oos_start = await conn.fetchval(
            "SELECT config_value::timestamptz FROM config_state "
            "WHERE config_key = 'alpha.validation.oos_start'"
        )
        rows = [
            dict(r)
            for r in await conn.fetch(_FULL_POPULATION_SQL, _CHAMPION_WEIGHT_EPOCH, oos_start)
        ]
    finally:
        await conn.close()

    print(f"full ungated high_neutral population: {len(rows)} bars across 5m+15m")
    print(f"regime_gate_min_clusters floor: {min_clusters}\n")

    for tf in ("5m", "15m"):
        tf_rows = [r for r in rows if r["tf"] == tf]
        n_days_all = len({r["cluster_id"] for r in tf_rows})
        print(f"=== tf={tf} -- {len(tf_rows)} bars, {n_days_all} distinct days total ===")

        current_rule_rows = [r for r in tf_rows if r["alpha_score"] > 0]
        scores = np.array([r["alpha_score"] for r in tf_rows])
        median = np.median(scores) if len(scores) else 0.0
        top_half_rows = [r for r, s in zip(tf_rows, scores) if s >= median]

        for label, rule_rows in (
            ("current rule (alpha_score>0)", current_rule_rows),
            ("top-half by within-cell percentile", top_half_rows),
        ):
            print(f"  --- {label}, n={len(rule_rows)} ---")
            for scale in _SCALES:
                result = _evaluate(
                    rule_rows, scale, bootstrap_max_n, bootstrap_batch, bootstrap_random_state
                )
                coverage = "OK" if result["n_clusters"] >= min_clusters else "insufficient"
                print(
                    f"    scale={scale:<5} n={result['n']:>6} n_clusters={result['n_clusters']:>3} "
                    f"({coverage:<11}) mean_r={result['mean_r']:>10.6f} "
                    f"ci_lower={result['ci_lower']:>10.6f} ci_upper={result['ci_upper']:>10.6f} "
                    f"passes={result['passes']}"
                )
        print()


if __name__ == "__main__":
    asyncio.run(main())
