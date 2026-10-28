#!/usr/bin/env python3
"""The done-coding gate (CLAUDE.md, Done-Coding SOP): one command that decides what a change needs,
runs it in order, stops at the first failure, and records the result.

    .venv/bin/python tools/gate.py                  # classify the change, run what it needs
    .venv/bin/python tools/gate.py --dry-run        # print the plan only
    .venv/bin/python tools/gate.py --compare-all    # also the E17 parity gate (hours; locked)
    .venv/bin/python tools/gate.py --integration tests/integration/test_research_ledger.py

Run it from the worktree that holds the change (a detached scratch worktree off origin/main when
the shared checkout has other sessions' work in it; see docs/reference/gotchas.md). It compares
the working tree with the merge base against --base (default origin/main), so staged, unstaged,
untracked and already-committed-but-unpushed files all count.

What it decides, from the changed paths:
- migration numbers: a migration whose number another file already holds on origin/main, or that
  two changed files share, stops the gate before anything slow runs;
- the full unit suite (`pytest tests/unit -n auto`) for any change that is not text only;
- `repro_frozen` (must report bit-identical) when src/intelligence/research/, src/intelligence/
  statistics/ or the determinism scripts changed;
- `--compare-all` and `--integration` only when asked.

`repro_frozen` and `compare-all` run under one cross-session lock (logs/gate/parity.lock in the
main checkout), so two sessions never replay the frozen verdicts at once; a waiter prints who holds
it. Ruff, black, the duplicate-test and glossary checks are the pre-commit hook's job and are not
repeated here. Every run writes logs/gate/<stamp>_<head>/ with one log per step and result.json.

Exit 0: every step passed. Exit 1: a step failed or the plan is unsafe. Exit 2: bad usage.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

# Paths whose edits can move a recorded research verdict (CLAUDE.md, Frozen verdicts).
REPRO_PREFIXES = (
    "src/intelligence/research/",
    "src/intelligence/statistics/",
    "scripts/research/determinism/",
)
MIGRATION_DIR = "production/migrations/"
_MIGRATION_NUMBER = re.compile(r"^(\d+)_.+\.sql$")
LOCK_POLL_SECONDS = 15
LOCK_TIMEOUT_SECONDS = 8 * 3600


@dataclasses.dataclass(frozen=True)
class Plan:
    needs_repro: bool
    migrations: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class Step:
    name: str
    argv: tuple[str, ...]
    locked: bool = False
    expect: str | None = None  # text the output must contain (guards against a silent skip)


def classify(changed: Sequence[str]) -> Plan:
    return Plan(
        needs_repro=any(p.startswith(REPRO_PREFIXES) for p in changed),
        migrations=tuple(
            sorted(
                p
                for p in changed
                if p.startswith(MIGRATION_DIR) and p.endswith(".sql") and p.count("/") == 2
            )
        ),
    )


def migration_clashes(changed: Sequence[str], base_names: Sequence[str]) -> list[str]:
    """Why a changed migration's number is unsafe: held by a different file on the base, or shared
    with another changed migration. `base_names` are file names under production/migrations/."""
    held: dict[int, set[str]] = {}
    for name in base_names:
        match = _MIGRATION_NUMBER.match(name)
        if match:
            held.setdefault(int(match.group(1)), set()).add(name)
    problems, seen = [], {}
    for path in changed:
        name = Path(path).name
        match = _MIGRATION_NUMBER.match(name)
        if not match:
            problems.append(f"{path}: not named <number>_<name>.sql")
            continue
        number = int(match.group(1))
        if held.get(number, set()) - {name}:
            problems.append(
                f"{path}: number {number} is held on the base by {sorted(held[number] - {name})}"
            )
        if number in seen and seen[number] != name:
            problems.append(f"{path}: shares number {number} with {seen[number]}")
        seen[number] = name
    return problems


def build_steps(
    plan: Plan,
    python: str,
    *,
    repro_dir: str,
    logs: str,
    compare_all: bool,
    integration: Sequence[str],
) -> list[Step]:
    steps = [
        Step(
            "unit",
            (python, "-m", "pytest", "tests/unit/", "-n", "auto", "-q", "-p", "no:cacheprovider"),
        )
    ]
    if plan.needs_repro:
        steps.append(
            Step(
                "repro_frozen",
                (
                    python,
                    "-m",
                    "scripts.research.determinism.repro_frozen",
                    repro_dir,
                    "--logs",
                    logs,
                ),
                locked=True,
                expect="bit-identical",
            )
        )
    if compare_all:
        steps.append(
            Step(
                "compare_all",
                (python, "scripts/research/backfill_attempt_series.py", "--compare-all"),
                locked=True,
            )
        )
    if integration:
        steps.append(
            Step(
                "integration",
                (python, "-m", "pytest", "-q", "-p", "no:cacheprovider", *integration),
            )
        )
    return steps


@contextlib.contextmanager
def parity_lock(
    path: Path, who: str, *, timeout: float, poll: float = LOCK_POLL_SECONDS
) -> Iterator[None]:
    """Hold an exclusive cross-process lock on `path`, waiting up to `timeout` seconds and saying
    who holds it. The holder's note is advisory; the flock is the lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    deadline = time.monotonic() + timeout
    waited = False
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as error:
                if time.monotonic() >= deadline:
                    holder = os.pread(fd, 400, 0).decode(errors="replace").strip()
                    raise TimeoutError(
                        f"parity lock still held after {timeout:.0f}s by: {holder}"
                    ) from error
                if not waited:
                    holder = os.pread(fd, 400, 0).decode(errors="replace").strip()
                    print(
                        f"  waiting for the parity lock, held by: {holder or 'unknown'}", flush=True
                    )
                    waited = True
                time.sleep(poll)
        os.ftruncate(fd, 0)
        os.pwrite(fd, f"{who} pid {os.getpid()} since {datetime.now(UTC).isoformat()}".encode(), 0)
        yield
    finally:
        with contextlib.suppress(OSError):
            os.ftruncate(fd, 0)
        os.close(fd)  # closing releases the flock


