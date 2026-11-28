#!/usr/bin/env python3
"""Harness signals logger (todo 685; docs/foundation/harness-improvement-sop.md, step 1 "Instrument").

    .venv/bin/python tools/harness_signals.py                      # one snapshot (the timer runs this)
    .venv/bin/python tools/harness_signals.py --note owner_intervention "poked an idle session"
    .venv/bin/python tools/harness_signals.py --summary 7          # the retro's input, as JSON

Appends one JSON line per run to logs/harness/signals.jsonl (append-only, git-ignored):
- a snapshot: every Claude Code session of this project (cwd in one of its git worktrees), from the
  records Claude Code keeps in ~/.claude/sessions/<pid>.json: name, status (`busy` working, `idle`
  waiting for input, `shell` running a shell command) and since when; gone when the process is no
  longer the recorded one. Malformed records are counted, never fatal. Then the open and stale
  todo claims (tools/todo_claims.py), and origin/main's sha with the CI checks that finished red
  (tools/ci_status.py; a cancelled check is a superseded push, not a red).
- a note: what no tool can see, written by the lead: an owner intervention or a review finding by
  class (NOTE_CLASSES, the SOP's signal list).

The summary pairs activity (minutes per status, idle minutes per session and per covered hour)
with outcome (landings per day on origin/main, todos closed, P0 and P1 closed, filed-to-closed
days), CI red commits and notes, and states its coverage: the share of the window the snapshots
cover. A dead timer shows as low coverage and an old last snapshot, never as zero idle time.

Read-only on the system: no database connection, no run touched; it writes only its log, its own
service log and the refs `git fetch` updates. It stores names, statuses, counts and timestamps,
never transcript content.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from tools import ci_status, todo_claims  # noqa: E402

LOG_PATH = REPO_ROOT / "logs" / "harness" / "signals.jsonl"
SESSIONS_DIR = Path.home() / ".claude" / "sessions"
TIMER_UNIT = REPO_ROOT / "tools" / "systemd-user" / "indicagent-harness-signals.timer"
JOB = "harness-signals"
# The timer's cadence (OnCalendar=*:0/10 in TIMER_UNIT; a test binds the two). A snapshot's state
# holds for at most two cadences: a longer gap is the timer being off, and credits nothing.
CADENCE = timedelta(minutes=10)
HOLD = 2 * CADENCE
GIT_TIMEOUT_S = 60  # a hung fetch must not keep the oneshot active and stop the timer
# The SOP's signal list (one definition): what a lead's note may record.
NOTE_CLASSES = (
    "owner_intervention",
    "review_correctness",
    "review_rule_breach",
    "review_stale_doc",
    "review_test_gap",
)
IDLE = "idle"
# Check conclusions that are not a red: a pass, a superseded push, a skipped or informational job.
_NOT_RED = frozenset({"success", "cancelled", "skipped", "neutral"})
_COMPLETED = re.compile(r"^\.planning/todos/completed/(\d+-[^/]+\.md)$")


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_S,
    ).stdout


def _proc_start(pid: int) -> str | None:
    """The process's start time in clock ticks (field 22 of /proc/<pid>/stat), None when gone."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return stat.rsplit(")", 1)[1].split()[19]  # fields after the command name, 22nd overall


def worktrees(root: Path) -> list[Path]:
    """Every worktree of this repo (the main checkout first), from git."""
    listing = _git(root, "worktree", "list", "--porcelain")
    prefix = "worktree "
    return [Path(line[len(prefix) :]) for line in listing.splitlines() if line.startswith(prefix)]


def _session(record: Any, proc_start: Callable[[int], str | None]) -> dict[str, Any]:
    """One session's state; raises on a record that lacks a field the summary needs."""
    pid, name, status = record["pid"], record["name"], record["status"]
    if not (isinstance(pid, int) and isinstance(name, str) and isinstance(status, str)):
        raise TypeError("pid, name and status must be an int and two strings")
    since = record.get("statusUpdatedAt")
    return {
        "name": name,
        "pid": pid,
        "status": status,
        "status_since": (
            _iso(datetime.fromtimestamp(since / 1000, UTC))
            if isinstance(since, int | float)
            else None
        ),
        "alive": proc_start(pid) == str(record.get("procStart")),
    }


