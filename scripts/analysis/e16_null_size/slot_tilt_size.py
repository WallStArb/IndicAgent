"""Size of the E16 timing test on intraday books with slot-level fixed effects (H0).

Returns carry per-(slot, name) fixed effects, one common factor, Student t4 noise and
volatility clustering, and no predictability. The predictor is a persistent AR(1) per
(slot, name) (autocorrelation time tau) plus a static slot-varying part aligned with the fixed
effects: the case where a per-symbol tilt leaves slot-varying static exposure in the tested
series. Books are rank-weighted and dollar-neutral per row. Reports rejection rates of the
one-sided HAC t at 0.05, 0.01 and 0.00167 for three tested series: "pinned" (E16 as proposed,
(w - wbar) * r per (slot, symbol)), "symbol" (the pinned form with a per-symbol tilt), and
"adopted" (src/intelligence/research/timing.py: (w - wbar) * (r - rbar) per (slot, symbol)).

    .venv/bin/python scripts/analysis/e16_null_size/slot_tilt_size.py <tau> <sims> <seed> [fe_sd]

fe_sd is the fixed effects' standard deviation in units of the per-bar noise sd.
"""

import sys

import numpy as np
from scipy.signal import lfilter

sys.path.insert(0, ".")
from src.intelligence.research.timing import timing_series  # noqa: E402
from src.intelligence.statistics.hac import hac_mean_test  # noqa: E402

tau, sims, seed = float(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
fe_sd = float(sys.argv[4]) if len(sys.argv) > 4 else 0.3
rng = np.random.default_rng(seed)
S, bps, m, warm = 1500, 4, 40, 252
n = S * bps
phi = np.exp(-1.0 / tau)
alphas = (0.05, 0.01, 0.00167)
rej = {k: dict.fromkeys(alphas, 0) for k in ("pinned", "symbol", "adopted")}


def pinned_series(w, r):
    """E16 as proposed: (w - wbar) * r with wbar per (slot, symbol), no return demeaning."""
    ws, rs = w.reshape(S, bps, m), r.reshape(S, bps, m)
    prior = np.concatenate([np.zeros((1, bps, m)), np.cumsum(ws, 0)[:-1]])
    tilt = prior / np.maximum(np.arange(S), 1)[:, None, None]
    d = ((ws - tilt) * rs).sum(axis=(1, 2))
    d[:warm] = np.nan
    return d


def per_symbol_series(w, r):
    """Tilt per symbol only (pooled over slots), same tested-session rule."""
    wd = w.reshape(S, bps, m).sum(axis=1)  # session exposure per symbol
    rd = r.reshape(S, bps, m)
    prior = np.concatenate([np.zeros((1, m)), np.cumsum(wd, 0)[:-1]])
    count = np.arange(S)[:, None]
    tilt = np.where(count > 0, prior / np.maximum(count, 1), 0.0) / bps
    d = ((w.reshape(S, bps, m) - tilt[:, None, :]) * rd).sum(axis=(1, 2))
    d[:warm] = np.nan
    return d


for _ in range(sims):
    fe = fe_sd * rng.standard_normal((bps, m))  # slot-level fixed effects in returns
    vol = np.exp(lfilter([1.0], [1.0, -0.97], 0.15 * rng.standard_normal(n + 500))[500:])
    noise = rng.standard_t(4, (n, m)) / np.sqrt(2.0) * vol[:, None]
    factor = rng.standard_normal(n)[:, None] * rng.uniform(0.5, 1.5, m)
    r = np.tile(fe, (S, 1)) + factor + noise  # no predictability
    ar = lfilter([1.0], [1.0, -phi], rng.standard_normal((S + 600, bps, m)), axis=0)[600:]
    pred = (ar * np.sqrt(1 - phi**2)).reshape(n, m) + np.tile(fe, (S, 1))  # static part = fe
    ranks = pred.argsort(axis=1).argsort(axis=1) / (m - 1) - 0.5
    w = ranks / np.abs(ranks).sum(axis=1, keepdims=True)
    ones = np.ones(n, dtype=bool)
    for kind, d in (
        ("pinned", pinned_series(w, r)),
        ("symbol", per_symbol_series(w, r)),
        # Since E17 this arm is the E17 statistic (weights here never read returns, so any
        # memory is exact; 1 session). E16's own results stay recorded in the ledger entry.
        (
            "adopted",
            timing_series(
                w, r, ones, ones, bars_per_session=bps, warmup_sessions=warm, memory_sessions=1
            ),
        ),
    ):
        p = hac_mean_test(d).p
        for a in alphas:
            rej[kind][a] += p < a

for kind in rej:
    print(
        f"tau {tau:g} fe_sd {fe_sd:g} sims {sims} {kind}: "
        + " ".join(f"p<{a}: {rej[kind][a] / sims:.4f}" for a in alphas),
        flush=True,
    )
