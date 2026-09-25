"""Size of a mean-P&L test for a frozen book on a short forward span, under H0 (predictors
independent of returns), versus predictor persistence. P&L_t = <w_t, r_{t+1}>, w_t the
cross-sectionally demeaned, unit-gross predictor. One-sided HAC (Newey-West) t-test."""

import sys

import numpy as np
from scipy.signal import lfilter
from scipy.stats import norm


def nw_t(p):
    n = len(p)
    x = p - p.mean()
    L = int(np.floor(4 * (n / 100) ** (2 / 9)))
    v = x @ x / n
    for k in range(1, L + 1):
        v += 2 * (1 - k / (L + 1)) * (x[k:] @ x[:-k]) / n
    return p.mean() / np.sqrt(v / n)


rng = np.random.default_rng(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
m, sims = 50, 20000
for n in (190, 500, 1000):
    for phi in (0.0, 0.975, 0.997):
        for vol in (False, True):
            rej = 0
            for _ in range(sims):
                s = lfilter([1.0], [1.0, -phi], rng.standard_normal((n + 1500, m)), axis=0)[1500:]
                w = s - s.mean(1, keepdims=True)
                w /= np.abs(w).sum(1, keepdims=True)
                r = rng.standard_normal((n, m))
                if vol:  # volatility clustering plus a common factor
                    sig = np.exp(
                        lfilter([1.0], [1.0, -0.98], rng.standard_normal(n + 500))[500:] * 0.3
                    )
                    r = (r + rng.standard_normal((n, 1))) * sig[:, None]
                p = (w * r).sum(1)
                rej += nw_t(p) > norm.ppf(0.95)
            tau = (1 + phi) / (1 - phi) if phi else 1
            print(f"n={n:5d} tau~{tau:5.0f} vol={vol!s:5} size@0.05={rej/sims:.4f}", flush=True)
