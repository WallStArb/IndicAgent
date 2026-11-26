"""The guarded launchers' untested branches, against stub psql, systemctl, pgrep, journalctl, cat and python.

`host_gate` (every refusal and the pass), `verdict_preflight` (stale count, capture not delivered, query
failure) and `corpus_pilot.sh` (the `--resume` commit check, release on 0, hold otherwise, and the
new-run failure paths that must release the timers after a quiesce). The scripts are copied into a
temporary repo so their status file, scratch directory and worktrees are private; nothing real is read.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "ops"
RUN_ID = "11111111-2222-3333-4444-555555555555"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}

_STUBS = {
    "python": """#!/bin/sh
echo "$*" >> "$STUB_LOG"
case "$*" in
  *--quiesce*) exit "${QUIESCE_RC:-0}";;
  *--release*) exit "${RELEASE_RC:-0}";;
  *--new-run*) [ "${NEWRUN_RC:-0}" = 0 ] || { echo "new-run failed"; exit "$NEWRUN_RC"; }
               echo "${NEWRUN_OUT-created run $STUB_RUN_ID}"; exit 0;;
  *"--through pilot"*) sleep 0.6; exit "${PILOT_RC:-0}";;
  *ops_capture_delivered*) if [ "${CAPTURE_RC:-0}" = 0 ]; then echo "capture delivered"; else
                             echo "wait for the nightly capture: 2026-11-25 missing"; exit "$CAPTURE_RC"; fi; exit 0;;
  *rebuild_code_key*) echo "${STUB_KEY:-0f593f92f8b4aaaa}"; exit 0;;
esac
exec /usr/bin/python3 "$@"
""",
    "psql": """#!/bin/sh
case "$*" in
  *blocking_timers*) echo '["a.timer","b.timer"]';;
  *feature_factory.workers*) echo "${WORKERS_NOW:-4}";;
  *feature_block_columns*) echo "${WIDTH_NOW:-16}";;
  *"select code_commit"*) echo "$RECORDED_COMMIT";;
  *bar_integrity*) [ "${PSQL_VERDICT_FAIL:-0}" = 1 ] && exit 1; echo "${VERDICT_ROW-30 0 100}";;
esac
""",
    "systemctl": """#!/bin/sh
case "$1 $3" in
  "show LoadState") echo loaded;;
  "show Triggers") echo "${5%.timer}.service";;
  "is-active "*) echo inactive;;
esac
""",
    "pgrep": """#!/bin/sh
case "$1" in
  -x) [ "${STUB_MEMTESTER:-0}" = 1 ];;
  *) [ "${STUB_HEAVY:-0}" = 1 ];;
esac
""",
    "journalctl": """#!/bin/sh
[ -n "$STUB_NO_JOURNAL" ] && exit 0
echo "${STUB_JOURNAL:-kernel: all quiet}"
""",
    "cat": """#!/bin/sh
