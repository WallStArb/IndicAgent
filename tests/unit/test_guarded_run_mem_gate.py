"""The guarded-run host gate compares MemAvailable in kB against a 40 GiB floor and reports the
exact GiB. It passes and fails at the same points as the old `free -g` whole-GB test; only the
message and a rounding edge change."""

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "guarded_run_common.sh"
KIB_PER_GIB = 1024 * 1024


def _mem_gate(tmp_path: Path, meminfo_text: str) -> subprocess.CompletedProcess[str]:
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(meminfo_text)
    script = f'source "{SCRIPT}"; fail() {{ echo "ABORT $*"; exit 3; }}; mem_gate; echo PASS'
    return subprocess.run(
        ["bash", "-c", script],
        env={"GUARDED_RUN_DIR": str(tmp_path), "MEMINFO": str(meminfo), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )


def _available(gib: float) -> str:
    return f"MemTotal:       65536000 kB\nMemAvailable:   {int(gib * KIB_PER_GIB)} kB\n"


def test_mem_gate_script_parses() -> None:
    assert subprocess.run(["bash", "-n", str(SCRIPT)], check=False).returncode == 0


def test_below_the_floor_fails_with_the_exact_gib(tmp_path: Path) -> None:
    result = _mem_gate(tmp_path, _available(39.6))
    assert result.returncode == 3
    assert "only 39.60 GiB available, need 40 GiB" in result.stdout


@pytest.mark.parametrize("gib", [40.0, 40.1])
def test_at_or_above_the_floor_passes(tmp_path: Path, gib: float) -> None:
    result = _mem_gate(tmp_path, _available(gib))
    assert result.returncode == 0
    assert "PASS" in result.stdout


def test_a_missing_memavailable_line_fails(tmp_path: Path) -> None:
    result = _mem_gate(tmp_path, "MemTotal: 1 kB\n")
    assert result.returncode == 3
    assert "PASS" not in result.stdout
