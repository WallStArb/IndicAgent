"""One runner for services/bar_derivation.py stage invocations (plan 185-18).

The cwd/PYTHONPATH convention is load-bearing (worktrees have no .venv; the
child needs src.* importable), so it lives here once instead of in every
caller: the historical pipeline chains the daily stage per run, the nightly
runs the daily and grid stages after its legs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent

_DERIVATION_SCRIPT = (project_root / "services" / "bar_derivation.py").resolve()


def run_derivation_stage(stage: str, *extra_args: str) -> int:
    """Run bar_derivation's `stage` subprocess; return its exit code."""
    result = subprocess.run(
        [sys.executable, str(_DERIVATION_SCRIPT), "--stage", stage, *extra_args],
        cwd=str(project_root),
        env={**os.environ, "PYTHONPATH": str(project_root)},
    )
    return result.returncode
