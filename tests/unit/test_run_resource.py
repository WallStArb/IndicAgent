"""tools/run_resource.sh: the per-run memory peak from the run's cgroup (todo 681, part A).

Most tests run against a fake cgroup tree and a temp textfile directory, so no real scope is made and the
real node-exporter directory is never written. The live probe at the end makes a real user scope, lets a
300 MiB child SIGKILL itself and checks the peak survives it; it skips where no user manager answers (CI).
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
import uuid
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "run_resource.sh"
MIB = 1024 * 1024


class Lab:
    """A fake cgroup scope and a textfile directory under tmp_path."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.scope = root / "cg" / "scope"
        self.out = root / "out"
        self.scope.mkdir(parents=True)
        self.out.mkdir()
        self.set(peak=300 * MIB)

    def set(
        self,
        peak: int | None = None,
        swap: int | None = 0,
        events: str = "low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n",
        procs: str = "",
    ) -> None:
        if peak is not None:
            (self.scope / "memory.peak").write_text(f"{peak}\n")
        if swap is not None:
            (self.scope / "memory.swap.peak").write_text(f"{swap}\n")
        (self.scope / "memory.events").write_text(events)
        (self.scope / "cgroup.procs").write_text(procs)

    def env(self, **extra: str) -> dict[str, str]:
        return {
            "PATH": os.environ["PATH"],
            "CGROUP_ROOT": str(self.root / "cg"),
            "RUN_RESOURCE_CGROUP": "/scope",
            "TEXTFILE_DIR": str(self.out),
            "RUN_RESOURCE_IN_SCOPE": "1",
            **extra,
        }

    def run(self, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SCRIPT), *args], env=self.env(**extra), capture_output=True, text=True, timeout=60
        )

    def emit(self, body: str = "", rc: int = 0, **extra: str) -> subprocess.CompletedProcess[str]:
        prelude = f"{body}; " if body else ""
        command = f'source "{SCRIPT}"; {prelude}run_resource_emit wl st r1 {rc}; echo "emit=$?"'
        return subprocess.run(
            ["bash", "-c", command],
            env=self.env(**extra),
            capture_output=True,
            text=True,
            timeout=60,
        )

    def samples(self, workload: str = "wl") -> dict[str, str]:
        text = (self.out / f"run_resource_{workload}.prom").read_text()
        found = re.findall(
            rf'^(run_resource_\w+)\{{workload="{workload}",stage="st",run_id="r1"\}} (\S+)$',
            text,
            re.M,
        )
        return dict(found)


@pytest.fixture
def lab(tmp_path: Path) -> Lab:
    return Lab(tmp_path)


def _alive(needle: str) -> bool:
    pattern = needle[:-1] + "[" + needle[-1] + "]"
    return (
        subprocess.run(["pgrep", "-f", pattern], capture_output=True, check=False).returncode == 0
    )


def test_emit_writes_every_series_atomically(lab: Lab) -> None:
    lab.set(peak=319815680, swap=4096, procs="")
    result = lab.emit(rc=7, RUN_RESOURCE_START="1700000000")
    assert "emit=0" in result.stdout, result.stderr
    values = lab.samples()
    assert values["run_resource_memory_peak_bytes"] == "319815680"
    assert values["run_resource_swap_peak_bytes"] == "4096"
    assert values["run_resource_oom_kill"] == "0"
    assert values["run_resource_leftover_processes"] == "0"
    assert values["run_resource_exit_code"] == "7"
    assert values["run_resource_start_timestamp_seconds"] == "1700000000"
    assert int(values["run_resource_end_timestamp_seconds"]) >= 1700000000
    assert [p.name for p in lab.out.iterdir()] == ["run_resource_wl.prom"]  # no temp file left
    assert (lab.out / "run_resource_wl.prom").stat().st_mode & 0o777 == 0o644
    assert "memory_peak_gib=0.30" in result.stdout and "exit=7" in result.stdout


def test_a_second_run_overwrites_the_workload_file(lab: Lab) -> None:
    lab.emit()
    lab.set(peak=2 * 1024 * MIB)
    lab.emit(rc=0)
    assert lab.samples()["run_resource_memory_peak_bytes"] == str(2 * 1024 * MIB)
    assert [p.name for p in lab.out.iterdir()] == ["run_resource_wl.prom"]


def test_oom_kill_is_read_from_memory_events(lab: Lab) -> None:
    lab.set(events="low 0\nhigh 3\nmax 9\noom 2\noom_kill 2\n")
    lab.emit()
    assert lab.samples()["run_resource_oom_kill"] == "2"


def test_a_kernel_without_swap_accounting_gives_nan_not_zero(lab: Lab) -> None:
    (lab.scope / "memory.swap.peak").unlink()
    lab.emit()
    assert lab.samples()["run_resource_swap_peak_bytes"] == "NaN"


