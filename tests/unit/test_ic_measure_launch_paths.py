"""The guarded first-IC-measure launcher (scripts/ops/ic_measure_launch.sh) end to end against stubs: the blocking
timers stay held on every failure path and are released only by a clean exit (lead ruling 2026-11-27), and the
MemAvailable floor comes from APR (infra.run_guarded.mem_floor_gib.ic_measure) before the host gate.
"""

from __future__ import annotations

import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

from tests.unit.test_guarded_run_launch_paths import RUN_ID, SCRIPTS, Lab, _commit

SCRIPT = SCRIPTS / "ic_measure_launch.sh"
KEY = "0f593f92f8b4aaaa"
PREFIX = "0f593f92f8b4"

_PSQL = """#!/bin/sh
case "$*" in
  *data_gate_scope*) echo "1d"; exit 0;;
  *"from corpus_run_step"*)
    case "$*" in
      *"step='pilot'"*|*"step='feature_complete'"*) echo "completed";;
    esac
    exit 0;;
  *mem_floor_gib.ic_measure*) [ -z "${FLOOR_RC:-}" ] || exit "$FLOOR_RC"; echo "${FLOOR_NOW-24}"; exit 0;;
esac
exec "$BASE_STUBS/psql" "$@"
"""
_PYTHON = """#!/bin/sh
case "$*" in
  *--quiesce*) [ -z "${QUIESCE_SLEEP:-}" ] || sleep "$QUIESCE_SLEEP";;
  *--check*|*--release*) ;;
  *"--through ic_measure"*) echo "$*" >> "$STUB_LOG"; sleep 0.6; exit "${IC_RC:-0}";;
esac
exec "$BASE_STUBS/python" "$@"
"""


class IcLab(Lab):
    """The guarded-run lab plus the IC measure launcher and the stubs it reads."""

    def __init__(self, tmp_path: Path) -> None:
        super().__init__(tmp_path)
        shutil.copy(SCRIPT, self.repo / "scripts" / "ops" / SCRIPT.name)
        base = tmp_path / "base_bin"
        base.mkdir()
        shutil.move(self.stubs / "psql", base / "psql")
        (self.stubs / "psql").write_text(_PSQL)
        (self.stubs / "psql").chmod(0o755)
        python = self.repo / ".venv" / "bin" / "python"
        shutil.move(python, base / "python")
        python.write_text(_PYTHON)
        python.chmod(0o755)
        self.env["BASE_STUBS"] = str(base)
        self.env["STUB_KEY"] = KEY
        self.head = _commit(tmp_path / f"repo-corpus-run-{RUN_ID}")
        self.env["RECORDED_COMMIT"] = self.head
        (tmp_path / "meminfo").write_text("MemAvailable:   31457280 kB\n")  # 30 GiB

    def launch(self, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.repo / "scripts" / "ops" / SCRIPT.name), RUN_ID, PREFIX],
            env={**self.env, **env},
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def calls_with(self, needle: str) -> list[str]:
        return [c for c in self.calls() if needle in c]


@pytest.fixture
def ic(tmp_path: Path) -> IcLab:
    return IcLab(tmp_path)


def test_a_clean_ic_measure_releases_the_timers(ic: IcLab) -> None:
    result = ic.launch()
    assert result.returncode == 0, ic.status_text()
    assert ic.calls_with(f"--run-id {RUN_ID} --through ic_measure")
    assert len(ic.calls_with("--release")) == 1
    assert "timers released" in ic.status_text()


def test_a_failed_ic_measure_holds_the_timers_and_keeps_its_exit_code(ic: IcLab) -> None:
    result = ic.launch(IC_RC="7")
    assert result.returncode == 7
    assert not ic.calls_with("--release")
    assert f"timers held: run {RUN_ID} (ic_measure exit=7)" in ic.status_text()


def test_a_failed_quiesce_holds_the_timers_instead_of_releasing_them(ic: IcLab) -> None:
    result = ic.launch(QUIESCE_RC="1")
    assert result.returncode == 3
    assert not ic.calls_with(
        "--release"
    )  # releasing would re-enable them between feature_complete and the IC measure
    text = ic.status_text()
    assert "quiesce failed: the timer set may be only partly quiesced, nothing was released" in text
    assert f"bash {ic.repo}/scripts/ops/ic_measure_launch.sh {RUN_ID} {PREFIX}" in text
    assert not ic.calls_with("--through ic_measure")


def test_ic_floor_comes_from_apr_and_applies_before_the_host_gate(ic: IcLab) -> None:
    assert ic.launch(FLOOR_NOW="24").returncode == 0  # 30 GiB available passes a 24 GiB floor
    refused = ic.launch(FLOOR_NOW="40")
    assert refused.returncode == 3
    assert "only 30.00 GiB available, need 40 GiB" in ic.status_text()


@pytest.mark.parametrize(
    "value", ["", "abc", "7", "513", "-5", "24.5", "0", "0000", "18446744073709551656", "1000"]
)
def test_ic_unusable_floor_refuses(ic: IcLab, value: str) -> None:
    result = ic.launch(FLOOR_NOW=value)
    assert result.returncode == 3
    assert (
        "infra.run_guarded.mem_floor_gib.ic_measure is not an integer from 8 to 512"
        in ic.status_text()
    )
    assert not ic.calls_with("--through ic_measure")


def test_ic_floor_with_a_leading_zero_is_read_as_decimal(ic: IcLab) -> None:
    assert ic.launch(FLOOR_NOW="08").returncode == 0


