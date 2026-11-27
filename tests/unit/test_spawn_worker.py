"""scripts/ops/spawn_worker.sh against stub git, psql, pgrep and claude: every refusal, one stubbed spawn,
--list and --reap. Nothing real is spawned and no database or repository is touched."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "spawn_worker.sh"
KIB_PER_GIB = 1024 * 1024
BRIEF = """GOAL: land the thing.
STATE: todo 700, origin/main abc.
SCOPE (in a detached worktree):
1. edit the file.
FAILURE MODES: none known.
GATES: ruff, the touched tests.
BOUNDARIES: no src/.
REPORT (under 200 words): the sha.
"""

_GIT = """#!/bin/sh
echo "git $*" >> "$STUB_LOG"
[ "$1" = -C ] && shift 2
case "$1" in
  fetch) exit 0;;
  ls-tree) echo ".planning/todos/pending/700-x.md"; exit 0;;
  rev-parse) echo 0123456789abcdef; exit 0;;
  worktree) [ "$2" = add ] && mkdir -p "$5"; [ "$2" = list ] && exit 0; [ "$2" = remove ] && for last; do :; done && rm -rf "$last"; exit 0;;
  status) [ -n "${DIRTY:-}" ] && echo "$DIRTY"; printf '!! tools/__pycache__/\n!! .ruff_cache/\n'; exit 0;;
  show) [ -n "${CLAIMED:-}" ] && printf -- '---\nclaimed_by: indicagent-03\n---\n'; exit 0;;
  branch) exit 0;;
  cherry) [ -n "${UNLANDED:-}" ] && echo "+ 0123 the work"; exit 0;;
esac
exit 1
"""
_PSQL = """#!/bin/sh
case "$*" in
  *"'infra.spawn_worker.max_workers'"*) echo "${MAX_ROW-2|1|8}";;
  *"'infra.spawn_worker.mem_margin_gib'"*) echo "${MARGIN_ROW-8|2|64}";;
  *"like 'infra.run_guarded.mem_floor_gib.%'"*) echo infra.run_guarded.mem_floor_gib.stage_1d;;
  *mem_floor_gib*) echo "${FLOOR-24|8|512}";;
  *) exit 2;;
