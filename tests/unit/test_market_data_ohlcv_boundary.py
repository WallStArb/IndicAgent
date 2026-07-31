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
    "services/equity_regime_model.py": (
        "PERMANENT: Dead code -- Phase 144 rollback path only "
        "(services/cross_sectional_regime_model.py is the live replacement), not currently "
        "invoked by the corpus pipeline."
    ),
    "scripts/ops/pipeline/ops_pipeline_status.py": (
        "PERMANENT: Monitoring wants the full grid -- gaps are the signal here, not noise. "
        "Correctly left alone (design doc's 'correctly left alone' list)."
    ),
    "scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py": (
        "PERMANENT + PENDING mix, resolved 2026-07-31 (todo 124): the min(timestamp) gap-"
        "reorder query migrated to the tradeable view (behaviorally identical either way --\n"
        "normalize_bars() never fabricates a synthetic fill before a symbol's first real "
        "bar). The remaining raw-table reads (_detect_gaps, the INSERT/UPSERT writer paths, "
        "run_normalize's own fetch_bars/store_bars) are PERMANENT and intentional: this "
        "script both creates AND consumes its own synthetic fills as a self-consistent "
        "'calendar slot already handled' bookkeeping system -- _detect_gaps deliberately "
        "treats a prior synthetic fill as 'already there' so a genuinely-closed weekend/"
        "holiday slot isn't re-requested from IBKR forever. Its own comments (the "
        "'[rca_analysis 2026-07-05, F1/F2]' block) confirm this is deliberate design, not an "
        "oversight -- migrating these to the tradeable view would break the idempotent "
        "re-run behavior the tool depends on."
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
    "scripts/infrastructure/backfill/infrastructure_backfill_progress_check.sh": (
        "PERMANENT: Backfill progress monitor -- COUNT(*) GROUP BY timeframe against the full "
        "calendar grid is the intended behavior (tracking calendar completeness, not "
        "tradeable-bar count), same rationale as the already-allow-listed "
        "ops_pipeline_status.py."
    ),
    "scripts/infrastructure/backfill/infrastructure_truncate_derived_tables.sh": (
        "PERMANENT: Re-seeds backfill_status bookkeeping from the full calendar grid after a "
        "truncate -- intentionally wants the complete grid (including placeholder bars) to "
        "correctly mark what calendar coverage has been backfilled, not just tradeable bars."
    ),
}


@functools.lru_cache(maxsize=1)
def _find_raw_table_references() -> dict[str, int]:
    """Returns {relative_path: match_count} for every .py/.sh file under _SEARCH_DIRS that
    references the raw market_data_ohlcv table (not the _tradeable view)."""
    hits: dict[str, int] = {}
    for search_dir in _SEARCH_DIRS:
        for pattern in ("*.py", "*.sh"):
            for path in (_REPO_ROOT / search_dir).rglob(pattern):
                text = path.read_text(encoding="utf-8", errors="ignore")
                count = len(_RAW_TABLE_PATTERN.findall(text))
                if count:
                    hits[str(path.relative_to(_REPO_ROOT))] = count
    return hits


def test_every_raw_market_data_ohlcv_reference_is_on_the_allow_list():
    hits = _find_raw_table_references()
    unexpected = set(hits) - set(_ALLOW_LIST)
    assert not unexpected, (
        f"New raw `market_data_ohlcv` read(s) found, not on the allow-list: {unexpected}. "
        "If this is a genuine new call site, either point it at "
        "`market_data_ohlcv_tradeable` (preferred, if it needs tradeable bars only) or add "
        "it to _ALLOW_LIST in this file with a one-line reason (if it genuinely needs the "
        "full calendar grid)."
    )


def test_allow_list_has_no_stale_entries():
    hits = _find_raw_table_references()
    stale = set(_ALLOW_LIST) - set(hits)
    assert not stale, (
        f"Allow-list entries that no longer match any raw `market_data_ohlcv` reference: "
        f"{stale}. Either the file was fixed (remove its entry here) or moved/renamed "
        "(update the path)."
    )
