"""Null-arm validation of the PRODUCTION regime axes (Phase 171 follow-on, investigation-only).

WHY THIS EXISTS
---------------
Three sweeps in this investigation validated regime axes with one battery: two-pool best-of-N
cross-block agreement >= 0.90 AND Cohen's kappa >= 0.80, plus production's occupation gate and a
min-state-separation check. `hmm_candidate_regime_axes_identifiability_sweep.py` then discovered
that battery does not discriminate signal from noise: refitting the same configuration on an
IID-PERMUTED copy of the same series -- a series with zero regime structure by construction --
cleared every bar just as often (the `persistence` axis: 34/34 real, 34/34 null, at a measured
signal fraction of -0.006). A two-state HMM on a stationary series is a deterministic threshold
split of that series; it is perfectly reproducible across disjoint seed pools, well separated,
and healthily occupied while encoding nothing.

That gap was never checked against the axes Phase 172 actually proposes to ship:

  * composite        (cols 0,1,2,3,4) at K=3 -- the headline recommendation
  * trend            (cols 0,2) at K=2 and K=3 -- incl. the group-specific-K conclusion from the
                     widened 17-symbol run (equity clean at K=3, fx/commodity/rates/intl
                     degenerate at K=3/1h)
  * volatility       (cols 1,3) at K=2 and K=3
  * trend_volatility (cols 0,1,2,3) at K=3 -- composite minus volume, 16/16 on 8 symbols

`volume` is deliberately NOT re-tested: it already fails the weaker agreement/kappa battery
outright at every K, so there is no "passes but might be noise" question to resolve for it. Only
axes that already cleared the weaker test need the stronger control.

WHAT THIS SCRIPT MEASURES
-------------------------
Two arms, exactly as the candidate-axes sweep ran them, on production's own observation matrix:

1. `block_reliability` (the instrument that actually discriminates). Correlation between the
   axis's constituent statistic estimated on ADJACENT DISJOINT blocks -- blocks [i*W, (i+1)*W)
   and [(i+1)*W, (i+2)*W). The two estimates share no observation, so sampling noise cannot
   contribute to their correlation; by the classical two-parallel-measurements identity the
   coefficient IS the fraction of the statistic's variance that is real rather than estimation
   error. `null_block_reliability` is the same measure on a jointly-permuted copy of the same
   series and is the calibration control. THE BAR IS THE MARGIN (real minus null) AND a
   positive real coefficient -- an absolute threshold alone is not enough, because two of
   production's five columns have a mechanically inflated null (see below), and a margin alone
   is not enough, because a coefficient that is negative in both arms describes an alternating
   artifact rather than a state that persists. See `_MARGIN_FLOOR`.

2. The full identifiability battery (`_run_config_cell`, imported unchanged) fit on BOTH the
   real observation matrix and one built from the permuted series. If the null arm clears
   agreement/kappa/occupation as cleanly as the real arm, that battery is not evidence for the
   axis, whatever number it produced.

THE PER-COLUMN DESIGN (this is the interpretive core)
-----------------------------------------------------
The candidate sweep probed one primary statistic per axis because its axes were 2-column
constructs of one concept. Production's axes are not: `composite` fuses five columns spanning
three families, and `_build_label_map` rank-orders states by `means[:, 0]` -- the log_return
column -- so the LABEL SEMANTICS of composite/trend/trend_volatility rest on column 0 even when
the PARTITION is driven by some other column. Reliability is therefore measured for all five of
production's observation columns, and each axis is read against both: which of its columns carry
real structure, and specifically whether its ordering column does.

The block-level analogue of each production column, at block width W:

  log_return   -> sum of log returns over the block (block drift; correlation is scale-free, so
                  block sum and block mean give the identical coefficient)
  realized_vol -> std of log returns over the block
  momentum     -> block drift / block std -- production's own `sum(r)/realized_vol` formula with
                  momentum_window = vol_window = W
  vol_of_vol   -> std over the block of the inner `vol_window`-bar realized-vol series
  rel_volume   -> mean over the block of production's own rel_volume (log volume minus its
                  `vol_window`-bar rolling mean)

log_return, realized_vol and momentum are computed from raw returns at width W, so adjacent
blocks share literally no input observation. vol_of_vol and rel_volume are two-window statistics
whose inner `vol_window` estimator straddles the block boundary by up to `vol_window - 1` bars,
which induces some positive adjacency correlation from overlap alone. That contamination is
present IDENTICALLY in the null arm -- which is exactly why the verdict is the real-vs-null
margin rather than the raw coefficient.

WINDOW CHOICE
-------------
Unlike the candidate axes (second- and third-order statistics whose window was a free parameter
that had to be swept to make a negative result attributable), these axes have an established
window: production's `feature.hmm.vol_window` / `obs_momentum_window` / `obs_vol_of_vol_window`,
all 20. W = 20 is therefore the production-parity headline, and 60/120/250 are run alongside as
a cheap sensitivity check -- if a verdict flipped with window, the headline would be an artifact
of one arbitrary choice and that has to be visible rather than assumed.

SIGNIFICANCE
------------
Median across cells is the headline (matching the candidate sweep's convention), but a median
gap is not on its own a test. Under the null hypothesis that an axis has no persistent
structure, the real and permuted reliabilities of a cell are exchangeable, so the count of cells
with real > null is Binomial(n_cells, 0.5). The exact two-sided sign test on that count is
reported per axis-column and timeframe.

Read-only diagnostic: no `feature_vectors` writes, no `config_state` writes, no
`regime_writer.py` CLI invocation, no modification to `services/regime_writer.py` or to either
sweep script this one imports from.

Usage:
    .venv/bin/python scripts/analysis/hmm_production_regime_axes_null_arm_validation.py
    .venv/bin/python scripts/analysis/hmm_production_regime_axes_null_arm_validation.py \
        --axes volatility --symbols SPY TLT --tf 1d --skip-sweep
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import as_completed
from math import comb
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np  # noqa: E402
import psycopg  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

from scripts.analysis.hmm_candidate_regime_axes_identifiability_sweep import (  # noqa: E402
    _MIN_PROBE_BLOCKS,
    _block_reliability,
    _load_regime_groups,
    _place,
    _rolling_sum,
    _sliding,
)
from scripts.analysis.hmm_regime_axis_decomposition_identifiability_sweep import (  # noqa: E402
    _AGREEMENT_THRESHOLD,
    _AXIS_COLUMNS,
    _KAPPA_THRESHOLD,
    _fetch_ohlcv,
    _load_config,
    _passes,
    _run_config_cell,
)
from services._batch_utils import make_worker_pool as _make_worker_pool  # noqa: E402
from services.regime_writer import _build_obs_matrix  # noqa: E402
from src.config.settings import Settings  # noqa: E402

# todo 216: BLAS thread cap, see make_worker_pool()/limit_blas_threads(). A bare pool
# construction silently reintroduces the OpenBLAS oversubscription bug (24 cores x N workers x
# default BLAS threads); this is the project-wide fix, applied per-worker via the pool's
# initializer rather than a module-level env-var guess.
_BLAS_THREADS_PER_WORKER = 1

# The 17-symbol set the widened trend check used. Kept identical so the fx/commodity/rates/
# intl-equity-vs-domestic-equity split that check surfaced is testable here on the same cells.
_DEFAULT_SYMBOLS = [
    "SPY",
    "IWM",
    "TLT",
    "GLD",
    "XLE",
    "EEM",
    "FXY",
    "SMH",
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "JPM",
    "QQQ",
    "DIA",
    "XLF",
    "XLK",
]
_DEFAULT_TFS = ["1d", "1h"]

# Only the configurations Phase 172 would actually ship, and only axes that already cleared the
# weaker agreement/kappa battery. `volume` is excluded on purpose (see module docstring).
_AXIS_K_VALUES: dict[str, list[int]] = {
    "composite": [3],
    "trend": [2, 3],
    "volatility": [2, 3],
    "trend_volatility": [3],
}

# `full` only -- production's own choice, and the decomposition sweep showed diag never changed a
# verdict on any axis.
_COV_TYPE = "full"

_DEFAULT_N_VALUES = [5, 10, 20]

# Production's own observation column names, in `_build_obs_matrix` order.
_COLUMN_NAMES = ("log_return", "realized_vol", "momentum", "vol_of_vol", "rel_volume")

# Column 0 of every axis slice is the dimension `_build_label_map` rank-orders states by, i.e.
# the column that gives the emitted labels their semantics.
_ORDERING_COLUMN = {axis: cols[0] for axis, cols in _AXIS_COLUMNS.items()}

_DEFAULT_PROBE_WINDOWS = [20, 60, 120, 250]
_PRODUCTION_WINDOW = 20
_DEFAULT_PROBE_REPLICATES = 5

# Applied twice: the real arm's median reliability must exceed this in absolute terms (the
# statistic persists across a block boundary at all), AND must exceed the null arm's by this
# much (it is not just the two-window columns' overlap artifact). [initial_estimate] -- a
# reasoned floor, not a calibrated one; 0.10 is the same magnitude the candidate sweep used as
# its absolute signal floor. Every measured value is printed alongside the verdict so a reader
# can apply a different bar without re-running.
_MARGIN_FLOOR = 0.10

_MIN_OBS = 250

_RESULTS_PATH = Path("cache/hmm_production_regime_axes_null_arm_validation.json")


# ---------------------------------------------------------------------------
# Block-level statistics
# ---------------------------------------------------------------------------


def _rolling_std(a: np.ndarray, window: int) -> np.ndarray:
    sw = _sliding(a, window)
    return _place(None if sw is None else sw.std(axis=1), len(a), window)


def _rolling_mean(a: np.ndarray, window: int) -> np.ndarray:
    sw = _sliding(a, window)
    return _place(None if sw is None else sw.mean(axis=1), len(a), window)


def _block_statistics(
    log_returns: np.ndarray, log_volumes: np.ndarray, window: int, vol_window: int
) -> dict[str, np.ndarray]:
    """Block-level analogue of each of production's five observation columns.

    All arrays are right-aligned with a NaN warm-up prefix, so the value at index
    `i*window - 1` is exactly the statistic of block [(i-1)*window, i*window) and
    `_block_reliability`'s stride-`window` subsample yields non-overlapping estimates.
    """
    ret_sum = _rolling_sum(log_returns, window)
    ret_std = _rolling_std(log_returns, window)
    realized_vol_inner = _rolling_std(log_returns, vol_window)
    rel_volume_inner = log_volumes - _rolling_mean(log_volumes, vol_window)
    return {
        "log_return": ret_sum,
        "realized_vol": ret_std,
        # Production's own formula (`sum(r) / max(realized_vol, 1e-8)`) with both of its windows
        # set to the block width, so this is the block's vol-normalized drift.
        "momentum": ret_sum / np.maximum(ret_std, 1e-8),
        "vol_of_vol": _rolling_std(realized_vol_inner, window),
        "rel_volume": _rolling_mean(rel_volume_inner, window),
    }


def _run_probe_cell(job: dict) -> dict:
    """Real and null block reliability of all five production columns at one (cell, window).

    The null jointly permutes returns and log volumes with a single permutation, preserving both
    marginal distributions and their contemporaneous relationship exactly while destroying all
    time dependence. Compute-only: no DB handle, no writes.
    """
    log_returns: np.ndarray = job["log_returns"]
    log_volumes: np.ndarray = job["log_volumes"]
    window = job["window"]
    vol_window = job["vol_window"]

    real = _block_statistics(log_returns, log_volumes, window, vol_window)
    real_reliability: dict[str, float] = {}
    n_pairs: dict[str, int] = {}
    for name, values in real.items():
        coefficient, pairs = _block_reliability(values, window)
        real_reliability[name] = coefficient
        n_pairs[name] = pairs

    rng = np.random.default_rng(job["seed"])
    null_samples: dict[str, list[float]] = {name: [] for name in _COLUMN_NAMES}
    for _ in range(job["replicates"]):
        order = rng.permutation(len(log_returns))
        null = _block_statistics(log_returns[order], log_volumes[order], window, vol_window)
        for name, values in null.items():
            coefficient, _ = _block_reliability(values, window)
            if np.isfinite(coefficient):
                null_samples[name].append(coefficient)

    return {
        "symbol": job["symbol"],
        "tf": job["tf"],
        "window": window,
        "n_obs": int(len(log_returns)),
        "columns": {
            name: {
                "block_reliability": real_reliability[name],
                "null_block_reliability": (
                    float(np.mean(null_samples[name])) if null_samples[name] else float("nan")
                ),
                "null_block_reliability_max": (
                    float(np.max(null_samples[name])) if null_samples[name] else float("nan")
                ),
                "n_block_pairs": n_pairs[name],
            }
            for name in _COLUMN_NAMES
        },
    }


def _permuted_series(
    closes: list[float], volumes: list[float], seed: int
) -> tuple[list[float], list[float]]:
    """Prices/volumes whose implied log returns and log volumes are an IID permutation of the
    real ones, so `_build_obs_matrix` can be called on the null arm unmodified.

    Reconstructing a price path from permuted returns (rather than permuting the obs matrix) is
    what makes the null arm a genuine counterfactual for production's pipeline: every column is
    then rebuilt by production's own code from a series with no time dependence.
    """
    closes_arr = np.asarray(closes, dtype=float)
    volumes_arr = np.maximum(np.asarray(volumes, dtype=float), 1.0)
    log_returns = np.log(closes_arr[1:] / np.maximum(closes_arr[:-1], 1e-12))
    log_volumes = np.log(volumes_arr[1:])

    order = np.random.default_rng(seed).permutation(len(log_returns))
    null_closes = np.concatenate(
        [closes_arr[:1], closes_arr[0] * np.exp(np.cumsum(log_returns[order]))]
    )
    null_volumes = np.concatenate([volumes_arr[:1], np.exp(log_volumes[order])])
    return list(null_closes), list(null_volumes)


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------


def _sign_test_p(n_greater: int, n_total: int) -> float:
    """Exact two-sided binomial sign test at p=0.5.

    Under 'this axis has no persistent structure', a cell's real and permuted reliabilities are
    exchangeable, so the count of cells where real > null is Binomial(n, 0.5). This converts a
    median gap into a statement about how often the gap has the same sign.
    """
    if n_total == 0:
        return float("nan")
    extreme = max(n_greater, n_total - n_greater)
    tail = sum(comb(n_total, i) for i in range(extreme, n_total + 1))
    return min(1.0, 2.0 * tail / (2.0**n_total))


def _column_stats(rows: list[dict], column: str) -> dict | None:
    """Median real/null reliability and the sign test, across whatever cells `rows` holds."""
    pairs = [
        (r["columns"][column]["block_reliability"], r["columns"][column]["null_block_reliability"])
        for r in rows
        if np.isfinite(r["columns"][column]["block_reliability"])
        and np.isfinite(r["columns"][column]["null_block_reliability"])
    ]
    if not pairs:
        return None
    real = np.array([p[0] for p in pairs])
    null = np.array([p[1] for p in pairs])
    n_greater = int(np.count_nonzero(real > null))
    return {
        "n_cells": len(pairs),
        "median_real": float(np.median(real)),
        "median_null": float(np.median(null)),
        "median_margin": float(np.median(real - null)),
        "min_real": float(real.min()),
        "max_null": float(null.max()),
        "n_real_gt_null": n_greater,
        "sign_test_p": _sign_test_p(n_greater, len(pairs)),
        "median_pairs": float(np.median([r["columns"][column]["n_block_pairs"] for r in rows])),
    }


def _print_probe_summary(probe_rows: list[dict], windows: list[int], tfs: list[str]) -> None:
    print("\n" + "=" * 118)
    print("BLOCK RELIABILITY, PER PRODUCTION OBSERVATION COLUMN")
    print("corr of the column's block-level estimate across ADJACENT DISJOINT blocks. real minus")
    print("null is the bar -- an absolute value is not, because vol_of_vol and rel_volume are")
    print("two-window statistics whose inner estimator straddles the block boundary and so carry")
    print("an overlap-induced positive null. sign p = exact two-sided binomial on #(real>null).")
    print("=" * 118)
    print(
        f"{'column':<14} {'W':>4} {'tf':>4} {'cells':>6} {'med_real':>9} {'med_null':>9} "
        f"{'margin':>8} {'min_real':>9} {'max_null':>9} {'real>null':>10} {'sign_p':>10} "
        f"{'pairs':>7}"
    )
    for column in _COLUMN_NAMES:
        for window in windows:
            for tf in tfs:
                rows = [r for r in probe_rows if r["window"] == window and r["tf"] == tf]
                stats = _column_stats(rows, column)
                if stats is None:
                    continue
                print(
                    f"{column:<14} {window:>4} {tf:>4} {stats['n_cells']:>6} "
                    f"{stats['median_real']:>9.3f} {stats['median_null']:>9.3f} "
                    f"{stats['median_margin']:>8.3f} {stats['min_real']:>9.3f} "
                    f"{stats['max_null']:>9.3f} "
                    f"{f'{stats["n_real_gt_null"]}/{stats["n_cells"]}':>10} "
                    f"{stats['sign_test_p']:>10.2e} {stats['median_pairs']:>7.0f}"
                )


def _print_group_breakdown(
    probe_rows: list[dict], group_by_symbol: dict[str, str], window: int, tfs: list[str]
) -> None:
    """Does the equity vs fx/commodity/rates/intl split the widened trend check found in
    agreement/kappa/occupation reappear in block reliability, or is it a different pattern?"""
    print("\n" + "=" * 118)
    print(f"BLOCK RELIABILITY BY REGIME GROUP at W={window} (group from")
    print("ic_engine._build_symbol_regime_class -- the same routing any group-specific K would")
    print("have to be expressed through)")
    print("=" * 118)
    groups = sorted({group_by_symbol.get(r["symbol"], "UNROUTED") for r in probe_rows})
    print(f"{'column':<14} {'tf':>4} " + "".join(f"{g[:15]:>17}" for g in groups))
    for column in _COLUMN_NAMES:
        for tf in tfs:
            line = f"{column:<14} {tf:>4} "
            for group in groups:
                rows = [
                    r
                    for r in probe_rows
                    if r["window"] == window
                    and r["tf"] == tf
                    and group_by_symbol.get(r["symbol"], "UNROUTED") == group
                ]
                stats = _column_stats(rows, column)
                line += (
                    f"{'-':>17}"
                    if stats is None
                    else f"{f'{stats["median_real"]:+.2f}/{stats["median_null"]:+.2f}':>17}"
                )
            print(line)
    print("(cell = median_real / median_null across that group's symbols)")


def _axis_verdicts(probe_rows: list[dict], axes: list[str], window: int) -> list[dict]:
    """Per-axis verdict from the columns that axis actually consumes, pooled over timeframes."""
    print("\n" + "=" * 118)
    print(f"PER-AXIS VERDICT at W={window} (production parity), pooled over timeframes")
    print("A column carries real structure only when ALL THREE hold:")
    print(f"  persists  median(real) > {_MARGIN_FLOOR} -- a regime must survive the block")
    print("            boundary at all; a negative coefficient is an alternating artifact, not a")
    print("            state that persists")
    print(f"  beats null median(real - null) > {_MARGIN_FLOOR} -- clears its OWN permutation")
    print("            control, which is what the two-window columns' overlap inflates")
    print("  consistent  exact two-sided sign test on #(real > null) rejects at p < 0.05")
    print("The ORDERING column is called out separately: it is what `_build_label_map` ranks")
    print("states by, so it is what the emitted labels MEAN.")
    print("=" * 118)
    rows = [r for r in probe_rows if r["window"] == window]
    verdicts: list[dict] = []
    for axis in axes:
        print(f"\n-- axis: {axis}  columns={_AXIS_COLUMNS[axis]}")
        print(
            f"   {'column':<14} {'role':<9} {'med_real':>9} {'med_null':>9} {'margin':>8} "
            f"{'sign_p':>10} {'persists':>9} {'beats null':>11} {'real?':>7}"
        )
        real_columns: list[str] = []
        ordering_real = False
        for index in _AXIS_COLUMNS[axis]:
            column = _COLUMN_NAMES[index]
            stats = _column_stats(rows, column)
            if stats is None:
                continue
            persists = stats["median_real"] > _MARGIN_FLOOR
            beats_null = stats["median_margin"] > _MARGIN_FLOOR
            is_real = persists and beats_null and stats["sign_test_p"] < 0.05
            role = "ORDERING" if index == _ORDERING_COLUMN[axis] else ""
            if is_real:
                real_columns.append(column)
                ordering_real = ordering_real or index == _ORDERING_COLUMN[axis]
            print(
                f"   {column:<14} {role:<9} {stats['median_real']:>9.3f} "
                f"{stats['median_null']:>9.3f} {stats['median_margin']:>8.3f} "
                f"{stats['sign_test_p']:>10.2e} {('yes' if persists else 'NO'):>9} "
                f"{('yes' if beats_null else 'NO'):>11} {('yes' if is_real else 'NO'):>7}"
            )
        if not real_columns:
            verdict = "NOT VALIDATED"
        elif ordering_real:
            verdict = "VALIDATED"
        else:
            verdict = "PARTIAL"
        print(
            f"   => {verdict}: {len(real_columns)}/{len(_AXIS_COLUMNS[axis])} columns real "
            f"({', '.join(real_columns) if real_columns else 'none'}); ordering column "
            f"({_COLUMN_NAMES[_ORDERING_COLUMN[axis]]}) "
            f"{'carries' if ordering_real else 'DOES NOT carry'} real structure"
        )
        verdicts.append(
            {
                "axis": axis,
                "window": window,
                "verdict": verdict,
                "real_columns": real_columns,
                "ordering_column": _COLUMN_NAMES[_ORDERING_COLUMN[axis]],
                "ordering_column_real": ordering_real,
            }
        )
    return verdicts


def _print_sweep_summary(
    results: list[dict], axes: list[str], n_top: int, group_by_symbol: dict[str, str]
) -> list[dict]:
    """Real vs null arm on the identifiability battery itself. Headline is the MINIMUM across
    cells and the PASS COUNT, never an average."""
    print("\n" + "=" * 118)
    print("IDENTIFIABILITY BATTERY: REAL ARM vs NULL ARM")
    print("The null arm is production's own `_build_obs_matrix` rebuilt from an IID-permuted")
    print("return/volume series -- no regime exists in it by construction. A null arm that")
    print("passes as often as the real arm proves the battery is not evidence for the axis.")
    print("=" * 118)
    print(
        f"{'axis':<17} {'K':>2} {'real pass':>10} {'NULL pass':>10} {'real min_agree':>15} "
        f"{'NULL min_agree':>15} {'real degen':>11} {'NULL degen':>11} {'real med_sep':>13} "
        f"{'NULL med_sep':>13} {'informative':>12}"
    )
    config_rows: list[dict] = []
    for axis in axes:
        for k in _AXIS_K_VALUES[axis]:
            arms: dict[str, dict] = {}
            for arm in ("real", "null"):
                cells = [
                    r for r in results if r["axis"] == axis and r["k"] == k and r["arm"] == arm
                ]
                if not cells:
                    continue
                entries = [(r, r["by_n"].get(str(n_top), {})) for r in cells]
                valid = [(r, e) for r, e in entries if not e.get("pool_failure", True)]
                seps = [
                    float(e["separation_a"])
                    for _, e in valid
                    if e.get("separation_a") is not None and np.isfinite(float(e["separation_a"]))
                ]
                arms[arm] = {
                    "n_pass": sum(1 for _, e in entries if _passes(e)),
                    "n_cells": len(cells),
                    "min_agreement": min(e.get("agreement_smoothed", 0.0) for _, e in entries),
                    "min_kappa": min(e.get("kappa_smoothed", 0.0) for _, e in entries),
                    "median_separation": float(np.median(seps)) if seps else float("nan"),
                    "n_degenerate": sum(1 for _, e in valid if e.get("degenerate_a")),
                    "degenerate_cells": [
                        f"{r['symbol']}/{r['tf']}" for r, e in valid if e.get("degenerate_a")
                    ],
                    "failing_cells": [
                        f"{r['symbol']}/{r['tf']}" for r, e in entries if not _passes(e)
                    ],
                }
            if "real" not in arms or "null" not in arms:
                continue
            real, null = arms["real"], arms["null"]
            informative = (
                "yes"
                if null["n_pass"] / null["n_cells"] < real["n_pass"] / real["n_cells"]
                else "NO"
            )
            print(
                f"{axis:<17} {k:>2} "
                f"{f'{real["n_pass"]}/{real["n_cells"]}':>10} "
                f"{f'{null["n_pass"]}/{null["n_cells"]}':>10} "
                f"{real['min_agreement']:>15.4f} {null['min_agreement']:>15.4f} "
                f"{f'{real["n_degenerate"]}/{real["n_cells"]}':>11} "
                f"{f'{null["n_degenerate"]}/{null["n_cells"]}':>11} "
                f"{real['median_separation']:>13.2f} {null['median_separation']:>13.2f} "
                f"{informative:>12}"
            )
            config_rows.append({"axis": axis, "k": k, "n": n_top, "real": real, "null": null})

    print("\n" + "=" * 118)
    print("OCCUPATION-GATE DEGENERACY BY REGIME GROUP (real arm) -- does the widened trend")
    print("check's equity vs fx/commodity/rates/intl split hold up, and does the null arm show")
    print("the same pattern (which would make it a property of the fit, not of the data)?")
    print("=" * 118)
    groups = sorted({group_by_symbol.get(r["symbol"], "UNROUTED") for r in results})
    print(f"{'axis':<17} {'K':>2} {'arm':>5} " + "".join(f"{g[:13]:>15}" for g in groups))
    for row in config_rows:
        for arm in ("real", "null"):
            line = f"{row['axis']:<17} {row['k']:>2} {arm:>5} "
            for group in groups:
                bad = [
                    c
                    for c in set(row[arm]["failing_cells"]) | set(row[arm]["degenerate_cells"])
                    if group_by_symbol.get(c.split("/")[0], "UNROUTED") == group
                ]
                total = sum(
                    1
                    for r in results
                    if r["axis"] == row["axis"]
                    and r["k"] == row["k"]
                    and r["arm"] == arm
                    and group_by_symbol.get(r["symbol"], "UNROUTED") == group
                )
                line += f"{f'{len(bad)}/{total}':>15}"
            print(line)
    print("(cell = failing-or-degenerate cells / total cells in that group)")
    return config_rows


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _load_cells(
    conn: psycopg.Connection, symbols: list[str], tfs: list[str], seed: int
) -> dict[tuple[str, str], dict]:
    """Fetch OHLCV once per cell and derive both arms' inputs from it."""
    cells: dict[tuple[str, str], dict] = {}
    for tf in tfs:
        for symbol in symbols:
            timestamps, closes, volumes = _fetch_ohlcv(conn, symbol, tf)
            if len(timestamps) < 2:
                print(f"SKIP {symbol}/{tf}: no OHLCV rows")
                continue
            closes_arr = np.asarray(closes, dtype=float)
            volumes_arr = np.maximum(np.asarray(volumes, dtype=float), 1.0)
            log_returns = np.log(closes_arr[1:] / np.maximum(closes_arr[:-1], 1e-12))
            if len(log_returns) < _MIN_OBS:
                print(f"SKIP {symbol}/{tf}: insufficient history n={len(log_returns)}")
                continue
            null_closes, null_volumes = _permuted_series(closes, volumes, seed)
            cells[(symbol, tf)] = {
                "symbol": symbol,
                "tf": tf,
                "timestamps": timestamps,
                "log_returns": log_returns,
                "log_volumes": np.log(volumes_arr[1:]),
                "closes": {"real": closes, "null": null_closes},
                "volumes": {"real": volumes, "null": null_volumes},
            }
            print(f"loaded {symbol}/{tf}: n_returns={len(log_returns)}")
    return cells


