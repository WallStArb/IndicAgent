"""The shared H0 stress primitives behind the E17 batteries (todo 546).

Every battery module composes the same five stresses — Student t4 noise, AR(1) log-vol
volatility clustering, static per-cell means, a common factor with uniform loadings, and late
listings — but each used to carry its own copy, and a fix to one stress in one module silently
left the other families' gates certified on the old one. These primitives are the single copy:
each issues exactly the rng call the inline code issued, in the order the modules compose them,
so every existing cell is bit-identical at fixed seeds (pinned by
tests/unit/test_null_panels.py). A new battery (184-05) builds on these instead of a fourth copy.

Pure: no I/O, no database. Constants are stress definitions, not tunables.
"""

from __future__ import annotations

import math

import numpy as np

# The stress definitions (module docstring). In one place so the batteries cannot drift apart.
T4_DOF = 4
T4_VARIANCE_SCALE = math.sqrt(2.0)  # standard_t(4) has variance 4: divide to reach unit
VOL_AR1 = 0.97  # log-vol persistence
VOL_SHOCK_SD = 0.15
FACTOR_LOADING_RANGE = (0.5, 1.5)  # uniform per-name loadings
LATE_LISTING_SPAN = 0.6  # late listings start uniformly in the first 60% of the span


def noise(rng: np.random.Generator, shape: tuple[int, ...], t4: bool) -> np.ndarray:
    """Unit-variance noise: standard_t(4)/sqrt(2) when t4, else standard_normal."""
    if t4:
        return rng.standard_t(T4_DOF, shape) / T4_VARIANCE_SCALE
    return rng.standard_normal(shape)


def vol_clustering(u: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Multiply u (first axis = sessions) by AR(1) log-vol: log_vol[s] = 0.97 log_vol[s-1]
    + 0.15 z, broadcast over every trailing axis. The shocks draw comes first, exactly where
    the inline copies drew it."""
    s_n = u.shape[0]
    log_vol = np.zeros(s_n)
    shocks = VOL_SHOCK_SD * rng.standard_normal(s_n)
    for s in range(1, s_n):
        log_vol[s] = VOL_AR1 * log_vol[s - 1] + shocks[s]
    return u * np.exp(log_vol)[(slice(None),) + (None,) * (u.ndim - 1)]


def cell_means(rng: np.random.Generator, shape: tuple[int, ...], sd: float) -> np.ndarray:
    """An additive per-cell mean field: sd * standard_normal(shape)."""
    return sd * rng.standard_normal(shape)


def factor_loadings(rng: np.random.Generator, names: int) -> np.ndarray:
    """Uniform per-name loadings on FACTOR_LOADING_RANGE."""
    return rng.uniform(*FACTOR_LOADING_RANGE, names)


def factor_term(
    rng: np.random.Generator,
    shock_shape: tuple[int, ...],
    names: int,
    sd: float,
    *,
    loadings_first: bool,
) -> np.ndarray:
    """The common-factor additive: per-(session[, cell]) shocks times the per-name loadings
    (the loadings broadcast over the shock shape's trailing name axis). The two historical
    draw orders are kept as a flag: the slot and legs batteries drew loadings first, the
    daily battery drew the shock first, and swapping the order changes the values at a fixed
    seed (bit-identity requirement, not a semantic difference)."""
    loadings = factor_loadings(rng, names) if loadings_first else None
    shock = sd * rng.standard_normal(shock_shape)
    if loadings is None:
        loadings = factor_loadings(rng, names)
    return shock * loadings


def listing_starts(
    rng: np.random.Generator, sessions: int, names: int, late_fraction: float, late_name: bool
) -> np.ndarray:
    """Session index each name lists at: 0, a uniform draw in the first LATE_LISTING_SPAN of
    the span for the late_fraction names, and LATE_LISTING_SPAN for name 0 when late_name."""
    start = np.zeros(names, dtype=int)
    late = rng.random(names) < late_fraction
    start[late] = rng.integers(1, int(LATE_LISTING_SPAN * sessions), int(late.sum()))
    if late_name:
        start[0] = int(LATE_LISTING_SPAN * sessions)
    return start


def listing_mask(
    starts: np.ndarray, sessions: int, names: int, bars_per_session: int
) -> np.ndarray:
    """bool [sessions * bars_per_session, names]: False before each name lists."""
    n = sessions * bars_per_session
    return np.arange(n)[:, None] >= (starts * bars_per_session)[None, :]
