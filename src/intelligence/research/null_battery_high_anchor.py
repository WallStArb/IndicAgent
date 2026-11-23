"""The E17 H0 battery for family 9, the 52-week-high member (methodology-change-ledger E17,
condition 2; prereg docs/plans/2026-11-15-family9-52week-high-prereg-draft.md section 6.6; driver
scripts/research/e17_null_battery.py --battery src.intelligence.research.null_battery_high_anchor).

The daily residual battery's panels and stresses (null_battery_daily_residual: one row per session,
overnight and intraday moves, Student t4 noise, static per-name means, a market mean, a common
factor, volatility clustering, late listings, an S1 cell), with one addition: the member reads the
panel's close, not the residual returns, so each simulation also builds the synthetic price panel of
the same seeded draw (the one the daily battery sends through S1) and the member runs on its close
through member_sources.compute_panel_members, the runner's own route. Synthetic closes have no
dividends, so total-return and price-only are the same series here. Disclosed limit of the pass: the
synthetic closes are finite once listed, so the battery does not exercise the real panel's NaN
structure (NaN outside dividend coverage and for 240 sessions after a suspect dividend event,
ledger 2026-11-23d); the size cells certify the statistic on a complete-panel null. Members, parameters and slot
histories are read from the registered spec (research/specs/family9_high_anchor_h5.yaml), never
retyped, and the member is scored at its declared memory through R1 and timing.timing_test. The
cells are the daily battery's, renamed. Compute only.
"""

from __future__ import annotations

import dataclasses
import functools
import math
from pathlib import Path

import numpy as np

from src.intelligence.research import battery_pass, member_sources, static_sizes
from src.intelligence.research import null_battery_daily_residual as daily
from src.intelligence.research.null_battery import listing_mask
from src.intelligence.research.panel import Panel
from src.intelligence.research.portfolio import rank_vol_neutral_weights, trailing_vol
from src.intelligence.research.spec import load_spec_from_file
from src.intelligence.research.timing import e17_memory, timing_test

_REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = "research/specs/family9_high_anchor_h5.yaml"

DailyScenario = daily.DailyScenario


def _rename(name: str) -> str:
    """A daily battery cell name as this battery's cell name."""
    return name.replace("daily_", "high_anchor_", 1)


DIAGNOSTIC_CELLS = frozenset(_rename(name) for name in daily.DIAGNOSTIC_CELLS)


@functools.lru_cache(maxsize=1)
def _spec():
    return load_spec_from_file(_REPO_ROOT / SPEC_PATH, root=_REPO_ROOT).model


def price_panel(sc: DailyScenario, seed: int) -> Panel:
    """The synthetic daily price panel of the draw `daily.null_panel(sc, seed)` reads: the same
    generator calls in the same order on the same seed, so the closes and the residual returns and
    target the member is scored against are one panel."""
    rng = np.random.default_rng(seed)
    u = daily._returns(sc, rng)
    listed = listing_mask(sc, rng)
    overnight, intraday = daily._split(u, rng)
    return daily._price_panel(overnight, intraday, listed)


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
        memory_sessions=e17_memory(memory, spec.horizon, 1, spec.construction.vol_window_sessions),
        overlap_sessions=spec.horizon - 1,
    )


def _arms(sc: DailyScenario, seed: int):
    spec = _spec()
    resid, target = daily.null_panel(sc, seed)
    members = member_sources.compute_panel_members(spec, price_panel(sc, seed), bars_per_session=1)
    window = spec.construction.vol_window_sessions
    vol = trailing_vol(
        resid,
        window_rows=window,
        min_finite=math.ceil(spec.construction.vol_min_finite_fraction * window),
    )
    trade = np.zeros(len(resid), dtype=bool)
    trade[spec.scoring.warmup_sessions :] = True
    for m in spec.members:
        yield m.name, _score(members[m.name], vol, target, trade, m.slot_history_sessions)


def simulate(sc: DailyScenario, seed: int) -> dict[str, tuple[float, float]]:
    """One H0 panel: {member: (t, p)}."""
    return {name: (r.hac.t, r.hac.p) for name, r in _arms(sc, seed)}


def simulate_series(sc: DailyScenario, seed: int) -> dict[str, np.ndarray]:
    """One H0 panel: {member: D_s series} for the StepM battery."""
    return {name: r.series for name, r in _arms(sc, seed)}


def scenarios() -> tuple[DailyScenario, ...]:
    """The daily residual battery's cells (null_battery_daily_residual.scenarios), renamed."""
    return tuple(dataclasses.replace(sc, name=_rename(sc.name)) for sc in daily.scenarios())


def inputs_mismatch(spec) -> list[str]:
    """What this battery simulates that the family spec does not say (battery_pass.make_record
    refuses a bind while this is non-empty): the registered spec at SPEC_PATH must be the spec bound,
    every member must read the panel close with no orthogonalization stage (the battery runs
    member_sources.compute_panel_members only), and the daily battery's module constants that the
    cells and the scoring read must equal the spec's."""
    out = []
    if battery_pass.battery_input_hash(spec) != battery_pass.battery_input_hash(_spec()):
        out.append(f"inputs differ from {SPEC_PATH}")
    if any(m.panel_source != "close" or m.orthogonalize is not None for m in spec.members):
        out.append("members: every member must be a close panel_source with no orthogonalize")
    c = spec.construction
    checks = {
        "horizon": (daily.HORIZON, spec.horizon),
        "coverage_floor": (daily._COVERAGE_FLOOR, c.coverage_floor),
        "vol_window_sessions": (daily._VOL_WINDOW_SESSIONS, c.vol_window_sessions),
        "warmup_sessions": (daily._WARMUP_SESSIONS, spec.scoring.warmup_sessions),
    }
    out += [name for name, (battery, registered) in checks.items() if battery != registered]
    return out


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
