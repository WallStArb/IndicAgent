"""CI gate: assert zero binary scoring patterns remain in plugin source.

This test runs the binary pattern scanner as a subprocess and asserts zero
violations. Direction encoders, categorical flags, detection events, and
eligibility gates are excluded via the scanner's allowlist.

Run with: .venv/bin/pytest tests/unit/intelligence/test_binary_pattern_scanner.py -v
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


def _project_root() -> Path:
    """Find project root by walking up from this test file."""
    here = Path(__file__).resolve().parent
    for parent in [here] + list(here.parents):
        if (parent / "src" / "intelligence").is_dir():
            return parent
    raise FileNotFoundError("Cannot find project root (src/intelligence/ not found)")


def _find_python(root: Path) -> Path:
    """Find Python interpreter -- .venv in project root or walk up to parent repos."""
    # Check project root first
    candidate = root / ".venv" / "bin" / "python"
    if candidate.is_file():
        return candidate
    # Walk up for worktree or monorepo setups where .venv is in a parent
    for parent in root.parents:
        candidate = parent / ".venv" / "bin" / "python"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Cannot find .venv/bin/python from {root}")


def test_zero_binary_violations():
    """Assert the binary pattern scanner finds zero true violations."""
    root = _project_root()
    scanner = root / "tools" / "scan_binary_patterns.py"
    python = _find_python(root)

    assert scanner.is_file(), f"Scanner not found at {scanner}"

    result = subprocess.run(
        [str(python), str(scanner), "--json"],
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    if result.returncode != 0:
        violations = json.loads(result.stdout) if result.stdout else []
        violation_summary = "\n".join(
            f"  {v['file']}:{v['line']}: {v['pattern']}" for v in violations[:20]
        )
        pytest.fail(
            f"Binary pattern scanner found {len(violations)} violation(s):\n" f"{violation_summary}"
        )
