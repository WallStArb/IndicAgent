"""Does a per-book sign-flip surrogate calibration restore the shift null's size for slow
signals? Surrogate: returns multiplied by one random +-1 per session (whole cross-section),
same shift null; calibrated bar = alpha-quantile of surrogate p-values."""

import sys

import numpy as np
from scipy.signal import lfilter

n, m, min_shift, memory = 4700, 20, 63, 252
ks = np.arange(min_shift, n - min_shift - memory + 1)
phi, sims, R, seed = float(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
rng = np.random.default_rng(seed)


def pvals(Sf, r_batch):  # r_batch [B, n, m]
    c = np.fft.irfft(np.fft.rfft(r_batch, axis=1) * np.conj(Sf)[None], n=n, axis=1).sum(2)
    obs, null = c[:, 0], c[:, ks]
    return (1 + (null >= obs[:, None]).sum(1)) / (1 + len(ks))


raw, cal = [], {0.05: [], 0.01: []}
for i in range(sims):
    s = lfilter([1.0], [1.0, -phi], rng.standard_normal((n + 500, m)), axis=0)[500:]
    s -= s.mean(1, keepdims=True)
    r = rng.standard_normal((n, m))
    Sf = np.fft.rfft(s, axis=0)
    p_obs = pvals(Sf, r[None])[0]
    eps = rng.choice([-1.0, 1.0], size=(R, n, 1))
    p_sur = np.concatenate([pvals(Sf, r[None] * eps[j : j + 50]) for j in range(0, R, 50)])
    raw.append(p_obs)
    for a in cal:
        cal[a].append(p_obs <= np.quantile(p_sur, a))
raw = np.array(raw)
print(
    f"phi={phi} sims={sims} R={R} | raw P(p<=.05)={np.mean(raw<=.05):.4f} P(p<=.01)={np.mean(raw<=.01):.4f}"
    f" | calibrated size@.05={np.mean(cal[0.05]):.4f} @.01={np.mean(cal[0.01]):.4f}",
    flush=True,
)
