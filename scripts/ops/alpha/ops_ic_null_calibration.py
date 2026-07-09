#!/usr/bin/env python3
"""
ops_ic_null_calibration.py -- L4-2 empirical null calibration for the IC inference chain.

Design: docs/plans/2026-07-09-ic-null-calibration-design.md (todo 071 / L4-2).

Checks whether `_fisher_z_ci`'s analytic standard error (SE = 1/sqrt(n-3)) correctly
describes the sampling distribution of Spearman IC on this corpus, by circularly
shifting the forward-return series (destroys X-Y alignment, preserves Y's own
autocorrelation) 200x per sampled cell and comparing the empirical null's standard
error and shape against the analytic prediction.

Cells are stratified at the CI/FDR gate decision boundary (5 boundary cells nearest
`|ic_ci_lower|`, 2 clearly-null, 2 clearly-strong per (tf, is_pooled) stratum) rather
than sampled uniformly -- the point is to protect decisions actually being made
today, not to characterize the null everywhere. See the design doc for the full
rationale, including why `is_pooled` (not `regime_scope`) is the correct
stratification axis (`regime_scope='symbol_hmm'` has zero rows today).

D-01: regime labels for every sampled cell -- per-symbol AND pooled -- come from
`market_regimes` (this corpus was measured with `equity_model_enabled=true`), never
from `feature_vectors.regime`. The per-symbol and pooled fetch queries differ only in
whether `fv.symbol` is pinned to one value.

D-02: sampling scopes to the single latest `training_window_end` vintage in
`feature_ic_scores`, matching the existing "latest vintage" convention used by
`ops_ensemble_ic_diagnosis.py` -- prevents mixing cells across corpus rebuilds.

D-03: the `n_independent` cross-check (production's `_compute_ic_rolling_metrics`
computes this as `len(sub_idx)` BEFORE the completeness/finite-value mask) compares
against the diagnostic's own post-stride, pre-completeness-filter row count -- not
the post-filter valid count -- to match production's definition exactly.

This report is diagnostic; remediation (delete the dead `alpha.ic.bootstrap_*` APR
keys, or reopen circular block bootstrap) is a follow-up decision recorded in
`docs/research/measurement-ic-engine.md`, not made by this script. Exit code is
always 0 -- informational, not a gate.

Usage:
    python scripts/ops/alpha/ops_ic_null_calibration.py
    python scripts/ops/alpha/ops_ic_null_calibration.py --n-permutations 500 --seed 7
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import asyncpg
import numpy as np
from scipy.stats import rankdata, shapiro

from src.config.settings import Settings
from src.intelligence.statistics.ic_math import _circular_shift_null, _vectorized_ic

_TFS = ("5m", "15m", "1h", "1d")
_N_BOUNDARY_CELLS = 5
_N_NULL_CELLS = 2
_N_STRONG_CELLS = 2
_N_PERMUTATIONS_DEFAULT = 200
_SE_RATIO_SUSPECT_THRESHOLD_DEFAULT = 1.2
_SHAPIRO_ALPHA = 0.05

_LATEST_VINTAGE_SQL = "SELECT max(training_window_end) FROM feature_ic_scores"

_LOOKAHEAD_APR_KEYS = {
    "fast": "alpha.ic.lookahead.fast",
    "mid": "alpha.ic.lookahead.mid",
    "slow": "alpha.ic.lookahead.slow",
    "extended": "alpha.ic.lookahead.extended",
}
_LOOKAHEAD_DEFAULTS = {"fast": 1, "mid": 5, "slow": 20, "extended": 60}

_BOUNDARY_CELLS_SQL = """
    SELECT feature_name, symbol, tf, regime, lookahead_bars, training_window_end,
           is_pooled, n_independent, ic_ci_lower, ic_value, ic_sharpe_hac
    FROM feature_ic_scores
    WHERE tf = $1 AND is_pooled = $2 AND training_window_end = $3
      AND passes_fdr = true AND reliable = true AND ic_ci_lower IS NOT NULL
      AND regime != '_pooled'
    ORDER BY abs(ic_ci_lower) ASC
    LIMIT $4
"""

_NULL_CELLS_SQL = """
    SELECT feature_name, symbol, tf, regime, lookahead_bars, training_window_end,
           is_pooled, n_independent, ic_ci_lower, ic_value, ic_sharpe_hac
    FROM feature_ic_scores
    WHERE tf = $1 AND is_pooled = $2 AND training_window_end = $3
      AND passes_fdr = false AND reliable = true AND ic_value IS NOT NULL
      AND regime != '_pooled'
    ORDER BY abs(ic_value) ASC
    LIMIT $4
