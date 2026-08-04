"""143.1-08 Shadow Validation: Component E (sign-symmetric eligibility) criteria 1,2,3,4,6,7.

Read-only reporting script. Reuses counterfactual_tracker.py's frame_gate_passes verbatim (no
reimplementation) per 143.1-08-SHADOW-VALIDATION.md Section 3's pre-committed rule. Criterion 5
is N/A this round (Section 3a correction -- no recurring ensemble_ic_engine cadence exists yet
to form a trailing-vs-full-period split).

Usage: .venv/bin/python scripts/analysis/phase143_1_08_shadow_validation.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services._batch_utils import cfg as _cfg  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.intelligence.statistics.gate_math import (  # noqa: E402
    _DEFAULT_BOOTSTRAP_RANDOM_STATE,
    evaluate_frame_gate,
    frame_gate_passes,
)

_OOS_QUERY_SQL = """
    SELECT bar_ts, direction, regime, bar_ts::date AS cluster_id, counterfactual_pnl_r AS pnl_r
    FROM alpha_frames
    WHERE weight_epoch = $1
      AND frame_variant = 'primary'
      AND status != 'open'
      AND bar_ts >= $2
      AND counterfactual_pnl_r IS NOT NULL
    ORDER BY bar_ts ASC
"""


def _max_drawdown(pnl_r_ordered: np.ndarray) -> tuple[float | None, bool]:
    """Max peak-to-trough decline of the cumulative-R equity curve.

    Returns (drawdown_ratio_or_None, fails). WR-03 frozen edge case: if the running peak
    cumulative R at the point of max decline is <= 0, this criterion fails outright
    regardless of the ratio (a "drawdown" from a non-positive peak is not meaningful).
    """
    cum = np.cumsum(pnl_r_ordered)
    peak = np.maximum.accumulate(cum)
    decline = peak - cum
    trough_idx = int(np.argmax(decline))
    peak_at_trough = float(peak[trough_idx])
    if peak_at_trough <= 0:
        return None, True
    dd = float(decline[trough_idx] / peak_at_trough)
    return dd, dd >= 0.25


def _annualized_sharpe(pnl_r_ordered: list[float], bar_ts_ordered: list[Any]) -> float | None:
    """Annualized Sharpe of per-trading-day pooled mean counterfactual_pnl_r."""
    df = pd.DataFrame({"day": pd.to_datetime(bar_ts_ordered).date, "pnl_r": pnl_r_ordered})
    daily = df.groupby("day")["pnl_r"].mean()
    if len(daily) < 2 or daily.std(ddof=1) == 0:
        return None
    return float(daily.mean() / daily.std(ddof=1) * np.sqrt(252))


async def _load_apr(conn: asyncpg.Connection) -> tuple[int, int, int, int, int]:
    apr_rows = await conn.fetch(
        "SELECT config_key, config_value FROM config_state WHERE config_key LIKE ANY($1::text[])",
        ["alpha.scoring.%", "alpha.validation.regime_gate_min_clusters"],
    )
    apr_cfg = {row["config_key"]: row["config_value"] for row in apr_rows}
    min_n = _cfg(apr_cfg, "alpha.scoring.min_strategy_n", 30)
    bootstrap_max_n = _cfg(apr_cfg, "alpha.scoring.bootstrap_max_n", 5000)
    bootstrap_batch = _cfg(apr_cfg, "alpha.scoring.bootstrap_batch", 1000)
    bootstrap_random_state = _cfg(
        apr_cfg, "alpha.scoring.bootstrap_random_state", _DEFAULT_BOOTSTRAP_RANDOM_STATE
    )
    regime_gate_min_clusters = _cfg(apr_cfg, "alpha.validation.regime_gate_min_clusters", 20)
    return min_n, bootstrap_max_n, bootstrap_batch, bootstrap_random_state, regime_gate_min_clusters


async def evaluate_epoch(
    conn: asyncpg.Connection,
    weight_epoch: str,
    oos_start: Any,
    min_n: int,
    bootstrap_max_n: int,
    bootstrap_batch: int,
    bootstrap_random_state: int,
    regime_gate_min_clusters: int,
) -> dict[str, Any]:
    rows = [dict(r) for r in await conn.fetch(_OOS_QUERY_SQL, weight_epoch, oos_start)]
    n_days = len({r["cluster_id"] for r in rows})
    pnl_r = [r["pnl_r"] for r in rows]
    cluster_ids = [r["cluster_id"] for r in rows]
    bar_ts = [r["bar_ts"] for r in rows]

    c2_passes, ci_lower, ci_upper = frame_gate_passes(
        pnl_r, cluster_ids, min_n, bootstrap_max_n, bootstrap_batch, bootstrap_random_state
    )

    sharpe = _annualized_sharpe(pnl_r, bar_ts) if pnl_r else None
    dd, dd_fails = _max_drawdown(np.array(pnl_r)) if pnl_r else (None, True)

    # Regime-stratified re-evaluation of C2/C7 (todo 165) -- groups by (direction, regime),
    # never reaches into in-sample data (rows are already OOS-only from _OOS_QUERY_SQL).
    # Scope-narrowed to C2/C7 only: C1 (day floor)/C3 (Sharpe)/C4 (drawdown)/C6
    # (non-regression) stay pooled, since Sharpe/drawdown are multi-day path statistics
    # that are not meaningful on an 8-25 day regime slice.
    regime_cells = evaluate_frame_gate(
        rows,
        min_n=1,  # frame-count floor not meaningful here; min_clusters is the real floor
        bootstrap_max_n=bootstrap_max_n,
        bootstrap_batch=bootstrap_batch,
        bootstrap_random_state=bootstrap_random_state,
        group_key=lambda row: (row["direction"], row["regime"]),
        min_clusters=regime_gate_min_clusters,
    )
    evaluated_cells = [c for c in regime_cells if c["coverage"] == "evaluated"]
    c2_regime_stratified_passes = (
        all(c["passes"] for c in evaluated_cells) if evaluated_cells else None
    )
    c7_regime_stratified_no_confident_loss = not any(
        c["ci_upper"] is not None and not np.isnan(c["ci_upper"]) and c["ci_upper"] < 0
        for c in evaluated_cells
    )

    short_rows = [r for r in rows if r["direction"] == "short"]
    n_short = len(short_rows)
    short_ci_lower, short_ci_upper = float("nan"), float("nan")
    if n_short >= 2:
        _, short_ci_lower, short_ci_upper = frame_gate_passes(
            [r["pnl_r"] for r in short_rows],
            [r["cluster_id"] for r in short_rows],
            1,  # no min_n floor for the informational short-side check
            bootstrap_max_n,
            bootstrap_batch,
            bootstrap_random_state,
        )
    confident_loss = n_short > 0 and not np.isnan(short_ci_upper) and short_ci_upper < 0

    return {
        "weight_epoch": weight_epoch,
        "n_rows": len(rows),
        "n_days": n_days,
        "c1_min_60_days": n_days >= 60,
        "c2_ci_lower": ci_lower,
        "c2_ci_upper": ci_upper,
        "c2_passes": c2_passes,
        "c3_sharpe": sharpe,
        "c3_passes": sharpe is not None and sharpe > 0.5,
        "c4_max_dd": dd,
        "c4_passes": not dd_fails,
        "n_short": n_short,
        "c7_short_ci_lower": short_ci_lower,
        "c7_short_ci_upper": short_ci_upper,
        "c7_confident_loss": confident_loss,
        "regime_cells": regime_cells,
        "c2_regime_stratified_passes": c2_regime_stratified_passes,
        "c7_regime_stratified_no_confident_loss": c7_regime_stratified_no_confident_loss,
    }


async def main() -> None:
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(db_dsn)
    try:
        (
            min_n,
            bootstrap_max_n,
            bootstrap_batch,
            bootstrap_random_state,
            regime_gate_min_clusters,
        ) = await _load_apr(conn)
        oos_start = await conn.fetchval(
            "SELECT config_value::timestamptz FROM config_state "
            "WHERE config_key = 'alpha.validation.oos_start'"
        )
        if oos_start is None:
            raise RuntimeError("alpha.validation.oos_start is not set in config_state")

        champion = await evaluate_epoch(
            conn,
            "143.1-08-champion",
            oos_start,
            min_n,
            bootstrap_max_n,
            bootstrap_batch,
            bootstrap_random_state,
            regime_gate_min_clusters,
        )
        challenger = await evaluate_epoch(
            conn,
            "143.1-08-challenger",
            oos_start,
            min_n,
            bootstrap_max_n,
            bootstrap_batch,
            bootstrap_random_state,
            regime_gate_min_clusters,
        )
    finally:
        await conn.close()

    c6_passes = challenger["c2_ci_lower"] >= champion["c2_ci_lower"]

    for label, result in (("CHAMPION", champion), ("CHALLENGER", challenger)):
        print(f"\n=== {label} ({result['weight_epoch']}) ===")
        for key, value in result.items():
            if key == "regime_cells":
                continue
            print(f"  {key}: {value}")
        print(f"  --- regime coverage (min_clusters={regime_gate_min_clusters}) ---")
        for cell in sorted(result["regime_cells"], key=lambda c: (c["tf"], c["regime"])):
            print(
                f"    direction={cell['tf']} regime={cell['regime']} "
                f"n_frames={cell['n_frames']} n_clusters={cell['n_clusters']} "
                f"coverage={cell['coverage']} passes={cell['passes']} "
                f"ci_lower={cell['ci_lower']} ci_upper={cell['ci_upper']}"
            )

    print(f"\n=== CRITERION 6 (non-regression vs champion) ===\n  passes: {c6_passes}")

    verdict = (
        "PROMOTE"
        if all(
            [
                challenger["c1_min_60_days"],
                challenger["c2_regime_stratified_passes"] is True,
                challenger["c3_passes"],
                challenger["c4_passes"],
                c6_passes,
                challenger["c7_regime_stratified_no_confident_loss"],
            ]
        )
        else "HOLD"
    )
    print(
        "\n=== VERDICT (criteria 1, 3, 4, 6 pooled; 2, 7 regime-stratified per todo 165) "
        f"===\n  {verdict}"
    )
    if challenger["c2_regime_stratified_passes"] is None:
        print(
            "  NOTE: no (direction, regime) cell had sufficient OOS day-cluster coverage "
            f"(floor={regime_gate_min_clusters}) -- verdict is inconclusive on regime-conditional "
            "edge, not a clean HOLD."
        )


if __name__ == "__main__":
    asyncio.run(main())
