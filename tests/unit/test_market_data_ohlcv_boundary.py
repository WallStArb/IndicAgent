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
    "services/signal_replay_auditor.py": (
        "PERMANENT: Dead v2.x Signal Ledger Architecture code (signal_ledger) -- CLAUDE.md "
        "documents this tier as archived, no live consumer since 2026-07-02. Verified "
        "2026-07-16: no running systemd unit, signal_events/trade_frames have zero rows. Not "
        "fixed -- v2.x's fate is todo 056's separate open question, not this guard's call."
    ),
    "services/signal_probe_auditor.py": (
        "PERMANENT: Dead v2.x Signal Ledger Architecture code (signal_events/trade_frames) -- "
        "same verification as signal_replay_auditor.py above."
    ),
    "scripts/ops/pipeline/ops_pipeline_status.py": (
        "PERMANENT: Monitoring wants the full grid -- gaps are the signal here, not noise. "
        "Correctly left alone (design doc's 'correctly left alone' list)."
    ),
    "scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py": (
        "PERMANENT: the min(timestamp) gap-reorder query reads the tradeable view (todo 124); "
        "the remaining raw-table reads (_detect_gaps and the INSERT/UPSERT writer paths) treat "
        "any stored slot, zero-volume provider bars included, as already answered, so a closed "
        "slot is not re-requested from IBKR forever; the tradeable view's volume > 0 filter "
        "would break that. The store holds real rows only since plan 185-25, and plan 185-32 "
        "deleted the --normalize pass and the last placeholder path (migration 444 refuses "
        "synthetic_fill)."
    ),
    "scripts/infrastructure/backfill/_d1_gaps.py": (
        "PERMANENT (todo 462, plan 185-18): reads stored slot timestamps for gap planning "
        "(zero-volume provider bars count as covered, which the tradeable view's WHERE "
        "volume > 0 filter would drop and turn into endless re-requests) and checks that a "
        "`bars` ohlcv_request answer has at least one stored row in its window, so a failed "
        "bar insert never leaves a window that looks covered."
    ),
    "services/bar_reconciliation_audit.py": (
        "PERMANENT: D7 counts rows by source, including sources the tradeable view hides "
        "(D-26); its completeness and masked-slot checks (todo 462) classify placeholder and "
        "zero-volume rows, and its late-heads check reads the earliest canonical row of any "
        "real source."
    ),
    "scripts/infrastructure/backfill/infrastructure_run_tradier_daily.py": (
        "PERMANENT (phase 185, Tradier primary 1d source): the loader writes canonical 1d rows "
        "and diffs them against the existing rows of every real source, zero-volume provider "
        "bars included, to record revisions and gate a source change; the tradeable view would "
        "hide those rows and turn a revision into a silent new bar."
    ),
    "scripts/ops/bars/ops_tradier_lineage_backfill.py": (
        "ONE-TIME (plan 185-30): the 1d lineage, digest and legacy-flag repair counts every "
        "stored canonical 1d bar, zero-volume provider bars included, and joins a legacy flag "
        "to its stored bar's source; lineage and digests cover those rows, so the tradeable "
        "view would hide exactly the bars being traced."
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
    "scripts/ops/bars/ops_masked_slot_baseline.py": (
        "PERMANENT (todo 462, plan 185-12): counts the synthetic_fill rows of a coarse timeframe "
        "and compares them with the tradeable 5m volume over the same slots; the synthetic rows "
        "are the thing measured, so the tradeable view (which hides them) cannot be the source."
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
    "scripts/debug/analysis/debug_batch_agent_memory.py": (
        "PERMANENT: Joins signal_ledger, confirmed zero rows in the live DB -- dead v2.x "
        "Signal Ledger Architecture code, same bucket as "
        "signal_probe_auditor.py/signal_replay_auditor.py already on this allow-list."
    ),
    "scripts/infrastructure/backfill/infrastructure_truncate_derived_tables.sh": (
        "PERMANENT: Re-seeds backfill_status bookkeeping from the full calendar grid after a "
        "truncate -- intentionally wants the complete grid (including placeholder bars) to "
        "correctly mark what calendar coverage has been backfilled, not just tradeable bars."
    ),
    "scripts/ops/bars/ops_export_known_answer_fixtures.py": (
        "PERMANENT: exports price_sanity_status rows, including confirmed_corrupt ones the "
        "tradeable view hides, as phase 185 known-answer fixtures (D-10); read-only"
    ),
    "services/bar_derivation.py": (
        "PERMANENT: the derivation archives and replaces stored 15m/1h rows and later "
        "writes canonical 1d; it must address the raw table (D-06, D-15). The archive "
        "INSERT ... SELECT, the archive checksum verify and the segment DELETE all "
        "operate on exactly the stored segment being replaced, placeholders included -- "
        "the tradeable view's WHERE volume > 0 filter would hide the placeholder rows "
        "the DELETE must remove and skew the checksums."
    ),
    "scripts/ops/bars/ops_real_rows_swap.py": (
        "PERMANENT until the swap lands (todo 462 step 6, plan 185-25): the real-rows swap "
        "compares the raw table's real rows (source IS DISTINCT FROM 'synthetic_fill', "
        "zero-volume provider bars included) with the new table's per (symbol, timeframe); the "
        "tradeable view would hide zero-volume real rows and let a lost one pass the digest."
    ),
    "services/intraday_raw_archive.py": (
        "PERMANENT: the archive's single owner module (plan 12). Its "
        "ARCHIVE_FROM_TABLE_SQL is bar_derivation's INSERT ... SELECT moved here "
        "byte-identical; it reads exactly the stored 15m/1h segment being archived, "
        "placeholders excluded by source <> 'synthetic_fill'."
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