"""

_STRONG_CELLS_SQL = """
    SELECT feature_name, symbol, tf, regime, lookahead_bars, training_window_end,
           is_pooled, n_independent, ic_ci_lower, ic_value, ic_sharpe_hac
    FROM feature_ic_scores
    WHERE tf = $1 AND is_pooled = $2 AND training_window_end = $3
      AND reliable = true AND ic_sharpe_hac IS NOT NULL
      AND regime != '_pooled'
    ORDER BY ic_sharpe_hac DESC
    LIMIT $4
"""

_FETCH_PER_SYMBOL_SQL_TMPL = """
    SELECT fv.bar_ts, fv."{feature_name}" AS x_val, fr.return_{scale} AS y_val,
           fr.complete_{scale} AS is_complete
    FROM market_regimes mr
    INNER JOIN feature_vectors fv ON fv.bar_ts = mr.ts AND fv.tf = mr.tf
    INNER JOIN forward_returns fr
        ON fr.symbol = fv.symbol AND fr.tf = fv.tf AND fr.bar_ts = fv.bar_ts
        AND fr.return_type = 'executable_open_to_open'
    WHERE mr.asset_class = 'equity' AND mr.tf = $1 AND mr.regime_label = $2
      AND fv.bar_ts <= $3 AND fv.symbol = $4
    ORDER BY fv.bar_ts
"""

_FETCH_POOLED_SQL_TMPL = """
    SELECT fv.bar_ts, fv."{feature_name}" AS x_val, fr.return_{scale} AS y_val,
           fr.complete_{scale} AS is_complete
    FROM market_regimes mr
    INNER JOIN feature_vectors fv ON fv.bar_ts = mr.ts AND fv.tf = mr.tf
    INNER JOIN forward_returns fr
        ON fr.symbol = fv.symbol AND fr.tf = fv.tf AND fr.bar_ts = fv.bar_ts
        AND fr.return_type = 'executable_open_to_open'
    WHERE mr.asset_class = 'equity' AND mr.tf = $1 AND mr.regime_label = $2
      AND fv.bar_ts <= $3
    ORDER BY fv.bar_ts, fv.symbol
