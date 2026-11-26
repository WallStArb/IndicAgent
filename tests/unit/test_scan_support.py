"""The scan floor fails a guard that visited too little, and hands back what it visited."""

from pathlib import Path

import pytest

from tests.unit._scan_support import assert_scanned


def test_a_scan_at_or_above_the_floor_returns_the_paths() -> None:
    paths = [Path("a"), Path("b"), Path("c")]
    assert assert_scanned(iter(paths), 3, "three files") == paths


def test_a_scan_below_the_floor_fails_loudly() -> None:
    with pytest.raises(AssertionError, match=r"visited 2 files, expected at least 3"):
        assert_scanned([Path("a"), Path("b")], 3, "two files")


def test_an_empty_scan_fails() -> None:
    with pytest.raises(AssertionError, match="visited 0 files"):
        assert_scanned((p for p in ()), 1, "nothing")
