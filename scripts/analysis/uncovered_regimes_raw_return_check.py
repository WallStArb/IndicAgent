"""Do the 4 regimes the ensemble has ZERO eligible features for have any real forward-return
edge at all, independent of the current ensemble's alpha_score?

Read-only reporting script, no DB writes. Direct follow-on to a rigor gap the user caught:
there are 9 architectural cross-sectional regime labels (market_regimes.regime_label,
regime_group='equity'), but ensemble_weights has rows for only 5 of them
(high_bear/high_neutral/low_bull/mid_bull/mid_neutral) -- ensemble_trainer.py never found an
eligible feature for high_bull/low_bear/low_neutral/mid_bear, so alpha_score is architecturally
always ~0 there. Every check run today (including the supposedly "all regimes" symbol_hmm
decomposition) filtered on alpha_score > 0, which silently excluded these 4 regimes entirely --
not because they were tested and failed, but because the current ensemble is structurally blind
to them. This checks whether real, un-barriered forward-return edge exists in these 4 regimes
regardless of what the current ensemble can see -- a genuinely different question from
everything else run today (which all conditioned on the CURRENT ensemble's own score).

Population: raw forward_returns for every symbol/bar in the OOS window whose cross-sectional
regime is one of the 4 zero-eligible-feature regimes, decomposed by symbol_hmm regime (the same
axis todo 179's recursive check applied elsewhere). No alpha_score filter at all -- this tests
whether the market itself shows a directional (long) edge there, not whether this ensemble's
specific score construction can find it.

Usage: .venv/bin/python scripts/analysis/uncovered_regimes_raw_return_check.py
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

_UNCOVERED_REGIMES = ("high_bull", "low_bear", "low_neutral", "mid_bear")
_SCALES = ("fast", "mid", "slow")

_RAW_POPULATION_SQL = """
    SELECT fr.symbol, fr.tf, mr.regime_label AS cross_regime, fv.regime AS symbol_regime,
           CASE WHEN fr.return_fast_suspect THEN NULL ELSE fr.return_fast END AS return_fast,
           CASE WHEN fr.return_mid_suspect THEN NULL ELSE fr.return_mid END AS return_mid,
           CASE WHEN fr.return_slow_suspect THEN NULL ELSE fr.return_slow END AS return_slow,
           fr.bar_ts::date AS cluster_id
    FROM forward_returns fr
    JOIN market_regimes mr
      ON mr.regime_group = 'equity' AND mr.tf = fr.tf AND mr.ts = fr.bar_ts
    LEFT JOIN feature_vectors fv
      ON fv.symbol = fr.symbol AND fv.tf = fr.tf AND fv.bar_ts = fr.bar_ts
    WHERE fr.return_type = 'executable_open_to_open'
      AND fr.tf IN ('5m', '15m')
      AND fr.bar_ts >= $1
      AND mr.regime_label = ANY($2::text[])
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
            for r in await conn.fetch(_RAW_POPULATION_SQL, oos_start, list(_UNCOVERED_REGIMES))
        ]
    finally:
        await conn.close()

    print(
        f"raw forward_returns, uncovered regimes {_UNCOVERED_REGIMES}, "
        f"no ensemble_alpha filter: {len(rows)} bars"
    )
    print(f"regime_gate_min_clusters floor: {min_clusters}\n")

    by_cell: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (row["tf"], row["cross_regime"], row["symbol_regime"] or "(no_hmm_label)")
        by_cell[key].append(row)

    print("distinct (tf, cross_regime) cells with any data: ", end="")
    print(sorted({(k[0], k[1]) for k in by_cell}))
    print()

    all_results: list[dict[str, Any]] = []
    for (tf, cross_regime, symbol_regime), cell_rows in sorted(by_cell.items()):
        n_days = len({r["cluster_id"] for r in cell_rows})
        for scale in _SCALES:
            result = _evaluate(
                cell_rows, scale, bootstrap_max_n, bootstrap_batch, bootstrap_random_state
            )
            all_results.append(
                {
                    "tf": tf,
                    "cross_regime": cross_regime,
                    "symbol_regime": symbol_regime,
                    "scale": scale,
                    "n_days": n_days,
                    **result,
                }
            )

    evaluated = [r for r in all_results if r["n_clusters"] >= min_clusters]
    passing = [r for r in evaluated if r["passes"]]

    print(f"total cells tested: {len(all_results)}")
    print(f"cells with sufficient day-cluster coverage: {len(evaluated)}")
    print(f"cells that PASS (ci_lower > 0): {len(passing)}\n")

    if passing:
        print("=== PASSING CELLS ===")
        for r in passing:
            print(
                f"  tf={r['tf']} cross_regime={r['cross_regime']} "
                f"symbol_regime={r['symbol_regime']} scale={r['scale']} n={r['n']} "
                f"n_clusters={r['n_clusters']} mean_r={r['mean_r']:.6f} "
                f"ci_lower={r['ci_lower']:.6f}"
            )
    else:
        print("=== NO PASSING CELLS ===")
        print("Closest 5 cells by ci_lower (least negative), among evaluated (coverage OK):")
        for r in sorted(evaluated, key=lambda r: -r["ci_lower"])[:5]:
            print(
                f"  tf={r['tf']} cross_regime={r['cross_regime']} "
                f"symbol_regime={r['symbol_regime']} scale={r['scale']} n={r['n']} "
                f"n_clusters={r['n_clusters']} mean_r={r['mean_r']:.6f} "
                f"ci_lower={r['ci_lower']:.6f}"
            )


if __name__ == "__main__":
    asyncio.run(main())