def test_leftover_processes_exclude_the_wrapper_itself(lab: Lab) -> None:
    result = lab.emit(body=f'printf "%s\\n41\\n42\\n" "$$" > "{lab.scope}/cgroup.procs"')
    assert "emit=0" in result.stdout, result.stderr
    assert lab.samples()["run_resource_leftover_processes"] == "2"
    assert "leftover_processes=2" in result.stdout


def test_an_unreadable_peak_refuses_and_writes_nothing(lab: Lab) -> None:
    (lab.scope / "memory.peak").unlink()
    result = lab.emit()
    assert "emit=3" in result.stdout
    assert "memory.peak" in result.stderr
    assert list(lab.out.iterdir()) == []


@pytest.mark.parametrize("label", ["bad label", 'q"uote', "semi;colon", "new\nline"])
def test_an_unsafe_label_is_refused(lab: Lab, label: str) -> None:
    command = f'source "{SCRIPT}"; run_resource_emit "$1" st r1 0; echo "emit=$?"'
    result = subprocess.run(
        ["bash", "-c", command, "_", label],
        env=lab.env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert "emit=2" in result.stdout
    assert list(lab.out.iterdir()) == []


def test_wrapper_runs_the_command_and_reports_its_exit_code(lab: Lab) -> None:
    result = lab.run(
        "wl", "st", "r1", "--", "bash", "-c", "echo ran; exit 7", RUN_RESOURCE_START="5"
    )
    assert result.returncode == 7
    assert "ran" in result.stdout
    assert lab.samples()["run_resource_exit_code"] == "7"


def test_a_sigkilled_child_still_gets_its_peak_and_exit_137(lab: Lab) -> None:
    result = lab.run("wl", "st", "r1", "--", "bash", "-c", "kill -9 $$")
    assert result.returncode == 137
    values = lab.samples()
    assert values["run_resource_exit_code"] == "137"
    assert values["run_resource_memory_peak_bytes"] == str(300 * MIB)


def test_a_term_to_the_wrapper_reaches_the_job_and_is_still_emitted(lab: Lab) -> None:
    marker = f"31.{uuid.uuid4().int % 900 + 100}"
    process = subprocess.Popen(
        [str(SCRIPT), "wl", "st", "r1", "--", "sleep", marker],
        env=lab.env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    for _ in range(100):
        if _alive(f"sleep {marker}"):
            break
        time.sleep(0.05)
    assert _alive(f"sleep {marker}")
    process.send_signal(signal.SIGTERM)
    process.communicate(timeout=30)
    assert process.returncode == 143
    assert lab.samples()["run_resource_exit_code"] == "143"
    assert not _alive(f"sleep {marker}")


def test_wrapper_without_a_command_prints_usage(lab: Lab) -> None:
    result = lab.run("wl", "st", "r1")
    assert result.returncode == 64 and "usage" in result.stderr


def test_no_user_manager_refuses_with_exit_3(lab: Lab, tmp_path: Path) -> None:
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "systemd-run").write_text("#!/bin/sh\nexit 1\n")
    (stub / "systemd-run").chmod(0o755)
    env = lab.env(PATH=f"{stub}:{os.environ['PATH']}")
    del env["RUN_RESOURCE_IN_SCOPE"]
    result = subprocess.run(
        [str(SCRIPT), "wl", "st", "r1", "--", "true"], env=env, capture_output=True, text=True
    )
    assert result.returncode == 3 and "systemd-run --user failed" in result.stderr
    assert list(lab.out.iterdir()) == []


def _user_manager_answers() -> bool:
    try:
        return (
            subprocess.run(
                ["systemd-run", "--user", "--scope", "--quiet", "true"],
                capture_output=True,
                timeout=15,
                check=False,
            ).returncode
            == 0
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.mark.skipif(not _user_manager_answers(), reason="no systemd user manager (CI)")
def test_live_a_sigkilled_300_mib_child_leaves_its_peak(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    child = (
        "import os, signal; buf = bytearray(300 * 1024 * 1024); "
        "buf[::4096] = b'x' * len(buf[::4096]); os.kill(os.getpid(), signal.SIGKILL)"
    )
    env = {"PATH": os.environ["PATH"], "TEXTFILE_DIR": str(out), "HOME": os.environ["HOME"]}
    env["XDG_RUNTIME_DIR"] = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    result = subprocess.run(
        [str(SCRIPT), "probe", "st", "r1", "--", "python3", "-c", child],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 137, result.stderr
    text = (out / "run_resource_probe.prom").read_text()
    peak = int(re.search(r"memory_peak_bytes\{[^}]*\} (\d+)", text).group(1))
    assert 300 * MIB <= peak <= 400 * MIB
    assert re.search(r"oom_kill\{[^}]*\} 0\b", text)
