"""Characterization tests: no naive datetime.now() calls in service files.

These tests guard against naive datetime usage that would produce timezone-unaware
timestamps — all datetimes must be UTC-aware per CLAUDE.md conventions.
"""

import pathlib
import re


def _find_naive_now_lines(path: str) -> list[str]:
    """Return lines that contain datetime.now() without UTC/tz argument."""
    src = pathlib.Path(path).read_text()
    naive_lines = []
    for line in src.splitlines():
        # Match datetime.now() but not datetime.now(UTC) or datetime.now(tz=...)
        if re.search(r"datetime\.now\(\s*\)", line):
            naive_lines.append(line.strip())
    return naive_lines


def test_indicator_compute_agent_no_naive_now():
    naive = _find_naive_now_lines("services/indicator_compute_agent.py")
    assert not naive, f"Found naive datetime.now() calls in indicator_compute_agent.py: {naive}"


def test_intelligence_compute_agent_no_naive_now():
    naive = _find_naive_now_lines("services/intelligence_compute_agent.py")
    assert not naive, f"Found naive datetime.now() calls in intelligence_compute_agent.py: {naive}"
