"""E17 condition 2: the H0 battery for the timing statistic (methodology-change-ledger E17).

Runs `sims` simulations of each scenario in src/intelligence/research/null_battery.py and
reports, per scenario and arm (each family 1 member and the equal-weight book), the rejection
rate of the one-sided HAC test at 0.05, 0.01 and 0.00167 and the mean and sd of t. Size holds
at a level when the rejection count is at most the upper 99% binomial quantile under that level
(a one-sided check: an undersized test is conservative, an oversized one is not). Writes one
JSON record to the output path.

    .venv/bin/python scripts/research/e17_null_battery.py <out.json> [--sims 1000] [--workers 6]
        [--cells name,name]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from scipy.stats import binom

sys.path.insert(0, ".")
from services._batch_utils import make_worker_pool  # noqa: E402
from src.intelligence.research.null_battery import (  # noqa: E402
    ALPHAS,
    DIAGNOSTIC_CELLS,
    scenarios,
    simulate,
)

_BOUND_QUANTILE = 0.99


def _run(args: tuple) -> tuple[str, dict]:
    sc, seed = args
    return sc.name, simulate(sc, seed)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--sims", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--cells", default=None, help="comma-separated scenario names")
    args = parser.parse_args()
    cells = scenarios()
    if args.cells:
        wanted = set(args.cells.split(","))
        cells = tuple(sc for sc in cells if sc.name in wanted)
        if {sc.name for sc in cells} != wanted:
            raise SystemExit(f"unknown cells: {wanted - {sc.name for sc in cells}}")
    start = time.time()
    draws: dict[tuple[str, str], list[tuple[float, float]]] = {}
    jobs = [(sc, 10_000 * k + i) for k, sc in enumerate(cells) for i in range(args.sims)]
    with make_worker_pool(args.workers, blas_threads_per_worker=1) as pool:
        for name, out in pool.map(_run, jobs, chunksize=4):
            for arm, tp in out.items():
                draws.setdefault((name, arm), []).append(tp)
    report, failures = [], []
    for (name, arm), tps in sorted(draws.items()):
        ts = [t for t, _ in tps]
        n = len(tps)
        levels = {}
        for a in ALPHAS:
            rejected = sum(p < a for _, p in tps)
            bound = int(binom.ppf(_BOUND_QUANTILE, n, a))
            levels[str(a)] = {"rate": rejected / n, "rejected": rejected, "bound": bound}
            if rejected > bound and name not in DIAGNOSTIC_CELLS:
                failures.append(f"{name}/{arm} at {a}: {rejected} > {bound}")
        report.append(
            {
                "cell": name,
                "arm": arm,
                "sims": n,
                "mean_t": statistics.mean(ts),
                "sd_t": statistics.stdev(ts),
                "levels": levels,
            }
        )
        print(
            f"{name:28s} {arm:10s} mean_t {statistics.mean(ts):6.2f} sd_t "
            f"{statistics.stdev(ts):5.2f} "
            + " ".join(
                f"{a}:{levels[str(a)]['rejected']}/{levels[str(a)]['bound']}" for a in ALPHAS
            ),
            flush=True,
        )
    record = {
        "schema": "e17_null_battery_v1",
        "sims_per_cell": args.sims,
        "bound_quantile": _BOUND_QUANTILE,
        "scenarios": [sc.__dict__ for sc in cells],
        "report": report,
        "failures": failures,
        "seconds": time.time() - start,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(record, indent=2))
    print("SIZE HOLDS" if not failures else "SIZE FAILS:\n  " + "\n  ".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
