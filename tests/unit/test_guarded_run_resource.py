"""run_guarded reports the run's true memory peak (todo 681, part B): the gauges and one status line after a
normal exit, a watchdog kill and a launcher TERM, and a failed report never changes the job's exit code.

Every test sources `guarded_run_common.sh` against a fake hwmon tree, a fake cgroup tree and a private status
file, so no scope is made and the real `logs/` and node-exporter directory are never written."""

import re
import signal
import subprocess
import time
import uuid
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[2] / "scripts" / "ops"
COMMON = OPS / "guarded_run_common.sh"
MIB = 1024 * 1024
LAUNCHERS = (
    "corpus_pilot.sh",
    "ic_measure_launch.sh",
    "family10_launch.sh",
    "family10_block2_rerun.sh",
    "corpus_stage_launch.sh",
)


class Lab:
    def __init__(self, root: Path, temps_c: tuple[int, int] = (40, 40)) -> None:
        self.root = root
        for index, temp in enumerate(temps_c):
            sensor = root / "hw" / f"hwmon{index}"
            sensor.mkdir(parents=True)
            (sensor / "name").write_text("spd5118\n")
            (sensor / "temp1_input").write_text(f"{temp * 1000}\n")
        scope = root / "cg" / "scope"
        scope.mkdir(parents=True)
        (scope / "memory.peak").write_text(f"{300 * MIB}\n")
        (scope / "memory.swap.peak").write_text("0\n")
        (scope / "memory.events").write_text("oom_kill 0\n")
        (scope / "cgroup.procs").write_text("")
        (root / "out").mkdir()
        self.scope = scope

    def command(self, body: str) -> tuple[list[str], dict[str, str]]:
        preamble = (
            f'source "{COMMON}"; STATUS="{self.root}/status"; TEMPLOG="{self.root}/temp.log"; '
            'POLL_S=0.2; KILL_GRACE_S=1; : >> "$STATUS"; '
            "GUARDED_WORKLOAD=launcher; GUARDED_STAGE=stage_x; RUN=r1; RUN_RESOURCE_SCOPED=1; "
        )
        env = {
            "GUARDED_RUN_DIR": str(self.root),
            "DIMM_HWMON_ROOT": str(self.root / "hw"),
            "CGROUP_ROOT": str(self.root / "cg"),
            "RUN_RESOURCE_CGROUP": "/scope",
            "TEXTFILE_DIR": str(self.root / "out"),
            "PATH": "/usr/bin:/bin",
        }
        return ["bash", "-c", preamble + body], env

    def run(self, body: str) -> subprocess.CompletedProcess[str]:
        command, env = self.command(body)
        return subprocess.run(
            command, env=env, capture_output=True, text=True, check=False, timeout=60
        )

    def status(self) -> str:
        return (self.root / "status").read_text()

    def samples(self) -> dict[str, str]:
        text = (self.root / "out" / "run_resource_launcher_stage_x.prom").read_text()
        return dict(
            re.findall(
                r'^(run_resource_\w+)\{workload="launcher",stage="stage_x"(?:,run_id="r1")?\} (\S+)$',
                text,
                re.M,
            )
        )


def _alive(needle: str) -> bool:
    pattern = needle[:-1] + "[" + needle[-1] + "]"
    return (
        subprocess.run(["pgrep", "-f", pattern], capture_output=True, check=False).returncode == 0
    )


def test_a_normal_exit_emits_the_gauges_and_a_status_line(tmp_path: Path) -> None:
    lab = Lab(tmp_path, (41, 57))
    result = lab.run(f'run_guarded "{tmp_path}/o" bash -c "sleep 0.6; exit 7"; echo rc=$?')
    assert "rc=7" in result.stdout
    values = lab.samples()
    assert values["run_resource_exit_code"] == "7"
    assert values["run_resource_memory_peak_bytes"] == str(300 * MIB)
    line = next(x for x in lab.status().splitlines() if "run_resource workload=launcher" in x)
    assert "exit=7" in line and "memory_peak_gib=0.29" in line and "max_c=57" in line


