#!/usr/bin/env python3
"""
ops_ic_shrinkage.py — E1: empirical-Bayes IC shrinkage compute pass + hard
out-of-fold acceptance gate (D-04/D-05/D-06, Phase 142B.1).

Two responsibilities, both pure-importable where the actual math lives:

(A) Compute pass: for every `reliable = true` `feature_ic_scores` row, shrink
    `ic_sharpe_hac` toward a leave-one-out `(feature_registry.group_name, regime, tf)`
    peer-group prior via `shrink_ic()` (src/intelligence/ensemble/shrinkage.py, Plan 02),
    and bulk-UPDATE `ic_shrunk`/`shrinkage_weight` by the 6-column PK using
    `services/_batch_utils.py::bulk_update_by_key` — keeps `ic_engine.py`'s large,
    already-audited write path untouched (RESEARCH.md Open Question 2).

(B) Out-of-fold acceptance gate (D-05, HARD GATE, not a diagnostic): reconstructs, for
    every cross-sectional POOLED reliable cell, an in-sample train-window-T /
    held-out-window-T+1 split of the ALREADY in-sample corpus (`bar_ts < oos_start`;
    Phase 144's true OOS boundary is never touched here) with a scale-specific embargo
    between them (mirrors `ic_engine.py`/`ensemble_ic_engine.py`'s expanding-window
    walk-forward + embargo discipline). Computes `ic_raw_T` and a window-T-only
    `ic_shrunk_T` (fresh leave-one-out prior over window T, NOT the full-corpus
    Part-A prior — the test must validate the mechanism using only information a live
    re-run would have had), then compares each to the REALIZED IC in T+1
    (RESEARCH.md Pitfall 4: predicting a future held-out window's IC, not same-window
    fit, not correlation-with-returns). PASS iff mean |ic_shrunk_T - ic_realized_T+1|
    < mean |ic_raw_T - ic_realized_T+1| across cells.

    On PASS: `alpha.ensemble.ic_input` is flipped to `'ic_shrunk'` via
    `ConfigService.set()` (config_history-audited). On FAIL: `ic_input` is left
    untouched — `ensemble_trainer.py` keeps reading `ic_sharpe_hac` — and E1 is
    reported failed/inconclusive. The flip lives strictly inside the PASS branch
    (verifiable as a source assertion, T-142B1-03-02).

Exit code: 0 for a successful RUN (compute pass completed, gate report emitted)
regardless of PASS/FAIL verdict — a gate FAIL is a valid, expected report, not a
script failure, so this step must not halt the nightly corpus pipeline (it runs
between ic_engine and ensemble_trainer, which must always proceed using whichever
ic_input is currently configured). Exit code 1 only for genuine operational failure
(missing OOS boundary, DB exception).

Usage:
    python scripts/ops/alpha/ops_ic_shrinkage.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np
import psycopg2
import psycopg2.extras
import structlog
from scipy.stats import rankdata

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import LOOKAHEAD_FALLBACKS_BY_TF, bulk_update_by_key, connect_db_from_url
from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async as _load_apr_dict
from src.config.config_service import ConfigService
from src.config.settings import Settings
from src.intelligence.ensemble.shrinkage import leave_one_out_group_prior, shrink_ic
from src.intelligence.statistics.ic_math import _vectorized_ic

_logger = structlog.get_logger(__name__)

# feature_ic_scores composite PK (services/_batch_utils.py::bulk_update_by_key key_cols).
_PK_COLS: tuple[str, ...] = (
    "feature_name",
    "symbol",
    "tf",
    "regime",
    "lookahead_bars",
    "training_window_end",
)
_SET_COLS: tuple[str, ...] = ("ic_shrunk", "shrinkage_weight")
_COL_TYPES: dict[str, str] = {
    "ic_shrunk": "double precision",
    "shrinkage_weight": "double precision",
    "feature_name": "text",
    "symbol": "text",
    "tf": "text",
    "regime": "text",
    "lookahead_bars": "integer",
    "training_window_end": "timestamptz",
}

_RELIABLE_ROWS_SQL = """
    SELECT feature_name, symbol, tf, regime, lookahead_bars, training_window_end,
           n_independent, ic_sharpe_hac
    FROM feature_ic_scores
    WHERE reliable = true AND ic_sharpe_hac IS NOT NULL
