#!/usr/bin/env python3
"""Todo claims (PLANNING-SYSTEM.md, "Claiming a todo"): each claim, its problems, its staleness.

    .venv/bin/python tools/todo_claims.py        # the lead loop runs this

Read-only. Prints one line per claimed todo (file, worker, claimed_at, age), then one per problem:
a malformed claim (`parse_claim`, also held for the repo by
tests/unit/test_todo_priorities_link_integrity.py) or a stale one (claimed_at older than
STALE_DAYS; a worker still on it renews by rewriting claimed_at). Exit 0 when there is no problem,
1 otherwise. Staleness is reported here and never tested in the suite, so an abandoned claim
cannot turn an unrelated worker's suite red.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

TODOS_DIR = Path(__file__).resolve().parent.parent / ".planning" / "todos"
STALE_DAYS = 3
CLOCK_SKEW = timedelta(minutes=5)
CLAIM_KEYS = ("claimed_by", "claimed_at")

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
# a claim-looking line (also indented, bulleted or quoted) in the head of a todo: its line-1
# block, or without one the lines before the first heading or blank line; the body is prose
_CLAIM_LINE = re.compile(rf"^[\s>*-]*[\"']?({'|'.join(CLAIM_KEYS)})[\"']?\s*:", re.M)
_HEAD_END = re.compile(r"^(?:#|\s*$)", re.M)
_SESSION_NAME = re.compile(r"indicagent-[a-z0-9]+")  # a ListAgents name, e.g. indicagent-03


@dataclass
class Claim:
    todo: str  # path under the todos dir, e.g. "pending/598-....md"
    fields: dict[str, str]
    claimed_at: datetime | None  # None when claimed_at is not a UTC ISO time
    errors: tuple[str, ...]


def _utc_time(value: str) -> datetime | None:
    """An ISO time with a zero UTC offset, or None (unparsable, naive or another offset)."""
    try:
        at = datetime.fromisoformat(value)
    except ValueError:
        return None
    return at if at.utcoffset() == timedelta(0) else None


def frontmatter(text: str) -> list[tuple[str, str]]:
    """Top-level `key: value` pairs of the frontmatter block on line 1, in order and with
    duplicates kept (quotes and trailing comments stripped); empty when there is no block."""
    match = _FRONTMATTER.match(text)
    pairs = []
    for line in match[1].splitlines() if match else ():
        key, sep, value = line.partition(":")
        if sep and key and not key[0].isspace():
            pairs.append((key.strip(), value.split(" #", 1)[0].strip().strip("'\"")))
    return pairs


def parse_claim(todo: str, text: str, now: datetime) -> Claim | None:
    """The claim in one todo file with every rule it breaks, or None when it carries no claim."""
    block = _FRONTMATTER.match(text)
    head_end = _HEAD_END.search(text)
    head = block[0] if block else text[: head_end.start() if head_end else len(text)]
    claim_lines = _CLAIM_LINE.findall(head)
    if not claim_lines:
        return None
    pairs = frontmatter(text)
    keys = [key for key, _value in pairs]
    fields = dict(pairs)
    errors = []
    if misplaced := [key for key in CLAIM_KEYS if claim_lines.count(key) != keys.count(key)]:
        errors.append(
            f"{' and '.join(misplaced)} outside the line-1 frontmatter or not a plain top-level key"
        )
    if duplicated := sorted({key for key in (*CLAIM_KEYS, "claimable") if keys.count(key) > 1}):
        errors.append(f"more than one {' and '.join(duplicated)} line (one claim per todo)")
    if not todo.startswith("pending/") or fields.get("claimable", "").lower() != "true":
        errors.append("a claim outside pending/ or without claimable: true")
    worker = fields.get("claimed_by", "")
    if not _SESSION_NAME.fullmatch(worker):
        errors.append(f"claimed_by {worker!r} is not a session name")
    at = _utc_time(fields.get("claimed_at", ""))
    if at is None:
        errors.append("claimed_at is not a UTC ISO time")
    elif at > now + CLOCK_SKEW:
        errors.append("claimed_at is in the future")
    return Claim(todo, fields, at, tuple(errors))


def claims(todos_dir: Path, now: datetime) -> list[Claim]:
    found = []
    for path in sorted(todos_dir.glob("*/*.md")):
        claim = parse_claim(
            path.relative_to(todos_dir).as_posix(), path.read_text(encoding="utf-8"), now
        )
        if claim is not None:
            found.append(claim)
    return found


def is_stale(claim: Claim, now: datetime) -> bool:
    return claim.claimed_at is not None and now - claim.claimed_at > timedelta(days=STALE_DAYS)


def main(todos_dir: Path = TODOS_DIR) -> int:
    now = datetime.now(UTC)
    problems = []
    found = claims(todos_dir, now)
    for claim in found:
        worker, at = claim.fields.get("claimed_by"), claim.fields.get("claimed_at")
        age = (
            f"{max(now - claim.claimed_at, timedelta(0)) / timedelta(hours=1):.1f} h"
            if claim.claimed_at
            else "?"
        )
        print(f"{claim.todo}  {worker}  claimed {at}  age {age}")
        problems += [f"{claim.todo}: {error}" for error in claim.errors]
        if is_stale(claim, now):
            problems.append(
                f"{claim.todo}: stale, age {age} > {STALE_DAYS * 24} h, release or renew it"
            )
    print(f"{len(found)} claim(s), {len(problems)} problem(s)")
    for problem in problems:
        print(f"PROBLEM {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
