"""E17 H0 size diagnostic for todo 549 (exploratory, not a counted look: synthetic H0 panels).

Per null-battery cell and arm: the pooled ACF of D_s (lags 1..80), rejection at 1.645 under the
Newey-West lag x1/x2/x4/x8, rejection at the Kiefer-Vogelsang (2005) fixed-b Bartlett 95%
value at b = lag / n, and the design effect of pooling an H0 simulation's arms (they share one
panel), which a pooled Clopper-Pearson interval ignores. Seeds start at 9,000,000, far from the
battery's positional seeds.

    .venv/bin/python scripts/research/e17_size_diagnostic.py CELLS SIMS SESSIONS WORKERS OUT.json
    .venv/bin/python scripts/research/e17_size_diagnostic.py --report OUT.json
"""

import dataclasses
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from services._batch_utils import make_worker_pool  # noqa: E402
from src.intelligence.research import null_battery as nb  # noqa: E402
from src.intelligence.statistics.hac import newey_west_lag  # noqa: E402

MAXLAG = 80
SEED0 = 9_000_000
Z95 = 1.6449


def t_bartlett(x: np.ndarray, lag: int) -> float:
    d = x - x.mean()
    n = len(x)
    v = d @ d / n
    for k in range(1, lag + 1):
        v += 2 * (1 - k / (lag + 1)) * (d[k:] @ d[:-k]) / n
    return float(x.mean() / np.sqrt(v / n))


def fixed_b_cv95(b: float) -> float:
    """Kiefer and Vogelsang (2005), Bartlett kernel, 95% one-sided (cubic fit in b)."""
    return 1.6449 + 2.1859 * b + 0.3142 * b**2 - 0.3427 * b**3


def one(args: tuple[str, int, int]) -> tuple[str, int, dict]:
    cell, seed, sessions = args
    sc = dataclasses.replace(next(s for s in nb.scenarios() if s.name == cell), sessions=sessions)
    out = {}
    for arm, s in nb.simulate_series(sc, seed).items():
        x = s[np.isfinite(s)]
        n = len(x)
        d = x - x.mean()
        g0 = d @ d / n
        lag = newey_west_lag(n)
        out[arm] = {
            "acf": [float((d[k:] @ d[:-k]) / n / g0) for k in range(1, MAXLAG + 1)],
            **{f"lag{m}": t_bartlett(x, m * lag) for m in (1, 2, 4, 8)},
            "L": lag,
            "n": n,
        }
    return cell, seed, out


def report(path: str) -> None:
    res = json.load(open(path))
    by, sims = defaultdict(list), defaultdict(list)
    for cell, _seed, out in res:
        for arm, r in out.items():
            by[(cell, arm)].append(r)
        sims[cell].append([out[a]["lag1"] > Z95 for a in sorted(out)])
    for (cell, arm), rs in sorted(by.items()):
        t1 = np.array([r["lag1"] for r in rs])
        rates = [np.mean([r[f"lag{m}"] > Z95 for r in rs]) * 100 for m in (1, 2, 4, 8)]
        fb = np.mean(t1 > fixed_b_cv95(rs[0]["L"] / rs[0]["n"])) * 100
        acf = np.mean([r["acf"] for r in rs], axis=0)
        print(
            f"{cell}/{arm:28s} N {len(rs)} sd_t {t1.std():.3f} rej x1/x2/x4/x8 "
            + " ".join(f"{r:.2f}" for r in rates)
            + f" fixed-b {fb:.2f} acf1-5 "
            + " ".join(f"{a:+.3f}" for a in acf[:5])
            + f" sum10-80 {acf[9:].sum():+.3f}"
        )
    for cell, rows in sims.items():
        x = np.array(rows, float)
        p = x.mean()
        deff = (x.mean(axis=1).var(ddof=1) / len(x)) / (p * (1 - p) / x.size)
        print(f"{cell}: pooled {p * 100:.2f}% design effect {deff:.2f}")


if __name__ == "__main__":
    if sys.argv[1] == "--report":
        report(sys.argv[2])
        sys.exit(0)
    cells, n_sims, sessions, workers, out = (
        sys.argv[1].split(","),
        *map(int, sys.argv[2:5]),
        sys.argv[5],
    )
    jobs = [(c, SEED0 + i, sessions) for c in cells for i in range(n_sims)]
    with make_worker_pool(workers, blas_threads_per_worker=1) as ex:
        results = list(ex.map(one, jobs))
    json.dump(results, open(out, "w"))
    print("done", len(results))
