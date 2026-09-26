"""Synthetic panels for the book test's power check (D-11, D-19, D-20; research pattern 8).

Planting happens in residual space and power replicates skip S1: S1 costs minutes per
residualization of the full panel, and what S1 removes (market, groups, statistical factors)
is not what the power question asks. synthetic_price_panel adds factor structure back for the
check that S1 passes such a plant nearly unchanged.

- Breadth (D-20). Each slot's residual cross-section has covariance I + s Q Q' with Q a seeded
  random orthonormal m x k basis and s set by loading_scale_for_pr, so its participation ratio
  equals the pinned breadth (60, from step 0). Independent residuals would overstate power
  about twofold.
- Plants. Each family owns its generator (the `Plant` protocol below), in its own module next
  to its members: family 1's HKS same-slot plant is `families.intraday_periodicity.SameSlotPlant`.
  This module holds only what every plant shares.
- Effect size (D-19). The planted strength c is calibrated so the per-slot cross-sectional rank
  IC of the best linear combination of the members against the target equals the
  pre-declared IC (0.002 for family 1).
- The finite mask carries no return information; passing the real panel's mask
  (np.isfinite(panel.close)) makes coverage realistic.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable, Sequence
from typing import Protocol

import numpy as np

from src.intelligence.research.panel import Panel
from src.intelligence.research.portfolio import average_ranks
from src.intelligence.statistics.correlation import pairwise_corr
from src.intelligence.statistics.correlation import participation_ratio as statistics_pr


class Plant(Protocol):
    """A family's synthetic generator (it lives in the family's module, next to its members):
    residual-space bar returns with the family's effect planted at strength plant_coef, and the
    matching target. `finite_mask` carries the real residuals' availability only;
    `target_mask`, when given, the real target's."""

    bars_per_session: int

    def generate(
        self,
        finite_mask: np.ndarray,
        *,
        plant_coef: float,
        seed: int,
        target_mask: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]: ...


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


def factor_basis(rng: np.random.Generator, n_names: int, n_factors: int) -> np.ndarray:
    """Q [m, k]: a seeded random orthonormal basis for the common part of the residuals."""
    if n_factors == 0:
        return np.zeros((n_names, 0))
    return np.linalg.qr(rng.standard_normal((n_names, n_factors)))[0]


def breadth_noise(rng: np.random.Generator, n_rows: int, q: np.ndarray, scale: float) -> np.ndarray:
    """[n_rows, m] cross-sections with covariance I + scale Q Q', demeaned per row (D-20)."""
    m, k = q.shape
    e = rng.standard_normal((n_rows, m)) + math.sqrt(scale) * rng.standard_normal((n_rows, k)) @ q.T
    return e - e.mean(axis=1, keepdims=True)


def participation_ratio(
    x: np.ndarray, *, min_coverage: float = 0.8, min_overlap: int = 100
) -> float:
    """Step 0's breadth of a residual panel x [T, m]: names with at least min_coverage finite
    rows, their pairwise-complete correlation (pairs need min_overlap common rows), and its
    participation ratio (docs/research/measurement-residual-breadth.md)."""
    keep = np.isfinite(x).mean(axis=0) >= min_coverage
    if keep.sum() < 2:
        raise ValueError(f"{keep.sum()} name(s) meet the coverage rule; breadth needs 2")
    return statistics_pr(pairwise_corr(x[:, keep], min_overlap))


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
    """[n, m, K] float32, filled one member at a time to bound peak memory."""
    stack = np.empty((*resid_bar.shape, len(members)), dtype=np.float32)
    for k, (fn, params) in enumerate(members):
        stack[:, :, k] = fn(
            resid_bar, bars_per_session=bps, coverage_floor=coverage_floor, **params
        )
    return stack


@dataclasses.dataclass(frozen=True)
class CalibratedPlant:
    plant_coef: float
    achieved_ic: float
    ic_se: float
    iterations: int


def calibrate_plant(
    plant: Plant,
    finite_mask: np.ndarray,
    *,
    members: Sequence[tuple[Callable, dict]],
    coverage_floor: int,
    target_ic: float,
    tolerance: float,
    n_panels: int,
    seed: int,
    max_iterations: int = 60,
    target_mask: np.ndarray | None = None,
) -> CalibratedPlant:
    """Bisection on plant_coef with common random numbers (the same n_panels seeds at every
    step) until the mean combo_rank_ic is within tolerance of target_ic."""
    seeds = [seed + i for i in range(n_panels)]

    def ics(coef: float) -> np.ndarray:
        out = []
        for s in seeds:
            resid, target = plant.generate(
                finite_mask, plant_coef=coef, seed=s, target_mask=target_mask
            )
            stack = _member_stack(resid, members, plant.bars_per_session, coverage_floor)
            out.append(
                combo_rank_ic(
                    stack,
                    target,
                    coverage_floor=coverage_floor,
                    bars_per_session=plant.bars_per_session,
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
    plant: Plant,
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
    bps = plant.bars_per_session
    n = n_sessions * bps
    rng = np.random.default_rng(seed + 1_000_003)
    resid, _ = plant.generate(np.ones((n, n_names), dtype=bool), plant_coef=plant_coef, seed=seed)
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
