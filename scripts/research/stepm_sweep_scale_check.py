"""What an IC sweep costs the recorded selection: StepM on the recorded series plus null cells
(todo 670; ledger 2026-11-24i: a disclosure, not a gate).

The recorded universe (the counted attempts of the vintage that have a series) is read as
`select_books` reads it. To it are appended mean-zero null cells at the sweep's scale: each of
`--cells` base cells enters twice, as itself and as its negation (the long and the mirrored short
of ledger 2026-11-24i). The shipped `stepm.stepm` runs unchanged on the whole matrix; the report
says, per setting, how often each recorded series stays selected, its adjusted p, and how many
null cells were falsely selected. It opens no run, writes no database row and is no counted look:
it reads recorded series and draws synthetic ones.

The null cells are the only invented data. Each has mean exactly zero, so every one is true under
H0 and the check measures the price of multiplicity, never power. A cell at horizon h in
(1, 2, 5, 10) is the moving sum of h session shocks (the MA(h - 1) overlap of overlapping
targets), shocks are Student t (5 degrees of freedom) or normal, cells are grouped so that the
`n_eff` groups are independent and cells inside a group correlate at WITHIN_GROUP_CORR (n_eff =
cells means independent cells, the bound), and each cell's first w sessions are missing (warmup,
w uniform to WARMUP_MAX) so the per-draw studentization sees unequal spans. This bounds the cost;
it does not predict real cell series.

The settings below are declared in a dated line of docs/plans/methodology-change-ledger.md before
a run and mirrored here as named constants (APR exempt: pre-registered gate constants); a new value
is a new dated line. `--seed-base` has no default for the same reason.

    .venv/bin/python scripts/research/stepm_sweep_scale_check.py <out.json> --seed-base N
        [--cells 1108] [--workers 4] [--replicates 8] [--n-eff 8,50,0] [--tails t5,normal]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.research.select_books import attempt_universe  # noqa: E402
from scripts.research.stepm_null_battery import stepm_source_sha256  # noqa: E402
from src.intelligence.statistics.stepm import stepm  # noqa: E402

# Declared settings (ledger line before the first run); changing one is a new dated line.
CELL_HORIZONS = (1, 2, 5, 10)
WITHIN_GROUP_CORR = 0.9
SCALE_RANGE = (0.02, 0.03)
WARMUP_MAX = 252
T_DF = 5
TAILS = ("t5", "normal")
DEFAULT_N_EFF = (8, 50, 0)  # 0 stands for independent cells (n_eff = cells)
DEFAULT_REPLICATES = 8
DEFAULT_CELLS = 1108


def _shocks(rng: np.random.Generator, shape: tuple[int, int], tail: str) -> np.ndarray:
    if tail == "normal":
        return rng.standard_normal(shape)
    if tail == "t5":
        return rng.standard_t(T_DF, size=shape) / np.sqrt(T_DF / (T_DF - 2))
    raise ValueError(f"tail must be one of {TAILS}, got {tail!r}")


def null_block(n_sessions: int, n_cells: int, *, n_eff: int, tail: str, seed: int) -> np.ndarray:
    """[n_sessions, 2 * n_cells]: `n_cells` mean-zero null cells and their negations (columns
    n_cells onward). n_eff = 0 or >= n_cells draws independent cells; otherwise cell j belongs to
    group j % n_eff and cells of a group share one factor at WITHIN_GROUP_CORR."""
    if n_cells < 1 or n_sessions < max(CELL_HORIZONS) + 2:
        raise ValueError(f"need n_cells >= 1 and enough sessions, got {n_cells}, {n_sessions}")
    rng = np.random.default_rng(seed)
    lead = max(CELL_HORIZONS) - 1
    rows = n_sessions + lead
    idio = _shocks(rng, (rows, n_cells), tail)
    if n_eff and n_eff < n_cells:
        factor = _shocks(rng, (rows, n_eff), tail)
        group = np.arange(n_cells) % n_eff
        shocks = (
            np.sqrt(WITHIN_GROUP_CORR) * factor[:, group] + np.sqrt(1 - WITHIN_GROUP_CORR) * idio
        )
    else:
        shocks = idio
    horizon = np.resize(np.array(CELL_HORIZONS), n_cells)
    cumulative = np.vstack([np.zeros((1, n_cells)), np.cumsum(shocks, axis=0)])
    cells = np.empty((n_sessions, n_cells))
    for h in CELL_HORIZONS:
        cols = np.flatnonzero(horizon == h)
        # session t holds the sum of shocks t .. t + h - 1 (an h-session overlap), unit variance
        window = cumulative[h : n_sessions + h, cols] - cumulative[:n_sessions, cols]
        cells[:, cols] = window / np.sqrt(h)
    cells *= rng.uniform(*SCALE_RANGE, size=n_cells)
    warmup = rng.integers(0, WARMUP_MAX + 1, size=n_cells)
    cells[np.arange(n_sessions)[:, None] < warmup[None, :]] = np.nan
    return np.concatenate([cells, -cells], axis=1)


def run_replicate(job: dict) -> dict:
    """One StepM run on [recorded | null block]; the shipped function, unchanged."""
    recorded = job["recorded"]
    k = recorded.shape[1]
    if job["n_cells"]:
        block = null_block(
            recorded.shape[0],
            job["n_cells"],
            n_eff=job["n_eff"],
            tail=job["tail"],
            seed=job["null_seed"],
        )
        matrix = np.concatenate([recorded, block], axis=1)
    else:
        matrix = recorded
    out = stepm(
        matrix,
        block_mean=job["block_mean"],
        max_horizon_sessions=job["max_horizon"],
        reps=job["reps"],
        fwer=job["fwer"],
        seed=job["stepm_seed"],
    )
    return {
        "recorded_selected": out.selected[:k].tolist(),
        "recorded_adjusted_p": out.adjusted_p[:k].tolist(),
        "false_selections": int(out.selected[k:].sum()),
    }


def summarize(replicates: list[dict], labels: list[str]) -> dict:
    """Per recorded series: the share of replicates that keep it selected and its adjusted p."""
    selected = np.array([r["recorded_selected"] for r in replicates], dtype=bool)
    adjusted = np.array([r["recorded_adjusted_p"] for r in replicates])
    return {
        "replicates": len(replicates),
        "false_selection_replicates": int(sum(r["false_selections"] > 0 for r in replicates)),
        "false_selections_total": int(sum(r["false_selections"] for r in replicates)),
        "series": [
            {
                "label": label,
                "share_selected": float(selected[:, i].mean()),
                "adjusted_p_median": float(np.median(adjusted[:, i])),
                "adjusted_p_min": float(adjusted[:, i].min()),
                "adjusted_p_max": float(adjusted[:, i].max()),
            }
            for i, label in enumerate(labels)
        ],
    }


async def _recorded(dsn: str, vintage: str | None):
    from scripts.research.select_books import _load, repo_root  # noqa: PLC0415

    rows, _others, apr, vintage = await _load(dsn, vintage)
    with_series = [r for r in rows if r["sessions"] is not None]
    if not with_series:
        raise SystemExit("no counted attempt with a series in the vintage")
    horizons, _calendar, matrix = attempt_universe(with_series, repo_root(Path.cwd()))
    labels = [f"{r['concept']}:{r['run_id'][:8]}" for r in with_series]
    return matrix, max(horizons), labels, apr, vintage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--seed-base", type=int, required=True, help="declared in the ledger line")
    parser.add_argument("--cells", type=int, default=DEFAULT_CELLS)
    parser.add_argument("--replicates", type=int, default=DEFAULT_REPLICATES)
    parser.add_argument("--n-eff", default=",".join(map(str, DEFAULT_N_EFF)))
    parser.add_argument("--tails", default=",".join(TAILS))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--vintage", default=None)
    parser.add_argument("--dsn", default=None)
    args = parser.parse_args()

    from services.batch_support.pool import make_worker_pool  # noqa: PLC0415
    from src.config.settings import Settings  # noqa: PLC0415

    dsn = args.dsn or Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    recorded, max_horizon, labels, apr, vintage = asyncio.run(_recorded(dsn, args.vintage))
    n_eff_settings = [int(v) for v in args.n_eff.split(",")]
    tails = args.tails.split(",")
    base = {
        "recorded": recorded,
        "max_horizon": max_horizon,
        "block_mean": float(apr["alpha.selection.stepm.block_mean_sessions"]),
        "reps": int(apr["alpha.selection.stepm.reps"]),
        "fwer": float(apr["alpha.selection.stepm.fwer"]),
        "stepm_seed": int(apr["alpha.selection.stepm.seed"]),
    }
    start = time.time()
    settings = [(n_eff, tail) for tail in tails for n_eff in n_eff_settings]
    jobs = [
        {
            **base,
            "n_cells": args.cells,
            "n_eff": n_eff,
            "tail": tail,
            "null_seed": args.seed_base + 10_000 * k + r,
        }
        for k, (n_eff, tail) in enumerate(settings)
        for r in range(args.replicates)
    ]
    # Regression guard: no null cells reproduces the recorded StepM selection.
    baseline = run_replicate({**base, "n_cells": 0})
    report = []
    with make_worker_pool(args.workers, blas_threads_per_worker=1) as pool:
        results = list(pool.map(run_replicate, jobs, chunksize=1))
    for k, (n_eff, tail) in enumerate(settings):
        chunk = results[k * args.replicates : (k + 1) * args.replicates]
        report.append({"n_eff": n_eff or args.cells, "tail": tail, **summarize(chunk, labels)})
    record = {
        "schema": "stepm_sweep_scale_check_v1",
        "vintage": vintage,
        "stepm_sha256": stepm_source_sha256(),
        "declared": {
            "cells": args.cells,
            "columns_appended": 2 * args.cells,
            "replicates": args.replicates,
            "n_eff": n_eff_settings,
            "tails": tails,
            "within_group_corr": WITHIN_GROUP_CORR,
            "cell_horizons": list(CELL_HORIZONS),
            "scale_range": list(SCALE_RANGE),
            "warmup_max": WARMUP_MAX,
            "seed_base": args.seed_base,
        },
        "stepm": {k: base[k] for k in ("block_mean", "reps", "fwer", "stepm_seed", "max_horizon")},
        "recorded_labels": labels,
        "baseline_without_null_cells": baseline,
        "report": report,
        "seconds": time.time() - start,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(record, indent=2))
    for row in report:
        kept = ", ".join(
            f"{s['share_selected']:.2f}" for s in row["series"] if s["share_selected"] > 0
        )
        print(
            f"n_eff {row['n_eff']:5d} {row['tail']:6s} selected shares [{kept}] "
            f"false-selection replicates {row['false_selection_replicates']}/{row['replicates']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
