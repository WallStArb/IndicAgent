"""Fresh-seed size check of single arms of an E17 battery (ledger E17 amendment 2026-11-18, todo 636).

The battery gate (battery_pass.problems) has weak power at 2,000 simulations (a true 6.45 percent size at
alpha 0.05 is caught about 17 percent of the time), so an arm that exceeds its bound once is settled by
this check: many fresh simulations of one cell through the battery's own `simulate`, the rejection rate
at each alpha with a one-sided 95 percent normal upper bound, and a pass rule fixed BEFORE it is run.

Pass rule (declared in the commit that adds this file, before any run): for each arm named in --arms, the
one-sided 95 percent upper bound of the rejection rate at alpha 0.05 is below 0.055. Exit status 1 when
any named arm fails or fewer than 10,000 simulations are asked for.

    .venv/bin/python scripts/research/e17_arm_calibration.py <out.json> --cell daily_static_means \\
        --arms reversal_5,reversal_5_skip1 --sims 12000 --seed-base 77000000 \\
        --battery src.intelligence.research.null_battery_daily_residual
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from services.batch_support.pool import make_worker_pool  # noqa: E402
from src.intelligence.research.null_battery import ALPHAS  # noqa: E402

PASS_UPPER_BOUND_AT_005 = 0.055
MIN_SIMS = 10_000  # fewer cannot separate 5.0 from 5.5 percent, so a short run never passes
Z_95_ONE_SIDED = 1.6448536269514722


def _run(args: tuple) -> dict:
    module, cell, seed = args
    battery = importlib.import_module(module)
    scenario = next(s for s in battery.scenarios() if s.name == cell)
    return battery.simulate(scenario, seed)


def _upper(rejected: int, n: int) -> float:
    rate = rejected / n
    return rate + Z_95_ONE_SIDED * math.sqrt(rate * (1 - rate) / n)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--cell", required=True)
    parser.add_argument(
        "--arms", required=True, help="comma-separated arms the pass rule applies to"
    )
    parser.add_argument("--sims", type=int, default=12000)
    parser.add_argument("--seed-base", type=int, required=True)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--battery", required=True)
    args = parser.parse_args()
    if args.sims < MIN_SIMS:
        raise SystemExit(f"--sims {args.sims} is below {MIN_SIMS}")
    named = args.arms.split(",")
    jobs = [(args.battery, args.cell, args.seed_base + i) for i in range(args.sims)]
    draws: dict[str, list[tuple[float, float]]] = {}
    with make_worker_pool(args.workers, blas_threads_per_worker=1) as pool:
        for out in pool.map(_run, jobs, chunksize=8):
            for arm, tp in out.items():
                draws.setdefault(arm, []).append(tp)
    rows, failed = [], []
    for arm, tps in sorted(draws.items()):
        n = len(tps)
        levels = {}
        for alpha in ALPHAS:
            rejected = sum(p < alpha for _, p in tps)
            levels[str(alpha)] = {
                "rejected": rejected,
                "rate": rejected / n,
                "upper95": _upper(rejected, n),
            }
        ts = [t for t, _ in tps]
        mean = sum(ts) / n
        sd = math.sqrt(sum((t - mean) ** 2 for t in ts) / (n - 1))
        rows.append({"arm": arm, "sims": n, "mean_t": mean, "sd_t": sd, "levels": levels})
        if arm in named and levels["0.05"]["upper95"] >= PASS_UPPER_BOUND_AT_005:
            failed.append(arm)
        print(arm, n, {a: (lv["rejected"], round(lv["rate"], 4)) for a, lv in levels.items()})
    missing = [a for a in named if a not in draws]
    record = {
        "schema": "e17_arm_calibration_v1",
        "battery": args.battery,
        "cell": args.cell,
        "named_arms": named,
        "sims": args.sims,
        "seed_base": args.seed_base,
        "pass_rule": f"upper95 of the rate at 0.05 below {PASS_UPPER_BOUND_AT_005} for each named arm",
        "commit": subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip(),
        "rows": rows,
        "failed_arms": failed,
        "missing_arms": missing,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(record, indent=2))
    print("FAILED:" if failed or missing else "PASSED:", failed or missing or named)
    return 1 if failed or missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
