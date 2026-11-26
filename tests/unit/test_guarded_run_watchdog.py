"""The guarded-run safety layer fails closed: DIMM watchdog state machine, sensor loss, TERM then KILL,
the nightly window, the blocking-timer gate and the heavy-job list (guarded-run runbook, gap list of 2026-11-25).

Every test sources `guarded_run_common.sh` against a fake hwmon tree and a private status file, so the
real `logs/` is never written. The watchdog is exercised with real child processes (`sleep` with a unique
duration) and a short poll interval."""

import subprocess
import time
import uuid
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "guarded_run_common.sh"


def _fake_hwmon(root: Path, temps_c: tuple[int, int] = (40, 40)) -> None:
    for index, temp in enumerate(temps_c):
        sensor = root / f"hwmon{index}"
        sensor.mkdir(parents=True)
        (sensor / "name").write_text("spd5118\n")
        (sensor / "temp1_input").write_text(f"{temp * 1000}\n")


def _command(tmp_path: Path, body: str) -> tuple[list[str], dict[str, str]]:
    """`body` with the common file sourced, private status and temperature logs, 0.2 s polls."""
    preamble = (
        f'source "{SCRIPT}"; STATUS="{tmp_path}/status"; TEMPLOG="{tmp_path}/temp.log"; '
        'POLL_S=0.2; KILL_GRACE_S=1; : >> "$STATUS"; '
    )
    env = {
        "GUARDED_RUN_DIR": str(tmp_path),
        "DIMM_HWMON_ROOT": str(tmp_path / "hw"),
        "PATH": "/usr/bin:/bin",
    }
    return ["bash", "-c", preamble + body], env