def _build_sweep_jobs(cells: dict[tuple[str, str], dict], axes: list[str], cfg: dict) -> list[dict]:
    jobs: list[dict] = []
    for cell in sorted(cells):
        data = cells[cell]
        for arm in ("real", "null"):
            obs_full, _ = _build_obs_matrix(
                data["timestamps"],
                data["closes"][arm],
                data["volumes"][arm],
                vol_window=cfg["vol_window"],
                momentum_window=cfg["momentum_window"],
                vol_of_vol_window=cfg["vol_of_vol_window"],
            )
            if len(obs_full) < _MIN_OBS:
                print(f"SKIP {data['symbol']}/{data['tf']} arm={arm}: n_obs={len(obs_full)}")
                continue
            for axis in axes:
                obs = StandardScaler().fit_transform(obs_full[:, list(_AXIS_COLUMNS[axis])])
                for k in _AXIS_K_VALUES[axis]:
                    jobs.append(
                        {
                            "symbol": data["symbol"],
                            "tf": data["tf"],
                            "axis": axis,
                            "arm": arm,
                            "obs": obs,
                            "k": k,
                            "cov_type": _COV_TYPE,
                            "n_iter": cfg["n_iter"],
                            "full_cov_min_obs": cfg["full_cov_min_obs"],
                            "min_hold_bars": cfg["min_hold_bars"],
                            "min_state_occupation": cfg["min_state_occupation"],
                            "pool_a_base": cfg["pool_a_base"],
                            "pool_b_base": cfg["pool_b_base"],
                            "max_n": cfg["max_n"],
                            "n_values": cfg["n_values"],
                        }
                    )
    return jobs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=_DEFAULT_SYMBOLS)
    parser.add_argument("--tf", nargs="+", default=_DEFAULT_TFS)
    parser.add_argument("--axes", nargs="+", default=list(_AXIS_K_VALUES))
    parser.add_argument("--n-values", nargs="+", type=int, default=_DEFAULT_N_VALUES)
    parser.add_argument("--max-n", type=int, default=None)
    parser.add_argument("--pool-a-base", type=int, default=None)
    parser.add_argument("--pool-b-base", type=int, default=1000)
    parser.add_argument("--probe-windows", nargs="+", type=int, default=_DEFAULT_PROBE_WINDOWS)
    parser.add_argument("--probe-replicates", type=int, default=_DEFAULT_PROBE_REPLICATES)
    parser.add_argument(
        "--skip-sweep",
        action="store_true",
        help="Run only the block-reliability probe, skipping the HMM identifiability arms.",
    )
    parser.add_argument("--max-workers", type=int, default=16)
    parser.add_argument("--results-path", default=str(_RESULTS_PATH))
    args = parser.parse_args()

    max_n = args.max_n if args.max_n is not None else max(args.n_values)
    settings = Settings()
    conn = psycopg.connect(settings.database_url)
    raw_cfg = _load_config(conn)
    pool_a_base = (
        args.pool_a_base if args.pool_a_base is not None else int(raw_cfg["alpha.hmm.random_state"])
    )
    cfg = {
        "n_iter": int(raw_cfg["feature.hmm.n_iter"]),
        "full_cov_min_obs": int(raw_cfg["feature.hmm.full_cov_min_obs"]),
        "min_hold_bars": int(raw_cfg["feature.hmm.min_hold_bars"]),
        "min_state_occupation": float(raw_cfg["feature.hmm.min_state_occupation"]),
        "vol_window": int(raw_cfg["feature.hmm.vol_window"]),
        "momentum_window": int(raw_cfg["feature.hmm.obs_momentum_window"]),
        "vol_of_vol_window": int(raw_cfg["feature.hmm.obs_vol_of_vol_window"]),
        "pool_a_base": pool_a_base,
        "pool_b_base": args.pool_b_base,
        "max_n": max_n,
        "n_values": args.n_values,
    }
    group_by_symbol = _load_regime_groups(conn, list(args.symbols))

    print("=" * 118)
    print("NULL-ARM VALIDATION of the production regime axes Phase 172 would ship")
    print("=" * 118)
    for axis in args.axes:
        print(
            f"  axis {axis:<17} cols={_AXIS_COLUMNS[axis]} K={_AXIS_K_VALUES[axis]} "
            f"cov={_COV_TYPE} ordering_column={_COLUMN_NAMES[_ORDERING_COLUMN[axis]]}"
        )
    print(f"symbols={len(args.symbols)} tf={args.tf}  probe_windows={args.probe_windows}")
    print(f"production window={_PRODUCTION_WINDOW} (vol_window={cfg['vol_window']})")
    print(f"probe replicates={args.probe_replicates}  margin floor={_MARGIN_FLOOR}")
    print(f"n_values={args.n_values} max_n={max_n}  standardize=True (production parity)")
    print(
        f"n_iter={cfg['n_iter']} full_cov_min_obs={cfg['full_cov_min_obs']} "
        f"min_hold_bars={cfg['min_hold_bars']} "
        f"min_state_occupation={cfg['min_state_occupation']}"
    )
    print(f"pool_a_base={pool_a_base} pool_b_base={args.pool_b_base}")
    print(f"bars: agreement>={_AGREEMENT_THRESHOLD} AND kappa>={_KAPPA_THRESHOLD} (both required)")
    print("=" * 118)

    cells = _load_cells(conn, list(args.symbols), list(args.tf), pool_a_base)
    probe_jobs = [
        {
            "symbol": data["symbol"],
            "tf": data["tf"],
            "log_returns": data["log_returns"],
            "log_volumes": data["log_volumes"],
            "window": window,
            "vol_window": cfg["vol_window"],
            "replicates": args.probe_replicates,
            "seed": pool_a_base,
        }
        for data in (cells[c] for c in sorted(cells))
        for window in args.probe_windows
    ]
    sweep_jobs = [] if args.skip_sweep else _build_sweep_jobs(cells, list(args.axes), cfg)
    conn.close()

    # Heaviest jobs first: with a fixed worker pool, dispatching the long tail last leaves
    # workers idle at the end.
    sweep_jobs.sort(key=lambda j: -(len(j["obs"]) * j["k"] * j["obs"].shape[1]))
    print(f"\n{len(probe_jobs)} probe jobs, {len(sweep_jobs)} sweep jobs queued\n")

    probe_rows: list[dict] = []
    results: list[dict] = []
    t_start = time.monotonic()
    with _make_worker_pool(args.max_workers, _BLAS_THREADS_PER_WORKER) as pool:
        for future in as_completed([pool.submit(_run_probe_cell, j) for j in probe_jobs]):
            probe_rows.append(future.result())
        print(f"probe done in {time.monotonic() - t_start:.0f}s")
        _print_probe_summary(probe_rows, args.probe_windows, list(args.tf))
        _print_group_breakdown(probe_rows, group_by_symbol, _PRODUCTION_WINDOW, list(args.tf))
        verdicts = _axis_verdicts(probe_rows, list(args.axes), _PRODUCTION_WINDOW)

        t_sweep = time.monotonic()
        print()
        futures = {pool.submit(_run_config_cell, job): job for job in sweep_jobs}
        for done, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            result["arm"] = futures[future]["arm"]
            results.append(result)
            entry = result["by_n"].get(str(max_n), {})
            print(
                f"[{done}/{len(sweep_jobs)}] {result['symbol']}/{result['tf']} "
                f"axis={result['axis']:<17} K={result['k']} arm={result['arm']:<4} "
                f"agree={entry.get('agreement_smoothed', float('nan')):.4f} "
                f"kappa={entry.get('kappa_smoothed', float('nan')):.4f} "
                f"sep={entry.get('separation_a', float('nan')):.2f} "
                f"occ={entry.get('min_occupation_a', float('nan')):.3f} "
                f"({result['fit_seconds']:.0f}s)",
                flush=True,
            )
    if sweep_jobs:
        print(f"\nsweep done in {time.monotonic() - t_sweep:.0f}s")
    print(f"total {time.monotonic() - t_start:.0f}s")

    config_rows = (
        _print_sweep_summary(results, list(args.axes), max_n, group_by_symbol) if results else []
    )

    out_path = Path(args.results_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(
            {
                "agreement_threshold": _AGREEMENT_THRESHOLD,
                "kappa_threshold": _KAPPA_THRESHOLD,
                "margin_floor": _MARGIN_FLOOR,
                "min_probe_blocks": _MIN_PROBE_BLOCKS,
                "axis_columns": {a: list(_AXIS_COLUMNS[a]) for a in args.axes},
                "axis_k_values": {a: _AXIS_K_VALUES[a] for a in args.axes},
                "column_names": list(_COLUMN_NAMES),
                "cov_type": _COV_TYPE,
                "production_window": _PRODUCTION_WINDOW,
                "probe_windows": args.probe_windows,
                "probe_replicates": args.probe_replicates,
                "n_values": args.n_values,
                "max_n": max_n,
                "pool_a_base": pool_a_base,
                "pool_b_base": args.pool_b_base,
                "regime_group_by_symbol": group_by_symbol,
                "probe": probe_rows,
                "axis_verdicts": verdicts,
                "sweep_summary": config_rows,
                "results": results,
            },
            f,
            indent=2,
            default=str,
        )
    print(f"\nResults written to {out_path}")


if __name__ == "__main__":
    main()
