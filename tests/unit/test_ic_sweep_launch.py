"""The guarded IC sweep launcher (scripts/ops/ic_sweep_launch.sh, todo 690): the pure judges, then the launch paths
against stub psql, systemctl and python in the private repo copy the guarded-run tests build.

The recorder runs inside the window the corpus stage holds (lead ruling 2026-11-28): the launcher refuses unless the
blocking timers are already quiesced and never quiesces or releases them; only ic_measure_launch.sh releases.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit.test_guarded_run_launch_paths import RUN_ID, SCRIPTS, Lab, _commit, _git

SCRIPT = SCRIPTS / "ic_sweep_launch.sh"

_PSQL = """#!/bin/sh
[ -n "${PGPASSWORD:-}" ] || { echo "psql: no password supplied" >&2; exit 2; }
case "$*" in
  *data_gate_scope*) echo "${SCOPE_NOW-1d}"; exit 0;;
  *"step='feature_complete'"*) echo "${FC_STATUS-completed}"; exit 0;;
  *"step='ic_measure'"*) echo "${ICM_STATUS-}"; exit 0;;
  *mem_floor_gib.ic_sweep*) echo "${FLOOR_NOW-24}"; exit 0;;
esac
exec "$BASE_STUBS/psql" "$@"
"""
_SYSTEMCTL = """#!/bin/sh
[ "$1" = is-enabled ] && { echo "${STUB_ENABLED-disabled}"; exit 0; }
if [ "$1" = is-active ]; then
  case "$2" in *.timer) echo "${STUB_TIMER_ACTIVE:-inactive}"; exit 0;; esac
fi
exec "$BASE_STUBS/systemctl" "$@"
"""
_PYTHON = """#!/bin/sh
case "$*" in
  *ic_sweep_recorder*|*stepm_sweep_scale_check*) echo "$PWD $*" >> "$STUB_LOG"; sleep 0.3; exit "${JOB_RC:-0}";;
