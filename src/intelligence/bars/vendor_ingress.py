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

Every artifact also reports when the vendor answered it
(``answered_at``): raw is last-wins by serve time (fourth review of
191-07, finding 1), so a replayed artifact must carry its own fetch time,
never the load time. The Alpaca pull records no answer time inside the
parquet (todo 535 item 20), so its recorded fetch time is the file's
modification time: the pull writes the file right after the answer, so
the mtime is an upper bound within seconds of it, and it only moves if the
file is rewritten (a copy that does not preserve mtime would make old data
look new; keep artifacts in place).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
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
    grid. ``answered_at`` maps (directory, symbol) to the artifact's
    recorded fetch time (tz-aware UTC). ``artifact_dir`` is the directory
    a caller means when it names none.
    """

    source: str
    timeframe: str
    artifact_dir: Path
    read_artifacts: Callable[[Path, list[str] | None], dict[str, pd.DataFrame]]
    answered_at: Callable[[Path, str], datetime]


def _read_alpaca_5m(
    artifact_dir: Path, symbols: list[str] | None = None
) -> dict[str, pd.DataFrame]:
    """Alpaca's per-symbol parquet artifacts -> canonical 5m frames.

    Alpaca names artifacts ``{SYMBOL}_5Min.parquet`` and stamps the ``t``
    column in UTC; stray sub-minute offsets are floored to the 5m grid so
    they survive the engine's session-grid filter. ``symbols`` restricts the
    read so a subset run holds only its own frames.
    """
    floor = stamp_floor("5m")
    frames: dict[str, pd.DataFrame] = {}
    for path in sorted(artifact_dir.glob("*_5Min.parquet")):
        symbol = path.name.split("_")[0]
        if symbols is not None and symbol not in symbols:
            continue
        frame = pd.read_parquet(path)
        frame["t"] = pd.to_datetime(frame["t"], utc=True).dt.floor(floor)
        frames[symbol] = frame
    return frames


def _alpaca_5m_answered_at(artifact_dir: Path, symbol: str) -> datetime:
    """The recorded fetch time of one Alpaca 5m artifact: its modification time (module
    docstring)."""
    path = artifact_dir / f"{symbol}_5Min.parquet"
    return datetime.fromtimestamp(path.stat().st_mtime, UTC)


ALPACA_5M = VendorIngress(
    source=SOURCE_ALPACA,
    timeframe="5m",
    artifact_dir=Path("data/scratch/alpaca-pilot/depth"),
    read_artifacts=_read_alpaca_5m,
    answered_at=_alpaca_5m_answered_at,
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