esac
"""
_PGREP = '#!/bin/sh\nexit "${HEAVY_RC:-1}"\n'
_CLAUDE = (
    '#!/bin/sh\necho "$*" > "$STUB_DIR/claude_args"; cat > "$STUB_DIR/claude_stdin"\n'
    'env | grep -cE "^CLAUDE(CODE|_CODE_)" > "$STUB_DIR/claude_env"\n'
    'touch "$STUB_DIR/claude_done"\n'
)


@pytest.fixture
def lab(tmp_path: Path):
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, body in {"git": _GIT, "psql": _PSQL, "pgrep": _PGREP, "claude": _CLAUDE}.items():
        (stubs / name).write_text(body)
        (stubs / name).chmod(0o755)
    (tmp_path / "brief.md").write_text(BRIEF)
    return tmp_path


def _run(lab: Path, *args: str, gib: float = 40.0, **env: str) -> subprocess.CompletedProcess[str]:
    (lab / "meminfo").write_text(f"MemAvailable: {int(gib * KIB_PER_GIB)} kB\n")
    base = {
        "PATH": f"{lab / 'stubs'}:/usr/bin:/bin",
        "MEMINFO": str(lab / "meminfo"),
        "SPAWN_AGENTS_DIR": str(lab / "agents"),
        "SPAWN_WORKTREE_ROOT": str(lab / "wt"),
        "CLAUDE_BIN": str(lab / "stubs" / "claude"),
        "STUB_LOG": str(lab / "calls.log"),
        "STUB_DIR": str(lab),
        "CLAUDECODE": "1",
        "CLAUDE_CODE_SESSION_ID": "lead",
    }
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        env=base | env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def _spawn(
    lab: Path, brief: str = "brief.md", mode: str = "acceptEdits", **kw: str | float
) -> subprocess.CompletedProcess[str]:
    return _run(
        lab,
        *("--name", "w1", "--todo", "700", "--brief", str(lab / brief)),
        *("--model", "sonnet", "--permission-mode", mode),
        **kw,
    )


def _wait_for_the_stub_claude(lab: Path) -> None:
    """The stub exits at once after reading its stdin; wait for its marker."""
    for _ in range(100):
        if (lab / "claude_done").exists():
            return
        time.sleep(0.05)
    raise AssertionError("the stub claude never ran")


def _registry(lab: Path) -> list[dict]:
    path = lab / "agents" / "workers.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def _assert_refused(result: subprocess.CompletedProcess[str], lab: Path, needle: str) -> None:
    assert result.returncode == 3, result.stdout + result.stderr
    assert needle in result.stdout
    assert not (lab / "claude_args").exists(), "a refused spawn started claude"
    assert "worktree add" not in (lab / "calls.log").read_text()
    assert _registry(lab) == []


def test_spawn_worker_script_parses():
    assert subprocess.run(["bash", "-n", str(SCRIPT)], check=False).returncode == 0


@pytest.mark.parametrize(
    "part", ["GOAL", "STATE", "SCOPE", "FAILURE MODES", "GATES", "BOUNDARIES", "REPORT"]
)
def test_a_brief_missing_a_part_is_refused(lab, part):
    text = "\n".join(line for line in BRIEF.splitlines() if not line.startswith(part))
    (lab / "short.md").write_text(text)
    _assert_refused(_spawn(lab, brief="short.md"), lab, part.lower()[:5])


def test_the_cap_counts_live_recorded_workers(lab):
    start = Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(") ", 1)[1].split()[19]
    (lab / "agents").mkdir()
    live = {"event": "spawned", "name": "old", "todo": 1, "pid": os.getpid(), "pid_start": start}
    (lab / "agents" / "workers.jsonl").write_text(
        json.dumps(live | {"worktree": "x", "started": "t"}) + "\n"
    )
    result = _spawn(lab, MAX_ROW="1|1|8")
    assert result.returncode == 3
    assert "1 live worker(s), cap infra.spawn_worker.max_workers = 1" in result.stdout
    assert not (lab / "claude_args").exists()


def test_memory_under_the_live_runs_floor_plus_margin_is_refused(lab):
    # heavy job live: floor 24 + margin 8 = 32 GiB
    _assert_refused(_spawn(lab, gib=31.5, HEAVY_RC="0"), lab, "need 32 GiB")


def test_without_a_heavy_job_only_the_margin_applies(lab):
    assert _spawn(lab, gib=9.0).returncode == 0


@pytest.mark.parametrize(
    ("env", "needle"),
    [
        ({"MAX_ROW": ""}, "missing or not an integer"),
        ({"MAX_ROW": "9|1|8"}, "outside [1, 8]"),
        ({"MARGIN_ROW": "x|2|64"}, "missing or not an integer"),
    ],
)
def test_a_missing_or_out_of_bounds_apr_key_refuses(lab, env, needle):
    _assert_refused(_spawn(lab, **env), lab, needle)


def test_all_refusals_are_reported_at_once(lab):
    (lab / "short.md").write_text("GOAL: x\n")
    result = _spawn(lab, brief="short.md", gib=1.0, MAX_ROW="")
    assert result.stdout.count("REFUSED:") == 3


@pytest.mark.parametrize("mode", ["", "yolo", "manual", "plan"])
def test_the_permission_mode_has_no_default(lab, mode):
    result = _spawn(lab, mode=mode)
    assert result.returncode == 2
    assert "--permission-mode is required" in result.stderr


def test_a_spawn_records_the_worker_and_passes_the_brief_on_stdin(lab):
    result = _spawn(lab)
    assert result.returncode == 0, result.stdout + result.stderr
    (record,) = _registry(lab)
    assert record["event"] == "spawned" and record["name"] == "w1" and record["todo"] == 700
    assert record["worktree"] == str(lab / "wt" / "indicagent-wt-w1")
    assert record["permission_mode"] == "acceptEdits" and record["base"] == "0123456789abcdef"
    _wait_for_the_stub_claude(lab)
    assert (lab / "claude_stdin").read_text() == BRIEF
    args = (lab / "claude_args").read_text()
    assert "--model sonnet --permission-mode acceptEdits -n w1" in args and "GOAL" not in args
    assert (lab / "claude_env").read_text().strip() == "0"  # no caller session identity
    # the name is now taken
    assert "already recorded" in _spawn(lab).stdout


def test_list_and_reap_keep_a_dirty_worktree_and_reap_a_clean_one(lab):
    assert _spawn(lab).returncode == 0
    _wait_for_the_stub_claude(lab)
    listed = _run(lab, "--list").stdout
    assert "w1\ttodo 700\tpid" in listed and "\tfinished\t" in listed
    for dirty in (" M file", "!! logs/result.json"):
        assert "keep w1: dirty" in _run(lab, "--reap", DIRTY=dirty).stdout
    assert (lab / "wt" / "indicagent-wt-w1").is_dir()
    assert "reaped w1" in _run(lab, "--reap").stdout
    assert [r["event"] for r in _registry(lab)] == ["spawned", "reaped"]
    assert "0 worker(s) not reaped" in _run(lab, "--list").stdout


def test_a_record_with_an_empty_start_time_reads_finished_and_its_worktree_is_reaped(lab):
    wt = lab / "wt" / "indicagent-wt-quick"
    wt.mkdir(parents=True)
    (lab / "agents").mkdir()
    dead = subprocess.Popen(["true"])
    dead.wait()
    quick = {"event": "spawned", "name": "quick", "todo": 700, "pid": dead.pid, "pid_start": ""}
    (lab / "agents" / "workers.jsonl").write_text(
        json.dumps(quick | {"worktree": str(wt), "started": "t"}) + "\n"
    )
    assert f"\tfinished\tstarted t\t{wt}" in _run(lab, "--list").stdout
    assert "keep quick: not landed on origin/main" in _run(lab, "--reap", UNLANDED="1").stdout
    assert "reaped quick" in _run(lab, "--reap").stdout
    assert not wt.exists()


def test_an_unreadable_registry_refuses_instead_of_counting_zero(lab):
    (lab / "agents").mkdir()
    (lab / "agents" / "workers.jsonl").write_text('{"event": "spawned", "name": "x"\n')
    result = _spawn(lab)
    assert result.returncode == 3 and "cannot read" in result.stdout
    assert not (lab / "claude_args").exists()


def test_a_missing_claude_binary_is_refused(lab):
    _assert_refused(_spawn(lab, CLAUDE_BIN=str(lab / "nope")), lab, "no claude binary")


def test_unreadable_floors_while_a_heavy_job_is_live_refuse(lab):
    (lab / "stubs" / "psql").write_text(
        _PSQL.replace("echo infra.run_guarded.mem_floor_gib.stage_1d;;", "exit 2;;")
    )
    _assert_refused(_spawn(lab, HEAVY_RC="0"), lab, "cannot read the guarded-run floors")


def test_a_spawned_worker_does_not_hold_the_lock(lab):
    (lab / "stubs" / "claude").write_text("#!/bin/sh\nexec sleep 3\n")
    assert _spawn(lab).returncode == 0
    listed = _run(lab, "--reap")
    assert "keep w1: still running" in listed.stdout, listed.stdout + listed.stderr


def test_a_todo_claimed_on_origin_main_is_refused(lab):
    _assert_refused(_spawn(lab, CLAIMED="1"), lab, "claimed by another session")


def test_a_second_worker_on_the_same_todo_is_refused(lab):
    (lab / "stubs" / "claude").write_text("#!/bin/sh\nexec sleep 3\n")
    assert _spawn(lab).returncode == 0
    result = _run(
        lab,
        *("--name", "w2", "--todo", "700", "--brief", str(lab / "brief.md")),
        *("--model", "sonnet", "--permission-mode", "acceptEdits"),
    )
    assert result.returncode == 3 and "worker w1 holds todo 700 until it is reaped" in result.stdout


def test_a_brief_may_name_its_parts_in_the_template_wording(lab):
    (lab / "long.md").write_text(
        BRIEF.replace("STATE:", "State with ids:")
        .replace("FAILURE MODES:", "Failure modes by name:")
        .replace("GOAL:", "(1) Goals:")
        .replace("GATES:", "Gate:")
    )
    assert _spawn(lab, brief="long.md").returncode == 0
