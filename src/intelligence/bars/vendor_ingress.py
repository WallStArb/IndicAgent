"""Vendor seam between a fetch artifact and the canonical ingress frame.

One entry per (vendor, timeframe) pair that turns that vendor's on-disk
artifact into the canonical ``t, o, h, l, c, v`` frame the load engine
(``services/bar_load.load_series``) reads. Everything downstream of this
seam is vendor-blind: the vendor travels in the row tuples' source column
via the policy, never in the frame's shape.

A vendor addition is one ``VendorIngress`` row here plus its SOURCE_/
ROUTE_ constants in ``sources.py``; no new loader script, no new write
path. The fetch stage stays vendor-owned (IBKR pacing and 2FA recovery,
Alpaca parquet pulls) and is deliberately not unified behind this seam.

Pure with respect to the database: artifact paths in, frames out. The
5min/1min stamp floor derives from the timeframe's own vocabulary, not a
tunable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.intelligence.bars.sources import SOURCE_ALPACA

#: Vendor stamp floors by timeframe vocabulary (a statistic definition of
#: the grid, not an APR tunable).
_STAMP_FLOOR: dict[str, str] = {"1m": "1min", "5m": "5min"}


@dataclass(frozen=True)
class VendorIngress:
    """One (vendor, timeframe) artifact reader.

    ``read_artifacts`` maps an artifact directory to ``{symbol: frame}``
    with the canonical columns and UTC stamps floored to the timeframe
    grid. ``artifact_dir`` is the directory a caller means when it names
    none.
    """

    source: str
    timeframe: str
    artifact_dir: Path
    read_artifacts: Callable[[Path], dict[str, pd.DataFrame]]


def _read_alpaca_5m(artifact_dir: Path) -> dict[str, pd.DataFrame]:
    """Alpaca's per-symbol parquet artifacts -> canonical 5m frames.

    Alpaca names artifacts ``{SYMBOL}_5Min.parquet`` and stamps the ``t``
    column in UTC; stray sub-minute offsets are floored to the 5m grid so
    they survive the engine's session-grid filter.
    """
    frames: dict[str, pd.DataFrame] = {}
    for path in sorted(artifact_dir.glob("*_5Min.parquet")):
        frame = pd.read_parquet(path)
        frame["t"] = pd.to_datetime(frame["t"], utc=True).dt.floor("5min")
        frames[path.name.split("_")[0]] = frame
    return frames


ALPACA_5M = VendorIngress(
    source=SOURCE_ALPACA,
    timeframe="5m",
    artifact_dir=Path("data/scratch/alpaca-pilot/depth"),
    read_artifacts=_read_alpaca_5m,
)

_INGRESSES: dict[tuple[str, str], VendorIngress] = {
    (ALPACA_5M.source, ALPACA_5M.timeframe): ALPACA_5M,
}


def vendor_ingress(source: str, timeframe: str) -> VendorIngress:
    """Resolve the ingress for a (vendor, timeframe) pair, or raise."""
    try:
        return _INGRESSES[(source, timeframe)]
    except KeyError:
        known = sorted(f"{v.source}/{v.timeframe}" for v in _INGRESSES.values())
        raise ValueError(f"no vendor ingress for {source}/{timeframe}; known: {known}") from None


def stamp_floor(timeframe: str) -> str:
    """The vendor stamp floor for a timeframe vocabulary, or raise."""
    return _STAMP_FLOOR[timeframe]
