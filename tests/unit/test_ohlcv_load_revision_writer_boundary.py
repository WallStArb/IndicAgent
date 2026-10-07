"""CI guard: ohlcv_load and ohlcv_revision have named writers on disjoint segments (plan 185-31).

Migration 443 widened ohlcv_load from the Tradier daily load record to the write record of every
canonical writer, and ohlcv_revision to the one revision table (data layer integrity design
section 3). Each writer owns one `source` segment of ohlcv_load and writes ohlcv_revision rows
only under its own load rows, so the segments below are pairwise disjoint: the Tradier loader
owns source tradier, the grid stage of services/bar_derivation.py owns source derived, and
185-39 adds the IBKR ingress writers as source ibkr. Any other INSERT, UPDATE, DELETE, COPY,
TRUNCATE or MERGE into either table fails CI unless the allow-list is edited with a reason, and
an entry that no longer writes fails as stale. This file replaces the two tables' scanned
entries in test_single_writer_registry.py (185-44).

The same widening would make a grid or ingress load row read as "Tradier owns this name" to the
readers of outcome = 'loaded'; the last test pins `source = 'tradier'` into each of them.

CI-clean: no DB, no network, pure filesystem grep plus imports of SQL constants.
"""

from __future__ import annotations

import functools
import re
from itertools import combinations
from pathlib import Path

from tests.unit._source_grep_helpers import (
    assert_allow_list_has_no_stale_entries,
    assert_no_unlisted_references,
    find_pattern_references,
)

_REPO_ROOT = Path(__file__).parent.parent.parent
_SEARCH_DIRS = ("services", "src", "scripts")
_FILE_GLOBS = ("*.py", "*.sh", "*.sql")
_VERBS = r"(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|COPY|TRUNCATE(?:\s+TABLE)?|MERGE\s+INTO)"
_TABLES = {
    table: re.compile(
        rf"\b{_VERBS}\s+(?:ONLY\s+)?(?:public\.)?{table}\b"
        rf"|copy_(?:records_)?to_table\(\s*[\"']{table}[\"']",
        re.IGNORECASE,
    )
    for table in ("ohlcv_load", "ohlcv_revision")
}

_LOADER = "scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py"

# table -> module -> (owned ohlcv_load.source values, reason)
_ALLOW_LISTS: dict[str, dict[str, tuple[frozenset[str], str]]] = {
    "ohlcv_load": {
        _LOADER: (
            frozenset({"tradier"}),
            "PERMANENT: the Tradier daily loader records every load attempt of one symbol "
            "(plan 185-27; outcome loaded, short_history, no_data, failed or gated).",
        ),
    },
    "ohlcv_revision": {
        _LOADER: (
            frozenset({"tradier"}),
            "PERMANENT: the old value of each canonical 1d bar a Tradier load changed, under "
            "that load's row (plan 185-27).",
        ),
    },
}


@functools.cache
def _hits(table: str) -> dict[str, int]:
    hits: dict[str, int] = {}
    for file_glob in _FILE_GLOBS:
        hits.update(
            find_pattern_references(
                _REPO_ROOT, _SEARCH_DIRS, _TABLES[table], file_globs=(file_glob,)
            )
        )
    return hits


def _reasons(table: str) -> dict[str, str]:
    return {module: reason for module, (_segment, reason) in _ALLOW_LISTS[table].items()}


def test_every_load_and_revision_writer_is_on_the_allow_list():
    for table in _ALLOW_LISTS:
        assert_no_unlisted_references(
            _hits(table),
            _reasons(table),
            what=f"`{table}` write(s)",
            remedy=(
                "single_writer: a new canonical writer records its loads under its own "
                "ohlcv_load.source segment; add it here with that segment and a reason."
            ),
        )


def test_load_and_revision_allow_lists_have_no_stale_entries():
    for table in _ALLOW_LISTS:
        assert_allow_list_has_no_stale_entries(_hits(table), _reasons(table))


def test_segments_are_declared_and_pairwise_disjoint():
    for table, allow_list in _ALLOW_LISTS.items():
        for module, (segment, _reason) in allow_list.items():
            assert segment, f"{table}: {module} declares an empty segment"
        for (first, (a, _)), (second, (b, _)) in combinations(allow_list.items(), 2):
            assert not a & b, f"{table}: {first} and {second} both own source {sorted(a & b)}"


def test_the_pattern_catches_each_write_form():
    pattern = _TABLES["ohlcv_revision"]
    assert pattern.search("INSERT INTO ohlcv_revision (load_id)")
    assert pattern.search("update ohlcv_revision set origin = 'load'")
    assert pattern.search("DELETE FROM ohlcv_revision WHERE load_id = $1")
    assert pattern.search("COPY ohlcv_revision FROM STDIN")
    assert pattern.search('conn.copy_records_to_table("ohlcv_revision", records=r)')
    assert not pattern.search("SELECT * FROM ohlcv_revision")
    assert not pattern.search("JOIN ohlcv_revision r ON r.load_id = l.load_id")


def test_every_ownership_predicate_requires_a_tradier_source():
    from scripts.infrastructure.backfill.infrastructure_run_tradier_daily import (
        _SELECT_MISSING_SQL,
        TRADIER_OWNED_SQL,
    )
    from services.bar_derivation import _SELECT_DAILY_CHANGED_SINCE_SQL
    from services.bar_reconciliation_audit import _TRADIER_LATEST_LOAD_SQL

    for name, sql in (
        ("bar_derivation._SELECT_DAILY_CHANGED_SINCE_SQL", _SELECT_DAILY_CHANGED_SINCE_SQL),
        ("TRADIER_OWNED_SQL", TRADIER_OWNED_SQL),
        ("loader _SELECT_MISSING_SQL", _SELECT_MISSING_SQL),
        ("D7 _TRADIER_LATEST_LOAD_SQL", _TRADIER_LATEST_LOAD_SQL),
    ):
        # Lookahead so a nested EXISTS over ohlcv_load is matched as well as its outer query.
        predicates = re.findall(r"(?=FROM ohlcv_load (\w+)\s+WHERE([^)]*))", sql)
        assert predicates, name
        for alias, where in predicates:
            assert f"{alias}.source = 'tradier'" in where, f"{name}: {where.strip()}"
