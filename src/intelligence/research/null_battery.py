"""The H0 battery for the timing statistic (methodology-change-ledger E17, condition 2).

Panels with no predictability at all, built to stress what the decision statistic must survive:
Student t4 noise, static per-(slot, name) mean returns, a per-slot time-of-day effect common to
every name, a common factor with name loadings, volatility clustering, names that list late, and
one name listing partway through. A scenario may also send the panel through S1 (synthetic
prices into runner.compute_residuals, the production path) so the residualization's 252-session
loadings sit in the loop.

Each simulation scores the real family 1 members (same-slot means) and an equal-weight book of
them through the production construction (R1) and statistic (timing.timing_test), and returns
their one-sided HAC p values and t. Size must hold at 0.05, 0.01 and 0.00167. Compute only: no
I/O, no database; the driver (scripts/research/e17_null_battery.py) aggregates.
"""

from __future__ import annotations

import dataclasses
import math
import warnings

import numpy as np

from src.intelligence.research.families.intraday_periodicity import SLOT_BARS, same_slot_mean
from src.intelligence.research.panel import Panel
from src.intelligence.research.portfolio import rank_vol_neutral_weights, trailing_vol
from src.intelligence.research.timing import timing_test

ALPHAS = (0.05, 0.01, 0.00167)
MEMBER_WINDOWS = (1, 5, 20, 40)  # family 1's slot histories
_WARMUP_SESSIONS = 252
_COVERAGE_FLOOR = 20
_VOL_WINDOW_SESSIONS = 20


@dataclasses.dataclass(frozen=True)
class NullScenario:
    name: str
    sessions: int = 1500
    bars_per_session: int = 8
    names: int = 60
    t4_noise: bool = False
    static_cell_sd: float = 0.0  # per-(slot, name) mean, in units of the slot noise sd
    slot_effect_sd: float = 0.0  # per-slot mean shared by every name
    factor_sd: float = 0.0  # common factor, name loadings uniform on [0.5, 1.5]
    vol_clustering: bool = False
    late_fraction: float = 0.0  # names listing at a uniform point in the first 60% of the span
    late_name: bool = False  # name 0 lists at 60% of the span
    s1: bool = False  # residualize through runner.compute_residuals


def _slot_returns(sc: NullScenario, rng: np.random.Generator) -> np.ndarray:
    """[S, J, m] slot returns under H0 (slot noise sd about 1)."""
    s_n, j_n, m = sc.sessions, sc.bars_per_session // SLOT_BARS, sc.names
    if sc.t4_noise:
        noise = rng.standard_t(4, (s_n, j_n, m)) / math.sqrt(2.0)  # unit variance
    else:
        noise = rng.standard_normal((s_n, j_n, m))
    if sc.vol_clustering:
        log_vol = np.zeros(s_n)
        shocks = 0.15 * rng.standard_normal(s_n)
        for s in range(1, s_n):
            log_vol[s] = 0.97 * log_vol[s - 1] + shocks[s]
        noise *= np.exp(log_vol)[:, None, None]
    u = noise
    if sc.static_cell_sd:
        u = u + sc.static_cell_sd * rng.standard_normal((j_n, m))
    if sc.slot_effect_sd:
        u = u + sc.slot_effect_sd * rng.standard_normal((j_n, 1))
    if sc.factor_sd:
        loading = rng.uniform(0.5, 1.5, m)
        u = u + sc.factor_sd * rng.standard_normal((s_n, j_n, 1)) * loading
    return u


def _listing_mask(sc: NullScenario, rng: np.random.Generator) -> np.ndarray:
    """bool [n, m]: False before each name lists."""
    n, m = sc.sessions * sc.bars_per_session, sc.names
    start = np.zeros(m, dtype=int)
    late = rng.random(m) < sc.late_fraction
    start[late] = rng.integers(1, int(0.6 * sc.sessions), late.sum())
    if sc.late_name:
        start[0] = int(0.6 * sc.sessions)
    return np.arange(n)[:, None] >= (start * sc.bars_per_session)[None, :]


