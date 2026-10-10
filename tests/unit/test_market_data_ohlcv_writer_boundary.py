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
        "transaction per symbol by the write contract (plan 185-31): new derived rows "
        "inserted, changed rows upserted, stale rows deleted by key, old values in "
        "ohlcv_revision; stored vendor rows archived into ohlcv_intraday_raw_archive, "
        "verified by value and only then deleted. Registered in service_auditor.py's "
        "_DAG_ORDER and _ONESHOT_UNITS as indicagent-bar-derivation."
    ),
    "scripts/infrastructure/backfill/_history_fetch.py": (
        "PERMANENT: the phase 189 fetcher's provider-bar store (plan 189-08 made this helper "
        "library of the historical pipeline): raw provider observations at the five- and "
        "one-minute timeframes only -- the derivation never rewrites those (D-15); "
        "real-bars-only since plan 185-18 (todo 462), so no synthetic fill reaches the "
        "table, and five-minute chunks commit through the atomic persist helper under the "
        "185-39 write contract. Daily bars stopped landing here in plan 185-18 task 1b: "
        "the fetch captures them into D1 and services/bar_derivation.py owns the daily "
        "rows. The hourly and quarter-hour fetches are archive-bound raw observations "
        "(plan 12) routed through services/intraday_raw_archive.py; the grid readers see "
        "them derived from five-minute bars by bar_derivation (the fetcher's grid stage)."
    ),
    "services/bar_writer.py": (
        "PERMANENT: the streaming-path bar writer persists provider bars at the one- "
        "and five-minute timeframes only (the live path is dormant while the IBKR feed "
        "is down). Plan 185-18 task 1b made it refuse the derivation-owned timeframes "
        "(daily, hourly, quarter-hour) with a logged warning."
    ),
    "scripts/ops/bars/ops_alpaca_5m_load.py": (
        "CAMPAIGN (todo 521, 2026-10-09): the Alpaca 5m admission loader -- scratch parquet "
        "into market_data_ohlcv through the 185-39 ingress write contract with source "
        "'alpaca', five-minute only, first-writer-stays (stored stamps dropped before the "
        "contract sees them, so it only ever inserts). RTH-grid filter from nyse_sessions; "
        "coverage upsert rides the atomic persist helper in the chunk transaction. The T4 "
        "nightly leaf must reuse this writer, not grow a second one."
    ),
}


# Writers other than the daily stage that cannot write the derivation-owned timeframes (1d,
# 15m, 1h) without referencing the DERIVATION_OWNED_TIMEFRAMES fence: why each cannot (plan
# 185-38: the daily stage is the only 1d writer).
_FENCE_EXEMPT: dict[str, str] = {
    "scripts/infrastructure/backfill/_history_fetch.py": (
        "its raw write is the five- and one-minute persist path only; daily answers go to D1 "
        "and hourly and quarter-hour answers to the archive (plan 185-18 task 1b)"
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


def test_every_other_writer_is_fenced_from_the_derivation_owned_timeframes():
    """services/bar_derivation.py is the only 1d (and grid) writer: every other allow-listed
    writer references DERIVATION_OWNED_TIMEFRAMES or names why it cannot write them."""
    for module in _ALLOW_LIST:
        if module == "services/bar_derivation.py":
            continue
        source = (_REPO_ROOT / module).read_text()
        assert "DERIVATION_OWNED_TIMEFRAMES" in source or module in _FENCE_EXEMPT, module
    for module in _FENCE_EXEMPT:
        assert module in _ALLOW_LIST, f"stale fence exemption: {module}"
