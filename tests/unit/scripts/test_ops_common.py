"""scripts/ops/_common.py: the shared file digest."""

from __future__ import annotations

import hashlib

from scripts.ops._common import file_sha256


def test_file_sha256_matches_hashlib_across_the_block_boundary(tmp_path):
    payload = b"x" * ((1 << 20) + 17)
    path = tmp_path / "blob.bin"
    path.write_bytes(payload)
    assert file_sha256(path) == hashlib.sha256(payload).hexdigest()


def test_file_sha256_of_an_empty_file(tmp_path):
    path = tmp_path / "empty"
    path.write_bytes(b"")
    assert file_sha256(path) == hashlib.sha256(b"").hexdigest()
