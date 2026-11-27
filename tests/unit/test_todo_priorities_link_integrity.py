"""CI guard: every file under .planning/todos/pending/ must have a matching
[N](pending/<file>) link somewhere in .planning/todos/PRIORITIES.md, and every
such link must point to a file that actually exists.

PRIORITIES.md's own preamble states it is "the single source of truth for
todo-level prioritization" -- a pending todo with no table row is invisible to
anyone scanning the P0-P3 tables, and a link pointing at a moved/renamed file
is a silent dead end. This exact drift class was caught by manual `ls pending/`
vs. link-diff audits at least 5 times before this guard existed (2026-08-11,
2026-08-13, 2026-08-21 x2, 2026-08-26) -- most consequentially todo 335, filed
self-tagged priority:P0 but missing from the file entirely for two days while
it was actively corrupting a multi-day-running corpus job. Per this project's
"automate manual tasks" principle, a recurring manual-audit finding this many
times qualifies for a CI-enforced check, matching the existing precedent of
test_migration_number_uniqueness.py (todo 101) and
test_compressed_hypertable_migration_vacuum_check.py (todo 305).

Detection-only, same discipline as test_migration_number_uniqueness.py: this
test does not add missing rows or fix dead links, it only fails fast so drift
never again accumulates silently between manual audits.

CI-clean: no DB, no network -- pure filesystem + regex scan (the stale-claim check reads git log;
it skips in CI, without git and on shallow history).
"""

from __future__ import annotations

import functools
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.unit._allow_list_scan import stale_allow_list_entries, unexpected_violations

_REPO_ROOT = Path(__file__).parent.parent.parent
_TODOS_DIR = _REPO_ROOT / ".planning" / "todos"
_PENDING_DIR = _TODOS_DIR / "pending"
_PRIORITIES_FILE = _REPO_ROOT / ".planning" / "todos" / "PRIORITIES.md"
_LINK_PATTERN = re.compile(r"\(pending/([^)]+\.md)\)")

# {filename: reason} -- pending/ files deliberately excluded from PRIORITIES.md's
# tables. Adding an entry here requires a real justification, not just silencing
# the test -- the correct fix for a genuinely-untracked todo is almost always to
# add its row, not allow-list the gap.
_UNLINKED_ALLOW_LIST: dict[str, str] = {}

# {filename: reason} -- PRIORITIES.md links deliberately pointing at a filename
# with no live pending/ file (e.g. a documented pending rename in flight).
# Empty today; add an entry only with a real justification.
_DEAD_LINK_ALLOW_LIST: dict[str, str] = {}


@functools.lru_cache(maxsize=1)
def _pending_filenames() -> set[str]:
    return {path.name for path in _PENDING_DIR.glob("*.md")}


@functools.lru_cache(maxsize=1)
def _linked_filenames() -> set[str]:
    return set(_LINK_PATTERN.findall(_PRIORITIES_FILE.read_text()))


def test_no_new_unlinked_pending_todos():
    unlinked = unexpected_violations(
        _pending_filenames() - _linked_filenames(), _UNLINKED_ALLOW_LIST
    )
    assert not unlinked, (
        "New pending todo(s) with no [N](pending/...) link anywhere in "
        f"PRIORITIES.md: {unlinked}. Add a real table row (P0-P3, matching the "
        "todo's own frontmatter priority) -- do not allow-list a todo that "
        "should actually be tracked."
    )


def test_no_dead_priorities_links():
    dead = unexpected_violations(_linked_filenames() - _pending_filenames(), _DEAD_LINK_ALLOW_LIST)
    assert not dead, (
        f"PRIORITIES.md link(s) pointing at a nonexistent pending/ file: {dead}. "
        "The todo was likely closed (moved to completed/) or renamed -- update "
        "or remove the stale link."
    )


def test_unlinked_allow_list_has_no_stale_entries():
    stale = stale_allow_list_entries(
        _pending_filenames() - _linked_filenames(), _UNLINKED_ALLOW_LIST
    )
    assert not stale, (
        f"Allow-list entries that are no longer actually unlinked: {stale}. "
        "The todo got a real table row -- remove its entry here."
    )


def test_dead_link_allow_list_has_no_stale_entries():
    stale = stale_allow_list_entries(
        _linked_filenames() - _pending_filenames(), _DEAD_LINK_ALLOW_LIST
    )
    assert not stale, (
        f"Allow-list entries that are no longer actually dead links: {stale}. "
        "The file exists again (or the link was already fixed) -- remove its "
        "entry here."
    )


