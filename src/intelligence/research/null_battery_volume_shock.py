"""The E17 H0 battery for family 10, the volume shock members (methodology-change-ledger E17,
condition 2, E24; ledger 2026-11-23e; driver scripts/research/e17_null_battery.py --battery
src.intelligence.research.null_battery_volume_shock).

The daily residual battery's return panels and stresses (null_battery_daily_residual), plus a
synthetic share-volume panel per cell, scored through the same stage the run uses: the members of
the registered spec (research/specs/family10_volume_shock_h5.yaml, never retyped) are computed by
`volume_rank_member`, then `member_sources.orthogonalize_members` residualizes them on the S1
residual returns, then R1 and timing.timing_test score each member and their equal-weight book.

H0: volume carries no information about future returns. The generator below makes volume depend
on the same-session and the previous-session move size (|u|), which is exactly what the stage
exists to remove and what volatility clustering turns into a variance link, but never on a future
signed return. Every constant is a named value here, declared in the registration ledger line
before the first block, and changed only by a dated amendment.

Disclosed limits of the pass: in the static-mean cells the generator's volume depends on |resid|, which
includes the per-name static means, so volume levels correlate with |static mean|; and in the S1
cell the volume is NaN wherever the S1 residual returns are (the S1 warmup), so the members start
later than on the real panel.

Panels carry NAMES = 300 names, not the daily battery's 100: the spec's 200-name fit minimum
(`min_names`) would leave every row of a 100-name panel NaN. Compute only.
"""

from __future__ import annotations

import dataclasses
import functools
import math
from pathlib import Path

import numpy as np

from src.intelligence.research import battery_pass, member_sources, null_panels, static_sizes
from src.intelligence.research import null_battery_daily_residual as daily
from src.intelligence.research.combiner import EqualWeight
from src.intelligence.research.portfolio import trailing_vol
from src.intelligence.research.spec import load_spec_from_file, resolve_member

_REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = "research/specs/family10_volume_shock_h5.yaml"
# Longest read (the member's 50 sessions) plus S1's 273 and the E17 memory L, plus a tested span of
# about 6 years: 3,200 sessions leaves roughly 1,500 tested sessions per panel (as the seasonality
# battery).
SESSIONS = 3200
NAMES = 300  # above the spec's 200-name fit minimum; unchanged, so the registered stage runs as is

# This battery's own gating sizes (provisional, chosen before any panel is measured, in units of the
# idiosyncratic daily sd; the same values as the daily residual and seasonality batteries, pinned
# here so a rerun of those does not move this gate silently). A change needs a rerun.
GATE_STATIC_SD = 0.06
GATE_MARKET_MEAN = 0.04

# The synthetic volume generator (log volume, one [S, m] panel per cell). Declared before any block.
VOLUME_NAME_SD = 0.5  # per-name level of log volume, N(0, VOLUME_NAME_SD)
VOLUME_PHI = 0.9  # AR(1) persistence of the per-name and the market log volume factors
VOLUME_IDIO_SD = 0.3  # stationary sd of the per-name AR(1) component
VOLUME_MARKET_SD = 0.2  # stationary sd of the market-wide AR(1) component
VOLUME_ABS_LOADING = (
    0.15  # log volume on |u| of the same session (the dependence the stage removes)
)
VOLUME_LAG_ABS_LOADING = 0.15  # log volume on |u| of the previous session (volume follows moves)
VOLUME_NOISE_SD = 0.2  # iid log noise (Student t4 in the hostile cells)
HOLE_FRACTION = 0.01  # hostile cells: share of name-days with no volume (NaN, never filled); 0.05 leaves V2 mostly undefined (0.95^5 of the short means finite, 37 of 46 needed)
STEP_FRACTION = 0.3  # hostile cells: share of names with one permanent level step in log volume
STEP_SIZE = math.log(8.0)  # a basis-sized step, the worst case a rank window can see
CONVEX_LOADING = 0.3  # stress cell: log volume on |u|^2 (a dependence a linear stage cannot remove)
STRESS_PHI = 0.99  # stress cell: near-unit-root volume persistence
_VOLUME_STREAM = 1  # SeedSequence stream of the volume generator, apart from the return panel's


@dataclasses.dataclass(frozen=True)
class VolumeScenario(daily.DailyScenario):
    names: int = NAMES
    volume_phi: float = VOLUME_PHI
    volume_t4: bool = False  # Student t4 volume noise
    hole_fraction: float = 0.0
    step_fraction: float = 0.0
    convex: bool = False  # the |u|^2 term


