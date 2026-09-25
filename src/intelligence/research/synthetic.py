"""Synthetic panels for the book test's power check (D-11, D-19, D-20; research pattern 8).

Planting happens in residual space and power replicates skip S1: S1 costs minutes per
residualization of the full panel, and what S1 removes (market, groups, statistical factors)
is not what the power question asks. synthetic_price_panel adds factor structure back for the
check that S1 passes such a plant nearly unchanged.

- Breadth (D-20). Each slot's residual cross-section has covariance I + s Q Q' with Q a seeded
  random orthonormal m x k basis and s set by loading_scale_for_pr, so its participation ratio
  equals the pinned breadth (60, from step 0). Independent residuals would overstate power
  about twofold.
- Plant (HKS shape). u[d, j, i] = e[d, j, i] + c * mean_{l=1..L} u[d - l, j, i]: flat
  persistence of a name's own slot-j residual over the last L sessions, cross-sectionally
  demeaned per slot. It lives at the slot level, so members built from bars see exactly what
  was planted. Each slot splits into its two bars with an independent split whose bars sum to
  the slot return.
- Effect size (D-19). The planted strength c is calibrated so the per-slot cross-sectional rank
  IC of the best linear combination of the members against the target equals the
  pre-declared IC (0.002 for family 1).
- Scale. Idiosyncratic slot variance is 1: ranks, R1 weights and Sharpe ratios are scale free.
- The finite mask carries no return information; passing the real panel's mask
  (np.isfinite(panel.close)) makes coverage realistic.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable, Sequence

import numpy as np

from src.intelligence.research.families.intraday_periodicity import SLOT_BARS
from src.intelligence.research.panel import Panel
from src.intelligence.research.portfolio import average_ranks

_BAR_SPLIT_SD = 0.5  # sd of the within-slot split, in units of the slot's idiosyncratic sd


@dataclasses.dataclass(frozen=True)
class SyntheticSpec:
    bars_per_session: int
    participation_ratio: float
    n_common_factors: int
    plant_lags_sessions: int


def loading_scale_for_pr(n_names: int, n_factors: int, participation_ratio: float) -> float:
    """s with PR(I + s Q Q') = target. Eigenvalues: 1 + s (k times) and 1 (m - k times), so
    PR = (m + k s)^2 / (m - k + k (1 + s)^2), a quadratic in x = 1 + s."""
    m, k, p = n_names, n_factors, participation_ratio
    if k == 0:
        if not math.isclose(p, m):
            raise ValueError(f"with no factors the participation ratio is {m}, not {p}")
        return 0.0
    # (m - k + k x)^2 = p (m - k + k x^2)  ->  k (k - p) x^2 + 2 k (m - k) x + (m - k)(m - k - p) = 0
    a = k * (k - p)
    b = 2 * k * (m - k)
    c = (m - k) * (m - k - p)
    disc = b * b - 4 * a * c
    if not (k <= p <= m) or disc < 0:
        raise ValueError(f"participation ratio {p} not attainable with m={m}, k={k}")
    roots = [(-b + sign * math.sqrt(disc)) / (2 * a) for sign in (1, -1)] if a else [-c / b]
    xs = [x for x in roots if x >= 1]
    if not xs:
        raise ValueError(f"participation ratio {p} not attainable with m={m}, k={k}")
    return min(xs) - 1.0


def _slot_residuals(
    spec: SyntheticSpec, n_sessions: int, n_names: int, plant_coef: float, rng
) -> np.ndarray:
    """u [S, J, m]: demeaned slot residuals with the planted same-slot persistence."""
    j_n, m, k, lags = (
        spec.bars_per_session // SLOT_BARS,
        n_names,
        spec.n_common_factors,
        spec.plant_lags_sessions,
    )
    scale = loading_scale_for_pr(m, k, spec.participation_ratio)
    q = np.linalg.qr(rng.standard_normal((m, k)))[0] if k else np.zeros((m, 0))
    u = np.empty((n_sessions, j_n, m))
    window = np.zeros((lags, j_n, m))  # ring buffer of the last `lags` sessions
    running = np.zeros((j_n, m))
    for d in range(n_sessions):
        e = rng.standard_normal((j_n, m)) + math.sqrt(scale) * rng.standard_normal((j_n, k)) @ q.T
        e -= e.mean(axis=1, keepdims=True)
        u[d] = e + plant_coef * running / lags
        slot = d % lags
        running += u[d] - window[slot]
        window[slot] = u[d]
    return u


def generate_residual_panel(
    spec: SyntheticSpec, finite_mask: np.ndarray, *, plant_coef: float, seed: int
) -> tuple[np.ndarray, np.ndarray]:
    """(resid_bar [n, m], target [n, m]): bar residuals whose slot pairs sum to u, and the
    target u[d, j] at slot j's placement row (the bar before the slot), NaN elsewhere and
    wherever a bar of the slot is masked."""
    bps = spec.bars_per_session
    n, m = finite_mask.shape
    n_sessions, j_n = n // bps, bps // SLOT_BARS
    rng = np.random.default_rng(seed)
    u = _slot_residuals(spec, n_sessions, m, plant_coef, rng)
    first = u / SLOT_BARS + _BAR_SPLIT_SD * rng.standard_normal(u.shape)
    bars = np.stack([first, u - first], axis=2)  # [S, J, 2, m]
    resid_bar = bars.reshape(n, m)
    resid_bar[~finite_mask] = np.nan

    slot_ok = finite_mask.reshape(n_sessions, j_n, SLOT_BARS, m).all(axis=2)
    rows = (np.arange(n_sessions)[:, None] * bps + SLOT_BARS * np.arange(j_n)[None, :] - 1).ravel()
    values = np.where(slot_ok, u, np.nan).reshape(-1, m)
    keep = rows >= 0
    target = np.full((n, m), np.nan)
    target[rows[keep]] = values[keep]
    return resid_bar, target


def _row_spearman(a: np.ndarray, b: np.ndarray, floor: int) -> np.ndarray:
    """Per-row Spearman correlation over names where both are finite; NaN below floor."""
    both = np.isfinite(a) & np.isfinite(b)
    rows = np.flatnonzero(both.sum(axis=1) >= floor)
    out = np.full(a.shape[0], np.nan)
    if rows.size == 0:
        return out
    ra = average_ranks(np.where(both[rows], a[rows], np.nan))
    rb = average_ranks(np.where(both[rows], b[rows], np.nan))
    ra -= np.nanmean(ra, axis=1, keepdims=True)
    rb -= np.nanmean(rb, axis=1, keepdims=True)
    num = np.nansum(ra * rb, axis=1)
    den = np.sqrt(np.nansum(ra * ra, axis=1) * np.nansum(rb * rb, axis=1))
    with np.errstate(invalid="ignore", divide="ignore"):
        out[rows] = num / den
    return out


def combo_rank_ic(
    stack: np.ndarray, target: np.ndarray, *, coverage_floor: int, bars_per_session: int
) -> float:
    """D-19's effect measure: the mean per-row cross-sectional Spearman correlation between the
    target and the best linear combination of the standardized members, over rows with at
    least coverage_floor complete names. The combination is cross-fitted (OLS on odd sessions
    scores even sessions and the reverse): an in-sample fit is biased upward by about
    sqrt(K / N), which at the planted size is a material share of the effect."""
    ok = np.isfinite(target) & np.isfinite(stack).all(axis=2)
    session = np.arange(target.shape[0]) // bars_per_session
    ics = []
    for fold in (0, 1):
        fit = ok & (session % 2 == fold)[:, None]
        score = ok & (session % 2 != fold)[:, None]
        x = stack[fit].astype(np.float64)
        mu, sd = x.mean(axis=0), x.std(axis=0)
        sd = np.where(sd > 0, sd, 1.0)
        z = (x - mu) / sd
        b = np.linalg.lstsq(
            np.column_stack([np.ones(len(z)), z]), target[fit].astype(np.float64), rcond=None
        )[0][1:]
        combo = np.full(target.shape, np.nan)
        combo[score] = ((stack[score].astype(np.float64) - mu) / sd) @ b
        ics.append(_row_spearman(combo, np.where(score, target, np.nan), coverage_floor))
    return float(np.nanmean(np.concatenate(ics)))


def _member_stack(resid_bar, members, bps: int, coverage_floor: int) -> np.ndarray:
    return np.stack(
        [
            fn(resid_bar, bars_per_session=bps, coverage_floor=coverage_floor, **params)
            for fn, params in members
        ],
        axis=2,
    ).astype(np.float32)


@dataclasses.dataclass(frozen=True)
class CalibratedPlant:
    plant_coef: float
    achieved_ic: float
    ic_se: float
    iterations: int


def calibrate_plant(
    spec: SyntheticSpec,
    finite_mask: np.ndarray,
    *,
    members: Sequence[tuple[Callable, dict]],
    coverage_floor: int,
    target_ic: float,
    tolerance: float,
    n_panels: int,
    seed: int,
    max_iterations: int = 60,
) -> CalibratedPlant:
    """Bisection on plant_coef with common random numbers (the same n_panels seeds at every
    step) until the mean combo_rank_ic is within tolerance of target_ic."""
    seeds = [seed + i for i in range(n_panels)]

    def ics(coef: float) -> np.ndarray:
        out = []
        for s in seeds:
            resid, target = generate_residual_panel(spec, finite_mask, plant_coef=coef, seed=s)
            stack = _member_stack(resid, members, spec.bars_per_session, coverage_floor)
            out.append(
                combo_rank_ic(
                    stack,
                    target,
                    coverage_floor=coverage_floor,
                    bars_per_session=spec.bars_per_session,
                )
            )
        return np.array(out)

    def summary(values: np.ndarray, coef: float, it: int) -> CalibratedPlant:
        se = float(values.std(ddof=1) / math.sqrt(len(values))) if len(values) > 1 else float("nan")
        return CalibratedPlant(coef, float(values.mean()), se, it)

    lo, hi = 0.0, 0.05
    it = 0
    vals_hi = ics(hi)
    while vals_hi.mean() < target_ic:
        lo, hi = hi, hi * 2
        it += 1
        if hi >= 1.0 or it > max_iterations:
            raise ValueError(f"plant not bracketed: IC {vals_hi.mean():.4g} at coef {hi / 2}")
        vals_hi = ics(hi)
    if abs(vals_hi.mean() - target_ic) <= tolerance:
        return summary(vals_hi, hi, it + 1)
    while it < max_iterations:
        it += 1
        mid = (lo + hi) / 2
        vals = ics(mid)
        if abs(vals.mean() - target_ic) <= tolerance:
            return summary(vals, mid, it)
        if vals.mean() < target_ic:
            lo = mid
        else:
            hi = mid
    raise ValueError(f"plant calibration did not converge in {max_iterations} iterations")


def synthetic_price_panel(
    spec: SyntheticSpec,
    *,
    n_sessions: int,
    n_names: int,
    plant_coef: float,
    seed: int,
    start: str,
    missing_fraction: float,
    idio_sd: float = 0.001,
) -> Panel:
    """A price panel whose bar returns are market + group + the residual-space panel (scaled
    to idio_sd), for the S1 fidelity check and synthetic CLI runs. Sessions are weekdays from
    `start`, bars 15 minutes apart from 14:30 UTC; volume is positive wherever close is finite."""
    bps = spec.bars_per_session
    n = n_sessions * bps
    rng = np.random.default_rng(seed + 1_000_003)
    resid, _ = generate_residual_panel(
        spec, np.ones((n, n_names), dtype=bool), plant_coef=plant_coef, seed=seed
    )
    groups = np.arange(n_names) % 5
    r = (
        rng.normal(0, 0.002, n)[:, None] * rng.uniform(0.5, 1.5, n_names)
        + rng.normal(0, 0.0015, (n, 5))[:, groups] * rng.uniform(0.5, 1.5, n_names)
        + idio_sd * resid
    )
    log_close = np.cumsum(r, axis=0) + math.log(100.0)
    close = np.exp(log_close)
    # bar_returns reads a session's first bar as open to close; later bars as close to close.
    opens = np.empty_like(close)
    opens[1:] = close[:-1]
    first = np.arange(0, n, bps)
    opens[first] = close[first] * np.exp(-r[first])
    missing = rng.random((n, n_names)) < missing_fraction
    close[missing] = np.nan
    opens[missing] = np.nan
    days = np.busday_offset(np.datetime64(start, "D"), np.arange(n_sessions), roll="forward")
    ts = (
        np.repeat(days, bps).astype("datetime64[m]")
        + np.timedelta64(14 * 60 + 30, "m")
        + np.tile(np.arange(bps), n_sessions) * np.timedelta64(15, "m")
    )
    return Panel(
        tf="15m",
        symbols=tuple(f"SYN{i:03d}" for i in range(n_names)),
        timestamps=ts,
        bars_per_session=bps,
        valid=np.ones(n, dtype=bool),
        open=opens,
        close=close,
        volume=np.where(missing, np.nan, 1e5),
    )