# ---------------------------------------------------------------------------------------------
# Claims (PLANNING-SYSTEM.md, "Claiming a todo"): the lead marks light work `claimable: true`;
# an idle worker claims it by pushing `claimed_by` and `claimed_at` in the line-1 frontmatter.
# ---------------------------------------------------------------------------------------------

# a claim with no commit to its todo for this many days is abandoned and must be released
_CLAIM_STALE_DAYS = 3
_CLAIM_KEYS = ("claimed_by", "claimed_at")
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def _frontmatter(text: str) -> dict[str, str] | None:
    """Top-level `key: value` pairs of the leading frontmatter block (quotes and trailing comments
    stripped), or None when the file has no block on its first line."""
    match = _FRONTMATTER.match(text)
    if match is None:
        return None
    fields = {}
    for line in match[1].splitlines():
        key, sep, value = line.partition(":")
        if sep and key and not key[0].isspace():
            fields[key.strip()] = value.split(" #", 1)[0].strip().strip("'\"")
    return fields


@functools.lru_cache(maxsize=1)
def _todo_frontmatter() -> dict[Path, tuple[dict[str, str] | None, str]]:
    return {
        path: (_frontmatter(text := path.read_text()), text)
        for path in sorted(_TODOS_DIR.glob("*/*.md"))
    }


def _claim_time(fields: dict[str, str]) -> datetime | None:
    """claimed_at as an aware UTC time, or None when it is missing, unparsable or not UTC."""
    try:
        at = datetime.fromisoformat(fields.get("claimed_at", ""))
    except ValueError:
        return None
    return at if at.utcoffset() == timedelta(0) else None


def _claims() -> dict[Path, dict[str, str]]:
    return {
        path: fields
        for path, (fields, _text) in _todo_frontmatter().items()
        if fields and any(key in fields for key in _CLAIM_KEYS)
    }


def test_a_claim_is_in_frontmatter_the_test_can_read():
    hidden = sorted(
        path.name
        for path, (fields, text) in _todo_frontmatter().items()
        if re.search(r"^claimed_(by|at):", text, re.M)
        and not (fields and set(_CLAIM_KEYS) & set(fields))
    )
    assert not hidden, f"claim fields outside a leading --- frontmatter block (line 1): {hidden}"


def test_only_a_pending_claimable_todo_is_claimed():
    wrong = sorted(
        f"{path.parent.name}/{path.name}"
        for path, fields in _claims().items()
        if path.parent != _PENDING_DIR or fields.get("claimable", "").lower() != "true"
    )
    assert not wrong, (
        "a claim outside pending/ or without claimable: true (drop the claim when closing "
        f"or deferring; only the lead marks a todo claimable): {wrong}"
    )


def test_a_claim_names_its_worker_and_a_utc_time():
    bad = sorted(
        path.name
        for path, fields in _claims().items()
        if not fields.get("claimed_by") or _claim_time(fields) is None
    )
    assert not bad, f"a claim needs both claimed_by and claimed_at as a UTC ISO time: {bad}"


def test_no_claim_is_stale():
    """A claim older than three days with no commit to its todo since is abandoned. It runs in every
    local suite and skips in CI (env CI set), because a calendar date must not turn an
    unrelated push red; it also skips without git or with shallow history, where the last touch
    cannot be dated.
    """
    if os.environ.get("CI"):
        pytest.skip(
            "CI: a stale claim is a lead-loop finding, not a reason to fail an unrelated push"
        )
    git = ["git", "-C", str(_REPO_ROOT)]
    try:
        shallow = subprocess.run(
            [*git, "rev-parse", "--is-shallow-repository"], capture_output=True, text=True
        )
    except FileNotFoundError:
        pytest.skip("no git binary")
    if shallow.stdout.strip() != "false":
        pytest.skip("shallow or no git history: a claim's last touch cannot be dated")
    now, stale = datetime.now(UTC), []
    for path, fields in _claims().items():
        claimed = _claim_time(fields)
        if claimed is None:
            continue  # the format test reports it
        log = subprocess.run(
            [*git, "log", "-1", "--format=%cI", "--", str(path)], capture_output=True, text=True
        )
        assert log.returncode == 0, log.stderr
        touched = datetime.fromisoformat(log.stdout.strip()) if log.stdout.strip() else claimed
        if now - max(claimed, touched) > timedelta(days=_CLAIM_STALE_DAYS):
            stale.append(
                f"{path.name} ({fields.get('claimed_by')}, claimed {fields['claimed_at']})"
            )
    assert not stale, f"claims with no commit for {_CLAIM_STALE_DAYS} days; release them: {stale}"