"""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-permutations", type=int, default=_N_PERMUTATIONS_DEFAULT)
    parser.add_argument(
        "--se-ratio-suspect-threshold", type=float, default=_SE_RATIO_SUSPECT_THRESHOLD_DEFAULT
    )
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


async def _load_config_int(pool: asyncpg.Pool, key: str, default: int) -> int:
    row = await pool.fetchval("SELECT config_value FROM config_state WHERE config_key = $1", key)
    return int(row) if row is not None else default


async def _sample_cells(pool: asyncpg.Pool, vintage) -> list[dict]:
    cells: list[dict] = []
    for tf in _TFS:
        for is_pooled in (False, True):
            for sql, limit in (
                (_BOUNDARY_CELLS_SQL, _N_BOUNDARY_CELLS),
                (_NULL_CELLS_SQL, _N_NULL_CELLS),
                (_STRONG_CELLS_SQL, _N_STRONG_CELLS),
            ):
                rows = await pool.fetch(sql, tf, is_pooled, vintage, limit)
                if len(rows) < limit:
                    print(
                        f"WARNING: stratum tf={tf} is_pooled={is_pooled} query="
                        f"{sql.strip().splitlines()[1].strip()[:40]}... only found "
                        f"{len(rows)}/{limit} qualifying cells"
                    )
                cells.extend(dict(r) for r in rows)
    return cells


async def _fetch_cell_series(
    pool: asyncpg.Pool, cell: dict, scale: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    tmpl = _FETCH_POOLED_SQL_TMPL if cell["is_pooled"] else _FETCH_PER_SYMBOL_SQL_TMPL
    sql = tmpl.format(feature_name=cell["feature_name"], scale=scale)
    if cell["is_pooled"]:
        rows = await pool.fetch(sql, cell["tf"], cell["regime"], cell["training_window_end"])
    else:
        rows = await pool.fetch(
            sql, cell["tf"], cell["regime"], cell["training_window_end"], cell["symbol"]
        )
    x = np.array([r["x_val"] for r in rows], dtype=np.float64)
    y = np.array([r["y_val"] if r["y_val"] is not None else np.nan for r in rows], dtype=np.float64)
    complete = np.array([bool(r["is_complete"]) for r in rows], dtype=bool)
    return x, y, complete


def _evaluate_cell(
    x_raw: np.ndarray,
    y_raw: np.ndarray,
    complete_raw: np.ndarray,
    stride: int,
    stored_n_independent: int,
    n_permutations: int,
    rng: np.random.Generator,
) -> dict | None:
    n_raw = len(x_raw)
    sub_idx = np.arange(0, n_raw, stride)
    n_independent = len(sub_idx)
    if n_independent != stored_n_independent:
        return None  # mismatch: cell mis-selected or corpus drifted since measurement

    x_sub = x_raw[sub_idx]
    y_sub = y_raw[sub_idx]
    complete_sub = complete_raw[sub_idx]
    valid_mask = complete_sub & np.isfinite(y_sub) & np.isfinite(x_sub)
    n_valid = int(valid_mask.sum())
    if n_valid < 4:
        return None  # _fisher_z_ci requires n >= 4

    x_valid = x_sub[valid_mask]
    y_valid = y_sub[valid_mask]
    ranks_x = rankdata(x_valid).reshape(-1, 1)

    observed_ic = float(_vectorized_ic(ranks_x, rankdata(y_valid))[0])

    ic_null = np.empty(n_permutations)
    for i in range(n_permutations):
        y_shifted = _circular_shift_null(y_valid, rng)
        ic_null[i] = _vectorized_ic(ranks_x, rankdata(y_shifted))[0]

    z_null = np.arctanh(np.clip(ic_null, -1 + 1e-10, 1 - 1e-10))
    empirical_se = float(np.std(z_null, ddof=1))
    analytic_se = 1.0 / np.sqrt(n_valid - 3)
    se_ratio = empirical_se / analytic_se
    shapiro_stat, shapiro_p = shapiro(z_null)

    return {
        "n_valid": n_valid,
        "observed_ic": observed_ic,
        "empirical_se": empirical_se,
        "analytic_se": analytic_se,
        "se_ratio": se_ratio,
        "shapiro_p": float(shapiro_p),
    }


async def main() -> int:
    args = _parse_args()
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)

    try:
        vintage = await pool.fetchval(_LATEST_VINTAGE_SQL)
        if vintage is None:
            print("ERROR: feature_ic_scores is empty -- nothing to sample.")
            return 0

        lookaheads = {
            scale: await _load_config_int(pool, key, _LOOKAHEAD_DEFAULTS[scale])
            for scale, key in _LOOKAHEAD_APR_KEYS.items()
        }
        bars_to_scale = {bars: scale for scale, bars in lookaheads.items()}
        subsample_min_stride = await _load_config_int(pool, "alpha.ic.subsample_min_stride", 5)

        print(f"# L4-2 Null Calibration Report (vintage: {vintage})\n")
        print(
            f"n_permutations={args.n_permutations}, seed={args.seed}, "
            f"se_ratio_suspect_threshold={args.se_ratio_suspect_threshold}\n"
        )

        cells = await _sample_cells(pool, vintage)
        print(f"Sampled {len(cells)} cells.\n")

        rng = np.random.default_rng(args.seed)
        print(
            "| feature | symbol | tf | regime | lookahead | n_valid | observed_ic | "
            "analytic_se | empirical_se | se_ratio | shapiro_p | flag |"
        )
        print("|---|---|---|---|---|---|---|---|---|---|---|---|")

        n_suspect = 0
        n_evaluated = 0
        n_skipped = 0
        suspect_by_stratum: dict[tuple[str, bool], int] = {}

        for cell in cells:
            scale = bars_to_scale.get(cell["lookahead_bars"])
            if scale is None:
                n_skipped += 1
                continue
            stride = max(subsample_min_stride, cell["lookahead_bars"])
            x_raw, y_raw, complete_raw = await _fetch_cell_series(pool, cell, scale)
            result = _evaluate_cell(
                x_raw,
                y_raw,
                complete_raw,
                stride,
                cell["n_independent"],
                args.n_permutations,
                rng,
            )
            if result is None:
                n_skipped += 1
                continue

            n_evaluated += 1
            flag = "SUSPECT" if result["se_ratio"] > args.se_ratio_suspect_threshold else "OK"
            if flag == "SUSPECT":
                n_suspect += 1
                key = (cell["tf"], cell["is_pooled"])
                suspect_by_stratum[key] = suspect_by_stratum.get(key, 0) + 1

            print(
                f"| {cell['feature_name']} | {cell['symbol']} | {cell['tf']} | "
                f"{cell['regime']} | {scale} | {result['n_valid']} | "
                f"{result['observed_ic']:.4f} | {result['analytic_se']:.4f} | "
                f"{result['empirical_se']:.4f} | {result['se_ratio']:.3f} | "
                f"{result['shapiro_p']:.4f} | {flag} |"
            )

        print("\n## Summary\n")
        print(
            f"Evaluated: {n_evaluated}, skipped (mismatch/insufficient N): {n_skipped}, "
            f"SUSPECT: {n_suspect}\n"
        )
        if n_suspect == 0:
            print("**Verdict: Fisher-z CI calibration confirmed across all sampled cells.**")
        else:
            print(
                "**Verdict: SUSPECT cells found -- analytic CI may be too narrow. "
                "Stratum breakdown:**"
            )
            for (tf, is_pooled), count in sorted(suspect_by_stratum.items()):
                print(f"- tf={tf}, is_pooled={is_pooled}: {count} SUSPECT cell(s)")
        print("\n---\nThis report is diagnostic; remediation decisions are human/operator.")
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
