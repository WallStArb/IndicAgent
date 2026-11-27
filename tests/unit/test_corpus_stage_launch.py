"""The guarded corpus stage launcher (scripts/ops/corpus_stage_launch.sh): the pure preflight judge, then the
launch paths against stub psql, systemctl and python in the private repo copy the guarded-run tests build.

A stage that stops keeps the blocking timers held; a clean one releases them. The MemAvailable floor is read
from APR (infra.run_guarded.mem_floor_gib.stage_1d) and applied before the host gate.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit.test_guarded_run_launch_paths import RUN_ID, SCRIPTS, Lab, _commit

SCRIPT = SCRIPTS / "corpus_stage_launch.sh"
KEY = "0f593f92f8b4aaaa"
PREFIX = "0f593f92f8b4"
OK = ("1d", "completed", "", "abc", "abc", KEY, PREFIX)

# Prepended to the shared stubs: the run row, its steps, the floor key, a timer's state and the stage step.
_PSQL = """#!/bin/sh
[ -n "${PGPASSWORD:-}" ] || { echo "psql: error: connection to server failed: fe_sendauth: no password supplied" >&2; exit 2; }
case "$*" in
  *data_gate_scope*) echo "${SCOPE_NOW-1d}"; exit 0;;
  *"from corpus_run_step"*)
    case "$*" in
      *"step='pilot'"*) echo "${PILOT_STATUS-completed}";;
      *"step='feature_complete'"*) echo "${FC_STATUS-}";;
    esac
    exit 0;;
  *mem_floor_gib*) echo "${FLOOR_NOW-24}"; exit 0;;
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
  *--check*|*--quiesce*|*--release*) ;;
  *"--through feature_complete"*) echo "$*" >> "$STUB_LOG"; sleep 0.6; exit "${STAGE_RC:-0}";;
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


def _judge(*args: str) -> subprocess.CompletedProcess[str]:
    return _bash("stage_preflight_judge " + " ".join(f"'{a}'" for a in args))


def test_stage_launcher_parses() -> None:
    assert subprocess.run(["bash", "-n", str(SCRIPT)], check=False).returncode == 0


def test_a_ready_run_passes_the_stage_judge() -> None:
    assert _judge(*OK).returncode == 0


@pytest.mark.parametrize(
    ("index", "value", "message"),
    [
        (0, "all", "only a scope-1d run"),
        (1, "failed", "pilot step is 'failed'"),
        (1, "", "pilot step is ''"),
        (2, "completed", "feature_complete already completed"),
        (3, "def", "is not the run's code_commit"),
        (4, "", "is not the run's code_commit"),
        (5, "ffffffffffff", "does not start with"),
        (5, PREFIX, "does not start with"),  # a key equal to the prefix is not a full key
    ],
)
def test_each_stage_refusal_names_its_reason(index: int, value: str, message: str) -> None:
    args = list(OK)
    args[index] = value
    result = _judge(*args)
    assert result.returncode == 1
    assert message in result.stdout


class Stage(Lab):
    """The guarded-run lab plus the stage launcher and the stubs it reads."""

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
        self.env["STUB_KEY"] = KEY
        self.head = _commit(tmp_path / f"repo-corpus-run-{RUN_ID}")
        self.env["RECORDED_COMMIT"] = self.head
        (tmp_path / "meminfo").write_text("MemAvailable:   31457280 kB\n")  # 30 GiB

    def stage(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.repo / "scripts" / "ops" / SCRIPT.name), *args],
            env={**self.env, **env},
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )


@pytest.fixture
def stage(tmp_path: Path) -> Stage:
    return Stage(tmp_path)


def _launch(stage: Stage, **env: str) -> subprocess.CompletedProcess[str]:
    return stage.stage(RUN_ID, PREFIX, **env)


def _calls(stage: Stage, needle: str) -> list[str]:
    return [c for c in stage.calls() if needle in c]


def test_a_ready_run_stages_and_holds_the_timers_for_ic_measure(stage: Stage) -> None:
    result = _launch(stage)
    assert result.returncode == 0, stage.status_text()
    assert _calls(stage, f"--run-id {RUN_ID} --through feature_complete")
    assert not _calls(stage, "--release")
    text = stage.status_text()
    assert "timers held for ic_measure, release after it" in text and "mem floor 24 GiB" in text
    assert "stage=stage_1d" in text  # the run_resource gauge line for the stage


def test_a_failed_stage_holds_the_timers_and_keeps_its_exit_code(stage: Stage) -> None:
    result = _launch(stage, STAGE_RC="7")
    assert result.returncode == 7
    assert not _calls(stage, "--release")
    assert f"timers held: run {RUN_ID} (stage exit=7)" in stage.status_text()


def test_the_launch_never_quiesces_it_refuses_unquiesced_timers(stage: Stage) -> None:
    result = _launch(stage, STUB_ENABLED="enabled")
    assert result.returncode == 3
    assert "is not disabled or masked: quiesce first" in stage.status_text()
    assert not _calls(stage, "--through") and not _calls(stage, "--quiesce")


