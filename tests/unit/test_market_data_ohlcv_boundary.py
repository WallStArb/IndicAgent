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

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent.parent
_RAW_TABLE_PATTERN = re.compile(r"FROM\s+market_data_ohlcv\b(?!_tradeable)")
_SEARCH_DIRS = ("services", "src", "scripts")

# (file, reason) -- every raw `market_data_ohlcv` reference in the tree must appear here.
# Adding a new call site requires adding a row here with a real reason, not just silencing
# the test.
_ALLOW_LIST: dict[str, str] = {
    "services/signal_replay_auditor.py": (
        "Dead v2.x Signal Ledger Architecture code (signal_ledger) -- CLAUDE.md documents "
        "this tier as archived, no live consumer since 2026-07-02. Verified 2026-07-16: no "
        "running systemd unit, signal_events/trade_frames have zero rows. Not fixed -- "
        "v2.x's fate is todo 056's separate open question, not this guard's call."
    ),
    "services/signal_probe_auditor.py": (
        "Dead v2.x Signal Ledger Architecture code (signal_events/trade_frames) -- same "
        "verification as signal_replay_auditor.py above."
    ),
    "services/equity_regime_model.py": (
        "Dead code -- Phase 144 rollback path only (services/cross_sectional_regime_model.py "
        "is the live replacement), not currently invoked by the corpus pipeline."
    ),
    "services/backfill_feature_factory.py": (
        "Already correctly filters with `volume > 0` (confirmed correct via empirical audit "
        "2026-07-16, not migrated to the view yet -- Tier-2 follow-up, todo 123's sibling "
        "audit list)."
    ),
    "services/regime_writer.py": (
        "Already correctly filters with `volume > 0` -- same Tier-2 follow-up as above."
    ),
    "services/forward_return_writer.py": (
        "Already correctly filters with `volume > 0` -- same Tier-2 follow-up as above."
    ),
    "services/bar_replay_provider.py": (
        "Not yet classified -- Tier-2 audit follow-up (see design doc's 'not yet classified' "
        "list, 2026-07-16)."
    ),
    "scripts/ops/roll/ops_roll_batch.py": ("Not yet classified -- Tier-2 audit follow-up."),
    "scripts/infrastructure/backfill/infrastructure_fetch_htf_bars.py": (
        "Not yet classified -- Tier-2 audit follow-up."
    ),
    "src/providers/base_provider_agent.py": (
        "Not yet classified -- likely wants the full calendar grid intentionally (backfill "
        "completeness count against the calendar target), but not verified. Tier-2 follow-up."
    ),
    "src/intelligence/services/bar_history_seeder.py": (
        "Not yet classified -- Tier-2 audit follow-up."
    ),
    "scripts/ops/pipeline/ops_pipeline_status.py": (
        "Monitoring wants the full grid -- gaps are the signal here, not noise. Correctly "
        "left alone (design doc's 'correctly left alone' list)."
    ),
    "scripts/infrastructure/backfill/infrastructure_context_features_writer.py": (
        "Not yet classified -- Tier-2 audit follow-up."
    ),
    "scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py": (
        "Backfill bookkeeping (min/max timestamp checks) against the full calendar grid -- "
        "plausibly intentional, not verified. Tier-2 audit follow-up."
    ),
    "scripts/debug/analysis/debug_bic_k_selection.py": ("Debug tooling -- Tier-2 audit follow-up."),
    "scripts/debug/replay/debug_lifecycle_replay.py": ("Debug tooling -- Tier-2 audit follow-up."),
    "scripts/analysis/crowding_proxy_regression.py": (
        "Standing diagnostic script, not a live gate -- Tier-2 audit follow-up."
    ),
    "src/persistence/repository/feature_snapshot_repository.py": (
        "Not yet classified -- Tier-2 audit follow-up."
    ),
    "src/api/routes/market_data.py": (
        "Raw display/API surface, not a measurement input -- correctly left alone (design "
        "doc's 'correctly left alone' list)."
    ),
}


def _find_raw_table_references() -> dict[str, int]:
    """Returns {relative_path: match_count} for every .py file under _SEARCH_DIRS that
    references the raw market_data_ohlcv table (not the _tradeable view)."""
    hits: dict[str, int] = {}
    for search_dir in _SEARCH_DIRS:
        for path in (_REPO_ROOT / search_dir).rglob("*.py"):
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
