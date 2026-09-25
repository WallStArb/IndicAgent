"""Size of the whole-panel circular-shift null with slow signals, under H0 (signal independent
of returns). Same p-value and shift rules as src/intelligence/statistics/panel_null.py."""

import sys

import numpy as np
from scipy.signal import lfilter

n, m, min_shift, memory = 4700, 50, 63, 252
ks = np.arange(min_shift, n - min_shift - memory + 1)


def ar1(rng, phi, shape):
    e = rng.standard_normal(shape)
    x = lfilter([1.0], [1.0, -phi], e, axis=0)
    return x[500:] if shape[0] > n else x


def pvalue(s, r):
    c = np.fft.irfft(np.fft.rfft(r, axis=0) * np.conj(np.fft.rfft(s, axis=0)), n=n, axis=0).sum(1)
    obs, null = c[0], c[ks]
    return (1 + (null >= obs).sum()) / (1 + len(ks))


def run(name, phi, sims, fixed=False, vol=False, seed=0):
    rng = np.random.default_rng(seed)
    ps = np.empty(sims)
    for i in range(sims):
        s = ar1(rng, phi, (n + 500, m))
        r = rng.standard_normal((n, m))
        if fixed:  # persistent per-symbol components in both (e.g. yield in signal and drift)
            s += 3 * rng.standard_normal(m)
            r += 0.05 * rng.standard_normal(m)
        if vol:  # common volatility clustering and a common factor
            sig = np.exp(ar1(rng, 0.98, (n + 500, 1)) * 0.3)
            r = (r + rng.standard_normal((n, 1))) * sig
        s = s - s.mean(1, keepdims=True)  # cross-sectional demean (S4-like)
        ps[i] = pvalue(s, r)
    tau = (1 + phi) / (1 - phi)
    print(
        f"{name}: phi={phi} tau~{tau:.0f} sims={sims} | "
        + " ".join(f"P(p<={a})={np.mean(ps <= a):.4f}" for a in (0.05, 0.01, 0.00167)),
        flush=True,
    )


sims = int(sys.argv[1])
which = int(sys.argv[2])
SC = [
    ("tau79", 0.975, {}),
    ("tau132", 0.985, {}),
    ("tau3", 0.5, {}),
    ("tau7", 0.75, {}),
    ("tau19", 0.9, {}),
    ("tau39", 0.95, {}),
    ("iid signal", 0.0, {}),
    ("slow AR1", 0.99, {}),
    ("very slow AR1", 0.997, {}),
    ("slow + fixed effects", 0.99, {"fixed": True}),
    ("slow + vol clustering", 0.99, {"vol": True}),
]
name, phi, kw = SC[which]
run(name, phi, sims, seed=100 + which, **kw)
