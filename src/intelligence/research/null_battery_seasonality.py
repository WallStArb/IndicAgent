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

import dataclasses
import functools
from pathlib import Path

import numpy as np

from src.intelligence.research import null_battery_daily_residual as daily
from src.intelligence.research import static_sizes
from src.intelligence.research.combiner import EqualWeight
from src.intelligence.research.families.common import SESSION_DATES
from src.intelligence.research.portfolio import trailing_vol
from src.intelligence.research.spec import load_spec_from_file, resolve_member

_REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = "research/specs/seasonality_h5.yaml"
# 60 months of reads (about 1,300 sessions) + E17 L (1,408) + a tested span of about 6 years: 3,200
# sessions (about 12.7 years) leaves roughly 1,500 tested sessions per panel.
SESSIONS = 3200
_START = np.datetime64("2000-01-03")

DailyScenario = daily.DailyScenario
DIAGNOSTIC_CELLS = frozenset(
    {f"seasonal_{name.removeprefix('daily_')}" for name in daily.DIAGNOSTIC_CELLS}
)


@functools.lru_cache(maxsize=1)
def members() -> tuple[tuple[str, object, dict, int], ...]:
    """(name, function, params, slot history) of every registered member, in spec order."""
    spec = load_spec_from_file(_REPO_ROOT / SPEC_PATH, root=_REPO_ROOT).model
    return tuple(
        (m.name, resolve_member(m.signal), dict(m.params), m.slot_history_sessions)
        for m in spec.members
    )


def session_dates(sessions: int) -> np.ndarray:
    """datetime64[D] weekday sessions from 2000-01-03 (a Monday)."""
    return np.busday_offset(_START, np.arange(sessions)).astype("datetime64[D]")


def _arms(sc: DailyScenario, seed: int):
    resid, target = daily.null_panel(sc, seed)
    dates = session_dates(len(resid))
    vol = trailing_vol(
        resid, window_rows=daily._VOL_WINDOW_SESSIONS, min_finite=daily._VOL_WINDOW_SESSIONS // 2
    )
    trade = np.zeros(len(resid), dtype=bool)
    trade[daily._WARMUP_SESSIONS :] = True
    registered = members()
    alphas = []
    for name, fn, params, memory in registered:
        alpha = fn(
            resid,
            bars_per_session=1,
            coverage_floor=daily._COVERAGE_FLOOR,
            **{SESSION_DATES: dates},
            **params,
        )
        alphas.append(alpha)
        yield name, daily._score(alpha, vol, target, trade, memory, sc.horizon)
    book = EqualWeight((1.0,) * len(registered)).combine(np.stack(alphas, axis=2), None)
    yield "book_equal", daily._score(
        book, vol, target, trade, max(m[3] for m in registered), sc.horizon
    )


def simulate(sc: DailyScenario, seed: int) -> dict[str, tuple[float, float]]:
    """One H0 panel: {arm: (t, p)} for each member and the equal-weight book."""
    return {name: (r.hac.t, r.hac.p) for name, r in _arms(sc, seed)}


def simulate_series(sc: DailyScenario, seed: int) -> dict[str, np.ndarray]:
    """One H0 panel: {arm: D_s series} for the StepM battery."""
    return {name: r.series for name, r in _arms(sc, seed)}


def scenarios() -> tuple[DailyScenario, ...]:
    """The daily residual cells on panels long enough for the 60-month reads."""
    return tuple(
        dataclasses.replace(
            sc, name=f"seasonal_{sc.name.removeprefix('daily_')}", sessions=SESSIONS
        )
        for sc in daily.scenarios()
    )


def static_gate() -> static_sizes.StaticGate:
    """The sizes every gating cell holds at, as the daily residual battery's (same panels)."""
    return static_sizes.gate_from_cells(
        __name__,
        1,
        scenarios(),
        DIAGNOSTIC_CELLS,
        static=lambda c: (c.static_sd,),
        time_of_day=lambda c: (abs(c.market_mean),),
    )