"""

_FEATURE_GROUP_SQL = "SELECT feature_name, group_name FROM feature_registry"

_POOLED_RELIABLE_CELLS_SQL = """
    SELECT DISTINCT feature_name, tf, regime, lookahead_bars
    FROM feature_ic_scores
    WHERE reliable = true AND ic_sharpe_hac IS NOT NULL
      AND symbol = 'POOLED' AND is_pooled = true AND regime != '_pooled'
"""

_SCALE_RETURN_COLUMNS: dict[str, str] = {
    "fast": "return_fast",
    "mid": "return_mid",
    "slow": "return_slow",
    "extended": "return_extended",
}

# Cross-sectional average is pushed into SQL (GROUP BY bar_ts) rather than pulled into
# Python row-by-row -- the regime is already pinned by the WHERE clause below, so
# grouping-before-averaging (RESEARCH.md Pitfall 5's discipline) holds by construction;
# this is materially faster than transferring raw per-(symbol, bar_ts) rows for a
# 10M+-row corpus and matches Pitfall 5's requirement without needing the Python-side
# _aggregate_pooled_series step ensemble_ic_engine.py uses for its own unit-testability.
_STRATUM_FETCH_SQL_TEMPLATE = """
    SELECT fv.bar_ts, {col_list},
           AVG(fr.return_fast) FILTER (WHERE NOT fr.return_fast_suspect) AS return_fast,
           AVG(fr.return_mid) FILTER (WHERE NOT fr.return_mid_suspect) AS return_mid,
           AVG(fr.return_slow) FILTER (WHERE NOT fr.return_slow_suspect) AS return_slow,
           AVG(fr.return_extended) FILTER (WHERE NOT fr.return_extended_suspect) AS return_extended
    FROM feature_vectors fv
    JOIN market_regimes mr
      ON mr.regime_group = 'equity' AND mr.tf = fv.tf AND mr.ts = fv.bar_ts
    JOIN forward_returns fr
      ON fr.symbol = fv.symbol AND fr.tf = fv.tf AND fr.bar_ts = fv.bar_ts
      AND fr.return_type = 'executable_open_to_open'
    WHERE fv.tf = %s AND mr.regime_label = %s AND fv.bar_ts < %s
    GROUP BY fv.bar_ts
    ORDER BY fv.bar_ts
