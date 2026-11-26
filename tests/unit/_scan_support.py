"""One floor for every guard that scans a directory tree and asserts nothing was found.

A scan that visits nothing (a renamed directory, a glob that stopped matching, a wrong repo root)
reports "no violations" and passes forever. `assert_scanned` makes the guard fail instead when it
visits fewer files than a floor set a margin below today's count; raise the floor when the tree
grows, never lower it to quiet a failure."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def assert_scanned(paths: Iterable[Path], minimum: int, what: str) -> list[Path]:
    """The paths as a list, after checking that the scan visited at least `minimum` of them."""
    found = list(paths)
    assert len(found) >= minimum, (
        f"{what}: the scan visited {len(found)} files, expected at least {minimum}. "
        "A directory moved or a glob stopped matching, so this guard would pass without checking anything."
    )
    return found
