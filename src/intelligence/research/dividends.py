"""Total-return prices for research panels (todo 428). Compute-only numpy.

Stored bars are split-adjusted, not dividend-adjusted: every return spanning an ex-date carries
the dividend as a loss, which biases daily targets, the overnight leg and price-level features on
high-yield names. total_return fixes it at the root, in the prices, so every downstream return
(targets, bar returns, legs) is corrected without special cases.

With y = amount / prior close, each symbol's opens and closes are multiplied by a forward factor
F(s) = product of 1 / (1 - y) over its ex-date sessions up to and including s: the CRSP and
IBKR adjustment convention (IBKR's ADJUSTED_LAST ratio steps by exactly this). When the price
drops by the dividend, the adjusted return across the ex-date is exactly zero; the log return
over (a, b] gains -ln(1 - y) per ex-date in (a, b]. F is constant within a session, so any
return inside a session is unchanged (to floating-point rounding, about 1e-16), and it reads
only past ex-dates, so it adds no lookahead.

Coverage (todo 651) decides known vs unknown per session, one source per session:
- Yahoo covers a session inside its span (and outside its gaps, of which it has none today);
  there the events are the reconciled Yahoo and IBKR facts, as before Massive existed.
- Otherwise Massive covers it if it lies inside the symbol's Massive claim and outside every
  dividend_event_coverage_gap row of that claim; there the events are Massive's only, each with
  yield amount / stored raw prior close, and each unconfirmed (one source), so the spec's
  suspect_yield judges it exactly as it judges a one-source Yahoo or IBKR event.
- A Massive event declared after its ex-date (declared_on, where Massive gives one) was not
  knowable at the session it adjusts, so that session is unknown (temporal_integrity).
- Massive carries cash only: a spin-off or return of capital in a Massive span is not an event
  and stays in the prices as a loss, as it does in a price-only panel. No price-based guard
  replaces it: one cannot tell such a drop from an earnings gap, and splitting dead names at
  their gaps would remove their crash returns from the targets (measurement and decision in
  docs/plans/2026-11-21-massive-dividend-coverage-rule.md, section 6).
A name with no Massive claim keeps its Yahoo-only grid bit for bit.

Unknown dividends are never zero-filled:
- Outside coverage the prices are NaN.
- A covered session after an uncovered one that follows earlier coverage (a hole inside a
  claim) starts a new segment, as a suspect event does below, so no return window spans
  dividends nobody knows.
- An event with a yield above the spec's suspect_yield that only one source reports (a spin-off
  recorded as a dividend, or a vendor error), or a session whose yields reach 1 (no finite
  factor), is not applied and not ignored: the symbol splits
  into a new column from that ex-date on, named `<symbol>~<k>`, like a delisting followed by a
  new listing. No return or feature window can then span the event, nothing before it changes,
  and the cross-section never holds two segments of one name at once. Segment identity lives in
  the name, so anything that joins to the database by symbol must run before total_return.

The grid S0 captures is its own artifact (arrays in the snapshot directory, so the snapshot
hash covers them), not a Panel field: nothing that slices a panel needs to know about it.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path

import numpy as np

from src.intelligence.bars.massive_dividends import SOURCE as MASSIVE
from src.intelligence.research import store
from src.intelligence.research.panel import OPTIONAL_BAR_FIELDS, Panel
from src.intelligence.research.panel import present as present_arrays

SEGMENT_SEPARATOR = "~"
YAHOO = "yahoo"
# The coverage sources S0 reads, in the order dividend_grid applies them (Yahoo's span first,
# Massive's claim on the sessions Yahoo leaves); the reconciled Yahoo/IBKR facts belong to
# the Yahoo coverage.
COVERAGE_SOURCES = (YAHOO, MASSIVE)
_FIELDS = ("div_yield", "div_unconfirmed_yield", "div_covered")


@dataclasses.dataclass(frozen=True)
class DividendGrid:
    """Per-session dividend facts, [S, m] in `symbols` order."""

    symbols: tuple[str, ...]
    div_yield: np.ndarray  # float: the session's ex-date yields compounded, 0 without one
    # float: the largest yield among that session's events only one source reports (0 if none),
    # kept per event so a confirmed event sharing the session is never judged by another's flag
    div_unconfirmed_yield: np.ndarray
    div_covered: np.ndarray  # bool: a coverage source (Yahoo, else Massive) covers the session

    def arrays(self) -> dict[str, np.ndarray]:
        return {name: getattr(self, name) for name in _FIELDS}

    def aligned(self, symbols: tuple[str, ...]) -> DividendGrid:
        """The grid in `symbols` order; a symbol the grid lacks is uncovered everywhere."""
        col = {s: j for j, s in enumerate(self.symbols)}
        idx = np.array([col.get(s, -1) for s in symbols])
        known = idx >= 0

        def take(a: np.ndarray, fill) -> np.ndarray:
            out = np.full((a.shape[0], len(symbols)), fill, dtype=a.dtype)
            out[:, known] = a[:, idx[known]]
            return out

        return DividendGrid(
            symbols,
            take(self.div_yield, 0.0),
            take(self.div_unconfirmed_yield, 0.0),
            take(self.div_covered, False),
        )


def ibkr_rounding_bound(prev_close: float, noise_margin: float = 1.0) -> float:
    """The yield error an IBKR-derived dividend can carry from ADJUSTED_LAST's cent rounding,
    doubled to cover two closes: noise_margin * 0.02 / prev_close. The one definition, shared
    with services/dividend_event_writer.py. With the adjusted prior close (prev_close * ratio) it
    is exact; with the stored prev_close it understates the bound for old events, never
    overstates it."""
    return noise_margin * 0.02 / prev_close


@dataclasses.dataclass(frozen=True)
class DisputeRule:
    """When two sources' yields for one ex-date disagree: beyond both a relative tolerance and
    IBKR's rounding bound. The writer's reconciliation and the research reader share it, with
    the writer's APR values (threshold.dividend_event.source_yield_rel_tolerance and
    .noise_margin), which S0 records in the snapshot manifest."""

    rel_tolerance: float
    noise_margin: float

    def disagree(self, yahoo_yield: float, ibkr_yield: float, ibkr_prev_close: float) -> bool:
        return abs(ibkr_yield - yahoo_yield) > max(
            self.rel_tolerance * yahoo_yield,
            ibkr_rounding_bound(ibkr_prev_close, self.noise_margin),
        )


def resolve_event(
    yahoo_yield: float | None,
    ibkr_yield: float | None,
    ibkr_prev_close: float | None,
    rule: DisputeRule,
) -> tuple[float, float]:
    """(yield to apply, unconfirmed yield) for one ex-date. Pure.

    - Both sources, agreeing under `rule`: Yahoo's declared amount, confirmed (0).
    - Both, disputed (a part-stock special such as WY 2010: Yahoo 63%, IBKR 24%): IBKR's yield,
      which by construction reconciles the IBKR bars we store, and unconfirmed at the larger of
      the two, so the spec's suspect_yield decides whether the symbol splits.
    - One source: its yield, unconfirmed at that yield.
    """
    if yahoo_yield is not None and ibkr_yield is not None:
        if not rule.disagree(yahoo_yield, ibkr_yield, ibkr_prev_close):
            return yahoo_yield, 0.0
        return ibkr_yield, max(ibkr_yield, yahoo_yield)
    y = yahoo_yield if yahoo_yield is not None else ibkr_yield
    if y is None:
        raise ValueError("an event needs at least one source's yield")
    return y, y


@dataclasses.dataclass(frozen=True)
class MassiveYieldEvent:
    """One stored Massive event as research reads it: yield = amount / the stored raw prior
    close (not bars.massive_dividends.MassiveEvent, the writer's amount and record ids)."""

    symbol: str
    ex_date: date
    dividend_yield: float
    declared_on: date | None


Span = tuple[date, date]


def covered_mask(sessions: np.ndarray, span: Span, gaps: Iterable[Span] = ()) -> np.ndarray:
    """Pure: sessions (sorted) inside the closed span [from, to] and outside every closed gap."""
    lo, hi = (np.datetime64(d, "D") for d in span)
    inside = (sessions >= lo) & (sessions <= hi)
    for a, b in gaps:
        start = np.searchsorted(sessions, np.datetime64(a, "D"), side="left")
        inside[start : np.searchsorted(sessions, np.datetime64(b, "D"), side="right")] = False
    return inside


def dividend_grid(
    sessions: np.ndarray,
    symbols: tuple[str, ...],
    coverage: dict[str, Span],
    events: Iterable[tuple[str, date, float | None, float | None, float | None]],
    rule: DisputeRule,
    *,
    gaps: Mapping[tuple[str, str], Sequence[Span]] | None = None,
    massive_coverage: Mapping[str, Span] | None = None,
    massive_events: Sequence[MassiveYieldEvent] = (),
) -> DividendGrid:
    """Pure: per-session dividend facts (module docstring).

    `coverage` holds the Yahoo spans and `events` the reconciled facts (symbol, ex_date,
    yahoo_yield, ibkr_yield, ibkr_prev_close), each resolved by resolve_event; `massive_coverage`
    and `massive_events` the Massive claim and events; `gaps` the holes per (symbol, source).
    A session takes the facts of the first source in COVERAGE_SOURCES that covers it, so
    events of two sources never meet on one session. An ex-date that is not a session (a
    holiday) lands on the next session, where the price drop shows; one outside the panel's
    sessions is ignored. Two events on one session share one prior close, so the drop is
    y1 + y2 and their yields add; the unconfirmed yield keeps the largest event's, not the sum."""
    n_s, m = len(sessions), len(symbols)
    col = {s: j for j, s in enumerate(symbols)}
    gaps = gaps or {}
    div_yield = np.zeros((n_s, m))
    unconfirmed = np.zeros((n_s, m))
    covered = np.zeros((n_s, m), dtype=bool)
    by_massive = np.zeros((n_s, m), dtype=bool)
    for sym, span in coverage.items():
        if sym in col:
            covered[:, col[sym]] = covered_mask(sessions, span, gaps.get((sym, YAHOO), ()))
    for sym, span in (massive_coverage or {}).items():
        if sym in col:
            j = col[sym]
            by_massive[:, j] = covered_mask(sessions, span, gaps.get((sym, MASSIVE), ()))
            by_massive[:, j] &= ~covered[:, j]

    def session_of(sym: str, ex_date: date) -> tuple[int, int] | None:
        ex = np.datetime64(ex_date, "D")
        if sym not in col or not sessions[0] <= ex <= sessions[-1]:
            return None
        return int(np.searchsorted(sessions, ex, side="left")), col[sym]

    massive_at = [(session_of(e.symbol, e.ex_date), e) for e in massive_events]
    for at, e in massive_at:  # declared after its ex-date: not knowable at its session
        if at is not None and e.declared_on is not None and e.declared_on > e.ex_date:
            by_massive[at] = False
    for at, e in massive_at:
        if at is not None and by_massive[at]:
            div_yield[at] += e.dividend_yield
            unconfirmed[at] = max(unconfirmed[at], e.dividend_yield)
    for sym, ex_date, yahoo_y, ibkr_y, ibkr_pc in events:
        at = session_of(sym, ex_date)
        if at is None or by_massive[at]:
            continue
        y, u = resolve_event(yahoo_y, ibkr_y, ibkr_pc, rule)
        div_yield[at] += y
        unconfirmed[at] = max(unconfirmed[at], u)
    covered |= by_massive
    return DividendGrid(symbols, div_yield, unconfirmed, covered)


def no_dividends(panel: Panel) -> DividendGrid:
    """The identity grid (every session covered, no events): total_return then changes nothing.
    For synthetic panels, which carry no dividends."""
    shape = (panel.n_sessions, len(panel.symbols))
    return DividendGrid(panel.symbols, np.zeros(shape), np.zeros(shape), np.ones(shape, dtype=bool))


def load_grid(path: Path) -> DividendGrid | None:
    """The grid S0 saved into a snapshot directory next to its panel, or None if it has none.
    Its symbols are the panel's at capture. The caller verifies the directory hash first."""
    if not (Path(path) / f"{_FIELDS[0]}.npy").exists():
        return None
    symbols = tuple(store.read_meta(path)["symbols"])
    return DividendGrid(symbols, **{n: np.asarray(store.read_array(path, n)) for n in _FIELDS})


def total_return(panel: Panel, grid: DividendGrid, suspect_yield: float) -> Panel:
    """The panel with total-return prices, split at suspect events (module docstring). Symbols
    with no covered session are dropped; the manifest names them and every split."""
    n_s, bps, m = panel.n_sessions, panel.bars_per_session, len(panel.symbols)
    g = grid.aligned(panel.symbols)
    if g.div_yield.shape != (n_s, m):
        raise ValueError(f"dividend grid has {g.div_yield.shape[0]} sessions, panel has {n_s}")
    cov = g.div_covered
    suspect = cov & ((g.div_unconfirmed_yield > suspect_yield) | (g.div_yield >= 1.0))
    use = np.where(cov & ~suspect, g.div_yield, 0.0)
    factor = np.cumprod(1.0 / (1.0 - use), axis=0)[:, None, :]  # [S, 1, m], over bars
    # A covered session right after a hole inside coverage reopens the name as a new segment.
    reentry = np.zeros_like(cov)
    reentry[1:] = cov[1:] & ~cov[:-1] & np.logical_or.accumulate(cov, axis=0)[:-1]
    segment = np.cumsum(suspect | reentry, axis=0)  # [S, m]
    uncovered = ~cov[:, None, :]

    def adjust(prices: np.ndarray, scale: bool) -> np.ndarray:
        out = np.array(prices, dtype=float).reshape(n_s, bps, m)
        if scale:
            out *= factor
        out[np.broadcast_to(uncovered, out.shape)] = np.nan
        return out.reshape(n_s * bps, m)

    # Every price scales by the total-return factor, high and low included (plan 187-15);
    # volume does not.
    fields = {"open": True, "close": True, "volume": False}
    fields.update(dict.fromkeys(present_arrays(panel, OPTIONAL_BAR_FIELDS), True))
    adjusted = {f: adjust(getattr(panel, f), scale) for f, scale in fields.items()}

    # Output columns: (symbol, segment) pairs with a covered session, segments next to their
    # symbol. Only split symbols need a per-column mask.
    take, names, splits, dropped = [], [], [], []
    for j, sym in enumerate(panel.symbols):
        present = np.unique(segment[cov[:, j], j])
        if not len(present):
            dropped.append(sym)
        for k in present.tolist():
            take.append((j, k))
            names.append(sym if k == 0 else f"{sym}{SEGMENT_SEPARATOR}{k}")
            if k:
                first = int(np.argmax(segment[:, j] == k)) * bps
                splits.append([names[-1], str(panel.timestamps[first])])
    if not names:
        raise ValueError("no symbol has a covered session: dividend coverage is missing")
    cols = np.array([j for j, _ in take])
    identity = len(cols) == m and not splits
    out = adjusted if identity else {f: a[:, cols] for f, a in adjusted.items()}
    sector_pit = None
    if panel.sector_pit is not None:
        sector_pit = np.where(cov, panel.sector_pit, -1).astype(np.int16)[:, cols]
    if not identity:
        split_cols = [c for c, (j, _) in enumerate(take) if segment[-1, j] > 0]
        for c in split_cols:
            j, k = take[c]
            other = np.repeat(segment[:, j] != k, bps)
            for a in out.values():
                a[other, c] = np.nan
            if sector_pit is not None:
                sector_pit[segment[:, j] != k, c] = -1
    return dataclasses.replace(
        panel,
        symbols=tuple(names),
        **out,
        **({} if sector_pit is None else {"sector_pit": sector_pit}),
        **({} if panel.member is None else {"member": panel.member[:, cols]}),
        sectors=tuple(panel.sectors[j] for j, _ in take) if panel.sectors else (),
        valid=np.isfinite(out["close"]).any(axis=1),
        manifest={
            **panel.manifest,
            "total_return": {
                "suspect_yield": suspect_yield,
                "events_applied": int((use > 0).sum()),
                "uncovered_symbol_sessions": int((~cov).sum()),
                "splits": splits,
                "symbols_without_coverage": dropped,
            },
        },
    )