def test_the_status_line_reads_only_the_polls_of_its_own_job(tmp_path: Path) -> None:
    lab = Lab(tmp_path, (41, 57))
    (tmp_path / "temp.log").write_text("2026-01-01T00:00:00Z pid=1 max_c=99 rss_mb=1 paused=0\n")
    lab.run(f'run_guarded "{tmp_path}/o" bash -c "sleep 0.6"')
    assert "max_c=57" in lab.status() and "max_c=99" not in lab.status()


def test_a_watchdog_kill_still_emits_with_exit_143(tmp_path: Path) -> None:
    lab = Lab(tmp_path, (101, 50))
    marker = f"32.{uuid.uuid4().int % 900 + 100}"  # unique: other sessions run sleeps of their own
    result = lab.run(f'run_guarded "{tmp_path}/o" sleep {marker}; echo rc=$?')
    assert "rc=143" in result.stdout
    assert lab.samples()["run_resource_exit_code"] == "143"
    assert not _alive(f"sleep {marker}")


def test_a_launcher_term_still_emits_with_exit_143(tmp_path: Path) -> None:
    lab = Lab(tmp_path)
    marker = f"31.{uuid.uuid4().int % 900 + 100}"
    command, env = lab.command(f'run_guarded "{tmp_path}/o" sleep {marker}')
    process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    for _ in range(100):
        if _alive(f"sleep {marker}"):
            break
        time.sleep(0.05)
    time.sleep(0.5)  # the trap is installed after the group's pgid is read
    process.send_signal(signal.SIGTERM)
    process.communicate(timeout=30)
    assert process.returncode == 143
    assert lab.samples()["run_resource_exit_code"] == "143"
    assert "launcher signalled" in lab.status()
    assert not _alive(f"sleep {marker}")


def test_a_shell_that_made_no_scope_never_reports_its_cgroup(tmp_path: Path) -> None:
    lab = Lab(tmp_path)
    command, env = lab.command(
        f'unset RUN_RESOURCE_SCOPED; run_guarded "{tmp_path}/o" sleep 0.5; echo rc=$?'
    )
    result = subprocess.run(
        command, env=env, capture_output=True, text=True, check=False, timeout=60
    )
    assert "rc=0" in result.stdout
    assert not list((tmp_path / "out").iterdir())
    assert "run_resource workload" not in lab.status()


def test_a_failed_report_is_logged_and_keeps_the_jobs_exit_code(tmp_path: Path) -> None:
    lab = Lab(tmp_path)
    (lab.scope / "memory.peak").unlink()
    result = lab.run(f'run_guarded "{tmp_path}/o" bash -c "sleep 0.3; exit 5"; echo rc=$?')
    assert "rc=5" in result.stdout
    assert "WARN run_resource_emit failed for stage stage_x" in lab.status()
    assert not list((tmp_path / "out").iterdir())


@pytest.mark.parametrize("launcher", LAUNCHERS)
def test_every_launcher_runs_in_a_scope_and_names_its_stage(launcher: str) -> None:
    path = OPS / launcher
    assert subprocess.run(["bash", "-n", str(path)], check=False).returncode == 0
    text = path.read_text()
    assert 'run_resource_scope bash "$0" "$@"' in text
    assert re.search(r"^\s*GUARDED_STAGE=\S+ run_guarded ", text, re.M)
    assert not re.search(r"^\s*run_guarded ", text, re.M)  # no job without a stage label
    assert text.index("run_resource_scope") > text.index("guarded_run_common.sh")


def test_the_pilot_check_path_is_not_scoped() -> None:
    lines = (OPS / "corpus_pilot.sh").read_text().splitlines()
    scoped = [line for line in lines if "run_resource_scope" in line and not line.startswith("#")]
    assert len(scoped) == 1 and scoped[0].startswith(
        '[ -n "$CHECK" ] || {'
    )  # a check writes nothing


def test_the_common_file_sources_the_tool_beside_it() -> None:
    assert (OPS.parents[1] / "tools" / "run_resource.sh").exists()
    assert '. "$REPO/tools/run_resource.sh"' in COMMON.read_text()
