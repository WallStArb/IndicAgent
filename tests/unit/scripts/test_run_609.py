"""run_609.sh is the plan of record for the todo 609 chain: it must parse, and its read-only
`gaps` form must run without touching the status file or the database."""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "ops" / "bars" / "run_609.sh"


def test_the_script_parses():
    assert subprocess.run(["bash", "-n", str(SCRIPT)], check=False).returncode == 0


def test_gaps_lists_the_open_gaps_and_marks_g5_resolved():
    out = subprocess.run(["bash", str(SCRIPT), "gaps"], capture_output=True, text=True, check=False)
    assert out.returncode == 0
    assert "G5 RESOLVED" in out.stdout and "G3" in out.stdout and "G4" in out.stdout
