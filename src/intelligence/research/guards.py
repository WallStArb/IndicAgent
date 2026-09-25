"""S3 guards: mechanical checks a signal passes before S5 sees it (research architecture 3.3).

Each guard raises GuardFailure, a verdict on the signal that the ledger records; a failed guard
produces no evidence. Calling a guard wrongly (mismatched shapes) raises EvaluatorMisuse
instead, so a caller's bug never becomes a recorded failure of the signal. run_guards is the
entry point for a signal source; the functions below it are for targets and residualized
signals, which have no SignalSource.

- causality_probe: output at row t is bit-identical when every row after t + reach is replaced,
  once with NaN and once with per-cell random rescaling (a uniform rescale would hide a leak
  built from a ratio of future prices). reach is 0 for signals (S2) and factor-residualized
  signals (S4), fwd_span(horizon) for targets (S1), whose window legitimately reads ahead.
- memory_check: a one-row price shock moves the output no further ahead than the declared
  memory. Declared memory is the contract; this only checks it, because a threshold signal can
  hide memory from a small shock and a recursive filter never decays to exactly zero.
- integrity: no inf, no alpha where the row's own close is missing, no bar with non-positive
  volume (research reads market_data_ohlcv_tradeable, so a zero-volume bar means a panel built
  off the raw table), and per-row coverage reported.
- causality_probe_array, memory_check_array: the same two probes over a plain array (D-25).
  On the real panel S1 takes minutes per call, so recomputing it inside every probe of every
  member would take hours; the runner probes S1 once on a bounded sub-panel and probes the
  members on the fixed, full-size S1 residual array with these. The memory shock is additive
  (the array holds returns), SHOCK_SDS of each column's own standard deviation.
- require_testable: synthetic power at the declared effect is at least 50% (evidence
  framework section 6, E16). Only book tests call it (D-21).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

import numpy as np

from src.intelligence.research.evaluate import EvaluatorMisuse
from src.intelligence.research.panel import _PRICE_FIELDS, Panel
from src.intelligence.research.signals import SignalSource

# Evidence framework section 6 (methodology-change-ledger E15): a test below this synthetic
# power spends budget without a chance of passing. A decision rule, not a tunable.
MIN_POWER = 0.5
# Output change that counts as "moved", as a fraction of the output's overall standard
# deviation: the 1e-4 impulse-response cut signals.py uses to declare a recursive filter's
# memory.
MEMORY_TOLERANCE = 1e-4
# Size of the memory check's one-row shock, in each symbol's own log-return standard deviations.
SHOCK_SDS = 5.0

PanelFn = Callable[[Panel], np.ndarray]


class GuardFailure(Exception):
    """A signal, target or panel failed an S3 guard. No evidence may be produced from it."""


@dataclasses.dataclass(frozen=True)
class IntegrityReport:
    coverage: np.ndarray  # [n], finite alpha / finite close per row; NaN where no close
    volume_checked: bool  # False when the panel carries no volume (synthetic panels)


@dataclasses.dataclass(frozen=True)
class GuardReport:
    probe_rows: np.ndarray
    memory_reach: int  # furthest measured reach, <= the source's declared memory
    integrity: IntegrityReport


def run_guards(
    source: SignalSource, panel: Panel, *, seed: int, n_random: int, max_rows: int
) -> GuardReport:
    """All S3 guards for a signal source, in order; raises GuardFailure on the first failure."""
    # Integrity first: a broken value (inf) must fail as itself, not as a leak downstream.
    report = integrity(panel, source.compute(panel))
    rows = probe_rows(panel, n_random=n_random, seed=seed, max_rows=max_rows)
    causality_probe(source.compute, panel, rows, seed=seed)
    # A shock's reach is only fully visible when `memory` rows follow it.
    shock_rows = rows[rows < len(panel.timestamps) - source.memory - 1]
    reach = memory_check(source.compute, panel, shock_rows, declared=source.memory)
    return GuardReport(probe_rows=rows, memory_reach=reach, integrity=report)


def probe_rows(panel: Panel, *, n_random: int, seed: int, max_rows: int) -> np.ndarray:
    """Rows to probe: every session's last bar at a month end, the last traded bar of every
    session with an untraded slot (half days), each symbol's first and last bar with a close,
    plus n_random uniform rows. Deterministic rows are thinned evenly to fit max_rows."""
    if n_random > max_rows:
        raise EvaluatorMisuse(f"n_random {n_random} exceeds max_rows {max_rows}")
    n, bps = len(panel.timestamps), panel.bars_per_session
    last_bar = np.arange(bps - 1, n, bps)
    month = panel.timestamps[last_bar].astype("datetime64[M]")
    month_end = last_bar[np.append(month[1:] != month[:-1], True)]

    finite = np.isfinite(panel.close)
    traded = finite.any(axis=1).reshape(-1, bps)
    short = np.flatnonzero(~panel.valid.reshape(-1, bps).all(axis=1) & traded.any(axis=1))
    half_day = short * bps + (bps - 1 - traded[short, ::-1].argmax(axis=1))

    listed = finite.any(axis=0)
    first = finite.argmax(axis=0)[listed]
    last = (n - 1 - finite[::-1].argmax(axis=0))[listed]

    fixed = np.unique(np.concatenate([month_end, half_day, first, last]))
    budget = max(max_rows - n_random, 0)
    if len(fixed) > budget:
        fixed = fixed[np.linspace(0, len(fixed) - 1, budget).round().astype(np.int64)]
    random = np.random.default_rng(seed).integers(0, n, n_random)
    return np.unique(np.concatenate([fixed, random]).astype(np.int64))


def _working_copy(panel: Panel) -> tuple[Panel, dict[str, np.ndarray]]:
    """A panel over copies of the price fields, and those copies, for editing in place."""
    work = {name: getattr(panel, name).copy() for name in _PRICE_FIELDS}
    return dataclasses.replace(panel, **work), work


def _moved(out: np.ndarray, base: np.ndarray, base_nan: np.ndarray, tol: float) -> np.ndarray:
    """Elementwise: moved by more than tol, or NaN on exactly one side. Equal values, infinite
    ones included, never count as moved."""
    with np.errstate(invalid="ignore"):
        return ~((out == base) | (np.abs(out - base) <= tol) | (base_nan & np.isnan(out)))


def causality_probe(fn: PanelFn, panel: Panel, rows: np.ndarray, *, seed: int, reach: int = 0):
    """Raise unless fn(panel)[:t + 1] is unchanged when rows after t + reach are replaced."""
    base = fn(panel)
    base_nan = np.isnan(base)
    rng = np.random.default_rng(seed)
    for fill in ("nan", "rescale"):
        probed, work = _working_copy(panel)
        filled_from = len(panel.timestamps)
        # Descending t: rows already replaced for a later t stay replaced for an earlier one.
        for t in np.sort(rows)[::-1]:
            cut = int(t) + reach + 1
            if cut < filled_from:
                for name, arr in work.items():
                    block = arr[cut:filled_from]
                    if fill == "nan":
                        block[:] = np.nan
                    else:
                        block *= np.exp(rng.normal(0.0, 0.5, block.shape))
                filled_from = cut
            out = fn(probed)
            head = slice(0, int(t) + 1)
            moved = _moved(out[head], base[head], base_nan[head], tol=0.0)
            if moved.any():
                raise GuardFailure(
                    f"lookahead: output at row {int(np.argwhere(moved)[0][0])} changed when rows "
                    f"after {int(t) + reach} were replaced ({fill})"
                )


def memory_check(fn: PanelFn, panel: Panel, rows: np.ndarray, *, declared: int) -> int:
    """Shock every symbol's prices at row t by SHOCK_SDS of its own log-return sd and return
    the furthest reach (rows after t) at which the output moves. Raise if an earlier row moves
    (lookahead) or the reach exceeds `declared`. Rows need `declared` rows after them for the
    full reach to be visible."""
    base = fn(panel)
    base_nan = np.isnan(base)
    scale = float(np.nanstd(base))
    tol = MEMORY_TOLERANCE * scale if np.isfinite(scale) and scale > 0 else 0.0
    with np.errstate(invalid="ignore", divide="ignore"):
        sd = np.nanstd(np.diff(np.log(panel.close), axis=0), axis=0)
    shock = np.exp(SHOCK_SDS * np.where(np.isfinite(sd) & (sd > 0), sd, 0.01))
    probed, work = _working_copy(panel)
    furthest = 0
    for t in rows:
        t = int(t)
        for arr in work.values():
            arr[t] *= shock
        out = fn(probed)
        for name, arr in work.items():
            arr[t] = getattr(panel, name)[t]
        moved = _moved(out, base, base_nan, tol).reshape(len(out), -1).any(axis=1)
        changed = np.flatnonzero(moved)
        if len(changed) == 0:
            continue
        if changed[0] < t:
            raise GuardFailure(f"lookahead: a shock at row {t} moved row {changed[0]}")
        reach = int(changed[-1]) - t
        if reach > declared:
            raise GuardFailure(
                f"memory: a shock at row {t} moved row {changed[-1]}, reach {reach} > "
                f"declared {declared}"
            )
        furthest = max(furthest, reach)
    return furthest


ArrayFn = Callable[[np.ndarray], np.ndarray]


def causality_probe_array(
    fn: ArrayFn, x: np.ndarray, rows: np.ndarray, *, seed: int, reach: int = 0
) -> None:
    """causality_probe over an array input: raise unless fn(x)[:t + 1] is unchanged when rows
    after t + reach are replaced, once with NaN and once with per-cell random rescaling."""
    base = fn(x)
    base_nan = np.isnan(base)
    rng = np.random.default_rng(seed)
    for fill in ("nan", "rescale"):
        work = x.astype(float, copy=True)
        filled_from = len(x)
        for t in np.sort(rows)[::-1]:
            cut = int(t) + reach + 1
            if cut < filled_from:
                block = work[cut:filled_from]
                if fill == "nan":
                    block[:] = np.nan
                else:
                    block *= np.exp(rng.normal(0.0, 0.5, block.shape))
                filled_from = cut
            out = fn(work)
            head = slice(0, int(t) + 1)
            moved = _moved(out[head], base[head], base_nan[head], tol=0.0)
            if moved.any():
                raise GuardFailure(
                    f"lookahead: output at row {int(np.argwhere(moved)[0][0])} changed when rows "
                    f"after {int(t) + reach} were replaced ({fill})"
                )


def memory_check_array(fn: ArrayFn, x: np.ndarray, rows: np.ndarray, *, declared: int) -> int:
    """memory_check over an array of returns: add SHOCK_SDS of each column's sd at row t and
    return the furthest reach at which the output moves; raise on lookahead or a reach beyond
    `declared`."""
    base = fn(x)
    base_nan = np.isnan(base)
    scale = float(np.nanstd(base))
    tol = MEMORY_TOLERANCE * scale if np.isfinite(scale) and scale > 0 else 0.0
    with np.errstate(invalid="ignore"):
        sd = np.nanstd(x, axis=0)
    overall = float(np.nanstd(x))
    shock = SHOCK_SDS * np.where(np.isfinite(sd) & (sd > 0), sd, overall)
    work = x.astype(float, copy=True)
    furthest = 0
    for t in rows:
        t = int(t)
        work[t] = x[t] + shock
        out = fn(work)
        work[t] = x[t]
        moved = _moved(out, base, base_nan, tol).reshape(len(out), -1).any(axis=1)
        changed = np.flatnonzero(moved)
        if len(changed) == 0:
            continue
        if changed[0] < t:
            raise GuardFailure(f"lookahead: a shock at row {t} moved row {changed[0]}")
        reach = int(changed[-1]) - t
        if reach > declared:
            raise GuardFailure(
                f"memory: a shock at row {t} moved row {changed[-1]}, reach {reach} > "
                f"declared {declared}"
            )
        furthest = max(furthest, reach)
    return furthest


def integrity(panel: Panel, alpha: np.ndarray) -> IntegrityReport:
    if alpha.shape != panel.close.shape:
        raise EvaluatorMisuse(f"alpha shape {alpha.shape} != panel {panel.close.shape}")
    n_inf = int(np.isinf(alpha).sum())
    if n_inf:
        raise GuardFailure(f"{n_inf} infinite alpha values")
    close_ok = np.isfinite(panel.close)
    alpha_ok = np.isfinite(alpha)
    orphan = alpha_ok & ~close_ok
    if orphan.any():
        r, c = np.argwhere(orphan)[0]
        raise GuardFailure(
            f"{int(orphan.sum())} alpha values on bars with no close (first row {r}, "
            f"{panel.symbols[c]}): a missing input must give no position"
        )
    volume_checked = bool(np.isfinite(panel.volume[close_ok]).any())
    if volume_checked:
        bad = close_ok & ~(panel.volume > 0)
        if bad.any():
            raise GuardFailure(
                f"{int(bad.sum())} bars with a close but no positive volume: the panel did not "
                "come from market_data_ohlcv_tradeable"
            )
    n_close = close_ok.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        coverage = np.where(n_close > 0, alpha_ok.sum(axis=1) / n_close, np.nan)
    return IntegrityReport(coverage=coverage, volume_checked=volume_checked)


def require_testable(*, power: float) -> None:
    """A book test runs only when its synthetic power at the pre-declared effect, through the
    same statistic and bar, is at least MIN_POWER (evidence framework section 6,
    methodology-change-ledger E16 (d): the shift-count floor it replaced is gone with the
    shift null). Evidence runs are never refused on power (D-21)."""
    if not power >= MIN_POWER:
        raise GuardFailure(f"underpowered: synthetic power {power:.2f} < {MIN_POWER}")
