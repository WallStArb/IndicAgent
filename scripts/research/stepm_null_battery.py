"""StepM through the E17 H0 battery (phase 187 plan 05; todo 448 item 4, todo 432).

Each simulation of a battery cell yields every arm's null D_s series on one calendar (family 1's
four members and their equal-weight book: a small, highly correlated null universe). StepM runs
over them; a simulation is a family-wise error when StepM selects any arm. Per cell, the
family-wise rejection count must be at most the upper binomial quantile under `fwer` at the
Bonferroni level 1 - 0.01 / 20 (step B), and the pooled gating rate at most 6%. Cells in the battery's DIAGNOSTIC_CELLS are reported but do not
gate. Synthetic only: no database, no ledger. Writes one JSON record.

    .venv/bin/python scripts/research/stepm_null_battery.py <out.json> [--sims 1000]
        [--workers 20] [--reps 500] [--block-mean 20] [--fwer 0.05] [--cells a,b]
        [--studentize draw|sample] [--sessions 4000]

The attestation select_books accepts is a complete run at REAL_SESSIONS, the real panel length
(owner decision 2026-10-27: on the battery's 1,500-session default panels E17's short-panel
excess pushes two cells over the bound; at 4,000 sessions they hold).
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib
import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.stats import binom

sys.path.insert(0, ".")
from services._batch_utils import make_worker_pool  # noqa: E402
from src.intelligence.statistics import stepm as stepm_module  # noqa: E402
from src.intelligence.statistics.stepm import stepm  # noqa: E402

# Step B pass rule (owner decision 2026-10-27, todo 549; written before the run it judges, and
# judged on that run only): each cell's family-wise rejection count is at most the upper binomial
# quantile at a Bonferroni level over the battery's 20 cells (1 - 0.01 / 20), and the rejection
# rate pooled over the gating cells is at most _POOLED_TOLERANCE.
_BATTERY_CELLS = 20
_BOUND_QUANTILE = 1 - 0.01 / _BATTERY_CELLS
_POOLED_TOLERANCE = 0.06
# The panel length the attestation is judged at (owner decision 2026-10-27, methodology-change
# ledger E18 implementation note): about the real span of the vintage-1 panels.
REAL_SESSIONS = 4000
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


def stepm_source_sha256() -> str:
    """The content hash of the StepM module a battery record attests."""
    return hashlib.sha256(Path(stepm_module.__file__).read_bytes()).hexdigest()


def pooled_rate(report: list[dict]) -> float:
    """Family-wise rejection rate over every simulation of every gating cell."""
    gating = [r for r in report if r["gating"]]
    return sum(r["familywise_rejections"] for r in gating) / sum(r["sims"] for r in gating)


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
    parser.add_argument(
        "--seed-base",
        type=int,
        default=0,
        help="added to every simulation seed; a new base is a fresh run (0 reproduces the "
        "2026-10-27 run's seeds)",
    )
    parser.add_argument(
        "--sessions", type=int, default=REAL_SESSIONS, help="override every cell's panel length"
    )
    args = parser.parse_args()
    battery = importlib.import_module(args.battery)
    cells = tuple(dataclasses.replace(sc, sessions=args.sessions) for sc in battery.scenarios())
    if args.cells:
        wanted = set(args.cells.split(","))
        cells = tuple(sc for sc in cells if sc.name in wanted)
    start = time.time()
    jobs = [
        (
            args.battery,
            sc,
            args.seed_base + 10_000 * k + i,
            args.reps,
            args.block_mean,
            args.fwer,
            args.studentize,
        )
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
    pooled = pooled_rate(report)
    if pooled > _POOLED_TOLERANCE:
        failures.append("pooled")
    record = {
        "schema": "stepm_null_battery_v1",
        "battery": args.battery,
        # select_books accepts a record as its attestation only when it covers every cell and
        # was run on the StepM code it is about to use.
        "complete": args.cells is None,
        "sessions": args.sessions,
        "stepm_sha256": stepm_source_sha256(),
        "sims_per_cell": args.sims,
        "reps": args.reps,
        "block_mean": args.block_mean,
        "fwer": args.fwer,
        "studentize": args.studentize,
        "bound_quantile": _BOUND_QUANTILE,
        "seed_base": args.seed_base,
        "pooled_rate": pooled,
        "pooled_tolerance": _POOLED_TOLERANCE,
        "report": report,
        "failures": failures,
        "seconds": time.time() - start,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(record, indent=2))
    verdict = "FWER HOLDS" if not failures else f"FWER FAILS: {failures}"
    print(verdict if record["complete"] else f"{verdict} (partial run: not an attestation)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
