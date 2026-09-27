"""E17's per-family static-size precondition (methodology-change-ledger E17, owner option C;
todo 447).

E17's H0 battery holds size with its gating cells at twice the static effect sizes measured on
families 1 and 2; above that, static means with volatility clustering oversize the tail. So the
gate is checked, not assumed: before a family's statistic, its own sizes are measured on the
panel the run scores, and a family above its battery's gated sizes is refused.

Measurement, by the method that produced the battery's sizes (on family 1's panel it reproduces
the recorded static 0.019, split-half 0.21 and raw time-of-day rms 0.0096): raw returns, not S1
residuals.

- Cell returns: `panel.bar_returns` of the analysis panel (after the members' universe filter,
  total return and any transform; split segments `<sym>~<k>` are separate names), summed over
  each cell's `cell_rows` rows (NaN if any is missing), sessions from `trading_start` on.
- e = cell return minus its cross-sectional mean, where at least `coverage_floor` names are
  finite. sd_j: pooled sd of e over sessions and names for cell j (the idiosyncratic sd).
- Static: per (cell, name), mean(e) / sd_j; the true sd across names is
  sqrt(var(means) - mean(sampling variances)), clipped at 0.
- Time of day: per cell, the mean over sessions of the raw cross-sectional mean, over sd_j, and
  its standard error. The gated size is its magnitude net of sampling noise,
  sqrt(mean^2 - se^2) clipped at 0, the same correction the static sd gets. The raw value is
  recorded too; it is what produced the battery's 0.0096, and it is mostly noise (family 1: raw
  rms 0.0096, per-slot se 0.005 to 0.011, net 0.0036), enough to refuse a short panel with no
  time-of-day effect at all.

A battery gates either one pooled value (family 1: the same static sd and time-of-day sd drawn
for every slot; pooled = sqrt of the mean net variance over cells) or one value per cell
(family 2's legs). Compute-only numpy, no I/O.
"""

from __future__ import annotations

import dataclasses
import importlib
import math
import warnings

import numpy as np

from src.intelligence.research.panel import Panel, bar_returns

METHOD = "raw_cross_sectionally_demeaned_cell_returns"


@dataclasses.dataclass(frozen=True)
class StaticGate:
    """A battery's gated sizes, derived from its gating cells (never typed twice)."""

    battery: str  # module name
    cell_rows: int  # analysis-panel rows summed into one cell (a slot or a leg)
    static_sd: tuple[float, ...]  # one pooled value, or one per cell
    time_of_day: tuple[float, ...]  # one pooled rms, or one absolute mean per cell


@dataclasses.dataclass(frozen=True)
class StaticSizes:
    per_cell_static_sd: tuple[float, ...]
    per_cell_time_of_day: tuple[float, ...]  # raw signed mean, idiosyncratic sd units
    per_cell_time_of_day_se: tuple[float, ...]
    split_half_corr: float
    sessions: int
    names: int

    def _tod_net_var(self) -> np.ndarray:
        return np.square(self.per_cell_time_of_day) - np.square(self.per_cell_time_of_day_se)

    def per_cell_time_of_day_net(self) -> tuple[float, ...]:
        return tuple(np.sqrt(np.clip(self._tod_net_var(), 0.0, None)).tolist())

    def pooled_static_sd(self) -> float:
        return math.sqrt(float(np.mean(np.square(self.per_cell_static_sd))))

    def pooled_time_of_day(self) -> float:
        return math.sqrt(max(float(np.mean(self._tod_net_var())), 0.0))

    def pooled_time_of_day_raw(self) -> float:
        return math.sqrt(float(np.mean(np.square(self.per_cell_time_of_day))))


def gate_for(family_module) -> StaticGate:
    """The gate of the battery a family module names in NULL_BATTERY; AttributeError when it
    names none (option C: such a family needs a battery at its own sizes first)."""
    return importlib.import_module(family_module.NULL_BATTERY).static_gate()


def gate_from_cells(
    battery: str,
    cell_rows: int,
    cells,
    diagnostic: frozenset[str],
    *,
    static,
    time_of_day,
) -> StaticGate:
    """Elementwise max over the battery's gating cells of `static(cell)` and `time_of_day(cell)`
    (each a tuple). The gate is what every gating cell was shown to hold at; with no stress in
    any gating cell the value is 0 and any measured size refuses."""
    gating = [c for c in cells if c.name not in diagnostic]
    return StaticGate(
        battery=battery,
        cell_rows=cell_rows,
        static_sd=tuple(np.max([static(c) for c in gating], axis=0).tolist()),
        time_of_day=tuple(np.max([time_of_day(c) for c in gating], axis=0).tolist()),
    )


