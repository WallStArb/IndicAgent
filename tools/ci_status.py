#!/usr/bin/env python3
"""CI status of a commit from the GitHub check-runs API (unauthenticated), for hosts without gh.

    .venv/bin/python tools/ci_status.py                  # origin/main, one read
    .venv/bin/python tools/ci_status.py --wait           # poll until every check has finished
    .venv/bin/python tools/ci_status.py <sha-or-ref> --wait --timeout 1200

Prints one line per check: name, status, conclusion. Exit 0 only when every check is completed and
successful. Exit 1: a check finished without success (failure, cancelled, ...), or the commit has no
checks at all after the wait. Exit 3: checks still running (or none yet) when the read, or the
--wait timeout, ended. Exit 2: bad usage, or the API answered with an error (a private repository
or an unknown commit answers 404, and the unauthenticated limit is 60 reads an hour, so the poll
interval is 20 s by default).

A superseded push is cancelled by the workflow's concurrency group, so a cancelled check on an old
commit is not a failure of the code; read the newest commit.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence

API = "https://api.github.com/repos/{repo}/commits/{sha}/check-runs?per_page=100"
POLL_SECONDS = 20
TIMEOUT_SECONDS = 900
_REMOTE = re.compile(r"github\.com[:/](?P<repo>[^/]+/[^/]+?)(?:\.git)?$")

PASS, FAIL, PENDING, NONE = "pass", "fail", "pending", "none"
EXIT = {PASS: 0, FAIL: 1, NONE: 1, PENDING: 3}


class ApiError(RuntimeError):
    pass


def repo_of(remote_url: str) -> str:
    """'owner/name' from an ssh or https GitHub remote URL."""
    match = _REMOTE.search(remote_url.strip())
    if not match:
        raise ApiError(f"not a GitHub remote: {remote_url!r}")
    return match["repo"]


def verdict(runs: Sequence[dict]) -> str:
    """fail as soon as any check finished without success; pass only when all are completed and
    successful; pending while any is still running; none when the commit has no checks."""
    if not runs:
        return NONE
    if any(r["status"] == "completed" and r["conclusion"] != "success" for r in runs):
        return FAIL
    return PASS if all(r["status"] == "completed" for r in runs) else PENDING


def render(runs: Sequence[dict]) -> str:
    return "\n".join(
        f"{r['name']:<28} {r['status']:<12} {r['conclusion'] or '-'}"
        for r in sorted(runs, key=lambda r: r["name"])
    )


def fetch_runs(repo: str, sha: str, opener: Callable = urllib.request.urlopen) -> list[dict]:
    request = urllib.request.Request(
        API.format(repo=repo, sha=sha), headers={"Accept": "application/vnd.github+json"}
    )
    try:
        with opener(request, timeout=20) as response:
            body = json.load(response)
    except urllib.error.HTTPError as error:
        raise ApiError(f"GitHub answered {error.code} for {repo}@{sha[:9]}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise ApiError(f"GitHub unreachable: {error}") from error
    runs = body["check_runs"]
    if body["total_count"] > len(runs):
        raise ApiError(f"{body['total_count']} checks, only {len(runs)} read (one page)")
    return runs


def wait_for(
    read: Callable[[], list[dict]],
    *,
    timeout: float,
    poll: float = POLL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[str, list[dict]]:
    """Read until the verdict is final (pass or fail) or the timeout ends; the last read comes back
    either way. A commit with no checks is retried like a pending one: the workflow may not have
    started yet."""
    deadline = clock() + timeout
    while True:
        runs = read()
        state = verdict(runs)
        if state in (PASS, FAIL) or clock() + poll > deadline:
            return state, runs
        sleep(poll)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "ref", nargs="?", default="origin/main", help="sha or ref (default origin/main)"
    )
    parser.add_argument("--wait", action="store_true", help="poll until every check has finished")
    parser.add_argument("--timeout", type=float, default=TIMEOUT_SECONDS, help="seconds to wait")
    parser.add_argument("--poll", type=float, default=POLL_SECONDS, help="seconds between reads")
    args = parser.parse_args(argv)

    try:
        subprocess.run(["git", "fetch", "-q", "origin"], check=False)
        sha = _git("rev-parse", args.ref)
        repo = repo_of(_git("remote", "get-url", "origin"))

        def read() -> list[dict]:
            return fetch_runs(repo, sha)

        if args.wait:
            state, runs = wait_for(read, timeout=args.timeout, poll=args.poll)
        else:
            runs = read()
            state = verdict(runs)
    except (ApiError, subprocess.CalledProcessError) as error:
        print(f"[ci_status] {error}", file=sys.stderr)
        return 2
    print(f"[ci_status] {repo}@{sha[:9]}: {state}")
    if runs:
        print(render(runs))
    return EXIT[state]


if __name__ == "__main__":
    sys.exit(main())
