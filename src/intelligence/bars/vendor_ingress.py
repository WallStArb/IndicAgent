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
never the load time. The Alpaca pull records the time of its last page's
answer in the parquet's schema metadata (``ANSWERED_AT_KEY``, review of
191-08 M2) through ``write_alpaca_artifact``; a rewrite or copy keeps it.
An artifact written before that has none, and falls back to the file's
modification time, which a rewrite or a copy without preserved mtime moves.
Either stamp is checked against the artifact's newest bar before a load
(``check_answered_at``, APR ``infra.alpaca.artifact_max_answer_lag_hours``):
a stamp at or before the newest bar, or later than it by more than the
bound, is refused, so a re-stamped old artifact cannot pass as a fresh serve.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from src.intelligence.bars.massive_flat import (
    file_trading_date,
    read_day_file,
    read_minute_file,
    session_bounds_ns,
)
from src.intelligence.bars.sources import SOURCE_ALPACA, SOURCE_MASSIVE
from src.intelligence.bars.vendor_kind import (
    ALPACA_RAW_ADJUSTMENT,
    KIND_MASSIVE_1D,
    KIND_MASSIVE_5M,
    alpaca_kind_for_feed,
)

#: Vendor stamp floors by timeframe vocabulary (a statistic definition of
#: the grid, not an APR tunable).
_STAMP_FLOOR: dict[str, str] = {"1m": "1min", "5m": "5min"}
#: Parquet schema-metadata key holding the vendor's answer time (ISO 8601, UTC).
ANSWERED_AT_KEY = b"indicagent.answered_at"


@dataclass(frozen=True)
class VendorIngress:
    """One (vendor, timeframe) artifact reader.

    ``read_artifacts`` maps an artifact directory to ``{symbol: frame}``
    with the canonical columns and UTC stamps floored to the timeframe
    grid. ``answered_at`` maps (directory, symbol) to the artifact's
    recorded fetch time (tz-aware UTC). ``artifact_dir`` is the directory
    a caller means when it names none. ``kind`` is the raw kind the
    artifacts' basis is written under (the pull's feed and adjustment).
    """

    source: str
    timeframe: str
    artifact_dir: Path
    read_artifacts: Callable[[Path, list[str] | None], dict[str, pd.DataFrame]]
    answered_at: Callable[[Path, str], datetime]
    kind: str
    # False for a vendor whose answer time is checked inside ``answered_at`` itself (Massive: the
    # manifest record), so the loader skips the Alpaca-shaped lag bound (``check_answered_at``).
    check_lag: bool = True


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


def write_alpaca_artifact(frame: pd.DataFrame, path: Path, answered_at: datetime) -> None:
    """Write one Alpaca artifact with the vendor's answer time in its schema metadata."""
    if answered_at.tzinfo is None:
        raise ValueError("answered_at must be timezone-aware")
    table = pa.Table.from_pandas(frame, preserve_index=False)
    metadata = dict(table.schema.metadata or {})
    metadata[ANSWERED_AT_KEY] = answered_at.astimezone(UTC).isoformat().encode()
    pq.write_table(table.replace_schema_metadata(metadata), path)


def _alpaca_5m_answered_at(artifact_dir: Path, symbol: str) -> datetime:
    """The recorded fetch time of one Alpaca 5m artifact: the answer time the pull wrote into
    its metadata, else (an artifact written before the stamp existed) its modification time
    (module docstring)."""
    path = artifact_dir / f"{symbol}_5Min.parquet"
    stamp = (pq.read_schema(path).metadata or {}).get(ANSWERED_AT_KEY)
    if stamp is not None:
        answered = datetime.fromisoformat(stamp.decode())
        if answered.tzinfo is None:
            raise ValueError(f"{path}: answered_at metadata {stamp!r} has no timezone")
        return answered.astimezone(UTC)
    return datetime.fromtimestamp(path.stat().st_mtime, UTC)


def check_answered_at(
    answered_at: datetime, frame: pd.DataFrame, *, max_lag: timedelta, where: str
) -> None:
    """Refuse an artifact stamp that cannot be the vendor's answer time: not after the newest
    bar's start, or later than it by more than `max_lag` (a rewritten or copied old artifact).
    An empty frame has nothing to load and passes."""
    if frame.empty:
        return
    newest = pd.Timestamp(frame["t"].max()).to_pydatetime()
    if answered_at <= newest:
        raise ValueError(
            f"{where}: answered_at {answered_at.isoformat()} is not after the newest bar "
            f"{newest.isoformat()}"
        )
    if answered_at - newest > max_lag:
        raise ValueError(
            f"{where}: answered_at {answered_at.isoformat()} is {answered_at - newest} after the "
            f"newest bar {newest.isoformat()} (bound {max_lag}); a rewritten or copied artifact "
            "would pass as a fresh serve"
        )


