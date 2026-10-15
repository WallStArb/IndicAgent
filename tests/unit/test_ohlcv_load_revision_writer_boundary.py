"""CI guard: ohlcv_load and ohlcv_revision have named writers on disjoint segments (plan 185-31).

Migration 443 widened ohlcv_load from the Tradier daily load record to the write record of every
canonical writer, and ohlcv_revision to the one revision table (data layer integrity design
section 3). Each writer owns one `source` segment of ohlcv_load and writes ohlcv_revision rows
only under its own load rows, so the segments below are pairwise disjoint: the grid stage of
services/bar_derivation.py owns source derived and 185-39 adds the IBKR ingress contract
(services/ohlcv_ingress_contract.py) as source ibkr. Phase 191 plan 04 widens a segment from the
source alone to (source, caller): sources may overlap, callers may not. Source tradier rows are the deleted Tradier
loader's history (plan 185-48); no writer owns that segment now. Any other INSERT, UPDATE, DELETE, COPY,
TRUNCATE or MERGE into either table fails CI unless the allow-list is edited with a reason, and
an entry that no longer writes fails as stale. This file replaces the two tables' scanned
entries in test_single_writer_registry.py (185-44).

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

_DERIVATION = "services/bar_derivation.py"
_INGRESS = "services/ohlcv_ingress_contract.py"
_RAW_WRITER = "services/ohlcv_raw_writer.py"

_BACKFILL = "scripts/ops/bars/ops_raw_backfill.py"

# table -> module -> (sources, callers, reason). A segment is the (source, caller) pairs a writer
# records: sources MAY overlap between writers now (vendor names are shared by the ingress
# contract and the one-shot raw backfill), the callers MAY NOT. "*" as a source means any vendor.
_ALLOW_LISTS: dict[str, dict[str, tuple[frozenset[str], frozenset[str], str]]] = {
    "ohlcv_load": {
        _DERIVATION: (
            frozenset({"derived"}),
            frozenset({"bar_derivation-daily", "bar_derivation-grid", "bar_derivation-restore"}),
            "PERMANENT: the grid stage records one load per (symbol, 15m/1h) it derives, with "
            "its new, changed, unchanged and removed counts (outcome applied or refused, "
            "plan 185-31).",
        ),
        _INGRESS: (
            frozenset({"ibkr", "alpaca"}),
            frozenset({"ibkr-history-fetch", "alpaca-5m-load"}),
            "PERMANENT: the ingress write contract records one load per (symbol, timeframe, "
            "vendor, kind) series of every chunk it records (destination raw; the fetcher, the "
            "Alpaca loader and store_bars all write through it since phase 191 plan 05), "
            "outcome applied or refused (plans 185-39, 191-04 and 191-05). Never the caller "
            "raw-backfill-191.",
        ),
        _BACKFILL: (
            frozenset({"*"}),
            frozenset({"raw-backfill-191"}),
            "TEMPORARY retire: 191-17. The --revisions mode writes one load per (symbol, vendor, "
            "restatement ordinal) with destination raw, outcome applied, caller raw-backfill-191 "
            "(phase 191 plan 04, D-191-E).",
        ),
    },
    "ohlcv_revision": {
        _DERIVATION: (
            frozenset({"derived"}),
            frozenset({"bar_derivation-daily", "bar_derivation-grid", "bar_derivation-restore"}),
            "PERMANENT: the grid stage's and the daily stage's old values under their own "
            "load rows: changed or removed derived and canonical 1d rows (origin load) and "
            "stored vendor rows the archive does not hold equal (origin archive_segment) "
            "before they leave market_data_ohlcv (plans 185-31 and 185-38).",
        ),
        _RAW_WRITER: (
            frozenset({"origin:raw", "origin:superseded"}),
            frozenset({"origin:raw", "origin:superseded"}),
            "PERMANENT: the raw writer logs the old values of a vendor's restated ohlcv_raw row "
            "(origin raw; phase 191 plan 02) and an offer older than the stored answer (origin "
            "superseded; migration 485) under the load row its caller inserted. "
            "It writes ohlcv_revision rows only and never an ohlcv_load row, so its segment is "
            "the revision origin, not a caller.",
        ),
        _BACKFILL: (
            frozenset({"*"}),
            frozenset({"raw-backfill-191"}),
            "TEMPORARY retire: 191-17. The --revisions mode writes the superseded observation "
            "value runs as origin raw revisions under raw-backfill-191 loads (phase 191 plan 04).",
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
    return {module: reason for module, (_sources, _callers, reason) in _ALLOW_LISTS[table].items()}


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


def test_segments_are_declared_and_callers_are_pairwise_disjoint():
    for table, allow_list in _ALLOW_LISTS.items():
        for module, (sources, callers, _reason) in allow_list.items():
            assert sources and callers, f"{table}: {module} declares an empty segment"
        for (first, (_, a, _)), (second, (_, b, _)) in combinations(allow_list.items(), 2):
            assert not a & b, f"{table}: {first} and {second} both own caller {sorted(a & b)}"


def test_the_backfill_caller_is_the_literal_the_module_writes_and_the_contract_never_uses_it():
    backfill = (_REPO_ROOT / _BACKFILL).read_text()
    assert '_REVISION_CALLER = "raw-backfill-191"' in backfill
    assert "'raw'" in backfill  # destination raw
    ingress = (_REPO_ROOT / _INGRESS).read_text()
    assert "raw-backfill-191" not in ingress


def test_the_pattern_catches_each_write_form():
    pattern = _TABLES["ohlcv_revision"]
    assert pattern.search("INSERT INTO ohlcv_revision (load_id)")
    assert pattern.search("update ohlcv_revision set origin = 'load'")
    assert pattern.search("DELETE FROM ohlcv_revision WHERE load_id = $1")
    assert pattern.search("COPY ohlcv_revision FROM STDIN")
    assert pattern.search('conn.copy_records_to_table("ohlcv_revision", records=r)')
    assert not pattern.search("SELECT * FROM ohlcv_revision")
    assert not pattern.search("JOIN ohlcv_revision r ON r.load_id = l.load_id")
