"""The E17 H0 battery for the seasonality family (methodology-change-ledger E17, condition 2; drafts
docs/plans/2026-11-15-published-prior-top3-prereg-drafts.md H-C; driver
scripts/research/e17_null_battery.py --battery src.intelligence.research.null_battery_seasonality).

The daily residual battery's panels and stresses (null_battery_daily_residual: one row per session,
overnight and intraday moves, Student t4 noise, static per-name means, a market mean, a common
factor, volatility clustering, late listings, an S1 cell), run on a weekday calendar so the members'
month labels and monthly sums are the production ones. A panel is long enough for the longest read
(60 months) plus the E17 memory and a tested span. Members, parameters and slot histories are read
from the registered spec (research/specs/seasonality_h5.yaml), never retyped, and the members are
scored at their declared memories with their equal-weight book through R1 and timing.timing_test.
Compute only.
"""

from __future__ import annotations

import functools
import math
from pathlib import Path

import numpy as np

from src.intelligence.research import null_battery_daily_residual as daily
from src.intelligence.research import static_sizes
from src.intelligence.research.combiner import EqualWeight
from src.intelligence.research.families.common import SESSION_DATES
from src.intelligence.research.portfolio import rank_vol_neutral_weights, trailing_vol
from src.intelligence.research.spec import load_spec_from_file, resolve_member
from src.intelligence.research.timing import e17_memory, timing_test

_REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = "research/specs/seasonality_h5.yaml"
# 60 months of reads (about 1,300 sessions) + E17 L (1,408) + a tested span of about 6 years: 3,200
# sessions (about 12.7 years) leaves roughly 1,500 tested sessions per panel.
SESSIONS = 3200
_START = np.datetime64("2000-01-03")

# This battery's own gating sizes (provisional, chosen before any panel is measured, in units of the
# idiosyncratic daily sd; the same values as the daily residual battery, pinned here so a rerun of
# that battery at other sizes does not move this gate silently). A change needs a rerun.
GATE_STATIC_SD = 0.06
GATE_MARKET_MEAN = 0.04
_STRESS_STATIC_SD = 0.3  # diagnostic cells document the limit

DailyScenario = daily.DailyScenario
DIAGNOSTIC_CELLS = frozenset({"seasonal_static_vol_stress", "seasonal_hostile_stress"})


@functools.lru_cache(maxsize=1)
def _spec():
    return load_spec_from_file(_REPO_ROOT / SPEC_PATH, root=_REPO_ROOT).model


def members() -> tuple[tuple[str, object, dict, int], ...]:
    """(name, function, params, slot history) of every registered member, in spec order."""
    return tuple(
        (m.name, resolve_member(m.signal), dict(m.params), m.slot_history_sessions)
        for m in _spec().members
    )


def _score(alpha, vol, target, trade, memory: int):
    """R1 and the E17 timing test with the spec's own construction, warmup and horizon."""
    spec = _spec()
    weights, has = rank_vol_neutral_weights(
        alpha,
        vol=vol,
        direction=float(spec.construction.direction),
        coverage_floor=spec.construction.coverage_floor,
    )
    return timing_test(
        weights,
        target,
        has,
        trade,
        bars_per_session=1,
        warmup_sessions=spec.scoring.warmup_sessions,
        memory_sessions=e17_memory(memory, spec.horizon, 1),
        overlap_sessions=spec.horizon - 1,
    )


def session_dates(sessions: int) -> np.ndarray:
    """datetime64[D] weekday sessions from 2000-01-03 (a Monday)."""
    return np.busday_offset(_START, np.arange(sessions)).astype("datetime64[D]")


def _arms(sc: DailyScenario, seed: int):
    spec = _spec()
    resid, target = daily.null_panel(sc, seed)
    dates = session_dates(len(resid))
    window = spec.construction.vol_window_sessions
    vol = trailing_vol(
        resid,
        window_rows=window,
        min_finite=math.ceil(spec.construction.vol_min_finite_fraction * window),
    )
    trade = np.zeros(len(resid), dtype=bool)
    trade[spec.scoring.warmup_sessions :] = True
    registered = members()
    alphas = []
    for name, fn, params, memory in registered:
        alpha = fn(
            resid,
            bars_per_session=1,
            coverage_floor=spec.construction.coverage_floor,
            **{SESSION_DATES: dates},
            **params,
        )
        alphas.append(alpha)
        yield name, _score(alpha, vol, target, trade, memory)
    book = EqualWeight((1.0,) * len(registered)).combine(np.stack(alphas, axis=2), None)
    yield "book_equal", _score(book, vol, target, trade, max(m[3] for m in registered))


def simulate(sc: DailyScenario, seed: int) -> dict[str, tuple[float, float]]:
    """One H0 panel: {arm: (t, p)} for each member and the equal-weight book."""
    return {name: (r.hac.t, r.hac.p) for name, r in _arms(sc, seed)}


def simulate_series(sc: DailyScenario, seed: int) -> dict[str, np.ndarray]:
    """One H0 panel: {arm: D_s series} for the StepM battery."""
    return {name: r.series for name, r in _arms(sc, seed)}


def scenarios() -> tuple[DailyScenario, ...]:
    """The daily residual battery's cells (null_battery_daily_residual.scenarios) at this
    battery's sizes, on panels long enough for the 60-month reads."""
    base = dict(market_mean=GATE_MARKET_MEAN, sessions=SESSIONS, horizon=_spec().horizon)
    other = dict(
        t4_noise=True, factor_sd=0.5, vol_clustering=True, late_fraction=0.4, late_name=True
    )
    return (
        DailyScenario("seasonal_gaussian", **base),
        DailyScenario("seasonal_static_means", static_sd=GATE_STATIC_SD, **base),
        DailyScenario("seasonal_late_listings", late_fraction=0.4, late_name=True, **base),
        DailyScenario("seasonal_hostile", static_sd=GATE_STATIC_SD, **base, **other),
        DailyScenario("seasonal_hostile_no_static", **base, **other),
        DailyScenario("seasonal_s1_hostile", static_sd=GATE_STATIC_SD, s1=True, **base, **other),
        DailyScenario(
            "seasonal_static_vol_stress", static_sd=_STRESS_STATIC_SD, vol_clustering=True, **base
        ),
        DailyScenario("seasonal_hostile_stress", static_sd=_STRESS_STATIC_SD, **base, **other),
    )


def static_gate() -> static_sizes.StaticGate:
    """The sizes every gating cell holds at: static per-name sd and the market mean (in absolute
    value), one cell row per session."""
    return static_sizes.gate_from_cells(
        __name__,
        1,
        scenarios(),
        DIAGNOSTIC_CELLS,
        static=lambda c: (c.static_sd,),
        time_of_day=lambda c: (abs(c.market_mean),),
    )
