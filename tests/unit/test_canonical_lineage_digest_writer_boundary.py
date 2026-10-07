"""CI guard: canonical_bar_lineage has no writer; bar_content_digest has one (plans 185-27, 185-38).

single_writer: since plan 185-38 canonical_bar_lineage is a view derived on read (migration
447), so no module may INSERT, UPDATE, DELETE or COPY into it; services/bar_derivation.py
(the derived grid and the daily stage, write_1d_digests) is the only bar_content_digest writer.
The Tradier loader writes neither: it lands D1 and chains the daily stage. Any other write
fails CI unless the allow-list below is edited with a reason.

CI-clean: no DB, no network, pure filesystem grep.
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

from tests.unit._source_grep_helpers import (
    assert_allow_list_has_no_stale_entries,
    assert_no_unlisted_references,
    find_pattern_references,
)

_REPO_ROOT = Path(__file__).parent.parent.parent
_SEARCH_DIRS = ("services", "src", "scripts")
# bar_content_digest\b does not match bar_content_digest_current (the read view).
_TABLES = {
    "canonical_bar_lineage": re.compile(
        r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|COPY)\s+canonical_bar_lineage\b"
        r"|copy_records_to_table\(\s*[\"']canonical_bar_lineage[\"']"
    ),
    "bar_content_digest": re.compile(
        r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|COPY)\s+bar_content_digest\b"
        r"|copy_records_to_table\(\s*[\"']bar_content_digest[\"']"
    ),
}

_ALLOW_LISTS: dict[str, dict[str, str]] = {
    # A view since migration 447: nothing may write it.
    "canonical_bar_lineage": {},
    "bar_content_digest": {
        "services/bar_derivation.py": (
            "PERMANENT: the one digest writer: the grid stage's 5m/15m/1h months and the "
            "daily stage's write_1d_digests at d2-v2 (plans 185-27 and 185-38)."
        ),
    },
}


@functools.cache
def _hits(table: str) -> dict[str, int]:
    return find_pattern_references(_REPO_ROOT, _SEARCH_DIRS, _TABLES[table], file_globs=("*.py",))


def test_every_lineage_and_digest_writer_is_on_the_allow_list():
    for table, allow_list in _ALLOW_LISTS.items():
        assert_no_unlisted_references(
            _hits(table),
            allow_list,
            what=f"`{table}` write(s)",
            remedy=(
                "single_writer: canonical_bar_lineage is a view (no writer); digests go "
                "through services/bar_derivation.py (write_1d_digests). Only edit the "
                "allow-list here with a review-ready reason for a new writer."
            ),
        )


def test_lineage_and_digest_allow_lists_have_no_stale_entries():
    for table, allow_list in _ALLOW_LISTS.items():
        assert_allow_list_has_no_stale_entries(_hits(table), allow_list)


def test_the_pattern_catches_each_write_form_and_skips_the_current_view():
    pattern = _TABLES["bar_content_digest"]
    assert pattern.search("INSERT INTO bar_content_digest (symbol)")
    assert pattern.search("UPDATE bar_content_digest SET")
    assert pattern.search("COPY bar_content_digest FROM STDIN")
    assert pattern.search('conn.copy_records_to_table("bar_content_digest", records=r)')
    assert not pattern.search("SELECT digest FROM bar_content_digest_current")
    assert not pattern.search("INSERT INTO bar_content_digest_current")


def test_the_pattern_catches_each_lineage_write_form():
    pattern = _TABLES["canonical_bar_lineage"]
    for sql in (
        "INSERT INTO canonical_bar_lineage (symbol)",
        "UPDATE canonical_bar_lineage SET rule_version = 'x'",
        "DELETE FROM canonical_bar_lineage WHERE symbol = $1",
        "COPY canonical_bar_lineage FROM STDIN",
        'conn.copy_records_to_table("canonical_bar_lineage", records=r)',
    ):
        assert pattern.search(sql), sql
    assert not pattern.search("SELECT * FROM canonical_bar_lineage")
