"""Helpers shared by the operator scripts under scripts/ops/.

Only what two or more scripts repeated verbatim. Output formats (JSON indent, key order) stay with
each script: evidence files are compared and hashed byte for byte, so they are not merged here.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_BLOCK_BYTES = 1 << 20


def file_sha256(path: Path) -> str:
    """Lowercase hex sha256 of a file, read in blocks so a multi-GB spool never sits in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(_BLOCK_BYTES):
            digest.update(block)
    return digest.hexdigest()
