"""Content-hashed array directories: the on-disk form of every research snapshot.

A directory `<prefix>_<sha256[:16]>/` holds one .npy per array plus meta.json. The hash covers
every array's name and bytes and the metadata, so the directory name is a checksum of its
content: verify() recomputes it, and a modified snapshot fails loudly instead of feeding a run.
Arrays load memory-mapped. Phase 179's sleeve snapshots use the same format (prefix
"snapshot"), so their existing hashes still verify.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np

_META = "meta.json"


def _digest(directory: Path, names: list[str]) -> str:
    digest = hashlib.sha256()
    for name in names:
        digest.update(name.encode())
        digest.update((directory / f"{name}.npy").read_bytes())
    digest.update((directory / _META).read_bytes())
    return digest.hexdigest()


def write(out_dir: Path, prefix: str, arrays: dict[str, np.ndarray], meta: dict) -> Path:
    """Write to a temporary directory, then rename it to its content hash."""
    tmp = Path(out_dir) / f"{prefix}_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for name in sorted(arrays):
        np.save(tmp / f"{name}.npy", arrays[name], allow_pickle=False)
    (tmp / _META).write_text(json.dumps(meta, sort_keys=True, default=str))
    final = Path(out_dir) / f"{prefix}_{_digest(tmp, sorted(arrays))[:16]}"
    shutil.rmtree(final, ignore_errors=True)
    tmp.rename(final)
    return final


def verify(path: Path) -> None:
    """Recompute the content hash and compare it with the directory name."""
    path = Path(path)
    names = sorted(p.stem for p in path.glob("*.npy"))
    if not path.name.endswith(_digest(path, names)[:16]):
        raise ValueError(f"snapshot hash mismatch: {path} was modified after it was written")


def read_meta(path: Path) -> dict:
    return json.loads((Path(path) / _META).read_text())


def read_array(path: Path, name: str) -> np.ndarray:
    return np.load(Path(path) / f"{name}.npy", mmap_mode="r", allow_pickle=False)
