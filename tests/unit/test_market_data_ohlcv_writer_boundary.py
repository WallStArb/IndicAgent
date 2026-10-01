"""CI guard: no new raw `market_data_ohlcv` writes outside this checked-in allow-list.

Single-writer fence for phase 185 D2b (migration 383's header names this test): after
plan 11, services/bar_derivation.py is the only PERMANENT writer of derived 15m/1h (and
later, plan 17, canonical 1d) rows into the raw table; every other write path that
remains on disk is TEMPORARY and owned by a later plan in the phase (the backfill
rework). A new file writing the raw table now fails CI immediately unless this
allow-list is also edited -- which forces a "who owns this segment after phase 185"
justification into the diff itself, at review time.

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
# the test. PERMANENT means the write survives phase 185; TEMPORARY names the plan that
# retires it.
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
        "TEMPORARY (1d): the historical backfill still writes provider 1d bars directly; "
        "retired by plan 18's backfill rework. PERMANENT (5m, 1m): raw provider "
        "observations the derivation never rewrites (D-15). Since plan 12 this "
        "pipeline writes NO 15m/1h here: they are archive-bound raw observations "
        "routed through services/intraday_raw_archive.py into "
        "ohlcv_intraday_raw_archive, and the grid readers see is derived from 5m "
        "by services/bar_derivation.py (chained from the nightly)."
    ),
    "services/backfill_feature_factory.py": (
        "TEMPORARY (1d, 15m, 1h): feature-factory backfill writes provider bars at "
        "these timeframes; retired by plan 18's backfill rework. PERMANENT (5m, 1m): "
        "its --fetch-only stage survives the phase 186 rebuild per 186-06/186-25; only "
        "the raw 5m/1m fetch remains, and the derivation never rewrites those (D-15)."
    ),
    "services/bar_writer.py": (
        "TEMPORARY: the streaming-path bar writer persists provider bars for the live "
        "feed; retired from derived timeframes by plan 18's backfill rework (the live "
        "path is dormant while the IBKR feed is down)."
    ),
    "services/bar_auditor.py": (
        "TEMPORARY: UPDATE market_data_ohlcv AS m writes price_sanity_status audit "
        "verdicts; moves to its own audited surface in plan 18's backfill rework."
    ),
    "scripts/ops/corpus/ops_known_corrupt_print_cleanup.py": (
        "TEMPORARY: UPDATE market_data_ohlcv sets price_sanity_status on the known-corrupt "
        "print set (one-time corpus cleanup); retired with the bar_auditor write path in "
        "plan 18's backfill rework."
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
            "After phase 185 plan 11, services/bar_derivation.py is the only permanent "
            "writer of derived 15m/1h (later 1d) rows. If this is a genuine new write "
            "path, add it to _ALLOW_LIST in this file with a PERMANENT/TEMPORARY reason "
            "naming the plan that owns or retires it."
        ),
    )


def test_writer_allow_list_has_no_stale_entries():
    hits = _find_writer_references()
    assert_allow_list_has_no_stale_entries(hits, _ALLOW_LIST)