def _bash(tmp_path: Path, body: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    command, env = _command(tmp_path, body)
    return subprocess.run(
        command, env=env, capture_output=True, text=True, check=False, timeout=timeout
    )


def _status(tmp_path: Path) -> str:
    return (tmp_path / "status").read_text()


def _set_temp_later(tmp_path: Path, delay_s: float, millidegrees: str) -> str:
    """Shell snippet that rewrites the first sensor after a delay, in the background."""
    return f'( sleep {delay_s}; printf "%s\\n" "{millidegrees}" > "{tmp_path}/hw/hwmon0/temp1_input" ) &'


def _alive(needle: str) -> bool:
    """A process whose command line contains `needle` is running. The last character is bracketed so the
    pattern cannot match a shell whose own command line merely quotes it (a tool echoing the test source).
    """
    pattern = needle[:-1] + "[" + needle[-1] + "]"
    return (
        subprocess.run(["pgrep", "-f", pattern], capture_output=True, check=False).returncode == 0
    )


def test_common_file_parses() -> None:
    assert subprocess.run(["bash", "-n", str(SCRIPT)], check=False).returncode == 0


def test_dimm_max_c_reads_the_hottest_of_two_sensors(tmp_path: Path) -> None:
    _fake_hwmon(tmp_path / "hw", (41, 57))
    result = _bash(tmp_path, "dimm_max_c")
    assert result.returncode == 0
    assert result.stdout == "57"


@pytest.mark.parametrize("bad", ["", "n/a", "-"])
def test_dimm_max_c_refuses_an_unreadable_sensor(tmp_path: Path, bad: str) -> None:
    _fake_hwmon(tmp_path / "hw")
    (tmp_path / "hw" / "hwmon1" / "temp1_input").write_text(f"{bad}\n")
    result = _bash(tmp_path, "dimm_max_c")
    assert result.returncode == 1
    assert result.stdout == ""


def test_dimm_max_c_refuses_a_single_sensor(tmp_path: Path) -> None:
    _fake_hwmon(tmp_path / "hw")
    (tmp_path / "hw" / "hwmon1" / "temp1_input").unlink()
    assert _bash(tmp_path, "dimm_max_c").returncode == 1


def test_a_cool_run_returns_the_childs_exit_code(tmp_path: Path) -> None:
    _fake_hwmon(tmp_path / "hw")
    result = _bash(
        tmp_path, f'run_guarded "{tmp_path}/out" bash -c "sleep 0.6; exit 7"; echo rc=$?'
    )
    assert "rc=7" in result.stdout
    assert "ABORT" not in _status(tmp_path)
    assert "max_c=40" in (tmp_path / "temp.log").read_text()


def test_kill_temperature_aborts_with_143_and_empties_the_group(tmp_path: Path) -> None:
    _fake_hwmon(tmp_path / "hw", (101, 50))
    result = _bash(tmp_path, f'run_guarded "{tmp_path}/out" sleep 31.001; echo rc=$?')
    assert "rc=143" in result.stdout
    assert "ABORT watchdog killed" in _status(tmp_path)
    assert "DIMM at 101C" in _status(tmp_path)
    assert not _alive("sleep 31.001")


def test_stop_at_92_then_continue_at_80(tmp_path: Path) -> None:
    _fake_hwmon(tmp_path / "hw", (93, 50))
    body = (
        f'{_set_temp_later(tmp_path, 1.0, "70000")} '
        f'run_guarded "{tmp_path}/out" bash -c "sleep 1.5; exit 0"; echo rc=$?'
    )
    result = _bash(tmp_path, body)
    status = _status(tmp_path)
    assert "rc=0" in result.stdout
    assert "watchdog STOP at 93C" in status
    assert "watchdog CONT at 70C" in status
    assert "ABORT" not in status


def test_a_pause_longer_than_the_limit_kills_the_run(tmp_path: Path) -> None:
    _fake_hwmon(tmp_path / "hw", (93, 50))
    result = _bash(
        tmp_path, f'MAX_PAUSE_S=1; run_guarded "{tmp_path}/out" sleep 31.002; echo rc=$?'
    )
    assert "rc=143" in result.stdout
    assert "paused more than 1s" in _status(tmp_path)
    assert not _alive("sleep 31.002")


def test_a_lost_sensor_stops_then_kills_instead_of_running_on(tmp_path: Path) -> None:
    _fake_hwmon(tmp_path / "hw")
    body = (
        f'( sleep 0.5; rm "{tmp_path}/hw/hwmon1/temp1_input" ) & '
        f'run_guarded "{tmp_path}/out" sleep 31.003; echo rc=$?'
    )
    result = _bash(tmp_path, body)
    status = _status(tmp_path)
    assert "rc=143" in result.stdout
    assert "watchdog STOP: DIMM sensors unreadable" in status
    assert "DIMM sensors unreadable for 3 polls" in status
    assert not _alive("sleep 31.003")


def test_a_single_unreadable_poll_resumes_when_the_sensor_returns(tmp_path: Path) -> None:
    _fake_hwmon(tmp_path / "hw", (40, 40))
    body = (
        f'( sleep 0.3; : > "{tmp_path}/hw/hwmon0/temp1_input"; '
        f'until grep -q "STOP: DIMM sensors unreadable" "$STATUS"; do sleep 0.02; done; '
        f'printf "40000\\n" > "{tmp_path}/hw/hwmon0/temp1_input" ) & '
        f'run_guarded "{tmp_path}/out" bash -c "sleep 2; exit 0"; echo rc=$?'
    )
    result = _bash(tmp_path, body)
    status = _status(tmp_path)
    assert "rc=0" in result.stdout
    assert "watchdog STOP: DIMM sensors unreadable" in status
    assert "watchdog CONT at 40C" in status
    assert "ABORT" not in status


def test_a_child_that_ignores_term_is_killed_and_the_group_is_empty(tmp_path: Path) -> None:
    _fake_hwmon(tmp_path / "hw", (101, 50))
    result = _bash(
        tmp_path, f'run_guarded "{tmp_path}/out" bash -c \'trap "" TERM; sleep 31.004\'; echo rc=$?'
    )
    assert "rc=143" in result.stdout
    assert "escalated to KILL" in _status(tmp_path)
    assert "still has live members" not in _status(tmp_path)
    assert not _alive("sleep 31.004")


def test_an_unreadable_pgid_aborts_and_returns_1(tmp_path: Path) -> None:
    _fake_hwmon(tmp_path / "hw")
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "ps").write_text("#!/bin/sh\nexit 0\n")
    (stub / "ps").chmod(0o755)
    result = _bash(
        tmp_path, f'PATH="{stub}:$PATH"; run_guarded "{tmp_path}/out" sleep 31.005; echo rc=$?'
    )
    assert "rc=1" in result.stdout
    assert "ABORT cannot read pgid" in _status(tmp_path)
    time.sleep(0.3)
    assert not _alive("sleep 31.005")


