"""Shared helper for grep-as-test source assertions.

Several unit tests assert on the literal text of a service module (e.g. to
guard an invariant like "must filter on executable_open_to_open" or "must
never read from alpha_events") without importing or executing it. This
factors out the read-the-source-file boilerplate those tests share.
"""

from __future__ import annotations

from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent


def read_source(*relative_parts: str) -> str:
    """Read a project source file by path parts relative to the repo root.

    Example: read_source("services", "ensemble_ic_engine.py")
    """
    path = _PROJECT_ROOT.joinpath(*relative_parts)
    assert path.exists(), f"{Path(*relative_parts)} not found at {path}"
    return path.read_text()