if [ "$1" = /proc/sys/kernel/tainted ]; then echo "${STUB_TAINTED:-0}"; exit 0; fi
exec /bin/cat "$@"
""",
}


def _git(path: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, **GIT_ENV},
    )
    return done.stdout.strip()


def _commit(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    (path / "f").write_text("x")
    _git(path, "add", "f")
    _git(path, "commit", "-q", "-m", "c")
    return _git(path, "rev-parse", "HEAD")


class Lab:
    """A private repo copy of the launcher scripts, stubs on PATH, a fake hwmon tree and meminfo."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.repo = tmp_path / "repo"
        ops = self.repo / "scripts" / "ops"
        ops.mkdir(parents=True)
        for name in ("guarded_run_common.sh", "corpus_pilot.sh"):
            shutil.copy(SCRIPTS / name, ops / name)
        (self.repo / ".venv" / "bin").mkdir(parents=True)
        self.stubs = tmp_path / "bin"
        self.stubs.mkdir()
        for name, text in _STUBS.items():
            target = (
                self.repo / ".venv" / "bin" / "python" if name == "python" else self.stubs / name
            )
            target.write_text(text)
            target.chmod(0o755)
        for index in (0, 1):
            sensor = tmp_path / "hw" / f"hwmon{index}"
            sensor.mkdir(parents=True)
            (sensor / "name").write_text("spd5118\n")
            (sensor / "temp1_input").write_text("40000\n")
        (tmp_path / "meminfo").write_text("MemAvailable:   67108864 kB\n")
        self.scratch = self.repo / "logs" / "guarded_run"
        self.scratch.mkdir(parents=True)
        (self.scratch / "memtester_clean").write_text("ok\n")
        self.status = self.repo / "logs" / "family10_run_status.txt"
        self.status.write_text("block2 compare: IDENTICAL []\n")
        self.log = tmp_path / "stub.log"
        self.log.write_text("")
        self.env = {
            "PATH": f"{self.stubs}:/usr/bin:/bin",
            "STUB_LOG": str(self.log),
            "STUB_RUN_ID": RUN_ID,
            "DIMM_HWMON_ROOT": str(tmp_path / "hw"),
            "MEMINFO": str(tmp_path / "meminfo"),
            "NOW_H": "12",
            "POLL_S": "0.1",
            **GIT_ENV,
        }

    def run(self, body: str = "", script: str = "", **env: str) -> subprocess.CompletedProcess[str]:
        command = (
            ["bash", str(self.repo / "scripts" / "ops" / script)]
            if script
            else ["bash", "-c", f'source "{self.repo}/scripts/ops/guarded_run_common.sh"; {body}']
        )
        return subprocess.run(
            command,
            env={**self.env, **env},
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def status_text(self) -> str:
        return self.status.read_text()

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines()


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    return Lab(tmp_path)


# ---------------------------------------------------------------------------------------------
# host_gate
# ---------------------------------------------------------------------------------------------


def test_host_gate_passes_on_a_healthy_host(lab: Lab) -> None:
    result = lab.run("host_gate; echo PASS")
    assert result.returncode == 0, lab.status_text()
    assert "PASS" in result.stdout


def test_host_gate_refuses_without_the_memtester_record(lab: Lab) -> None:
    (lab.scratch / "memtester_clean").unlink()
    assert lab.run("host_gate").returncode == 3
    assert "no memtester_clean file" in lab.status_text()


def test_host_gate_refuses_while_memtester_runs(lab: Lab) -> None:
    assert lab.run("host_gate", STUB_MEMTESTER="1").returncode == 3
    assert "memtester still running" in lab.status_text()


def test_host_gate_refuses_while_another_heavy_job_is_live(lab: Lab) -> None:
    assert lab.run("host_gate", STUB_HEAVY="1").returncode == 3
    assert "another heavy job is live" in lab.status_text()


def test_host_gate_refuses_a_tainted_kernel(lab: Lab) -> None:
    assert lab.run("host_gate", STUB_TAINTED="4096").returncode == 3
    assert "kernel tainted: 4096" in lab.status_text()


@pytest.mark.parametrize(
    "signature",
    [
        "segfault at 0",
        "bash[1]: segfault at 7fff055b5e40 ip 00005d02bbb56bdf sp 00007fff055b5e48 error 6 in bash",
        "BUG: Bad page state",
        "Bad swap file entry",
        "general protection fault",
    ],
)
def test_host_gate_refuses_a_kernel_memory_fault_signature(lab: Lab, signature: str) -> None:
    assert lab.run("host_gate", STUB_JOURNAL=f"kernel: {signature}").returncode == 3
    assert "memory-fault signatures" in lab.status_text()


STACK_OVERFLOW = "bash[2953915]: segfault at 7fff055b5e40 ip 00005d02bbb56bdf sp 00007fff055b5e40 error 6 in bash"


def test_host_gate_discloses_and_ignores_a_stack_overflow_segfault(lab: Lab) -> None:
    assert (
        lab.run("host_gate; echo PASS", STUB_JOURNAL=f"kernel: {STACK_OVERFLOW}").returncode == 0
    ), lab.status_text()
    assert f"ignored stack-overflow segfault: kernel: {STACK_OVERFLOW}" in lab.status_text()


def test_host_gate_refuses_a_stack_overflow_beside_a_real_fault(lab: Lab) -> None:
    journal = f"kernel: {STACK_OVERFLOW}\nkernel: bash[1]: segfault at 10 ip 0000 sp 7fff0000 error 4 in bash"
    assert lab.run("host_gate", STUB_JOURNAL=journal).returncode == 3
    assert "memory-fault signatures" in lab.status_text()


def test_host_gate_refuses_an_unreadable_kernel_log(lab: Lab) -> None:
    assert lab.run("host_gate", STUB_NO_JOURNAL="1").returncode == 3
    assert "kernel log unreadable" in lab.status_text()


def test_host_gate_refuses_with_one_dimm_sensor(lab: Lab) -> None:
    (lab.root / "hw" / "hwmon1" / "temp1_input").unlink()
    assert lab.run("host_gate").returncode == 3
    assert "expected 2 spd5118 sensors, found 1" in lab.status_text()


def test_host_gate_refuses_a_warm_dimm(lab: Lab) -> None:
    (lab.root / "hw" / "hwmon0" / "temp1_input").write_text("61000\n")
    assert lab.run("host_gate").returncode == 3
    assert "DIMM at 61C, gate 60C" in lab.status_text()


def test_host_gate_accepts_a_dimm_at_the_gate(lab: Lab) -> None:
    (lab.root / "hw" / "hwmon0" / "temp1_input").write_text("60000\n")
    assert lab.run("host_gate; echo PASS").returncode == 0


def test_host_gate_refuses_low_memory(lab: Lab) -> None:
    (lab.root / "meminfo").write_text("MemAvailable:   1048576 kB\n")
    assert lab.run("host_gate").returncode == 3
    assert "GiB available" in lab.status_text()


# ---------------------------------------------------------------------------------------------
# verdict_preflight
# ---------------------------------------------------------------------------------------------


def test_verdict_preflight_passes_when_no_verdict_is_stale(lab: Lab) -> None:
    result = lab.run("verdict_preflight; echo PASS")
    assert result.returncode == 0, lab.status_text()


def test_verdict_preflight_refuses_stale_member_verdicts(lab: Lab) -> None:
    assert lab.run("verdict_preflight", VERDICT_ROW="30 91 12857").returncode == 3
    text = lab.status_text()
    assert "91 of 12857 member 1d verdicts are older than 30 h" in text
    assert "ops_member_verdicts_1d.py --apply" in text


def test_verdict_preflight_refuses_before_the_capture_is_delivered(lab: Lab) -> None:
    assert lab.run("verdict_preflight", CAPTURE_RC="1").returncode == 3
    assert "wait for the nightly capture" in lab.status_text()
    assert not any(
        "bar_integrity" in c for c in lab.calls()
    )  # refused first, before any verdict read


def test_verdict_preflight_refuses_when_the_query_fails(lab: Lab) -> None:
    assert lab.run("verdict_preflight", PSQL_VERDICT_FAIL="1").returncode == 3
    assert "verdict preflight query failed" in lab.status_text()


def test_verdict_preflight_refuses_when_the_query_reads_nothing(lab: Lab) -> None:
    assert lab.run("verdict_preflight", VERDICT_ROW="").returncode == 3
    assert "verdict preflight read nothing" in lab.status_text()


# ---------------------------------------------------------------------------------------------
# corpus_pilot.sh
# ---------------------------------------------------------------------------------------------


def _pilot(lab: Lab, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(lab.repo / "scripts" / "ops" / "corpus_pilot.sh"), *args],
        env={**lab.env, **env},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def _calls_with(lab: Lab, needle: str) -> list[str]:
    return [c for c in lab.calls() if needle in c]


def _run_worktree(lab: Lab) -> str:
    """The run's worktree, a git repo whose HEAD is returned."""
    return _commit(lab.root / f"repo-corpus-run-{RUN_ID}")


def test_resume_refuses_when_the_worktree_head_is_not_the_recorded_commit(lab: Lab) -> None:
    _run_worktree(lab)
    result = _pilot(lab, "--resume", RUN_ID, RECORDED_COMMIT="deadbeef" * 5)
    assert result.returncode == 3
    assert "is not the run's recorded code_commit" in lab.status_text()
    assert not _calls_with(lab, "--through pilot")


def test_resume_releases_the_timers_after_a_clean_pilot(lab: Lab) -> None:
    head = _run_worktree(lab)
    result = _pilot(lab, "--resume", RUN_ID, RECORDED_COMMIT=head, PILOT_RC="0")
    assert result.returncode == 0, lab.status_text()
    assert _calls_with(lab, f"--run-id {RUN_ID} --through pilot")
    assert _calls_with(lab, "--release")
    assert "timers released" in lab.status_text()


def test_resume_holds_the_timers_when_the_pilot_fails(lab: Lab) -> None:
    head = _run_worktree(lab)
    result = _pilot(lab, "--resume", RUN_ID, RECORDED_COMMIT=head, PILOT_RC="1")
    assert result.returncode == 1
    assert not _calls_with(lab, "--release")
    assert f"timers held: run {RUN_ID}" in lab.status_text()


def test_resume_refuses_without_a_worktree(lab: Lab) -> None:
    result = _pilot(lab, "--resume", RUN_ID)
    assert result.returncode == 3
    assert "no worktree" in lab.status_text()


def test_resume_refuses_a_run_id_that_is_not_a_uuid(lab: Lab) -> None:
    (lab.root / "repo-corpus-run-not-a-uuid").mkdir()
    result = _pilot(lab, "--resume", "not-a-uuid")
    assert result.returncode == 3
    assert "is not a uuid" in lab.status_text()


def test_resume_refuses_a_run_the_database_does_not_know(lab: Lab) -> None:
    _run_worktree(lab)
    result = _pilot(lab, "--resume", RUN_ID, RECORDED_COMMIT="")
    assert result.returncode == 3
    assert "no corpus_run row" in lab.status_text()


def _new_run_lab(lab: Lab) -> None:
    """A repo with an origin to fast-forward from, and the worktree the new run will use."""
    origin = lab.root / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    _commit(lab.repo)
    _git(lab.repo, "remote", "add", "origin", str(origin))
    _git(lab.repo, "push", "-q", "-u", "origin", "main")
    _run_worktree(lab)


def _new_run(lab: Lab, **env: str) -> subprocess.CompletedProcess[str]:
    _new_run_lab(lab)
    return _pilot(lab, "0f593f92f8b4", **env)


def test_new_run_walks_quiesce_new_run_pilot_release(lab: Lab) -> None:
    result = _new_run(lab, PILOT_RC="0")
    assert result.returncode == 0, lab.status_text()
    steps = [
        c.split("corpus_rerun ")[-1].split()[0] for c in lab.calls() if "services.corpus_rerun" in c
    ]
    assert steps == ["--quiesce", "--new-run", "--run-id", "--release"]


def test_a_failed_quiesce_releases_and_stops(lab: Lab) -> None:
    result = _new_run(lab, QUIESCE_RC="1")
    assert result.returncode == 3
    assert "quiesce failed" in lab.status_text()
    assert _calls_with(lab, "--release")
    assert not _calls_with(lab, "--new-run")


def test_a_failed_new_run_releases_the_timers(lab: Lab) -> None:
    result = _new_run(lab, NEWRUN_RC="1")
    assert result.returncode == 3
    assert "new-run failed" in lab.status_text()
    assert len(_calls_with(lab, "--release")) == 1


def test_a_new_run_without_a_run_id_releases_the_timers(lab: Lab) -> None:
    result = _new_run(lab, NEWRUN_OUT="created, but no id printed")
    assert result.returncode == 3
    assert "no run id in the new-run output" in lab.status_text()
    assert len(_calls_with(lab, "--release")) == 1


def test_a_missing_run_worktree_releases_the_timers(lab: Lab) -> None:
    _new_run_lab(lab)
    shutil.rmtree(lab.root / f"repo-corpus-run-{RUN_ID}")
    result = _pilot(lab, "0f593f92f8b4")
    assert result.returncode == 3
    assert "cd worktree" in lab.status_text()
    assert len(_calls_with(lab, "--release")) == 1


def test_a_failed_pilot_after_the_run_exists_holds_the_timers(lab: Lab) -> None:
    _new_run(lab, PILOT_RC="1")
    assert not _calls_with(lab, "--release")
    assert f"timers held: run {RUN_ID}" in lab.status_text()


def test_a_failed_pilot_makes_the_launcher_exit_nonzero(lab: Lab) -> None:
    assert _new_run(lab, PILOT_RC="1").returncode == 1


def test_a_rebuild_key_that_does_not_match_the_plan_refuses_before_any_quiesce(lab: Lab) -> None:
    result = _new_run(lab, STUB_KEY="aaaaaaaaaaaa")
    assert result.returncode == 3
    assert "does not start with 0f593f92f8b4" in lab.status_text()
    assert not _calls_with(lab, "--quiesce")


def test_the_pilot_refuses_without_the_block2_comparison(lab: Lab) -> None:
    lab.status.write_text("nothing\n")
    result = _pilot(lab, "0f593f92f8b4")
    assert result.returncode == 3
    assert "no IDENTICAL block 2 comparison" in lab.status_text()


def test_the_pilot_refuses_with_the_wrong_worker_count(lab: Lab) -> None:
    result = _pilot(lab, "0f593f92f8b4", WORKERS_NOW="12")
    assert result.returncode == 3
    assert "infra.feature_factory.workers is 12, expected 4" in lab.status_text()


def test_the_pilot_refuses_inside_the_nightly_window(lab: Lab) -> None:
    result = _pilot(lab, "0f593f92f8b4", NOW_H="03")
    assert result.returncode == 3
    assert "inside the nightly window" in lab.status_text()
    assert not _calls_with(lab, "--quiesce")


def test_the_pilot_refuses_a_wrong_ic_block_width_before_any_quiesce(lab: Lab) -> None:
    result = _pilot(lab, "0f593f92f8b4", WIDTH_NOW="32")
    assert result.returncode == 3
    assert "alpha.ic.feature_block_columns is 32, expected 16" in lab.status_text()
    assert not _calls_with(lab, "--quiesce")


def test_a_resume_also_refuses_a_wrong_ic_block_width(lab: Lab) -> None:
    head = _run_worktree(lab)
    result = _pilot(lab, "--resume", RUN_ID, RECORDED_COMMIT=head, WIDTH_NOW="32")
    assert result.returncode == 3
    assert not _calls_with(lab, "--through pilot")