@pytest.mark.parametrize(
    ("hour", "refused"),
    [("00", False), ("01", True), ("04", True), ("05", False), ("06", False), ("08", False)],
)
def test_window_gate_refuses_one_to_five_utc(tmp_path: Path, hour: str, refused: bool) -> None:
    result = _bash(tmp_path, f"NOW_H={hour}; window_gate; echo PASS")
    if refused:
        assert result.returncode == 3
        assert "nightly window (1:00 to 5:00Z)" in _status(tmp_path)
    else:
        assert result.returncode == 0
        assert "PASS" in result.stdout


def _stub_python(tmp_path: Path) -> Path:
    """A `python` that records its arguments; QUIESCE_RC makes `--quiesce` fail."""
    stub = tmp_path / "stub_python"
    stub.write_text(
        '#!/bin/sh\necho "$@" >> "$STUB_LOG"\n'
        'case "$*" in *--quiesce*) exit "${QUIESCE_RC:-0}";; esac\nexit 0\n'
    )
    stub.chmod(0o755)
    return stub


def _hold(
    tmp_path: Path, after: str, quiesce_rc: int = 0
) -> tuple[subprocess.CompletedProcess[str], str]:
    stub, log = _stub_python(tmp_path), tmp_path / "stub.log"
    log.write_text("")
    body = f'PY="{stub}"; export STUB_LOG="{log}" QUIESCE_RC={quiesce_rc}; hold_timers; {after}'
    return _bash(tmp_path, body), log.read_text()


def test_hold_timers_quiesces_and_the_exit_trap_releases_on_a_clean_exit(tmp_path: Path) -> None:
    result, calls = _hold(tmp_path, "exit 0")
    assert result.returncode == 0
    assert calls.splitlines() == [
        "-m services.corpus_rerun --quiesce",
        "-m services.corpus_rerun --release",
    ]
    assert "timers released (exit trap)" in _status(tmp_path)


def test_hold_timers_releases_after_a_failed_launch(tmp_path: Path) -> None:
    result, calls = _hold(tmp_path, 'fail "repro_frozen not bit-identical"')
    assert result.returncode == 3
    assert calls.splitlines()[-1] == "-m services.corpus_rerun --release"


def test_a_failed_quiesce_releases_and_stops_the_launch(tmp_path: Path) -> None:
    result, calls = _hold(tmp_path, "echo LAUNCHED", quiesce_rc=1)
    assert result.returncode == 3
    assert "LAUNCHED" not in result.stdout
    assert "quiesce failed" in _status(tmp_path)
    assert calls.splitlines().count("-m services.corpus_rerun --release") == 1


def _timers_gate(
    tmp_path: Path,
    is_active: str,
    units: str = "a.timer\nb.timer",
    load_state: str = "loaded",
    triggers_b: str = "b@yahoo.service",
) -> subprocess.CompletedProcess[str]:
    """A fake systemctl: timer a.timer triggers a.service, b.timer triggers `triggers_b` (a template instance)."""
    stub = tmp_path / "bin"
    stub.mkdir(exist_ok=True)
    (stub / "systemctl").write_text(
        "#!/bin/sh\n"
        'case "$1 $3" in\n'
        f'  "show LoadState") echo {load_state};;\n'
        '  "show Triggers") [ "$5" = b.timer ] && echo "' + triggers_b + '" || echo a.service;;\n'
        f'  "is-active "*) [ "$2" = "b@yahoo.service" ] && echo {is_active} || echo inactive;;\n'
        "esac\n"
    )
    (stub / "systemctl").chmod(0o755)
    body = f'PATH="{stub}:$PATH"; blocking_timer_units() {{ printf "{units}\\n"; }}; timers_gate; echo PASS'
    return _bash(tmp_path, body)


