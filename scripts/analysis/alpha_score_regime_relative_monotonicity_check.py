"""Does alpha_score carry real, exploitable rank information once regime drift is netted out?

Read-only reporting script, no DB writes. Reuses counterfactual_tracker.py's
frame_gate_passes verbatim (no reimplementation) for the day-clustered bootstrap CI.

Motivation: Gate 1 (EIC-04, ops_ensemble_ic_gate.py) measures per-(symbol, tf, regime)
Spearman rank-IC between alpha_score and forward_return -- 140/640 cells (21.875%) qualify,
a real pass. Gate 2 (frame simulation) fails everywhere the regime-eligibility validation
tested (see this repo's regime_eligibility_joint_stratification_validation.py, 2026-07-24):
zero cells clear a positive bootstrap CI, even the buckets that looked best under naive
averaging.

Spearman rank-IC is invariant to any common (monotonic) shift applied uniformly to every
observation in the sample it's computed over. alpha_publisher's emission gate fires on an
ABSOLUTE threshold (`alpha_score > 0 AND alpha_ci_lower > cost_hurdle`), not a
regime/symbol-relative one. If a symbol's own regime-restricted forward-return distribution
has a substantial common negative level (which the raw un-barriered mid_bull check already
established is real -- return_fast/mid/slow all negative on average), a real, IC-significant
WITHIN-symbol rank relationship (higher score -> relatively less-bad return) can coexist with
an absolute-threshold rule losing money on every fire, because "relatively less bad" can still
be negative in absolute terms.

This script tests directly whether that's what's happening: for each (symbol, tf, regime)
cell with enough bars, converts alpha_score to a WITHIN-cell percentile rank (so a symbol's own
score distribution during its own regime history is what's being ranked -- no cross-symbol
scale contamination, no absolute global threshold), splits into top-half vs bottom-half by
that percentile, pools across symbols within each (tf, regime), and bootstraps each half's mean
raw forward_return_fast (return_type='executable_open_to_open', todo 148 suspect-masked)
separately.

Two possible outcomes:
  - Top half's CI clears positive (or is meaningfully less negative than bottom half's, with
    non-overlapping CIs): real, tradeable regime/symbol-relative timing information exists --
    the fix is a regime-relative entry threshold, not a signal or feature problem.
  - Top and bottom halves are statistically indistinguishable (or top is worse): the
    IC-significant relationship is too weak/noisy to build a threshold rule around at this
    horizon -- points toward needing better features/signal (Phase 164/165) rather than a
    construction fix.

Usage: .venv/bin/python scripts/analysis/alpha_score_regime_relative_monotonicity_check.py
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
_MIN_CELL_N = 20  # minimum bars in a (symbol, tf, regime) cell to bother ranking it

_UNGATED_QUERY_SQL = """
    SELECT ea.symbol, ea.tf, ea.bar_ts, ea.alpha_score,
           CASE WHEN fr.return_fast_suspect THEN NULL ELSE fr.return_fast END AS return_fast,
           mr.regime_label AS regime,
           ea.bar_ts::date AS cluster_id
    FROM ensemble_alpha ea
    JOIN forward_returns fr
      ON fr.symbol = ea.symbol AND fr.tf = ea.tf AND fr.bar_ts = ea.bar_ts
      AND fr.return_type = 'executable_open_to_open'
    JOIN market_regimes mr
      ON mr.regime_group = 'equity' AND mr.tf = ea.tf AND mr.ts = ea.bar_ts
    WHERE ea.weight_version = $1
      AND ea.bar_ts >= $2
      AND fr.return_fast IS NOT NULL
      AND NOT fr.return_fast_suspect
    ORDER BY ea.symbol, ea.tf, ea.bar_ts
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


