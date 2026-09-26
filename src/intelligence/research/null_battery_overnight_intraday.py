"""The E17 H0 battery for family 2 (methodology-change-ledger E17, condition 2; driver
scripts/research/e17_null_battery.py --battery src.intelligence.research.null_battery_overnight_intraday).

Panels with no predictability, in family 2's shape: three legs per session (overnight, first
15 minutes, rest of session; `legs.py`), the target the rest-of-session leg entered at bar 1's
open. Stresses follow null_battery's conventions (Student t4 noise, static per-(leg, name)
means, a common factor with name loadings, volatility clustering, late listings, one late name,
trading from 252 sessions), plus a time-of-day market mean per leg, common to every name. The
measured means (187-name members' universe, 2010-2025, in units of each leg's idiosyncratic sd)
are overnight +0.0588, first 15 minutes -0.0263, rest of session +0.0127; gating cells use twice
those, as null_battery's S1 cell does.

An S1 scenario builds a synthetic 15m source panel whose session legs are exactly the drawn
legs (bar 1 opens at bar 0's close, so the target equals the rest leg) and sends it through the
production seam: transforms.SESSION_LEGS.apply, then runner.compute_residuals with that
transform (S1 per leg and on the target series). That puts S1's per-leg loadings in the loop,
the channel for the a^2 var(beta_hat) credit null_battery's s1_slot_stress documents.

Each simulation scores family 2's six members at their declared memories and their equal-weight
book (memory 61, the members' largest) through R1 and timing.timing_test. Compute only.
"""

from __future__ import annotations

import dataclasses
import math
import warnings

import numpy as np

from src.intelligence.research.families import overnight_intraday as f2
from src.intelligence.research.legs import LEGS, SIGNAL_LEG
from src.intelligence.research.null_battery import _listing_mask
from src.intelligence.research.panel import Panel
from src.intelligence.research.portfolio import rank_vol_neutral_weights, trailing_vol
from src.intelligence.research.timing import timing_test

# Members as registered (research/specs/family2_overnight_intraday.yaml): name, function,
# params, slot history (the E17 memory).
MEMBERS = (
    ("intraday_persistence_20", f2.intraday_persistence, {"window_sessions": 20}, 20),
    ("intraday_persistence_60", f2.intraday_persistence, {"window_sessions": 60}, 60),
    ("overnight_to_intraday_20", f2.overnight_to_intraday, {"window_sessions": 20}, 21),
    ("overnight_to_intraday_60", f2.overnight_to_intraday, {"window_sessions": 60}, 61),
    ("gap_fade", f2.gap_fade, {}, 1),
    ("gap_fade_z", f2.gap_fade_z, {"window_sessions": 60}, 61),
)
MEASURED_LEG_MEANS = (0.0588, -0.0263, 0.0127)  # overnight, first 15m, rest (idio sd units)
_WARMUP_SESSIONS = 252
_COVERAGE_FLOOR = 20
_VOL_WINDOW_SESSIONS = 20
_SOURCE_BARS = 4  # synthetic 15m bars per session on the S1 path: bar 0 plus a 3-bar rest
_PRICE_SCALE = 0.01  # leg noise sd 1 -> 1% returns, as null_battery's S1 path


@dataclasses.dataclass(frozen=True)
class LegsScenario:
    name: str
    sessions: int = 1500
    names: int = 60
    leg_means: tuple[float, float, float] = (0.0, 0.0, 0.0)
    t4_noise: bool = False
    static_cell_sd: float = 0.0  # per-(leg, name) mean
    factor_sd: float = 0.0  # common factor per (session, leg), loadings uniform on [0.5, 1.5]
    vol_clustering: bool = False
    late_fraction: float = 0.0
    late_name: bool = False
    s1: bool = False
    bars_per_session: int = LEGS  # _listing_mask's row unit


def _legs(sc: LegsScenario, rng: np.random.Generator) -> np.ndarray:
    """[S, 3, m] leg returns under H0 (leg noise sd about 1)."""
    s_n, m = sc.sessions, sc.names
    if sc.t4_noise:
        u = rng.standard_t(4, (s_n, LEGS, m)) / math.sqrt(2.0)
    else:
        u = rng.standard_normal((s_n, LEGS, m))
    if sc.vol_clustering:
        log_vol = np.zeros(s_n)
        shocks = 0.15 * rng.standard_normal(s_n)
        for s in range(1, s_n):
            log_vol[s] = 0.97 * log_vol[s - 1] + shocks[s]
        u *= np.exp(log_vol)[:, None, None]
    u = u + np.asarray(sc.leg_means)[None, :, None]
    if sc.static_cell_sd:
        u = u + sc.static_cell_sd * rng.standard_normal((LEGS, m))
    if sc.factor_sd:
        loading = rng.uniform(0.5, 1.5, m)
        u = u + sc.factor_sd * rng.standard_normal((s_n, LEGS, 1)) * loading
    return u