def sessions(
    sessions_dir: Path,
    project_dirs: Sequence[Path],
    proc_start: Callable[[int], str | None] = _proc_start,
) -> tuple[list[dict[str, Any]], int]:
    """(the sessions whose cwd is one of `project_dirs` or below it, the count of records that
    could not be read): a malformed record is counted, never fatal."""
    roots = [str(p) for p in project_dirs]
    found, unreadable = [], 0
    for path in sorted(sessions_dir.glob("*.json")):
        try:
            record = json.loads(path.read_text())
            cwd = str(record.get("cwd", ""))
            if not any(cwd == r or cwd.startswith(r + "/") for r in roots):
                continue
            found.append(_session(record, proc_start))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            unreadable += 1
    return found, unreadable


def claim_counts(todos_dir: Path, now: datetime) -> dict[str, int]:
    found = todo_claims.claims(todos_dir, now)
    return {"open": len(found), "stale": sum(todo_claims.is_stale(c, now) for c in found)}


def _last_record(path: Path) -> dict[str, Any] | None:
    """The log's last complete line, read from its tail (the log only grows)."""
    if not path.exists():
        return None
    with path.open("rb") as handle:
        handle.seek(0, 2)
        handle.seek(max(handle.tell() - 65536, 0))
        lines = handle.read().decode("utf-8", "replace").splitlines()
    for line in reversed(lines):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def origin_main(
    root: Path,
    fetch_runs: Callable[[str, str], list[dict]],
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """origin/main's sha (after a fetch) and its CI: the verdict and the checks that finished red.
    A final verdict already logged for the same sha is reused, which saves the shared GitHub
    quota; an API error is recorded, not raised."""
    try:
        subprocess.run(
            ["git", "-C", str(root), "fetch", "-q", "origin"],
            check=True,
            capture_output=True,
            timeout=GIT_TIMEOUT_S,
        )
        fetched = True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        fetched = False
    sha = _git(root, "rev-parse", "origin/main").strip()
    known = (previous or {}).get("origin_main") or {}
    # reuse a pass, or a fail with a named red; a fail from a cancelled check alone (no red) can
    # still turn red later on the same sha, so it is read again
    settled = known.get("ci") == "pass" or (
        known.get("ci") == "fail" and known.get("failed_checks")
    )
    if known.get("sha") == sha and settled:
        return {**known, "fetch_ok": fetched}
    try:
        repo = ci_status.repo_of(_git(root, "remote", "get-url", "origin"))
        runs = fetch_runs(repo, sha)
    except (ci_status.ApiError, subprocess.SubprocessError, OSError) as error:
        return {"sha": sha, "ci": "error", "error": str(error)[:200], "fetch_ok": fetched}
    red = sorted(
        r["name"]
        for r in runs
        if r.get("status") == "completed" and r.get("conclusion") not in _NOT_RED
    )
    return {"sha": sha, "ci": ci_status.verdict(runs), "failed_checks": red, "fetch_ok": fetched}


def snapshot(
    now: datetime,
    sessions_dir: Path,
    root: Path,
    fetch_runs: Callable[[str, str], list[dict]] = ci_status.fetch_runs,
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    found, unreadable = sessions(sessions_dir, worktrees(root))
    return {
        "kind": "snapshot",
        "ts": _iso(now),
        "sessions": found,
        "sessions_unreadable": unreadable,
        "claims": claim_counts(root / ".planning" / "todos", now),
        "origin_main": origin_main(root, fetch_runs, previous),
    }


def note(now: datetime, note_class: str, text: str) -> dict[str, Any]:
    if note_class not in NOTE_CLASSES:
        raise ValueError(f"note class {note_class!r} is not one of {NOTE_CLASSES}")
    return {"kind": "note", "ts": _iso(now), "class": note_class, "text": text}


def append(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def read_log(path: Path) -> tuple[list[dict[str, Any]], int]:
    """(the records, the count of lines that could not be parsed, such as a torn last write)."""
    if not path.exists():
        return [], 0
    records, torn = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            torn += 1
    return records, torn


# ---------------------------------------------------------------------------
# The summary (pure over the log and the git facts it is given)
# ---------------------------------------------------------------------------


def credited(
    snapshots: Sequence[Mapping[str, Any]], start: datetime, end: datetime
) -> tuple[dict[str, dict[str, float]], float]:
    """({session: {status: minutes}}, covered minutes) inside [start, end]. A snapshot's state
    holds until the next snapshot or for HOLD, whichever is first: the rest of a longer gap is
    the timer being off and covers nothing. A snapshot taken before `start` counts for its part inside
    the window; a gone session credits nothing."""
    ordered = sorted(snapshots, key=lambda s: s["ts"])
    out: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    covered = 0.0
    for index, snap in enumerate(ordered):
        begin = _parse(snap["ts"])
        stop = begin + HOLD  # the last snapshot, or one before a gap, holds for HOLD only
        if index + 1 < len(ordered):
            stop = min(stop, _parse(ordered[index + 1]["ts"]))
        lo, hi = max(begin, start), min(stop, end)
        if hi <= lo:
            continue
        minutes = (hi - lo).total_seconds() / 60
        covered += minutes
        for session in snap["sessions"]:
            if session["alive"]:
                out[session["name"]][session["status"]] += minutes
    return {name: dict(by_status) for name, by_status in out.items()}, covered


def summarize(
    records: Sequence[Mapping[str, Any]],
    commits: Sequence[datetime],
    closed: Sequence[Mapping[str, Any]],
    now: datetime,
    days: int,
) -> dict[str, Any]:
    """The retro's input for the window [now - days, now]: activity paired with outcome, and how
    much of the window the snapshots cover."""
    if days < 1:
        raise ValueError("a summary covers at least one day")
    start = now - timedelta(days=days)
    snaps = [r for r in records if r["kind"] == "snapshot" and _parse(r["ts"]) <= now]
    minutes, covered = credited(snaps, start, now)
    by_status: Counter[str] = Counter()
    for per_session in minutes.values():
        by_status.update(per_session)
    inside = [r for r in records if start <= _parse(r["ts"]) <= now]
    in_snaps = [r for r in inside if r["kind"] == "snapshot"]
    last = max((_parse(s["ts"]) for s in snaps), default=None)
    covered_hours = covered / 60
    reds = sorted(
        {s["origin_main"]["sha"] for s in in_snaps if s["origin_main"].get("failed_checks")}
    )
    landed = [c for c in commits if start <= c <= now]
    closed_in = [c for c in closed if start <= c["closed_at"] <= now]
    lead_days = [
        (c["closed_at"].date() - c["filed"]).days for c in closed_in if c.get("filed") is not None
    ]
    idle = by_status.get(IDLE, 0.0)
    return {
        "window": {"start": _iso(start), "end": _iso(now), "days": days},
        "coverage": {
            "snapshots": len(in_snaps),
            "covered_share": round(covered / (days * 24 * 60), 3),
            "last_snapshot_age_minutes": (
                round((now - last).total_seconds() / 60, 1) if last else None
            ),
            "sessions_unreadable": sum(s.get("sessions_unreadable", 0) for s in in_snaps),
        },
        "activity": {
            "minutes_by_status": {k: round(v, 1) for k, v in sorted(by_status.items())},
            # a rate needs at least one cadence of coverage: seconds of it would read as noise
            "idle_minutes_per_covered_hour": (
                round(idle / covered_hours, 2) if covered >= CADENCE.total_seconds() / 60 else None
            ),
            "idle_minutes_by_session": {
                name: round(m.get(IDLE, 0.0), 1) for name, m in sorted(minutes.items())
            },
        },
        "outcome": {
            "landings": len(landed),
            "landings_per_day": round(len(landed) / days, 2),
            "todos_closed": len(closed_in),
            "p0_p1_closed": sum(c.get("priority") in ("P0", "P1") for c in closed_in),
            "filed_to_closed_days_median": statistics.median(lead_days) if lead_days else None,
        },
        "ci_red_commits": reds,
        "notes": dict(sorted(Counter(r["class"] for r in inside if r["kind"] == "note").items())),
    }


# ---------------------------------------------------------------------------
# Git facts for the summary (read-only)
# ---------------------------------------------------------------------------


def git_facts(root: Path, since: datetime) -> tuple[list[datetime], list[dict[str, Any]]]:
    """Commits on origin/main since `since`, and each todo that entered completed/ there: its
    closing commit time, and its `filed` date and priority as that commit wrote them."""
    log = _git(
        root, "log", "origin/main", f"--since={_iso(since)}", "--format=@%H %cI", "--name-status"
    )
    commits: list[datetime] = []
    closed: list[dict[str, Any]] = []
    sha = ""
    for line in log.splitlines():
        if line.startswith("@"):
            sha, when = line[1:].split(" ", 1)
            commits.append(_parse(when))
            continue
        parts = line.split("\t")
        if not parts[0] or parts[0][0] not in "AR" or not commits:
            continue
        match = _COMPLETED.match(parts[-1])
        if not match:
            continue
        fields = dict(todo_claims.frontmatter(_git(root, "show", f"{sha}:{parts[-1]}")))
        try:
            filed = date.fromisoformat(fields.get("filed", ""))
        except ValueError:
            filed = None
        closed.append(
            {
                "todo": match[1],
                "closed_at": commits[-1],
                "filed": filed,
                "priority": fields.get("priority"),
            }
        )
    return commits, closed


def _days(value: str) -> int:
    days = int(value)
    if days < 1:
        raise argparse.ArgumentTypeError("a summary covers at least one day")
    return days


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Harness signals logger (todo 685)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--note", nargs=2, metavar=("CLASS", "TEXT"), help=f"one of {NOTE_CLASSES}")
    mode.add_argument("--summary", type=_days, metavar="DAYS", help="print the retro summary")
    parser.add_argument("--log", type=Path, default=LOG_PATH)
    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    if args.summary is not None:
        records, torn = read_log(args.log)
        commits, closed = git_facts(REPO_ROOT, now - timedelta(days=args.summary))
        out = summarize(records, commits, closed, now, args.summary)
        out["coverage"]["log_lines_unreadable"] = torn
        print(json.dumps(out, indent=2))
        return 0
    if args.note is not None:
        append(args.log, note(now, *args.note))
        return 0
    return snapshot_job(args.log, now, SESSIONS_DIR)


def snapshot_job(log_path: Path, now: datetime, sessions_dir: Path) -> int:
    """One snapshot, with the oneshot's job_completed_total and structlog line."""
    import structlog

    from src.core.service_utils import setup_service_logging
    from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
    from src.observability.otel import OTelInitError, init_otel_providers

    setup_service_logging(str(REPO_ROOT / "logs" / "harness_signals.log"))
    logger = structlog.get_logger("harness_signals")
    try:
        init_otel_providers(service_name=JOB)
    except OTelInitError as error:
        logger.warning("harness_signals.otel_init_failed", error=str(error))
    status = "success"
    try:
        record = snapshot(now, sessions_dir, REPO_ROOT, previous=_last_record(log_path))
        append(log_path, record)
        logger.info(
            "harness_signals.snapshot",
            sessions=len(record["sessions"]),
            unreadable=record["sessions_unreadable"],
            ci=record["origin_main"]["ci"],
        )
    except Exception as error:
        status = "failure"
        logger.error("harness_signals.fatal_error", error=str(error))
        raise
    finally:
        JOB_COMPLETED_TOTAL.add(1, {"job": JOB, "status": status})
        flush_and_shutdown_metrics()
    return 0


if __name__ == "__main__":
    sys.exit(main())
