"""Re-run today's full 9-regime x symbol_hmm x scale sweep using the RECALIBRATED breadth
regime labels (todo 092 fix), entirely offline -- no production market_regimes write.

Read-only reporting script, no DB writes. Direct follow-on to
recalibrated_breadth_regime_relabel_check.py's population-balance confirmation. Re-derives
cross-sectional regime labels from market_regimes.regime_prob_vector's already-stored raw
vix_pct/breadth_frac values, using the fixed causal-rank breadth signal (migration 257) and
0.33/0.67 cuts on both axes, then re-runs the exact same day-clustered-bootstrap sweep as
all_regimes_symbol_hmm_decomposition_check.py / uncovered_regimes_raw_return_check.py against
raw forward_returns (no alpha_score/ensemble_alpha dependency -- avoids the same circularity
concern already established today), crossed with feature_vectors.regime (symbol_hmm), for the
current OOS window.

Usage: .venv/bin/python scripts/analysis/recalibrated_regime_full_sweep_check.py
"""

from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
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

_REGIME_SIGNAL_SQL = """
    SELECT ts,
           (regime_prob_vector->>'vix_pct')::double precision AS vix_pct,
           (regime_prob_vector->>'breadth_frac')::double precision AS breadth_frac
    FROM market_regimes
    WHERE regime_group = 'equity' AND tf = $1
    ORDER BY ts
"""

_RETURNS_SQL = """
    SELECT fr.tf, fr.bar_ts, fv.regime AS symbol_regime,
           CASE WHEN fr.return_fast_suspect THEN NULL ELSE fr.return_fast END AS return_fast,
           CASE WHEN fr.return_mid_suspect THEN NULL ELSE fr.return_mid END AS return_mid,
           CASE WHEN fr.return_slow_suspect THEN NULL ELSE fr.return_slow END AS return_slow,
           fr.bar_ts::date AS cluster_id
    FROM forward_returns fr
    LEFT JOIN feature_vectors fv
      ON fv.symbol = fr.symbol AND fv.tf = fr.tf AND fv.bar_ts = fr.bar_ts
    WHERE fr.return_type = 'executable_open_to_open'
      AND fr.tf IN ('5m', '15m')
      AND fr.bar_ts >= $1
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
        oos_start = await conn.fetchval(
            "SELECT config_value::timestamptz FROM config_state "
            "WHERE config_key = 'alpha.validation.oos_start'"
        )

        # Recompute recalibrated regime label per (tf, ts), full history (causal rank needs
        # the whole preceding series, not just the OOS window).
        new_label_by_tf_ts: dict[tuple[str, Any], str] = {}
        for tf in ("5m", "15m"):
            rows = await conn.fetch(_REGIME_SIGNAL_SQL, tf)
            ts_list = [r["ts"] for r in rows]
            vix_pct = np.array([r["vix_pct"] for r in rows], dtype=float)
            breadth_frac = pd.Series([r["breadth_frac"] for r in rows], index=ts_list, dtype=float)
            breadth_pct = _causal_expanding_rank(breadth_frac).to_numpy()

            vix_label = _bucket(vix_pct, _VIX_TIERS)
            breadth_label = _bucket(breadth_pct, _NEW_BREADTH_TIERS)
            for t, v, b in zip(ts_list, vix_label, breadth_label):
                new_label_by_tf_ts[(tf, t)] = f"{v}_{b}"

        print(f"recomputed {len(new_label_by_tf_ts)} recalibrated (tf, ts) regime labels\n")

        return_rows = [dict(r) for r in await conn.fetch(_RETURNS_SQL, oos_start)]
    finally:
        await conn.close()

    by_cell: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    n_unmatched = 0
    for row in return_rows:
        new_regime = new_label_by_tf_ts.get((row["tf"], row["bar_ts"]))
        if new_regime is None:
            n_unmatched += 1
            continue
        key = (row["tf"], new_regime, row["symbol_regime"] or "(no_hmm_label)")
        by_cell[key].append(row)

    print(
        f"forward_returns rows: {len(return_rows)}, unmatched to a recalibrated ts: {n_unmatched}\n"
    )

    all_results: list[dict[str, Any]] = []
    for (tf, cross_regime, symbol_regime), cell_rows in sorted(by_cell.items()):
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
                    **result,
                }
            )

    evaluated = [r for r in all_results if r["n_clusters"] >= 20]
    passing = [r for r in evaluated if r["passes"]]

    print(f"total cells tested: {len(all_results)}")
    print(f"cells with sufficient day-cluster coverage: {len(evaluated)}")
    print(f"cells that PASS (ci_lower > 0): {len(passing)}\n")

    if passing:
        print("=== PASSING CELLS (under RECALIBRATED regime labels) ===")
        for r in passing:
            print(
                f"  tf={r['tf']} cross_regime={r['cross_regime']} "
                f"symbol_regime={r['symbol_regime']} scale={r['scale']} n={r['n']} "
                f"n_clusters={r['n_clusters']} mean_r={r['mean_r']:.6f} "
                f"ci_lower={r['ci_lower']:.6f}"
            )
    else:
        print("=== NO PASSING CELLS ===")
        print("Closest 8 cells by ci_lower (least negative), among evaluated (coverage OK):")
        for r in sorted(evaluated, key=lambda r: -r["ci_lower"])[:8]:
            print(
                f"  tf={r['tf']} cross_regime={r['cross_regime']} "
                f"symbol_regime={r['symbol_regime']} scale={r['scale']} n={r['n']} "
                f"n_clusters={r['n_clusters']} mean_r={r['mean_r']:.6f} "
                f"ci_lower={r['ci_lower']:.6f}"
            )


if __name__ == "__main__":
    asyncio.run(main())
