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

CI-clean: no DB, no network -- pure filesystem + regex scan.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

from tests.unit._allow_list_scan import stale_allow_list_entries, unexpected_violations

_REPO_ROOT = Path(__file__).parent.parent.parent
_PENDING_DIR = _REPO_ROOT / ".planning" / "todos" / "pending"
_PRIORITIES_FILE = _REPO_ROOT / ".planning" / "todos" / "PRIORITIES.md"
_LINK_PATTERN = re.compile(r"\(pending/([^)]+\.md)\)")

# {filename: reason} -- pending/ files deliberately excluded from PRIORITIES.md's
# tables. Adding an entry here requires a real justification, not just silencing
# the test -- the correct fix for a genuinely-untracked todo is almost always to
# add its row, not allow-list the gap.
_UNLINKED_ALLOW_LIST: dict[str, str] = {
    "080-ensemble-combination-e-candidates-queue.md": (
        "Deliberate redirect stub, not live work: content moved 2026-08-07 to "
        "docs/research/measurement-adaptive-combiner-weights.md, file kept in "
        "pending/ only as a pointer."
    ),
    "270-broadcast-feature-significance-overstates-effective-n.md": (
        "Promoted out of the P0 backlog into Phase 173 (ROADMAP.md) 2026-08-21, "
        "per PRIORITIES.md's own stated scope ('Phases... are a separate "
        "execution track and do not appear here'). File kept in pending/ as the "
        "historical scope record, not re-linked."
    ),
}

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
