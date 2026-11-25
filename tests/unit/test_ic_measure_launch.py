"""Preflight logic of the guarded first-IC-measure launcher (todo 471, guarded-run runbook)."""

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "ic_measure_launch.sh"
OK = ("1d", "16", "completed", "completed", "", "abc", "abc", "09708ae249f2ff", "09708ae249f2")


def _bash(tmp_path: Path, body: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f'source "{SCRIPT}"; {body}'],
        env={"GUARDED_RUN_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )


def _judge(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    quoted = " ".join(f"'{a}'" for a in args)
    return _bash(tmp_path, f"ic_preflight_judge {quoted}")


def test_script_parses() -> None:
    assert subprocess.run(["bash", "-n", str(SCRIPT)], check=False).returncode == 0


def test_a_ready_run_passes(tmp_path: Path) -> None:
    assert _judge(tmp_path, *OK).returncode == 0


@pytest.mark.parametrize(
    ("index", "value", "message"),
    [
        (0, "all", "only a scope-1d run"),
        (1, "32", "ruled 16"),
        (2, "failed", "pilot step is 'failed'"),
        (3, "", "feature_complete step is ''"),
        (4, "completed", "already completed"),
        (5, "def", "not the run's code_commit"),
        (7, "0c65f74d0457ff", "does not start with"),
    ],
)
def test_each_refusal_names_its_reason(
    tmp_path: Path, index: int, value: str, message: str
) -> None:
    args = list(OK)
    args[index] = value
    result = _judge(tmp_path, *args)
    assert result.returncode == 1
    assert message in result.stdout


def test_a_failed_ic_measure_step_may_be_resumed(tmp_path: Path) -> None:
    args = list(OK)
    args[4] = "failed"
    assert _judge(tmp_path, *args).returncode == 0


def test_peak_rss_reads_only_lines_after_the_start(tmp_path: Path) -> None:
    log = tmp_path / "temp.log"
    log.write_text(
        "t pid=1 max_c=40 rss_mb=99999 paused=0\n"
        "t pid=2 max_c=41 rss_mb=1200 paused=0\n"
        "t pid=2 max_c=42 rss_mb=9100 paused=0\n"
        "t pid=2 max_c=42 rss_mb=800 paused=0\n"
    )
    assert _bash(tmp_path, f'peak_rss_mb_since "{log}" 1').stdout.strip() == "9100"
    assert _bash(tmp_path, f'peak_rss_mb_since "{log}" 4').stdout.strip() == "unknown"