def test_timers_gate_passes_when_no_blocking_service_runs(tmp_path: Path) -> None:
    assert "PASS" in _timers_gate(tmp_path, "inactive").stdout


@pytest.mark.parametrize("state", ["active", "activating"])
def test_timers_gate_refuses_while_a_blocking_service_runs(tmp_path: Path, state: str) -> None:
    result = _timers_gate(tmp_path, state)
    assert result.returncode == 3
    assert "b@yahoo.service is running" in _status(tmp_path)


def test_timers_gate_refuses_an_empty_timer_list(tmp_path: Path) -> None:
    result = _timers_gate(tmp_path, "inactive", units="")
    assert result.returncode == 3
    assert "no blocking timers" in _status(tmp_path)


@pytest.mark.parametrize(
    "module",
    [
        "services.corpus_rerun",
        "backfill_feature_factory",
        "ic_sweep_recorder",
        "ops_member_verdicts_1d",
    ],
)
def test_heavy_job_pattern_names_the_corpus_runner_rebuild_sweep_and_verdict_refresh(
    tmp_path: Path, module: str
) -> None:
    result = _bash(
        tmp_path,
        f'printf "%s\\n" "python3 -m {module} --run-id x" | grep -Eq "$HEAVY_JOB_RE" && echo LIVE',
    )
    assert "LIVE" in result.stdout


def test_heavy_job_live_finds_a_matching_process(tmp_path: Path) -> None:
    token = f"tok_{uuid.uuid4().hex}"  # only this test produces it, so no real process can match
    decoy = subprocess.Popen(["python3", "-c", "import time; time.sleep(30)", token])
    try:
        result = _bash(tmp_path, f'HEAVY_JOB_RE="python.*{token}"; heavy_job_live && echo LIVE')
        assert "LIVE" in result.stdout
    finally:
        decoy.kill()
        decoy.wait()


def test_heavy_job_check_passes_when_nothing_matches(tmp_path: Path) -> None:
    # the bracket keeps the pattern from matching this very `bash -c` command line
    result = _bash(tmp_path, "HEAVY_JOB_RE='no_such_[p]rocess_xyz'; heavy_job_live || echo CLEAR")
    assert "CLEAR" in result.stdout


@pytest.mark.parametrize(
    ("load_state", "triggers_b", "message"),
    [
        ("not-found", "b@yahoo.service", "is not loaded"),
        ("loaded", "", "triggers 'no unit'"),
        ("loaded", "b@yahoo.service c.service", "expected exactly one service"),
    ],
)
def test_timers_gate_refuses_a_timer_it_cannot_resolve(
    tmp_path: Path, load_state: str, triggers_b: str, message: str
) -> None:
    result = _timers_gate(tmp_path, "inactive", load_state=load_state, triggers_b=triggers_b)
    assert result.returncode == 3
    assert message in _status(tmp_path)


def test_a_signalled_launcher_stops_its_group_and_exits_143(tmp_path: Path) -> None:
    _fake_hwmon(tmp_path / "hw", (93, 50))  # paused by the watchdog: the worst case to leave behind
    command, env = _command(tmp_path, f'run_guarded "{tmp_path}/out" sleep 31.006')
    launcher = subprocess.Popen(
        command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try:
        time.sleep(1.0)
        assert _alive("sleep 31.006")
        launcher.terminate()
        assert launcher.wait(timeout=20) == 143
    finally:
        if launcher.poll() is None:
            launcher.kill()
    assert "ABORT launcher signalled" in _status(tmp_path)
    assert not _alive("sleep 31.006")