"""


# ---------------------------------------------------------------------------
# Part A -- pure compute: leave-one-out prior + shrink_ic per reliable cell
# ---------------------------------------------------------------------------


def compute_shrinkage_updates(
    ic_rows: list[dict[str, Any]],
    feature_to_group: dict[str, str],
    k: float,
) -> list[tuple]:
    """Pure function (no DB): compute (ic_shrunk, shrinkage_weight, *pk) update tuples
    for every reliable `feature_ic_scores` row, via a leave-one-out
    `(group_name, regime, tf)` peer-group prior (D-06).

    Peer group is keyed purely on `(group_name, regime, tf)` — NOT scoped to symbol or
    lookahead_bars — matching D-06's literal spec ("feature family x regime x tf").
    Rows whose feature has no `feature_registry.group_name` mapping are skipped (cannot
    form a peer group without a family label). Non-finite `shrink_ic` outputs are
    dropped, never persisted (Pitfall 1's degenerate-input guard already returns a
    defined value for n_eff<=0; this is defense-in-depth against any other NaN/Inf
    source, e.g. a corrupt `ic_sharpe_hac` value).
    """
    buckets: dict[tuple[str, str, str], list[int]] = {}
    for idx, row in enumerate(ic_rows):
        group_name = feature_to_group.get(row["feature_name"])
        if group_name is None:
            continue
        buckets.setdefault((group_name, row["regime"], row["tf"]), []).append(idx)

    updates: list[tuple] = []
    for _key, idxs in buckets.items():
        group_values = np.array([ic_rows[i]["ic_sharpe_hac"] for i in idxs], dtype=float)
        for local_i, global_i in enumerate(idxs):
            row = ic_rows[global_i]
            prior = leave_one_out_group_prior(group_values, local_i)
            n_eff = float(row["n_independent"]) if row["n_independent"] is not None else 0.0
            ic_shrunk, weight = shrink_ic(float(row["ic_sharpe_hac"]), n_eff, prior, k)
            if not np.isfinite(ic_shrunk) or not np.isfinite(weight):
                continue
            updates.append(
                (
                    ic_shrunk,
                    weight,
                    row["feature_name"],
                    row["symbol"],
                    row["tf"],
                    row["regime"],
                    row["lookahead_bars"],
                    row["training_window_end"],
                )
            )
    return updates


# ---------------------------------------------------------------------------
# Part B -- out-of-fold acceptance gate (D-05, hard gate; Pitfall 4 correct test)
# ---------------------------------------------------------------------------


def evaluate_out_of_fold_gate(
    shrunk_errors: np.ndarray | list[float],
    raw_errors: np.ndarray | list[float],
) -> tuple[bool, float, float]:
    """Pure, importable decision helper (unit-testable without a DB).

    Given parallel arrays of `|ic_shrunk_T - ic_realized_T+1|` and
    `|ic_raw_T - ic_realized_T+1|` across held-out cells, returns
    `(passed, mean_shrunk_error, mean_raw_error)`. PASS iff the mean shrunk error is
    STRICTLY less than the mean raw error (D-05: shrinkage must genuinely improve
    next-window IC prediction, not merely tie it). Degenerate: empty input -> FAIL
    (no evidence exists to justify flipping the live estimator).
    """
    shrunk_arr = np.asarray(shrunk_errors, dtype=float)
    raw_arr = np.asarray(raw_errors, dtype=float)
    if shrunk_arr.size == 0 or raw_arr.size == 0:
        return False, float("nan"), float("nan")
    mean_shrunk = float(np.mean(shrunk_arr))
    mean_raw = float(np.mean(raw_arr))
    return mean_shrunk < mean_raw, mean_shrunk, mean_raw


def _spearman_ic(x: np.ndarray, y: np.ndarray) -> float | None:
    """Spearman IC between two 1-D arrays via `rankdata` + `_vectorized_ic` — reuses
    the shared, correctness-audited rank-IC machinery (Don't Hand-Roll table) instead
    of a parallel implementation. Returns None when fewer than 2 valid paired
    observations exist (undefined correlation)."""
    valid = np.isfinite(x) & np.isfinite(y)
    if int(valid.sum()) < 2:
        return None
    rx = rankdata(x[valid].reshape(-1, 1), axis=0)
    ry = rankdata(y[valid])
    return float(_vectorized_ic(rx, ry)[0])


def _lookahead_bars_to_scale_by_tf(
    lookaheads_by_tf: dict[str, dict[str, int]],
) -> dict[str, dict[int, str]]:
    """Todo 146/202: a single global bars->scale map is ill-defined once the same bar
    count means a different scale on different tfs (e.g. 5 is 15m's old slow AND part
    of nothing consistent post-146; 15m's and 1d's extended both happen to be 10).
    Build the reverse map per tf instead."""
    return {
        tf: {bars: scale for scale, bars in scales.items()}
        for tf, scales in lookaheads_by_tf.items()
    }


def build_out_of_fold_errors(
    pooled_by_stratum: dict[tuple[str, str], list[dict[str, Any]]],
    cells_by_stratum: dict[tuple[str, str], list[dict[str, Any]]],
    feature_to_group: dict[str, str],
    bars_to_scale_by_tf: dict[str, dict[int, str]],
    k: float,
) -> tuple[list[float], list[float], int]:
    """Pure function (no DB): given already-fetched pooled cross-sectional series per
    (tf, regime) stratum, split each into train window T / held-out window T+1 with a
    scale-specific embargo, compute `ic_raw_T` for every (feature, lookahead) cell,
    derive a fresh window-T leave-one-out `(group_name)` prior (D-06) and `ic_shrunk_T`,
    then compare both to the REALIZED IC in T+1.

    Returns (shrunk_errors, raw_errors, n_cells_evaluated) — feed directly into
    `evaluate_out_of_fold_gate`. Split out from the DB-fetching orchestration in
    `_run_out_of_fold_gate` so the split/prior/error math is independently unit-testable
    with synthetic in-memory series (no DB, no asyncpg, no psycopg2).
    """
    shrunk_errors: list[float] = []
    raw_errors: list[float] = []
    n_evaluated = 0

    for stratum_key, stratum_cells in cells_by_stratum.items():
        pooled = pooled_by_stratum.get(stratum_key)
        if not pooled:
            continue
        n = len(pooled)
        if n < 4:
            continue

        # stratum_key is (tf, regime) -- every cell in stratum_cells shares this tf, so
        # the bars->scale map only needs resolving once per stratum, not per cell.
        tf, _regime = stratum_key
        bars_to_scale = bars_to_scale_by_tf.get(tf, {})

        cell_results: list[dict[str, Any]] = []
        for cell in stratum_cells:
            feature_name = cell["feature_name"]
            lookahead_bars = cell["lookahead_bars"]
            scale = bars_to_scale.get(lookahead_bars)
            if scale is None:
                continue
            group_name = feature_to_group.get(feature_name)
            if group_name is None:
                continue
            return_col = _SCALE_RETURN_COLUMNS[scale]

            x = np.array(
                [
                    r.get(feature_name) if r.get(feature_name) is not None else np.nan
                    for r in pooled
                ],
                dtype=float,
            )
            y = np.array(
                [r.get(return_col) if r.get(return_col) is not None else np.nan for r in pooled],
                dtype=float,
            )

            embargo = lookahead_bars
            train_end = n // 2
            test_start = train_end + embargo
            if test_start >= n:
                continue

            ic_raw_train = _spearman_ic(x[:train_end], y[:train_end])
            ic_realized_test = _spearman_ic(x[test_start:], y[test_start:])
            if ic_raw_train is None or ic_realized_test is None:
                continue

            n_eff_train = int(np.isfinite(x[:train_end]).sum())
            cell_results.append(
                {
                    "group_name": group_name,
                    "ic_raw_train": ic_raw_train,
                    "ic_realized_test": ic_realized_test,
                    "n_eff_train": n_eff_train,
                }
            )

        # Fresh window-T-only leave-one-out prior per group_name (D-06) -- deliberately
        # NOT Part A's full-corpus prior; this test validates the mechanism using only
        # information a live re-run over window T would have had.
        group_buckets: dict[str, list[int]] = {}
        for idx, cr in enumerate(cell_results):
            group_buckets.setdefault(cr["group_name"], []).append(idx)

        for _group_name, idxs in group_buckets.items():
            group_values = np.array([cell_results[i]["ic_raw_train"] for i in idxs], dtype=float)
            for local_i, global_i in enumerate(idxs):
                cr = cell_results[global_i]
                prior = leave_one_out_group_prior(group_values, local_i)
                ic_shrunk_train, _w = shrink_ic(
                    cr["ic_raw_train"], float(cr["n_eff_train"]), prior, k
                )
                shrunk_errors.append(abs(ic_shrunk_train - cr["ic_realized_test"]))
                raw_errors.append(abs(cr["ic_raw_train"] - cr["ic_realized_test"]))
                n_evaluated += 1

    return shrunk_errors, raw_errors, n_evaluated


async def _run_out_of_fold_gate(
    apool: asyncpg.Pool,
    sync_conn: Any,
    feature_to_group: dict[str, str],
    k: float,
    oos_start: datetime,
    lookaheads_by_tf: dict[str, dict[str, int]],
) -> tuple[bool, float, float, int]:
    """DB orchestration for Part B: fetch cross-sectional pooled series per (tf, regime)
    stratum (one query per stratum, cross-symbol average computed in SQL), then hand off
    to the pure `build_out_of_fold_errors` for the split/prior/error math.
    """
    bars_to_scale_by_tf = _lookahead_bars_to_scale_by_tf(lookaheads_by_tf)

    async with apool.acquire() as conn:
        cells = await conn.fetch(_POOLED_RELIABLE_CELLS_SQL)

    cells_by_stratum: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for cell in cells:
        key = (cell["tf"], cell["regime"])
        cells_by_stratum.setdefault(key, []).append(dict(cell))

    pooled_by_stratum: dict[tuple[str, str], list[dict[str, Any]]] = {}
    with sync_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for (tf, regime), stratum_cells in cells_by_stratum.items():
            feature_names = sorted({c["feature_name"] for c in stratum_cells})
            col_list = ", ".join(f'AVG(fv."{name}") AS "{name}"' for name in feature_names)
            sql = _STRATUM_FETCH_SQL_TEMPLATE.format(col_list=col_list)
            try:
                cur.execute(sql, (tf, regime, oos_start))
                fetched = cur.fetchall()
            except Exception as error:  # CLAUDE.md: exception variable name is `error`
                _logger.warning(
                    "ic_shrinkage.oof_stratum_fetch_failed",
                    tf=tf,
                    regime=regime,
                    error=str(error),
                )
                sync_conn.rollback()
                continue
            pooled_by_stratum[(tf, regime)] = [dict(r) for r in fetched]

    shrunk_errors, raw_errors, n_evaluated = build_out_of_fold_errors(
        pooled_by_stratum, cells_by_stratum, feature_to_group, bars_to_scale_by_tf, k
    )
    passed, mean_shrunk, mean_raw = evaluate_out_of_fold_gate(shrunk_errors, raw_errors)
    return passed, mean_shrunk, mean_raw, n_evaluated


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


async def main() -> int:
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    apool = await asyncpg.create_pool(dsn=dsn)
    sync_conn = connect_db_from_url(dsn)
    try:
        async with apool.acquire() as conn:
            apr = await _load_apr_dict(conn)

        k = float(_cfg(apr, "alpha.ic.shrinkage_k", 100.0))
        # Todo 146/202: lookahead grid is per-tf now, not one shared scale->bars dict.
        lookaheads_by_tf = {
            tf: {
                scale: int(_cfg(apr, f"alpha.ic.lookahead.{tf}.{scale}", default))
                for scale, default in fallbacks.items()
            }
            for tf, fallbacks in LOOKAHEAD_FALLBACKS_BY_TF.items()
        }

        async with apool.acquire() as conn:
            oos_start = await conn.fetchval(
                "SELECT config_value::timestamptz FROM config_state "
                "WHERE config_key = 'alpha.validation.oos_start'"
            )
        if oos_start is None:
            print(
                "## E1 IC Shrinkage\n\n"
                "FAILED: alpha.validation.oos_start is not set in config_state — "
                "the out-of-fold gate's train/holdout split cannot be scoped to the "
                "in-sample corpus without it."
            )
            return 1

        # --- Part A: compute pass ---
        async with apool.acquire() as conn:
            ic_rows_raw = await conn.fetch(_RELIABLE_ROWS_SQL)
            group_rows = await conn.fetch(_FEATURE_GROUP_SQL)
        ic_rows = [dict(r) for r in ic_rows_raw]
        feature_to_group = {r["feature_name"]: r["group_name"] for r in group_rows}

        updates = compute_shrinkage_updates(ic_rows, feature_to_group, k)
        if updates:
            bulk_update_by_key(
                sync_conn,
                table="feature_ic_scores",
                temp_table="tmp_ic_shrinkage_update",
                key_cols=list(_PK_COLS),
                set_cols=list(_SET_COLS),
                col_types=_COL_TYPES,
                rows=updates,
            )
            sync_conn.commit()

        print("## E1 IC Shrinkage — Compute Pass\n")
        print(f"Reliable cells read: {len(ic_rows)}")
        print(f"Rows updated (ic_shrunk, shrinkage_weight): {len(updates)}")
        print(f"shrinkage_k (alpha.ic.shrinkage_k): {k}")
        print()

        # --- Part B: out-of-fold hard gate ---
        passed, mean_shrunk, mean_raw, n_evaluated = await _run_out_of_fold_gate(
            apool, sync_conn, feature_to_group, k, oos_start, lookaheads_by_tf
        )

        print("## E1 Out-of-Fold Acceptance Gate (D-05, HARD GATE)\n")
        print(f"Cells evaluated: {n_evaluated}")
        print(f"Mean |ic_shrunk_T - ic_realized_T+1|: {mean_shrunk}")
        print(f"Mean |ic_raw_T - ic_realized_T+1|: {mean_raw}")
        print(f"Verdict: {'PASS' if passed else 'FAIL'}")

        if passed:
            config_service = ConfigService(database_url=dsn, pool=apool)
            await config_service.initialize()
            await config_service.set(
                "alpha.ensemble.ic_input",
                "ic_shrunk",
                changed_by="ops-ic-shrinkage",
                reason=(
                    f"E1 out-of-fold gate PASSED: {n_evaluated} cells, "
                    f"mean_shrunk_error={mean_shrunk:.6f} < mean_raw_error={mean_raw:.6f}"
                ),
            )
            print()
            print("alpha.ensemble.ic_input flipped to 'ic_shrunk'.")
        else:
            print()
            print(
                "E1 FAILED/INCONCLUSIVE — alpha.ensemble.ic_input left unchanged; "
                "ensemble_trainer.py continues reading ic_sharpe_hac."
            )

        # Exit 0 for both PASS and FAIL: this is a successful RUN either way (the
        # compute pass wrote ic_shrunk unconditionally; only the ic_input flip is
        # gated). A FAIL must not halt the corpus pipeline step that invokes this
        # script between ic_engine and ensemble_trainer.
        return 0
    finally:
        sync_conn.close()
        await apool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
