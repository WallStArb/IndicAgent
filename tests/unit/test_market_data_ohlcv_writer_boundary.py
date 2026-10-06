"""CI guard: no new raw `market_data_ohlcv` writes outside this checked-in allow-list.

Single-writer fence for phase 185 D2b (migration 383's header names this test): after
plan 185-18, services/bar_derivation.py is the only writer of derived grid rows (the
quarter-hour and hourly grid, and the canonical daily rows) into the raw table; every
other write path on disk is a raw provider observation the derivation never rewrites.
A new file writing the raw table now fails CI immediately unless this allow-list is
also edited -- which forces a "who owns this segment" justification into the diff
itself, at review time.

The read boundary is separate and stays in test_market_data_ohlcv_boundary.py (raw
READS, the synthetic-fill grid); this guard owns INSERT/UPDATE/DELETE/COPY only.

CI-clean: no DB, no network -- pure filesystem grep.
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
_WRITER_PATTERN = re.compile(
    r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|COPY)\s+market_data_ohlcv\b(?!_tradeable)"
)
_SEARCH_DIRS = ("services", "src", "scripts")

# (file, reason) -- every raw `market_data_ohlcv` write in the tree must appear here.
# Adding a new writer requires adding a row here with a real reason, not just silencing
# the test.
_ALLOW_LIST: dict[str, str] = {
    "services/bar_derivation.py": (
        "PERMANENT: the D2b derivation writer (phase 185 plan 11, D-06/D-15) -- the only "
        "permanent writer of derived 15m/1h rows (and, from plan 17, canonical 1d). One "
        "transaction per symbol: archive the stored segment into "
        "ohlcv_intraday_raw_archive, verify checksums, DELETE the segment (placeholders "
        "included), INSERT the derived rows. Registered in service_auditor.py's _DAG_ORDER "
        "and _ONESHOT_UNITS as indicagent-bar-derivation."
    ),
    "scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py": (
        "PERMANENT: raw provider observations at the five- and one-minute timeframes "
        "only -- the derivation never rewrites those (D-15); real-bars-only since plan "
        "185-18 (todo 462), so no synthetic fill reaches the table, and five-minute "
        "chunks commit through the atomic persist helper. Daily bars stopped landing "
        "here in plan 185-18 task 1b: the fetch captures them into D1 and "
        "services/bar_derivation.py owns the daily rows. The hourly and quarter-hour "
        "fetches are archive-bound raw observations (plan 12) routed through "
        "services/intraday_raw_archive.py; the grid readers see them derived from "
        "five-minute bars by bar_derivation (chained from the nightly)."
    ),
    "services/backfill_feature_factory.py": (
        "PERMANENT: its --fetch-only stage survives the phase 186 rebuild per "
        "186-06/186-25; only the raw five- and one-minute provider fetch remains, and "
        "the derivation never rewrites those (D-15). Plan 185-18 task 1b fenced the "
        "daily and derived-grid timeframes out of the fetch stage entirely."
    ),
    "scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py": (
        "TEMPORARY: the Tradier daily loader (owner decision 2026-10-03, migration 438: "
        "Tradier is the primary 1d source). It lands raw observations in D1 and writes the "
        "canonical 1d bars it plans, refusing short or source-changing loads; plan 185-26 "
        "chains it as the nightly's Tradier 1d leg. A second 1d writer with no disjoint "
        "segment: the data layer integrity design makes the daily stage the only 1d writer "
        "(retire: 185-38)."
    ),
    "services/bar_writer.py": (
        "PERMANENT: the streaming-path bar writer persists provider bars at the one- "
        "and five-minute timeframes only (the live path is dormant while the IBKR feed "
        "is down). Plan 185-18 task 1b made it refuse the derivation-owned timeframes "
        "(daily, hourly, quarter-hour) with a logged warning."
    ),
}


@functools.lru_cache(maxsize=1)
def _find_writer_references() -> dict[str, int]:
    """Returns {relative_path: match_count} for every .py file under _SEARCH_DIRS that
    writes the raw market_data_ohlcv table (not the _tradeable view)."""
    return find_pattern_references(_REPO_ROOT, _SEARCH_DIRS, _WRITER_PATTERN, file_globs=("*.py",))


def test_every_raw_market_data_ohlcv_writer_is_on_the_allow_list():
    hits = _find_writer_references()
    assert_no_unlisted_references(
        hits,
        _ALLOW_LIST,
        what="raw `market_data_ohlcv` write(s)",
        remedy=(
            "After phase 185 plan 18, services/bar_derivation.py is the only writer of "
            "derived grid rows into market_data_ohlcv; every other writer on the list "
            "is a raw provider observation path. If this is a genuine new write path, "
            "add it to _ALLOW_LIST in this file with a reason naming the plan that "
            "owns it."
        ),
    )


def test_writer_allow_list_has_no_stale_entries():
    hits = _find_writer_references()
    assert_allow_list_has_no_stale_entries(hits, _ALLOW_LIST)
