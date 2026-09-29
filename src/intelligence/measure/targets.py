"""IC targets: the research kernel on S0 panels built in symbol chunks (D-18, D-19).

Every target is `panel.forward_returns`, never a return computed here (UD-25). Panels are built
with `end_exclusive = oos_start`; the kernel leaves the last `1 + horizon` rows NaN, so no target
exit row reaches the panel end, which is what makes D-19 hold by construction.

Forward returns are column-independent, so targets of symbol chunks stacked onto the union time
grid equal the targets of one unchunked panel exactly, provided each chunk's rows are adjacent in
the union grid (an interior skipped row would change which open the kernel pairs, so it raises).
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from pathlib import Path

import numpy as np

from src.intelligence.measure.params import MeasureParams
from src.intelligence.research import snapshot
from src.intelligence.research.panel import Panel, forward_returns


def check_horizon(tf: str, bars_per_session: int, horizon: int) -> None:
    """Refuse a horizon that cannot be measured cleanly on this clock."""
    if horizon < 1:
        raise ValueError(f"horizon must be >= 1, got {horizon}")
    if bars_per_session > 1 and horizon >= bars_per_session:
        raise ValueError(
            f"{tf} horizon {horizon} >= {bars_per_session} bars per session crosses a session; "
            "decay beyond a session is measured on the 1d clock (D-18)"
        )


def chunk_targets(panel: Panel, horizon: int) -> np.ndarray:
    """[n, m] kernel targets of one panel; intraday targets never cross a session."""
    check_horizon(panel.tf, panel.bars_per_session, horizon)
    session = panel.session if panel.bars_per_session > 1 else None
    return forward_returns(np.asarray(panel.open), horizon, session=session)


@dataclasses.dataclass(frozen=True)
class TargetStack:
    tf: str
    bars_per_session: int
    timestamps: np.ndarray  # [n] union grid
    symbols: tuple[str, ...]
    session: np.ndarray  # [n] int session index on the union grid
    horizon: int
    targets: np.ndarray  # [n, m] float64
    valid: np.ndarray  # [n] bool, some chunk traded the slot
    end_exclusive: np.datetime64

    def valid_grid(self) -> np.ndarray:
        """[n, m] bool view of `valid` broadcast across symbols."""
        return np.broadcast_to(self.valid[:, None], self.targets.shape)

    def max_target_end(self) -> np.datetime64 | None:
        """Timestamp of the exit-open row of the latest finite target (row t + 1 + horizon)."""
        finite_rows = np.flatnonzero(np.isfinite(self.targets).any(axis=1))
        if finite_rows.size == 0:
            return None
        return self.timestamps[int(finite_rows[-1]) + 1 + self.horizon]


def stride(stack: TargetStack, params: MeasureParams) -> int:
    """Row stride of a pooled cell at this stack's horizon: max(params.min_stride, horizon)."""
    return max(params.min_stride, stack.horizon)


@dataclasses.dataclass(frozen=True)
class StackGrid:
    """The union grid of a panel set, before any target: everything a stack holds that does not
    depend on the horizon (`valid` is the union of the chunks' traded slots)."""

    tf: str
    bars_per_session: int
    timestamps: np.ndarray  # [n] union grid
    symbols: tuple[str, ...]
    session: np.ndarray  # [n] int session index on the union grid
    valid: np.ndarray  # [n] bool, some chunk traded the slot
    end_exclusive: np.datetime64
    chunk_rows: tuple[np.ndarray, ...]  # per panel, its rows on the union grid

    def valid_grid(self) -> np.ndarray:
        """[n, m] bool view of `valid` broadcast across symbols."""
        return np.broadcast_to(self.valid[:, None], (len(self.timestamps), len(self.symbols)))


