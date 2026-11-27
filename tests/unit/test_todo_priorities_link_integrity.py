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

It also holds todo numbers unique across pending/, completed/ and deferred/ and every
PRIORITIES.md link label equal to its file's number (todo 394), and every todo claim well formed
(tools/todo_claims.py), and every todo's `objective:` an id of .planning/OBJECTIVES.md (required on
todos numbered after todo_claims.OBJECTIVE_REQUIRED_AFTER).

CI-clean: no DB, no network -- pure filesystem + regex scan.
"""

from __future__ import annotations

import functools
import re
from datetime import UTC, datetime
from pathlib import Path

from tests.unit._allow_list_scan import stale_allow_list_entries, unexpected_violations
from tools import todo_claims

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


_TODO_NUMBER = todo_claims.TODO_NUMBER
_TODO_LINK = re.compile(r"\[([^\]]*)\]\(\.?/?(?:pending|completed|deferred)/([^)#]*)[^)]*\)")


def test_todo_numbers_are_unique_across_pending_completed_and_deferred():
    """No two current todo files share a number (todo 394: two sessions filed 389), and every
    todo file starts with its number, so none escapes the check. A number freed by deleting a
    completed todo is not tracked."""
    by_number: dict[int, list[str]] = {}
    unnumbered = []
    for path in _TODOS_DIR.glob("*/*.md"):
        name = f"{path.parent.name}/{path.name}"
        if match := _TODO_NUMBER.match(path.name):
            by_number.setdefault(int(match[1]), []).append(name)
        else:
            unnumbered.append(name)
    assert not unnumbered, f"todo files not named <number>-<slug>.md: {sorted(unnumbered)}"
    shared = {n: sorted(files) for n, files in sorted(by_number.items()) if len(files) > 1}
    assert not shared, f"todo numbers used by more than one file (renumber the newer one): {shared}"


def test_a_priorities_link_label_matches_its_file_number():
    """`[N](pending/M-...)` with N != M reads as the wrong todo (todo 394: [391] linked 389)."""
    text = _PRIORITIES_FILE.read_text()
    wrong = sorted(
        m[0]
        for m in _TODO_LINK.finditer(text)
        if not (
            (number := _TODO_NUMBER.match(m[2])) and m[1].isdigit() and int(m[1]) == int(number[1])
        )
    )
    assert not wrong, f"PRIORITIES.md links whose label is not the file's number: {wrong}"


def test_every_claim_is_well_formed():
    """The claim rules of PLANNING-SYSTEM.md ("Claiming a todo"), checked by tools/todo_claims.py,
    whose own tests plant each broken case. Staleness is the tool's report, never a test."""
    bad = {
        claim.todo: claim.errors
        for claim in todo_claims.claims(_TODOS_DIR, datetime.now(UTC))
        if claim.errors
    }
    assert not bad, f"malformed todo claims (fix or release them): {bad}"


def test_every_todo_names_a_known_objective():
    """PLANNING-SYSTEM.md "Objectives": OBJECTIVES.md ids are unique, and a todo's `objective:` is
    one of them (required on every todo filed after the layer landed). Planted cases live in
    tests/unit/tools/test_todo_claims.py."""
    ids = todo_claims.objective_ids(todo_claims.OBJECTIVES_FILE.read_text(encoding="utf-8"))
    assert ids, "OBJECTIVES.md has no objective rows"
    repeated = sorted({i for i in ids if ids.count(i) > 1})
    assert not repeated, f"objective ids used by more than one row of OBJECTIVES.md: {repeated}"
    bad = {
        f"{path.parent.name}/{path.name}": errors
        for path in sorted(_TODOS_DIR.glob("*/*.md"))
        if (errors := todo_claims.objective_errors(path.name, path.read_text(), set(ids)))
    }
    assert not bad, f"todos with a missing or unknown objective (OBJECTIVES.md ids): {bad}"
