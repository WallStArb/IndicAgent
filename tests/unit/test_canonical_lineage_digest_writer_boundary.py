"""CI guard: canonical_bar_lineage and bar_content_digest have named writers (plan 185-27).

single_writer: services/bar_derivation.py (D2 and the derived grid) writes both tables; the
Tradier daily loader writes canonical_bar_lineage for the 1d bars it stores, under rule
tradier-v1, and reaches bar_content_digest only through bar_derivation.write_1d_digests. The
scan matches the SQL where it is defined, so a script that imports TRADIER_LINEAGE_UPSERT_SQL or
write_1d_digests (the 185-30 backfill) is not a new writer. Any other INSERT, UPDATE or COPY into
either table fails CI unless the allow-list below is edited with a reason.

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
        r"\b(?:INSERT\s+INTO|UPDATE|COPY)\s+canonical_bar_lineage\b"
        r"|copy_records_to_table\(\s*[\"']canonical_bar_lineage[\"']"
    ),
    "bar_content_digest": re.compile(
        r"\b(?:INSERT\s+INTO|UPDATE|COPY)\s+bar_content_digest\b"
        r"|copy_records_to_table\(\s*[\"']bar_content_digest[\"']"
    ),
}

_ALLOW_LISTS: dict[str, dict[str, str]] = {
    "canonical_bar_lineage": {
        "services/bar_derivation.py": (
            "PERMANENT: D2's daily stage writes lineage for every canonical IBKR 1d bar "
            "(rule d2-v1, plan 185-17)."
        ),
        "scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py": (
            "TEMPORARY: the second 1d writer (owner decision 2026-10-03) traces every bar it "
            "stores to its TRADIER D1 observation (TRADIER_LINEAGE_UPSERT_SQL, rule tradier-v1, "
            "plan 185-27) inside the bar write's transaction. The loader's canonical write and "
            "this table give way to the lineage view (retire: 185-38)."
        ),
    },
    "bar_content_digest": {
        "services/bar_derivation.py": (
            "PERMANENT: the one digest writer: the grid stage's 5m/15m/1h months and "
            "write_1d_digests, which D2 and the Tradier loader both call (plan 185-27)."
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
                "single_writer: route the write through services/bar_derivation.py "
                "(write_1d_digests) or the Tradier loader's TRADIER_LINEAGE_UPSERT_SQL; only "
                "edit the allow-list here with a review-ready reason for a new writer."
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
