"""CI guard: no two files under production/migrations/ may share the same leading
number prefix (e.g. 042_foo.sql and 042_bar.sql).

Per docs/foundation/naming-system.md #11, migration numbers must be unique -- a
duplicate is a real naming violation. Todo 101
(.planning/todos/pending/101-migration-duplicate-number-sweep.md) found 14 such
duplicate groups accumulated across production/migrations/'s history (concurrent
worktree sessions independently picking the same "next free" number) and resolved
all 14 in commit 18551320 (2026-07-18, "renumber to close 14 duplicate leading-number
collisions"). This guard exists because that fix regrows without prevention: this
file's own authoring discovered a brand-new collision at 240 that appeared after the
18551320 renumbering, confirming the exact regrowth todo 101 predicted.

Renumbering an already-applied migration file is a separate, higher-risk, live-DB-
adjacent operation (todo 101 scopes it as its own dedicated session). This test is
detection-only: it fails fast on any NEW collision so one never again accumulates
silently, without attempting to resolve the one(s) already found.

CI-clean: no DB, no network -- pure filesystem grep.
"""

from __future__ import annotations

import functools
import re
from collections import defaultdict
from pathlib import Path

from tests.unit._allow_list_scan import stale_allow_list_entries, unexpected_violations

_REPO_ROOT = Path(__file__).parent.parent.parent
_MIGRATIONS_DIR = _REPO_ROOT / "production" / "migrations"
_NUMBER_PATTERN = re.compile(r"^(\d+)_.+\.sql$")

# {leading number: reason} -- every number prefix currently claimed by 2+ files under
# production/migrations/ must appear here with a reason, or the test below fails.
# Adding a new collision here requires a real justification, not just silencing the
# test -- the correct fix for a brand-new collision is almost always to pick the next
# free number instead of allow-listing it.
_ALLOW_LIST: dict[str, str] = {
    "240": (
        "PENDING (todo 101): 240_counterfactual_tracker_chunk_size.sql (Phase 143.1-08, "
        "commit 996250a1) and 240_cross_symbol_corroboration_apr_key.sql (todo 152, "
        "commit 428d7622) -- two concurrent worktree sessions independently picked the "
        "same 'next free' number, the exact failure mode this guard exists to catch "
        "going forward. Discovered 2026-07-31 while building this guard -- a NEW "
        "collision, distinct from the 14 groups already resolved in commit 18551320 "
        "(2026-07-18, 'renumber to close 14 duplicate leading-number collisions'). "
        "Renumbering this pair is deliberately deferred, not fixed here: todo 101 scopes "
        "any production/migrations/ renumbering as its own dedicated session given the "
        "live-DB-adjacent risk; this guard is detection-only."
    ),
}


@functools.lru_cache(maxsize=1)
def _duplicate_number_groups() -> dict[str, list[str]]:
    """Returns {number: [filenames]} for every leading number claimed by 2+ files."""
    by_number: dict[str, list[str]] = defaultdict(list)
    for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        match = _NUMBER_PATTERN.match(path.name)
        if not match:
            continue
        by_number[match.group(1)].append(path.name)
    return {number: names for number, names in by_number.items() if len(names) > 1}


def test_no_new_migration_number_collisions():
    unexpected = unexpected_violations(_duplicate_number_groups(), _ALLOW_LIST)
    assert not unexpected, (
        "New duplicate migration number prefix(es) found under production/migrations/, "
        f"not on the allow-list: {unexpected}. Pick the next free number instead "
        "(check `ls production/migrations/ | sort -n | tail`); if this collision is "
        "genuinely intentional, add it to _ALLOW_LIST in this file with a real reason."
    )


def test_migration_number_allow_list_has_no_stale_entries():
    stale = stale_allow_list_entries(_duplicate_number_groups(), _ALLOW_LIST)
    assert not stale, (
        f"Allow-list entries that no longer match any duplicate migration number: "
        f"{stale}. The collision was resolved (renumbered) -- remove its entry here."
    )