def _bars(u: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """[n, m] bar returns whose slot pairs sum to u."""
    first = u / SLOT_BARS + 0.5 * rng.standard_normal(u.shape)
    s_n, j_n, m = u.shape
    return np.stack([first, u - first], axis=2).reshape(s_n * j_n * SLOT_BARS, m)


def _target(u: np.ndarray, bps: int) -> np.ndarray:
    """[n, m] slot j of session d at row d * bps + 2j - 1 (the bar before the slot)."""
    s_n, j_n, m = u.shape
    rows = (np.arange(s_n)[:, None] * bps + SLOT_BARS * np.arange(j_n)[None, :] - 1).ravel()
    keep = rows >= 0
    out = np.full((s_n * bps, m), np.nan)
    out[rows[keep]] = u.reshape(-1, m)[keep]
    return out


def _s1(bars: np.ndarray, sc: NullScenario) -> tuple[np.ndarray, np.ndarray]:
    """Prices from the bar returns (1% slot noise sd), then S1 as the runner applies it."""
    from src.intelligence.research.runner import FACTOR_SPECS, compute_residuals

    bps = sc.bars_per_session
    n, m = bars.shape
    log_close = np.log(100.0) + np.nancumsum(0.01 * bars, axis=0)
    close = np.exp(log_close)
    opens = np.vstack([np.full((1, m), 100.0), close[:-1]])
    opens[np.isnan(bars)] = np.nan
    close[np.isnan(bars)] = np.nan
    days = np.repeat(np.arange(sc.sessions), bps) * np.timedelta64(1, "D")
    stamps = (
        np.datetime64("2000-01-03T14:30")
        + days
        + np.tile(np.arange(bps), sc.sessions) * (np.timedelta64(15, "m"))
    )
    panel = Panel(
        tf="15m",
        symbols=tuple(f"s{j}" for j in range(m)),
        timestamps=stamps,
        bars_per_session=bps,
        valid=np.ones(n, dtype=bool),
        open=opens,
        close=close,
        volume=np.ones((n, m)),
    )
    res = compute_residuals(panel, horizon=SLOT_BARS, factor_spec=FACTOR_SPECS["vintage_1"])
    return res.bar, res.fwd


def null_panel(sc: NullScenario, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """(residual bar returns [n, m], residual target [n, m]) of one H0 panel: the members'
    input and the target at each slot's placement row, NaN where a name has not listed."""
    rng = np.random.default_rng(seed)
    bps = sc.bars_per_session
    u = _slot_returns(sc, rng)
    listed = _listing_mask(sc, rng)
    bars = _bars(u, rng)
    bars[~listed] = np.nan
    if sc.s1:
        resid, target = _s1(bars, sc)
    else:
        resid = bars
        target = _target(u, bps)
        target[~listed] = np.nan
        # A slot with a missing bar has no target (the member sees NaN there too).
        slot_ok = listed.reshape(sc.sessions, -1, SLOT_BARS, sc.names).all(axis=2)
        target[np.isnan(_target(np.where(slot_ok, u, np.nan), bps))] = np.nan
    return resid, target


def simulate(sc: NullScenario, seed: int) -> dict[str, tuple[float, float]]:
    """One H0 panel: {arm: (t, p)} for each member window and the equal-weight book."""
    bps = sc.bars_per_session
    resid, target = null_panel(sc, seed)
    window = _VOL_WINDOW_SESSIONS * bps
    vol = trailing_vol(resid, window_rows=window, min_finite=window // 2)
    trade = np.zeros(len(resid), dtype=bool)
    trade[_WARMUP_SESSIONS * bps :] = True
    kw = dict(bars_per_session=bps, warmup_sessions=_WARMUP_SESSIONS)
    out: dict[str, tuple[float, float]] = {}
    members = []
    for w in MEMBER_WINDOWS:
        alpha = same_slot_mean(
            resid, bars_per_session=bps, coverage_floor=_COVERAGE_FLOOR, window_sessions=w
        )
        members.append(alpha)
        weights, has = rank_vol_neutral_weights(
            alpha, vol=vol, direction=1.0, coverage_floor=_COVERAGE_FLOOR
        )
        res = timing_test(weights, target, has, trade, memory_sessions=w, **kw).hac
        out[f"mean{w}"] = (res.t, res.p)
    stack = np.stack(members, axis=2)
    with warnings.catch_warnings(), np.errstate(invalid="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)  # rows with no finite member stay NaN
        z = (stack - np.nanmean(stack, axis=1, keepdims=True)) / np.nanstd(
            stack, axis=1, keepdims=True
        )
    book = np.where(np.isfinite(z).all(axis=2), z.mean(axis=2), np.nan)
    weights, has = rank_vol_neutral_weights(
        book, vol=vol, direction=1.0, coverage_floor=_COVERAGE_FLOOR
    )
    res = timing_test(weights, target, has, trade, memory_sessions=max(MEMBER_WINDOWS), **kw).hac
    out["book_equal"] = (res.t, res.p)
    return out


# The per-slot market mean measured on family 1's panel (2010-2025, 13 half-hour slots): rms
# 0.0096 of the idiosyncratic slot sd. The gating S1 cell uses twice that.
MEASURED_SLOT_EFFECT_SD = 0.0096


def scenarios() -> tuple[NullScenario, ...]:
    """E17 condition 2's cells, all gating size, plus one diagnostic (DIAGNOSTIC_CELLS).
    'hostile' combines every stress at 0.3 of the slot sd; 's1_hostile' sends it through S1
    with the slot effect at twice the measured size. 's1_slot_stress' is the documented limit:
    scored on S1 residual targets, a book is credited with S1's per-slot beta error times the
    time-of-day market mean, a bias of order a^2 var(beta_hat), material at a = 0.3 and about
    a thousandth of that at the measured size."""
    stress = dict(
        t4_noise=True,
        static_cell_sd=0.3,
        slot_effect_sd=0.3,
        factor_sd=0.5,
        vol_clustering=True,
        late_fraction=0.4,
        late_name=True,
    )
    s1_stress = {**stress, "slot_effect_sd": 2 * MEASURED_SLOT_EFFECT_SD}
    return (
        NullScenario("gaussian"),
        NullScenario("t4", t4_noise=True),
        NullScenario("static_cell_means", static_cell_sd=0.3),
        NullScenario("slot_effects", slot_effect_sd=0.3),
        NullScenario("late_listings", late_fraction=0.4, late_name=True),
        NullScenario("late_listings_static_means", late_fraction=0.4, static_cell_sd=0.3),
        NullScenario("hostile", **stress),
        NullScenario("real_grid_hostile", bars_per_session=26, **stress),
        NullScenario("s1_hostile", s1=True, **s1_stress),
        NullScenario("s1_slot_stress", s1=True, slot_effect_sd=0.3),
    )


DIAGNOSTIC_CELLS = frozenset({"s1_slot_stress"})
