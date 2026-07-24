"""Does high_neutral's failure to clear a CI hide a symbol_hmm sub-bucket that DOES?

Read-only reporting script, no DB writes. Direct follow-on to a rigor gap the user caught: every
regime breakdown run today (gate1_pooled_vs_regime_decomposed_ic_check.py,
high_neutral_full_coverage_ci_check.py) used ONLY the cross-sectional regime axis
(market_regimes, regime_group='equity') -- because ensemble_ic_engine.py (Gate 1's own
measurement engine) only ever joins market_regimes, never feature_vectors, so Gate 1's
regime-decomposed evidence has literally never been tested against the per-symbol HMM axis at
all. This matters because a PRE-EXISTING finding (todo 179, before today) already showed
per-symbol HMM state reveals real heterogeneity WITHIN mid_bull (a `ranging` sub-bucket near
breakeven vs. `trending_up`/`transition_down` genuinely bad) that the cross-sectional label
alone blurs. This script checks whether `high_neutral` -- which failed the full-coverage CI
check today at both current-rule and top-half-by-score entry rules, across fast/mid/slow
horizons -- has the same kind of hidden split.

Pulls the full ungated high_neutral population (same as high_neutral_full_coverage_ci_check.py)
joined additionally to feature_vectors.regime (symbol_hmm, forward_filter source), and
evaluates each symbol_hmm sub-bucket's own day-clustered bootstrap CI, at the same three
lookahead scales, under the current entry rule (alpha_score > 0).

Usage: .venv/bin/python scripts/analysis/high_neutral_symbol_hmm_decomposition_check.py
"""

from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
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
    SELECT ea.tf, ea.alpha_score, fv.regime AS symbol_regime,
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
    LEFT JOIN feature_vectors fv
      ON fv.symbol = ea.symbol AND fv.tf = ea.tf AND fv.bar_ts = ea.bar_ts
    WHERE ea.weight_version = $1
      AND ea.bar_ts >= $2
      AND mr.regime_label = 'high_neutral'
      AND ea.tf IN ('5m', '15m')
      AND ea.alpha_score > 0
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

    n_no_symbol_regime = sum(1 for r in rows if r["symbol_regime"] is None)
    print(f"high_neutral, alpha_score>0, full ungated population: {len(rows)} bars")
    print(f"rows with no symbol_hmm label (Layer-1 coverage gap): {n_no_symbol_regime}")
    print(f"regime_gate_min_clusters floor: {min_clusters}\n")

    by_tf_symbolregime: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (row["tf"], row["symbol_regime"] or "(no_hmm_label)")
        by_tf_symbolregime[key].append(row)

    any_pass = False
    for (tf, symbol_regime), cell_rows in sorted(by_tf_symbolregime.items()):
        n_days = len({r["cluster_id"] for r in cell_rows})
        print(
            f"=== tf={tf} symbol_regime={symbol_regime:<16} n={len(cell_rows):>6} "
            f"n_days={n_days:>3} ==="
        )
        for scale in _SCALES:
            result = _evaluate(
                cell_rows, scale, bootstrap_max_n, bootstrap_batch, bootstrap_random_state
            )
            coverage = "OK" if result["n_clusters"] >= min_clusters else "insufficient"
            if result["passes"]:
                any_pass = True
            print(
                f"    scale={scale:<5} n={result['n']:>6} n_clusters={result['n_clusters']:>3} "
                f"({coverage:<11}) mean_r={result['mean_r']:>10.6f} "
                f"ci_lower={result['ci_lower']:>10.6f} passes={result['passes']}"
            )

    print(f"\n=== SUMMARY: any (tf, symbol_regime, scale) cell pass? {any_pass} ===")


if __name__ == "__main__":
    asyncio.run(main())