def run_step(step: Step, cwd: Path, log: Path) -> dict:
    started = time.monotonic()
    with log.open("w") as out:
        proc = subprocess.run(step.argv, cwd=cwd, stdout=out, stderr=subprocess.STDOUT, check=False)
    text = log.read_text(errors="replace")
    ok = proc.returncode == 0 and (step.expect is None or step.expect in text)
    return {
        "step": step.name,
        "ok": ok,
        "returncode": proc.returncode,
        "seconds": round(time.monotonic() - started, 1),
        "log": str(log),
        **({} if step.expect is None or step.expect in text else {"missing": step.expect}),
    }


def run_steps(
    steps: Sequence[Step],
    cwd: Path,
    logdir: Path,
    lock_path: Path,
    *,
    lock_timeout: float = LOCK_TIMEOUT_SECONDS,
) -> list[dict]:
    """Run in order; stop at the first failure. A locked step waits for the parity lock."""
    logdir.mkdir(parents=True, exist_ok=True)
    results = []
    for step in steps:
        print(f"[gate] {step.name} ...", flush=True)
        log = logdir / f"{step.name}.log"
        if step.locked:
            with parity_lock(lock_path, f"{step.name} in {cwd}", timeout=lock_timeout):
                result = run_step(step, cwd, log)
        else:
            result = run_step(step, cwd, log)
        results.append(result)
        print(
            f"[gate] {step.name}: {'ok' if result['ok'] else 'FAILED'} ({result['seconds']}s) {log}",
            flush=True,
        )
        if not result["ok"]:
            break
    return results


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout


def changed_paths(cwd: Path, base: str) -> tuple[list[str], str]:
    """(paths changed against the merge base, including untracked files; the base commit)."""
    merge_base = _git(cwd, "merge-base", base, "HEAD").strip()
    tracked = _git(cwd, "diff", "--name-only", merge_base).split("\n")
    untracked = _git(cwd, "ls-files", "--others", "--exclude-standard").split("\n")
    return sorted({p for p in (*tracked, *untracked) if p}), merge_base


def main_checkout(cwd: Path) -> Path:
    """The primary checkout (the one holding .git), where shared logs live."""
    common = Path(_git(cwd, "rev-parse", "--git-common-dir").strip())
    return (common if common.is_absolute() else cwd / common).resolve().parent


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--dry-run", action="store_true", help="print the plan and run nothing")
    parser.add_argument("--compare-all", action="store_true", help="add the E17 parity gate")
    parser.add_argument(
        "--integration", nargs="+", default=[], metavar="TEST", help="add these integration tests"
    )
    args = parser.parse_args(argv)

    cwd = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    subprocess.run(["git", "-C", str(cwd), "fetch", "-q", "origin"], check=False)
    changed, merge_base = changed_paths(cwd, args.base)
    if not changed:
        print("[gate] nothing changed against", args.base)
        return 1
    plan = classify(changed)
    clashes = migration_clashes(
        plan.migrations,
        [
            Path(p).name
            for p in _git(cwd, "ls-tree", "--name-only", args.base, MIGRATION_DIR).split("\n")
            if p
        ],
    )
    for problem in clashes:
        print(f"[gate] migration: {problem}")
    if clashes:
        return 1

    root = main_checkout(cwd)
    logs = root / "logs"
    head = _git(cwd, "rev-parse", "--short", "HEAD").strip()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    logdir = logs / "gate" / f"{stamp}_{head}"
    with tempfile.TemporaryDirectory(prefix="gate_repro_") as repro_dir:
        steps = build_steps(
            plan,
            sys.executable,
            repro_dir=repro_dir,
            logs=str(logs),
            compare_all=args.compare_all,
            integration=args.integration,
        )
        print(f"[gate] {len(changed)} changed file(s) against {args.base} @ {merge_base[:9]}")
        print(
            "[gate] plan: "
            + ", ".join(s.name for s in steps)
            + (" (migrations: " + ", ".join(plan.migrations) + ")" if plan.migrations else "")
        )
        if args.dry_run:
            return 0
        results = run_steps(steps, cwd, logdir, logs / "gate" / "parity.lock")
    ok = len(results) == len(steps) and all(r["ok"] for r in results)
    record = {
        "head": _git(cwd, "rev-parse", "HEAD").strip(),
        "base": merge_base,
        "changed": changed,
        "plan": [s.name for s in steps],
        "results": results,
        "ok": ok,
    }
    (logdir / "result.json").write_text(json.dumps(record, indent=2))
    print(f"[gate] {'PASSED' if ok else 'FAILED'}: {logdir / 'result.json'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
