#!/usr/bin/env python3
"""Grid lane guard (phase 185 plan 12): keep the D2b grid rewrite off the
symbols a running backfill lane is writing.

A "grid lane" is an infrastructure_run_historical_pipeline.py process whose
--timeframes intersect {5m, 15m, 1h} (or that runs the default full stack,
which includes them). Its symbols must not be derived while it runs: the
derivation would archive/delete a 15m/1h segment the lane is concurrently
rewriting (T-185-12-01), and from plan 12 on the lane itself writes 15m/1h
into the archive, which derivation also touches.

running_lane_symbols() parses `ps -eo args` output and returns the union of
the grid lanes' explicit --symbols plus whether any grid lane runs WITHOUT
--symbols (the nightly's full-stack dispatch, or a dimension-wide run): no
exclude file can scope such a lane, so the caller must stop instead of
narrowing (plan 12: blocked, not failed).

write_exclude_file() writes the one-symbol-per-line file that
services/bar_derivation.py --exclude-symbols-file consumes and returns the
symbol count. The nightly grid stage calls it right before the subprocess.

Read-only over the process table; it never signals a lane. The todo 449
chain's lane script is never edited or killed here.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

# Timeframes whose concurrent writers the derivation must avoid. 5m counts:
# the todo 449 second leg and the full-stack nightly both write it.
_GRID_TFS = frozenset({"5m", "15m", "1h"})
# The pipeline's default stack (no --timeframes): intersects the grid, so a
# process without the flag is a grid lane unless it names 1d only explicitly.
_DEFAULT_TFS = frozenset({"1d", "1h", "15m", "5m", "1m"})
_PIPELINE_MARKER = "infrastructure_run_historical_pipeline.py"


def _arg_value(args: Sequence[str], flag: str) -> str | None:
    """Value of `flag` in a pre-split argv (--flag value or --flag=value)."""
    for i, part in enumerate(args):
        if part == flag and i + 1 < len(args):
            return args[i + 1]
        if part.startswith(f"{flag}="):
            return part.split("=", 1)[1]
    return None


def _lane_symbols(args: Sequence[str]) -> tuple[set[str], bool]:
    """(explicit --symbols, has none) for one pipeline process's argv."""
    raw_tfs = _arg_value(args, "--timeframes")
    tfs = {t.strip() for t in raw_tfs.split(",") if t.strip()} if raw_tfs else set(_DEFAULT_TFS)
    if not (tfs & _GRID_TFS):
        return set(), False
    raw_symbols = _arg_value(args, "--symbols")
    if raw_symbols is None:
        return set(), True
    return {s.strip() for s in raw_symbols.split(",") if s.strip()}, False


def running_lane_symbols(ps_args: str | None = None) -> tuple[frozenset[str], bool]:
    """Symbols a running grid lane is writing, and whether any grid lane runs
    dimension-wide (no --symbols). `ps_args` injects `ps -eo args` output for
    tests; None runs the real process table."""
    if ps_args is None:
        result = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True, check=False)
        ps_args = result.stdout
    symbols: set[str] = set()
    unscoped = False
    for line in ps_args.splitlines():
        if _PIPELINE_MARKER not in line:
            continue
        line_symbols, line_unscoped = _lane_symbols(line.split())
        symbols |= line_symbols
        unscoped = unscoped or line_unscoped
    return frozenset(symbols), unscoped


def write_exclude_file(path: Path, ps_args: str | None = None) -> int:
    """Write the running grid lanes' symbols to `path`, one per line; return
    the count. Refuses (RuntimeError) when a grid lane runs without --symbols:
    the exclude file cannot scope it, so the caller must stop and record a
    blocker rather than derive symbols the lane is writing."""
    symbols, unscoped = running_lane_symbols(ps_args)
    if unscoped:
        raise RuntimeError(
            "a grid-timeframe infrastructure_run_historical_pipeline process is "
            "running without --symbols (dimension-wide): the lane guard cannot "
            "scope it with an exclude file, so the grid rewrite is blocked, not "
            "narrowed. Let the lane finish or stop it deliberately, then retry."
        )
    lines = ["# written by ops_grid_lane_guard: symbols a running grid lane is writing"] + sorted(
        symbols
    )
    path = Path(path)
    path.write_text("\n".join(lines) + "\n")
    return len(symbols)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("path", type=Path, help="exclude file to write")
    args = parser.parse_args(argv)
    try:
        n = write_exclude_file(args.path)
    except RuntimeError as error:
        print(f"REFUSED: {error}", file=sys.stderr)
        return 1
    print(f"{n} symbol(s) excluded from the grid rewrite; wrote {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