DIAGNOSTIC_CELLS = frozenset({"volume_convex_stress", "volume_unit_root_stress"})


@functools.lru_cache(maxsize=1)
def _spec():
    return load_spec_from_file(_REPO_ROOT / SPEC_PATH, root=_REPO_ROOT).model


def members() -> tuple[tuple[str, object, dict, int], ...]:
    """(name, function, params, slot history) of every registered member, in spec order."""
    return tuple(
        (m.name, resolve_member(m.signal), dict(m.params), m.slot_history_sessions)
        for m in _spec().members
    )


def _ar1(rng: np.random.Generator, shape: tuple[int, int], phi: float, sd: float) -> np.ndarray:
    """[S, m] stationary AR(1) with marginal sd `sd`, started from its stationary law."""
    s_n, m = shape
    innovation = sd * math.sqrt(1.0 - phi * phi) * rng.standard_normal(shape)
    out = np.empty(shape)
    out[0] = sd * rng.standard_normal(m)
    for d in range(1, s_n):
        out[d] = phi * out[d - 1] + innovation[d]
    return out


def synthetic_volume(sc: VolumeScenario, resid: np.ndarray, seed: int) -> np.ndarray:
    """[S, m] share volume for one H0 panel: lognormal level, persistent per-name and market
    components, a dependence on the move sizes |u|, optional heavy-tailed noise, holes and level
    steps. NaN wherever the return is missing (an unlisted name has no volume) and on holes.
    Independent of every future signed return."""
    rng = np.random.default_rng([seed, _VOLUME_STREAM])
    shape = resid.shape
    # The S1 cell hands back residual returns at the price scale (daily._PRICE_SCALE, sd about 0.01);
    # every other cell is at unit sd. The move-size dependence is declared at unit sd.
    move = np.abs(np.nan_to_num(resid)) / (daily._PRICE_SCALE if sc.s1 else 1.0)
    log_v = rng.normal(0.0, VOLUME_NAME_SD, (1, shape[1]))
    log_v = log_v + _ar1(rng, shape, sc.volume_phi, VOLUME_IDIO_SD)
    log_v = log_v + _ar1(rng, (shape[0], 1), sc.volume_phi, VOLUME_MARKET_SD)
    log_v = log_v + VOLUME_ABS_LOADING * move
    log_v[1:] += VOLUME_LAG_ABS_LOADING * move[:-1]
    if sc.convex:
        log_v = log_v + CONVEX_LOADING * move**2
    log_v = log_v + VOLUME_NOISE_SD * null_panels.noise(rng, shape, sc.volume_t4)
    if sc.step_fraction:
        stepped = rng.random(shape[1]) < sc.step_fraction
        at = rng.integers(shape[0] // 4, 3 * shape[0] // 4, shape[1])
        log_v = log_v + np.where(
            stepped[None, :] & (np.arange(shape[0])[:, None] >= at[None, :]), STEP_SIZE, 0.0
        )
    volume = np.exp(log_v)
    gone = ~np.isfinite(resid)
    if sc.hole_fraction:
        gone = gone | (rng.random(shape) < sc.hole_fraction)
    return np.where(gone, np.nan, volume)


def _score(alpha, vol, target, trade, memory: int):
    """R1 and the E17 timing test at the spec's horizon (the daily battery's scorer; inputs_mismatch
    holds its constants equal to the spec's)."""
    return daily._score(alpha, vol, target, trade, memory, _spec().horizon)


def member_arrays(spec, volume: np.ndarray, resid: np.ndarray) -> dict[str, np.ndarray]:
    """What the run computes for a volume spec: each member over the volume field, then the stage
    (`member_sources.orthogonalize_members`) over the S1 residual returns. No membership mask: the
    battery panel has no non-member cells."""
    ranked = member_sources.compute_panel_members(
        spec,
        _VolumePanel(volume),  # type: ignore[arg-type]  # _VolumePanel is the duck-typed Panel the member kernel reads
        bars_per_session=1,
    )
    return member_sources.orthogonalize_members(spec, ranked, resid, bars_per_session=1)


@dataclasses.dataclass(frozen=True)
class _VolumePanel:
    """The one field `member_sources.compute_panel_members` reads from a panel, with no mask."""

    volume: np.ndarray
    member: None = None


def _arms(sc: VolumeScenario, seed: int):
    spec = _spec()
    resid, target = daily.null_panel(sc, seed)
    volume = synthetic_volume(sc, resid, seed)
    window = spec.construction.vol_window_sessions
    vol = trailing_vol(
        resid,
        window_rows=window,
        min_finite=math.ceil(spec.construction.vol_min_finite_fraction * window),
    )
    trade = np.zeros(len(resid), dtype=bool)
    trade[spec.scoring.warmup_sessions :] = True
    registered = members()
    arrays = member_arrays(spec, volume, resid)
    alphas = []
    for name, _fn, _params, memory in registered:
        alphas.append(arrays[name])
        yield name, _score(arrays[name], vol, target, trade, memory)
    book = EqualWeight((1.0,) * len(registered)).combine(np.stack(alphas, axis=2), None)  # type: ignore[arg-type]  # target is unread: fixed signs, no fold
    yield "book_equal", _score(book, vol, target, trade, max(m[3] for m in registered))


def simulate(sc: VolumeScenario, seed: int) -> dict[str, tuple[float, float]]:
    """One H0 panel: {arm: (t, p)} for each member and the equal-weight book."""
    return {name: (r.hac.t, r.hac.p) for name, r in _arms(sc, seed)}


def simulate_series(sc: VolumeScenario, seed: int) -> dict[str, np.ndarray]:
    """One H0 panel: {arm: D_s series} for the StepM battery."""
    return {name: r.series for name, r in _arms(sc, seed)}


def scenarios() -> tuple[VolumeScenario, ...]:
    """The daily residual battery's cells at this battery's sizes with the volume stresses (the
    exact list, in this order, is declared in the registration ledger line)."""
    base = dict(market_mean=GATE_MARKET_MEAN, sessions=SESSIONS, horizon=_spec().horizon)
    other = dict(
        t4_noise=True, factor_sd=0.5, vol_clustering=True, late_fraction=0.4, late_name=True
    )
    volume_hostile = dict(volume_t4=True, hole_fraction=HOLE_FRACTION, step_fraction=STEP_FRACTION)
    return (
        VolumeScenario("volume_gaussian", **base),
        VolumeScenario("volume_static_means", static_sd=GATE_STATIC_SD, **base),
        VolumeScenario("volume_late_listings", late_fraction=0.4, late_name=True, **base),
        VolumeScenario(
            "volume_hostile", static_sd=GATE_STATIC_SD, **base, **other, **volume_hostile  # type: ignore[arg-type]  # mypy cannot type ** of a float-valued dict into the scenario fields
        ),
        VolumeScenario("volume_hostile_no_static", **base, **other, **volume_hostile),  # type: ignore[arg-type]  # mypy cannot type ** of a float-valued dict into the scenario fields
        VolumeScenario(
            "volume_s1_hostile",
            static_sd=GATE_STATIC_SD,
            s1=True,
            **base,
            **other,  # type: ignore[arg-type]  # mypy cannot type ** of a float-valued dict into the scenario fields
            **volume_hostile,  # type: ignore[arg-type]  # volume_hostile keys are the VolumeScenario fields, typed per field
        ),
        VolumeScenario("volume_convex_stress", convex=True, static_sd=GATE_STATIC_SD, **base),
        VolumeScenario(
            "volume_unit_root_stress", volume_phi=STRESS_PHI, static_sd=GATE_STATIC_SD, **base
        ),
    )


def inputs_mismatch(spec) -> list[str]:
    """What this battery simulates that the family spec does not say (battery_pass.make_record
    refuses a bind while this is non-empty): the registered spec at SPEC_PATH must be the spec
    bound, every member must be a volume panel_source with an orthogonalization stage (the battery
    runs exactly that route), and the daily battery's constants its scorer and cells read must equal
    the spec's."""
    out = []
    if battery_pass.battery_input_hash(spec) != battery_pass.battery_input_hash(_spec()):
        out.append(f"inputs differ from {SPEC_PATH}")
    if any(m.panel_source != "volume" or m.orthogonalize is None for m in spec.members):
        out.append("members: every member must be a volume panel_source with orthogonalize")
    c = spec.construction
    checks = {
        "horizon": (daily.HORIZON, spec.horizon),
        "coverage_floor": (daily._COVERAGE_FLOOR, c.coverage_floor),
        "vol_window_sessions": (daily._VOL_WINDOW_SESSIONS, c.vol_window_sessions),
        "warmup_sessions": (daily._WARMUP_SESSIONS, spec.scoring.warmup_sessions),
        "direction": (1, c.direction),
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