esac
exec "$BASE_STUBS/python" "$@"
"""


def _bash(body: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f'source "{SCRIPT}"; {body}'],
        env={"GUARDED_RUN_DIR": "/nonexistent", "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )


def _q(*args: str) -> str:
    return " ".join(f"'{a}'" for a in args)


def test_sweep_launcher_parses() -> None:
    assert subprocess.run(["bash", "-n", str(SCRIPT)], check=False).returncode == 0


@pytest.mark.parametrize("mode", ["dry-run", "record"])
def test_a_run_inside_the_held_window_passes_the_judge(mode: str) -> None:
    assert _bash(f"sweep_preflight_judge {_q(mode, '1d', 'completed', '')}").returncode == 0


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("bogus", "1d", "completed", ""), "is not dry-run, record or stepm-check"),
        (("dry-run", "all", "completed", ""), "a scope-1d run"),
        (("dry-run", "1d", "running", ""), "feature_complete step is 'running'"),
        (("record", "1d", "completed", "completed"), "the recorder's window is closed"),
    ],
)
def test_each_judge_refusal_names_its_reason(args: tuple[str, ...], message: str) -> None:
    result = _bash(f"sweep_preflight_judge {_q(*args)}")
    assert result.returncode == 1 and message in result.stdout


def test_the_stepm_check_needs_no_run_state() -> None:
    assert _bash(f"sweep_preflight_judge {_q('stepm-check', '', '', '')}").returncode == 0


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("/nonexistent", "no", "", "yes"), "no sweep worktree"),
        (("/tmp", "yes", "", "yes"), "is a corpus run worktree"),
        (("/tmp", "no", " M services/x.py", "yes"), "uncommitted tracked changes"),
        (("/tmp", "no", "", "no"), "not an ancestor of origin/main"),
    ],
)
def test_each_worktree_refusal_names_its_reason(args: tuple[str, ...], message: str) -> None:
    result = _bash(f"sweep_worktree_judge {_q(*args)}")
    assert result.returncode == 1 and message in result.stdout
    assert _bash(f"sweep_worktree_judge {_q('/tmp', 'no', '', 'yes')}").returncode == 0


class Sweep(Lab):
    """The guarded-run lab plus the sweep launcher, its stubs and a published sweep worktree."""

    def __init__(self, tmp_path: Path) -> None:
        super().__init__(tmp_path)
        shutil.copy(SCRIPT, self.repo / "scripts" / "ops" / SCRIPT.name)
        base = tmp_path / "base_bin"
        base.mkdir()
        for name, text in (("psql", _PSQL), ("systemctl", _SYSTEMCTL)):
            shutil.move(self.stubs / name, base / name)
            (self.stubs / name).write_text(text)
            (self.stubs / name).chmod(0o755)
        python = self.repo / ".venv" / "bin" / "python"
        shutil.move(python, base / "python")
        python.write_text(_PYTHON)
        python.chmod(0o755)
        self.env["BASE_STUBS"] = str(base)
        (tmp_path / "meminfo").write_text("MemAvailable:   31457280 kB\n")  # 30 GiB
        self.worktree = tmp_path / "wt-sweep"
        _commit(self.worktree)
        _git(self.worktree, "update-ref", "refs/remotes/origin/main", "HEAD")

    def launch(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.repo / "scripts" / "ops" / SCRIPT.name), *args],
            env={**self.env, **env},
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )


@pytest.fixture
def sweep(tmp_path: Path) -> Sweep:
    return Sweep(tmp_path)


def _jobs(sweep: Sweep) -> list[str]:
    return [c for c in sweep.calls() if "ic_sweep_recorder" in c or "stepm_sweep_scale_check" in c]


def test_a_dry_run_in_the_held_window_runs_in_the_worktree_and_never_touches_the_timers(
    sweep: Sweep,
) -> None:
    result = sweep.launch("dry-run", str(sweep.worktree), RUN_ID, "--report", "r.json")
    assert result.returncode == 0, sweep.status_text()
    (job,) = _jobs(sweep)
    assert job.startswith(str(sweep.worktree) + " ")
    assert "-m services.ic_sweep_recorder --tf 1d --dry-run --report r.json" in job
    assert not [c for c in sweep.calls() if "--quiesce" in c or "--release" in c]
    text = sweep.status_text()
    assert "ic_sweep dry-run exit=0" in text and "(timers untouched)" in text
    assert "floor 24 GiB" in text


def test_a_record_passes_its_arguments_without_dry_run(sweep: Sweep) -> None:
    args = ("--horizons", "1", "--declared-n-looks", "8")
    assert sweep.launch("record", str(sweep.worktree), RUN_ID, *args).returncode == 0
    (job,) = _jobs(sweep)
    assert "--tf 1d --horizons 1 --declared-n-looks 8" in job and "--dry-run" not in job


def test_a_failed_job_keeps_its_exit_code_and_releases_nothing(sweep: Sweep) -> None:
    assert sweep.launch("dry-run", str(sweep.worktree), RUN_ID, JOB_RC="5").returncode == 5
    assert not [c for c in sweep.calls() if "--release" in c]


def test_timers_not_held_by_the_stage_refuse_and_are_not_quiesced(sweep: Sweep) -> None:
    result = sweep.launch("dry-run", str(sweep.worktree), RUN_ID, STUB_ENABLED="enabled")
    assert result.returncode == 3
    assert "is not disabled: quiesce first" in sweep.status_text()
    assert not _jobs(sweep) and not [c for c in sweep.calls() if "--quiesce" in c]


def test_after_the_ic_measure_the_recorder_refuses(sweep: Sweep) -> None:
    assert (
        sweep.launch("record", str(sweep.worktree), RUN_ID, ICM_STATUS="completed").returncode == 3
    )
    assert "the recorder's window is closed" in sweep.status_text() and not _jobs(sweep)


def test_the_stepm_check_needs_no_hold_and_no_run(sweep: Sweep) -> None:
    result = sweep.launch(
        "stepm-check",
        str(sweep.worktree),
        "-",
        "out.json",
        "--seed-base",
        "7",
        STUB_ENABLED="enabled",
    )
    assert result.returncode == 0, sweep.status_text()
    (job,) = _jobs(sweep)
    assert "scripts/research/stepm_sweep_scale_check.py out.json --seed-base 7" in job


def test_a_recorder_mode_without_a_run_id_refuses(sweep: Sweep) -> None:
    assert sweep.launch("dry-run", str(sweep.worktree), "-").returncode == 3
    assert not _jobs(sweep)


def test_a_dirty_or_unpublished_worktree_refuses(sweep: Sweep) -> None:
    (sweep.worktree / "f").write_text("changed")
    assert sweep.launch("dry-run", str(sweep.worktree), RUN_ID).returncode == 3
    assert "uncommitted tracked changes" in sweep.status_text()
    _git(sweep.worktree, "commit", "-qam", "local")
    assert sweep.launch("dry-run", str(sweep.worktree), RUN_ID).returncode == 3
    assert "not an ancestor of origin/main" in sweep.status_text()
    assert not _jobs(sweep)


def test_another_heavy_job_refuses(sweep: Sweep) -> None:
    assert sweep.launch("dry-run", str(sweep.worktree), RUN_ID, STUB_HEAVY="1").returncode == 3
    assert "another heavy job is live" in sweep.status_text() and not _jobs(sweep)


def test_the_floor_comes_from_apr(sweep: Sweep) -> None:
    assert sweep.launch("dry-run", str(sweep.worktree), RUN_ID, FLOOR_NOW="40").returncode == 3
    assert "need 40 GiB" in sweep.status_text() and not _jobs(sweep)


def test_a_check_reports_every_refusal_and_runs_nothing(sweep: Sweep) -> None:
    result = sweep.launch(
        "--check", "dry-run", str(sweep.worktree), RUN_ID, STUB_ENABLED="enabled", FLOOR_NOW=""
    )
    assert result.returncode != 0
    assert "is not disabled" in result.stdout and "is not an integer from 8 to 512" in result.stdout
    assert not _jobs(sweep)
