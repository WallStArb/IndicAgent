"""Independent check of todo 432 (E17 adoption, 2026-09-26). Run from the repo root.
Full-history cases plus late listings (40% of names list after t = 0).
: own-history member under H0 (no timing skill).
r[t,j] = mu[t,j] + eps, eps t4. w = dollar-neutral centred rank of trailing-L mean of r.
A: E16 as built  sum (w - wbar)(r - fbar), expanding means
B: 432 fix       sum w (r - fbar_L), fbar_L = mean r over sessions < t - L, floor 60
Cases: mu = 0; static mu (sd 0.3); drifting mu (OU, half-life H sessions, stationary sd 0.3)."""

import sys

import numpy as np

sys.path.insert(0, ".")
from src.intelligence.statistics.hac import hac_mean_test


def rank_w(a):
    out = np.zeros_like(a)
    ok = np.isfinite(a)
    for t in range(len(a)):
        k = ok[t]
        if k.sum() < 20:
            continue
        r = a[t, k].argsort().argsort().astype(float)
        c = r / (k.sum() - 1) - 0.5
        pos, neg = c.clip(0), (-c).clip(0)
        out[t, k] = 0.5 * pos / pos.sum() - 0.5 * neg / neg.sum()
    return out


def sim(case, L=40, n=3000, m=100, seed=0, half_life=500, warm=252, floor=60):
    rng = np.random.default_rng(seed)
    eps = rng.standard_t(4, (n, m)) / np.sqrt(2)
    if case == "zero":
        mu = np.zeros((n, m))
    elif case == "static":
        mu = np.broadcast_to(rng.normal(0, 0.3, m), (n, m))
    else:
        phi = 0.5 ** (1 / half_life)
        mu = np.empty((n, m))
        mu[0] = rng.normal(0, 0.3, m)
        z = rng.normal(0, 0.3 * np.sqrt(1 - phi**2), (n, m))
        for t in range(1, n):
            mu[t] = phi * mu[t - 1] + z[t]
    r = mu + eps
    cs = np.vstack([np.zeros((1, m)), np.cumsum(r, 0)])
    trail = np.full((n, m), np.nan)
    trail[L:] = (cs[L:n] - cs[: n - L]) / L  # mean of r[t-L .. t-1]
    w = rank_w(trail)
    idx = np.arange(n)
    # A
    wcs = np.vstack([np.zeros((1, m)), np.cumsum(w, 0)])
    wbar = wcs[:n] / np.maximum(idx, 1)[:, None]
    fbar = cs[:n] / np.maximum(idx, 1)[:, None]
    A = ((w - wbar) * (r - fbar)).sum(1)[warm:]
    # B: fbar_L over sessions < t - L  (count t - L)
    cnt = idx - L
    fL = np.where(cnt[:, None] > 0, cs[np.clip(cnt, 0, None)] / np.maximum(cnt, 1)[:, None], np.nan)
    ok = cnt >= floor
    B = np.where(ok, (w * (r - np.nan_to_num(fL))).sum(1), np.nan)[warm:]
    return hac_mean_test(A).t, hac_mean_test(B[np.isfinite(B)]).t


def main_full_history():
    for case, hl in [("zero", 0), ("static", 0), ("drift", 2000), ("drift", 500), ("drift", 100)]:
        ts = np.array([sim(case, seed=s, half_life=hl or 500) for s in range(40)])
        lab = case if case != "drift" else f"drift hl={hl}"
        print(
            f"{lab:16s} A(E16 built) mean t {ts[:,0].mean():+.2f} sd {ts[:,0].std():.2f} | "
            f"B(432 fix) mean t {ts[:,1].mean():+.2f} sd {ts[:,1].std():.2f}"
        )


def sim_late(case, L=40, n=3000, m=100, seed=0, warm=252, floor=60):
    rng = np.random.default_rng(seed)
    start = np.where(rng.random(m) < 0.4, rng.integers(0, n - 300, m), 0)
    live = np.arange(n)[:, None] >= start[None, :]
    mu = 0.0 if case == "zero" else rng.normal(0, 0.3, m)[None, :]
    r = np.where(live, mu + rng.standard_t(4, (n, m)) / np.sqrt(2), np.nan)
    f = np.isfinite(r)
    r0 = np.where(f, r, 0.0)
    cs = np.vstack([np.zeros((1, m)), np.cumsum(r0, 0)])
    cc = np.vstack([np.zeros((1, m)), np.cumsum(f, 0)])
    trail = np.full((n, m), np.nan)
    k = cc[L:n] - cc[: n - L]
    trail[L:] = np.where(k == L, (cs[L:n] - cs[: n - L]) / L, np.nan)
    w = rank_w(trail)
    wcs = np.vstack([np.zeros((1, m)), np.cumsum(w, 0)])
    idx = np.arange(n)
    wbar = wcs[:n] / np.maximum(idx, 1)[:, None]
    with np.errstate(invalid="ignore", divide="ignore"):
        fbar = np.where(cc[:n] > 0, cs[:n] / cc[:n], 0.0)
        A = ((w - wbar) * np.where(f, r0 - fbar, 0.0)).sum(1)[warm:]
        lag = np.clip(idx - L, 0, None)
        nL = cc[lag]
        fL = np.where(nL > 0, cs[lag] / nL, np.nan)
        ok = (nL >= floor) & f
        B = np.where(ok, w * (r0 - np.nan_to_num(fL)), 0.0).sum(1)[warm:]
    return hac_mean_test(A).t, hac_mean_test(B).t


def main_late_listings():
    for case in ("zero", "static"):
        ts = np.array([sim_late(case, seed=s) for s in range(40)])
        print(
            f"late listings, {case:6s}: A mean t {ts[:,0].mean():+.2f} sd {ts[:,0].std():.2f} | "
            f"B mean t {ts[:,1].mean():+.2f} sd {ts[:,1].std():.2f}"
        )


if __name__ == "__main__":
    main_full_history()
    main_late_listings()
