"""CI guard: services/ohlcv_coverage_writer.py is the only writer of ohlcv_coverage.

Single-writer fence for the coverage ledger (migration 432, phase 189 CD-03): the ledger stays
in step with the stored bars only because every write happens in the writer module, inside the
bars' transaction or the fetcher's outcome write. A second INSERT/UPDATE/DELETE/COPY elsewhere
could drift it silently, so a new one fails here unless this allow-list is edited with a reason.

The file also fenced the wave-1 cutover discipline (phase 190 plan 02, review adjudication
item 1): through waves 1-4 the live conflict target of every writer statement stayed the old
shape (symbol, timeframe) -- the running drain held that module in memory, and the new target
had no unique index until migration 465 applied at the 190-06 cutover. The fence now asserts
the NEW three-column shape on every writer statement, flipped in the same commit as the
live 465 apply.

CI-clean: no DB, no network; pure filesystem grep.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit._source_grep_helpers import (
    assert_allow_list_has_no_stale_entries,
    assert_no_unlisted_references,
    find_pattern_references,
    read_source,
)

_REPO_ROOT = Path(__file__).parent.parent.parent
_WRITER_PATTERN = re.compile(r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|COPY)\s+ohlcv_coverage\b")
_SEARCH_DIRS = ("services", "src", "scripts")

_ALLOW_LIST: dict[str, str] = {
    "services/ohlcv_coverage_writer.py": (
        "PERMANENT: the single writer of ohlcv_coverage (phase 189 CD-03/CD-04): the "
        "upsert inside persist_chunk_atomically's transaction, the per-item outcome "
        "write and the --reset-failures path."
    ),
    "scripts/ops/bars/ops_tradier_delete.py": (
        "TEMPORARY retire: 191-25. DELETE FROM ohlcv_coverage where provider tradier only, in "
        "symbol batches after the COPY backup (plan 191-20, Tradier source-scoped deletion, "
        "owner exception 2026-10-12); it never inserts or updates the ledger."
    ),
}


def test_every_ohlcv_coverage_writer_is_on_the_allow_list():
    hits = find_pattern_references(_REPO_ROOT, _SEARCH_DIRS, _WRITER_PATTERN)
    assert_no_unlisted_references(
        hits,
        _ALLOW_LIST,
        what="ohlcv_coverage write(s)",
        remedy=(
            "Write the ledger through services/ohlcv_coverage_writer.py, never inline; it must "
            "stay in the bars' transaction to stay true."
        ),
    )


def test_coverage_writer_allow_list_has_no_stale_entries():
    hits = find_pattern_references(_REPO_ROOT, _SEARCH_DIRS, _WRITER_PATTERN)
    assert_allow_list_has_no_stale_entries(hits, _ALLOW_LIST)


# ---------------------------------------------------------------------------
# Provider dimension and the wave-5 conflict-target discipline (190-02)
# ---------------------------------------------------------------------------


def _writer_source() -> str:
    return read_source("services", "ohlcv_coverage_writer.py")


def test_at_the_cutover_the_live_conflict_target_is_the_new_shape():
    """Migration 465 (applied at the 190-06 cutover with the fetcher stopped, in the same
    breath as the writer flip) re-keyed the ledger to (symbol, timeframe, provider); the
    old two-column target has no unique index to match and would fail every write with
    42P10. Every ON CONFLICT on the ledger must name the three-column shape."""
    source = _writer_source()
    targets = re.findall(r"ON CONFLICT \(([^)]*)\)", source)
    assert targets, "the writer lost its conflict targets"
    assert all(target.strip() == "symbol, timeframe, provider" for target in targets), targets


def test_every_write_carries_the_provider_label():
    source = _writer_source()
    # provider sits in the INSERT column list of all four writer statements: the two
    # upserts, the 1d refresh and the rebuild.
    inserts = re.findall(r"INSERT INTO ohlcv_coverage \(([^)]*)\)", source, flags=re.DOTALL)
    assert len(inserts) == 4, inserts
    for columns in inserts:
        assert "provider" in columns, columns
    assert "%(provider)s" in source  # _REBUILD_SQL's labeled select
    for fn in (
        "def record_fetch_outcome(",
        "def refresh_1d_bounds(",
        "def reset_failures(",
        "def rebuild_from_stored_state(",
    ):
        start = source.index(fn)
        end = source.index(")", start)
        assert "provider" in source[start:end], fn
    # CoverageDelta carries the label so the caller's vendor reaches the upsert.
    delta = source[source.index("class CoverageDelta") :]
    assert 'provider: str = "ibkr"' in delta[: delta.index("def ")]


def test_rebuild_filters_are_per_provider_and_unknown_providers_raise():
    source = _writer_source()
    assert "_REBUILD_FILTERS: dict[str, str]" in source
    assert "_REQUEST_FILTER" not in source  # the hardcoded IBKR constant is gone
    assert '"ibkr":' in source
    assert "raise ValueError" in source
    assert "unknown coverage provider" in source
    # Alpaca's leaf landed (phase 190): its rows are rebuilt from its own raw rows too.
    assert '"alpaca":' in source
    assert source.index('"alpaca":') < source.index("REBUILD_PROVIDERS")


def test_coverage_is_per_source_over_ohlcv_raw_only():
    """Phase 191 plan 06: one destination (raw); the archive, the grid table and the canonical
    view are not coverage inputs, and every raw scan is scoped to the provider's vendor."""
    source = _writer_source()
    assert 'DESTINATION_RAW = "raw"' in source
    for gone in (
        "DESTINATION_ARCHIVE",
        "DESTINATION_GRID",
        "DESTINATION_TABLES",
        "ohlcv_intraday_raw_archive",
        "market_data_ohlcv",
        "existing_timestamps",
    ):
        assert gone not in source, gone
    scans = re.findall(r"FROM ohlcv_raw\s+WHERE ([^\n]*)", source)
    assert len(scans) == 3, scans  # the slot count of a chunk, the 1d refresh and the rebuild
    assert all("vendor = " in scan for scan in scans), scans


def test_the_writer_functions_are_the_listed_set():
    source = _writer_source()
    defs = set(re.findall(r"^def (\w+)\(", source, flags=re.MULTILINE))
    assert defs == {
        "upsert_coverage",
        "record_fetch_outcome",
        "refresh_1d_bounds",
        "rebuild_from_stored_state",
        "reset_failures",
        "count_new_slots",  # the incremental row_count in distinct slots, as the rebuild counts
        "fetch_status_for_outcome",  # the rebuild's outcome CASE, for incremental status writes
    }