def stack_grid(panels: list[Panel], end_exclusive: str | np.datetime64) -> StackGrid:
    """Validate the chunks and build their union grid; horizon-free, so a caller measuring
    several horizons builds it once and calls `stack_at_horizon` per horizon."""
    if not panels:
        raise ValueError("no panels to stack")
    tf, bps = panels[0].tf, panels[0].bars_per_session
    for panel in panels:
        if panel.tf != tf or panel.bars_per_session != bps:
            raise ValueError(
                f"chunks disagree on the clock: {panel.tf}/{panel.bars_per_session} "
                f"vs {tf}/{bps}"
            )
    symbols = tuple(s for panel in panels for s in panel.symbols)
    if len(set(symbols)) != len(symbols):
        raise ValueError("a symbol appears in more than one chunk")
    union = np.unique(np.concatenate([np.asarray(p.timestamps) for p in panels]))
    if len(union) % bps:
        raise ValueError(f"union grid of {len(union)} rows is not whole {bps}-bar sessions")
    n = len(union)
    valid = np.zeros(n, dtype=bool)
    chunk_rows = []
    for panel in panels:
        stamps = np.asarray(panel.timestamps)
        expected = union[(union >= stamps[0]) & (union <= stamps[-1])]
        if not np.array_equal(stamps, expected):
            missing = np.setdiff1d(expected, stamps)
            raise ValueError(
                f"chunk starting {panel.symbols[0]} skips grid row {missing[0]} inside its span; "
                "stacking would shift its targets"
            )
        rows = np.searchsorted(union, stamps)
        valid[rows] |= np.asarray(panel.valid)
        chunk_rows.append(rows)
    return StackGrid(
        tf=tf,
        bars_per_session=bps,
        timestamps=union,
        symbols=symbols,
        session=np.repeat(np.arange(n // bps), bps),
        valid=valid,
        end_exclusive=_as_datetime64(end_exclusive),
        chunk_rows=tuple(chunk_rows),
    )


def stack_at_horizon(grid: StackGrid, panels: list[Panel], horizon: int) -> TargetStack:
    """The grid's targets at one horizon: each chunk's kernel targets on its grid rows."""
    targets = np.full((len(grid.timestamps), len(grid.symbols)), np.nan)
    col = 0
    for panel, rows in zip(panels, grid.chunk_rows, strict=True):
        m = len(panel.symbols)
        targets[rows, col : col + m] = chunk_targets(panel, horizon)
        col += m
    return TargetStack(
        tf=grid.tf,
        bars_per_session=grid.bars_per_session,
        timestamps=grid.timestamps,
        symbols=grid.symbols,
        session=grid.session,
        horizon=horizon,
        targets=targets,
        valid=grid.valid,
        end_exclusive=grid.end_exclusive,
    )


def stack_targets(
    panels: list[Panel], horizon: int, end_exclusive: str | np.datetime64
) -> TargetStack:
    return stack_at_horizon(stack_grid(panels, end_exclusive), panels, horizon)


def _as_datetime64(value: str | np.datetime64) -> np.datetime64:
    if isinstance(value, np.datetime64):
        return value
    return np.datetime64(_utc(value).replace(tzinfo=None))


def _utc(text: str) -> datetime:
    return snapshot.utc(datetime.fromisoformat(text))


async def build_target_panels(
    dsn: str,
    out_dir: Path,
    symbols: list[str],
    tf: str,
    start: str,
    end_exclusive: str,
    oos_start: str,
    params: MeasureParams,
) -> list[Path]:
    """Build one read-only S0 panel per symbol chunk; returns the panel paths.

    The caller passes `end_exclusive = oos_start` (read from `alpha.validation.oos_start`). That
    is what makes D-19 hold by construction: the kernel leaves the last `1 + horizon` rows NaN,
    so no target window reaches oos_start. Later than oos_start is refused before any fetch
    (S0 refuses again).
    """
    if _utc(end_exclusive) > _utc(oos_start):
        raise ValueError(f"end_exclusive {end_exclusive} is later than oos_start {oos_start}")
    ordered = sorted(symbols)
    size = params.symbol_chunk_size
    paths: list[Path] = []
    for i in range(0, len(ordered), size):
        paths.append(
            await snapshot.build_panel(
                dsn,
                out_dir,
                symbols=ordered[i : i + size],
                tf=tf,
                start=start,
                end_exclusive=end_exclusive,
            )
        )
    return paths
