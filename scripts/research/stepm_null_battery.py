"""StepM through the E17 H0 battery (phase 187 plan 05; todo 448 item 4, todo 432).

Each simulation of a battery cell yields every arm's null D_s series on one calendar (family 1's
four members and their equal-weight book: a small, highly correlated null universe). StepM runs
over them; a simulation is a family-wise error when StepM selects any arm. Per cell, the
family-wise rejection count must be at most the upper 99% binomial quantile under `fwer` (the
E17 driver's one-sided rule). Cells in the battery's DIAGNOSTIC_CELLS are reported but do not
gate. Synthetic only: no database, no ledger. Writes one JSON record.

    .venv/bin/python scripts/research/stepm_null_battery.py <out.json> [--sims 1000]
        [--workers 20] [--reps 500] [--block-mean 20] [--fwer 0.05] [--cells a,b]
        [--studentize draw|sample]
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.stats import binom

sys.path.insert(0, ".")
from services._batch_utils import make_worker_pool  # noqa: E402
from src.intelligence.statistics.stepm import stepm  # noqa: E402

_BOUND_QUANTILE = 0.99
# The battery's target is the next bar's return: the longest holding horizon is one session.
_MAX_HORIZON_SESSIONS = 1


def simulate_stepm(args: tuple) -> tuple[str, bool, float]:
    """(cell, any arm selected, smallest adjusted p) for one null simulation."""
    module, sc, seed, reps, block_mean, fwer, studentize = args
    series = importlib.import_module(module).simulate_series(sc, seed)
    matrix = np.column_stack([series[arm] for arm in sorted(series)])
    out = stepm(
        matrix,
        block_mean=block_mean,
        max_horizon_sessions=_MAX_HORIZON_SESSIONS,
        reps=reps,
        fwer=fwer,
        seed=seed,
        studentize=studentize,
    )
    return sc.name, bool(out.selected.any()), float(out.adjusted_p.min())


def summarize(name: str, hits: list[bool], fwer: float, diagnostic: frozenset) -> dict:
    n = len(hits)
    rejected = sum(hits)
    bound = int(binom.ppf(_BOUND_QUANTILE, n, fwer))
    return {
        "cell": name,
        "sims": n,
        "familywise_rejections": rejected,
        "rate": rejected / n,
        "bound": bound,
        "gating": name not in diagnostic,
        "holds": rejected <= bound,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--sims", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--reps", type=int, default=500)
    parser.add_argument("--block-mean", type=float, default=20.0)
    parser.add_argument("--fwer", type=float, default=0.05)
    parser.add_argument("--cells", default=None)
    parser.add_argument("--studentize", choices=("draw", "sample"), default="draw")
    parser.add_argument("--battery", default="src.intelligence.research.null_battery")
    args = parser.parse_args()
    battery = importlib.import_module(args.battery)
    cells = battery.scenarios()
    if args.cells:
        wanted = set(args.cells.split(","))
        cells = tuple(sc for sc in cells if sc.name in wanted)
    start = time.time()
    jobs = [
        (args.battery, sc, 10_000 * k + i, args.reps, args.block_mean, args.fwer, args.studentize)
        for k, sc in enumerate(cells)
        for i in range(args.sims)
    ]
    report = []
    progress = Path(args.out).with_suffix(".partial.jsonl")
    progress.parent.mkdir(parents=True, exist_ok=True)
    # One cell at a time, each cell's row appended as it finishes: a stopped run keeps every
    # finished cell (rerun the rest with --cells).
    with make_worker_pool(args.workers, blas_threads_per_worker=1) as pool:
        for sc in cells:
            cell_jobs = [j for j in jobs if j[1].name == sc.name]
            results = list(pool.map(simulate_stepm, cell_jobs, chunksize=4))
            row = summarize(
                sc.name, [h for _, h, _ in results], args.fwer, battery.DIAGNOSTIC_CELLS
            )
            row["median_min_adjusted_p"] = float(np.median([p for _, _, p in results]))
            report.append(row)
            with progress.open("a") as fh:
                fh.write(json.dumps(row) + "\n")
            print(
                f"{sc.name:22s} {'gate' if row['gating'] else 'diag'} "
                f"{row['familywise_rejections']}/{row['bound']} rate {row['rate']:.3f}",
                flush=True,
            )
    failures = [r["cell"] for r in report if r["gating"] and not r["holds"]]
    record = {
        "schema": "stepm_null_battery_v1",
        "battery": args.battery,
        "sims_per_cell": args.sims,
        "reps": args.reps,
        "block_mean": args.block_mean,
        "fwer": args.fwer,
        "studentize": args.studentize,
        "bound_quantile": _BOUND_QUANTILE,
        "report": report,
        "failures": failures,
        "seconds": time.time() - start,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(record, indent=2))
    print("FWER HOLDS" if not failures else f"FWER FAILS: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