@pytest.mark.parametrize("state", ["enabled-runtime", "static", "linked", ""])
def test_a_timer_in_any_state_but_disabled_or_masked_refuses(stage: Stage, state: str) -> None:
    assert _launch(stage, STUB_ENABLED=state).returncode == 3
    assert "is not disabled or masked" in stage.status_text()


def test_a_masked_timer_passes(stage: Stage) -> None:
    assert _launch(stage, STUB_ENABLED="masked").returncode == 0, stage.status_text()


def test_a_floor_with_a_leading_zero_is_read_as_decimal(stage: Stage) -> None:
    assert _launch(stage, FLOOR_NOW="08").returncode == 0, stage.status_text()
    assert "mem floor 8 GiB" in stage.status_text()


def test_an_active_timer_refuses(stage: Stage) -> None:
    assert _launch(stage, STUB_TIMER_ACTIVE="active").returncode == 3
    assert "is active: quiesce first" in stage.status_text()


def test_the_floor_comes_from_apr_and_applies_before_the_host_gate(stage: Stage) -> None:
    # 30 GiB available: a 24 GiB floor passes (above), a 40 GiB floor refuses with the APR value in the message
    result = _launch(stage, FLOOR_NOW="40")
    assert result.returncode == 3
    assert "need 40 GiB" in stage.status_text()
    assert not _calls(stage, "--through")


@pytest.mark.parametrize("value", ["", "0", "1", "7", "513", "-5", "forty", "2.5"])
def test_an_unusable_floor_refuses(stage: Stage, value: str) -> None:
    assert _launch(stage, FLOOR_NOW=value).returncode == 3
    assert "is not a positive integer in APR" in stage.status_text()


def test_a_pilot_that_did_not_complete_refuses(stage: Stage) -> None:
    assert _launch(stage, PILOT_STATUS="failed").returncode == 3
    assert "pilot step is 'failed'" in stage.status_text()


def test_a_worktree_off_the_recorded_commit_refuses(stage: Stage) -> None:
    assert _launch(stage, RECORDED_COMMIT="deadbeef" * 5).returncode == 3
    assert "is not the run's code_commit" in stage.status_text()


def test_a_key_off_the_expected_prefix_refuses(stage: Stage) -> None:
    assert stage.stage(RUN_ID, "aaaaaaaaaaaa").returncode == 3
    assert "does not start with" in stage.status_text()


def test_a_missing_worktree_refuses(stage: Stage) -> None:
    shutil.rmtree(stage.root / f"repo-corpus-run-{RUN_ID}")
    assert _launch(stage).returncode == 3
    assert "no worktree" in stage.status_text()


def test_a_wrong_worker_count_refuses(stage: Stage) -> None:
    assert _launch(stage, WORKERS_NOW="12").returncode == 3
    assert "infra.feature_factory.workers is 12, expected 4" in stage.status_text()


def test_the_nightly_window_refuses(stage: Stage) -> None:
    assert _launch(stage, NOW_H="03").returncode == 3
    assert "inside the nightly window" in stage.status_text()


def test_a_run_id_that_is_not_a_uuid_refuses(stage: Stage) -> None:
    assert stage.stage("not-a-uuid", PREFIX).returncode == 3
    assert "is not a uuid" in stage.status_text()


def test_check_goes_on_after_a_missing_block2_comparison(stage: Stage) -> None:
    stage.status.write_text("")
    result = stage.stage("--check", RUN_ID, PREFIX, WORKERS_NOW="8")
    assert "REFUSED: no IDENTICAL block 2 comparison" in result.stdout
    assert "REFUSED: infra.feature_factory.workers is 8, expected 4" in result.stdout


def test_check_reports_every_refusal_and_writes_nothing(stage: Stage) -> None:
    before = stage.status_text()
    result = stage.stage(
        "--check",
        RUN_ID,
        PREFIX,
        STUB_ENABLED="enabled",
        PILOT_STATUS="failed",
        WORKERS_NOW="8",
        STUB_HEAVY="1",
    )
    assert result.returncode == 1
    for refusal in (
        "preflight: pilot step is 'failed', not completed",
        "a.timer is not disabled or masked: quiesce first",
        "infra.feature_factory.workers is 8, expected 4",
        "another heavy job is live",
    ):
        assert f"REFUSED: {refusal}" in result.stdout, result.stdout
    assert stage.status_text() == before
    assert not _calls(stage, "--through") and not list((stage.root / "textfile").iterdir())


def test_check_of_a_ready_run_runs_the_runner_check_and_exits_zero(stage: Stage) -> None:
    before = stage.status_text()
    result = stage.stage("--check", RUN_ID, PREFIX)
    assert result.returncode == 0, result.stdout
    assert "REFUSED" not in result.stdout
    assert _calls(stage, f"--run-id {RUN_ID} --check --step stage_1d")
    assert stage.status_text() == before and not _calls(stage, "--through")
