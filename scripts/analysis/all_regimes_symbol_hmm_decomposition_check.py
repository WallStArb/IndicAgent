"""Full-rigor check: does ANY (cross_sectional_regime, symbol_hmm_regime, tf, scale) cell
clear a real bootstrap CI, across every cross-sectional regime, not just high_neutral/mid_bull?

Read-only reporting script, no DB writes. Generalizes
high_neutral_symbol_hmm_decomposition_check.py to every cross-sectional regime -- a rigor gap
the user caught: every regime breakdown run earlier today used ONLY the cross-sectional axis
(ensemble_ic_engine.py, Gate 1's own measurement engine, never joins feature_vectors), and the
one PRE-EXISTING per-symbol-HMM finding (todo 179, before today: mid_bull's `ranging`
sub-bucket looked "near breakeven" vs. `trending_up`/`transition_down`) was based on naive
per-trade averaging against the GATED alpha_frames population, not this session's full-coverage
day-clustered bootstrap methodology. This re-checks that finding under the same rigor applied
everywhere else today, and extends it to every regime, not just the ones that looked promising
under weaker methods.

Population: full ungated ensemble_alpha (every scored bar, not just alpha_publisher's
gate-passing subset) joined to forward_returns (return_type='executable_open_to_open', todo 148
suspect-masked) and feature_vectors.regime (symbol_hmm), for the champion weight_version, OOS
window, tf in (5m, 15m). Current entry rule (alpha_score > 0) only -- this is a coverage/
existence check ("is there ANY cell with real edge"), not an entry-rule optimization.

Usage: .venv/bin/python scripts/analysis/all_regimes_symbol_hmm_decomposition_check.py
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
    SELECT ea.tf, mr.regime_label AS cross_regime, fv.regime AS symbol_regime,
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

    print(f"full ungated population, alpha_score>0, all cross-sectional regimes: {len(rows)} bars")
    print(f"regime_gate_min_clusters floor: {min_clusters}\n")

    by_cell: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (row["tf"], row["cross_regime"], row["symbol_regime"] or "(no_hmm_label)")
        by_cell[key].append(row)

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

    print(f"total (tf, cross_regime, symbol_regime, scale) cells tested: {len(all_results)}")
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

    print(
        f"\n=== VERDICT: across every cross-sectional regime x symbol_hmm sub-state x scale "
        f"tested (full ungated population, current entry rule), "
        f"{'a real, statistically defensible cell exists' if passing else 'NOTHING clears a bootstrap CI'} ==="
    )


if __name__ == "__main__":
    asyncio.run(main())
