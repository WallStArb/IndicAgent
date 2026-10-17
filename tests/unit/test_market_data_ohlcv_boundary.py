"""CI guard: no new raw `market_data_ohlcv` reads outside this checked-in allow-list.

market_data_ohlcv is a continuous calendar grid containing synthetic-fill and IBKR
flat-carry-forward placeholder bars (see docs/plans/2026-07-16-market-data-ohlcv-active-
bars-boundary-design.md). Three separate files independently reintroduced this exact gap
over three weeks before this guard existed. A new file reading the raw table now fails CI
immediately unless this allow-list is also edited -- which forces a "why does this need
raw access" justification into the diff itself, at review time, rather than relying on
someone remembering to add `market_data_ohlcv_tradeable` to a FROM clause.

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
_RAW_TABLE_PATTERN = re.compile(r"\b(?:FROM|JOIN)\s+market_data_ohlcv\b(?!_tradeable)")
_SEARCH_DIRS = ("services", "src", "scripts")

# (file, reason) -- every raw `market_data_ohlcv` reference in the tree must appear here.
# Adding a new call site requires adding a row here with a real reason, not just silencing
# the test.
_ALLOW_LIST: dict[str, str] = {
    "services/bar_selection.py": (
        "PERMANENT (phase 191 plan 02): the canonical selection writer compares each selected "
        "raw row with the stored canonical row of the same slot, zero-volume provider bars "
        "included; the tradeable view's volume > 0 filter would hide a stored zero-volume slot "
        "and re-write it as new on every run."
    ),
    "services/bar_reconciliation_audit.py": (
        "PERMANENT: D7 counts rows by source, including sources the tradeable view hides "
        "(D-26); its completeness and masked-slot checks (todo 462) classify placeholder and "
        "zero-volume rows, and its late-heads check reads the earliest canonical row of any "
        "real source."
    ),
    "scripts/ops/bars/ops_raw_backfill.py": (
        "TEMPORARY retire: 191-17 (one-shot backfill, deleted at close). Reads the raw canonical "
        "table because the backfill copies every vendor-labelled row, volume 0 included."
    ),
    "scripts/ops/bars/ops_canonical_vendor_kind_swap.py": (
        "TEMPORARY retire: 191-17 (one-shot rebuild, deleted at close). Copies the raw canonical "
        "table into market_data_ohlcv_v2 with the vendor/kind mapping and proves it equal: every "
        "row must be compared, zero-volume provider bars included, or the proof would pass while "
        "hiding rows the tradeable view filters."
    ),
    "scripts/ops/bars/ops_d2_raw_equivalence.py": (
        "TEMPORARY retire: 191-17 (one-shot equivalence check, deleted at close). Compares the "
        "daily rule over raw with every stored canonical 1d row, zero-volume rows included."
    ),
    "scripts/ops/bars/ops_truncated_bar_scan.py": (
        "PERMANENT: the read-only truncated-bar scan reports whether canonical holds a candidate "
        "bar (a reselect promotes a truncated raw bar), zero-volume rows included (191-07)."
    ),
    "scripts/ops/bars/ops_selection_gate.py": (
        "PERMANENT: standing proof that canonical is a pure function of raw plus policy (191-07). "
        "It compares every canonical vendor row, zero-volume provider bars included, with the "
        "selection of ohlcv_raw; the tradeable view's volume > 0 filter would hide the very rows "
        "the proof must equal."
    ),
    "scripts/ops/bars/ops_source_policy.py": (
        "PERMANENT (plan 185-38): the admission sweep asks whether a name's canonical 1d series "
        "is Tradier today (any stored tradier 1d row, zero-volume provider bars included); the "
        "tradeable view would hide a name whose only Tradier rows are zero-volume or quarantined "
        "and misclassify an incumbent as never-Tradier."
    ),
    "scripts/ops/bars/ops_data_bar_check.py": (
        "PERMANENT (plan 185-34): the D-28 gate judges each known-answer key by its stored row "
        "(source and the pre-381 price_sanity_status), keyed by the 87 fixed keys only; the "
        "tradeable view also hides a bar by that stale status, which would misread a bar "
        "Tradier replaced as missing. Every other gate read uses the tradeable view."
    ),
    "scripts/infrastructure/backfill/infrastructure_ibkr_chunk_and_rate_limit_probe.py": (
        "PERMANENT: _pick_probe_symbols checks whether a (symbol, timeframe) has ANY row at "
        "all -- including synthetic-fill placeholders -- to pick a genuinely never-backfilled "
        "candidate for a real IBKR test fetch. market_data_ohlcv_tradeable's WHERE volume > 0 "
        "filter would give a wrong answer here: a symbol could have placeholder bars (volume=0) "
        "and zero real tradeable bars, which this check must still treat as 'has data.'"
    ),
    "src/api/routes/market_data.py": (
        "PERMANENT: Raw display/API surface, not a measurement input -- correctly left alone "
        "(design doc's 'correctly left alone' list)."
    ),
    "services/bar_auditor.py": (
        "PERMANENT: Legitimate gap-detection auditor (registered live in service_auditor.py's "
        "DAG as bar_auditor -> indicagent-bar-auditor) -- deliberately counts ALL rows "
        "including synthetic-fill placeholders to detect actual calendar gaps and trigger "
        "backfill. Filtering here would break its purpose.\n"
        "PERMANENT (todo 149): _PRICE_SANITY_CANDIDATES_SQL's `candidates` CTE reads the "
        "raw table deliberately -- this query IS the price-sanity audit watermark "
        "(`price_sanity_status IS NULL`), gated by a dedicated partial index "
        "(idx_market_data_ohlcv_price_sanity_unaudited, migration 242) for deterministic "
        "query-plan usage on a query that runs every 5-minute audit cycle, rather than "
        "relying on the tradeable view's inlining behavior for a hot path. The subsequent "
        "`JOIN market_data_ohlcv o` fetching the candidate's own OHLC fields is the same "
        "deliberate raw-table read for the same watermark reason (it must see the exact "
        "row the CTE just selected, including its NULL price_sanity_status, not the "
        "tradeable view's filtered subset). Its LATERAL prev/next neighbor joins DO read "
        "market_data_ohlcv_tradeable, not the raw table."
    ),
    "scripts/ops/bars/ops_export_known_answer_fixtures.py": (
        "PERMANENT: exports price_sanity_status rows, including confirmed_corrupt ones the "
        "tradeable view hides, as phase 185 known-answer fixtures (D-10); read-only"
    ),
    "services/bar_derivation.py": (
        "PERMANENT: the single writer of the 15m/1h grid and canonical 1d (D-06, D-15); its "
        "write contract classifies against every stored row of those timeframes, so it must "
        "address the table, not the tradeable view, whose volume > 0 filter would hide "
        "stored rows the contract must see (a vendor grid row fails the stage loud)."
    ),
}


@functools.lru_cache(maxsize=1)
def _find_raw_table_references() -> dict[str, int]:
    """Returns {relative_path: match_count} for every .py/.sh file under _SEARCH_DIRS that
    references the raw market_data_ohlcv table (not the _tradeable view)."""
    return find_pattern_references(
        _REPO_ROOT, _SEARCH_DIRS, _RAW_TABLE_PATTERN, file_globs=("*.py", "*.sh")
    )


def test_every_raw_market_data_ohlcv_reference_is_on_the_allow_list():
    hits = _find_raw_table_references()
    assert_no_unlisted_references(
        hits,
        _ALLOW_LIST,
        what="raw `market_data_ohlcv` read(s)",
        remedy=(
            "If this is a genuine new call site, either point it at "
            "`market_data_ohlcv_tradeable` (preferred, if it needs tradeable bars only) or "
            "add it to _ALLOW_LIST in this file with a one-line reason (if it genuinely "
            "needs the full calendar grid)."
        ),
    )


def test_allow_list_has_no_stale_entries():
    hits = _find_raw_table_references()
    assert_allow_list_has_no_stale_entries(hits, _ALLOW_LIST)
