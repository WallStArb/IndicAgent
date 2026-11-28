"""Harness signals logger (tools/harness_signals.py, todo 685): sessions from the session records,
the summary and its coverage on planted JSONL, notes, the git facts, and that the timer's entry
point opens no database connection."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from tools import harness_signals as hs

T0 = datetime(2026, 11, 28, 0, 0, tzinfo=UTC)
REPO = Path(__file__).resolve().parents[2]
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def _record(pid: int, cwd: str, status: str, proc_start: str, **extra) -> dict:
    base = {
        "pid": pid,
        "cwd": cwd,
        "name": f"indicagent-{pid}",
        "status": status,
        "statusUpdatedAt": int(T0.timestamp() * 1000),
        "procStart": proc_start,
        "sessionId": "secret-id",
        "messagingSocketPath": "/run/x.sock",
    }
    return {**base, **extra}


def _write(directory: Path, name: str, record) -> None:
    (directory / f"{name}.json").write_text(json.dumps(record))


def test_sessions_of_this_project_with_gone_and_malformed_ones(tmp_path: Path) -> None:
    root, wt = Path("/home/bg/dev/indicagent"), Path("/home/bg/dev/indicagent-wt-x")
    _write(tmp_path, "1", _record(1, str(root), "idle", "100"))
    _write(tmp_path, "2", _record(2, str(wt / "sub"), "busy", "200"))
    _write(tmp_path, "3", _record(3, "/home/bg/dev/indicagentX", "busy", "300"))  # not a worktree
    _write(tmp_path, "4", _record(4, str(root), "idle", "400"))  # the pid now runs another process
    _write(tmp_path, "5", _record(5, str(root), "busy", "1", name=None))
    no_pid = {k: v for k, v in _record(6, str(root), "busy", "1").items() if k != "pid"}
    _write(tmp_path, "6", no_pid)
    _write(tmp_path, "7", _record(7, str(root), "busy", "1", statusUpdatedAt="soon"))
    _write(tmp_path, "8", [1, 2])
    (tmp_path / "9.json").write_text("{not json")
    starts = {1: "100", 2: "200", 4: "999", 7: "1"}
    found, unreadable = hs.sessions(tmp_path, [root, wt], starts.get)
    assert [(s["pid"], s["status"], s["alive"]) for s in found] == [
        (1, "idle", True),
        (2, "busy", True),
        (4, "idle", False),
        (7, "busy", True),
    ]
    assert found[0]["status_since"] == "2026-11-28T00:00:00Z" and found[3]["status_since"] is None
    assert unreadable == 4  # no name, no pid, a list, broken JSON: counted, never fatal
    assert all(set(s) == {"name", "pid", "status", "status_since", "alive"} for s in found)


def _snap(minute: int, statuses: dict[str, str], failed: list[str] | None = None) -> dict:
    return {
        "kind": "snapshot",
        "ts": hs._iso(T0 + timedelta(minutes=minute)),
        "sessions": [
            {"name": n, "pid": 1, "status": s, "status_since": None, "alive": s != "gone"}
            for n, s in statuses.items()
        ],
        "sessions_unreadable": 0,
        "claims": {"open": 0, "stale": 0},
        "origin_main": {
            "sha": f"sha{minute}",
            "ci": "fail" if failed else "pass",
            "failed_checks": failed or [],
        },
    }


def test_the_summary_pairs_idle_with_outcome_and_states_its_coverage(tmp_path: Path) -> None:
    log = tmp_path / "signals.jsonl"
    records = [
        _snap(-5, {"a": "busy"}),  # before the window: only its part inside counts
        _snap(5, {"a": "idle", "b": "busy"}),
        _snap(15, {"a": "idle", "b": "busy"}, failed=["Unit Tests"]),
        _snap(25, {"a": "busy", "b": "gone"}),
        _snap(35, {"a": "busy"}),
        _snap(135, {"a": "idle"}),  # 100 minutes after the last: the timer was off
        _snap(145, {"a": "idle"}),
        hs.note(T0 + timedelta(minutes=6), "owner_intervention", "poked a"),
        hs.note(T0 + timedelta(minutes=7), "review_test_gap", "no test of x"),
    ]
    for record in records:
        hs.append(log, record)
    with log.open("a") as handle:
        handle.write('{"kind": "snapsh')  # a torn last write
    read, torn = hs.read_log(log)
    assert torn == 1 and len(read) == len(records)
    commits = [T0 + timedelta(minutes=m) for m in (15, 25)] + [T0 - timedelta(days=9)]
    closed = [
        {
            "todo": "1-a.md",
            "closed_at": T0 + timedelta(minutes=25),
            "filed": date(2026, 11, 25),
            "priority": "P1",
        },
        {
            "todo": "2-b.md",
            "closed_at": T0 + timedelta(minutes=25),
            "filed": None,
            "priority": "P3",
        },
    ]
    now = T0 + timedelta(days=1)
    out = hs.summarize(read, commits, closed, now, days=1)
    # covered: 0-5 (the earlier snapshot's part), 5-35, 35-55 (held, the next is 100 minutes on)
    # and 135-165 (the last snapshot holds for two cadences): 85 of 1,440 minutes
    assert out["coverage"]["covered_share"] == round(85 / 1440, 3)
    assert out["coverage"]["last_snapshot_age_minutes"] == 1440 - 145
    # a: busy 0-5, idle 5-25, busy 25-55, idle 135-165; b: busy 5-25, then gone
    assert out["activity"]["idle_minutes_by_session"] == {"a": 50.0, "b": 0.0}
    assert out["activity"]["minutes_by_status"] == {"busy": 55.0, "idle": 50.0}
    assert out["activity"]["idle_minutes_per_covered_hour"] == round(50 / (85 / 60), 2)
    assert out["outcome"]["landings"] == 2 and out["outcome"]["todos_closed"] == 2
    assert out["outcome"]["p0_p1_closed"] == 1
    assert out["outcome"]["filed_to_closed_days_median"] == 3
    assert out["ci_red_commits"] == ["sha15"]
    assert out["notes"] == {"owner_intervention": 1, "review_test_gap": 1}


def test_a_dead_timer_reads_as_low_coverage_not_as_no_idle_time() -> None:
    """Two snapshots on day 1 of a 14-day window, then nothing: before the review of todo 685
    this read as a little idle time and no missing data."""
    records = [_snap(0, {"a": "idle"}), _snap(10, {"a": "idle"})]
    out = hs.summarize(records, [], [], T0 + timedelta(days=14), days=14)
    assert out["coverage"]["covered_share"] == round(30 / (14 * 1440), 3)
    assert out["coverage"]["last_snapshot_age_minutes"] == 14 * 1440 - 10
    empty = hs.summarize([], [], [], T0, days=7)
    assert empty["coverage"]["covered_share"] == 0
    assert empty["coverage"]["last_snapshot_age_minutes"] is None
    assert empty["activity"]["idle_minutes_per_covered_hour"] is None


def test_a_long_outage_between_few_snapshots_credits_nothing() -> None:
    """Gaps of 10 and 600 minutes: a median-based limit would have counted the outage."""
    records = [_snap(0, {"a": "idle"}), _snap(10, {"a": "idle"}), _snap(610, {"a": "idle"})]
    out = hs.summarize(records, [], [], T0 + timedelta(minutes=620), days=1)
    assert out["activity"]["idle_minutes_by_session"] == {"a": 40.0}  # 0-10, 10-30, 610-620


def test_the_cadence_is_the_timer_units() -> None:
    timer = hs.TIMER_UNIT.read_text()
    minutes = int(re.search(r"^OnCalendar=\*:0/(\d+)$", timer, re.M).group(1))
    assert timedelta(minutes=minutes) == hs.CADENCE


def test_a_summary_needs_a_day() -> None:
    with pytest.raises(ValueError, match="at least one day"):
        hs.summarize([], [], [], T0, days=0)
    with pytest.raises(SystemExit):
        hs.main(["--summary", "0"])


def test_a_note_class_comes_from_the_sop_list() -> None:
    assert hs.note(T0, "review_rule_breach", "x")["class"] == "review_rule_breach"
    with pytest.raises(ValueError, match="not one of"):
        hs.note(T0, "vibes", "x")


def _git(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **GIT_ENV},
    ).stdout.strip()


def _repo_with_origin(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "f").write_text("x")
    _git(repo, "add", "f")
    _git(repo, "commit", "-qm", "c")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "fetch", "-q", "origin")
    return repo


def test_ci_reds_are_finished_checks_that_did_not_pass_or_stand_aside(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _repo_with_origin(tmp_path)

    def runs(_repo, _sha):
        conclusions = [
            ("a", "success"),
            ("b", "cancelled"),
            ("c", "timed_out"),
            ("d", "failure"),
            ("e", "skipped"),
        ]
        return [{"name": n, "status": "completed", "conclusion": c} for n, c in conclusions]

    local = hs.origin_main(repo, runs)
    assert local["ci"] == "error" and local["fetch_ok"] is True  # a local remote is not GitHub
    monkeypatch.setattr(hs.ci_status, "repo_of", lambda url: "o/r")
    out = hs.origin_main(repo, runs)
    assert out["failed_checks"] == ["c", "d"] and out["ci"] == "fail"
    # a final verdict for the same sha is reused: no second read of the API
    again = hs.origin_main(repo, lambda *_: pytest.fail("read the API again"), {"origin_main": out})
    assert again["failed_checks"] == ["c", "d"]


def test_git_facts_read_a_closed_todo_as_its_closing_commit_wrote_it(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    pending = repo / ".planning" / "todos" / "pending"
    pending.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    todo = pending / "7-x.md"
    todo.write_text("---\nstatus: pending\npriority: P1\nfiled: 2026-11-20\n---\n\n# x\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "file 7")
    done = repo / ".planning" / "todos" / "completed"
    done.mkdir()
    _git(repo, "mv", str(todo), str(done / "7-x.md"))
    _git(repo, "commit", "-qm", "close 7")
    _git(repo, "rm", "-q", str(done / "7-x.md"))  # condensed away later
    _git(repo, "commit", "-qm", "delete 7")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    commits, closed = hs.git_facts(repo, datetime.now(UTC) - timedelta(days=1))
    assert len(commits) == 3
    assert [(c["todo"], c["filed"], c["priority"]) for c in closed] == [
        ("7-x.md", date(2026, 11, 20), "P1")
    ]


def test_the_timer_entry_point_loads_no_database_driver(tmp_path: Path) -> None:
    """The snapshot job as the timer runs it (logging, OTel, the snapshot), in a fresh process
    where every driver's connect entry point refuses (psycopg goes through libpq, below Python's
    sockets) and Python sockets refuse Postgres (TCP 5432 or its unix socket): the job still
    completes."""
    repo = _repo_with_origin(tmp_path)
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    _write(sessions, "1", _record(os.getpid(), str(repo), "busy", "x"))
    log = tmp_path / "signals.jsonl"
    code = f"""
import sys
from datetime import UTC, datetime
from pathlib import Path
sys.path.insert(0, {str(REPO)!r})
import socket
_connect = socket.socket.connect
def _refuse_postgres(self, address):
    target = address if isinstance(address, str) else address[1]
    if target == 5432 or ".s.PGSQL" in str(target):
        raise SystemExit("the harness logger connected to Postgres")
    return _connect(self, address)
socket.socket.connect = _refuse_postgres
def _refuse(*a, **k):
    raise SystemExit("the harness logger opened a database connection")
import asyncpg, psycopg
psycopg.connect = psycopg.Connection.connect = psycopg.AsyncConnection.connect = _refuse
asyncpg.connect = asyncpg.create_pool = _refuse
from tools import harness_signals as hs
hs.REPO_ROOT = Path({str(repo)!r})
hs.snapshot_job(Path({str(log)!r}), datetime.now(UTC), Path({str(sessions)!r}))
"""
    done = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, **GIT_ENV, "OTEL_SDK_DISABLED": "true"},
        timeout=120,
        cwd=tmp_path,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    (line,) = log.read_text().splitlines()
    record = json.loads(line)
    assert record["sessions"][0]["status"] == "busy" and record["origin_main"]["ci"] == "error"