def test_an_unreachable_apr_refuses_the_floor_read(ic: IcLab) -> None:
    result = ic.launch(FLOOR_RC="1")
    assert result.returncode == 3 and not ic.calls_with("--through ic_measure")


def test_the_read_only_preflight_reports_an_unusable_floor(ic: IcLab) -> None:
    assert ic.launch(PREFLIGHT_ONLY="1", FLOOR_NOW="24").returncode == 0
    refused = ic.launch(PREFLIGHT_ONLY="1", FLOOR_NOW="abc")
    assert (
        refused.returncode == 3 and "mem_floor_gib.ic_measure is not an integer" in refused.stdout
    )


def test_the_hold_line_gives_runnable_absolute_commands(ic: IcLab) -> None:
    ic.launch(IC_RC="7")
    text = ic.status_text()
    assert f"bash {ic.repo}/scripts/ops/ic_measure_launch.sh {RUN_ID} {PREFIX}" in text
    assert f"cd {ic.repo} && " in text and "--release (only after the run is abandoned)" in text


def test_the_read_only_preflight_probes_the_user_scope(ic: IcLab) -> None:
    refused = ic.launch(PREFLIGHT_ONLY="1", SYSTEMD_RUN_RC="1")
    assert refused.returncode == 3
    assert (
        "no user scope with memory accounting and a writable textfile directory" in refused.stdout
    )


def test_family10_preflight_only_refuses_early_when_no_scope_can_start(ic: IcLab) -> None:
    shutil.copy(SCRIPTS / "family10_launch.sh", ic.repo / "scripts" / "ops" / "family10_launch.sh")
    refused = subprocess.run(
        ["bash", str(ic.repo / "scripts" / "ops" / "family10_launch.sh")],
        env={**ic.env, "PREFLIGHT_ONLY": "1", "SYSTEMD_RUN_RC": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert refused.returncode == 3
    assert "no user scope with memory accounting" in refused.stdout
    assert "battery ok" not in refused.stdout  # before the fetch, the worktree and the static gates


@pytest.mark.parametrize(
    "name",
    ["corpus_pilot.sh", "corpus_stage_launch.sh", "ic_measure_launch.sh", "family10_launch.sh"],
)
def test_every_check_form_calls_the_one_scope_gate(name: str) -> None:
    text = (SCRIPTS / name).read_text()
    calls = [
        line
        for line in text.splitlines()
        if re.search(r"(^|[\s;{(])scope_gate\b", line) and not line.lstrip().startswith("#")
    ]
    assert calls, name
    assert (
        "run_resource_scope_check" not in text
    ), name  # the probe is called only through the helper


def test_the_read_only_preflight_says_which_gates_it_did_not_run(ic: IcLab) -> None:
    result = ic.launch(PREFLIGHT_ONLY="1")
    assert result.returncode == 0
    assert (
        "read-only form: database, worktree, floor, window, live-process and user-scope checks only"
        in result.stdout
    )
    assert not ic.calls_with("--quiesce") and not ic.calls_with("--release")


def test_a_term_during_the_measure_logs_the_hold_and_the_resume_command(ic: IcLab) -> None:
    process = subprocess.Popen(
        ["bash", str(ic.repo / "scripts" / "ops" / SCRIPT.name), RUN_ID, PREFIX],
        env=ic.env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    poll_log = (
        ic.repo / "logs" / "family10_dimm_temp.log"
    )  # run_guarded writes a line once its trap is armed
    for _ in range(400):
        if ic.calls_with("--through ic_measure") and poll_log.exists() and poll_log.stat().st_size:
            break
        time.sleep(0.05)
    else:
        process.kill()
        pytest.fail("the measure never reached its first watchdog poll")
    process.send_signal(signal.SIGTERM)
    process.communicate(timeout=30)
    assert process.returncode == 143
    assert not ic.calls_with("--release")
    assert f"bash {ic.repo}/scripts/ops/ic_measure_launch.sh {RUN_ID} {PREFIX}" in ic.status_text()


def test_a_failed_release_after_a_clean_measure_is_loud(ic: IcLab) -> None:
    result = ic.launch(RELEASE_RC="1")
    assert result.returncode == 4
    text = ic.status_text()
    assert "WARN the IC measure is complete but --release failed" in text
    assert (
        "resume with" not in text.split("WARN the IC measure")[1]
    )  # a finished run is not resumed


def test_ic_unreachable_apr_is_named_as_such(ic: IcLab) -> None:
    refused = ic.launch(FLOOR_RC="1", PREFLIGHT_ONLY="1")
    assert refused.returncode == 3 and "database unreachable" in refused.stdout


def test_a_term_during_the_quiesce_leaves_the_resume_command(ic: IcLab) -> None:
    process = subprocess.Popen(
        ["bash", str(ic.repo / "scripts" / "ops" / SCRIPT.name), RUN_ID, PREFIX],
        env={**ic.env, "QUIESCE_SLEEP": "2"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    for _ in range(200):
        if "quiesce" in ic.status_text().splitlines()[-1]:
            break
        time.sleep(0.05)
    process.send_signal(signal.SIGTERM)
    process.communicate(timeout=30)
    assert f"bash {ic.repo}/scripts/ops/ic_measure_launch.sh {RUN_ID} {PREFIX}" in ic.status_text()
    assert not ic.calls_with("--release")
