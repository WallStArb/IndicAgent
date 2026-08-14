"""CI guard: no new raw `UPDATE feature_vectors`/`UPDATE feature_ic_scores` outside this
checked-in allow-list.

Both are compressed TimescaleDB hypertables. Proven 2026-08-14 (see
services/_batch_utils.py's `compressed_hypertable_write_session` docstring for the full
writeup): a compressed chunk has no usable per-row index at all, so ANY row-level UPDATE
against one -- regardless of how selective its WHERE/JOIN predicate is -- forces a full
Seq Scan (decompressing the chunk) at roughly 1000x the cost of the same UPDATE against a
decompressed chunk. `bulk_update_by_key`'s callers can't be told apart from a hand-rolled
UPDATE by grepping the table name (bulk_update_by_key's own SQL is built as
`f"UPDATE {table} ..."`, so the literal text `UPDATE feature_vectors` never appears in its
call sites' source) -- so this guard's job is narrower than "wrap every write": it exists
to force any NEW raw, hand-rolled UPDATE against one of these two tables through the same
"why does this need to bypass bulk_update_by_key" justification `test_market_data_ohlcv_
boundary.py` already established for a structurally similar problem, at review time, in
the diff, rather than relying on someone remembering the incident later.

CI-clean: no DB, no network -- pure filesystem grep.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit._source_grep_helpers import (
    assert_allow_list_has_no_stale_entries,
    assert_no_unlisted_references,
    find_pattern_references,
)

_REPO_ROOT = Path(__file__).parent.parent.parent
_RAW_UPDATE_PATTERN = re.compile(r"\bUPDATE\s+(?:feature_vectors|feature_ic_scores)\b")
_SEARCH_DIRS = ("services", "src", "scripts")

# (file, reason) -- every raw UPDATE feature_vectors/feature_ic_scores reference in the
# tree must appear here. Adding a new call site requires adding a row here with a real
# reason (ideally: wrap it in compressed_hypertable_write_session /
# async_compressed_hypertable_write_session instead of writing a new raw UPDATE at all).
_ALLOW_LIST: dict[str, str] = {
    "scripts/ops/corpus/ops_regime_null_out_and_verify.py": (
        "PERMANENT: raw UPDATE retained (not migrated to bulk_update_by_key) because "
        "_build_null_out_sql always writes a fixed NULL across a family's owned columns "
        "for a (symbol, tf) scope -- there's no per-row value list for bulk_update_by_key's "
        "COPY-into-temp-table shape to carry. Wrapped in compressed_hypertable_write_session "
        "2026-08-14 (todo 306 follow-up), replacing the old log-only "
        "_log_compression_state() call this superseded."
    ),
    "scripts/ops/corpus/ops_stale_k3_hmm_fields_cleanup.py": (
        "PERMANENT: same shape as ops_regime_null_out_and_verify.py above -- "
        "_CLEANUP_UPDATE_SQL always writes fixed NULLs across 3 columns for a (symbol, tf) "
        "scope, not a per-row batch. Wrapped in async_compressed_hypertable_write_session "
        "2026-08-14 (todo 306 follow-up)."
    ),
    "scripts/ops/alpha/ops_interaction_primitives_pilot.py": (
        "PERMANENT: per-row $-placeholder values via asyncpg's executemany() -- doesn't fit "
        "bulk_update_by_key's psycopg/COPY-based shape without a larger rewrite of this "
        "pilot script's DB layer. Wrapped in async_compressed_hypertable_write_session "
        "2026-08-14 (todo 306 follow-up)."
    ),
    "services/ic_engine.py": (
        "TEMPORARY: two real, un-migrated raw UPDATE feature_ic_scores call sites "
        "(_FEATURE_STATUS_REFRESH_SQL and the bh_adjusted_p/passes_fdr executemany() pass) "
        "-- genuinely exposed to the same forced-full-scan cost as every other entry here, "
        "deliberately NOT touched in the 2026-08-14 sweep that added this guard: "
        "ic_engine.py is this codebase's largest, most heavily-relied-upon, already-audited "
        "write path (ops_ic_shrinkage.py's own docstring already calls this out: 'keeps "
        "ic_engine.py's large, already-audited write path untouched'), and bracketing its "
        "two write paths deserves a focused follow-up session with its own testing, not a "
        "rushed edit folded into an unrelated sweep. Tracked as its own todo -- remove this "
        "entry once that lands."
    ),
    "src/intelligence/features/feature_vector_persistence.py": (
        "PERMANENT: comment only (documents regime_writer.py's write behavior for the "
        "column-ownership manifest this module owns), not executable SQL -- there is no "
        "UPDATE here to migrate."
    ),
}


def _find_raw_update_references() -> dict[str, int]:
    return find_pattern_references(
        _REPO_ROOT, _SEARCH_DIRS, _RAW_UPDATE_PATTERN, file_globs=("*.py",)
    )


def test_every_raw_compressed_hypertable_update_is_on_the_allow_list():
    hits = _find_raw_update_references()
    assert_no_unlisted_references(
        hits,
        _ALLOW_LIST,
        what="raw `UPDATE feature_vectors`/`UPDATE feature_ic_scores` reference(s)",
        remedy=(
            "If this is a genuine new write, prefer routing it through "
            "bulk_update_by_key + compressed_hypertable_write_session (or the async "
            "sibling) in services/_batch_utils.py rather than a hand-rolled UPDATE -- see "
            "that function's docstring for why a raw UPDATE against either table is "
            "~1000x more expensive than it looks. If a raw UPDATE is genuinely necessary, "
            "bracket it in the session helper and add a row to _ALLOW_LIST here with a "
            "one-line reason."
        ),
    )


def test_compressed_hypertable_allow_list_has_no_stale_entries():
    hits = _find_raw_update_references()
    assert_allow_list_has_no_stale_entries(hits, _ALLOW_LIST)
