"""Exploratory (todo 547): size of E17's HAC t under extra Bartlett lags, paired on one set of daily-battery simulations. Run with OMP_NUM_THREADS=1. Usage: e17_lag_scan.py cells sims sessions workers seedbase horizon out.json"""

import dataclasses
import json
import sys
from multiprocessing import Pool

import numpy as np

from src.intelligence.research import null_battery_daily_residual as nb
from src.intelligence.statistics import hac

EXTRAS = [0, 4, 8, 12, 20]
CELLS = sys.argv[1].split(",")
SIMS, SESS, WORKERS, SEEDBASE = (
    int(sys.argv[2]),
    int(sys.argv[3]),
    int(sys.argv[4]),
    int(sys.argv[5]),
)
HORIZON = int(sys.argv[6]) if len(sys.argv) > 6 else 5


def job(args):
    name, seed = args
    sc = [c for c in nb.scenarios() if c.name == name][0]
    sc = dataclasses.replace(sc, sessions=SESS, horizon=HORIZON)
    out = {}
    base = hac.newey_west_lag
    for arm, series in nb.simulate_series(sc, seed).items():
        for extra in EXTRAS:
            hac.newey_west_lag = lambda n, e=extra: base(n) + e
            try:
                r = hac.hac_mean_test(series)
                out[(arm, extra)] = (r.t, r.p)
            finally:
                hac.newey_west_lag = base
    return name, out


if __name__ == "__main__":
    jobs = [(c, SEEDBASE + 10_000 * k + i) for k, c in enumerate(CELLS) for i in range(SIMS)]
    rows = {}
    with Pool(WORKERS) as pool:
        for name, out in pool.imap_unordered(job, jobs, chunksize=2):
            for key, tp in out.items():
                rows.setdefault((name,) + key, []).append(tp)
    res = {}
    for (name, arm, extra), tps in sorted(rows.items()):
        p = np.array([x[1] for x in tps])
        tt = np.array([x[0] for x in tps])
        res.setdefault(name, {}).setdefault(extra, []).append(
            {
                "arm": arm,
                "rej05": float((p < 0.05).mean()),
                "rej01": float((p < 0.01).mean()),
                "sd_t": float(tt.std(ddof=1)),
                "mean_t": float(tt.mean()),
            }
        )
    print("cell extra | mean over arms: rej@.05 rej@.01 sd_t | max over arms rej@.05")
    for name, d in res.items():
        for extra, arms in d.items():
            r05 = np.mean([a["rej05"] for a in arms])
            r01 = np.mean([a["rej01"] for a in arms])
            print(
                f"{name:22s} +{extra:<3d} | {r05:.4f} {r01:.4f} {np.mean([a['sd_t'] for a in arms]):.3f} | {max(a['rej05'] for a in arms):.3f}"
            )
    json.dump(
        {n: {str(k): v for k, v in d.items()} for n, d in res.items()},
        open(sys.argv[7] if len(sys.argv) > 7 else "/dev/null", "w"),
    )
