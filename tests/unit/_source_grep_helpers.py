"""Shared helper for grep-as-test source assertions.

Several unit tests assert on the literal text of a service module (e.g. to
guard an invariant like "must filter on executable_open_to_open" or "must
never read from alpha_events") without importing or executing it. This
factors out the read-the-source-file boilerplate those tests share.
"""

from __future__ import annotations

import re
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent


def read_source(*relative_parts: str) -> str:
    """Read a project source file by path parts relative to the repo root.

    Example: read_source("services", "ensemble_ic_engine.py")
    """
    path = _PROJECT_ROOT.joinpath(*relative_parts)
    assert path.exists(), f"{Path(*relative_parts)} not found at {path}"
    return path.read_text()


def find_pattern_references(
    repo_root: Path,
    search_dirs: tuple[str, ...],
    pattern: re.Pattern[str],
    file_globs: tuple[str, ...] = ("*.py",),
) -> dict[str, int]:
    """Scan search_dirs under repo_root for files matching file_globs, count regex
    `pattern` occurrences per file. Returns {relative_path: match_count} for files
    with at least one match.

    Shared walk-and-count mechanics behind this directory's allow-list CI guards
    (e.g. test_no_bare_process_pool_executor.py, and test_market_data_ohlcv_boundary.py
    which it was modeled on) -- each guard supplies its own pattern/allow-list/search
    scope, this owns only the part they'd otherwise duplicate.
    """
    hits: dict[str, int] = {}
    for search_dir in search_dirs:
        for file_glob in file_globs:
            for path in (repo_root / search_dir).rglob(file_glob):
                text = path.read_text(encoding="utf-8", errors="ignore")
                count = len(pattern.findall(text))
                if count:
                    hits[str(path.relative_to(repo_root))] = count
    return hits


def assert_no_unlisted_references(
    hits: dict[str, int], allow_list: dict[str, str], *, what: str, remedy: str
) -> None:
    """Fail loud if any hit isn't on the allow-list. `what` names what was found
    (folded into the message); `remedy` tells the reader what to do about it."""
    unexpected = set(hits) - set(allow_list)
    assert not unexpected, f"New {what} found, not on the allow-list: {unexpected}. {remedy}"


def assert_allow_list_has_no_stale_entries(
    hits: dict[str, int], allow_list: dict[str, str]
) -> None:
    stale = set(allow_list) - set(hits)
    assert not stale, (
        f"Allow-list entries that no longer match any reference: {stale}. Either the "
        "file was fixed (remove its entry here) or moved/renamed (update the path)."
    )