ALPACA_5M = VendorIngress(
    source=SOURCE_ALPACA,
    timeframe="5m",
    artifact_dir=Path("data/scratch/alpaca-pilot/depth"),
    read_artifacts=_read_alpaca_5m,
    answered_at=_alpaca_5m_answered_at,
    # scripts/research/alpaca_depth_scratch_pull.py pulls feed=sip, adjustment=split
    kind=alpaca_kind_for_feed("sip", ALPACA_RAW_ADJUSTMENT),
)


#: The downloader's manifest (one JSON record per download; the latest record of a key is its
#: current state) and the files root its ``path`` field is relative to.
MASSIVE_MANIFEST = Path("data/massive/manifest/manifest.jsonl")
MASSIVE_FILES_ROOT = Path("data/massive/files")


def massive_day_file(artifact: Path) -> Path:
    """The one day file a Massive ingress call loads. Serve time is per file, not per symbol, so
    a call never spans files: a directory is accepted only when it holds exactly one."""
    if artifact.is_file():
        return artifact
    files = sorted(artifact.rglob("*.csv.gz"))
    if len(files) != 1:
        raise ValueError(
            f"{artifact}: a massive load takes one day file per call, found {len(files)}"
        )
    return files[0]


def manifest_record(day_file: Path, manifest: Path = MASSIVE_MANIFEST) -> dict:
    """The latest manifest record of a day file, matched on its ``dataset/YYYY/MM/name`` path;
    ValueError when the manifest has none. The file bytes are not re-hashed here."""
    wanted = "/".join(day_file.parts[-4:])
    found: dict | None = None
    with manifest.open() as handle:
        for line in handle:
            record = json.loads(line)
            if record["path"] == wanted:
                found = record
    if found is None:
        raise ValueError(f"{day_file}: no manifest record for {wanted}")
    return found


def massive_answered_at(artifact: Path, symbol: str, manifest: Path = MASSIVE_MANIFEST) -> datetime:
    """When the vendor served a day file: the manifest record's LastModified (UTC).

    Fails loudly, never guesses: the record needs an etag and a last_modified, LastModified must
    be after the file's NYSE session close (a file cannot be complete before its day ends) and at
    or before the download. A historical file is legitimately served years after its day, so
    there is no lag bound. ``symbol`` is unused: the answer time belongs to the file."""
    day_file = massive_day_file(artifact)
    record = manifest_record(day_file, manifest)
    if not record.get("etag") or not record.get("last_modified"):
        raise ValueError(f"{day_file}: manifest record has no etag or last_modified")
    served = datetime.fromisoformat(record["last_modified"].replace("Z", "+00:00")).astimezone(UTC)
    downloaded = datetime.fromisoformat(record["downloaded_at"]).astimezone(UTC)
    _open_ns, close_ns = session_bounds_ns(file_trading_date(day_file))
    if served <= datetime.fromtimestamp(close_ns / 1_000_000_000, UTC):
        raise ValueError(f"{day_file}: LastModified {served.isoformat()} is not after the session")
    if served > downloaded:
        raise ValueError(
            f"{day_file}: LastModified {served.isoformat()} is after the download "
            f"{downloaded.isoformat()}"
        )
    return served


def _read_massive_5m(artifact: Path, symbols: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """One Massive minute day file -> canonical 5m frames per symbol, cut to the regular session
    by ``massive_flat``. ``symbols`` restricts the read to a subset run's own names."""
    return read_minute_file(massive_day_file(artifact)).frames(symbols)


def _read_massive_1d(artifact: Path, symbols: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """One Massive day aggregate file as served (unadjusted) -> canonical 1d frames."""
    return read_day_file(massive_day_file(artifact)).frames(symbols)


MASSIVE_5M = VendorIngress(
    source=SOURCE_MASSIVE,
    timeframe="5m",
    artifact_dir=MASSIVE_FILES_ROOT / "minute_aggs_v1",
    read_artifacts=_read_massive_5m,
    answered_at=massive_answered_at,
    kind=KIND_MASSIVE_5M,
    check_lag=False,
)

MASSIVE_1D = VendorIngress(
    source=SOURCE_MASSIVE,
    timeframe="1d",
    artifact_dir=MASSIVE_FILES_ROOT / "day_aggs_v1",
    read_artifacts=_read_massive_1d,
    answered_at=massive_answered_at,
    kind=KIND_MASSIVE_1D,
    check_lag=False,
)

_INGRESSES: dict[tuple[str, str], VendorIngress] = {
    (ALPACA_5M.source, ALPACA_5M.timeframe): ALPACA_5M,
    (MASSIVE_5M.source, MASSIVE_5M.timeframe): MASSIVE_5M,
    (MASSIVE_1D.source, MASSIVE_1D.timeframe): MASSIVE_1D,
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
