"""Screen-level tail size of a HAC t-test on (book P&L minus static-tilt P&L), under H0
(predictors independent of returns), with fat tails (Student t4 returns), volatility
clustering, and per-symbol fixed effects in both predictor and returns (the case the shift
null exists for). Static tilt = each symbol's expanding (causal) mean predictor weight."""

import sys

import numpy as np
from scipy.signal import lfilter
from scipy.stats import t as tdist


def nw_t(p):
    n = len(p)
    x = p - p.mean()
    L = int(np.floor(4 * (n / 100) ** (2 / 9)))
    v = x @ x / n
    for k in range(1, L + 1):
        v += 2 * (1 - k / (L + 1)) * (x[k:] @ x[:-k]) / n
    return p.mean() / np.sqrt(v / n)


phi, sims, seed = float(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
rng = np.random.default_rng(seed)
n, m, burn = 4000, 50, 252
crit = {a: tdist.ppf(1 - a, n - burn - 1) for a in (0.05, 0.01, 0.00167)}
rej_raw = {a: 0 for a in crit}
rej_dyn = {a: 0 for a in crit}
for _ in range(sims):
    s = lfilter([1.0], [1.0, -phi], rng.standard_normal((n + 1500, m)), axis=0)[1500:]
    s += 2.0 * rng.standard_normal(m)  # persistent predictor tilt
    r = rng.standard_t(4, size=(n, m)) / np.sqrt(2.0)
    sig = np.exp(lfilter([1.0], [1.0, -0.98], rng.standard_normal(n + 500))[500:] * 0.3)
    r = (r + rng.standard_normal((n, 1))) * sig[:, None] + 0.03 * rng.standard_normal(m)  # drift
    w = s - s.mean(1, keepdims=True)
    w /= np.abs(w).sum(1, keepdims=True)
    static = np.cumsum(w, 0) / np.arange(1, n + 1)[:, None]
    static = np.vstack([np.zeros((1, m)), static[:-1]])  # causal: mean through t-1
    p_book = (w * r).sum(1)[burn:]
    p_dyn = ((w - static) * r).sum(1)[burn:]
    tb, td = nw_t(p_book), nw_t(p_dyn)
    for a, c in crit.items():
        rej_raw[a] += tb > c
        rej_dyn[a] += td > c
print(
    f"phi={phi} sims={sims} | book-only "
    + " ".join(f"@{a}={rej_raw[a]/sims:.5f}" for a in crit)
    + " | book-minus-static "
    + " ".join(f"@{a}={rej_dyn[a]/sims:.5f}" for a in crit),
    flush=True,
)