def _within_cell_half_split(rows: list[dict[str, Any]]) -> None:
    """Mutates each row in place, adding a 'half' key: 'top' or 'bottom', based on
    alpha_score's percentile rank WITHIN its own (symbol, tf, regime) group."""
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["symbol"], row["tf"], row["regime"])].append(row)
    for group_rows in groups.values():
        if len(group_rows) < _MIN_CELL_N:
            for row in group_rows:
                row["half"] = None
            continue
        scores = np.array([r["alpha_score"] for r in group_rows])
        median = np.median(scores)
        for row, score in zip(group_rows, scores):
            row["half"] = "top" if score >= median else "bottom"


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
        if oos_start is None:
            raise RuntimeError("alpha.validation.oos_start is not set in config_state")
        rows = [
            dict(r) for r in await conn.fetch(_UNGATED_QUERY_SQL, _CHAMPION_WEIGHT_EPOCH, oos_start)
        ]
    finally:
        await conn.close()

    print(f"weight_version={_CHAMPION_WEIGHT_EPOCH}  oos_start={oos_start}")
    print(f"total (symbol, tf, bar_ts) rows fetched: {len(rows)}\n")

    _within_cell_half_split(rows)
    ranked_rows = [r for r in rows if r["half"] is not None]
    n_excluded_small_cell = len(rows) - len(ranked_rows)
    print(f"rows excluded (cell smaller than {_MIN_CELL_N} bars): {n_excluded_small_cell}\n")

    by_tf_regime: dict[tuple[str, str], dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"top": [], "bottom": []}
    )
    for row in ranked_rows:
        by_tf_regime[(row["tf"], row["regime"])][row["half"]].append(row)

    print(
        f"{'tf':>4} {'regime':<14} {'half':<7} {'n':>7} {'n_clust':>8} "
        f"{'mean_r':>10} {'ci_lower':>10} {'ci_upper':>10} {'passes':>7}"
    )
    results: dict[tuple[str, str], dict[str, Any]] = {}
    for (tf, regime), halves in sorted(by_tf_regime.items()):
        cell_result: dict[str, Any] = {}
        for half in ("top", "bottom"):
            half_rows = halves[half]
            if not half_rows:
                continue
            pnl_r = [r["return_fast"] for r in half_rows]
            cluster_ids = [r["cluster_id"] for r in half_rows]
            passes, ci_lower, ci_upper = frame_gate_passes(
                pnl_r, cluster_ids, 1, bootstrap_max_n, bootstrap_batch, bootstrap_random_state
            )
            mean_r = float(np.mean(pnl_r))
            n_clusters = len(set(cluster_ids))
            cell_result[half] = {
                "n": len(pnl_r),
                "n_clusters": n_clusters,
                "mean_r": mean_r,
                "ci_lower": ci_lower,
                "ci_upper": ci_upper,
                "passes": passes,
            }
            print(
                f"{tf:>4} {regime:<14} {half:<7} {len(pnl_r):>7} {n_clusters:>8} "
                f"{mean_r:>10.6f} {ci_lower:>10.6f} {ci_upper:>10.6f} {str(passes):>7}"
            )
        results[(tf, regime)] = cell_result

    print("\n=== MONOTONICITY SUMMARY (top mean_r vs bottom mean_r, by cell) ===")
    n_monotonic = 0
    n_cells_with_both = 0
    n_top_ci_positive = 0
    for (tf, regime), cell_result in sorted(results.items()):
        if "top" not in cell_result or "bottom" not in cell_result:
            continue
        n_cells_with_both += 1
        top_mean = cell_result["top"]["mean_r"]
        bottom_mean = cell_result["bottom"]["mean_r"]
        monotonic = top_mean > bottom_mean
        n_monotonic += monotonic
        if cell_result["top"]["passes"]:
            n_top_ci_positive += 1
        print(
            f"  tf={tf:>3} regime={regime:<14} top_mean={top_mean:>10.6f} "
            f"bottom_mean={bottom_mean:>10.6f} monotonic(top>bottom)={monotonic} "
            f"top_ci_lower={cell_result['top']['ci_lower']:>10.6f}"
        )

    print(
        f"\n{n_monotonic}/{n_cells_with_both} cells show top>bottom mean return "
        f"(within-symbol, within-regime relative ranking)"
    )
    print(f"{n_top_ci_positive}/{n_cells_with_both} cells have top-half ci_lower > 0")

    if n_monotonic >= max(1, int(0.7 * n_cells_with_both)) and n_top_ci_positive == 0:
        print(
            "\nVERDICT: real, consistent within-symbol/within-regime rank information exists "
            "(top beats bottom almost everywhere) but even the top half doesn't clear a "
            "positive bootstrap CI in absolute terms -- the regime-level common drift is too "
            "large relative to the score's discriminating power to flip to a net-positive "
            "absolute return just by picking the better half. A regime-relative threshold "
            "reduces losses but does not, on this evidence, produce a profitable rule on its "
            "own. This argues for improving signal magnitude/features (Phase 164/165), not "
            "just recalibrating the entry threshold."
        )
    elif n_top_ci_positive > 0:
        print(
            "\nVERDICT: at least one cell's top half clears a positive bootstrap CI -- real, "
            "exploitable regime-relative timing information exists somewhere. Worth building a "
            "regime/symbol-relative entry threshold (percentile-based, not global alpha_score>0) "
            "for the passing cell(s) rather than assuming the whole branch is dead."
        )
    else:
        print(
            "\nVERDICT: no consistent top>bottom separation -- the per-symbol IC gate's pass is "
            "not translating into an exploitable rank signal via a simple threshold split at "
            "this horizon. Does not rule out IC being real in a subtler (e.g. nonlinear, "
            "multi-horizon) sense, but a simple regime-relative threshold fix is not supported "
            "by this evidence."
        )


if __name__ == "__main__":
    asyncio.run(main())