def _cell_returns(panel: Panel, cell_rows: int, trading_start: np.datetime64) -> np.ndarray:
    bps = panel.bars_per_session
    if bps % cell_rows:
        raise ValueError(f"{bps} rows per session is not a whole number of {cell_rows}-row cells")
    n_s, m = panel.n_sessions, len(panel.symbols)
    r = bar_returns(panel).reshape(n_s, bps // cell_rows, cell_rows, m).sum(axis=2)
    days = np.asarray(panel.timestamps).reshape(n_s, bps)[:, 0].astype("datetime64[D]")
    return r[days >= trading_start]


def measure(panel: Panel, *, cell_rows: int, trading_start, coverage_floor: int) -> StaticSizes:
    """The family's static and time-of-day sizes on its analysis panel (module docstring)."""
    r = _cell_returns(panel, cell_rows, np.datetime64(trading_start, "D"))
    with warnings.catch_warnings(), np.errstate(invalid="ignore", divide="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)  # empty cells stay NaN
        count = np.isfinite(r).sum(axis=2, keepdims=True)
        xs_mean = np.where(count >= coverage_floor, np.nanmean(r, axis=2, keepdims=True), np.nan)
        e = r - xs_mean
        sd = np.nanstd(e, axis=(0, 2))  # [J]
        n = np.isfinite(e).sum(axis=0)  # [J, m]
        ok = n >= 2
        means = np.where(ok, np.nanmean(e, axis=0), np.nan) / sd[:, None]
        sampling = np.where(ok, np.nanvar(e, axis=0, ddof=1) / n, np.nan) / sd[:, None] ** 2
        true_var = np.nanvar(means, axis=1) - np.nanmean(sampling, axis=1)
        static = np.sqrt(np.clip(true_var, 0.0, None))
        market = xs_mean[..., 0]  # [S, J]
        tod = np.nanmean(market, axis=0) / sd
        tod_se = np.nanstd(market, axis=0, ddof=1) / np.sqrt(np.isfinite(market).sum(0)) / sd
        half = len(e) // 2
        a = np.nanmean(e[:half], axis=0) / sd[:, None]
        b = np.nanmean(e[half:], axis=0) / sd[:, None]
    both = np.isfinite(a) & np.isfinite(b)
    split = float(np.corrcoef(a[both], b[both])[0, 1]) if both.sum() > 2 else float("nan")
    if not (np.isfinite(static).all() and np.isfinite(tod).all() and np.isfinite(tod_se).all()):
        raise ValueError("a cell has too little cross-section to measure its static sizes")
    return StaticSizes(
        per_cell_static_sd=tuple(static.tolist()),
        per_cell_time_of_day=tuple(tod.tolist()),
        per_cell_time_of_day_se=tuple(tod_se.tolist()),
        split_half_corr=split,
        sessions=int(len(r)),
        names=int(np.isfinite(r).any(axis=(0, 1)).sum()),
    )


def exceedances(sizes: StaticSizes, gate: StaticGate) -> list[str]:
    """Each measured size above its gated size, named; empty when the family passes."""
    out = []

    def compare(label: str, gated: tuple[float, ...], pooled: float, per_cell) -> None:
        # A one-value gate is pooled over cells, otherwise one value per cell.
        measured = [pooled] if len(gated) == 1 else per_cell
        for k, (x, g) in enumerate(zip(measured, gated, strict=True)):
            if x > g:
                where = "pooled" if len(gated) == 1 else f"cell {k}"
                out.append(f"{label} ({where}) {x:.4g} > gated {g:.4g}")

    compare("static sd", gate.static_sd, sizes.pooled_static_sd(), sizes.per_cell_static_sd)
    compare(
        "time of day",
        gate.time_of_day,
        sizes.pooled_time_of_day(),
        sizes.per_cell_time_of_day_net(),
    )
    return out


def record(sizes: StaticSizes, gate: StaticGate) -> dict:
    """The evidence record's static_sizes block, with the gate's verdict."""
    problems = exceedances(sizes, gate)
    return {
        "method": METHOD,
        "battery": gate.battery,
        "cell_rows": gate.cell_rows,
        "passes": not problems,
        "exceeds": problems,
        "gate": {"static_sd": list(gate.static_sd), "time_of_day": list(gate.time_of_day)},
        "pooled_static_sd": sizes.pooled_static_sd(),
        "pooled_time_of_day_rms": sizes.pooled_time_of_day(),
        "pooled_time_of_day_rms_raw": sizes.pooled_time_of_day_raw(),
        "per_cell_static_sd": list(sizes.per_cell_static_sd),
        "per_cell_time_of_day_net": list(sizes.per_cell_time_of_day_net()),
        "per_cell_time_of_day": list(sizes.per_cell_time_of_day),
        "per_cell_time_of_day_se": list(sizes.per_cell_time_of_day_se),
        "split_half_corr": sizes.split_half_corr,
        "sessions": sizes.sessions,
        "names": sizes.names,
    }