def _source_panel(u: np.ndarray, listed: np.ndarray, rng: np.random.Generator) -> Panel:
    """A 15m source panel whose session legs are u: open0 = previous final close x overnight,
    close0 = open0 x first leg, bars 1..3 open at the previous close and split the rest leg."""
    s_n, _, m = u.shape
    bps = _SOURCE_BARS
    rest_split = u[:, 2, None, :] / (bps - 1) + 0.5 * rng.standard_normal((s_n, bps - 1, m))
    rest_split[:, -1] = u[:, 2] - rest_split[:, :-1].sum(axis=1)
    steps = np.concatenate([u[:, :2], rest_split], axis=1) * _PRICE_SCALE  # [S, 1 + bps, m]
    log_price = math.log(100.0) + np.cumsum(steps.reshape(-1, m), axis=0).reshape(steps.shape)
    price = np.exp(log_price)
    opens = np.empty((s_n, bps, m))
    closes = np.empty((s_n, bps, m))
    opens[:, 0], closes[:, 0] = price[:, 0], price[:, 1]
    for b in range(1, bps):
        opens[:, b], closes[:, b] = price[:, b], price[:, b + 1]
    live = listed.reshape(s_n, LEGS, m)[:, 0]  # a name lists at a session boundary
    opens[~np.broadcast_to(live[:, None, :], opens.shape)] = np.nan
    closes[~np.broadcast_to(live[:, None, :], closes.shape)] = np.nan
    days = np.repeat(np.arange(s_n), bps) * np.timedelta64(1, "D")
    stamps = (
        np.datetime64("2000-01-03T14:30")
        + days
        + np.tile(np.arange(bps), s_n) * np.timedelta64(15, "m")
    )
    n = s_n * bps
    return Panel(
        tf="15m",
        symbols=tuple(f"s{j}" for j in range(m)),
        timestamps=stamps,
        bars_per_session=bps,
        valid=np.ones(n, dtype=bool),
        open=opens.reshape(n, m),
        close=closes.reshape(n, m),
        volume=np.ones((n, m)),
    )


def null_panel(sc: LegsScenario, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """(residual leg returns [3S, m], residual target [3S, m] on row 1) of one H0 panel."""
    rng = np.random.default_rng(seed)
    u = _legs(sc, rng)
    listed = _listing_mask(sc, rng)  # [3S, m], session-aligned since bars_per_session = 3
    if sc.s1:
        from src.intelligence.research import transforms
        from src.intelligence.research.runner import FACTOR_SPECS, compute_residuals

        source = _source_panel(u, listed, rng)
        t = transforms.SESSION_LEGS
        res = compute_residuals(
            t.apply(source, None),
            horizon=1,
            factor_spec=FACTOR_SPECS["vintage_1"],
            transform=t,
        )
        return res.bar, res.fwd
    resid = u.reshape(-1, sc.names).copy()
    resid[~listed] = np.nan
    target = np.full(resid.shape, np.nan)
    target[SIGNAL_LEG::LEGS] = resid[2::LEGS]
    return resid, target


def _score(alpha, vol, target, trade, memory: int) -> tuple[float, float]:
    weights, has = rank_vol_neutral_weights(
        alpha, vol=vol, direction=1.0, coverage_floor=_COVERAGE_FLOOR
    )
    res = timing_test(
        weights,
        target,
        has,
        trade,
        bars_per_session=LEGS,
        warmup_sessions=_WARMUP_SESSIONS,
        memory_sessions=memory,
    ).hac
    return res.t, res.p


def simulate(sc: LegsScenario, seed: int) -> dict[str, tuple[float, float]]:
    """One H0 panel: {arm: (t, p)} for each member and the equal-weight book."""
    resid, target = null_panel(sc, seed)
    window = _VOL_WINDOW_SESSIONS * LEGS
    vol = trailing_vol(resid, window_rows=window, min_finite=window // 2)
    trade = np.zeros(len(resid), dtype=bool)
    trade[_WARMUP_SESSIONS * LEGS :] = True
    out: dict[str, tuple[float, float]] = {}
    alphas = []
    for name, fn, params, memory in MEMBERS:
        alpha = fn(resid, bars_per_session=LEGS, coverage_floor=_COVERAGE_FLOOR, **params)
        alphas.append(alpha)
        out[name] = _score(alpha, vol, target, trade, memory)
    stack = np.stack(alphas, axis=2)
    with warnings.catch_warnings(), np.errstate(invalid="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)  # rows with no finite member stay NaN
        z = (stack - np.nanmean(stack, axis=1, keepdims=True)) / np.nanstd(
            stack, axis=1, keepdims=True
        )
    book = np.where(np.isfinite(z).all(axis=2), z.mean(axis=2), np.nan)
    out["book_equal"] = _score(book, vol, target, trade, max(m[3] for m in MEMBERS))
    return out


def scenarios() -> tuple[LegsScenario, ...]:
    """Gating cells at twice the measured leg means, plus 's1_leg_stress' (diagnostic): every
    leg's time-of-day mean at 0.3, the documented a^2 var(beta_hat) limit in family 2's shape."""
    twice = tuple(2 * a for a in MEASURED_LEG_MEANS)
    stress = dict(
        t4_noise=True,
        static_cell_sd=0.3,
        factor_sd=0.5,
        vol_clustering=True,
        late_fraction=0.4,
        late_name=True,
    )
    return (
        LegsScenario("legs_gaussian", leg_means=twice),
        LegsScenario("legs_static_means", leg_means=twice, static_cell_sd=0.3),
        LegsScenario("legs_late_listings", leg_means=twice, late_fraction=0.4, late_name=True),
        LegsScenario("legs_hostile", leg_means=twice, **stress),
        LegsScenario("legs_s1_hostile", leg_means=twice, s1=True, **stress),
        LegsScenario("legs_s1_leg_stress", leg_means=(0.3, 0.3, 0.3), s1=True),
    )


DIAGNOSTIC_CELLS = frozenset({"legs_s1_leg_stress"})
