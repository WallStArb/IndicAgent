"""CellSpool: a compute cache of finished cells for one batch unit (todo 668).

A unit that takes hours (an intraday tf of ic_measure) loses all of it when it is killed before
its single `bulk_load`. The spool keeps each finished cell's arrays on disk so a rerun of the same
unit loads them instead of recomputing; the unit's rows are still assembled and written once, by
`bulk_load`, so the spool is never the writer of a result.

The directory is the unit's `batch_key`, which already hashes the code, the APR snapshot, every
input digest and the unit's scope: a changed input or a changed module is a different directory
and an old file is never read. Inside a file the cell's names are stored and compared on load, so
a cell written for another block is a miss. Arrays only (`allow_pickle` is never on), written to
a process-unique temporary name and renamed, so a kill never leaves a half file under a final name
and two writers of one cell write the same bytes (the cell is a deterministic function of the
key). A file that does not read back is a miss and is logged, never a crash: this is a cache.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
import structlog

_logger = structlog.get_logger(__name__)

_NAMES_FIELD = "__names__"
_CELL_FIELD = "__cell__"
_SUFFIX = ".npz"


class CellSpool:
    """The finished cells of one unit, keyed by the unit's batch key."""

    def __init__(self, root: Path, batch_key: str) -> None:
        if not batch_key or "/" in batch_key or batch_key.startswith("."):
            raise ValueError(f"batch key {batch_key!r} is not a directory name")
        self.directory = root / batch_key

    def _path(self, cell: str) -> Path:
        return self.directory / (hashlib.sha256(cell.encode()).hexdigest()[:24] + _SUFFIX)

    def load(self, cell: str, names: Sequence[str]) -> dict[str, np.ndarray] | None:
        """The arrays stored for `cell`, or None when there are none, the file does not read back,
        or it was written for other names."""
        path = self._path(cell)
        if not path.exists():
            return None
        try:
            with np.load(path, allow_pickle=False) as stored:
                arrays = {key: stored[key] for key in stored.files}
        except (OSError, ValueError, EOFError, KeyError, zipfile.BadZipFile) as error:
            _logger.warning("cell_spool.unreadable", cell=cell, path=str(path), error=str(error))
            return None
        if str(arrays.pop(_CELL_FIELD, "")) != cell or tuple(
            arrays.pop(_NAMES_FIELD, ()).tolist()
        ) != tuple(names):
            _logger.warning("cell_spool.mismatch", cell=cell, path=str(path))
            return None
        return arrays

    def store(self, cell: str, names: Sequence[str], arrays: Mapping[str, np.ndarray]) -> None:
        """Write `cell`'s arrays: a temporary file next to the final one, then a rename."""
        reserved = {_NAMES_FIELD, _CELL_FIELD} & set(arrays)
        if reserved:
            raise ValueError(f"array names {sorted(reserved)} are reserved")
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(cell)
        temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        payload = {**arrays, _NAMES_FIELD: np.array(list(names), dtype=str), _CELL_FIELD: cell}
        with temporary.open("wb") as handle:
            np.savez(handle, **payload)
        os.replace(temporary, path)

    def remove(self) -> None:
        """Delete the unit's directory once its rows are written."""
        shutil.rmtree(self.directory, ignore_errors=True)
