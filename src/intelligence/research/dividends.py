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

Unknown dividends are never zero-filled:
- Outside the symbol's Yahoo coverage the prices are NaN.
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
from collections.abc import Iterable
from datetime import date
from pathlib import Path

import numpy as np

from src.intelligence.research import store
from src.intelligence.research.panel import Panel

SEGMENT_SEPARATOR = "~"
_FIELDS = ("div_yield", "div_unconfirmed_yield", "div_covered")


@dataclasses.dataclass(frozen=True)
class DividendGrid:
    """Per-session dividend facts, [S, m] in `symbols` order."""

    symbols: tuple[str, ...]
    div_yield: np.ndarray  # float: the session's ex-date yields compounded, 0 without one
    # float: the largest yield among that session's events only one source reports (0 if none),
    # kept per event so a confirmed event sharing the session is never judged by another's flag
    div_unconfirmed_yield: np.ndarray
    div_covered: np.ndarray  # bool: the session lies inside the symbol's Yahoo coverage

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


def dividend_grid(
    sessions: np.ndarray,
    symbols: tuple[str, ...],
    coverage: dict[str, tuple[date, date]],
    events: Iterable[tuple[str, date, float, bool]],
) -> DividendGrid:
    """Pure: per-session dividend facts from Yahoo coverage spans and reconciled events
    (symbol, ex_date, yield, single_source). An ex-date that is not a session (a holiday) lands
    on the next session, where the price drop shows; one outside the panel's sessions is
    ignored. Two events on one session compound; the unconfirmed yield keeps the largest
    single-source event of the session, not the compound."""
    n_s, m = len(sessions), len(symbols)
    col = {s: j for j, s in enumerate(symbols)}
    div_yield = np.zeros((n_s, m))
    unconfirmed = np.zeros((n_s, m))
    covered = np.zeros((n_s, m), dtype=bool)
    for sym, (lo, hi) in coverage.items():
        if sym in col:
            covered[:, col[sym]] = (sessions >= np.datetime64(lo, "D")) & (
                sessions <= np.datetime64(hi, "D")
            )
    for sym, ex_date, y, single_source in events:
        ex = np.datetime64(ex_date, "D")
        if sym not in col or not sessions[0] <= ex <= sessions[-1]:
            continue
        k, j = int(np.searchsorted(sessions, ex, side="left")), col[sym]
        div_yield[k, j] = (1.0 + div_yield[k, j]) * (1.0 + y) - 1.0
        if single_source:
            unconfirmed[k, j] = max(unconfirmed[k, j], y)
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
    segment = np.cumsum(suspect, axis=0)  # [S, m]
    uncovered = ~cov[:, None, :]

    def adjust(prices: np.ndarray, scale: bool) -> np.ndarray:
        out = np.array(prices, dtype=float).reshape(n_s, bps, m)
        if scale:
            out *= factor
        out[np.broadcast_to(uncovered, out.shape)] = np.nan
        return out.reshape(n_s * bps, m)

    fields = {"open": True, "close": True, "volume": False}
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
    if not identity:
        split_cols = [c for c, (j, _) in enumerate(take) if segment[-1, j] > 0]
        for c in split_cols:
            j, k = take[c]
            other = np.repeat(segment[:, j] != k, bps)
            for a in out.values():
                a[other, c] = np.nan
    return dataclasses.replace(
        panel,
        symbols=tuple(names),
        **out,
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
