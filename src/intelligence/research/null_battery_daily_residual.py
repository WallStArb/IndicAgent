"""The E17 H0 battery for the daily residual family (methodology-change-ledger E17, condition 2;
prereg docs/plans/2026-10-27-daily-residual-momentum-reversal-prereg.md, B2; driver
scripts/research/e17_null_battery.py --battery src.intelligence.research.null_battery_daily_residual).

Panels with no predictability in the family's shape: one row per session, each session's
return split into an overnight move (into its open) and an intraday move (open to close). The
members read close-to-close returns; the target is open-to-open over the next h = 5 sessions,
entered at the next open, so it carries five intraday moves and the overnight moves into
sessions d+2 .. d+6. The overnight split is what lets the battery see a target that shares an
overnight move with a member's oldest input (E17 L, timing.e17_memory).
Consecutive targets overlap by 4 sessions, the case E17's Newey-West lag must cover at this
horizon (prereg section 4). Stresses follow null_battery's conventions: Student t4 noise, static
per-name mean returns, a market mean common to every name, a common factor with name loadings,
volatility clustering, late listings and one late name. An S1 cell builds a synthetic daily
price panel and sends it through runner.compute_residuals (S1 on the bars and on the 5-session
forward target), so S1's 252-session loadings and the forward-horizon lag are in the loop.

The gating sizes are provisional, chosen before the daily panel is measured: a static per-name
mean sd of 0.06 and a market mean of 0.04 (each in units of the idiosyncratic daily sd; a daily
equity drift of about 4 bps over a 2% idiosyncratic sd is 0.02). static_sizes.measure on the
spec's own panel must come in under them, or the run refuses and the battery reruns at twice
the measured sizes. Cells at 0.3 document the limit and are diagnostics.

Each simulation scores the five members at their declared memories and their equal-weight book
(memory 252, the members' largest) through R1 and timing.timing_test. Compute only.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np

from src.intelligence.research import static_sizes
from src.intelligence.research.combiner import EqualWeight
from src.intelligence.research.families import daily_residual as fam
from src.intelligence.research.null_battery import listing_mask
from src.intelligence.research.panel import Panel
from src.intelligence.research.portfolio import rank_vol_neutral_weights, trailing_vol
from src.intelligence.research.timing import e17_memory, timing_test

# Members as registered (research/specs/daily_residual_h5.yaml): name, function, params, slot
# history (the E17 memory).
MEMBERS = (
    ("residual_momentum_12_1", fam.residual_momentum, {}, 252),
    ("residual_momentum_12_1_z", fam.residual_momentum_z, {}, 252),
    ("reversal_5", fam.residual_reversal, {"window_sessions": 5}, 5),
    ("reversal_21", fam.residual_reversal, {"window_sessions": 21}, 21),
    ("reversal_5_skip1", fam.residual_reversal, {"window_sessions": 5, "skip_sessions": 1}, 6),
)
HORIZON = 5  # the spec's target horizon in sessions
GATE_STATIC_SD = 0.06  # provisional gating sizes (docstring); a change needs a rerun
GATE_MARKET_MEAN = 0.04
_WARMUP_SESSIONS = 252
_COVERAGE_FLOOR = 20
_VOL_WINDOW_SESSIONS = 60
_PRICE_SCALE = 0.01  # noise sd 1 -> 1% daily returns


@dataclasses.dataclass(frozen=True)
class DailyScenario:
    name: str
    sessions: int = 2000
    names: int = 100
    market_mean: float = 0.0
    t4_noise: bool = False
    static_sd: float = 0.0
    factor_sd: float = 0.0  # common factor per session, loadings uniform on [0.5, 1.5]
    vol_clustering: bool = False
    late_fraction: float = 0.0
    late_name: bool = False
    s1: bool = False
    bars_per_session: int = 1  # listing_mask's row unit
    horizon: int = HORIZON  # target horizon in sessions (todo 547 certifies h = 5 and 21)


def _returns(sc: DailyScenario, rng: np.random.Generator) -> np.ndarray:
    """[S, m] daily returns under H0 (noise sd about 1)."""
    s_n, m = sc.sessions, sc.names
    if sc.t4_noise:
        u = rng.standard_t(4, (s_n, m)) / math.sqrt(2.0)
    else:
        u = rng.standard_normal((s_n, m))
    if sc.vol_clustering:
        log_vol = np.zeros(s_n)
        shocks = 0.15 * rng.standard_normal(s_n)
        for s in range(1, s_n):
            log_vol[s] = 0.97 * log_vol[s - 1] + shocks[s]
        u *= np.exp(log_vol)[:, None]
    u = u + sc.market_mean
    if sc.static_sd:
        u = u + sc.static_sd * rng.standard_normal(m)
    if sc.factor_sd:
        u = u + sc.factor_sd * rng.standard_normal((s_n, 1)) * rng.uniform(0.5, 1.5, m)
    return u


_OVERNIGHT_SHARE = 0.3  # each session's overnight move: 0.3 u plus noise of sd 0.4


def _split(u: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """(overnight, intraday) [S, m] moves summing to u."""
    overnight = _OVERNIGHT_SHARE * u + 0.4 * rng.standard_normal(u.shape)
    return overnight, u - overnight


def _forward(overnight: np.ndarray, intraday: np.ndarray, horizon: int = HORIZON) -> np.ndarray:
    """[S, m] row d: log(open[d+1+h] / open[d+1]) = intraday d+1 .. d+h plus overnight
    d+2 .. d+1+h (NaN if any is missing or past the end)."""
    s_n = len(intraday)
    out = np.full(intraday.shape, np.nan)
    rows = s_n - 1 - horizon
    if rows <= 0:
        return out
    win = np.lib.stride_tricks.sliding_window_view
    intra = win(intraday[1:], horizon, axis=0)[:rows].sum(axis=-1)
    over = win(overnight[2:], horizon, axis=0)[:rows].sum(axis=-1)
    out[:rows] = intra + over
    return out


def _price_panel(overnight: np.ndarray, intraday: np.ndarray, listed: np.ndarray) -> Panel:
    """A daily panel built from the moves (scaled): open = previous close x overnight,
    close = open x intraday."""
    s_n, m = intraday.shape
    steps = np.stack([overnight, intraday], axis=1).reshape(2 * s_n, m) * _PRICE_SCALE
    log_price = np.log(100.0) + np.cumsum(steps, axis=0)
    opens, close = np.exp(log_price[0::2]), np.exp(log_price[1::2])
    close = np.where(listed, close, np.nan)
    opens = np.where(listed, opens, np.nan)
    stamps = np.datetime64("2000-01-03T21:00") + np.arange(s_n) * np.timedelta64(1, "D")
    return Panel(
        tf="1d",
        symbols=tuple(f"s{j}" for j in range(m)),
        timestamps=stamps,
        bars_per_session=1,
        valid=np.ones(s_n, dtype=bool),
        open=opens,
        close=close,
        volume=np.ones((s_n, m)),
    )


def null_panel(sc: DailyScenario, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """(residual daily returns [S, m], residual h-session target [S, m]) of one H0 panel."""
    rng = np.random.default_rng(seed)
    u = _returns(sc, rng)
    listed = listing_mask(sc, rng)
    overnight, intraday = _split(u, rng)
    if sc.s1:
        from src.intelligence.research.runner import FACTOR_SPECS, compute_residuals

        res = compute_residuals(
            _price_panel(overnight, intraday, listed),
            horizon=sc.horizon,
            factor_spec=FACTOR_SPECS["vintage_1"],
        )
        return res.bar, res.fwd
    resid = np.where(listed, u, np.nan)
    target = _forward(
        np.where(listed, overnight, np.nan), np.where(listed, intraday, np.nan), sc.horizon
    )
    return resid, target


def _score(alpha, vol, target, trade, memory: int, horizon: int):
    weights, has = rank_vol_neutral_weights(
        alpha, vol=vol, direction=1.0, coverage_floor=_COVERAGE_FLOOR
    )
    return timing_test(
        weights,
        target,
        has,
        trade,
        bars_per_session=1,
        warmup_sessions=_WARMUP_SESSIONS,
        memory_sessions=e17_memory(memory, horizon, 1),
    )


def _arms(sc: DailyScenario, seed: int):
    resid, target = null_panel(sc, seed)
    vol = trailing_vol(
        resid, window_rows=_VOL_WINDOW_SESSIONS, min_finite=_VOL_WINDOW_SESSIONS // 2
    )
    trade = np.zeros(len(resid), dtype=bool)
    trade[_WARMUP_SESSIONS:] = True
    alphas = []
    for name, fn, params, memory in MEMBERS:
        alpha = fn(resid, bars_per_session=1, coverage_floor=_COVERAGE_FLOOR, **params)
        alphas.append(alpha)
        yield name, _score(alpha, vol, target, trade, memory, sc.horizon)
    # The runner's combiner, so the battery certifies the book run_book scores.
    book = EqualWeight((1.0,) * len(MEMBERS)).combine(np.stack(alphas, axis=2), None)
    yield "book_equal", _score(book, vol, target, trade, max(m[3] for m in MEMBERS), sc.horizon)


def simulate(sc: DailyScenario, seed: int) -> dict[str, tuple[float, float]]:
    """One H0 panel: {arm: (t, p)} for each member and the equal-weight book."""
    return {name: (r.hac.t, r.hac.p) for name, r in _arms(sc, seed)}


def simulate_series(sc: DailyScenario, seed: int) -> dict[str, np.ndarray]:
    """One H0 panel: {arm: D_s series} for the StepM battery (scripts/research/
    stepm_null_battery.py)."""
    return {name: r.series for name, r in _arms(sc, seed)}


def scenarios() -> tuple[DailyScenario, ...]:
    """Gating cells at the provisional gate sizes; diagnostics at 0.3."""
    base = dict(market_mean=GATE_MARKET_MEAN)
    other = dict(
        t4_noise=True, factor_sd=0.5, vol_clustering=True, late_fraction=0.4, late_name=True
    )
    return (
        DailyScenario("daily_gaussian", **base),
        DailyScenario("daily_static_means", static_sd=GATE_STATIC_SD, **base),
        DailyScenario("daily_late_listings", late_fraction=0.4, late_name=True, **base),
        DailyScenario("daily_hostile", static_sd=GATE_STATIC_SD, **base, **other),
        DailyScenario("daily_hostile_no_static", **base, **other),
        DailyScenario("daily_s1_hostile", static_sd=GATE_STATIC_SD, s1=True, **base, **other),
        DailyScenario("daily_static_vol_stress", static_sd=0.3, vol_clustering=True, **base),
        DailyScenario("daily_hostile_stress", static_sd=0.3, **base, **other),
    )


DIAGNOSTIC_CELLS = frozenset({"daily_static_vol_stress", "daily_hostile_stress"})


def static_gate() -> static_sizes.StaticGate:
    """The sizes every gating cell holds at: static per-name sd and the market mean (in
    absolute value), one cell row per session."""
    return static_sizes.gate_from_cells(
        __name__,
        1,
        scenarios(),
        DIAGNOSTIC_CELLS,
        static=lambda c: (c.static_sd,),
        time_of_day=lambda c: (abs(c.market_mean),),
    )
